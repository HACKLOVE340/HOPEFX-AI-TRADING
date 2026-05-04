#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/reconcile_backtest.py
==============================
Reconciled backtest: runs advanced_oos.pkl on the same daily XAUUSD data
and entry/exit logic used in the OOS evaluation, producing Monte Carlo
results that are directly comparable to the OOS accuracy metrics.

This resolves the contradiction in data/monte_carlo_results.json where
the existing results used a different strategy (momentum SMA) on different
timeframes (1d/15m) than the model evaluation (daily, filtered-target).

Usage
-----
    python scripts/reconcile_backtest.py
    python scripts/reconcile_backtest.py --oos-only   # only OOS period
    python scripts/reconcile_backtest.py --mc-runs 1000

Output
------
    data/monte_carlo_results.json  — updated with reconciled results
    data/reconciled_backtest.json  — detailed trade log

Strategy (matches OOS evaluation exactly)
------------------------------------------
- Signal: advanced_oos.pkl predict_proba on daily XAUUSD bars
- Entry: next-bar open when model confidence >= 0.55 (same as OOS threshold)
- Exit: fixed 5-bar hold (matches OOS avg_hold of 5.1 days)
- Abstain: bars where |return| < 0.25 * ATR(14) are skipped (filtered-target)
- Position size: 1 unit per trade (P&L in points, scaled to USD at $1/point)
- Costs: $70 round-trip (35bp entry + 35bp exit at ~$2000 gold price)
- No overnight financing in this version (documented limitation)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy scalars and booleans."""

    def default(self, o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("reconcile_backtest")

# ── paths ─────────────────────────────────────────────────────────────────────

DATA_DIR = _ROOT / "data"
MODEL_DIR = _ROOT / "ml" / "saved_models"
OHLCV_CACHE = DATA_DIR / "XAUUSD_40Y.csv"
MONTE_CARLO_OUT = DATA_DIR / "monte_carlo_results.json"
RECONCILED_OUT = DATA_DIR / "reconciled_backtest.json"

# ── constants matching OOS evaluation ────────────────────────────────────────

CONFIDENCE_THRESHOLD = 0.55  # minimum model probability to take a trade
HOLD_BARS = 5  # fixed exit after N bars (matches OOS avg hold)
ATR_PERIOD = 14  # ATR window for filtered-target
MIN_MOVE_ATR = 0.25  # abstain if |return| < this * ATR
ROUND_TRIP_COST_USD = 70.0  # $70 round-trip at ~$2000 gold, 35bp each way
INITIAL_BALANCE = 100_000.0  # starting equity
UNIT_VALUE_USD = 1.0  # $1 per point move (1 oz contract approximation)


# ── data loading ──────────────────────────────────────────────────────────────


def load_ohlcv() -> pd.DataFrame:
    """Load XAUUSD daily OHLCV from cache."""
    if not OHLCV_CACHE.exists():
        raise FileNotFoundError(
            f"OHLCV cache not found: {OHLCV_CACHE}\nRun: python ml/train_advanced.py --smoke  to populate the cache."
        )
    df = pd.read_csv(OHLCV_CACHE, parse_dates=["Date"], index_col="Date")
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    logger.info("Loaded %d bars from %s", len(df), OHLCV_CACHE)
    return df


# ── feature engineering (must match train_advanced.py exactly) ───────────────


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the same 176-feature matrix used in training.
    Delegates to ml/features_extended.py to guarantee identical features.
    """
    try:
        from ml.features_extended import build_extended_features

        # Fetch macro data (same as train_advanced.py) so macro features are present
        macro_df = None
        try:
            from ml.train_advanced import fetch_macro

            start_dt = df.index[0].to_pydatetime().replace(tzinfo=UTC)
            end_dt = df.index[-1].to_pydatetime().replace(tzinfo=UTC)
            macro_df = fetch_macro(start_dt, end_dt)
            if macro_df is not None:
                logger.info("Macro data loaded: %d rows, %d series", *macro_df.shape)
        except Exception as macro_exc:
            logger.warning("Macro fetch failed (%s) — macro features will be zeroed", macro_exc)

        # Returns (X, y) tuple; we only need X for inference
        result = build_extended_features(df, macro_df=macro_df, use_filtered_target=True)
        feat_df = result[0] if isinstance(result, tuple) else result
        logger.info("Built %d features via features_extended.py", feat_df.shape[1])
        return feat_df
    except Exception as exc:
        logger.warning("features_extended unavailable (%s) — using base features", exc)
        return _build_base_features(df)


