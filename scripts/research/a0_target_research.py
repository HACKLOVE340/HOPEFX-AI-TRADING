# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/research/a0_target_research.py
======================================
Research spike (A0): which reformulation of the daily XAUUSD target shows skill
that survives an honest test? Writes nothing outside ``--out``; never touches
``ml/saved_models/``, ``ml/rl_models/`` or any registry.

Report: ``docs/audit/2026-09-25-a0-target-research.md``.

Families (every variant is counted in the multiple-comparison correction):

1. Direction over h in {5, 10, 20, 60} bars (logit, shallow GBM).
2. Magnitude-conditioned: 3-class up/flat/down; large-up / large-down events;
   direction restricted to large moves (diagnostic only, not tradable).
3. Volatility: next-N-day realised volatility (regression, against EWMA and
   persistence) and a volatility-regime classifier.
4. Well-known rules as strategies: 12-1 TSMOM, SMA trend filters, vol-targeted
   buy-and-hold, and two macro proxies (10y yield, DXY) on the 2021+ window.
5. The repo's eight backtestable ``strategies/`` classes, driven bar by bar
   through ``backtesting.strategy_adapter.BacktestStrategyAdapter``.

Honesty rules implemented here
------------------------------
* Data: ``ml.train_advanced.fetch_gold_ohlcv`` on ``data/XAUUSD_40Y.csv`` with
  ``allow_download=False``, so the spike and flat-bar gates run and no network
  is reached. High/low are not used for any target or ML feature (441 pre-2020
  bars are OHLC-inconsistent; ``ml.cached_series``): every threshold is scaled
  by close-to-close volatility.
* Features at t use closes <= t only. Labels are forward from close t.
* OOS window: every row dated after ``last_date - 8y`` (2018-03-25 for the
  committed file). Walk-forward inside it: refit at the start of each OOS year
  on all earlier rows, with the last ``horizon`` rows before the fold purged.
* Strategies: a position decided at close t is executed at close t+1 (one full
  bar of execution lag) and costs ``--cost-bps`` per unit of turnover.
* Uncertainty: moving-block bootstrap (block >= label horizon, and >= 20),
  1,000 draws, fixed seed. One-sided p-values from the bootstrap standard
  error; Bonferroni across every test run; deflated Sharpe ratio for the
  strategy families.

Usage::

    python scripts/research/a0_target_research.py --out /tmp/a0-research
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, rankdata, skew, spearmanr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("a0_target_research")

N_BOOT = 1000
SEED = 42
OOS_YEARS = 8
TRADING_DAYS = 252
MIN_BLOCK = 20
STRATEGY_BLOCK = 63
EWMA_LAMBDA = 0.94


# ── data ──────────────────────────────────────────────────────────────────────


def load_gold() -> pd.DataFrame:
    """Clean daily XAUUSD through the repo loader and its plausibility gates."""
    from ml.train_advanced import fetch_gold_ohlcv

    # years=40 keeps the whole committed file (2000-08-30 onward) regardless of
    # today's date, so the run is reproducible; the gate sees the full window.
    df = fetch_gold_ohlcv(
        "XAUUSD",
        40,
        use_cached=True,
        cached_csv=str(ROOT / "data" / "XAUUSD_40Y.csv"),
        allow_download=False,
    )
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def load_macro(name: str) -> pd.Series:
    m = pd.read_csv(ROOT / "data" / "macro" / f"{name}.csv", parse_dates=["date"], index_col="date")
    return m["value"].astype(float).sort_index()


def build_features(close: pd.Series) -> pd.DataFrame:
    """Stationary, close-only features. Row t uses closes <= t."""
    lc = np.log(close)
    r = lc.diff()
    f = pd.DataFrame(index=close.index)
    for n in (1, 5, 20, 60, 120, 250):
        f[f"ret_{n}"] = lc - lc.shift(n)
    f["mom_12_1"] = lc.shift(21) - lc.shift(252)
    for n in (5, 20, 60):
        f[f"logvol_{n}"] = np.log(r.rolling(n).std() + 1e-6)
    f["vol_ratio_20_60"] = f["logvol_20"] - f["logvol_60"]
    f["logvol_ewma"] = np.log(np.sqrt((r**2).ewm(alpha=1 - EWMA_LAMBDA, adjust=False).mean()) + 1e-6)
    f["dist_ma50"] = lc - lc.rolling(50).mean()
    f["dist_ma200"] = lc - lc.rolling(200).mean()
    f["dist_hi250"] = lc - lc.rolling(250).max()
    f["dist_lo250"] = lc - lc.rolling(250).min()
    f["ret20_z"] = f["ret_20"] / (r.rolling(20).std() * math.sqrt(20) + 1e-9)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    f["rsi_14"] = 100 - 100 / (1 + gain / (loss + 1e-12))
    return f


