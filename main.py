#!/usr/bin/env python3
"""
HOPEFX AI Trading Framework - COMPLETE PRODUCTION SYSTEM
All components integrated and wired together
"""

import argparse
import sys
import os
import asyncio
import signal
import logging
from pathlib import Path

# Core infrastructure (must be first)
from infrastructure.logging import HOPEFXLogger, get_logger, set_context, LogContext
from infrastructure.health import HealthChecker, get_health_checker, start_health_server
from infrastructure.metrics import get_metrics_registry, MetricsRegistry

# Data and execution
from data.real_time_price_engine import RealTimePriceEngine
from data.order_book import MultiSymbolOrderBook
from execution.position_tracker import PositionTracker
from execution.trade_executor import TradeExecutor

# Core intelligence
from brain.brain import HOPEFXBrain, SystemState
from strategies.manager import StrategyManager
from risk.manager import RiskManager, RiskConfig
from brokers import PaperTradingBroker, create_broker

# Infrastructure services
from database.connection import DatabaseManager, init_db_manager
from cache import MarketDataCache
from notifications.manager import NotificationManager, init_notification_manager
from events.event_store import EventStore, get_event_store, publish_event, EventType
from security.encryption import get_credential_manager
from dashboard.web_dashboard import start_dashboard
from api.server import create_api_app, start_api_server

# Utilities
from utils import get_framework_version, get_all_component_statuses

# Setup logging first
HOPEFXLogger().setup(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    log_dir="logs",
    app_name="hopefx",
    json_format=True,
    async_mode=True,
    enable_console=True
)

logger = get_logger(__name__)


