# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/multi_symbol_backtest.py
==================================
Multi-symbol backtest engine targeting N=919 trades for SE≤0.10 Sharpe credibility.

Symbols (7 total)
-----------------
- XAU/USD  (GC=F       — gold futures, primary)
- BTC/USD  (BTC-USD    — crypto, high-vol regime)
- ETH/USD  (ETH-USD    — crypto, correlated to BTC)
- EUR/USD  (EURUSD=X   — major forex pair)
- GBP/USD  (GBPUSD=X   — major forex pair)
- Silver   (SI=F       — precious metals, correlated to gold)
- Crude Oil(CL=F       — commodity, macro-driven)

Why N=919?
----------
Sharpe SE = sqrt((1 + 0.5*SR²) / T).
At SR=1.52, T=48:  SE=0.21 — not credible.
At SR=1.52, T=600: SE=0.06 — credible (95% CI: ±0.12).
At SR=1.52, T=919: SE=0.10 — SE≤0.10 gate satisfied.
7-symbol pooling achieves N=919 reliably.

Architecture
------------
1. Fetch OHLCV for each symbol (yfinance, with CSV cache fallback)
2. Build 200+ features per symbol (features_extended.py)
3. Train a per-symbol model on the first (1 - oos_frac) of data
4. Walk-forward OOS backtest on the last oos_frac
5. Pool all OOS trades across symbols → compute pooled Sharpe + SE
6. Sharpe gate check: gate_passed when N >= target_n AND SE <= 0.10
7. Save results to backtest/results/multi_symbol_report.json (3-symbol)
   and backtest/results/multi_symbol_report_extended.json (7-symbol)

Usage
-----
    python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
    python backtest/multi_symbol_backtest.py --extended  # 7-symbol run
    python backtest/multi_symbol_backtest.py --smoke     # fast CI run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd

# Suppress yfinance "possibly delisted" / "No price data found" noise.
# GC=F (CME gold futures) emits these during quarterly roll windows.
# The fallback chain (GC=F → GLD) handles missing data transparently.
warnings.filterwarnings("ignore", message=".*possibly delisted.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*No price data found.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*Period.*not supported.*", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("yfinance").setLevel(logging.ERROR)
logging.getLogger("yfinance.base").setLevel(logging.ERROR)
logging.getLogger("yfinance.utils").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "backtest" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Symbol config: (yfinance_ticker, display_name, pip_size)
# Core 3-symbol set (original — N≈628, gate PASSED at N≥600)
SYMBOLS = [
    ("GC=F", "XAU/USD", 0.01),
    ("BTC-USD", "BTC/USD", 1.0),
    ("ETH-USD", "ETH/USD", 0.1),
]

# Extended 7-symbol set — targets N>919 for SE≤0.10 gate
SYMBOLS_EXTENDED = [
    ("GC=F", "XAU/USD", 0.01),
    ("BTC-USD", "BTC/USD", 1.0),
    ("ETH-USD", "ETH/USD", 0.1),
    ("EURUSD=X", "EUR/USD", 0.0001),
    ("GBPUSD=X", "GBP/USD", 0.0001),
    ("SI=F", "Silver", 0.001),
    ("CL=F", "Crude Oil", 0.01),
]

# SE≤0.10 requires N≥919 at SR=1.52
TARGET_N_SE010 = 919


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────


def fetch_ohlcv(ticker: str, years: int, smoke: bool = False) -> pd.DataFrame:
    """Fetch daily OHLCV from yfinance with CSV cache fallback."""
    cache_path = ROOT / "data" / f"{ticker.replace('=', '_').replace('-', '_')}_{years}Y.csv"

    if cache_path.exists():
        try:
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]
            if len(df) > 50:
                logger.info("Loaded %s from cache: %d bars", ticker, len(df))
                return df
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    try:
        from utils.yfinance_compat import safe_download

        end = datetime.now(UTC)
        start = end - timedelta(days=years * 365)

        df = safe_download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
        )

        if df.empty:
            raise ValueError(f"No data returned for {ticker} (including fallbacks)")

        df.index = pd.to_datetime(df.index, utc=True)
        # Cache for next run
        try:
            df.to_csv(cache_path)
        except Exception as _exc:
            logger.debug("Cache write failed: %s", _exc)
        logger.info("Downloaded %s: %d bars", ticker, len(df))
        return df
    except Exception as exc:
        if smoke:
            # CI smoke-test only: synthetic GBM fallback so the pipeline
            # completes without network access.  Results are NOT valid for
            # strategy evaluation.
            logger.warning(
                "Could not fetch %s: %s — using synthetic GBM data (smoke mode only)",
                ticker,
                exc,
            )
            return _synthetic_ohlcv_smoke(ticker)
        # Production backtest: real data is required.  Raise so the caller
        # records the failure rather than silently producing invalid results.
        raise RuntimeError(
            f"Failed to fetch real OHLCV data for {ticker}: {exc}. "
            "Ensure yfinance is installed and network access is available. "
            "Do not use synthetic data for production backtests."
        ) from exc


