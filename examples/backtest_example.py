"""
Example: Running a Simple Backtest

Demonstrates how to backtest a strategy using the backtesting engine.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting import (
    DataHandler,
    YahooFinanceSource,
    BacktestEngine
)
from strategies import MovingAverageCrossover, StrategyConfig


def main():
    """Run a simple backtest example."""

    print("="*60)
    print("BACKTEST EXAMPLE: Moving Average Crossover")
    print("="*60)

    # 1. Setup data source
    data_source = YahooFinanceSource(interval='1d')

    # 2. Create data handler
    data_handler = DataHandler(
        data_source=data_source,
        symbols=['AAPL'],
        start_date='2020-01-01',
        end_date='2023-12-31'
    )

    # 3. Create strategy
    strategy_config = StrategyConfig(
        name='MA_Crossover',
        symbol='AAPL',
        timeframe='1D'
    )
    strategy = MovingAverageCrossover(strategy_config)

    # 4. Create backtest engine
    engine = BacktestEngine(
        data_handler=data_handler,
        strategy=strategy,
        initial_capital=100000,
        commission_pct=0.001,  # 0.1%
        slippage_pct=0.0005    # 0.05%
    )

    # 5. Run backtest
    print("\nRunning backtest...")
    results = engine.run()

    # 6. Print results
    engine.print_results()

    # 7. Optional: Save detailed report
    from backtesting import ReportGenerator
    report_gen = ReportGenerator(results)
    report_gen.save_to_file('backtest_report.txt')
    print("Detailed report saved to: backtest_report.txt")

    # 8. Optional: Plot equity curve
    try:
        from backtesting import PerformancePlotter
        plotter = PerformancePlotter(results)
        plotter.plot_equity_curve('equity_curve.png')
        plotter.plot_drawdown('drawdown.png')
        print("Charts saved: equity_curve.png, drawdown.png")
    except Exception as e:
        print(f"Plotting skipped: {e}")


if __name__ == '__main__':
    main()