def fwd_log_return(close: pd.Series, h: int) -> pd.Series:
    lc = np.log(close)
    return lc.shift(-h) - lc


def fwd_realised_vol(close: pd.Series, n: int) -> pd.Series:
    """log RMS of the daily log returns t+1..t+n (NaN where not yet known)."""
    r2 = np.log(close).diff() ** 2
    fwd_mean = r2.rolling(n).mean().shift(-n)
    return np.log(np.sqrt(fwd_mean) + 1e-6)


# ── bootstrap ─────────────────────────────────────────────────────────────────


def mbb_index(n: int, block: int, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    """Moving-block bootstrap row indices, shape (n_boot, n)."""
    rng = np.random.default_rng(seed)
    block = max(1, min(block, n // 2))
    n_blocks = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    return (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]


def rank_auc_rows(y: np.ndarray, s: np.ndarray) -> np.ndarray:
    ranks = rankdata(s, axis=1)
    n_pos = y.sum(axis=1)
    n_neg = y.shape[1] - n_pos
    with np.errstate(divide="ignore", invalid="ignore"):
        auc = ((ranks * y).sum(axis=1) - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    auc[(n_pos == 0) | (n_neg == 0)] = np.nan
    return auc


def summarise(point: float, boots: np.ndarray, null: float) -> dict[str, Any]:
    """95% percentile CI and a one-sided p (H1: stat > null) from the bootstrap SE."""
    b = boots[np.isfinite(boots)]
    se = float(np.std(b, ddof=1)) if len(b) > 1 else float("nan")
    z = (point - null) / se if se and se > 0 else float("nan")
    p = float(1 - norm.cdf(z)) if math.isfinite(z) else 1.0
    return {
        "stat": round(float(point), 4),
        "ci_low": round(float(np.quantile(b, 0.025)), 4) if len(b) else None,
        "ci_high": round(float(np.quantile(b, 0.975)), 4) if len(b) else None,
        "se": round(se, 4),
        "p_one_sided": p,
        "null": null,
    }


# ── walk-forward ──────────────────────────────────────────────────────────────


def fold_starts(oos_start: pd.Timestamp, last: pd.Timestamp) -> list[pd.Timestamp]:
    out, t = [], oos_start
    while t <= last:
        out.append(t)
        t = t + pd.DateOffset(years=1)
    return out


def walk_forward(
    x: pd.DataFrame,
    y: pd.Series,
    horizon: int,
    oos_start: pd.Timestamp,
    make_model: Callable[[], Any],
    kind: str,
) -> tuple[pd.Series | pd.DataFrame, pd.Series]:
    """Refit yearly inside the OOS window. Returns (OOS predictions, OOS labels).

    kind: "proba" (binary: P(y=1)), "multi" (DataFrame of class probabilities),
    "reg" (point prediction). Rows with a NaN feature or label are dropped.
    """
    ok = x.notna().all(axis=1) & y.notna()
    x, y = x[ok], y[ok]
    dates = x.index
    starts = fold_starts(oos_start, dates[-1])
    preds = []
    for k, fs in enumerate(starts):
        fe = starts[k + 1] if k + 1 < len(starts) else dates[-1] + pd.Timedelta(days=1)
        test = (dates >= fs) & (dates < fe)
        if not test.any():
            continue
        first = int(np.argmax(test))
        # Purge: a training label reaches `horizon` bars forward, so drop the
        # last `horizon` rows before the fold (row positions ~ trading days).
        n_train = max(first - horizon, 0)
        model = make_model()
        model.fit(x.iloc[:n_train].to_numpy(), y.iloc[:n_train].to_numpy())
        xt = x[test].to_numpy()
        if kind == "proba":
            preds.append(pd.Series(model.predict_proba(xt)[:, 1], index=dates[test]))
        elif kind == "multi":
            preds.append(pd.DataFrame(model.predict_proba(xt), index=dates[test], columns=model.classes_.astype(int)))
        else:
            preds.append(pd.Series(model.predict(xt), index=dates[test]))
    pred = pd.concat(preds)
    return pred, y.loc[pred.index]


def logit_clf() -> Any:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000))


def gbm_clf() -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_depth=2, max_iter=150, learning_rate=0.05, min_samples_leaf=100, early_stopping=False, random_state=0
    )


def ridge_reg() -> Any:
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), Ridge(alpha=10.0))


