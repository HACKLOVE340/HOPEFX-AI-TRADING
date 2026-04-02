# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/orchestrator.py
====================================
Training orchestrator and evaluation harness.

Responsibilities
----------------
1. Coordinate data ingestion → feature engineering → MTF fusion → model training
2. Enforce strict temporal train/val/test splits (no shuffling across time)
3. Train both the deep model (LSTM/Transformer/TCN) and the ensemble (XGB stack)
4. Combine their predictions via a learned meta-weight (late fusion)
5. Produce a standardised evaluation report: AUC, precision, recall, Sharpe,
   max drawdown, hit-rate, and a confusion matrix
6. Persist all artefacts under ml/saved_models/pipeline/

Temporal split convention
--------------------------
  |─── train (70%) ───|── val (15%) ──|── test (15%) ──|
  No data from val/test ever touches training.
  Val is used for early stopping and hyperparameter search.
  Test is touched exactly once for final reporting.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

from research.pipeline.data_ingestion import (
    attach_sentiment,
    fetch_daily,
    fetch_intraday,
    fetch_rss_sentiment,
)
from research.pipeline.feature_engineering import build_feature_matrix, add_targets
from research.pipeline.mtf_fusion import MTFFusion
from research.pipeline.models_deep import DeepPredictor, make_sequences
from research.pipeline.models_ensemble import EnsemblePredictor
from research.pipeline.anomaly import AnomalyWeighter
from research.pipeline.synthetic import RegimeSynthesizer, label_regimes
from research.pipeline.online_learning import IncrementalXGBoost, DriftDetector
from research.pipeline.regime_models import RegimeRouter

logger = logging.getLogger(__name__)

ARTEFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "saved_models" / "pipeline"
ARTEFACT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Config dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PipelineConfig:
    ticker: str = "GC=F"  # Gold futures (Yahoo Finance) — primary HOPEFX instrument
    interval: str = "1d"  # '1d', '5m', '15m', '1h'
    start_date: str = "2000-01-01"
    lookback_days: int = 730  # for intraday
    horizon: int = 1  # bars ahead to predict
    threshold: float = 0.001  # min return to label as directional
    seq_len: int = 60  # LSTM/Transformer look-back window
    deep_arch: str = "lstm"  # 'lstm' | 'transformer' | 'tcn'
    deep_epochs: int = 100
    deep_patience: int = 15
    ensemble_tune_trials: int = 30
    n_cv_splits: int = 5
    train_frac: float = 0.70
    val_frac: float = 0.15
    # test_frac is implied: 1 - train_frac - val_frac
    use_mtf: bool = True  # enrich intraday with daily context
    use_sentiment: bool = True
    use_cache: bool = True
    device: str = "auto"
    # ── Extension flags ───────────────────────────────────────────────────────
    use_anomaly_weighting: bool = True  # IsolationForest sample weights
    use_synthetic_augment: bool = False  # TimeGAN augmentation (slow; off by default)
    synthetic_epochs: int = 200  # TimeGAN training epochs
    use_regime_routing: bool = True  # Per-regime specialist models
    use_online_learning: bool = False  # IncrementalXGBoost live updates
    anomaly_contamination: float = 0.02  # Expected anomaly fraction
    n_regimes: int = 3  # Volatility regime count


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation helpers
# ─────────────────────────────────────────────────────────────────────────────


def _sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float:
    """Annualised Sharpe ratio of a return series."""
    if returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def _max_drawdown(equity: np.ndarray) -> float:
    """Maximum peak-to-trough drawdown of an equity curve."""
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak == 0, 1, peak)
    return float(dd.min())


def _strategy_returns(
    probs: np.ndarray,
    actual_returns: np.ndarray,
    threshold: float = 0.5,
) -> np.ndarray:
    """
    Simple long-only strategy: go long when prob > threshold, else flat.
    Returns per-bar strategy returns.
    """
    signal = (probs > threshold).astype(float)
    return signal * actual_returns


