# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtest/reconciled_backtest_investigation.py
=============================================
Root cause investigation for the -4.18 Sharpe reconciled backtest.

The OOS evaluation reports 66.3% directional accuracy but the reconciled
backtest on the same model shows 11.6% win rate and -10.6% return.

This module runs four targeted investigations:

1. Confidence threshold sweep (0.55 → 0.60 → 0.65 → 0.70 → 0.75)
   Tests whether higher-confidence signals have better win rates.

2. Hold period sweep (1-bar, 2-bar, 3-bar, 5-bar, 10-bar)
   Tests whether the 5-bar hold accumulates mean-reversion noise.

3. Accuracy vs P&L correlation
   For each trade: compare model's predicted direction to actual P&L sign.
   If they're uncorrelated despite 66% accuracy, the accuracy metric and
   trade entry/exit logic are measuring different things.

4. Cost sensitivity
   Run at $0, $35, $70, $105 round-trip cost to isolate the cost drag.

Results are written to:
  data/backtest_investigation.json   — full sweep results
  data/backtest_investigation_summary.txt — human-readable summary

Usage
-----
    python backtest/reconciled_backtest_investigation.py
    python backtest/reconciled_backtest_investigation.py --smoke  # fast CI run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Load existing reconciled backtest trades
# ─────────────────────────────────────────────────────────────────────────────


def load_reconciled_trades() -> list[dict[str, Any]]:
    """Load the trade list from data/reconciled_backtest.json."""
    path = DATA_DIR / "reconciled_backtest.json"
    if not path.exists():
        raise FileNotFoundError(f"reconciled_backtest.json not found at {path}")
    data = json.loads(path.read_text())
    trades = data.get("trades", [])
    if not trades:
        raise ValueError("No trades found in reconciled_backtest.json")
    logger.info("Loaded %d trades from reconciled_backtest.json", len(trades))
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# Metrics helpers
# ─────────────────────────────────────────────────────────────────────────────


def _sharpe(pnls: list[float], cost: float = 0.0) -> float:
    """Annualised Sharpe ratio from a list of per-trade P&Ls (daily bars)."""
    if len(pnls) < 2:  # noqa: PLR2004
        return 0.0
    net = [p - cost for p in pnls]
    arr = np.array(net, dtype=float)
    std = arr.std()
    if std == 0:
        return 0.0
    # Annualise: daily bars, ~252 trading days
    return float((arr.mean() / std) * np.sqrt(252))


def _win_rate(pnls: list[float], cost: float = 0.0) -> float:
    net = [p - cost for p in pnls]
    if not net:
        return 0.0
    return sum(1 for p in net if p > 0) / len(net)


def _total_return(pnls: list[float], cost: float = 0.0, initial: float = 100_000.0) -> float:
    net = sum(p - cost for p in pnls)
    return net / initial * 100.0