def gbm_reg() -> Any:
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(
        max_depth=2, max_iter=150, learning_rate=0.05, min_samples_leaf=100, early_stopping=False, random_state=0
    )


MODELS_CLF = {"logit": logit_clf, "gbm": gbm_clf}


# ── family 1/2: classification ────────────────────────────────────────────────


def eval_binary(name: str, family: str, y: pd.Series, p: pd.Series, block: int, *, gated: bool = True) -> dict:
    from ml.oos_skill import oos_skill_metrics, skill_over_base_rate_check

    yv, pv = y.to_numpy().astype(int), p.to_numpy()
    idx = mbb_index(len(yv), block)
    auc_b = rank_auc_rows(yv[idx], pv[idx])
    auc = float(rank_auc_rows(yv[None, :], pv[None, :])[0])
    s = summarise(auc, auc_b, 0.5)
    m = oos_skill_metrics(yv, pv, block_len=block, n_boot=N_BOOT, seed=SEED)
    repo_pass, repo_reason = skill_over_base_rate_check(m)
    return {
        "name": name,
        "family": family,
        "metric": "AUC",
        "baseline": "0.5 (and accuracy vs always-majority, repo rule)",
        "n": len(yv),
        "block": block,
        **s,
        "accuracy": m["oos_accuracy"],
        "majority_baseline": m["oos_majority_baseline_accuracy"],
        "balanced_accuracy": m["oos_balanced_accuracy"],
        "predicted_up_rate": m["oos_predicted_up_rate"],
        "base_rate": m["oos_base_rate"],
        "repo_rule_pass": bool(repo_pass) if gated else None,
        "repo_rule_reason": repo_reason if gated else "n/a (event target: accuracy at 0.5 is not the question)",
        "counted": True,
    }


def eval_multiclass(name: str, y: pd.Series, proba: pd.DataFrame, prior: pd.Series, block: int) -> dict:
    yv = y.to_numpy().astype(int)
    classes = list(proba.columns)
    pv = proba.to_numpy()
    idx = mbb_index(len(yv), block)
    aucs, aucs_b = [], []
    for j, c in enumerate(classes):
        yc = (yv == c).astype(int)
        aucs.append(float(rank_auc_rows(yc[None, :], pv[None, :, j])[0]))
        aucs_b.append(rank_auc_rows(yc[idx], pv[:, j][idx]))
    macro = float(np.mean(aucs))
    macro_b = np.nanmean(np.vstack(aucs_b), axis=0)
    s = summarise(macro, macro_b, 0.5)
    pred = np.array(classes)[pv.argmax(axis=1)]
    counts = np.bincount(yv - min(classes), minlength=len(classes))
    majority = counts.max() / len(yv)
    recalls = [float(np.mean(pred[yv == c] == c)) for c in classes if np.any(yv == c)]
    # log-loss skill vs the training-prior climatology forecast
    col = {c: j for j, c in enumerate(classes)}
    ll_m = -np.mean(np.log(np.clip(pv[np.arange(len(yv)), [col[v] for v in yv]], 1e-9, 1)))
    ll_c = -np.mean(np.log(np.clip(prior.loc[yv].to_numpy(), 1e-9, 1)))
    return {
        "name": name,
        "family": "2 magnitude",
        "metric": "macro OvR AUC",
        "baseline": "0.5 (accuracy vs always-majority reported)",
        "n": len(yv),
        "block": block,
        **s,
        "per_class_auc": {str(c): round(a, 4) for c, a in zip(classes, aucs, strict=True)},
        "accuracy": round(float(np.mean(pred == yv)), 4),
        "majority_baseline": round(float(majority), 4),
        "balanced_accuracy": round(float(np.mean(recalls)), 4),
        "logloss_skill_vs_prior": round(float(1 - ll_m / ll_c), 4),
        "repo_rule_pass": None,
        "counted": True,
    }


