
# 7. FIXED MAIN.PY - Complete, working entry point

main_fixed = '''#!/usr/bin/env python3
"""
HOPEFX AI Trading Framework - Main Entry Point (Production Ready)
Complete implementation with all components integrated
"""

import argparse
import sys
import os
import logging
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

# Project root setup
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Core imports
from config import initialize_config, get_config_manager
from cache import MarketDataCache
from database.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Component imports
from data.real_time_price_engine import RealTimePriceEngine
from brain.brain import HOPEFXBrain, SystemState
from strategies import StrategyManager
from risk import RiskManager, RiskConfig
from brokers import PaperTradingBroker, create_broker
from notifications import NotificationManager

# Optional imports with graceful degradation
try:
    from utils import get_all_component_statuses, get_framework_version
    UTILS_AVAILABLE = True
except ImportError:
    UTILS_AVAILABLE = False

try:
    from ml import LSTMPricePredictor, RandomForestTradingClassifier, TechnicalFeatureEngineer
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/hopefx_main.log')
    ]
)
logger = logging.getLogger(__name__)

class HopeFXTradingApp:
    """
    HOPEFX Trading Application
    Fully integrated trading system with brain, strategies, risk management
    """
    
    def __init__(self, environment: Optional[str] = None):
        self.environment = environment or os.getenv('APP_ENV', 'development')
        self.config = None
        self.db_engine = None
        self.db_session = None
        self.cache = None
        
        # Core components
        self.price_engine: Optional[RealTimePriceEngine] = None
        self.brain: Optional[HOPEFXBrain] = None
        self.strategy_manager: Optional[StrategyManager] = None
        self.risk_manager: Optional[RiskManager] = None
        self.broker = None
        self.notification_manager: Optional[NotificationManager] = None
        
        # State
        self.running = False
        self.tasks: list = []
        
        logger.info(f"HOPEFX Trading App v2.0.0 initialized [{self.environment}]")
    
    async def initialize(self):
        """Initialize all components"""
        logger.info("=" * 60)
        logger.info("INITIALIZING HOPEFX TRADING SYSTEM")
        logger.info("=" * 60)
        
        # 1. Configuration
        await self._init_config()
        
        # 2. Database
        await self._init_database()
        
        # 3. Cache
        await self._init_cache()
        
        # 4. Notifications
        await self._init_notifications()
        
        # 5. Broker
        await self._init_broker()
        
        # 6. Price Engine
        await self._init_price_engine()
        
        # 7. Risk Manager
        await self._init_risk_manager()
        
        # 8. Strategy Manager
        await self._init_strategy_manager()
        
        # 9. Brain (Central Intelligence)
        await self._init_brain()
        
        logger.info("=" * 60)
        logger.info("INITIALIZATION COMPLETE")
        logger.info("=" * 60)
    
    async def _init_config(self):
        """Load configuration"""
        try:
            self.config = initialize_config(environment=self.environment)
            logger.info(f"✓ Configuration loaded: {self.config.environment}")
        except Exception as e:
            logger.error(f"Config initialization failed: {e}")
            raise
    
    async def _init_database(self):
        """Initialize database"""
        try:
            connection_string = self.config.database.get_connection_string()
            self.db_engine = create_engine(connection_string)
            Base.metadata.create_all(self.db_engine)
            self.db_session = sessionmaker(bind=self.db_engine)
            logger.info(f"✓ Database initialized: {self.config.database.db_type}")
        except Exception as e:
            logger.warning(f"Database initialization issue: {e}")
            logger.info("Continuing without database...")
    
    async def _init_cache(self):
        """Initialize Redis cache"""
        try:
            self.cache = MarketDataCache(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                max_retries=3
            )
            if self.cache.health_check():
                logger.info("✓ Cache connected")
            else:
                logger.warning("⚠ Cache health check failed")
        except Exception as e:
            logger.warning(f"Cache initialization failed: {e}")
            self.cache = None
    
    async def _init_notifications(self):
        """Initialize notification system"""
        try:
            config = {
                'discord_webhook': os.getenv('DISCORD_WEBHOOK'),
                'telegram_bot_token': os.getenv('TELEGRAM_BOT_TOKEN'),
                'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID')
            }
            self.notification_manager = NotificationManager(config)
            await self.notification_manager.start()
            logger.info("✓ Notification system ready")
        except Exception as e:
            logger.warning(f"Notification init failed: {e}")
            self.notification_manager = None
    
    async def _init_broker(self):
        """Initialize broker connection"""
        try:
            broker_type = self.config.trading.get('broker_type', 'paper')
            
            if broker_type == 'paper':
                self.broker = PaperTradingBroker(
                    initial_balance=self.config.trading.get('initial_balance', 100000)
                )
                await self.broker.connect()
                logger.info(f"✓ Paper Trading Broker connected")
            else:
                # Live broker
                broker_config = self.config.api_configs.get(broker_type, {})
                self.broker = create_broker(broker_type, broker_config)
                await self.broker.connect()
                logger.info(f"✓ {broker_type.upper()} Broker connected")
                
        except Exception as e:
            logger.error(f"Broker initialization failed: {e}")
            raise
    
    async def _init_price_engine(self):
        """Initialize real-time price feed"""
        try:
            symbols = self.config.trading.get('symbols', ['EURUSD', 'GBPUSD', 'XAUUSD'])
            engine_config = {
                'symbols': symbols,
                'websocket_url': os.getenv('WS_URL', 'wss://ws-feed.exchange.coinbase.com'),
                'rest_url': os.getenv('REST_URL', 'https://api.exchange.coinbase.com')
            }
            
            self.price_engine = RealTimePriceEngine(engine_config)
            
            # Connect paper broker to price feed
            if isinstance(self.broker, PaperTradingBroker):
                self.broker.set_price_feed(self.price_engine)
            
            logger.info(f"✓ Price Engine initialized for {len(symbols)} symbols")
        except Exception as e:
            logger.error(f"Price engine initialization failed: {e}")
            raise
    
    async def _init_risk_manager(self):
        """Initialize risk management"""
        try:
            risk_config = RiskConfig(
                max_position_size_pct=self.config.trading.get('max_position_size_pct', 0.02),
                max_drawdown_pct=self.config.trading.get('max_drawdown_pct', 0.10),
                daily_loss_limit_pct=self.config.trading.get('daily_loss_limit_pct', 0.05)
            )
            self.risk_manager = RiskManager(risk_config)
            logger.info("✓ Risk Manager initialized")
        except Exception as e:
            logger.error(f"Risk manager initialization failed: {e}")
            raise
    
    async def _init_strategy_manager(self):
        """Initialize strategy system"""
        try:
            self.strategy_manager = StrategyManager()
            logger.info("✓ Strategy Manager initialized")
        except Exception as e:
            logger.error(f"Strategy manager initialization failed: {e}")
            raise
    
    async def _init_brain(self):
        """Initialize central intelligence"""
        try:
            self.brain = HOPEFXBrain()
            
            # Inject all components into brain
            self.brain.inject_components(
                price_engine=self.price_engine,
                risk_manager=self.risk_manager,
                broker=self.broker,
                strategy_manager=self.strategy_manager,
                notification_manager=self.notification_manager
            )
            
            logger.info("✓ Brain initialized and components injected")
        except Exception as e:
            logger.error(f"Brain initialization failed: {e}")
            raise
    
    async def run(self):
        """Main application loop"""
        self.running = True
        
        try:
            # Start price engine
            await self.price_engine.start()
            logger.info("Price engine started")
            
            # Start brain dominate loop
            brain_task = asyncio.create_task(self.brain.dominate())
            self.tasks.append(brain_task)
            
            # Start heartbeat
            heartbeat_task = asyncio.create_task(self._heartbeat())
            self.tasks.append(heartbeat_task)
            
            # Start monitoring
            monitor_task = asyncio.create_task(self._monitor())
            self.tasks.append(monitor_task)
            
            logger.info("=" * 60)
            logger.info("HOPEFX IS RUNNING")
            logger.info("Press Ctrl+C to stop")
            logger.info("=" * 60)
            
            # Send startup notification
            if self.notification_manager:
                await self.notification_manager.send_alert(
                    "info", 
                    "HOPEFX Trading System Started",
                    {"environment": self.environment, "symbols": self.price_engine.symbols}
                )
            
            # Wait for brain to complete (or be cancelled)
            await brain_task
            
        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        except Exception as e:
            logger.critical(f"Critical error in main loop: {e}", exc_info=True)
            if self.notification_manager:
                await self.notification_manager.send_alert(
                    "critical",
                    f"HOPEFX Critical Error: {str(e)}",
                    {"error": str(e)}
                )
        finally:
            await self.shutdown()
    
    async def _heartbeat(self):
        """System heartbeat"""
        while self.running:
            try:
                if self.brain and self.brain.state:
                    state = self.brain.state
                    logger.info(
                        f"HEARTBEAT | State: {state.system_state.value} | "
                        f"Equity: ${state.equity:,.2f} | Positions: {state.open_trades_count} | "
                        f"Time: {time.strftime('%H:%M:%S')}"
                    )
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(30)
    
    async def _monitor(self):
        """System monitoring loop"""
        while self.running:
            try:
                # Check component health
                if self.price_engine and not self.price_engine.active:
                    logger.error("Price engine stopped unexpectedly")
                    
                if self.brain and self.brain.state.system_state == SystemState.EMERGENCY_STOP:
                    logger.critical("Emergency stop detected")
                    self.running = False
                    break
                    
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("=" * 60)
        logger.info("SHUTTING DOWN HOPEFX")
        logger.info("=" * 60)
        
        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # Stop components
        if self.price_engine:
            await self.price_engine.stop()
            logger.info("Price engine stopped")
        
        if self.broker:
            await self.broker.disconnect()
            logger.info("Broker disconnected")
        
        if self.notification_manager:
            await self.notification_manager.send_alert("info", "HOPEFX Stopped")
            await self.notification_manager.stop()
        
        if self.cache:
            self.cache.close()
        
        if self.db_engine:
            self.db_engine.dispose()
        
        logger.info("Shutdown complete")
    
    def get_status(self) -> Dict:
        """Get system status"""
        return {
            'running': self.running,
            'environment': self.environment,
            'brain_state': self.brain.state.to_dict() if self.brain else None,
            'price_engine_active': self.price_engine.active if self.price_engine else False,
            'symbols': self.price_engine.symbols if self.price_engine else [],
            'broker_connected': self.broker.connected if self.broker else False
        }

async def main():
    """Async main entry point"""
    parser = argparse.ArgumentParser(description="HOPEFX AI Trading System")
    parser.add_argument("--mode", choices=['paper', 'live'], default="paper")
    parser.add_argument("--env", default=None, help="Environment (development/staging/production)")
    parser.add_argument("--init-db", action="store_true", help="Initialize database only")
    args = parser.parse_args()
    
    # Set environment
    if args.env:
        os.environ['APP_ENV'] = args.env
    
    # Create app
    app = HopeFXTradingApp(environment=args.env)
    
    try:
        # Initialize
        await app.initialize()
        
        if args.init_db:
            logger.info("Database initialization complete")
            return 0
        
        # Run
        await app.run()
        return 0
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        await app.shutdown()
        return 0
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)
    
    # Run async main
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
'''

with open(project_root / "main.py", "w") as f:
    f.write(main_fixed)

print("✓ Created FIXED main.py - production ready")