def _accuracy_pnl_correlation(trades: list[dict]) -> dict[str, Any]:
    """
    Measure correlation between model's predicted direction and actual P&L sign.

    direction=1 means model predicted UP (long), direction=-1 means DOWN (short).
    pnl_sign=1 means trade was profitable, -1 means loss.

    If accuracy and P&L are measuring the same thing, correlation should be ~0.66.
    If they're uncorrelated, the accuracy metric is not measuring tradeable edge.
    """
    directions = []
    pnl_signs = []
    for t in trades:
        d = t.get("direction", 0)
        p = t.get("pnl_usd", 0.0)
        if d != 0 and p != 0:
            directions.append(int(d))
            pnl_signs.append(1 if p > 0 else -1)

    if len(directions) < 10:  # noqa: PLR2004
        return {"correlation": None, "n": len(directions), "note": "Insufficient data"}

    corr = float(np.corrcoef(directions, pnl_signs)[0, 1])
    # Fraction where direction sign matches P&L sign
    matches = sum(1 for d, p in zip(directions, pnl_signs, strict=False) if d == p)
    match_rate = matches / len(directions)

    return {
        "correlation": round(corr, 4),
        "direction_pnl_match_rate": round(match_rate, 4),
        "n": len(directions),
        "note": (
            "direction_pnl_match_rate is the fraction of trades where the model's "
            "predicted direction matches the P&L sign. If this is ~0.50 despite "
            "66% OOS accuracy, the accuracy metric and trade P&L are measuring "
            "different things (e.g. accuracy measures 1-bar direction, P&L measures "
            "5-bar cumulative return)."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Investigation 1: Confidence threshold sweep
# ─────────────────────────────────────────────────────────────────────────────


def sweep_confidence_thresholds(
    trades: list[dict],
    thresholds: list[float],
    cost: float = 70.0,
) -> list[dict[str, Any]]:
    """
    Filter trades by signal_prob >= threshold and recompute metrics.

    Higher thresholds = fewer trades but potentially higher win rate.
    """
    results = []
    for thresh in thresholds:
        filtered = [t for t in trades if abs(t.get("signal_prob", 0.5) - 0.5) + 0.5 >= thresh]
        pnls = [t["pnl_usd"] for t in filtered]
        if not pnls:
            results.append(
                {
                    "threshold": thresh,
                    "n_trades": 0,
                    "win_rate": 0.0,
                    "sharpe": 0.0,
                    "total_return_pct": 0.0,
                    "avg_pnl": 0.0,
                }
            )
            continue
        results.append(
            {
                "threshold": thresh,
                "n_trades": len(pnls),
                "win_rate": round(_win_rate(pnls, cost), 4),
                "sharpe": round(_sharpe(pnls, cost), 4),
                "total_return_pct": round(_total_return(pnls, cost), 4),
                "avg_pnl": round(np.mean([p - cost for p in pnls]), 2),
            }
        )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Investigation 2: Hold period sweep (requires OHLCV data)
# ─────────────────────────────────────────────────────────────────────────────


def _load_xauusd_daily() -> pd.DataFrame | None:
    """Load XAUUSD daily OHLCV for hold-period re-simulation.

    Source priority
    ---------------
    1. CSV cache at data/XAUUSD_D1.csv (fastest, no network)
    2. yfinance GC=F (gold futures — highly correlated with XAU/USD spot,
       suitable for hold-period exit price lookup)

    Note: GC=F is gold futures, not XAU/USD spot.  The price difference is
    typically <0.5% and does not materially affect hold-period sweep results.
    For production-grade reconciliation, replace with OANDA v20 candles:
      GET /v3/instruments/XAU_USD/candles?granularity=D&count=2500
    and save to data/XAUUSD_D1.csv before running this script.
    """
    csv_path = DATA_DIR / "XAUUSD_D1.csv"
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            df = df.set_index("timestamp").sort_index()
            if len(df) > 100:  # noqa: PLR2004
                logger.info("Loaded %d daily bars from %s", len(df), csv_path)
                return df
        except Exception as exc:
            logger.debug("CSV load failed: %s", exc)

    # Try yfinance (GC=F — gold futures, highly correlated with XAU/USD spot)
    try:
        import yfinance as yf

        df = yf.download("GC=F", period="10y", interval="1d", progress=False, auto_adjust=True)
        if df is not None and len(df) > 100:  # noqa: PLR2004
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0].lower() for col in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]
            df.index.name = "timestamp"
            df.to_csv(csv_path)
            logger.info("Downloaded %d daily bars from yfinance (GC=F gold futures)", len(df))
            return df
    except Exception as exc:
        logger.debug("yfinance download failed: %s", exc)

    logger.warning(
        "_load_xauusd_daily: no OHLCV data available. "
        "Hold-period sweep will use approximate P&L scaling. "
        "For accurate results, save OANDA XAU_USD daily candles to %s",
        csv_path,
    )
    return None