def paired_auc(name: str, y: pd.Series, p_model: pd.Series, p_base: pd.Series, block: int) -> dict:
    yv = y.to_numpy().astype(int)
    pm, pb = p_model.to_numpy(), p_base.to_numpy()
    idx = mbb_index(len(yv), block)
    a_m = float(rank_auc_rows(yv[None, :], pm[None, :])[0])
    a_b = float(rank_auc_rows(yv[None, :], pb[None, :])[0])
    d_b = rank_auc_rows(yv[idx], pm[idx]) - rank_auc_rows(yv[idx], pb[idx])
    return {
        "name": name,
        "family": "2 magnitude",
        "metric": "AUC(model) - AUC(baseline)",
        "baseline": f"vol-only AUC {a_b:.4f}",
        "n": len(yv),
        "block": block,
        **summarise(a_m - a_b, d_b, 0.0),
        "auc_model": round(a_m, 4),
        "auc_baseline": round(a_b, 4),
        "repo_rule_pass": None,
        "counted": True,
    }


def run_classification(df: pd.DataFrame, feats: pd.DataFrame, oos_start: pd.Timestamp) -> list[dict]:
    close = df["close"]
    sigma = np.log(close).diff().rolling(20).std()
    out: list[dict] = []
    # 1. Direction.
    for h in (5, 10, 20, 60):
        fr = fwd_log_return(close, h)
        y = (fr > 0).astype(float).where(fr.notna())
        block = max(h, MIN_BLOCK)
        for mname, mk in MODELS_CLF.items():
            p, yy = walk_forward(feats, y, h, oos_start, mk, "proba")
            out.append(eval_binary(f"direction h={h} {mname}", "1 direction", yy, p, block))
            logger.info("done %s", out[-1]["name"])
    # 2a. Three-class up / flat / down, flat = |r| <= 0.5 sigma sqrt(h).
    for h in (5, 20):
        fr = fwd_log_return(close, h)
        thr = 0.5 * sigma * math.sqrt(h)
        y = pd.Series(np.select([fr > thr, fr < -thr], [2, 0], 1), index=close.index).astype(float)
        y = y.where(fr.notna() & thr.notna())
        block = max(h, MIN_BLOCK)
        for mname, mk in MODELS_CLF.items():
            p, yy = walk_forward(feats, y, h, oos_start, mk, "multi")
            train_prior = y[y.index < oos_start].value_counts(normalize=True)
            train_prior.index = train_prior.index.astype(int)
            out.append(eval_multiclass(f"3-class h={h} k=0.5 {mname}", yy, p, train_prior, block))
            logger.info("done %s", out[-1]["name"])
    # 2b. Large-move events, |r| > 1.0 sigma sqrt(h), per side.
    for h in (5, 20):
        fr = fwd_log_return(close, h)
        thr = 1.0 * sigma * math.sqrt(h)
        block = max(h, MIN_BLOCK)
        for side, cond in (("up", fr > thr), ("down", fr < -thr)):
            y = cond.astype(float).where(fr.notna() & thr.notna())
            for mname, mk in MODELS_CLF.items():
                p, yy = walk_forward(feats, y, h, oos_start, mk, "proba")
                out.append(eval_binary(f"large-{side} event h={h} {mname}", "2 magnitude", yy, p, block, gated=False))
                logger.info("done %s", out[-1]["name"])
    # 2d. Is the large-move skill directional, or is it volatility? The event
    # threshold is scaled by trailing sigma, so a model that only forecasts vol
    # expansion scores AUC > 0.5 on BOTH sides. Test: AUC(all features) minus
    # AUC(volatility features only), paired, same rows.
    vol_cols = ["logvol_5", "logvol_20", "logvol_60", "vol_ratio_20_60", "logvol_ewma"]
    for h in (5, 20):
        fr = fwd_log_return(close, h)
        thr = 1.0 * sigma * math.sqrt(h)
        block = max(h, MIN_BLOCK)
        for side, cond in (("up", fr > thr), ("down", fr < -thr), ("either", fr.abs() > thr)):
            y = cond.astype(float).where(fr.notna() & thr.notna())
            p_full, yy = walk_forward(feats, y, h, oos_start, logit_clf, "proba")
            p_vol, _ = walk_forward(feats[vol_cols], y, h, oos_start, logit_clf, "proba")
            out.append(
                paired_auc(
                    f"large-{side} h={h}: all features - vol-only (logit)", yy, p_full, p_vol.loc[yy.index], block
                )
            )
            logger.info("done %s", out[-1]["name"])
    # 2c. Direction among large moves only — row selection uses the future, so
    # this is a diagnostic of conditional predictability, not a tradable rule.
    for h in (5, 20):
        fr = fwd_log_return(close, h)
        thr = 1.0 * sigma * math.sqrt(h)
        keep = fr.abs() > thr
        y = (fr > 0).astype(float).where(fr.notna() & keep)
        p, yy = walk_forward(feats, y, h, oos_start, logit_clf, "proba")
        r = eval_binary(f"direction | large move h={h} logit (DIAGNOSTIC)", "2 magnitude", yy, p, max(h, MIN_BLOCK))
        r["note"] = "rows selected on the realised future move: not tradable"
        out.append(r)
        logger.info("done %s", out[-1]["name"])
    return out