def evaluate_predictions(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    actual_returns: np.ndarray | None = None,
    threshold: float = 0.5,
    periods_per_year: int = 252,
) -> dict:
    """
    Full evaluation suite.

    Returns dict with classification metrics + optional strategy metrics.
    """
    y_pred = (y_prob >= threshold).astype(int)

    report = {
        "auc": float(roc_auc_score(y_true, y_prob)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "classification_report": classification_report(y_true, y_pred, output_dict=True),
    }

    if actual_returns is not None:
        strat_ret = _strategy_returns(y_prob, actual_returns, threshold)
        equity = np.cumprod(1 + strat_ret)
        report["strategy_sharpe"] = _sharpe(strat_ret, periods_per_year)
        report["strategy_max_drawdown"] = _max_drawdown(equity)
        report["strategy_total_return"] = float(equity[-1] - 1) if len(equity) > 0 else 0.0
        report["hit_rate"] = float((strat_ret > 0).mean())

    return report


# ─────────────────────────────────────────────────────────────────────────────
# Temporal split
# ─────────────────────────────────────────────────────────────────────────────


def temporal_split(
    df: pd.DataFrame,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


# ─────────────────────────────────────────────────────────────────────────────
# Late-fusion meta-weight
# ─────────────────────────────────────────────────────────────────────────────


def _learn_meta_weight(
    deep_probs_val: np.ndarray,
    ens_probs_val: np.ndarray,
    y_val: np.ndarray,
) -> float:
    """
    Grid-search the scalar weight w such that:
        final_prob = w * deep_prob + (1-w) * ens_prob
    maximises AUC on the validation set.
    """
    best_w, best_auc = 0.5, -1.0
    for w in np.linspace(0, 1, 21):
        combined = w * deep_probs_val + (1 - w) * ens_probs_val
        try:
            auc = roc_auc_score(y_val, combined)
        except Exception:  # nosec B112 - skip weight if AUC computation fails
            continue
        if auc > best_auc:
            best_auc = auc
            best_w = w
    logger.info(
        "Meta-weight: deep=%.2f  ensemble=%.2f  val_AUC=%.4f",
        best_w,
        1 - best_w,
        best_auc,
    )
    return float(best_w)


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class PipelineOrchestrator:
    """
    End-to-end pipeline: data → features → models → evaluation → artefacts.

    Usage
    -----
        cfg = PipelineConfig(ticker="GC=F", interval="1d", start_date="2000-01-01")
        orch = PipelineOrchestrator(cfg)
        report = orch.run()
        print(report)
    """

    def __init__(self, config: PipelineConfig):
        self.cfg = config
        self.deep_model: DeepPredictor | None = None
        self.ensemble: EnsemblePredictor | None = None
        self.regime_router: RegimeRouter | None = None
        self.anomaly_weighter: AnomalyWeighter | None = None
        self.synthesizer: RegimeSynthesizer | None = None
        self.incremental_xgb: IncrementalXGBoost | None = None
        self.drift_detector: DriftDetector | None = None
        self.meta_weight: float = 0.5
        self.scaler = StandardScaler()
        self._feature_cols: list[str] | None = None

    # ── Step 1: Data ──────────────────────────────────────────────────────────

    def _load_data(self) -> pd.DataFrame:
        cfg = self.cfg
        logger.info("Loading data: %s @ %s", cfg.ticker, cfg.interval)

        if cfg.interval == "1d":
            df = fetch_daily(cfg.ticker, start=cfg.start_date, use_cache=cfg.use_cache)
        else:
            df = fetch_intraday(
                cfg.ticker,
                interval=cfg.interval,
                lookback_days=cfg.lookback_days,
                use_cache=cfg.use_cache,
            )

        if df.empty:
            raise ValueError(f"No data returned for {cfg.ticker} @ {cfg.interval}")

        # Attach sentiment
        if cfg.use_sentiment:
            try:
                sent = fetch_rss_sentiment(cfg.ticker)
                resample_window = "1D" if cfg.interval == "1d" else "1h"
                df = attach_sentiment(df, sent, window=resample_window)
            except Exception as exc:
                logger.warning("Sentiment fetch failed: %s", exc)

        return df

    # ── Step 2: Features ──────────────────────────────────────────────────────

    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self.cfg
        logger.info("Building feature matrix...")

        # MTF enrichment for intraday
        if cfg.use_mtf and cfg.interval != "1d":
            daily_df = fetch_daily(cfg.ticker, start=cfg.start_date, use_cache=cfg.use_cache)
            fusion = MTFFusion(resample_hourly_from_5m=True)
            df = fusion.enrich(intraday_df=df, daily_df=daily_df)

        feat_df = build_feature_matrix(df, drop_na=True)
        feat_df = add_targets(feat_df, horizon=cfg.horizon, threshold=cfg.threshold)

        # Drop rows where target is NaN (last `horizon` rows)
        feat_df.dropna(subset=["target_bin", "target_ret"], inplace=True)

        logger.info("Feature matrix: %d rows × %d cols", *feat_df.shape)
        return feat_df

    # ── Step 3: Split ─────────────────────────────────────────────────────────

    def _split(self, feat_df: pd.DataFrame):
        train, val, test = temporal_split(feat_df, self.cfg.train_frac, self.cfg.val_frac)
        logger.info(
            "Split: train=%d  val=%d  test=%d",
            len(train),
            len(val),
            len(test),
        )
        return train, val, test

    # ── Step 4: Prepare arrays ────────────────────────────────────────────────

    def _prepare_arrays(self, split_df: pd.DataFrame):
        """Return (X_df, y_bin, y_ret) for a split."""
        drop_cols = [
            c
            for c in split_df.columns
            if c.startswith("target") or c in ("is_forward_filled", "is_synthetic", "category")
        ]
        X = split_df.drop(columns=drop_cols, errors="ignore")
        y_bin = split_df["target_bin"].values
        y_ret = split_df["target_ret"].values
        return X, y_bin, y_ret

    # ── Step 5: Train deep model ──────────────────────────────────────────────

    def _train_deep(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> DeepPredictor:
        cfg = self.cfg
        n_features = X_train.shape[1]

        X_tr_seq, y_tr_seq = make_sequences(X_train, y_train, cfg.seq_len)
        X_val_seq, y_val_seq = make_sequences(X_val, y_val, cfg.seq_len)

        logger.info(
            "Training %s: seq_shape=%s  n_features=%d",
            cfg.deep_arch,
            X_tr_seq.shape,
            n_features,
        )

        model = DeepPredictor(
            architecture=cfg.deep_arch,
            n_features=n_features,
            seq_len=cfg.seq_len,
            task="binary",
            device=cfg.device,
            max_epochs=cfg.deep_epochs,
            patience=cfg.deep_patience,
        )
        model.fit(X_tr_seq, y_tr_seq, X_val_seq, y_val_seq)
        return model

    # ── Step 5b: Anomaly weighting ────────────────────────────────────────────

    def _fit_anomaly_weighter(self, X_train: pd.DataFrame) -> AnomalyWeighter:
        aw = AnomalyWeighter(contamination=self.cfg.anomaly_contamination)
        aw.fit(X_train)
        return aw

    # ── Step 5c: Synthetic augmentation ──────────────────────────────────────

    def _augment_with_synthetic(
        self,
        X_train: pd.DataFrame,
        y_train: np.ndarray,
    ) -> tuple[pd.DataFrame, np.ndarray]:
        cfg = self.cfg
        logger.info("Fitting TimeGAN synthesizer (epochs=%d)…", cfg.synthetic_epochs)
        regime_labels = label_regimes(X_train, n_regimes=cfg.n_regimes)
        synth = RegimeSynthesizer(
            seq_len=min(cfg.seq_len, 32),
            n_features=X_train.shape[1],
            n_regimes=cfg.n_regimes,
            device=cfg.device,
        )
        synth.fit(X_train.values, regime_labels, epochs=cfg.synthetic_epochs)
        self.synthesizer = synth

        # Augment the rarest regime (highest vol = index n_regimes-1)
        X_aug, labels_aug = synth.augment_rare_regimes(
            X_train.values,
            regime_labels,
            target_regime=cfg.n_regimes - 1,
            multiplier=2.0,
        )
        # Rebuild y_train for augmented rows (use majority label of rare regime)
        rare_mask = regime_labels == (cfg.n_regimes - 1)
        rare_label = int(np.round(y_train[rare_mask].mean())) if rare_mask.any() else 0
        n_new = len(X_aug) - len(X_train)
        y_aug = np.concatenate([y_train, np.full(n_new, rare_label)])
        X_aug_df = pd.DataFrame(X_aug, columns=X_train.columns)
        logger.info("Augmented training set: %d → %d samples", len(X_train), len(X_aug_df))
        return X_aug_df, y_aug

    # ── Step 6: Train ensemble ────────────────────────────────────────────────

    def _train_ensemble(
        self,
        X_train: pd.DataFrame,
        y_train: np.ndarray,
        sample_weights: np.ndarray | None = None,
    ) -> EnsemblePredictor:
        ens = EnsemblePredictor(
            tune_trials=self.cfg.ensemble_tune_trials,
            n_cv_splits=self.cfg.n_cv_splits,
        )
        # EnsemblePredictor.fit accepts sample_weight via sklearn's fit interface
        ens.fit(X_train, y_train)
        return ens

    # ── Step 6b: Train regime router ─────────────────────────────────────────

    def _train_regime_router(
        self,
        X_train: pd.DataFrame,
        y_train: np.ndarray,
    ) -> RegimeRouter:
        router = RegimeRouter(n_regimes=self.cfg.n_regimes, soft_routing=True)
        router.fit(X_train, y_train)
        return router

    # ── Step 6c: Init incremental XGBoost ────────────────────────────────────

    def _init_incremental_xgb(
        self,
        X_train: pd.DataFrame,
        y_train: np.ndarray,
    ) -> IncrementalXGBoost:
        inc = IncrementalXGBoost(n_base_rounds=200, n_new_rounds=20)
        inc.fit(X_train, y_train)
        return inc

    # ── Step 7: Evaluate ──────────────────────────────────────────────────────

    def _evaluate(
        self,
        split_name: str,
        X_df: pd.DataFrame,
        X_scaled: np.ndarray,
        y_bin: np.ndarray,
        y_ret: np.ndarray,
    ) -> dict:
        cfg = self.cfg

        # Deep predictions
        X_seq, y_seq = make_sequences(X_scaled, y_bin, cfg.seq_len)
        deep_probs = self.deep_model.predict(X_seq)

        # Ensemble predictions — blend standard ensemble + regime router
        ens_base = self.ensemble.predict_proba(X_df.iloc[cfg.seq_len :])
        if self.regime_router is not None:
            try:
                regime_probs = self.regime_router.predict_proba(X_df.iloc[cfg.seq_len :])
                ens_probs = 0.6 * ens_base + 0.4 * regime_probs
            except Exception as exc:
                logger.warning("Regime router predict failed: %s", exc)
                ens_probs = ens_base
        else:
            ens_probs = ens_base

        # Align lengths
        min_len = min(len(deep_probs), len(ens_probs))
        deep_probs = deep_probs[-min_len:]
        ens_probs = ens_probs[-min_len:]
        y_eval = y_seq[-min_len:]
        y_ret_eval = y_ret[cfg.seq_len :][-min_len:]

        # Late fusion
        final_probs = self.meta_weight * deep_probs + (1 - self.meta_weight) * ens_probs

        periods = 252 if cfg.interval == "1d" else (252 * 78 if "5m" in cfg.interval else 252 * 26)

        report = evaluate_predictions(
            y_true=y_eval,
            y_prob=final_probs,
            actual_returns=y_ret_eval,
            periods_per_year=periods,
        )
        report["split"] = split_name
        report["n_samples"] = int(min_len)

        logger.info(
            "%s  AUC=%.4f  Acc=%.4f  F1=%.4f  Sharpe=%.2f  MaxDD=%.2f%%",
            split_name,
            report["auc"],
            report["accuracy"],
            report["f1"],
            report.get("strategy_sharpe", 0),
            report.get("strategy_max_drawdown", 0) * 100,
        )
        return report

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Execute the full pipeline and return an evaluation report dict.
        """
        cfg = self.cfg
        run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        logger.info("Pipeline run %s  ticker=%s  interval=%s", run_id, cfg.ticker, cfg.interval)

        # 1. Data
        raw_df = self._load_data()

        # 2. Features
        feat_df = self._build_features(raw_df)

        # 3. Split
        train_df, val_df, test_df = self._split(feat_df)

        # 4. Arrays
        X_train_df, y_train, y_train_ret = self._prepare_arrays(train_df)
        X_val_df, y_val, y_val_ret = self._prepare_arrays(val_df)
        X_test_df, y_test, y_test_ret = self._prepare_arrays(test_df)

        self._feature_cols = list(X_train_df.columns)

        # 5. Scale (fit on train only)
        X_train_sc = self.scaler.fit_transform(X_train_df)
        X_val_sc = self.scaler.transform(X_val_df)
        X_test_sc = self.scaler.transform(X_test_df)

        # 5b. Anomaly weighting
        sample_weights = None
        if cfg.use_anomaly_weighting:
            self.anomaly_weighter = self._fit_anomaly_weighter(X_train_df)
            sample_weights = self.anomaly_weighter.sample_weights(X_train_df)
            n_anomalies = int(self.anomaly_weighter.flag(X_train_df).sum())
            logger.info("Anomaly weighting: %d anomalous bars down-weighted", n_anomalies)

        # 5c. Synthetic augmentation (optional — slow)
        X_train_aug, y_train_aug = X_train_df, y_train
        if cfg.use_synthetic_augment:
            X_train_aug, y_train_aug = self._augment_with_synthetic(X_train_df, y_train)
            # Re-scale augmented set
            X_train_sc = self.scaler.transform(X_train_aug)

        # 6. Train deep model
        self.deep_model = self._train_deep(X_train_sc, y_train_aug, X_val_sc, y_val)

        # 7. Train ensemble (standard) + regime router
        self.ensemble = self._train_ensemble(X_train_aug, y_train_aug, sample_weights)

        if cfg.use_regime_routing:
            self.regime_router = self._train_regime_router(X_train_aug, y_train_aug)

        # 7b. Init incremental XGBoost for online updates
        if cfg.use_online_learning:
            self.incremental_xgb = self._init_incremental_xgb(X_train_aug, y_train_aug)
            self.drift_detector = DriftDetector()

        # 8. Learn meta-weight on validation set
        X_val_seq, y_val_seq = make_sequences(X_val_sc, y_val, cfg.seq_len)
        deep_val_probs = self.deep_model.predict(X_val_seq)
        ens_val_probs = self.ensemble.predict_proba(X_val_df.iloc[cfg.seq_len :])
        min_len = min(len(deep_val_probs), len(ens_val_probs))
        self.meta_weight = _learn_meta_weight(
            deep_val_probs[-min_len:],
            ens_val_probs[-min_len:],
            y_val_seq[-min_len:],
        )

        # 9. Evaluate on val and test
        val_report = self._evaluate("val", X_val_df, X_val_sc, y_val, y_val_ret)
        test_report = self._evaluate("test", X_test_df, X_test_sc, y_test, y_test_ret)

        # 10. Save artefacts
        run_dir = ARTEFACT_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        self.deep_model.save(run_dir / "deep_model.pt")
        self.ensemble.save(run_dir / "ensemble.pkl")
        if self.regime_router is not None:
            self.regime_router.save(run_dir / "regime_router.pkl")
        if self.anomaly_weighter is not None:
            self.anomaly_weighter.save(run_dir / "anomaly_weighter.pkl")
        if self.synthesizer is not None:
            self.synthesizer.save(run_dir / "synthesizer.pt")
        if self.incremental_xgb is not None:
            self.incremental_xgb.save(run_dir / "incremental_xgb.pkl")

        meta = {
            "run_id": run_id,
            "config": asdict(cfg),
            "meta_weight": self.meta_weight,
            "feature_cols": self._feature_cols,
            "val_report": {k: v for k, v in val_report.items() if k != "classification_report"},
            "test_report": {k: v for k, v in test_report.items() if k != "classification_report"},
        }
        with open(run_dir / "run_meta.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

        logger.info("Artefacts saved → %s", run_dir)

        return {
            "run_id": run_id,
            "val": val_report,
            "test": test_report,
            "meta_weight": self.meta_weight,
            "artefact_dir": str(run_dir),
        }

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict_latest(self, df: pd.DataFrame) -> dict:
        """
        Run inference on the most recent bars of a live DataFrame.

        Returns
        -------
        dict with keys: deep_prob, ensemble_prob, final_prob, signal
        """
        if self.deep_model is None or self.ensemble is None:
            raise RuntimeError("Call run() or load artefacts before predict_latest()")

        feat_df = build_feature_matrix(df, drop_na=True)
        drop_cols = [
            c
            for c in feat_df.columns
            if c.startswith("target") or c in ("is_forward_filled", "is_synthetic", "category")
        ]
        X_df = feat_df.drop(columns=drop_cols, errors="ignore")[self._feature_cols]
        X_sc = self.scaler.transform(X_df)

        # Need at least seq_len bars
        if len(X_sc) < self.cfg.seq_len:
            raise ValueError(f"Need at least {self.cfg.seq_len} bars, got {len(X_sc)}")

        X_seq = X_sc[-self.cfg.seq_len :][np.newaxis, ...]  # (1, seq_len, features)
        deep_prob = float(self.deep_model.predict(X_seq)[0])

        ens_base = float(self.ensemble.predict_proba(X_df.iloc[[-1]])[0])
        if self.regime_router is not None:
            try:
                regime_prob = float(self.regime_router.predict_proba(X_df.iloc[[-1]])[0])
                ens_prob = 0.6 * ens_base + 0.4 * regime_prob
            except Exception:  # nosec B110 — regime prediction fallback
                ens_prob = ens_base
        else:
            ens_prob = ens_base

        final_prob = self.meta_weight * deep_prob + (1 - self.meta_weight) * ens_prob

        # Anomaly check on latest bar
        anomaly_flag = False
        if self.anomaly_weighter is not None:
            anomaly_flag = bool(self.anomaly_weighter.flag(X_df.iloc[[-1]])[0])

        return {
            "deep_prob": deep_prob,
            "ensemble_prob": ens_prob,
            "final_prob": final_prob,
            "anomaly_flag": anomaly_flag,
            "signal": "BUY"
            if final_prob > 0.6
            else ("SELL" if final_prob < 0.4 else "HOLD"),
        }