def sweep_hold_periods(
    trades: list[dict],
    hold_periods: list[int],
    cost: float = 70.0,
    ohlcv: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """
    Re-simulate trades with different hold periods using actual OHLCV data.

    For each trade, re-exit at entry_bar + hold_bars instead of the original 5.
    Requires OHLCV data to look up exit prices.
    """
    if ohlcv is None:
        # Fall back to scaling existing P&Ls by hold ratio (approximate)
        results = []
        for hold in hold_periods:
            # Scale P&L by hold ratio relative to original 5-bar hold
            # This is approximate — real re-simulation needs OHLCV
            scale = hold / 5.0
            pnls = [t["pnl_usd"] * scale for t in trades]
            results.append(
                {
                    "hold_bars": hold,
                    "n_trades": len(pnls),
                    "win_rate": round(_win_rate(pnls, cost), 4),
                    "sharpe": round(_sharpe(pnls, cost), 4),
                    "total_return_pct": round(_total_return(pnls, cost), 4),
                    "avg_pnl": round(np.mean([p - cost for p in pnls]), 2),
                    "note": "Approximate — scaled from 5-bar P&L. Run with OHLCV for exact results.",
                }
            )
        return results

    # Full re-simulation with OHLCV
    closes = ohlcv["close"].values
    results = []
    for hold in hold_periods:
        pnls = []
        for t in trades:
            entry_bar = t.get("entry_bar", 0)
            direction = t.get("direction", 1)
            entry_price = t.get("entry_price", closes[entry_bar] if entry_bar < len(closes) else 0)
            exit_bar = min(entry_bar + hold, len(closes) - 1)
            if exit_bar >= len(closes) or entry_bar >= len(closes):
                continue
            exit_price = closes[exit_bar]
            # P&L in USD: 1 contract = 100 oz, price in USD/oz
            # Use same scaling as original backtest
            pnl = direction * (exit_price - entry_price) * 100.0
            pnls.append(pnl)

        if not pnls:
            continue
        results.append(
            {
                "hold_bars": hold,
                "n_trades": len(pnls),
                "win_rate": round(_win_rate(pnls, cost), 4),
                "sharpe": round(_sharpe(pnls, cost), 4),
                "total_return_pct": round(_total_return(pnls, cost), 4),
                "avg_pnl": round(np.mean([p - cost for p in pnls]), 2),
                "note": "Exact re-simulation from OHLCV data.",
            }
        )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Investigation 3: Cost sensitivity
# ─────────────────────────────────────────────────────────────────────────────


def sweep_costs(
    trades: list[dict],
    costs: list[float],
) -> list[dict[str, Any]]:
    """Show how different round-trip costs affect the strategy."""
    pnls_gross = [t["pnl_usd"] for t in trades]
    results = []
    for cost in costs:
        results.append(
            {
                "round_trip_cost_usd": cost,
                "n_trades": len(pnls_gross),
                "win_rate": round(_win_rate(pnls_gross, cost), 4),
                "sharpe": round(_sharpe(pnls_gross, cost), 4),
                "total_return_pct": round(_total_return(pnls_gross, cost), 4),
                "avg_pnl": round(np.mean([p - cost for p in pnls_gross]), 2),
                "total_cost_drag_usd": round(cost * len(pnls_gross), 2),
            }
        )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Summary report
# ─────────────────────────────────────────────────────────────────────────────


def _format_summary(results: dict[str, Any]) -> str:
    lines = [
        "=" * 72,
        "RECONCILED BACKTEST ROOT CAUSE INVESTIGATION",
        f"Generated: {results['generated_at']}",
        "=" * 72,
        "",
        "BASELINE (threshold=0.55, hold=5, cost=$70)",
        f"  Trades: {results['baseline']['n_trades']}",
        f"  Win rate: {results['baseline']['win_rate_pct']:.1f}%",
        f"  Sharpe: {results['baseline']['sharpe_ratio']:.4f}",
        f"  Return: {results['baseline']['return_pct']:.2f}%",
        "",
        "─" * 72,
        "INVESTIGATION 1: Confidence Threshold Sweep",
        "─" * 72,
        f"{'Threshold':>10} {'N Trades':>10} {'Win Rate':>10} {'Sharpe':>10} {'Return%':>10}",
    ]
    for r in results["confidence_sweep"]:
        lines.append(
            f"{r['threshold']:>10.2f} {r['n_trades']:>10} "
            f"{r['win_rate'] * 100:>9.1f}% {r['sharpe']:>10.4f} "
            f"{r['total_return_pct']:>9.2f}%"
        )

    lines += [
        "",
        "─" * 72,
        "INVESTIGATION 2: Hold Period Sweep (cost=$70)",
        "─" * 72,
        f"{'Hold Bars':>10} {'N Trades':>10} {'Win Rate':>10} {'Sharpe':>10} {'Return%':>10}",
    ]
    for r in results["hold_period_sweep"]:
        lines.append(
            f"{r['hold_bars']:>10} {r['n_trades']:>10} "
            f"{r['win_rate'] * 100:>9.1f}% {r['sharpe']:>10.4f} "
            f"{r['total_return_pct']:>9.2f}%"
        )

    lines += [
        "",
        "─" * 72,
        "INVESTIGATION 3: Accuracy vs P&L Correlation",
        "─" * 72,
    ]
    corr = results["accuracy_pnl_correlation"]
    lines += [
        f"  Direction-P&L correlation: {corr.get('correlation', 'N/A')}",
        f"  Direction-P&L match rate:  {corr.get('direction_pnl_match_rate', 'N/A')}",
        f"  N trades analysed:         {corr.get('n', 0)}",
        f"  Note: {corr.get('note', '')}",
    ]

    lines += [
        "",
        "─" * 72,
        "INVESTIGATION 4: Cost Sensitivity",
        "─" * 72,
        f"{'Cost $':>10} {'Win Rate':>10} {'Sharpe':>10} {'Return%':>10} {'Cost Drag':>12}",
    ]
    for r in results["cost_sweep"]:
        lines.append(
            f"{r['round_trip_cost_usd']:>10.0f} "
            f"{r['win_rate'] * 100:>9.1f}% {r['sharpe']:>10.4f} "
            f"{r['total_return_pct']:>9.2f}% "
            f"${r['total_cost_drag_usd']:>10,.0f}"
        )

    lines += [
        "",
        "─" * 72,
        "DIAGNOSIS",
        "─" * 72,
    ]
    lines += results.get("diagnosis", ["No diagnosis available."])
    lines.append("=" * 72)
    return "\n".join(lines)


def _diagnose(results: dict[str, Any]) -> list[str]:
    """Generate a plain-English diagnosis from the sweep results."""
    diag = []

    # Check if higher thresholds help
    conf_sweep = results["confidence_sweep"]
    best_conf = max(conf_sweep, key=lambda r: r["sharpe"]) if conf_sweep else None
    if best_conf and best_conf["threshold"] > 0.55 and best_conf["sharpe"] > 0:  # noqa: PLR2004
        diag.append(
            f"✅ THRESHOLD EDGE EXISTS: At threshold={best_conf['threshold']:.2f}, "
            f"Sharpe={best_conf['sharpe']:.4f} (positive). "
            f"The edge exists but is diluted by low-confidence signals at 0.55. "
            f"Recommendation: raise SIGNAL_THRESHOLD_LONG to {best_conf['threshold']:.2f}."
        )
    else:
        diag.append(
            "❌ THRESHOLD SWEEP: No confidence threshold produces a positive Sharpe. "
            "The model's directional accuracy does not translate to tradeable edge "
            "at any tested threshold with the current 5-bar hold strategy."
        )

    # Check if shorter holds help
    hold_sweep = results["hold_period_sweep"]
    best_hold = max(hold_sweep, key=lambda r: r["sharpe"]) if hold_sweep else None
    if best_hold and best_hold["hold_bars"] < 5 and best_hold["sharpe"] > 0:  # noqa: PLR2004
        diag.append(
            f"✅ HOLD PERIOD EDGE EXISTS: At hold={best_hold['hold_bars']} bars, "
            f"Sharpe={best_hold['sharpe']:.4f} (positive). "
            f"The 5-bar hold accumulates mean-reversion noise. "
            f"Recommendation: use {best_hold['hold_bars']}-bar exits."
        )
    elif best_hold and best_hold["sharpe"] > results["baseline"]["sharpe_ratio"]:
        diag.append(
            f"⚠️  HOLD PERIOD: {best_hold['hold_bars']}-bar hold improves Sharpe to "
            f"{best_hold['sharpe']:.4f} but remains negative. "
            "Hold period is a contributing factor but not the sole cause."
        )
    else:
        diag.append(
            "❌ HOLD PERIOD SWEEP: No hold period produces a positive Sharpe. The problem is not the hold period alone."
        )

    # Check accuracy vs P&L correlation
    corr = results["accuracy_pnl_correlation"]
    match_rate = corr.get("direction_pnl_match_rate", 0.5)
    if match_rate is not None and match_rate < 0.55:  # noqa: PLR2004
        diag.append(
            f"❌ ACCURACY/P&L DISCONNECT: Direction-P&L match rate = {match_rate:.1%}. "
            "The model's predicted direction and actual trade P&L are nearly uncorrelated. "
            "The 66% OOS accuracy measures 1-bar direction; the 5-bar hold P&L measures "
            "something different. These two metrics are not comparable."
        )
    elif match_rate is not None:
        diag.append(
            f"⚠️  ACCURACY/P&L: Direction-P&L match rate = {match_rate:.1%}. "
            "Some correlation exists but is weaker than the 66% OOS accuracy suggests."
        )

    # Check cost drag
    cost_sweep = results["cost_sweep"]
    zero_cost = next((r for r in cost_sweep if r["round_trip_cost_usd"] == 0), None)
    if zero_cost and zero_cost["sharpe"] > 0:
        diag.append(
            f"✅ COST IS THE BLOCKER: At $0 cost, Sharpe={zero_cost['sharpe']:.4f} (positive). "
            f"The gross edge exists but $70 round-trip cost destroys it. "
            f"Total cost drag: ${zero_cost['total_cost_drag_usd']:,.0f} on "
            f"{zero_cost['n_trades']} trades. "
            "Recommendation: reduce position frequency or negotiate lower spreads."
        )
    elif zero_cost:
        diag.append(
            f"❌ COST IS NOT THE SOLE BLOCKER: Even at $0 cost, "
            f"Sharpe={zero_cost['sharpe']:.4f}. "
            "The strategy has no gross edge — cost reduction alone will not fix it."
        )

    if not diag:
        diag.append("Insufficient data for diagnosis.")

    return diag


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def run_investigation(smoke: bool = False) -> dict[str, Any]:
    """Run all four investigations and return the combined results dict."""
    trades = load_reconciled_trades()

    # Baseline metrics
    pnls = [t["pnl_usd"] for t in trades]
    baseline = {
        "n_trades": len(trades),
        "win_rate_pct": round(_win_rate(pnls, 70.0) * 100, 2),
        "sharpe_ratio": round(_sharpe(pnls, 70.0), 4),
        "return_pct": round(_total_return(pnls, 70.0), 4),
        "avg_pnl_net": round(np.mean([p - 70.0 for p in pnls]), 2),
    }
    logger.info("Baseline: %s", baseline)

    # Threshold sweep
    thresholds = [0.55, 0.58, 0.60, 0.65, 0.70, 0.75] if not smoke else [0.55, 0.65]
    conf_sweep = sweep_confidence_thresholds(trades, thresholds, cost=70.0)
    logger.info("Confidence sweep done (%d thresholds)", len(conf_sweep))

    # Hold period sweep
    hold_periods = [1, 2, 3, 5, 10] if not smoke else [1, 5]
    ohlcv = _load_xauusd_daily()
    hold_sweep = sweep_hold_periods(trades, hold_periods, cost=70.0, ohlcv=ohlcv)
    logger.info("Hold period sweep done (%d periods)", len(hold_sweep))

    # Accuracy vs P&L correlation
    corr = _accuracy_pnl_correlation(trades)
    logger.info("Accuracy/P&L correlation: %s", corr)

    # Cost sweep
    costs = [0.0, 35.0, 70.0, 105.0, 140.0] if not smoke else [0.0, 70.0]
    cost_sweep = sweep_costs(trades, costs)
    logger.info("Cost sweep done (%d cost levels)", len(cost_sweep))

    results: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_file": "data/reconciled_backtest.json",
        "baseline": baseline,
        "confidence_sweep": conf_sweep,
        "hold_period_sweep": hold_sweep,
        "accuracy_pnl_correlation": corr,
        "cost_sweep": cost_sweep,
        "diagnosis": [],  # filled below
    }
    results["diagnosis"] = _diagnose(results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconciled backtest root cause investigation")
    parser.add_argument("--smoke", action="store_true", help="Fast CI run (fewer sweep points)")
    args = parser.parse_args()

    results = run_investigation(smoke=args.smoke)

    # Write JSON
    out_json = DATA_DIR / "backtest_investigation.json"
    out_json.write_text(json.dumps(results, indent=2))
    logger.info("Results written to %s", out_json)

    # Write human-readable summary
    summary = _format_summary(results)
    out_txt = DATA_DIR / "backtest_investigation_summary.txt"
    out_txt.write_text(summary)
    logger.info("Summary written to %s", out_txt)

    print("\n" + summary)


if __name__ == "__main__":
    main()