# ── family 3: volatility ──────────────────────────────────────────────────────


def run_volatility(df: pd.DataFrame, feats: pd.DataFrame, oos_start: pd.Timestamp) -> list[dict]:
    from sklearn.linear_model import LinearRegression

    close = df["close"]
    r = np.log(close).diff()
    out: list[dict] = []
    for n in (5, 20):
        y = fwd_realised_vol(close, n)
        block = max(n, MIN_BLOCK)
        persist = np.log(np.sqrt((r**2).rolling(n).mean()) + 1e-6)
        ewma = feats["logvol_ewma"]
        # Calibrated EWMA: log-vol target ~ a + b * log EWMA, fitted walk-forward
        # like the models, so the baseline gets the same chance to fix its bias.
        ewma_cal, yy = walk_forward(ewma.to_frame(), y, n, oos_start, LinearRegression, "reg")
        # Constant forecast: the training-set mean of the target, per fold.
        const = pd.Series(np.nan, index=yy.index)
        for fs in fold_starts(oos_start, yy.index[-1]):
            tr = y[(y.index < fs)].dropna()
            tr = tr.iloc[: max(len(tr) - n, 0)]
            const[const.index >= fs] = tr.mean()
        preds = {"ewma_cal": ewma_cal}
        for mname, mk in (("ridge", ridge_reg), ("gbm", gbm_reg)):
            preds[mname], _ = walk_forward(feats, y, n, oos_start, mk, "reg")
        yv = yy.to_numpy()
        idx = mbb_index(len(yv), block)

        def r2_rel(pm: np.ndarray, pb: np.ndarray, yv: np.ndarray = yv, idx: np.ndarray = idx) -> tuple:
            em, eb = (yv - pm) ** 2, (yv - pb) ** 2
            point = 1 - em.sum() / eb.sum()
            boots = 1 - em[idx].sum(axis=1) / eb[idx].sum(axis=1)
            return point, boots

        def ic(pm: np.ndarray, yv: np.ndarray = yv) -> float:
            return float(spearmanr(pm, yv).statistic)

        pairs = [
            (f"RV{n} EWMA(cal) vs constant", ewma_cal, const, "constant (train mean)"),
            (f"RV{n} ridge vs EWMA(cal)", preds["ridge"], ewma_cal, "calibrated EWMA"),
            (f"RV{n} gbm vs EWMA(cal)", preds["gbm"], ewma_cal, "calibrated EWMA"),
        ]
        for name, pm, pb, base in pairs:
            pm_v, pb_v = pm.loc[yy.index].to_numpy(), pb.loc[yy.index].to_numpy()
            point, boots = r2_rel(pm_v, pb_v)
            is_const = base.startswith("constant")
            # Paired rank-IC difference (model - baseline), 200 draws; a per-fold
            # constant has no meaningful rank IC, so none is reported for it.
            ic_d = (
                None
                if is_const
                else np.array(
                    [spearmanr(pm_v[i], yv[i]).statistic - spearmanr(pb_v[i], yv[i]).statistic for i in idx[:200]]
                )
            )
            out.append(
                {
                    "name": name,
                    "family": "3 volatility",
                    "metric": "OOS R2 relative to baseline (1 - SSE/SSE_base)",
                    "baseline": base,
                    "n": len(yv),
                    "block": block,
                    **summarise(point, boots, 0.0),
                    "rank_ic_model": round(ic(pm_v), 4),
                    "rank_ic_baseline": None if is_const else round(ic(pb_v), 4),
                    "rank_ic_diff_ci_200": None
                    if ic_d is None
                    else [round(float(np.quantile(ic_d, q)), 4) for q in (0.025, 0.975)],
                    "r2_vs_persistence": round(
                        float(1 - ((yv - pm_v) ** 2).sum() / ((yv - persist.loc[yy.index].to_numpy()) ** 2).sum()), 4
                    ),
                    "repo_rule_pass": None,
                    "counted": True,
                }
            )
            logger.info("done %s", name)
    # Volatility regime: next-20d RV above the trailing 252-day median of RV20.
    rv20 = np.log(np.sqrt((r**2).rolling(20).mean()) + 1e-6)
    med = rv20.rolling(252).median()
    y_fwd = fwd_realised_vol(close, 20)
    y = (y_fwd > med).astype(float).where(y_fwd.notna() & med.notna())
    base_score = rv20 - med  # persistence: today's RV20 relative to its median
    for mname, mk in MODELS_CLF.items():
        p, yy = walk_forward(feats, y, 20, oos_start, mk, "proba")
        yv = yy.to_numpy().astype(int)
        pv, bv = p.to_numpy(), base_score.loc[yy.index].to_numpy()
        idx = mbb_index(len(yv), 20)
        d_b = rank_auc_rows(yv[idx], pv[idx]) - rank_auc_rows(yv[idx], bv[idx])
        a_m = float(rank_auc_rows(yv[None, :], pv[None, :])[0])
        a_b = float(rank_auc_rows(yv[None, :], bv[None, :])[0])
        out.append(
            {
                "name": f"vol regime h=20 {mname} vs persistence",
                "family": "3 volatility",
                "metric": "AUC(model) - AUC(persistence)",
                "baseline": f"persistence AUC {a_b:.4f}",
                "n": len(yv),
                "block": 20,
                **summarise(a_m - a_b, d_b, 0.0),
                "auc_model": round(a_m, 4),
                "auc_persistence": round(a_b, 4),
                "repo_rule_pass": None,
                "counted": True,
            }
        )
        logger.info("done %s", out[-1]["name"])
    return out


