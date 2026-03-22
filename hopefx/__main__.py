#!/usr/bin/env python3
"""
HOPEFX Institutional v4.0 - Entry Point

Usage:
    python -m hopefx                    # Run server
    python -m hopefx --mode backtest    # Run backtest
    python -m hopefx --mode train       # Train ML model
    python -m hopefx --mode prop-firm   # Prop firm challenge mode
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hopefx.api.main import app
from hopefx.core.events import event_bus
from hopefx.infrastructure.logging import setup_logging, get_logger
from hopefx.monitoring.metrics import metrics

logger = get_logger("hopefx.main")

def main():
    parser = argparse.ArgumentParser(description="HOPEFX Institutional Trading Platform")
    parser.add_argument("--mode", choices=["server", "backtest", "train", "prop-firm"], default="server")
    parser.add_argument("--config", default="config.yaml", help="Configuration file")
    parser.add_argument("--port", type=int, default=8000, help="API port")
    parser.add_argument("--metrics-port", type=int, default=9090, help="Metrics port")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    logger.info("HOPEFX Institutional v4.0 starting", mode=args.mode)
    
    if args.mode == "server":
        run_server(args.port, args.metrics_port)
    elif args.mode == "backtest":
        run_backtest(args.config)
    elif args.mode == "train":
        run_training(args.config)
    elif args.mode == "prop-firm":
        run_prop_firm_challenge(args.config)

def run_server(port: int, metrics_port: int):
    """Run API server with metrics."""
    import uvicorn
    
    # Start metrics
    metrics.start_server(metrics_port)
    
    # Run server
    uvicorn.run(
        "hopefx.api.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False
    )

def run_backtest(config_path: str):
    """Run backtesting mode."""
    logger.info("Starting backtest", config=config_path)
    # Implementation would load config and run backtest
    pass

def run_training(config_path: str):
    """Run ML training mode."""
    logger.info("Starting training", config=config_path)
    pass

def run_prop_firm_challenge(config_path: str):
    """Run prop firm challenge with strict compliance."""
    logger.info("Starting prop firm challenge", config=config_path)
    # Implementation would load challenge rules and enforce strictly
    pass

if __name__ == "__main__":
    main()
