"""
Application entry points for trading engine, API, and worker modes.
"""

import asyncio
import sys
from decimal import Decimal

import click

from src.brokers.paper import PaperBroker
from src.core.config import settings
from src.core.logging_config import configure_logging, get_logger
from src.core.trading_engine import TradingEngine
from src.data.feeds.polygon import PolygonDataFeed
from src.strategies.xauusd_ml import XAUUSDMLStrategy

logger = get_logger(__name__)


@click.group()
def cli():
    """HOPEFX AI Trading Platform CLI."""
    configure_logging(
        log_level=settings.log_level.value,
        json_output=False
    )


@cli.command()
@click.option('--mode', default='paper', help='Trading mode: paper/live')
def trade(mode: str):
    """Start trading engine."""
    async def run():
        # Initialize components
        broker = PaperBroker(initial_balance=Decimal("100000"))
        
        # Data feed (use Polygon in production)
        feed = PolygonDataFeed(symbols=["XAUUSD"])
        
        # Strategy
        strategy = XAUUSDMLStrategy(
            strategy_id="prod_xauusd",
            parameters={
                "lookback": 100,
                "threshold": 0.65,
                "cooldown": 15
            }
        )
        
        # Trading engine
        engine = TradingEngine(
            broker=broker,
            data_feed=feed,
            strategies=[strategy]
        )
        
        await engine.initialize()
        
        try:
            await engine.run()
        except KeyboardInterrupt:
            await engine.shutdown()
    
    asyncio.run(run())


@cli.command()
def api():
    """Start API server."""
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        workers=1 if settings.is_development else 4
    )


@cli.command()
def worker():
    """Start background worker."""
    async def run():
        from src.ml.online_learning import OnlineLearningWorker
        
        worker = OnlineLearningWorker()
        await worker.start()
        
        # Keep running
        while True:
            await asyncio.sleep(60)
    
    asyncio.run(run())


@cli.command()
@click.option('--start', required=True, help='Start date YYYY-MM-DD')
@click.option('--end', required=True, help='End date YYYY-MM-DD')
@click.option('--capital', default=100000, help='Initial capital')
def backtest(start: str, end: str, capital: float):
    """Run backtest."""
    async def run():
        from datetime import datetime
        import pandas as pd
        
        # Load data
        dates = pd.date_range(start=start, end=end, freq='1min')
        data = pd.DataFrame({
            'open': [1800 + i * 0.001 for i in range(len(dates))],
            'high': [1800 + i * 0.001 + 0.5 for i in range(len(dates))],
            'low': [1800 + i * 0.001 - 0.5 for i in range(len(dates))],
            'close': [1800 + i * 0.001 + 0.05 for i in range(len(dates))],
            'volume': [1000] * len(dates),
        }, index=dates)
        
        # Run backtest
        from src.backtest.engine import EventDrivenBacktester
        
        strategy = XAUUSDMLStrategy(strategy_id="backtest")
        backtester = EventDrivenBacktester(initial_capital=Decimal(str(capital)))
        
        result = await backtester.run(strategy, data)
        
        # Print results
        print("\n=== BACKTEST RESULTS ===")
        print(f"Total Return: {result.metrics['total_return']:.2%}")
        print(f"Sharpe Ratio: {result.metrics['sharpe_ratio']:.2f}")
        print(f"Max Drawdown: {result.metrics['max_drawdown']:.2%}")
        print(f"Number of Trades: {result.metrics['num_trades']}")
    
    asyncio.run(run())


if __name__ == "__main__":
    cli()
