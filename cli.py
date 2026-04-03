#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.

# Load .env first so all env vars are available before any module imports
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(override=False)
except ImportError:
    ...  # nosec B110
# No commercial use without explicit permission.
"""
HOPEFX AI Trading Framework - Command Line Interface

Provides a command-line interface for managing the trading framework.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from cache import MarketDataCache
from config import initialize_config
from database.models import Base

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def cmd_init(args):
    """Initialize the application"""
    logger.info("Initializing HOPEFX AI Trading Framework...")

    try:
        # Initialize config (auto-generates CONFIG_ENCRYPTION_KEY if missing)
        config = initialize_config(environment=args.environment)
        logger.info("✓ Configuration initialized: %s", config.environment)

        # Create database
        connection_string = config.database.get_connection_string()
        engine = create_engine(connection_string)
        Base.metadata.create_all(engine)
        logger.info("✓ Database tables created: %s", config.database.db_type)

        # Create required directories
        Path("logs").mkdir(exist_ok=True)
        Path("data").mkdir(exist_ok=True)
        Path("credentials").mkdir(exist_ok=True)
        logger.info("✓ Required directories created")

        logger.info("\n✓ Initialization complete!")
        logger.info("  Run 'hopefx status' to check system status")
        return 0

    except Exception as e:
        logger.error("Initialization failed: %s", e)

        return 1


def cmd_status(args):
    """Show system status"""
    logger.info("Checking system status...\n")

    try:
        # Check config
        config = initialize_config()
        logger.info("✓ Configuration: %s v%s", config.app_name, config.version)

        logger.info("  Environment: %s", config.environment)

        logger.info("  Debug: %s", config.debug)

        # Check database
        connection_string = config.database.get_connection_string()
        engine = create_engine(connection_string)
        engine.connect()
        logger.info("✓ Database: Connected (%s)", config.database.db_type)

        # Check cache
        try:
            cache = MarketDataCache(
                socket_timeout=2,
                socket_connect_timeout=2,
                max_retries=1,
                retry_delay=0.0,
            )
            if cache.health_check():
                stats = cache.get_statistics()
                logger.info("✓ Cache: Connected (hit rate: %s%)", stats.hit_rate)

            else:
                logger.warning("⚠ Cache: Connection failed")
        except Exception as exc:
            logger.warning("⚠ Cache: Not available (%s)", exc)

        # Check API configs
        logger.info("✓ API Configurations: %s configured", len(config.api_configs))

        # Check directories
        dirs = {
            "logs": Path("logs"),
            "data": Path("data"),
            "credentials": Path("credentials"),
        }
        for name, path in dirs.items():
            if path.exists():
                logger.info("✓ Directory '%s': Exists", name)

            else:
                logger.warning("⚠ Directory '%s': Not found", name)

        logger.info("\n✓ System status check complete")
        return 0

    except Exception as e:
        logger.error("Status check failed: %s", e)

        return 1


def cmd_config(args):
    """Manage configuration"""
    if args.action == "show":
        try:
            config = initialize_config()
            logger.info("Current Configuration:")
            logger.info("  App: %s v%s", config.app_name, config.version)

            logger.info("  Environment: %s", config.environment)

            logger.info("  Debug: %s", config.debug)

            logger.info("  Database: %s", config.database.db_type)

            logger.info("  Trading enabled: %s", config.trading.trading_enabled)

            logger.info("  Paper trading: %s", config.trading.paper_trading_mode)

            return 0
        except Exception as e:
            logger.error("Failed to show config: %s", e)

            return 1

    elif args.action == "validate":
        try:
            config = initialize_config()
            if config.validate():
                logger.info("✓ Configuration is valid")
                return 0
            logger.error("✗ Configuration validation failed")
            return 1
        except Exception as e:
            logger.error("Validation failed: %s", e)

            return 1

    return 0


def cmd_cache(args):
    """Manage cache"""
    try:
        cache = MarketDataCache()

        if args.action == "stats":
            stats = cache.get_statistics()
            logger.info("Cache Statistics:")
            logger.info("  Total keys: %s", stats.total_keys)

            logger.info("  Total hits: %s", stats.total_hits)

            logger.info("  Total misses: %s", stats.total_misses)

            logger.info("  Hit rate: %s%", stats.hit_rate)

            logger.info("  Memory usage: %s MB", stats.memory_usage_bytes / 1024 / 1024)

        elif args.action == "clear":
            if cache.clear_all():
                logger.info("✓ Cache cleared")
            else:
                logger.error("✗ Failed to clear cache")
                return 1

        elif args.action == "health":
            if cache.health_check():
                logger.info("✓ Cache is healthy")
            else:
                logger.error("✗ Cache health check failed")
                return 1

        return 0

    except Exception as e:
        logger.error("Cache operation failed: %s", e)

        return 1


def cmd_db(args):
    """Manage database"""
    try:
        config = initialize_config()
        connection_string = config.database.get_connection_string()
        engine = create_engine(connection_string)

        if args.action == "create":
            Base.metadata.create_all(engine)
            logger.info("✓ Database tables created")

        elif args.action == "drop":
            if not args.force:
                logger.error("This will delete all data! Use --force to confirm")
                return 1
            Base.metadata.drop_all(engine)
            logger.info("✓ Database tables dropped")

        return 0

    except Exception as e:
        logger.error("Database operation failed: %s", e)

        return 1


def cmd_start(args):
    """Start the API server"""
    import uvicorn

    environment = os.getenv("ENVIRONMENT", "development")

    # Refuse to start in production without a real encryption key
    if not os.getenv("CONFIG_ENCRYPTION_KEY"):
        if environment == "production":
            logger.error(
                "CONFIG_ENCRYPTION_KEY must be set for production. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
            return 1
        logger.warning("CONFIG_ENCRYPTION_KEY not set. Using default for development only.")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "dev-key-minimum-32-characters-long-for-testing"

    host = args.host
    port = args.port
    workers = args.workers
    reload = not args.no_reload

    base_url = f"http://{host}:{port}"
    logger.info("=" * 60)
    logger.info("  HOPEFX AI TRADING - STARTING")
    logger.info("=" * 60)
    logger.info("  API:          %s/", base_url)

    logger.info("  Docs:         %s/docs", base_url)

    logger.info("  Paper Trade:  %s/paper-trading", base_url)

    logger.info("  Pricing:      %s/pricing", base_url)

    logger.info("=" * 60)

    # uvicorn's --reload flag is incompatible with multiple workers;
    # enforce single worker when hot-reload is enabled.
    effective_workers = workers if not reload else 1

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        workers=effective_workers,
        reload=reload,
        log_level="info",
    )
    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="hopefx",
        description="HOPEFX AI Trading Framework CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--version", action="version", version="HOPEFX AI Trading Framework v1.0.0")

    parser.add_argument(
        "--env",
        "--environment",
        dest="environment",
        default=None,
        help="Environment (development/staging/production)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    parser_init = subparsers.add_parser("init", help="Initialize the application")
    parser_init.set_defaults(func=cmd_init)

    # status command
    parser_status = subparsers.add_parser("status", help="Show system status")
    parser_status.set_defaults(func=cmd_status)

    # config command
    parser_config = subparsers.add_parser("config", help="Manage configuration")
    parser_config.add_argument("action", choices=["show", "validate"], help="Config action")
    parser_config.set_defaults(func=cmd_config)

    # cache command
    parser_cache = subparsers.add_parser("cache", help="Manage cache")
    parser_cache.add_argument("action", choices=["stats", "clear", "health"], help="Cache action")
    parser_cache.set_defaults(func=cmd_cache)

    # db command
    parser_db = subparsers.add_parser("db", help="Manage database")
    parser_db.add_argument("action", choices=["create", "drop"], help="Database action")
    parser_db.add_argument("--force", action="store_true", help="Force operation")
    parser_db.set_defaults(func=cmd_db)

    # start command
    parser_start = subparsers.add_parser("start", help="Start the API server")
    parser_start.add_argument(
        "--host",
        default=os.getenv("API_HOST", "127.0.0.1"),
        help="Host to bind (default: 127.0.0.1)",
    )
    parser_start.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("API_PORT", "5000")),
        help="Port to listen on (default: 5000)",
    )
    parser_start.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("API_WORKERS", "1")),
        help="Number of worker processes (default: 1)",
    )
    parser_start.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reload (recommended for production)",
    )
    parser_start.set_defaults(func=cmd_start)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Execute command
    try:
        return args.func(args)
    except Exception as e:
        logger.error("Command failed: %s", e)

        return 1


if __name__ == "__main__":
    sys.exit(main())
