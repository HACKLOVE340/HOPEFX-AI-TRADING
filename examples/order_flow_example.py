# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Order Flow Example

Demonstrates how to use the streaming, time-and-sales, and advanced order
flow analysis modules together to monitor live market activity.

Data source: real XAUUSD ticks from the MarketDataOrchestrator (data layer).
No mock data, no synthetic feeds.

Usage
-----
    python examples/order_flow_example.py
    python examples/order_flow_example.py --ticks 200
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

UTC = timezone.utc

logger = logging.getLogger(__name__)

SYMBOL = "XAU_USD"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )


def print_metrics(analyzer, symbol: str) -> None:
    """Print a snapshot of current order-flow metrics to stdout."""
    aggression = analyzer.get_aggression_metrics(symbol)
    oscillator = analyzer.get_order_flow_oscillator(symbol)
    pressure = analyzer.get_pressure_gauges(symbol)

    logger.info("\n%s", '=' * 55)
    logger.info("  Order Flow Snapshot — %s  %s", symbol, datetime.now(UTC).strftime('%H:%M:%S UTC'))
    logger.info("%s", '=' * 55)

    if aggression:
        logger.info("  Buy aggression  : %6.1f%%", aggression.buy_aggression)
        logger.info("  Sell aggression : %6.1f%%", aggression.sell_aggression)
        logger.info("  Score           : %+.1f  (%s)", aggression.aggression_score, aggression.dominant_side)

    if oscillator:
        logger.info("  OFO value       : %+.1f  → %s", oscillator.value, oscillator.signal)

    if pressure:
        logger.info("  Buy pressure    : %6.1f%%", pressure.get('buy_pressure', 0.0))
        logger.info("  Sell pressure   : %6.1f%%", pressure.get('sell_pressure', 0.0))

    clusters = analyzer.get_volume_clusters(symbol, top_n=3)
    if clusters:
        logger.info("  Volume clusters :")
        for cluster in clusters:
            logger.info("    %10.4f  %s  strength=%.2f", cluster.price_level, f"{cluster.cluster_type:<12}", cluster.strength)


async def run_example(max_ticks: int = 100) -> None:
    """
    Feed real XAUUSD ticks from the orchestrator into the order flow analyzer.

    If the orchestrator has no live feed configured (no API keys), falls back
    to the most recent Dukascopy replay data for the last 24 hours.
    """
    from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer
    from data_layer.orchestrator import orchestrator

    analyzer = AdvancedOrderFlowAnalyzer()

    # ── Try live ticks first ──────────────────────────────────────────────────
    tick = orchestrator.get_latest_tick(SYMBOL)
    if tick is not None:
        logger.info("Live tick available — feeding real ticks into analyzer")
        count = 0

        def _on_tick(t) -> None:
            nonlocal count
            if count >= max_ticks:
                return
            side = "buy" if t.mid >= (t.bid + t.ask) / 2 else "sell"
            analyzer.add_trade(
                symbol=SYMBOL,
                price=t.mid,
                size=max(t.spread * 1000.0, 1.0),
                side=side,
                timestamp=t.timestamp,
            )
            count += 1
            if count % 20 == 0:
                logger.info("Processed %d live ticks …", count)

        orchestrator.subscribe_ticks("order_flow_example", _on_tick)
        # Wait for ticks to accumulate
        waited = 0
        while count < min(max_ticks, 50) and waited < 30:  # noqa: PLR2004
            await asyncio.sleep(1.0)
            waited += 1
        orchestrator.unsubscribe_ticks("order_flow_example")

    else:
        # ── Fallback: Dukascopy replay for last 24 hours ──────────────────────
        logger.info("No live tick — loading last 24h of Dukascopy M1 data for order flow")
        from datetime import timedelta

        # Access replay engine via orchestrator — single entry point rule
        end = datetime.now(UTC)
        start = end - timedelta(hours=24)
        engine = orchestrator._replay

        tick_count = 0
        async for replay_tick in engine.replay_ticks(start=start, end=end, symbol="XAUUSD"):
            if tick_count >= max_ticks:
                break
            side = "buy" if replay_tick.mid >= (replay_tick.bid + replay_tick.ask) / 2 else "sell"
            analyzer.add_trade(
                symbol=SYMBOL,
                price=replay_tick.mid,
                size=max(replay_tick.spread * 1000.0, 1.0),
                side=side,
                timestamp=replay_tick.timestamp,
            )
            tick_count += 1

        logger.info("Loaded %d replay ticks from Dukascopy", tick_count)

    # ── Print metrics ─────────────────────────────────────────────────────────
    print_metrics(analyzer, SYMBOL)

    # Detect delta divergence
    divergence = analyzer.detect_delta_divergence(SYMBOL)
    if divergence:
        logger.info("\n  Delta divergence: %s (confidence=%.2f)", divergence.divergence_type, divergence.confidence)
    else:
        logger.info("\n  No delta divergence detected.")

    # Stacked imbalances
    stacked = analyzer.get_stacked_imbalances(SYMBOL)
    if stacked:
        logger.info("\n  Stacked imbalances: %s found", len(stacked))
        for si in stacked[:3]:
            logger.info("    direction=%s  levels=%s  strength=%s", si.direction, len(si.levels), si.strength)
    else:
        logger.info("\n  No stacked imbalances found.")

    logger.info("Order flow example complete.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HOPEFX Order Flow Example — Real Data")
    parser.add_argument(
        "--ticks",
        type=int,
        default=100,
        help="Number of ticks to process (default: 100)",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = _parse_args()
    asyncio.run(run_example(max_ticks=args.ticks))


if __name__ == "__main__":
    main()
