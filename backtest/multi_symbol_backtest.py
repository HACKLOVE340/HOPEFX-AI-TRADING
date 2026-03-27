# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/multi_symbol_backtest.py
==================================
Multi-symbol backtest engine targeting N=600 trades for Sharpe credibility.

Symbols
-------
- XAU/USD  (GC=F  — gold futures, primary)
- BTC/USD  (BTC-USD — crypto, high-vol regime)
- ETH/USD  (ETH-USD — crypto, correlated to BTC)

Why N=600?
----------
Sharpe SE = sqrt((1 + 0.5*SR²) / T).
At SR=1.52, T=48:  SE=0.21 — not credible.
At SR=1.52, T=600: SE=0.06 — credible (95% CI: ±0.12).
Multi-symbol pooling achieves N=600 faster than single-symbol.

Architecture
------------
1. Fetch OHLCV for each symbol (yfinance, with CSV cache fallback)
2. Build 200+ features per symbol (features_extended.py)
3. Train a per-symbol model on the first (1 - oos_frac) of data
4. Walk-forward OOS backtest on the last oos_frac
5. Pool all OOS trades across symbols → compute pooled Sharpe + SE
6. Sharpe gate check: gate_passed when N >= target_n
7. Save results to backtest/results/multi_symbol_report.json

Usage
-----
    python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
    python backtest/multi_symbol_backtest.py --smoke   # fast CI run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "backtest" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Symbol config: (yfinance_ticker, display_name, pip_size)
SYMBOLS = [
    ("GC=F",    "XAU/USD", 0.01),
    ("BTC-USD", "BTC/USD", 1.0),
    ("ETH-USD", "ETH/USD", 0.1),
]


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, years: int, smoke: bool = False) -> pd.DataFrame:
    """Fetch daily OHLCV from yfinance with CSV cache fallback."""
    cache_path = ROOT / "data" / f"{ticker.replace('=','_').replace('-','_')}_{years}Y.csv"

    if cache_path.exists():
        try:
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]
            if len(df) > 50:
                logger.info("Loaded %s from cache: %d bars", ticker, len(df))
                return df
        except Exception:
            pass

    try:
        import yfinance as yf
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=years * 365)
        interval = "1d"
        df = yf.download(ticker, start=start, end=end, interval=interval,
                         auto_adjust=True, progress=False)
        if df.empty:
            raise ValueError(f"No data returned for {ticker}")
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index, utc=True)
        # Cache for next run
        try:
            df.to_csv(cache_path)
        except Exception:
            pass
        logger.info("Downloaded %s: %d bars", ticker, len(df))
        return df
    except Exception as exc:
        logger.warning("Could not fetch %s: %s — generating synthetic data", ticker, exc)
        return _synthetic_ohlcv(ticker, years, smoke)


def _synthetic_ohlcv(ticker: str, years: int, smoke: bool) -> pd.DataFrame:
    """Generate synthetic OHLCV for testing when yfinance is unavailable."""
    n = 500 if smoke else years * 252
    np.random.seed(abs(hash(ticker)) % 2**31)
    base = 1800.0 if "GC" in ticker else (40000.0 if "BTC" in ticker else 2500.0)
    returns = np.random.randn(n) * 0.015
    close = base * np.exp(np.cumsum(returns))
    idx = pd.date_range(end=datetime.now(timezone.utc).date(), periods=n, freq="B", tz="UTC")
    df = pd.DataFrame({
        "open":   close * (1 + np.random.randn(n) * 0.002),
        "high":   close * (1 + abs(np.random.randn(n)) * 0.008),
        "low":    close * (1 - abs(np.random.randn(n)) * 0.008),
        "close":  close,
        "volume": abs(np.random.randn(n)) * 1e6 + 1e5,
    }, index=idx)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Feature building
# ─────────────────────────────────────────────────────────────────────────────

