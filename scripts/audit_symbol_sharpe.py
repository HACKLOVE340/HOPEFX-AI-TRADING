#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/audit_symbol_sharpe.py
================================
Audit implausible Sharpe ratios for EUR/USD and GBP/USD backtest results
using PSI (Population Stability Index) and KS (Kolmogorov-Smirnov) tests.

Background
----------
The multi-symbol backtest reports Sharpe ratios of 12.48 (EUR/USD) and
16.36 (GBP/USD).  These are implausible for a real trading strategy and
likely indicate one or more of:

  - Look-ahead bias (future data leaking into features)
  - Overfitting to a narrow in-sample window
  - Signal distribution that does not match XAUUSD (the model's training symbol)
  - Survivorship bias in the backtest data

This script:
  1. Loads backtest signal distributions for each symbol from the evaluation
     CSVs in ml/evaluation/ (or generates synthetic distributions if not found)
  2. Runs PSI and KS tests comparing each symbol's signal distribution to
     the XAUUSD reference distribution
  3. Checks for look-ahead bias indicators (autocorrelation, return predictability)
  4. Computes a realistic Sharpe upper bound given the signal count and horizon
  5. Writes a JSON audit report to reports/output/sharpe_audit_<date>.json
  6. Prints a human-readable summary

Usage
-----
    python scripts/audit_symbol_sharpe.py
    python scripts/audit_symbol_sharpe.py --symbols EURUSD GBPUSD XAUUSD
    python scripts/audit_symbol_sharpe.py --csv-dir ml/evaluation --output reports/output
    python scripts/audit_symbol_sharpe.py --strict   # exit 1 if any symbol fails
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("audit_symbol_sharpe")

# ── Constants ─────────────────────────────────────────────────────────────────

# PSI thresholds (industry standard)
PSI_STABLE = 0.10  # < 0.10 → stable
PSI_MONITOR = 0.25  # 0.10–0.25 → monitor
# > 0.25 → major shift / likely artefact

# KS p-value threshold
KS_P_THRESHOLD = 0.05  # p < 0.05 → distributions differ significantly

# Sharpe upper bound: for N independent trades with win-rate w and R:R r,
# the theoretical maximum annualised Sharpe is bounded by:
#   Sharpe_max ≈ sqrt(N_annual) * (2w - 1) / sqrt(4 * w * (1-w))
# Anything above 5.0 for a daily strategy with < 500 trades/year is suspicious.
SHARPE_PLAUSIBILITY_THRESHOLD = 5.0

# Symbols to audit
DEFAULT_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD"]

# Known implausible Sharpe values from the multi-symbol backtest
KNOWN_IMPLAUSIBLE: dict[str, float] = {
    "EURUSD": 12.48,
    "GBPUSD": 16.36,
}


# ── PSI calculation ───────────────────────────────────────────────────────────


def compute_psi(
    reference: np.ndarray,
    comparison: np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Compute Population Stability Index between two distributions.

    PSI = sum((actual% - expected%) * ln(actual% / expected%))

    Returns PSI value. Higher = more drift.
    """
    # Use reference distribution to define bin edges
    min_val = min(reference.min(), comparison.min())
    max_val = max(reference.max(), comparison.max())
    bins = np.linspace(min_val, max_val, n_bins + 1)

    ref_counts, _ = np.histogram(reference, bins=bins)
    cmp_counts, _ = np.histogram(comparison, bins=bins)

    # Avoid division by zero — replace zeros with small epsilon
    eps = 1e-6
    ref_pct = (ref_counts + eps) / (len(reference) + eps * n_bins)
    cmp_pct = (cmp_counts + eps) / (len(comparison) + eps * n_bins)

    psi = float(np.sum((cmp_pct - ref_pct) * np.log(cmp_pct / ref_pct)))
    return round(psi, 6)


# ── KS test ───────────────────────────────────────────────────────────────────


def compute_ks(
    reference: np.ndarray,
    comparison: np.ndarray,
) -> tuple[float, float]:
    """
    Two-sample KS test.

    Returns (statistic, p_value).
    p < 0.05 → distributions differ significantly.
    """
    try:
        from scipy import stats as _stats

        result = _stats.ks_2samp(reference, comparison)
        return round(float(result.statistic), 6), round(float(result.pvalue), 6)
    except ImportError:
        # Manual KS statistic without scipy
        ref_sorted = np.sort(reference)
        cmp_sorted = np.sort(comparison)
        combined = np.sort(np.concatenate([ref_sorted, cmp_sorted]))
        cdf_ref = np.searchsorted(ref_sorted, combined, side="right") / len(ref_sorted)
        cdf_cmp = np.searchsorted(cmp_sorted, combined, side="right") / len(cmp_sorted)
        ks_stat = float(np.max(np.abs(cdf_ref - cdf_cmp)))
        # Approximate p-value (Kolmogorov distribution)
        n = len(reference) * len(comparison) / (len(reference) + len(comparison))
        z = ks_stat * math.sqrt(n)
        p_val = 2 * math.exp(-2 * z * z) if z > 0 else 1.0
        return round(ks_stat, 6), round(p_val, 6)


# ── Look-ahead bias detection ─────────────────────────────────────────────────


def detect_lookahead_bias(returns: np.ndarray) -> dict[str, object]:
    """
    Heuristic look-ahead bias indicators.

    Checks:
    1. Autocorrelation at lag 1 — genuine strategies have low autocorrelation
       in returns. Very high positive autocorrelation (> 0.5) suggests
       smoothing or look-ahead.
    2. Return predictability — if the sign of return[t] perfectly predicts
       return[t+1], that is a look-ahead signal.
    3. Sharpe stability — compute rolling 30-trade Sharpe. If it never drops
       below 2.0, the strategy may be overfitted or look-ahead contaminated.
    """
    results: dict[str, object] = {}

    if len(returns) < 10:
        results["insufficient_data"] = True
        return results

    # 1. Lag-1 autocorrelation
    if len(returns) > 2:
        autocorr = float(np.corrcoef(returns[:-1], returns[1:])[0, 1])
        results["autocorr_lag1"] = round(autocorr, 4)
        results["autocorr_suspicious"] = abs(autocorr) > 0.5
    else:
        results["autocorr_lag1"] = None
        results["autocorr_suspicious"] = False

    # 2. Sign predictability (fraction of times sign(r[t]) == sign(r[t+1]))
    if len(returns) > 2:
        signs = np.sign(returns)
        sign_match = float(np.mean(signs[:-1] == signs[1:]))
        results["sign_predictability"] = round(sign_match, 4)
        # > 0.75 is suspicious (random walk → ~0.5)
        results["sign_pred_suspicious"] = sign_match > 0.75
    else:
        results["sign_predictability"] = None
        results["sign_pred_suspicious"] = False

    # 3. Rolling Sharpe stability (window = min(30, len/3))
    window = max(5, min(30, len(returns) // 3))
    rolling_sharpes = []
    for i in range(window, len(returns)):
        chunk = returns[i - window : i]
        mu = float(np.mean(chunk))
        sigma = float(np.std(chunk, ddof=1))
        if sigma > 1e-10:
            rolling_sharpes.append(mu / sigma * math.sqrt(252))

    if rolling_sharpes:
        min_rolling = float(np.min(rolling_sharpes))
        results["rolling_sharpe_min"] = round(min_rolling, 3)
        results["rolling_sharpe_never_negative"] = min_rolling > 0
        results["rolling_sharpe_always_high"] = min_rolling > 2.0
    else:
        results["rolling_sharpe_min"] = None
        results["rolling_sharpe_never_negative"] = False
        results["rolling_sharpe_always_high"] = False

    return results


# ── Sharpe plausibility bound ─────────────────────────────────────────────────


def sharpe_upper_bound(
    n_trades: int,
    win_rate: float,
    trades_per_year: int = 250,
) -> float:
    """
    Theoretical maximum annualised Sharpe for a binary win/loss strategy.

    Formula: Sharpe_max = sqrt(N_annual) * (2w - 1) / sqrt(4 * w * (1-w))
    where N_annual = trades_per_year.

    This is the Sharpe of a strategy that wins exactly w% of the time with
    equal win/loss sizes — the best possible outcome with no edge beyond w.
    """
    if win_rate <= 0 or win_rate >= 1 or n_trades < 1:
        return float("inf")
    edge = 2 * win_rate - 1
    variance_term = math.sqrt(4 * win_rate * (1 - win_rate))
    if variance_term < 1e-10:
        return float("inf")
    return round(math.sqrt(trades_per_year) * edge / variance_term, 3)


# ── Data loading ──────────────────────────────────────────────────────────────


def _load_predictions_csv(csv_dir: Path, symbol: str) -> np.ndarray | None:
    """
    Load prediction probabilities from ml/evaluation/ CSVs.

    Looks for the most recent *_predictions_*.csv that contains a
    'y_prob' or 'probability' column.  Returns array of probabilities or None.
    """
    candidates = sorted(csv_dir.glob("*_predictions_*.csv"), reverse=True)
    for csv_path in candidates:
        try:
            import csv as _csv

            with Path(csv_path).open(newline="", encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                rows = list(reader)
            if not rows:
                continue
            # Find probability column
            prob_col = None
            for col in ("y_prob", "probability", "prob", "confidence", "score"):
                if col in rows[0]:
                    prob_col = col
                    break
            if prob_col is None:
                continue
            probs = np.array([float(r[prob_col]) for r in rows if r.get(prob_col)])
            if len(probs) > 0:
                logger.info("Loaded %d predictions from %s", len(probs), csv_path.name)
                return probs
        except Exception as exc:
            logger.debug("Could not load %s: %s", csv_path, exc)
    return None


def _implied_win_rate_from_sharpe(symbol: str) -> float | None:
    """
    Back-calculate the win-rate implied by a known implausible Sharpe ratio.

    Used only for logging/reporting — not for generating synthetic data.
    Returns None when the symbol has no known implausible Sharpe.
    """
    if symbol not in KNOWN_IMPLAUSIBLE:
        return None
    target_sharpe = KNOWN_IMPLAUSIBLE[symbol]
    ratio = target_sharpe / math.sqrt(250)
    x = ratio / math.sqrt(1 + ratio**2)
    win_rate = (x + 1) / 2
    return min(0.99, max(0.51, win_rate))


# ── Per-symbol audit ──────────────────────────────────────────────────────────


def audit_symbol(
    symbol: str,
    reference_dist: np.ndarray,
    comparison_dist: np.ndarray,
    known_sharpe: float | None = None,
    n_trades: int = 250,
    win_rate: float = 0.66,
) -> dict[str, object]:
    """
    Run full audit for one symbol against the reference distribution.

    Returns a dict with all test results and a verdict.
    """
    result: dict[str, object] = {
        "symbol": symbol,
        "n_reference": len(reference_dist),
        "n_comparison": len(comparison_dist),
        "known_sharpe": known_sharpe,
        "audited_at": datetime.now(UTC).isoformat(),
    }

    # PSI
    psi = compute_psi(reference_dist, comparison_dist)
    result["psi"] = psi
    if psi < PSI_STABLE:
        result["psi_verdict"] = "STABLE"
    elif psi < PSI_MONITOR:
        result["psi_verdict"] = "MONITOR"
    else:
        result["psi_verdict"] = "MAJOR_SHIFT"

    # KS test
    ks_stat, ks_p = compute_ks(reference_dist, comparison_dist)
    result["ks_statistic"] = ks_stat
    result["ks_p_value"] = ks_p
    result["ks_verdict"] = "DIFFERENT" if ks_p < KS_P_THRESHOLD else "SAME_DIST"

    # Distribution stats
    result["ref_mean"] = round(float(np.mean(reference_dist)), 4)
    result["ref_std"] = round(float(np.std(reference_dist)), 4)
    result["cmp_mean"] = round(float(np.mean(comparison_dist)), 4)
    result["cmp_std"] = round(float(np.std(comparison_dist)), 4)
    result["mean_drift_sigma"] = round(abs(result["cmp_mean"] - result["ref_mean"]) / max(result["ref_std"], 1e-10), 3)

    # Look-ahead bias detection (on comparison returns)
    # Convert probabilities to signed returns: r = sign(p - 0.5) * 2 * |p - 0.5|
    # No noise added — the signal is in the probabilities themselves.
    signed_returns = (2 * (comparison_dist > 0.5).astype(float) - 1) * (comparison_dist - 0.5) * 2
    result["lookahead_checks"] = detect_lookahead_bias(signed_returns)

    # Sharpe plausibility
    sharpe_bound = sharpe_upper_bound(n_trades, win_rate)
    result["sharpe_upper_bound"] = sharpe_bound
    result["sharpe_plausible"] = known_sharpe is None or known_sharpe <= SHARPE_PLAUSIBILITY_THRESHOLD
    result["sharpe_exceeds_bound"] = known_sharpe is not None and known_sharpe > sharpe_bound

    # Overall verdict
    flags = []
    if result["psi_verdict"] == "MAJOR_SHIFT":
        flags.append("PSI_MAJOR_SHIFT")
    if result["ks_verdict"] == "DIFFERENT":
        flags.append("KS_DISTRIBUTION_MISMATCH")
    if result["mean_drift_sigma"] > 2.0:
        flags.append("MEAN_DRIFT_2SIGMA")
    if not result["sharpe_plausible"]:
        flags.append("SHARPE_IMPLAUSIBLE")
    if result["sharpe_exceeds_bound"]:
        flags.append("SHARPE_EXCEEDS_THEORETICAL_BOUND")
    la = result["lookahead_checks"]
    if isinstance(la, dict):
        if la.get("autocorr_suspicious"):
            flags.append("HIGH_AUTOCORRELATION")
        if la.get("sign_pred_suspicious"):
            flags.append("HIGH_SIGN_PREDICTABILITY")
        if la.get("rolling_sharpe_always_high"):
            flags.append("ROLLING_SHARPE_NEVER_DROPS")

    result["flags"] = flags
    result["passed"] = len(flags) == 0
    result["verdict"] = "PASS" if result["passed"] else f"FAIL ({', '.join(flags)})"

    return result


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit EUR/USD and GBP/USD backtest Sharpe ratios using PSI and KS tests"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help="Symbols to audit (default: EURUSD GBPUSD XAUUSD)",
    )
    parser.add_argument(
        "--csv-dir",
        default="ml/evaluation",
        help="Directory containing *_predictions_*.csv files",
    )
    parser.add_argument(
        "--output",
        default="reports/output",
        help="Directory to write audit report JSON",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any symbol fails the audit",
    )
    parser.add_argument(
        "--n-trades",
        type=int,
        default=250,
        help="Assumed trades per year for Sharpe bound calculation",
    )
    parser.add_argument(
        "--win-rate",
        type=float,
        default=0.66,
        help="Assumed win-rate for Sharpe bound calculation",
    )
    args = parser.parse_args(argv)

    csv_dir = Path(args.csv_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("HopeFX Symbol Sharpe Audit")
    logger.info("Symbols: %s", args.symbols)
    logger.info("=" * 60)

    # Load XAUUSD reference distribution — required; no synthetic fallback
    xauusd_dist = _load_predictions_csv(csv_dir, "XAUUSD")
    if xauusd_dist is None:
        logger.error(
            "No XAUUSD predictions CSV found in %s. "
            "Run the ML pipeline to generate ml/evaluation/XAUUSD_predictions.csv "
            "before running this audit.",
            csv_dir,
        )
        sys.exit(1)

    audit_results = []
    any_failed = False

    for symbol in args.symbols:
        logger.info("\n── Auditing %s ──", symbol)

        # Load comparison distribution — skip symbol if CSV not found
        cmp_dist = _load_predictions_csv(csv_dir, symbol)
        if cmp_dist is None:
            implied_wr = _implied_win_rate_from_sharpe(symbol)
            wr_note = f" (implied win-rate from known Sharpe: {implied_wr:.1%})" if implied_wr is not None else ""
            logger.warning(
                "%s: no predictions CSV found in %s%s — skipping. Run the ML pipeline to generate evaluation CSVs.",
                symbol,
                csv_dir,
                wr_note,
            )
            continue

        known_sharpe = KNOWN_IMPLAUSIBLE.get(symbol)

        result = audit_symbol(
            symbol=symbol,
            reference_dist=xauusd_dist,
            comparison_dist=cmp_dist,
            known_sharpe=known_sharpe,
            n_trades=args.n_trades,
            win_rate=args.win_rate,
        )
        audit_results.append(result)

        # Print summary
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"\n{status}  {symbol}")
        if known_sharpe:
            print(f"  Known Sharpe:          {known_sharpe}")
        print(f"  Sharpe upper bound:    {result['sharpe_upper_bound']}")
        print(f"  PSI:                   {result['psi']} ({result['psi_verdict']})")
        print(f"  KS p-value:            {result['ks_p_value']} ({result['ks_verdict']})")
        print(f"  Mean drift (sigma):    {result['mean_drift_sigma']}")
        la = result.get("lookahead_checks", {})
        if isinstance(la, dict):
            print(f"  Autocorr lag-1:        {la.get('autocorr_lag1', 'N/A')}")
            print(f"  Sign predictability:   {la.get('sign_predictability', 'N/A')}")
            print(f"  Rolling Sharpe min:    {la.get('rolling_sharpe_min', 'N/A')}")
        if result["flags"]:
            print(f"  Flags:                 {', '.join(result['flags'])}")

        if not result["passed"]:
            any_failed = True

    # Write JSON report
    report = {
        "audit_type": "symbol_sharpe_audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "reference_symbol": "XAUUSD",
        "n_reference": len(xauusd_dist),
        "psi_thresholds": {"stable": PSI_STABLE, "monitor": PSI_MONITOR},
        "ks_p_threshold": KS_P_THRESHOLD,
        "sharpe_plausibility_threshold": SHARPE_PLAUSIBILITY_THRESHOLD,
        "results": audit_results,
        "summary": {
            "total": len(audit_results),
            "passed": sum(1 for r in audit_results if r["passed"]),
            "failed": sum(1 for r in audit_results if not r["passed"]),
            "overall": "PASS" if not any_failed else "FAIL",
        },
    }

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    report_path = output_dir / f"sharpe_audit_{date_str}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"\n{'=' * 60}")
    print(f"Audit complete: {report['summary']['passed']}/{report['summary']['total']} passed")
    print(f"Report saved:   {report_path}")

    if any_failed:
        print("\nRECOMMENDATION: Symbols that failed the audit should be:")
        print("  1. Re-examined for look-ahead bias in feature construction")
        print("  2. Re-backtested with walk-forward validation")
        print("  3. Excluded from live trading until Sharpe is confirmed OOS")
        print("\nRun signal_validator.py against live fills to confirm distribution match.")

    return 1 if (args.strict and any_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
