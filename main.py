#!/usr/bin/env python3
"""
HOPEFX AI Trading Framework - Main Entry Point

This is the main entry point for the HOPEFX AI Trading framework.
It initializes the application, loads configuration, and starts the trading system.
"""

import sys
import os
import logging
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import initialize_config, get_config_manager
from cache import MarketDataCache
from database.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


class HopeFXTradingApp:
    """Main application class for HOPEFX AI Trading Framework"""
    
    def __init__(self, environment: Optional[str] = None):
        """
        Initialize the trading application
        
        Args:
            environment: Environment to run in (development, staging, production)
        """
        self.environment = environment or os.getenv('APP_ENV', 'development')
        self.config = None
        self.db_engine = None
        self.db_session = None
        self.cache = None
        
        logger.info(f"Initializing HOPEFX AI Trading Framework v1.0.0")
        logger.info(f"Environment: {self.environment}")
    
    def initialize(self):
        """Initialize all components"""
        logger.info("=" * 70)
        logger.info("HOPEFX AI TRADING FRAMEWORK - INITIALIZATION")
        logger.info("=" * 70)
        
        # Step 1: Load configuration
        self._init_config()
        
        # Step 2: Initialize database
        self._init_database()
        
        # Step 3: Initialize cache
        self._init_cache()
        
        logger.info("=" * 70)
        logger.info("INITIALIZATION COMPLETE")
        logger.info("=" * 70)
    
    def _init_config(self):
        """Initialize configuration"""
        logger.info("[1/3] Loading configuration...")
        
        try:
            # Check for required environment variables
            encryption_key = os.getenv('CONFIG_ENCRYPTION_KEY')
            if not encryption_key:
                logger.warning(
                    "CONFIG_ENCRYPTION_KEY not set. "
                    "Using default for development only!"
                )
                os.environ['CONFIG_ENCRYPTION_KEY'] = 'dev-key-minimum-32-characters-long-for-testing'
            
            # Initialize configuration
            self.config = initialize_config(environment=self.environment)
            
            logger.info(f"✓ Configuration loaded: {self.config.app_name} v{self.config.version}")
            logger.info(f"  - Environment: {self.config.environment}")
            logger.info(f"  - Debug mode: {self.config.debug}")
            logger.info(f"  - Database: {self.config.database.db_type}")
            logger.info(f"  - Trading enabled: {self.config.trading.trading_enabled}")
            logger.info(f"  - Paper trading: {self.config.trading.paper_trading_mode}")
            
        except Exception as e:
            logger.error(f"✗ Configuration failed: {e}")
            raise
    
    def _init_database(self):
        """Initialize database connection"""
        logger.info("[2/3] Initializing database...")
        
        try:
            # Create database directory if needed
            if self.config.database.db_type == 'sqlite':
                db_path = Path(self.config.database.database)
                db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create engine
            connection_string = self.config.database.get_connection_string()
            self.db_engine = create_engine(
                connection_string,
                pool_size=self.config.database.connection_pool_size,
                max_overflow=self.config.database.max_overflow,
                pool_timeout=self.config.database.pool_timeout,
                echo=self.config.debug,
            )
            
            # Create all tables
            Base.metadata.create_all(self.db_engine)
            
            # Create session factory
            Session = sessionmaker(bind=self.db_engine)
            self.db_session = Session()
            
            logger.info(f"✓ Database initialized: {self.config.database.db_type}")
            logger.info(f"  - Connection: {connection_string.split('@')[-1] if '@' in connection_string else connection_string}")
            
        except Exception as e:
            logger.error(f"✗ Database initialization failed: {e}")
            raise
    
    def _init_cache(self):
        """Initialize Redis cache"""
        logger.info("[3/3] Initializing cache...")
        
        try:
            # Get Redis configuration from environment or use defaults
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            redis_db = int(os.getenv('REDIS_DB', 0))
            redis_password = os.getenv('REDIS_PASSWORD', None)
            
            # Initialize cache with retry logic
            self.cache = MarketDataCache(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                max_retries=3,
                retry_delay=1.0,
            )
            
            # Test connection
            if self.cache.health_check():
                logger.info(f"✓ Cache initialized: Redis at {redis_host}:{redis_port}")
            else:
                logger.warning("⚠ Cache health check failed, but continuing...")
                
        except Exception as e:
            logger.warning(f"⚠ Cache initialization failed: {e}")
            logger.warning("  Continuing without cache (development mode)")
            self.cache = None
    
    def run(self):
        """Run the main application"""
        logger.info("\n" + "=" * 70)
        logger.info("STARTING TRADING APPLICATION")
        logger.info("=" * 70)
        
        try:
            # Display status
            self._display_status()
            
            # Main application logic would go here
            logger.info("\n✓ Application ready!")
            logger.info("  To start the trading engine, implement your strategy.")
            logger.info("  To start the API server, run: hopefx-server")
            logger.info("  To use the CLI, run: hopefx --help")
            
        except KeyboardInterrupt:
            logger.info("\n\nShutdown requested...")
            self.shutdown()
        except Exception as e:
            logger.error(f"Application error: {e}", exc_info=True)
            self.shutdown()
            raise
    
    def _display_status(self):
        """Display application status"""
        logger.info("\nApplication Status:")
        logger.info(f"  ✓ Config: Loaded ({self.config.environment})")
        logger.info(f"  ✓ Database: Connected ({self.config.database.db_type})")
        logger.info(f"  {'✓' if self.cache else '⚠'} Cache: {'Connected' if self.cache else 'Not available'}")
        logger.info(f"  ✓ API Configs: {len(self.config.api_configs)} configured")
    
    def shutdown(self):
        """Gracefully shutdown the application"""
        logger.info("Shutting down...")
        
        # Close database session
        if self.db_session:
            self.db_session.close()
            logger.info("  ✓ Database session closed")
        
        # Close database engine
        if self.db_engine:
            self.db_engine.dispose()
            logger.info("  ✓ Database engine disposed")
        
        # Close cache connection
        if self.cache:
            self.cache.close()
            logger.info("  ✓ Cache connection closed")
        
        logger.info("Shutdown complete.")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='HOPEFX AI Trading Framework',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Run in development mode
  python main.py --env production   # Run in production mode
  python main.py --version          # Show version

Environment Variables:
  CONFIG_ENCRYPTION_KEY   - Required: Master encryption key
  CONFIG_SALT            - Optional: Encryption salt (hex-encoded)
  APP_ENV                - Optional: Environment (development/staging/production)
  REDIS_HOST             - Optional: Redis host (default: localhost)
  REDIS_PORT             - Optional: Redis port (default: 6379)

For more information, see README.md and SECURITY.md
        """
    )
    
    parser.add_argument(
        '--env', '--environment',
        dest='environment',
        choices=['development', 'staging', 'production'],
        help='Environment to run in'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='HOPEFX AI Trading Framework v1.0.0'
    )
    
    args = parser.parse_args()
    
    # Create and run application
    app = HopeFXTradingApp(environment=args.environment)
    
    try:
        app.initialize()
        app.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