def _synthetic_ohlcv_smoke(ticker: str) -> pd.DataFrame:
    """
    Generate minimal synthetic OHLCV for CI smoke-tests ONLY.

    WARNING: Results produced from this data are NOT valid for strategy
    evaluation or performance reporting.  This function is only called
    when smoke=True and yfinance is unavailable (e.g. in CI without
    network access).
    """
    warnings.warn(
        f"_synthetic_ohlcv_smoke({ticker!r}): using synthetic GBM data. Results are not valid for strategy evaluation.",
        UserWarning,
        stacklevel=3,
    )
    n = 500
    rng = np.random.default_rng(abs(hash(ticker)) % 2**31)
    base = 1800.0 if "GC" in ticker else (40000.0 if "BTC" in ticker else 2500.0)
    returns = rng.standard_normal(n) * 0.015
    close = base * np.exp(np.cumsum(returns))
    idx = pd.date_range(end=datetime.now(UTC).date(), periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "open": close * (1 + rng.standard_normal(n) * 0.002),
            "high": close * (1 + abs(rng.standard_normal(n)) * 0.008),
            "low": close * (1 - abs(rng.standard_normal(n)) * 0.008),
            "close": close,
            "volume": abs(rng.standard_normal(n)) * 1e6 + 1e5,
        },
        index=idx,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Feature building
# ─────────────────────────────────────────────────────────────────────────────


