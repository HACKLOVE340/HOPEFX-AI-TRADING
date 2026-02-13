#!/usr/bin/env python3
"""
HOPEFX AI Trading Framework - Command Line Interface

Provides a command-line interface for managing the trading framework.
"""

import sys
import os
from pathlib import Path
import argparse
import logging

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import get_config_manager, initialize_config
from cache import MarketDataCache
from database.models import Base
from sqlalchemy import create_engine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cmd_init(args):
    """Initialize the application"""
    logger.info("Initializing HOPEFX AI Trading Framework...")
    
    # Check for encryption key
    if not os.getenv('CONFIG_ENCRYPTION_KEY'):
        logger.error("CONFIG_ENCRYPTION_KEY environment variable not set!")
        logger.info("Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"")
        return 1
    
    try:
        # Initialize config
        config = initialize_config(environment=args.environment)
        logger.info(f"✓ Configuration initialized: {config.environment}")
        
        # Create database
        connection_string = config.database.get_connection_string()
        engine = create_engine(connection_string)
        Base.metadata.create_all(engine)
        logger.info(f"✓ Database tables created: {config.database.db_type}")
        
        # Create required directories
        Path("logs").mkdir(exist_ok=True)
        Path("data").mkdir(exist_ok=True)
        Path("credentials").mkdir(exist_ok=True)
        logger.info("✓ Required directories created")
        
        logger.info("\n✓ Initialization complete!")
        logger.info("  Run 'hopefx status' to check system status")
        return 0
        
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        return 1


def cmd_status(args):
    """Show system status"""
    logger.info("Checking system status...\n")
    
    try:
        # Check config
        config = initialize_config()
        logger.info(f"✓ Configuration: {config.app_name} v{config.version}")
        logger.info(f"  Environment: {config.environment}")
        logger.info(f"  Debug: {config.debug}")
        
        # Check database
        connection_string = config.database.get_connection_string()
        engine = create_engine(connection_string)
        engine.connect()
        logger.info(f"✓ Database: Connected ({config.database.db_type})")
        
        # Check cache
        try:
            cache = MarketDataCache()
            if cache.health_check():
                stats = cache.get_statistics()
                logger.info(f"✓ Cache: Connected (hit rate: {stats.hit_rate:.2f}%)")
            else:
                logger.warning("⚠ Cache: Connection failed")
        except:
            logger.warning("⚠ Cache: Not available")
        
        # Check API configs
        logger.info(f"✓ API Configurations: {len(config.api_configs)} configured")
        
        # Check directories
        dirs = {
            "logs": Path("logs"),
            "data": Path("data"),
            "credentials": Path("credentials"),
        }
        for name, path in dirs.items():
            if path.exists():
                logger.info(f"✓ Directory '{name}': Exists")
            else:
                logger.warning(f"⚠ Directory '{name}': Not found")
        
        logger.info("\n✓ System status check complete")
        return 0
        
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return 1


def cmd_config(args):
    """Manage configuration"""
    if args.action == 'show':
        try:
            config = initialize_config()
            logger.info("Current Configuration:")
            logger.info(f"  App: {config.app_name} v{config.version}")
            logger.info(f"  Environment: {config.environment}")
            logger.info(f"  Debug: {config.debug}")
            logger.info(f"  Database: {config.database.db_type}")
            logger.info(f"  Trading enabled: {config.trading.trading_enabled}")
            logger.info(f"  Paper trading: {config.trading.paper_trading_mode}")
            return 0
        except Exception as e:
            logger.error(f"Failed to show config: {e}")
            return 1
    
    elif args.action == 'validate':
        try:
            config = initialize_config()
            if config.validate():
                logger.info("✓ Configuration is valid")
                return 0
            else:
                logger.error("✗ Configuration validation failed")
                return 1
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return 1
    
    return 0


def cmd_cache(args):
    """Manage cache"""
    try:
        cache = MarketDataCache()
        
        if args.action == 'stats':
            stats = cache.get_statistics()
            logger.info("Cache Statistics:")
            logger.info(f"  Total keys: {stats.total_keys}")
            logger.info(f"  Total hits: {stats.total_hits}")
            logger.info(f"  Total misses: {stats.total_misses}")
            logger.info(f"  Hit rate: {stats.hit_rate:.2f}%")
            logger.info(f"  Memory usage: {stats.memory_usage_bytes / 1024 / 1024:.2f} MB")
            
        elif args.action == 'clear':
            if cache.clear_all():
                logger.info("✓ Cache cleared")
            else:
                logger.error("✗ Failed to clear cache")
                return 1
        
        elif args.action == 'health':
            if cache.health_check():
                logger.info("✓ Cache is healthy")
            else:
                logger.error("✗ Cache health check failed")
                return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"Cache operation failed: {e}")
        return 1


def cmd_db(args):
    """Manage database"""
    try:
        config = initialize_config()
        connection_string = config.database.get_connection_string()
        engine = create_engine(connection_string)
        
        if args.action == 'create':
            Base.metadata.create_all(engine)
            logger.info("✓ Database tables created")
            
        elif args.action == 'drop':
            if not args.force:
                logger.error("This will delete all data! Use --force to confirm")
                return 1
            Base.metadata.drop_all(engine)
            logger.info("✓ Database tables dropped")
        
        return 0
        
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        return 1


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog='hopefx',
        description='HOPEFX AI Trading Framework CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='HOPEFX AI Trading Framework v1.0.0'
    )
    
    parser.add_argument(
        '--env', '--environment',
        dest='environment',
        default=None,
        help='Environment (development/staging/production)'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # init command
    parser_init = subparsers.add_parser('init', help='Initialize the application')
    parser_init.set_defaults(func=cmd_init)
    
    # status command
    parser_status = subparsers.add_parser('status', help='Show system status')
    parser_status.set_defaults(func=cmd_status)
    
    # config command
    parser_config = subparsers.add_parser('config', help='Manage configuration')
    parser_config.add_argument(
        'action',
        choices=['show', 'validate'],
        help='Config action'
    )
    parser_config.set_defaults(func=cmd_config)
    
    # cache command
    parser_cache = subparsers.add_parser('cache', help='Manage cache')
    parser_cache.add_argument(
        'action',
        choices=['stats', 'clear', 'health'],
        help='Cache action'
    )
    parser_cache.set_defaults(func=cmd_cache)
    
    # db command
    parser_db = subparsers.add_parser('db', help='Manage database')
    parser_db.add_argument(
        'action',
        choices=['create', 'drop'],
        help='Database action'
    )
    parser_db.add_argument('--force', action='store_true', help='Force operation')
    parser_db.set_defaults(func=cmd_db)
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    # Execute command
    try:
        return args.func(args)
    except Exception as e:
        logger.error(f"Command failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