class HopeFXTradingApp:
    """
    Complete HOPEFX Trading Application
    All components wired together with proper lifecycle management
    """
    
    def __init__(self, environment: str = "development"):
        self.environment = environment
        self.version = get_framework_version()
        
        # Core state
        self.running = False
        self._shutdown_event = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        self._components_initialized = False
        
        # Infrastructure
        self.db_manager: Optional[DatabaseManager] = None
        self.cache: Optional[MarketDataCache] = None
        self.event_store: Optional[EventStore] = None
        self.credential_manager = get_credential_manager()
        
        # Trading components
        self.price_engine: Optional[RealTimePriceEngine] = None
        self.order_book: Optional[MultiSymbolOrderBook] = None
        self.broker = None
        self.risk_manager: Optional[RiskManager] = None
        self.strategy_manager: Optional[StrategyManager] = None
        self.position_tracker: Optional[PositionTracker] = None
        self.trade_executor: Optional[TradeExecutor] = None
        self.brain: Optional[HOPEFXBrain] = None
        self.notification_manager: Optional[NotificationManager] = None
        
        # Services
        self.health_checker: Optional[HealthChecker] = None
        self.metrics = get_metrics_registry()
        
        logger.info(f"HOPEFX v{self.version} initialized [{environment}]")
    
    async def initialize(self):
        """Initialize all components in dependency order"""
        logger.info("=" * 60)
        logger.info("INITIALIZING HOPEFX TRADING SYSTEM")
        logger.info("=" * 60)
        
        try:
            # 1. Event Store (for audit trail)
            self.event_store = get_event_store()
            await self.event_store.start()
            logger.info("✓ Event store started")
            
            # 2. Database
            db_url = os.getenv('DATABASE_URL', 'sqlite:///hopefx.db')
            self.db_manager = init_db_manager(db_url, pool_size=10)
            logger.info(f"✓ Database connected: {db_url[:20]}...")
            
            # 3. Cache
            self.cache = MarketDataCache(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379))
            )
            logger.info("✓ Cache initialized")
            
            # 4. Notifications
            self.notification_manager = init_notification_manager({
                'discord_webhook': os.getenv('DISCORD_WEBHOOK'),
                'telegram_bot_token': os.getenv('TELEGRAM_BOT_TOKEN'),
                'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID'),
                'environment': self.environment
            })
            await self.notification_manager.start()
            logger.info("✓ Notifications ready")
            
            # 5. Broker
            broker_type = os.getenv('BROKER_TYPE', 'paper')
            if broker_type == 'paper':
                self.broker = PaperTradingBroker(
                    initial_balance=float(os.getenv('INITIAL_BALANCE', '100000')),
                    commission_per_lot=float(os.getenv('COMMISSION', '3.5')),
                    session_factory=getattr(self, 'db_session_factory', None),
                    user_id=os.getenv('PAPER_USER_ID', 'paper'),
                )
                await self.broker.connect()
            else:
                # Live broker with encrypted credentials
                api_key = self.credential_manager.get_credential('oanda', 'api_key')
                account_id = self.credential_manager.get_credential('oanda', 'account_id')
                self.broker = create_broker('oanda', {
                    'api_key': api_key or os.getenv('OANDA_API_KEY'),
                    'account_id': account_id or os.getenv('OANDA_ACCOUNT_ID'),
                    'practice': os.getenv('OANDA_ENVIRONMENT', 'practice') == 'practice'
                })
                await self.broker.connect()
            logger.info(f"✓ Broker connected: {broker_type}")
            
            # 6. Price Engine
            symbols = os.getenv('TRADING_SYMBOLS', 'EURUSD,XAUUSD,GBPUSD').split(',')
            self.price_engine = RealTimePriceEngine({
                'symbols': symbols,
                'websocket_url': os.getenv('WS_URL'),
                'rest_url': os.getenv('REST_URL')
            })
            await self.price_engine.start()
            
            # Connect paper broker to price feed
            if isinstance(self.broker, PaperTradingBroker):
                self.broker.set_price_feed(self.price_engine)
            logger.info(f"✓ Price engine started: {len(symbols)} symbols")
            
            # 7. Order Book
            self.order_book = MultiSymbolOrderBook(symbols)
            logger.info("✓ Order book initialized")
            
            # 8. Risk Manager
            self.risk_manager = RiskManager(RiskConfig(
                max_position_size_pct=float(os.getenv('MAX_POSITION_PCT', '0.02')),
                max_drawdown_pct=float(os.getenv('MAX_DRAWDOWN_PCT', '0.10')),
                daily_loss_limit_pct=float(os.getenv('DAILY_LOSS_PCT', '0.05'))
            ))
            logger.info("✓ Risk manager ready")
            
            # 9. Strategy Manager
            self.strategy_manager = StrategyManager()
            logger.info("✓ Strategy manager ready")
            
            # 10. Position Tracker
            self.position_tracker = PositionTracker()
            logger.info("✓ Position tracker ready")
            
            # 11. Trade Executor
            self.trade_executor = TradeExecutor(
                broker=self.broker,
                risk_manager=self.risk_manager,
                position_tracker=self.position_tracker
            )
            logger.info("✓ Trade executor ready")
            
            # 12. Brain (Central Intelligence)
            self.brain = HOPEFXBrain(config={
                'max_decision_history': 1000,
                'regime_check_interval': 60,
                'circuit_breaker_threshold': 5
            })
            
            # Wire all components into brain
            self.brain.inject_components(
                price_engine=self.price_engine,
                risk_manager=self.risk_manager,
                broker=self.broker,
                strategy_manager=self.strategy_manager,
                notification_manager=self.notification_manager,
                position_tracker=self.position_tracker,
                trade_executor=self.trade_executor
            )
            logger.info("✓ Brain initialized with all components")
            
            # 13. Health Checker
            self.health_checker = get_health_checker(self)
            logger.info("✓ Health checker ready")
            
            # Publish system start event
            await publish_event(
                EventType.BRAIN_STARTED,
                aggregate_id="system",
                aggregate_type="system",
                payload={'version': self.version, 'environment': self.environment}
            )
            
            self._components_initialized = True
            
            logger.info("=" * 60)
            logger.info("ALL COMPONENTS INITIALIZED SUCCESSFULLY")
            logger.info("=" * 60)
            
            # Send startup notification
            await self._safe_notify(
                "info",
                f"🚀 HOPEFX v{self.version} Started",
                {
                    'environment': self.environment,
                    'symbols': symbols,
                    'broker': broker_type
                }
            )
            
        except Exception as e:
            logger.critical(f"Initialization failed: {e}", exc_info=True)
            await self.shutdown()
            raise
    
    async def run(self):
        """Run the complete trading system"""
        if not self._components_initialized:
            raise RuntimeError("Components not initialized")
        
        self.running = True
        
        # Start all background services
        services = [
            # Core trading
            asyncio.create_task(self.brain.dominate(), name="brain"),
            
            # Monitoring
            asyncio.create_task(self.health_checker.start_monitoring(30), name="health_monitor"),
            asyncio.create_task(self._metrics_collection(), name="metrics"),
            
            # Web services
            asyncio.create_task(start_api_server(trading_app=self), name="api"),
            asyncio.create_task(start_dashboard(self), name="dashboard"),
            asyncio.create_task(start_health_server(checker=self.health_checker), name="health_server"),
            
            # Event processing
            asyncio.create_task(self._event_processor(), name="events")
        ]
        
        self._tasks.extend(services)
        
        logger.info("=" * 60)
        logger.info("HOPEFX IS RUNNING")
        logger.info(f"API: http://localhost:8000")
        logger.info(f"Dashboard: http://localhost:8081")
        logger.info(f"Health: http://localhost:8080/health")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 60)
        
        # Wait for shutdown
        await self._shutdown_event.wait()
        await self.shutdown()
    
    async def _metrics_collection(self):
        """Collect metrics periodically"""
        while self.running:
            try:
                self.metrics.update_system_metrics()
                
                # Update trading metrics
                if self.broker:
                    account = await self.broker.get_account_info()
                    self.metrics.update_gauge('account_equity', account.get('equity', 0))
                    self.metrics.update_gauge('account_balance', account.get('balance', 0))
                
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metrics error: {e}")
                await asyncio.sleep(5)
    
    async def _event_processor(self):
        """Process system events"""
        while self.running:
            try:
                # Event processing logic here
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
    
    async def _safe_notify(self, level: str, message: str, data: Dict = None):
        """Safe notification with error handling"""
        if self.notification_manager:
            try:
                await asyncio.wait_for(
                    self.notification_manager.send_alert(level, message, data),
                    timeout=3.0
                )
            except Exception as e:
                logger.error(f"Notification failed: {e}")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self._shutdown_event.set()
    
    async def shutdown(self):
        """Graceful shutdown of all components"""
        if not self.running:
            return
        
        logger.info("=" * 60)
        logger.info("INITIATING GRACEFUL SHUTDOWN")
        logger.info("=" * 60)
        
        self.running = False
        self._shutdown_event.set()
        
        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Wait with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.warning("Some tasks did not terminate gracefully")
        
        # Shutdown components in reverse order
        shutdown_order = [
            ('brain', lambda: self.brain.shutdown() if self.brain else None),
            ('price_engine', lambda: self.price_engine.stop() if self.price_engine else None),
            ('broker', lambda: self.broker.disconnect() if self.broker else None),
            ('notifications', lambda: self.notification_manager.stop() if self.notification_manager else None),
            ('event_store', lambda: self.event_store.stop() if self.event_store else None),
            ('cache', lambda: self.cache.close() if self.cache else None),
            ('database', lambda: self.db_manager.close() if self.db_manager else None),
        ]
        
        for name, shutdown_fn in shutdown_order:
            try:
                result = shutdown_fn()
                if asyncio.iscoroutinefunction(shutdown_fn) or isinstance(result, asyncio.Future):
                    await asyncio.wait_for(result, timeout=5.0)
                logger.info(f"✓ {name} stopped")
            except Exception as e:
                logger.error(f"✗ Error stopping {name}: {e}")
        
        # Final notification
        await self._safe_notify(
            "info",
            "HOPEFX Stopped",
            {'uptime': 'unknown'}  # Would track actual uptime
        )
        
        logger.info("=" * 60)
        logger.info("SHUTDOWN COMPLETE")
        logger.info("=" * 60)
    
    def get_status(self) -> Dict:
        """Get complete system status"""
        return {
            'version': self.version,
            'environment': self.environment,
            'running': self.running,
            'initialized': self._components_initialized,
            'brain_state': self.brain.state.to_dict() if self.brain else None,
            'health': self.health_checker.run_all_checks() if self.health_checker else None,
            'metrics': self.metrics.get_all_metrics(),
            'components': {
                'database': self.db_manager is not None,
                'cache': self.cache is not None,
                'broker': self.broker.connected if self.broker else False,
                'price_engine': self.price_engine.active if self.price_engine else False,
                'brain': self.brain.state.system_state.value if self.brain else None
            }
        }


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="HOPEFX AI Trading System")
    parser.add_argument("--mode", choices=['paper', 'live'], default="paper")
    parser.add_argument("--env", default="development")
    parser.add_argument("--init-db", action="store_true")
    args = parser.parse_args()
    
    # Set environment
    os.environ['APP_ENV'] = args.env
    os.environ['BROKER_TYPE'] = args.mode
    
    # Create and run app
    app = HopeFXTradingApp(environment=args.env)
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, app.signal_handler)
    signal.signal(signal.SIGTERM, app.signal_handler)
    
    try:
        await app.initialize()
        
        if args.init_db:
            logger.info("Database initialization complete")
            return 0
        
        await app.run()
        return 0
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        await app.shutdown()
        return 0
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        await app.shutdown()
        return 1


if __name__ == "__main__":
    # Ensure directories exist
    Path("logs").mkdir(exist_ok=True)
    Path("config").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)
    
    # Run
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
