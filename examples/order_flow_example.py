"""
Order Flow Example

Demonstrates how to use the streaming, time-and-sales, and advanced order
flow analysis modules together to monitor live market activity.
"""

import logging
import secrets
from datetime import datetime, timezone

from data.streaming import StreamingService, StreamConfig, MockDataSource
from data.time_and_sales import TimeAndSalesService
from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

logger = logging.getLogger(__name__)

SYMBOL = "XAUUSD"


def setup_logging() -> None:
    """Configure console logging for the example."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )


def build_components():
    """Instantiate and wire the core components."""
    config = StreamConfig(symbols=[SYMBOL])
    source = MockDataSource()
    stream = StreamingService(config=config, data_source=source)
    tape = TimeAndSalesService()
    analyzer = AdvancedOrderFlowAnalyzer()
    return stream, tape, analyzer


def print_metrics(analyzer: AdvancedOrderFlowAnalyzer, symbol: str) -> None:
    """Print a snapshot of current order-flow metrics to stdout."""
    aggression = analyzer.get_aggression_metrics(symbol)
    oscillator = analyzer.get_order_flow_oscillator(symbol)
    pressure = analyzer.get_pressure_gauges(symbol)

    print(f"\n{'='*50}")
    print(f"  Order Flow Snapshot — {symbol}  {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
    print(f"{'='*50}")

    if aggression:
        print(f"  Buy aggression  : {aggression.buy_aggression:6.1f}%")
        print(f"  Sell aggression : {aggression.sell_aggression:6.1f}%")
        print(f"  Score           : {aggression.aggression_score:+.1f}  ({aggression.dominant_side})")

    if oscillator:
        print(f"  OFO value       : {oscillator.value:+.1f}  → {oscillator.signal}")

    if pressure:
        print(f"  Buy pressure    : {pressure['buy_pressure']:6.1f}%")
        print(f"  Sell pressure   : {pressure['sell_pressure']:6.1f}%")

    clusters = analyzer.get_volume_clusters(symbol, top_n=3)
    if clusters:
        print("  Volume clusters :")
        for cluster in clusters:
            print(
                f"    {cluster.price_level:10.5f}  "
                f"{cluster.cluster_type:<12}  "
                f"strength={cluster.strength:.2f}"
            )


def simulate_trades(analyzer: AdvancedOrderFlowAnalyzer, symbol: str) -> None:
    """Add a batch of simulated trades to the analyzer."""
    _rng = secrets.SystemRandom()

    base_price = 1950.0
    for _ in range(100):
        price = base_price + _rng.uniform(-5, 5)
        size = _rng.uniform(0.1, 2.0)
        side = "buy" if _rng.random() > 0.45 else "sell"
        ts = datetime.now(timezone.utc)
        analyzer.add_trade(symbol, price, size, side, ts)


def run_example() -> None:
    """Run the order-flow example synchronously."""
    setup_logging()
    logger.info("Starting order flow example …")

    _, _, analyzer = build_components()

    # Seed the analyzer with simulated data
    simulate_trades(analyzer, SYMBOL)

    # Print metrics snapshot
    print_metrics(analyzer, SYMBOL)

    # Detect delta divergence
    divergence = analyzer.detect_delta_divergence(SYMBOL)
    if divergence:
        print(f"\n  ⚡ Delta divergence: {divergence.divergence_type} "
              f"(confidence={divergence.confidence:.2f})")
    else:
        print("\n  No delta divergence detected.")

    # Stacked imbalances
    stacked = analyzer.get_stacked_imbalances(SYMBOL)
    if stacked:
        print(f"\n  Stacked imbalances: {len(stacked)} found")
        for si in stacked[:3]:
            print(f"    Direction={si.direction}  levels={len(si.levels)}  "
                  f"strength={si.strength}")
    else:
        print("\n  No stacked imbalances found.")

    logger.info("Example complete.")


if __name__ == "__main__":
    run_example()