def build_features(ohlcv: pd.DataFrame, smoke: bool = False) -> Tuple[pd.DataFrame, pd.Series]:
    """Build feature matrix using extended 200+ feature builder."""
    try:
        from ml.features_extended import build_extended_features
        return build_extended_features(
            ohlcv,
            macro_df=None,
            horizon=1,
            use_filtered_target=not smoke,
            min_move_atr=0.15 if not smoke else 0.0,
        )
    except Exception as exc:
        logger.warning("Extended features failed, using base: %s", exc)
        from ml.advanced_features import build_advanced_features
        return build_advanced_features(
            ohlcv, macro_df=None, horizon=1,
            use_filtered_target=not smoke, min_move_atr=0.15,
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
) -> Dict:
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
    X_oos,   y_oos   = X.iloc[-oos_n:], y.iloc[-oos_n:]

    if len(X_train) < 30:
        return {"symbol": display_name, "error": "train set too small", "n_trades": 0}

    # Train calibrated XGBoost
    n_est = 100 if smoke else 400
    base = xgb.XGBClassifier(
        n_estimators=n_est, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
        scale_pos_weight=float((y_train == 0).sum()) / max((y_train == 1).sum(), 1),
        eval_metric="logloss", random_state=42, n_jobs=-1,
    )
    cal = CalibratedClassifierCV(base, method="isotonic", cv=3)
    model = Pipeline([("scaler", StandardScaler()), ("model", cal)])
    model.fit(X_train, y_train)

    # OOS predictions
    proba = model.predict_proba(X_oos)[:, 1]
    preds = (proba >= 0.55).astype(int)  # threshold: 0.55 for signal

    # Align OOS prices for PnL calculation
    oos_close = ohlcv["close"].reindex(X_oos.index)

    # Simulate trades: enter on signal, exit next bar
    trades = []
    for i in range(len(X_oos) - 1):
        if proba[i] >= 0.58:   # long signal
            entry = float(oos_close.iloc[i])
            exit_  = float(oos_close.iloc[i + 1])
            pnl_pct = (exit_ - entry) / entry
            trades.append({"direction": "long",  "pnl_pct": pnl_pct, "prob": float(proba[i])})
        elif proba[i] <= 0.42:  # short signal
            entry = float(oos_close.iloc[i])
            exit_  = float(oos_close.iloc[i + 1])
            pnl_pct = (entry - exit_) / entry
            trades.append({"direction": "short", "pnl_pct": pnl_pct, "prob": float(proba[i])})

    n_trades = len(trades)
    if n_trades == 0:
        return {"symbol": display_name, "n_trades": 0, "sharpe": 0.0, "accuracy": 0.5}

    pnls = np.array([t["pnl_pct"] for t in trades])
    wins = (pnls > 0).sum()
    win_rate = wins / n_trades
    mean_pnl = pnls.mean()
    std_pnl  = pnls.std(ddof=1) if n_trades > 1 else 1e-6
    sharpe   = float(mean_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0
    max_dd   = _max_drawdown(pnls)

    # Classification metrics
    acc = accuracy_score(y_oos, (proba >= 0.5).astype(int))
    f1  = f1_score(y_oos, (proba >= 0.5).astype(int), zero_division=0)
    try:
        auc = roc_auc_score(y_oos, proba)
    except Exception:
        auc = 0.5

    logger.info(
        "%s: N=%d trades | Sharpe=%.2f | WinRate=%.1f%% | Acc=%.3f | MaxDD=%.1f%%",
        display_name, n_trades, sharpe, win_rate * 100, acc, max_dd * 100,
    )

    return {
        "symbol": display_name,
        "ticker": ticker,
        "n_trades": n_trades,
        "win_rate": round(win_rate, 4),
        "mean_pnl_pct": round(float(mean_pnl), 6),
        "std_pnl_pct":  round(float(std_pnl), 6),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(float(max_dd), 4),
        "accuracy": round(acc, 4),
        "f1": round(f1, 4),
        "auc": round(auc, 4),
        "oos_bars": len(X_oos),
        "train_bars": len(X_train),
        "feature_count": X.shape[1],
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

def compute_pooled_metrics(symbol_results: List[Dict], target_n: int = 600) -> Dict:
    """
    Pool all trades across symbols and compute pooled Sharpe + SE gate.

    Pooling is valid when symbols are not perfectly correlated (XAU, BTC, ETH
    have low pairwise correlation on daily returns).
    """
    all_pnls = []
    for r in symbol_results:
        if "trades" in r:
            all_pnls.extend([t["pnl_pct"] for t in r["trades"]])

    n_total = sum(r.get("n_trades", 0) for r in symbol_results)

    if n_total == 0 or not all_pnls:
        return {
            "n_total_trades": 0,
            "pooled_sharpe": 0.0,
            "pooled_sharpe_se": float("inf"),
            "sharpe_gate_passed": False,
            "target_n": target_n,
            "message": "No trades generated across all symbols.",
        }

    pnls = np.array(all_pnls)
    mean_pnl = pnls.mean()
    std_pnl  = pnls.std(ddof=1) if len(pnls) > 1 else 1e-6
    pooled_sharpe = float(mean_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0

    # Sharpe SE: sqrt((1 + 0.5*SR²) / T)
    sr = abs(pooled_sharpe)
    se = float(np.sqrt((1 + 0.5 * sr ** 2) / max(n_total, 1)))

    gate_passed = n_total >= target_n
    credible    = se <= 0.10

    if gate_passed and credible:
        msg = f"Sharpe gate PASSED: N={n_total} >= {target_n}, SE={se:.3f} <= 0.10"
    else:
        n_required = int(np.ceil((1 + 0.5 * sr ** 2) / 0.01))
        msg = (
            f"Sharpe gate BLOCKED: N={n_total} trades, SE={se:.3f}. "
            f"Need N>={target_n} (SE<=0.10 requires N>={n_required})."
        )

    logger.info("Pooled: N=%d | Sharpe=%.2f | SE=%.3f | Gate=%s",
                n_total, pooled_sharpe, se, "PASSED" if gate_passed else "BLOCKED")

    return {
        "n_total_trades": n_total,
        "pooled_sharpe": round(pooled_sharpe, 4),
        "pooled_sharpe_se": round(se, 4),
        "pooled_mean_pnl": round(float(mean_pnl), 6),
        "pooled_std_pnl":  round(float(std_pnl), 6),
        "sharpe_gate_passed": gate_passed,
        "sharpe_credible": credible,
        "target_n": target_n,
        "n_required_for_se_010": int(np.ceil((1 + 0.5 * sr ** 2) / 0.01)),
        "message": msg,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(
    years: int = 10,
    oos_frac: float = 0.3,
    target_n: int = 600,
    smoke: bool = False,
    symbols: Optional[List] = None,
) -> Dict:
    """Run multi-symbol backtest and return full report."""
    if smoke:
        years = 3
        oos_frac = 0.4
        logger.info("Smoke mode: years=3, oos_frac=0.4")

    syms = symbols or SYMBOLS
    symbol_results = []

    for ticker, display_name, pip_size in syms:
        try:
            result = backtest_symbol(
                ticker, display_name, pip_size,
                years=years, oos_frac=oos_frac, smoke=smoke,
            )
            symbol_results.append(result)
        except Exception as exc:
            logger.error("Backtest failed for %s: %s", display_name, exc)
            symbol_results.append({"symbol": display_name, "error": str(exc), "n_trades": 0})

    pooled = compute_pooled_metrics(symbol_results, target_n=target_n)

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "years": years,
        "oos_frac": oos_frac,
        "target_n": target_n,
        "symbols": symbol_results,
        "pooled": pooled,
    }

    # Save report
    report_path = RESULTS_DIR / "multi_symbol_report.json"
    # Strip trade-level data for the saved report (keep summary only)
    report_slim = {
        **report,
        "symbols": [
            {k: v for k, v in r.items() if k != "trades"}
            for r in symbol_results
        ],
    }
    report_path.write_text(json.dumps(report_slim, indent=2))
    logger.info("Report saved → %s", report_path)

    # Print summary
    print("\n" + "=" * 65)
    print("MULTI-SYMBOL BACKTEST SUMMARY")
    print("=" * 65)
    for r in symbol_results:
        if "error" in r:
            print(f"  {r['symbol']:12s}: ERROR — {r['error']}")
        else:
            print(
                f"  {r['symbol']:12s}: N={r['n_trades']:4d} trades | "
                f"Sharpe={r.get('sharpe', 0):.2f} | "
                f"WinRate={r.get('win_rate', 0)*100:.1f}% | "
                f"Acc={r.get('accuracy', 0):.3f}"
            )
    print()
    p = pooled
    gate = "PASSED ✓" if p["sharpe_gate_passed"] else "BLOCKED ✗"
    print(f"  Pooled N trades : {p['n_total_trades']}")
    print(f"  Pooled Sharpe   : {p['pooled_sharpe']:.3f}")
    print(f"  Sharpe SE       : {p['pooled_sharpe_se']:.3f}")
    print(f"  Sharpe gate     : {gate}")
    print(f"  {p['message']}")
    print("=" * 65)

    return report


def main():
    parser = argparse.ArgumentParser(description="Multi-symbol backtest engine")
    parser.add_argument("--years",    type=int,   default=10,  help="Years of history")
    parser.add_argument("--oos-frac", type=float, default=0.3, help="OOS fraction (default 0.3)")
    parser.add_argument("--target-n", type=int,   default=600, help="Target N trades for Sharpe gate")
    parser.add_argument("--smoke",    action="store_true",     help="Fast smoke test (3 years)")
    parser.add_argument("--symbols",  nargs="+",  default=None,
                        help="Override symbols: e.g. GC=F BTC-USD")
    args = parser.parse_args()

    syms = None
    if args.symbols:
        syms = [(s, s, 0.01) for s in args.symbols]

    run_backtest(
        years=args.years,
        oos_frac=args.oos_frac,
        target_n=args.target_n,
        smoke=args.smoke,
        symbols=syms,
    )


if __name__ == "__main__":
    main()
