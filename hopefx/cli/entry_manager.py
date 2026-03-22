#!/usr/bin/env python3
"""
HOPEFX Unified Entry Point Manager
Replaces: app.py, production_fastapi_app.py, main.py, main_ultimate*.py
Usage: python -m hopefx [command]
"""

import argparse
import sys
import os
import logging
from typing import Optional, Dict, Any
from pathlib import Path

# Configure logging before anything else
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/hopefx_startup.log')
    ]
)
logger = logging.getLogger(__name__)

class EntryPointManager:
    """
    Centralized entry point manager that routes to appropriate subsystems
    based on command-line arguments and environment.
    """
    
    MODES = {
        'development': {
            'server': 'fastapi_dev',
            'auto_reload': True,
            'debug': True,
            'log_level': 'debug'
        },
        'production': {
            'server': 'fastapi_prod',
            'auto_reload': False,
            'debug': False,
            'log_level': 'warning',
            'workers': 4
        },
        'cli': {
            'interface': 'interactive',
            'log_level': 'info'
        },
        'backtest': {
            'engine': 'event_driven',
            'parallel': True
        },
        'train': {
            'ml_backend': 'sklearn_xgboost',
            'gpu': False
        }
    }
    
    def __init__(self):
        self.config = self._load_config()
        self.mode = os.getenv('HOPEFX_MODE', 'development')
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment and config files."""
        from hopefx.config.config_manager import ConfigManager
        return ConfigManager().get_config()
    
    def _ensure_directories(self):
        """Create necessary output directories."""
        dirs = [
            'logs', 'outputs/equity_curves', 'outputs/models',
            'outputs/reports', 'data/ticks', 'data/ohlcv',
            'cache/backtest', 'cache/ml'
        ]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
            
    def run_fastapi_dev(self, host: str = '0.0.0.0', port: int = 5000):
        """Run development FastAPI server."""
        import uvicorn
        from hopefx.api.fastapi_app import create_app
        
        logger.info(f"Starting development server on {host}:{port}")
        self._ensure_directories()
        
        app = create_app(debug=True)
        uvicorn.run(
            app, host=host, port=port,
            reload=True, log_level='debug'
        )
    
    def run_fastapi_prod(self, host: str = '0.0.0.0', port: int = 8000):
        """Run production FastAPI server with multiple workers."""
        import uvicorn
        from hopefx.api.fastapi_app import create_app
        
        logger.info(f"Starting production server on {host}:{port}")
        self._ensure_directories()
        
        app = create_app(debug=False)
        uvicorn.run(
            app, host=host, port=port,
            workers=self.MODES['production']['workers'],
            log_level='warning',
            access_log=False
        )
    
    def run_cli(self):
        """Run interactive CLI mode."""
        from hopefx.cli.interactive import InteractiveShell
        
        logger.info("Starting interactive CLI")
        shell = InteractiveShell()
        shell.cmdloop()
    
    def run_backtest(self, strategy_file: Optional[str] = None):
        """Run backtesting engine."""
        from hopefx.backtest.engine import BacktestEngine
        
        logger.info("Starting backtest engine")
        self._ensure_directories()
        
        engine = BacktestEngine(self.config)
        if strategy_file:
            engine.load_strategy(strategy_file)
        engine.run()
        
    def run_training(self, model_type: str = 'xgboost'):
        """Run ML training pipeline."""
        from hopefx.ml.training_pipeline import TrainingPipeline
        
        logger.info(f"Starting training pipeline for {model_type}")
        self._ensure_directories()
        
        pipeline = TrainingPipeline(self.config)
        pipeline.train(model_type=model_type)
        pipeline.save_model(f'outputs/models/{model_type}_{datetime.now():%Y%m%d}.pkl')

def main():
    parser = argparse.ArgumentParser(
        description='HOPEFX AI Trading Platform',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s server --mode development          # Start dev server
  %(prog)s server --mode production --port 8000  # Start prod server
  %(prog)s cli                               # Interactive shell
  %(prog)s backtest --strategy my_strategy.py # Run backtest
  %(prog)s train --model xgboost             # Train ML model
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Server command
    server_parser = subparsers.add_parser('server', help='Start API server')
    server_parser.add_argument('--mode', choices=['development', 'production'], 
                              default='development')
    server_parser.add_argument('--host', default='0.0.0.0')
    server_parser.add_argument('--port', type=int, default=5000)
    
    # CLI command
    subparsers.add_parser('cli', help='Interactive CLI mode')
    
    # Backtest command
    backtest_parser = subparsers.add_parser('backtest', help='Run backtest')
    backtest_parser.add_argument('--strategy', help='Strategy file path')
    backtest_parser.add_argument('--start-date')
    backtest_parser.add_argument('--end-date')
    
    # Train command
    train_parser = subparsers.add_parser('train', help='Train ML model')
    train_parser.add_argument('--model', choices=['xgboost', 'lstm', 'random_forest'],
                             default='xgboost')
    train_parser.add_argument('--data-path')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    manager = EntryPointManager()
    
    # Route to appropriate handler
    if args.command == 'server':
        if args.mode == 'production':
            manager.run_fastapi_prod(args.host, args.port)
        else:
            manager.run_fastapi_dev(args.host, args.port)
    elif args.command == 'cli':
        manager.run_cli()
    elif args.command == 'backtest':
        manager.run_backtest(args.strategy)
    elif args.command == 'train':
        manager.run_training(args.model)

if __name__ == '__main__':
    main()