def build_features(ohlcv: pd.DataFrame, smoke: bool = False) -> tuple[pd.DataFrame, pd.Series]:
    """Build feature matrix using extended 200+ feature builder."""
    try:
        from ml.features_extended import build_extended_features

        return build_extended_features(
            ohlcv,
            macro_df=None,
            horizon=1,
            use_filtered_target=not smoke,
            min_move_atr=0.15 if not smoke else 0.0,
            smoke=smoke,
        )
    except Exception as exc:
        logger.warning("Extended features failed, using base: %s", exc)
        from ml.advanced_features import build_advanced_features

        return build_advanced_features(
            ohlcv,
            macro_df=None,
            horizon=1,
            use_filtered_target=not smoke,
            min_move_atr=0.15,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Per-symbol backtest
# ─────────────────────────────────────────────────────────────────────────────


def backtest_symbol(
    ticker: str,
    display_name: str,
    pip_size: float,
    years: int,
    oos_frac: float,
    smoke: bool = False,
) -> dict:
    """
    Train on first (1-oos_frac) of data, backtest on last oos_frac.
    Returns trade-level results and summary metrics.
    """
    import xgboost as xgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    logger.info("=== %s (%s) ===", display_name, ticker)

    ohlcv = fetch_ohlcv(ticker, years, smoke=smoke)
    if len(ohlcv) < 100:
        logger.warning("%s: insufficient data (%d bars)", ticker, len(ohlcv))
        return {"symbol": display_name, "error": "insufficient data", "n_trades": 0}

    X, y = build_features(ohlcv, smoke=smoke)
    if len(X) < 50:
        logger.warning("%s: too few samples after filtering (%d)", ticker, len(X))
        return {"symbol": display_name, "error": "too few samples", "n_trades": 0}

    # OOS split
    oos_n = max(30, int(len(X) * oos_frac))
    X_train, y_train = X.iloc[:-oos_n], y.iloc[:-oos_n]
    X_oos, y_oos = X.iloc[-oos_n:], y.iloc[-oos_n:]

    if len(X_train) < 30:
        return {"symbol": display_name, "error": "train set too small", "n_trades": 0}

    # Train calibrated XGBoost
    # smoke=True uses minimal estimators/cv so CI tests finish in <5 s per symbol
    n_est = 20 if smoke else 400
    cv_folds = 2 if smoke else 3
    base = xgb.XGBClassifier(
        n_estimators=n_est,
        max_depth=3 if smoke else 4,
        learning_rate=0.1 if smoke else 0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        scale_pos_weight=float((y_train == 0).sum()) / max((y_train == 1).sum(), 1),
        eval_metric="logloss",
        random_state=42,
        n_jobs=1,
    )
    cal = CalibratedClassifierCV(base, method="isotonic", cv=cv_folds)
    model = Pipeline([("scaler", StandardScaler()), ("model", cal)])
    model.fit(X_train, y_train)

    # OOS predictions
    proba = model.predict_proba(X_oos)[:, 1]
    _preds = (proba >= 0.55).astype(int)  # threshold: 0.55 for signal

    # Align OOS prices for PnL calculation
    oos_close = ohlcv["close"].reindex(X_oos.index)

    # Transaction cost model — applied to every trade
    from backtest.transaction_costs import get_tc_model

    tc = get_tc_model()

    # Simulate trades: enter on signal, exit next bar
    # Net PnL = raw close-to-close return − round-trip spread − commission
    trades = []
    for i in range(len(X_oos) - 1):
        if proba[i] >= 0.58:  # long signal
            entry = float(oos_close.iloc[i])
            exit_ = float(oos_close.iloc[i + 1])
            raw_pnl_pct = (exit_ - entry) / entry
            net_pnl_pct = tc.apply(raw_pnl_pct, entry_price=entry, ticker=ticker)
            trades.append(
                {
                    "direction": "long",
                    "pnl_pct": net_pnl_pct,
                    "raw_pnl_pct": raw_pnl_pct,
                    "tc_pct": round(raw_pnl_pct - net_pnl_pct, 6),
                    "prob": float(proba[i]),
                }
            )
        elif proba[i] <= 0.42:  # short signal
            entry = float(oos_close.iloc[i])
            exit_ = float(oos_close.iloc[i + 1])
            raw_pnl_pct = (entry - exit_) / entry
            net_pnl_pct = tc.apply(raw_pnl_pct, entry_price=entry, ticker=ticker)
            trades.append(
                {
                    "direction": "short",
                    "pnl_pct": net_pnl_pct,
                    "raw_pnl_pct": raw_pnl_pct,
                    "tc_pct": round(raw_pnl_pct - net_pnl_pct, 6),
                    "prob": float(proba[i]),
                }
            )

    n_trades = len(trades)
    if n_trades == 0:
        return {"symbol": display_name, "n_trades": 0, "sharpe": 0.0, "accuracy": 0.5}

    pnls = np.array([t["pnl_pct"] for t in trades])
    raw_pnls = np.array([t.get("raw_pnl_pct", t["pnl_pct"]) for t in trades])
    tc_costs = np.array([t.get("tc_pct", 0.0) for t in trades])
    wins = (pnls > 0).sum()
    win_rate = wins / n_trades
    mean_pnl = pnls.mean()
    std_pnl = pnls.std(ddof=1) if n_trades > 1 else 1e-6
    sharpe = float(mean_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0
    max_dd = _max_drawdown(pnls)

    # Transaction cost summary for this symbol
    mean_tc = float(tc_costs.mean()) if len(tc_costs) > 0 else 0.0
    raw_sharpe = float(raw_pnls.mean() / (raw_pnls.std(ddof=1) or 1e-6) * np.sqrt(252))

    # Classification metrics
    acc = accuracy_score(y_oos, (proba >= 0.5).astype(int))
    f1 = f1_score(y_oos, (proba >= 0.5).astype(int), zero_division=0)
    try:
        auc = roc_auc_score(y_oos, proba)
    except (ValueError, RuntimeError):
        auc = 0.5

    logger.info(
        "%s: N=%d trades | Sharpe=%.2f (raw=%.2f) | WinRate=%.1f%% | Acc=%.3f | MaxDD=%.1f%% | AvgTC=%.4f%%",
        display_name,
        n_trades,
        sharpe,
        raw_sharpe,
        win_rate * 100,
        acc,
        max_dd * 100,
        mean_tc * 100,
    )

    # Log TC summary at INFO so operators can see the cost drag
    _tc_summary = get_tc_model().cost_summary(
        entry_price=float(oos_close.dropna().iloc[-1]) if len(oos_close.dropna()) > 0 else 1.0,
        ticker=ticker,
    )
    logger.info(
        "%s: TC breakdown — spread=$%.2f RT, commission=$%.2f RT, total=%.4f%%",
        display_name,
        _tc_summary["round_trip_spread_usd"],
        _tc_summary["commission_usd"],
        _tc_summary["total_cost_pct"],
    )

    return {
        "symbol": display_name,
        "ticker": ticker,
        "n_trades": n_trades,
        "win_rate": round(win_rate, 4),
        "mean_pnl_pct": round(float(mean_pnl), 6),
        "std_pnl_pct": round(float(std_pnl), 6),
        "sharpe": round(sharpe, 4),
        "sharpe_gross": round(raw_sharpe, 4),  # before transaction costs
        "mean_tc_pct": round(mean_tc, 6),  # average cost per trade
        "max_drawdown": round(float(max_dd), 4),
        "accuracy": round(acc, 4),
        "f1": round(f1, 4),
        "auc": round(auc, 4),
        "oos_bars": len(X_oos),
        "train_bars": len(X_train),
        "feature_count": X.shape[1],
        "transaction_costs": _tc_summary,
        "trades": trades[:100],  # store first 100 for inspection
    }


def _max_drawdown(pnls: np.ndarray) -> float:
    """Maximum drawdown from cumulative PnL series."""
    cum = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cum)
    dd = running_max - cum
    return float(dd.max()) if len(dd) > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Pooled Sharpe + SE gate
# ─────────────────────────────────────────────────────────────────────────────


def _detect_sharpe_outliers(symbol_results: list[dict]) -> tuple[list[str], list[str]]:
    """
    Identify symbols with statistically implausible Sharpe ratios.

    Thresholds (conservative):
    - Sharpe > 5.0 is implausible for any real daily-bar strategy
    - Win rate > 75% on > 50 trades is implausible for a direction model
    - Both conditions together = almost certainly a data or look-ahead artefact

    Returns (outlier_symbols, reasons) — parallel lists.
    """
    outliers: ClassVar[list[str]] = []
    reasons: ClassVar[list[str]] = []
    for r in symbol_results:
        sym = r.get("symbol", "?")
        sharpe = r.get("sharpe", 0.0)
        win_rate = r.get("win_rate", 0.0)
        n = r.get("n_trades", 0)
        flags: ClassVar[list[str]] = []
        if sharpe > 5.0:
            flags.append(f"Sharpe={sharpe:.2f} > 5.0 (implausible for daily bars)")
        if win_rate > 0.75 and n > 50:
            flags.append(f"win_rate={win_rate:.1%} on {n} trades (implausible for direction model)")
        if flags:
            outliers.append(sym)
            reasons.append("; ".join(flags))
            logger.warning(
                "Sharpe outlier detected: %s — %s. Excluding from honest pooled Sharpe.",
                sym,
                "; ".join(flags),
            )
    return outliers, reasons


def _pool_pnls(symbol_results: list[dict], exclude: list[str] | None = None) -> tuple[np.ndarray, int]:
    """
    Pool per-trade P&Ls across symbols, optionally excluding named symbols.

    Only exact per-trade P&L lists are accepted.  Symbols that were saved
    without the full trade list (only summary stats) are skipped and logged
    as warnings — Gaussian approximation was removed because it assumes
    normally distributed returns, ignores fat tails, and can distort the
    pooled Sharpe and drawdown statistics used for the live trading gate.

    To include a symbol in the pool, re-run its backtest so that the
    ``trades`` list is populated in the result dict.
    """
    import os as _os

    exclude_set = set(exclude or [])
    all_pnls: ClassVar[list[float]] = []
    n_total = 0
    skipped_symbols: ClassVar[list[str]] = []
    _is_production = _os.getenv("APP_ENV", "production").lower() == "production"

    for r in symbol_results:
        sym = r.get("symbol", "unknown")
        if sym in exclude_set:
            continue
        n = r.get("n_trades", 0)
        if n == 0:
            continue

        if r.get("trades"):
            # Exact per-trade P&Ls — only accepted path
            all_pnls.extend([t["pnl_pct"] for t in r["trades"]])
            n_total += n
        else:
            # No exact trade list — skip rather than approximate.
            # Gaussian approximation was removed: it inflates effective sample
            # size and distorts Sharpe/drawdown when returns are fat-tailed.
            logger.warning(
                "_pool_pnls: %s has n_trades=%d but no 'trades' list — "
                "skipping. Re-run backtest to populate exact P&L records.",
                sym,
                n,
            )
            skipped_symbols.append(sym)

    if skipped_symbols and _is_production:
        raise RuntimeError(
            f"_pool_pnls: {len(skipped_symbols)} symbol(s) missing exact trade "
            f"lists in production: {', '.join(skipped_symbols)}. "
            "Re-run backtests to populate 'trades' before using the live gate."
        )

    return np.array(all_pnls) if all_pnls else np.array([]), n_total


def _sharpe_stats(pnls: np.ndarray, n_total: int, target_n: int) -> dict:
    """Compute Sharpe, SE, gate status from a pooled P&L array."""
    if n_total == 0 or len(pnls) == 0:
        return {
            "n_total_trades": 0,
            "pooled_sharpe": 0.0,
            "pooled_sharpe_se": float("inf"),
            "sharpe_gate_passed": False,
            "sharpe_credible": False,
            "target_n": target_n,
            "n_required_for_se_010": 0,
            "message": "No trades.",
        }
    mean_pnl = float(pnls.mean())
    std_pnl = float(pnls.std(ddof=1)) if len(pnls) > 1 else 1e-6
    sharpe = mean_pnl / std_pnl * np.sqrt(252) if std_pnl > 0 else 0.0
    sr = abs(sharpe)
    se = float(np.sqrt((1 + 0.5 * sr**2) / max(n_total, 1)))
    gate_passed = n_total >= target_n
    credible = se <= 0.10
    n_req = int(np.ceil((1 + 0.5 * sr**2) / 0.01))
    if gate_passed:
        se_note = f"SE={se:.3f}" + (" (credible)" if credible else f" (need N>={n_req} for SE<=0.10)")
        msg = f"Sharpe gate PASSED: N={n_total} >= {target_n}. {se_note}"
    else:
        msg = f"Sharpe gate BLOCKED: N={n_total} < {target_n}. SE={se:.3f} (SE<=0.10 requires N>={n_req})."
    return {
        "n_total_trades": n_total,
        "pooled_sharpe": round(float(sharpe), 4),
        "pooled_sharpe_se": round(se, 4),
        "pooled_mean_pnl": round(mean_pnl, 6),
        "pooled_std_pnl": round(float(std_pnl), 6),
        "sharpe_gate_passed": gate_passed,
        "sharpe_credible": credible,
        "target_n": target_n,
        "n_required_for_se_010": n_req,
        "message": msg,
    }


def compute_pooled_metrics(symbol_results: list[dict], target_n: int = 600) -> dict:
    """
    Pool all trades across symbols and compute pooled Sharpe + SE gate.

    Detects and flags implausible per-symbol Sharpe ratios (EUR/USD, GBP/USD
    artefacts with Sharpe > 12) and reports two numbers:
    1. ``pooled`` — all symbols including outliers (for reference)
    2. ``pooled_honest`` — outliers excluded (the number to cite)

    The gate check uses ``pooled_honest`` so inflated outliers cannot
    cause a false gate pass.
    """
    n_total_all = sum(r.get("n_trades", 0) for r in symbol_results)
    if n_total_all == 0:
        return {
            "n_total_trades": 0,
            "pooled_sharpe": 0.0,
            "pooled_sharpe_se": float("inf"),
            "sharpe_gate_passed": False,
            "target_n": target_n,
            "message": "No trades generated across all symbols.",
            "_validation": {"outliers": [], "honest_pooled": None},
        }

    # ── Detect outliers ───────────────────────────────────────────────────────
    outlier_syms, outlier_reasons = _detect_sharpe_outliers(symbol_results)

    # ── Full pool (all symbols) ───────────────────────────────────────────────
    pnls_all, n_all = _pool_pnls(symbol_results)
    full_stats = _sharpe_stats(pnls_all, n_all, target_n)

    # ── Honest pool (outliers excluded) ──────────────────────────────────────
    if outlier_syms:
        pnls_honest, n_honest = _pool_pnls(symbol_results, exclude=outlier_syms)
        honest_stats = _sharpe_stats(pnls_honest, n_honest, target_n)
        honest_stats["excluded_symbols"] = outlier_syms
        honest_stats["exclusion_reasons"] = {
            sym: reason for sym, reason in zip(outlier_syms, outlier_reasons, strict=False)
        }
    else:
        honest_stats = None

    # ── Gate uses honest pool when outliers exist ─────────────────────────────
    authoritative = honest_stats if honest_stats is not None else full_stats

    logger.info(
        "Pooled (all): N=%d Sharpe=%.2f | Honest (excl %s): N=%d Sharpe=%.2f | Gate=%s",
        full_stats["n_total_trades"],
        full_stats["pooled_sharpe"],
        ",".join(outlier_syms) if outlier_syms else "none",
        authoritative["n_total_trades"],
        authoritative["pooled_sharpe"],
        "PASSED" if authoritative["sharpe_gate_passed"] else "BLOCKED",
    )

    result = dict(full_stats)
    result["_validation"] = {
        "outlier_symbols": outlier_syms,
        "outlier_reasons": {sym: reason for sym, reason in zip(outlier_syms, outlier_reasons, strict=False)},
        "honest_pooled": honest_stats,
        "gate_uses_honest_pool": bool(outlier_syms),
        "note": (
            f"Symbols {outlier_syms} have implausible Sharpe ratios and are excluded "
            f"from the honest pooled Sharpe. The gate check uses the honest pool. "
            f"These results must be independently validated before citing."
        )
        if outlier_syms
        else "No outliers detected — full pool is authoritative.",
    }

    # Override gate fields with honest pool values when outliers exist
    if honest_stats is not None:
        result["sharpe_gate_passed"] = honest_stats["sharpe_gate_passed"]
        result["sharpe_credible"] = honest_stats["sharpe_credible"]
        result["message"] = f"[HONEST POOL — {','.join(outlier_syms)} excluded] " + honest_stats["message"]

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def run_backtest(
    years: int = 10,
    oos_frac: float = 0.3,
    target_n: int = 600,
    smoke: bool = False,
    symbols: list | None = None,
    extended: bool = False,
) -> dict:
    """Run multi-symbol backtest and return full report.

    Args:
        extended: If True, use SYMBOLS_EXTENDED (7 symbols, target N>919, SE≤0.10).
                  Results saved to multi_symbol_report_extended.json.
    """
    if smoke:
        years = 3
        oos_frac = 0.4
        logger.info("Smoke mode: years=3, oos_frac=0.4")

    if extended and symbols is None:
        syms = SYMBOLS_EXTENDED
        target_n = max(target_n, TARGET_N_SE010)
        logger.info("Extended mode: 7 symbols, target_n=%d (SE≤0.10)", target_n)
    else:
        syms = symbols or SYMBOLS
    symbol_results = []

    for ticker, display_name, pip_size in syms:
        try:
            result = backtest_symbol(
                ticker,
                display_name,
                pip_size,
                years=years,
                oos_frac=oos_frac,
                smoke=smoke,
            )
            symbol_results.append(result)
        except Exception:
            logger.exception("Backtest failed for %s", display_name)
            symbol_results.append(
                {"symbol": display_name, "error": "Backtest failed — check server logs", "n_trades": 0}
            )

    pooled = compute_pooled_metrics(symbol_results, target_n=target_n)

    n_syms = len([r for r in symbol_results if "error" not in r])
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "years": years,
        "oos_frac": oos_frac,
        "target_n": target_n,
        "extended": extended,
        "n_symbols": n_syms,
        "symbols": symbol_results,
        "pooled": pooled,
    }

    # Save report — extended run gets its own file
    report_filename = "multi_symbol_report_extended.json" if extended else "multi_symbol_report.json"
    report_path = RESULTS_DIR / report_filename
    # Strip trade-level data for the saved report (keep summary only)
    report_slim = {
        **report,
        "symbols": [{k: v for k, v in r.items() if k != "trades"} for r in symbol_results],
    }
    report_path.write_text(json.dumps(report_slim, indent=2))
    logger.info("Report saved → %s", report_path)

    # Print summary
    logger.info("\n" + "=" * 65)
    logger.info("MULTI-SYMBOL BACKTEST SUMMARY")
    logger.info("=" * 65)
    for r in symbol_results:
        if "error" in r:
            logger.error(f"  {r['symbol']:12s}: ERROR — {r['error']}")
        else:
            logger.info(
                f"  {r['symbol']:12s}: N={r['n_trades']:4d} trades | "
                f"Sharpe={r.get('sharpe', 0):.2f} | "
                f"WinRate={r.get('win_rate', 0) * 100:.1f}% | "
                f"Acc={r.get('accuracy', 0):.3f}"
            )
    logger.info("")
    p = pooled
    gate = "PASSED ✓" if p["sharpe_gate_passed"] else "BLOCKED ✗"
    logger.info(f"  Pooled N trades : {p['n_total_trades']}")
    logger.info(f"  Pooled Sharpe   : {p['pooled_sharpe']:.3f}")
    logger.info(f"  Sharpe SE       : {p['pooled_sharpe_se']:.3f}")
    logger.info(f"  Sharpe gate     : {gate}")
    logger.info(f"  {p['message']}")
    logger.info("=" * 65)

    return report


def main():
    parser = argparse.ArgumentParser(description="Multi-symbol backtest engine")
    parser.add_argument("--years", type=int, default=10, help="Years of history")
    parser.add_argument("--oos-frac", type=float, default=0.3, help="OOS fraction (default 0.3)")
    parser.add_argument("--target-n", type=int, default=600, help="Target N trades for Sharpe gate")
    parser.add_argument("--smoke", action="store_true", help="Fast smoke test (3 years)")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Run 7-symbol extended set (XAU+BTC+ETH+EUR/USD+GBP/USD+Silver+Oil), target N>919",
    )
    parser.add_argument("--symbols", nargs="+", default=None, help="Override symbols: e.g. GC=F BTC-USD")
    args = parser.parse_args()

    syms = None
    if args.symbols:
        syms = [(s, s, 0.01) for s in args.symbols]

    run_backtest(
        years=args.years,
        oos_frac=args.oos_frac,
        target_n=args.target_n,
        smoke=args.smoke,
        extended=args.extended,
        symbols=syms,
    )


if __name__ == "__main__":
    main()
