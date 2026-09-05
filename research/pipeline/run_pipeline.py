# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/run_pipeline.py
====================================
CLI entry point for the deep prediction pipeline.

Usage examples
--------------
# Daily AAPL since 2000, LSTM, 1-bar-ahead prediction
python -m research.pipeline.run_pipeline --ticker AAPL --interval 1d --start 2000-01-01

# 5-minute XAUUSD (gold futures), Transformer, 3-bar-ahead
python -m research.pipeline.run_pipeline --ticker GC=F --interval 5m --arch transformer --horizon 3

# Multi-asset batch run
python -m research.pipeline.run_pipeline --batch --interval 1d --start 1990-01-01

# Inference on latest data (requires a prior run's artefact dir)
python -m research.pipeline.run_pipeline --ticker AAPL --interval 1d --infer --run-id 20240101_120000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from research.pipeline.orchestrator import PipelineConfig, PipelineOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline.cli")

# ── Multi-asset batch universe ────────────────────────────────────────────────
BATCH_UNIVERSE = [
    # Equities
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "JPM",
    # ETFs
    "SPY",
    "QQQ",
    "GLD",
    "TLT",
    # Crypto
    "BTC-USD",
    "ETH-USD",
    # FX
    "EURUSD=X",
    "GBPUSD=X",
    # Commodities
    "GC=F",
    "CL=F",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="HOPEFX Deep Prediction Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--ticker", default="GC=F", help="Yahoo Finance ticker (default: GC=F Gold futures)")
    p.add_argument("--interval", default="1d", help="Bar interval: 1d | 5m | 15m | 1h")
    p.add_argument("--start", default="2000-01-01", help="Start date (daily only)")
    p.add_argument("--lookback", type=int, default=730, help="Lookback days (intraday)")
    p.add_argument("--horizon", type=int, default=1, help="Bars ahead to predict")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.001,
        help="Min return for directional label",
    )
    p.add_argument("--seq-len", type=int, default=60, help="LSTM/Transformer sequence length")
    p.add_argument(
        "--arch",
        default="lstm",
        choices=["lstm", "transformer", "tcn"],
        help="Deep model architecture",
    )
    p.add_argument("--epochs", type=int, default=100, help="Max training epochs")
    p.add_argument("--patience", type=int, default=15, help="Early stopping patience")
    p.add_argument("--trials", type=int, default=30, help="Optuna hyperparameter trials")
    p.add_argument("--device", default="auto", help="'cuda' | 'cpu' | 'auto'")
    p.add_argument("--no-mtf", action="store_true", help="Disable multi-timeframe fusion")
    p.add_argument("--no-sentiment", action="store_true", help="Disable RSS sentiment")
    p.add_argument("--no-cache", action="store_true", help="Bypass Parquet cache")
    p.add_argument("--batch", action="store_true", help="Run on full BATCH_UNIVERSE")
    p.add_argument("--infer", action="store_true", help="Inference mode (requires --run-id)")
    p.add_argument("--run-id", default=None, help="Artefact run ID for inference")
    p.add_argument("--output", default=None, help="Path to write JSON report")
    return p.parse_args()


def _run_single(args: argparse.Namespace, ticker: str) -> dict:
    cfg = PipelineConfig(
        ticker=ticker,
        interval=args.interval,
        start_date=args.start,
        lookback_days=args.lookback,
        horizon=args.horizon,
        threshold=args.threshold,
        seq_len=args.seq_len,
        deep_arch=args.arch,
        deep_epochs=args.epochs,
        deep_patience=args.patience,
        ensemble_tune_trials=args.trials,
        use_mtf=not args.no_mtf,
        use_sentiment=not args.no_sentiment,
        use_cache=not args.no_cache,
        device=args.device,
    )
    orch = PipelineOrchestrator(cfg)
    return orch.run()


def _print_report(report: dict, ticker: str) -> None:
    test = report.get("test", {})
    logger.info("\n%s", "─" * 60)
    logger.info("  %s  |  run_id=%s", ticker, report["run_id"])
    logger.info("%s", "─" * 60)
    logger.info("  AUC          : %.4f", test.get("auc", 0))
    logger.info("  Accuracy     : %.4f", test.get("accuracy", 0))
    logger.info("  F1           : %.4f", test.get("f1", 0))
    logger.info("  Precision    : %.4f", test.get("precision", 0))
    logger.info("  Recall       : %.4f", test.get("recall", 0))
    logger.info("  Sharpe       : %.2f", test.get("strategy_sharpe", 0))
    logger.info("  Max Drawdown : %.1f%%", test.get("strategy_max_drawdown", 0) * 100)
    logger.info("  Total Return : %.1f%%", test.get("strategy_total_return", 0) * 100)
    logger.info("  Hit Rate     : %.4f", test.get("hit_rate", 0))
    logger.info("  Meta-weight  : deep=%.2f  ens=%.2f", report["meta_weight"], 1 - report["meta_weight"])
    logger.info("  Artefacts    : %s", report["artefact_dir"])
    logger.info("%s\n", "─" * 60)


def main() -> None:
    args = _parse_args()

    if args.batch:
        all_reports = {}
        for ticker in BATCH_UNIVERSE:
            logger.info("=== Batch: %s ===", ticker)
            try:
                report = _run_single(args, ticker)
                all_reports[ticker] = report
                _print_report(report, ticker)
            except Exception:
                logger.exception("Failed %s", ticker)
                all_reports[ticker] = {"error": "Pipeline failed — check server logs"}

        if args.output:
            with Path(args.output).open("w", encoding="utf-8") as f:
                json.dump(all_reports, f, indent=2, default=str)
            logger.info("Batch report → %s", args.output)

    else:
        report = _run_single(args, args.ticker)
        _print_report(report, args.ticker)

        if args.output:
            with Path(args.output).open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
            logger.info("Report → %s", args.output)


if __name__ == "__main__":
    main()