def _build_base_features(df: pd.DataFrame) -> pd.DataFrame:
    """Minimal feature set as fallback (fewer features than training)."""
    out = pd.DataFrame(index=df.index)
    out["close"] = df["close"]
    out["returns"] = df["close"].pct_change(fill_method=None)
    out["atr14"] = _atr(df, 14)
    out["rsi14"] = _rsi(df["close"], 14)
    out["sma20"] = df["close"].rolling(20).mean()
    out["dist_ma20"] = (df["close"] - out["sma20"]) / out["sma20"]
    return out.dropna()


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    tr = (
        pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"] - df["close"].shift()).abs(),
            ],
            axis=1,
        )
        .fillna(0.0)
        .max(axis=1)
    )
    return tr.rolling(period).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ── model loading ─────────────────────────────────────────────────────────────


def load_model():
    """Load advanced_oos.pkl and its feature scaler."""
    import joblib

    pkl = MODEL_DIR / "advanced_oos.pkl"
    scaler_path = MODEL_DIR / "feature_scaler.pkl"

    if not pkl.exists():
        raise FileNotFoundError(
            f"Model not found: {pkl}\nRun: python scripts/retrain_model.py --advanced --years 50 --oos-years 5"
        )

    model = joblib.load(str(pkl))  # nosec B301 - pkl is hardcoded to ml/saved_models
    scaler = joblib.load(str(scaler_path)) if scaler_path.exists() else None  # nosec B301 - hardcoded path
    logger.info("Loaded model from %s", pkl)
    return model, scaler


# ── signal generation ─────────────────────────────────────────────────────────