# ── families 4/5: strategies ──────────────────────────────────────────────────


def strategy_returns(pos: pd.Series, close: pd.Series, cost_bps: float) -> pd.Series:
    """Position decided at close t is executed at close t+1 and earns r(t+2).

    Cost: ``cost_bps`` per unit of turnover, charged on the execution bar.
    """
    r = close.pct_change()
    executed = pos.shift(1).fillna(0.0)  # position held from close t onward
    gross = executed.shift(1).fillna(0.0) * r
    cost = executed.diff().abs().fillna(executed.abs()) * cost_bps / 1e4
    return (gross - cost).fillna(0.0)


def sharpe(x: np.ndarray, axis: int = -1) -> np.ndarray:
    return x.mean(axis=axis) / x.std(axis=axis, ddof=1) * math.sqrt(TRADING_DAYS)


def eval_strategy(name: str, family: str, sret: pd.Series, bh: pd.Series, pos: pd.Series, extra: dict) -> dict:
    s, b = sret.to_numpy(), bh.to_numpy()
    idx = mbb_index(len(s), STRATEGY_BLOCK)
    d_boot = sharpe(s[idx]) - sharpe(b[idx])
    sr_s, sr_b = float(sharpe(s)), float(sharpe(b))
    eq = np.cumprod(1 + s)
    dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    years = len(s) / TRADING_DAYS
    p = pos.loc[sret.index]
    return {
        "name": name,
        "family": family,
        "metric": "Sharpe(strategy) - Sharpe(buy-and-hold), net of costs",
        "baseline": f"buy-and-hold Sharpe {sr_b:.3f}",
        "n": len(s),
        "block": STRATEGY_BLOCK,
        **summarise(sr_s - sr_b, d_boot, 0.0),
        "sharpe": round(sr_s, 4),
        "sharpe_bh": round(sr_b, 4),
        "cagr": round(float(eq[-1] ** (1 / years) - 1), 4),
        "cagr_bh": round(float(np.prod(1 + b) ** (1 / years) - 1), 4),
        "max_dd": round(dd, 4),
        "exposure": round(float(p.abs().mean()), 4),
        "turnover_per_year": round(float(p.diff().abs().sum() / years), 2),
        "daily_sr": float(s.mean() / s.std(ddof=1)),
        "skew": float(skew(s)),
        "kurt": float(kurtosis(s, fisher=False)),
        "window": f"{sret.index[0].date()}..{sret.index[-1].date()}",
        "repo_rule_pass": None,
        "counted": True,
        **extra,
    }


