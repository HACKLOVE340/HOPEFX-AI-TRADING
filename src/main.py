#!/usr/bin/env python3
"""
HOPEFX Trading Platform - Main Entry Point

Usage:
    python -m src.main              # Run API server
    python -m src.main backtest     # Run backtest mode
    python -m src.main live         # Run live trading
    python -m src.main worker       # Run background worker
"""
import sys
import asyncio
import argparse
import uvicorn
from src.config.settings import get_settings

settings = get_settings()


def run_api_server():
    """Run FastAPI server with uvicorn."""
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        workers=1 if settings.environment == "development" else 4,
        log_level=settings.log_level.lower(),
        access_log=False  # We handle logging via structlog
    )


def run_backtest():
    """Run backtest mode."""
    from src.backtest.engine import BacktestEngine
    from src.strategies.xauusd_ml import XAUUSDMLEnsemble
    
    async def _run():
        engine = BacktestEngine(
            initial_capital=10000.0,
            start_date="2023-01-01",
            end_date="2024-01-01",
            symbols=["XAUUSD"]
        )
        
        strategy = XAUUSDMLEnsemble()
        results = await engine.run(strategy)
        
        print(f"\nBacktest Results:")
        print(f"Total Return: {results['total_return_pct']:.2f}%")
        print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        print(f"Max Drawdown: {results['max_drawdown_pct']:.2f}%")
        print(f"Win Rate: {results['win_rate_pct']:.2f}%")
        print(f"Report saved to: {results['report_path']}")
    
    asyncio.run(_run())


def run_live_trading():
    """Run live trading mode."""
    from src.core.trading_engine import TradingEngine
    
    async def _run():
        engine = TradingEngine()
        try:
            await engine.start()
            # Keep running until interrupted
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await engine.stop()
    
    asyncio.run(_run())


def run_worker():
    """Run background worker for ML retraining, etc."""
    from src.ml.online_learning import OnlineLearningWorker
    
    async def _run():
        worker = OnlineLearningWorker()
        await worker.start()
    
    asyncio.run(_run())


def main():
    parser = argparse.ArgumentParser(description="HOPEFX Trading Platform")
    parser.add_argument(
        "command",
        choices=["api", "backtest", "live", "worker"],
        default="api",
        nargs="?",
        help="Command to run (default: api)"
    )
    
    args = parser.parse_args()
    
    commands = {
        "api": run_api_server,
        "backtest": run_backtest,
        "live": run_live_trading,
        "worker": run_worker
    }
    
    commands[args.command]()


if __name__ == "__main__":
    main()