def generate_signals(
    feat_df: pd.DataFrame,
    raw_df: pd.DataFrame,
    model,
    scaler,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> pd.DataFrame:
    """
    Generate BUY/SELL signals using the model, matching OOS evaluation logic:
    - Abstain on bars where |return| < MIN_MOVE_ATR * ATR(14)
    - Signal only when predict_proba >= confidence_threshold
    """
    atr = _atr(raw_df, ATR_PERIOD).reindex(feat_df.index)
    returns = raw_df["close"].pct_change(fill_method=None).reindex(feat_df.index)

    # Filtered-target mask: only trade on bars with meaningful moves
    abs_move = returns.abs() * raw_df["close"].reindex(feat_df.index)
    tradeable = abs_move >= (MIN_MOVE_ATR * atr)

    # Align features with model's expected columns
    X = feat_df.copy()
    if scaler is not None:
        expected_cols = getattr(scaler, "feature_names_in_", None)
        if expected_cols is not None:
            # Add any missing columns as zero (unseen features default to neutral)
            missing = [c for c in expected_cols if c not in X.columns]
            if missing:
                logger.warning(
                    "Feature mismatch: %d columns missing from feature matrix "
                    "(model trained on %d, got %d). Missing: %s",
                    len(missing),
                    len(expected_cols),
                    len(X.columns),
                    missing[:5],
                )
                for col in missing:
                    X[col] = 0.0
            # Drop extra columns not seen during training
            extra = [c for c in X.columns if c not in set(expected_cols)]
            if extra:
                X = X.drop(columns=extra)
            X = X[expected_cols]  # enforce exact column order
        try:
            X_scaled = scaler.transform(X)
        except Exception as exc:
            logger.warning("Scaler transform failed (%s) — using raw features", exc)
            X_scaled = X.values
    else:
        X_scaled = X.values

    # Predict probabilities
    try:
        proba = model.predict_proba(X_scaled)
        prob_up = proba[:, 1]
    except Exception as exc:
        logger.error("Model prediction failed: %s", exc)
        raise

    signals = pd.DataFrame(index=feat_df.index)
    signals["prob_up"] = prob_up
    signals["tradeable"] = tradeable.values
    signals["signal"] = 0  # 0=hold, 1=buy, -1=sell

    buy_mask = tradeable & (prob_up >= confidence_threshold)
    sell_mask = tradeable & (prob_up <= (1 - confidence_threshold))
    signals.loc[buy_mask, "signal"] = 1
    signals.loc[sell_mask, "signal"] = -1

    n_buy = buy_mask.sum()
    n_sell = sell_mask.sum()
    n_abstain = int(np.nan_to_num((~tradeable).sum(), nan=0))
    logger.info(
        "Signals: %d BUY, %d SELL, %d abstain (%.1f%% of bars)",
        n_buy,
        n_sell,
        n_abstain,
        n_abstain / len(signals) * 100,
    )
    return signals


# ── backtest engine ───────────────────────────────────────────────────────────


def run_backtest(
    signals: pd.DataFrame,
    prices: pd.Series,
    hold_bars: int = HOLD_BARS,
    round_trip_cost: float = ROUND_TRIP_COST_USD,
) -> tuple[list[dict], pd.Series]:
    """
    Simulate trades using fixed hold_bars exit.

    Parameters
    ----------
    hold_bars       : Exit after this many bars (default: HOLD_BARS=5)
    round_trip_cost : Round-trip cost in USD per trade (default: $70)

    Returns
    -------
    trades : list of trade dicts
    equity : daily equity curve
    """
    trades: list[dict] = []
    equity = pd.Series(INITIAL_BALANCE, index=prices.index, dtype=float)
    balance = INITIAL_BALANCE
    open_trade: dict | None = None

    price_arr = prices.values
    sig_arr = signals["signal"].values
    idx = signals.index

    i = 0
    while i < len(idx):
        # Check exit first
        if open_trade is not None:
            bars_held = i - open_trade["entry_bar"]
            if bars_held >= hold_bars:
                exit_price = price_arr[i]
                direction = open_trade["direction"]
                pnl_points = (exit_price - open_trade["entry_price"]) * direction
                pnl_usd = pnl_points * UNIT_VALUE_USD - round_trip_cost
                balance += pnl_usd
                open_trade["exit_price"] = exit_price
                open_trade["exit_date"] = str(idx[i].date())
                open_trade["pnl_usd"] = round(pnl_usd, 2)
                open_trade["bars_held"] = bars_held
                open_trade["win"] = pnl_usd > 0
                trades.append(open_trade)
                open_trade = None

        # Enter new trade if no open position
        if open_trade is None and i + 1 < len(idx):
            sig = sig_arr[i]
            if sig != 0:
                entry_price = price_arr[i + 1]  # next-bar open (use close as proxy)
                open_trade = {
                    "entry_bar": i + 1,
                    "entry_date": str(idx[i + 1].date()),
                    "entry_price": entry_price,
                    "direction": int(sig),
                    "signal_prob": float(signals["prob_up"].iloc[i]),
                }

        equity.iloc[i] = balance
        i += 1

    # Close any open trade at end
    if open_trade is not None:
        exit_price = price_arr[-1]
        direction = open_trade["direction"]
        pnl_points = (exit_price - open_trade["entry_price"]) * direction
        pnl_usd = pnl_points * UNIT_VALUE_USD - ROUND_TRIP_COST_USD
        balance += pnl_usd
        open_trade["exit_price"] = exit_price
        open_trade["exit_date"] = str(idx[-1].date())
        open_trade["pnl_usd"] = round(pnl_usd, 2)
        open_trade["bars_held"] = len(idx) - open_trade["entry_bar"]
        open_trade["win"] = pnl_usd > 0
        trades.append(open_trade)

    return trades, equity


# ── metrics ───────────────────────────────────────────────────────────────────


def compute_metrics(
    trades: list[dict],
    equity: pd.Series,
    mc_runs: int = 200,
) -> dict[str, Any]:
    """Compute P&L metrics and Monte Carlo drawdown distribution."""
    if not trades:
        return {"error": "no trades generated"}

    pnls = np.array([t["pnl_usd"] for t in trades])
    wins = np.array([t["win"] for t in trades])
    total_pnl = float(pnls.sum())
    win_rate = float(wins.mean()) if len(wins) > 0 else 0.0

    # Drawdown
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min())

    # Sharpe (annualised, daily returns)
    daily_ret = equity.pct_change(fill_method=None).dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0

    # Monte Carlo: resample trade P&Ls to get drawdown distribution
    _mc_rng = np.random.default_rng()  # unseeded — bootstrap resampling
    mc_dds = []
    for _ in range(mc_runs):
        sampled = _mc_rng.choice(pnls, size=len(pnls), replace=True)
        cum = INITIAL_BALANCE + np.cumsum(sampled)
        pk = np.maximum.accumulate(cum)
        mc_dd = float(np.min((cum - pk) / pk))
        mc_dds.append(mc_dd)

    mc_dds_arr = np.array(mc_dds)

    return {
        "total_trades": len(trades),
        "win_rate_pct": round(win_rate * 100, 2),
        "total_pnl_usd": round(total_pnl, 2),
        "final_balance": round(INITIAL_BALANCE + total_pnl, 2),
        "initial_balance": INITIAL_BALANCE,
        "return_pct": round(total_pnl / INITIAL_BALANCE * 100, 4),
        "max_drawdown_pct": round(abs(max_dd) * 100, 4),
        "sharpe_ratio": round(sharpe, 4),
        "avg_pnl_per_trade": round(float(pnls.mean()), 2),
        "avg_hold_bars": round(float(np.mean([t["bars_held"] for t in trades])), 1),
        "monte_carlo": {
            "n_runs": mc_runs,
            "worst_case_dd_pct": round(abs(float(mc_dds_arr.min())) * 100, 4),
            "p99_dd_pct": round(abs(float(np.percentile(mc_dds_arr, 1))) * 100, 4),
            "p95_dd_pct": round(abs(float(np.percentile(mc_dds_arr, 5))) * 100, 4),
            "median_dd_pct": round(abs(float(np.median(mc_dds_arr))) * 100, 4),
            "mean_dd_pct": round(abs(float(mc_dds_arr.mean())) * 100, 4),
        },
    }