def run_rules(df: pd.DataFrame, oos_start: pd.Timestamp, cost_bps: float) -> list[dict]:
    close = df["close"]
    lc = np.log(close)
    r = lc.diff()
    oos = close.index >= oos_start
    bh = close.pct_change().fillna(0.0)
    out = []
    mom = lc.shift(21) - lc.shift(252)
    sma50, sma200 = close.rolling(50).mean(), close.rolling(200).mean()
    ewvol = np.sqrt((r**2).ewm(alpha=1 - EWMA_LAMBDA, adjust=False).mean() * TRADING_DAYS)
    target = float(r[~oos].std() * math.sqrt(TRADING_DAYS))  # pre-OOS realised vol: no look-ahead
    rules = {
        "TSMOM 12-1 long/flat": (mom > 0).astype(float),
        "TSMOM 12-1 long/short": np.sign(mom).fillna(0.0),
        "SMA200 long/flat": (close > sma200).astype(float),
        "SMA200 long/short": np.where(close > sma200, 1.0, -1.0),
        "SMA50>SMA200 long/flat": (sma50 > sma200).astype(float),
        f"vol-targeted buy-and-hold ({target:.1%}, cap 2x)": (target / ewvol).clip(upper=2.0),
    }
    for name, raw_pos in rules.items():
        pos = pd.Series(raw_pos, index=close.index).fillna(0.0)
        sret = strategy_returns(pos, close, cost_bps)
        pre = (close.index >= close.index[260]) & ~oos  # in-sample context, not a test
        extra = {"sharpe_pre_oos": round(float(sharpe(sret[pre].to_numpy())), 4)}
        extra["sharpe_bh_pre_oos"] = round(float(sharpe(bh[pre].to_numpy())), 4)
        out.append(eval_strategy(name, "4 rules", sret[oos], bh[oos], pos, extra))
        logger.info("done %s", name)
    # Macro proxies — offline data covers only 2021-03-29 onward. A value
    # dated d is used from the NEXT gold bar (lagged one bar) in case the
    # series is stamped at a later close than gold's.
    for series, label in (
        ("us10y_daily", "10y yield falling (20d) long/flat"),
        ("dxy_daily", "DXY falling (20d) long/flat"),
    ):
        m = load_macro(series).reindex(close.index, method="ffill").shift(1)
        chg = m - m.shift(20)
        pos = (chg < 0).astype(float).where(chg.notna(), 0.0)
        sret = strategy_returns(pos, close, cost_bps)
        start = chg.first_valid_index()
        win = close.index >= max(start, oos_start)
        out.append(
            eval_strategy(
                f"{label} [2021+ only]",
                "4 rules",
                sret[win],
                bh[win],
                pos,
                {"note": "no real-rate/TIPS series offline; nominal proxy only"},
            )
        )
        logger.info("done %s", label)
    return out


def run_repo_strategies(df: pd.DataFrame, oos_start: pd.Timestamp, cost_bps: float, window: int = 500) -> list[dict]:
    from backtesting.strategy_adapter import BacktestStrategyAdapter
    from strategies.registry import available_strategies, build

    close = df["close"]
    oos = close.index >= oos_start
    bh = close.pct_change().fillna(0.0)
    frame = df.copy()
    frame["timestamp"] = frame.index
    first_oos = int(np.argmax(oos))
    start = max(first_oos - 250, window)  # 250 warm-up bars so state exists at OOS start
    out = []
    for key in available_strategies():
        t0 = time.time()
        adapter = BacktestStrategyAdapter(build(key, "XAUUSD", timeframe="1d"), "XAUUSD")
        pos = pd.Series(0.0, index=close.index)
        for i in range(start, len(frame)):
            ts = frame.index[i]
            win = frame.iloc[max(0, i - window + 1) : i + 1]
            adapter.generate_signals(ts, {"XAUUSD": float(close.iloc[i])}, {"XAUUSD": win})
            pos.iloc[i] = 1.0 if adapter.position == "long" else 0.0
        sret = strategy_returns(pos, close, cost_bps)
        out.append(
            eval_strategy(
                f"repo {key} (long/flat)",
                "5 repo strategies",
                sret[oos],
                bh[oos],
                pos,
                {"strategy_errors": len(adapter.errors), "seconds": round(time.time() - t0, 1)},
            )
        )
        logger.info("done repo %s in %.0fs (errors=%d)", key, time.time() - t0, len(adapter.errors))
    return out