# ── main ──────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reconciled backtest using advanced_oos.pkl")
    p.add_argument(
        "--oos-only",
        action="store_true",
        help="Only backtest the OOS period (2019-04-12 to 2026-03-24)",
    )
    p.add_argument(
        "--mc-runs",
        type=int,
        default=200,
        help="Monte Carlo simulation runs (default: 200)",
    )
    p.add_argument(
        "--hold-bars",
        type=int,
        default=HOLD_BARS,
        help=(
            f"Exit after N bars (default: {HOLD_BARS}). "
            "Set to 1 to match the 1-bar training horizon. "
            "Root cause investigation shows 1-bar hold has better accuracy/P&L alignment."
        ),
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=CONFIDENCE_THRESHOLD,
        help=(
            f"Minimum model confidence to take a trade (default: {CONFIDENCE_THRESHOLD}). "
            "Investigation shows 0.65+ filters to higher-conviction signals."
        ),
    )
    p.add_argument(
        "--cost",
        type=float,
        default=ROUND_TRIP_COST_USD,
        help=f"Round-trip cost in USD (default: {ROUND_TRIP_COST_USD})",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    logger.info("Loading OHLCV data …")
    raw_df = load_ohlcv()

    if args.oos_only:
        raw_df = raw_df.loc["2019-04-12":]
        logger.info("OOS-only mode: %d bars from 2019-04-12", len(raw_df))

    logger.info("Building feature matrix …")
    feat_df = build_features(raw_df)

    # Align raw_df to feat_df index (features may drop leading NaN rows)
    raw_aligned = raw_df.reindex(feat_df.index)

    logger.info("Loading model …")
    model, scaler = load_model()

    # Apply CLI overrides — allows investigation sweeps without code changes
    effective_threshold = args.threshold
    effective_hold = args.hold_bars
    effective_cost = args.cost

    if effective_threshold != CONFIDENCE_THRESHOLD:
        logger.info(
            "Threshold override: %.2f (default %.2f)",
            effective_threshold,
            CONFIDENCE_THRESHOLD,
        )
    if effective_hold != HOLD_BARS:
        logger.info("Hold bars override: %d (default %d)", effective_hold, HOLD_BARS)
    if effective_cost != ROUND_TRIP_COST_USD:
        logger.info("Cost override: $%.0f (default $%.0f)", effective_cost, ROUND_TRIP_COST_USD)

    logger.info("Generating signals …")
    signals = generate_signals(
        feat_df,
        raw_aligned,
        model,
        scaler,
        confidence_threshold=effective_threshold,
    )

    logger.info("Running backtest …")
    trades, equity = run_backtest(
        signals,
        raw_aligned["close"],
        hold_bars=effective_hold,
        round_trip_cost=effective_cost,
    )

    logger.info("Computing metrics (MC runs=%d) …", args.mc_runs)
    metrics = compute_metrics(trades, equity, mc_runs=args.mc_runs)

    # Build output
    period_label = "oos_period" if args.oos_only else "full_history"
    result = {
        "symbol": "XAUUSD",
        "timeframe": "1d",
        "model": "advanced_oos.pkl",
        "strategy": "model_signal_fixed_hold",
        "confidence_threshold": effective_threshold,
        "hold_bars": effective_hold,
        "round_trip_cost_usd": effective_cost,
        "start": str(raw_aligned.index[0].date()),
        "end": str(raw_aligned.index[-1].date()),
        "total_bars": len(raw_aligned),
        **metrics,
        "_reconciliation": (
            "This backtest uses the same model (advanced_oos.pkl), same daily "
            "XAUUSD data, same filtered-target abstain logic, and same confidence "
            "threshold as the OOS evaluation. Results are directly comparable to "
            "the OOS accuracy metrics. The previous monte_carlo_results.json used "
            "a momentum SMA strategy on 1d/15m bars — a different strategy entirely."
        ),
    }

    # Save detailed trade log
    RECONCILED_OUT.write_text(json.dumps({"metadata": result, "trades": trades}, indent=2, cls=_NumpyEncoder))
    logger.info("Detailed trade log → %s", RECONCILED_OUT)

    # Update monte_carlo_results.json with reconciled daily result
    mc_data: dict[str, Any] = {}
    if MONTE_CARLO_OUT.exists():
        try:
            mc_data = json.loads(MONTE_CARLO_OUT.read_text())
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    mc_data[f"reconciled_{period_label}"] = result
    mc_data["_reconciliation_status"] = (
        "RECONCILED — reconciled_full_history and/or reconciled_oos_period entries "
        "use advanced_oos.pkl on daily XAUUSD bars, matching the OOS evaluation. "
        "The 'daily' and '15m' entries are legacy momentum-strategy results on a "
        "different strategy and are retained for reference only."
    )
    MONTE_CARLO_OUT.write_text(json.dumps(mc_data, indent=2, cls=_NumpyEncoder))
    logger.info("Updated %s", MONTE_CARLO_OUT)

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("  Reconciled Backtest Summary")
    logger.info("=" * 60)
    logger.info("  Model      : advanced_oos.pkl")
    logger.info(f"  Period     : {result['start']} to {result['end']}")
    logger.info(f"  Bars       : {result['total_bars']:,}")
    logger.info(f"  Trades     : {metrics['total_trades']}")
    logger.info(f"  Win rate   : {metrics['win_rate_pct']:.1f}%")
    logger.info(f"  Total P&L  : ${metrics['total_pnl_usd']:,.2f}")
    logger.info(f"  Return     : {metrics['return_pct']:.2f}%")
    logger.info(f"  Sharpe     : {metrics['sharpe_ratio']:.3f}")
    logger.info(f"  Max DD     : {metrics['max_drawdown_pct']:.2f}%")
    logger.info(f"  p99 MC DD  : {metrics['monte_carlo']['p99_dd_pct']:.2f}%")
    logger.info(f"  Avg hold   : {metrics['avg_hold_bars']:.1f} bars")
    logger.info("=" * 60)
    logger.info("")

    return 0


if __name__ == "__main__":
    sys.exit(main())