def deflated_sharpe(rows: list[dict]) -> None:
    """Bailey & Lopez de Prado DSR over all strategy variants, in place."""
    srs = np.array([r["daily_sr"] for r in rows])
    n_trials = len(srs)
    v = float(np.var(srs, ddof=1))
    em = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - em) * norm.ppf(1 - 1 / n_trials) + em * norm.ppf(1 - 1 / (n_trials * math.e)))
    for r in rows:
        sr, t = r["daily_sr"], r["n"]
        denom = math.sqrt(max(1 - r["skew"] * sr + (r["kurt"] - 1) / 4 * sr**2, 1e-12))
        r["dsr"] = round(float(norm.cdf((sr - sr0) * math.sqrt(t - 1) / denom)), 4)
        r["dsr_sr0_annual"] = round(sr0 * math.sqrt(TRADING_DAYS), 4)
        r["dsr_trials"] = n_trials


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="output directory, e.g. /tmp/a0-research")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="cost per unit turnover, one side (default 5bp)")
    ap.add_argument("--families", default="1,3,4,5", help="1=classification (1+2), 3=vol, 4=rules, 5=repo strategies")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument(
        "--truncate-at",
        default=None,
        help="drop bars on/after this date first (replication on an earlier, disjoint OOS window)",
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for noisy in ("ml", "strategies", "backtesting", "data_layer"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_gold()
    if args.truncate_at:
        df = df[df.index < pd.Timestamp(args.truncate_at)]
    oos_start = df.index[-1] - pd.DateOffset(years=OOS_YEARS) + pd.Timedelta(days=1)
    feats = build_features(df["close"])
    fam = set(args.families.split(","))
    meta = {
        "rows": len(df),
        "first": str(df.index[0].date()),
        "last": str(df.index[-1].date()),
        "oos_start": str(oos_start.date()),
        "features": list(feats.columns),
        "cost_bps": args.cost_bps,
        "n_boot": N_BOOT,
        "seed": SEED,
    }
    logger.info("data %s", meta)
    results: list[dict] = []
    if "1" in fam:
        results += run_classification(df, feats, oos_start)
    if "3" in fam:
        results += run_volatility(df, feats, oos_start)
    strat_rows: list[dict] = []
    if "4" in fam:
        strat_rows += run_rules(df, oos_start, args.cost_bps)
    if "5" in fam:
        strat_rows += run_repo_strategies(df, oos_start, args.cost_bps)
    if strat_rows:
        deflated_sharpe(strat_rows)
        bh = df["close"].pct_change()[df.index >= oos_start].to_numpy()
        sr = bh.mean() / bh.std(ddof=1)
        denom = math.sqrt(1 - skew(bh) * sr + (kurtosis(bh, fisher=False) - 1) / 4 * sr**2)
        meta["buy_and_hold_psr_vs_0"] = round(float(norm.cdf(sr * math.sqrt(len(bh) - 1) / denom)), 4)
        meta["buy_and_hold_sharpe"] = round(float(sr * math.sqrt(TRADING_DAYS)), 4)
    results += strat_rows

    m = sum(1 for r in results if r.get("counted"))
    for r in results:
        r["p_bonferroni"] = min(1.0, r["p_one_sided"] * m)
        r["pass_uncorrected"] = bool(r["ci_low"] is not None and r["ci_low"] > r["null"])
        rule_ok = r["repo_rule_pass"] is not False
        r["pass_corrected"] = bool(r["p_bonferroni"] < args.alpha and r["pass_uncorrected"] and rule_ok)
    meta["tests_counted"] = m
    suffix = f"_until_{args.truncate_at}" if args.truncate_at else ""
    (out_dir / f"results_{'_'.join(sorted(fam))}{suffix}.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=2, default=str)
    )
    print(f"\n{m} tests; Bonferroni alpha = {args.alpha / m:.5f}\n")
    for r in sorted(results, key=lambda r: r["p_one_sided"]):
        print(
            f"{r['name'][:55]:55s} {r['stat']:+.4f} [{r['ci_low']:+.4f},{r['ci_high']:+.4f}] "
            f"p={r['p_one_sided']:.2e} pB={r['p_bonferroni']:.3f} pass={r['pass_corrected']} rule={r['repo_rule_pass']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
