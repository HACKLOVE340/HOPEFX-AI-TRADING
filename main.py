#!/usr/bin/env python3
"""
HOPEFX AI Trading Framework - Main Entry Point

This is the main entry point for the HOPEFX AI Trading framework.
It initializes the application, loads configuration, and starts the trading system.

Integrated Components:
- Core: Config, Database, Cache, Strategies, Risk, Brokers, Notifications
- AI/ML: LSTM Price Predictor, Random Forest Classifier, Feature Engineering
- Backtesting: Engine, Optimizer, Walk-Forward Analysis, Reports
- News: Multi-source Aggregator, Impact Predictor, Economic Calendar
- Analytics: Portfolio Optimizer, Risk Analyzer, Simulation Engine
- Monetization: Subscription, Pricing, Commission, License Validation
- Payments: Wallet, Payment Gateway, Transaction Manager, Compliance
- Social: Copy Trading, Strategy Marketplace, Leaderboards
- Mobile: Mobile API, Push Notifications
- Charting: Chart Engine, Indicator Library

Version: 1.0.0
"""

import sys
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import initialize_config, get_config_manager
from cache import MarketDataCache
from database.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import core trading components
from strategies import StrategyManager
from risk import RiskManager, RiskConfig
from brokers import PaperTradingBroker
from notifications import NotificationManager, NotificationLevel

# Import component status utilities
try:
    from utils import get_all_component_statuses, get_framework_version, ComponentStatus
    UTILS_AVAILABLE = True
except ImportError:
    UTILS_AVAILABLE = False

# Import ML/AI components (optional - may not be available in all environments)
try:
    from ml import LSTMPricePredictor, RandomForestTradingClassifier, TechnicalFeatureEngineer
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

# Import backtesting components
try:
    from backtesting import (
        BacktestEngine, PerformanceMetrics, ParameterOptimizer,
        WalkForwardAnalysis, ReportGenerator, DataHandler
    )
    BACKTESTING_AVAILABLE = True
except ImportError:
    BACKTESTING_AVAILABLE = False

# Import news integration
try:
    from news import (
        MultiSourceAggregator, ImpactPredictor, EconomicCalendar,
        SentimentAnalyzer, FinancialSentimentAnalyzer
    )
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False

# Import analytics
try:
    from analytics import (
        portfolio_optimizer, risk_analyzer, simulation_engine,
        PortfolioOptimizer, RiskAnalyzer, SimulationEngine
    )
    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False

# Import monetization
try:
    from monetization import (
        PricingManager, SubscriptionManager, CommissionTracker,
        AccessCodeGenerator, LicenseValidator
    )
    MONETIZATION_AVAILABLE = True
except ImportError:
    MONETIZATION_AVAILABLE = False

# Import payments
try:
    from payments import (
        WalletManager, PaymentGateway, TransactionManager,
        SecurityManager, ComplianceManager
    )
    PAYMENTS_AVAILABLE = True
except ImportError:
    PAYMENTS_AVAILABLE = False

# Import social trading
try:
    from social import (
        copy_trading_engine, marketplace, leaderboard_manager,
        CopyTradingEngine, StrategyMarketplace, LeaderboardManager
    )
    SOCIAL_AVAILABLE = True
except ImportError:
    SOCIAL_AVAILABLE = False

# Import mobile
try:
    from mobile import (
        mobile_api, push_notification_manager,
        MobileAPI, PushNotificationManager
    )
    MOBILE_AVAILABLE = True
except ImportError:
    MOBILE_AVAILABLE = False

# Import charting
try:
    from charting import (
        chart_engine, indicator_library,
        ChartEngine, IndicatorLibrary
    )
    CHARTING_AVAILABLE = True
except ImportError:
    CHARTING_AVAILABLE = False

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

        # Core trading components
        self.strategy_manager = None
        self.risk_manager = None
        self.broker = None
        self.notification_manager = None

        # ML/AI components
        self.ml_models: Dict[str, Any] = {}
        self.feature_engineer = None

        # Backtesting components
        self.backtest_engine = None
        self.optimizer = None
        self.data_handler = None

        # News & sentiment components
        self.news_aggregator = None
        self.impact_predictor = None
        self.economic_calendar = None
        self.sentiment_analyzer = None

        # Analytics components
        self.portfolio_optimizer = None
        self.analytics_risk_analyzer = None
        self.simulation_engine = None

        # Monetization & payments
        self.subscription_manager = None
        self.pricing_manager = None
        self.wallet_manager = None
        self.payment_gateway = None
        self.license_validator = None

        # Social trading
        self.copy_trading_engine = None
        self.strategy_marketplace = None
        self.leaderboard_manager = None

        # Mobile & charting
        self.mobile_api = None
        self.chart_engine = None
        self.indicator_library = None

        # Track available modules
        self.available_modules: Dict[str, bool] = {
            'ml': ML_AVAILABLE,
            'backtesting': BACKTESTING_AVAILABLE,
            'news': NEWS_AVAILABLE,
            'analytics': ANALYTICS_AVAILABLE,
            'monetization': MONETIZATION_AVAILABLE,
            'payments': PAYMENTS_AVAILABLE,
            'social': SOCIAL_AVAILABLE,
            'mobile': MOBILE_AVAILABLE,
            'charting': CHARTING_AVAILABLE,
        }

        logger.info("Initializing HOPEFX AI Trading Framework v1.0.0")
        logger.info(f"Environment: {self.environment}")

    def initialize(self):
        """Initialize all components"""
        logger.info("=" * 70)
        logger.info("HOPEFX AI TRADING FRAMEWORK - INITIALIZATION")
        logger.info("=" * 70)

        # Count available modules for progress display
        total_steps = 7 + sum(self.available_modules.values())

        # Infrastructure Components
        self._init_config()        # Step 1: Load configuration
        self._init_database()      # Step 2: Initialize database
        self._init_cache()         # Step 3: Initialize cache

        # Core Trading Components
        self._init_notifications() # Step 4: Initialize notifications
        self._init_risk_manager()  # Step 5: Initialize risk manager
        self._init_broker()        # Step 6: Initialize broker
        self._init_strategies()    # Step 7: Initialize strategy manager

        # Extended Components (conditionally loaded)
        current_step = 8

        if self.available_modules['ml']:
            self._init_ml_components(current_step, total_steps)
            current_step += 1

        if self.available_modules['backtesting']:
            self._init_backtesting(current_step, total_steps)
            current_step += 1

        if self.available_modules['news']:
            self._init_news_integration(current_step, total_steps)
            current_step += 1

        if self.available_modules['analytics']:
            self._init_analytics(current_step, total_steps)
            current_step += 1

        if self.available_modules['monetization']:
            self._init_monetization(current_step, total_steps)
            current_step += 1

        if self.available_modules['payments']:
            self._init_payments(current_step, total_steps)
            current_step += 1

        if self.available_modules['social']:
            self._init_social_trading(current_step, total_steps)
            current_step += 1

        if self.available_modules['mobile']:
            self._init_mobile(current_step, total_steps)
            current_step += 1

        if self.available_modules['charting']:
            self._init_charting(current_step, total_steps)
            current_step += 1

        logger.info("=" * 70)
        logger.info("INITIALIZATION COMPLETE - ALL SYSTEMS READY")
        logger.info("=" * 70)

    def _init_config(self):
        """Initialize configuration"""
        logger.info("[1/7] Loading configuration...")

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
        logger.info("[2/7] Initializing database...")

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
            session_factory = sessionmaker(bind=self.db_engine)
            self.db_session = session_factory()

            logger.info(f"✓ Database initialized: {self.config.database.db_type}")
            logger.info(f"  - Connection: {connection_string.split('@')[-1] if '@' in connection_string else connection_string}")

        except Exception as e:
            logger.error(f"✗ Database initialization failed: {e}")
            raise

    def _init_cache(self):
        """Initialize Redis cache"""
        logger.info("[3/7] Initializing cache...")

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

    def _init_notifications(self):
        """Initialize notification system"""
        logger.info("[4/7] Initializing notifications...")

        try:
            self.notification_manager = NotificationManager()

            # Add console channel (always enabled)
            from notifications.manager import ConsoleNotificationChannel
            self.notification_manager.add_channel(ConsoleNotificationChannel())

            # Send startup notification
            self.notification_manager.send_notification(
                title="🚀 HOPEFX Trading Started",
                message=f"Trading framework initialized in {self.environment} mode",
                level=NotificationLevel.INFO
            )

            logger.info("✓ Notifications initialized")
            logger.info(f"  - Active channels: {len(self.notification_manager.channels)}")

        except Exception as e:
            logger.warning(f"⚠ Notifications initialization failed: {e}")
            logger.warning("  Continuing without notifications")
            self.notification_manager = None

    def _init_risk_manager(self):
        """Initialize risk management system"""
        logger.info("[5/7] Initializing risk manager...")

        try:
            # Create risk configuration
            risk_config = RiskConfig(
                max_position_size=self.config.trading.max_position_size if hasattr(self.config.trading, 'max_position_size') else 10000,
                max_open_positions=self.config.trading.max_positions if hasattr(self.config.trading, 'max_positions') else 5,
                max_daily_loss=self.config.trading.max_daily_loss if hasattr(self.config.trading, 'max_daily_loss') else 1000,
                max_drawdown=self.config.trading.max_drawdown if hasattr(self.config.trading, 'max_drawdown') else 0.10,
                default_stop_loss_pct=0.02,  # 2% default stop loss
                default_take_profit_pct=0.04,  # 4% default take profit
            )

            self.risk_manager = RiskManager(config=risk_config)

            logger.info("✓ Risk manager initialized")
            logger.info(f"  - Max positions: {risk_config.max_open_positions}")
            logger.info(f"  - Max daily loss: ${risk_config.max_daily_loss}")
            logger.info(f"  - Max drawdown: {risk_config.max_drawdown * 100}%")

        except Exception as e:
            logger.error(f"✗ Risk manager initialization failed: {e}")
            raise

    def _init_broker(self):
        """Initialize broker connection"""
        logger.info("[6/7] Initializing broker...")

        try:
            # Determine if using paper trading
            paper_trading = self.config.trading.paper_trading_mode if hasattr(self.config.trading, 'paper_trading_mode') else True

            if paper_trading:
                # Use paper trading broker
                broker_config = {
                    'initial_balance': 100000.0,  # $100k default
                    'leverage': 1.0
                }
                self.broker = PaperTradingBroker(config=broker_config)
                self.broker.connect()
                logger.info("✓ Broker initialized: Paper Trading")
                logger.info(f"  - Initial balance: ${self.broker.balance:,.2f}")
            else:
                # In production, you would initialize a real broker here
                logger.warning("⚠ Live trading mode selected but not implemented")
                logger.warning("  Falling back to paper trading")
                broker_config = {'initial_balance': 100000.0, 'leverage': 1.0}
                self.broker = PaperTradingBroker(config=broker_config)
                self.broker.connect()

        except Exception as e:
            logger.error(f"✗ Broker initialization failed: {e}")
            raise

    def _init_strategies(self):
        """Initialize strategy manager"""
        logger.info("[7/7] Initializing strategies...")

        try:
            self.strategy_manager = StrategyManager()

            logger.info("✓ Strategy manager initialized")
            logger.info(f"  - Active strategies: {len(self.strategy_manager.strategies)}")
            logger.info("  - Ready to load and run trading strategies")

        except Exception as e:
            logger.error(f"✗ Strategy manager initialization failed: {e}")
            raise

    # =========================================================================
    # EXTENDED COMPONENT INITIALIZATION
    # =========================================================================

    def _init_ml_components(self, step: int, total: int):
        """Initialize ML/AI components"""
        logger.info(f"[{step}/{total}] Initializing ML/AI components...")

        try:
            # Initialize feature engineer
            self.feature_engineer = TechnicalFeatureEngineer()

            # Initialize ML models (lazy loading - models trained on demand)
            self.ml_models = {
                'lstm_predictor': None,  # LSTMPricePredictor - initialized when needed
                'rf_classifier': None,   # RandomForestTradingClassifier - initialized when needed
            }

            logger.info("✓ ML/AI components initialized")
            logger.info("  - Feature Engineer: Ready")
            logger.info("  - LSTM Predictor: Available (lazy load)")
            logger.info("  - RF Classifier: Available (lazy load)")

        except Exception as e:
            logger.warning(f"⚠ ML components initialization failed: {e}")
            self.feature_engineer = None
            self.ml_models = {}

    def _init_backtesting(self, step: int, total: int):
        """Initialize backtesting engine"""
        logger.info(f"[{step}/{total}] Initializing backtesting engine...")

        try:
            # Initialize data handler
            self.data_handler = DataHandler()

            # Initialize backtest engine
            self.backtest_engine = BacktestEngine()

            # Initialize optimizer
            self.optimizer = ParameterOptimizer()

            logger.info("✓ Backtesting engine initialized")
            logger.info("  - Data Handler: Ready")
            logger.info("  - Backtest Engine: Ready")
            logger.info("  - Parameter Optimizer: Ready")
            logger.info("  - Walk-Forward Analysis: Available")

        except Exception as e:
            logger.warning(f"⚠ Backtesting initialization failed: {e}")
            self.backtest_engine = None
            self.optimizer = None
            self.data_handler = None

    def _init_news_integration(self, step: int, total: int):
        """Initialize news and sentiment analysis"""
        logger.info(f"[{step}/{total}] Initializing news integration...")

        try:
            # Initialize news aggregator
            self.news_aggregator = MultiSourceAggregator()

            # Initialize impact predictor
            self.impact_predictor = ImpactPredictor()

            # Initialize economic calendar
            self.economic_calendar = EconomicCalendar()

            # Initialize sentiment analyzer
            self.sentiment_analyzer = FinancialSentimentAnalyzer()

            logger.info("✓ News integration initialized")
            logger.info("  - News Aggregator: Ready")
            logger.info("  - Impact Predictor: Ready")
            logger.info("  - Economic Calendar: Ready")
            logger.info("  - Sentiment Analyzer: Ready")

        except Exception as e:
            logger.warning(f"⚠ News integration initialization failed: {e}")
            self.news_aggregator = None
            self.impact_predictor = None
            self.economic_calendar = None
            self.sentiment_analyzer = None

    def _init_analytics(self, step: int, total: int):
        """Initialize analytics components"""
        logger.info(f"[{step}/{total}] Initializing analytics...")

        try:
            # Use pre-instantiated instances or create new ones
            self.portfolio_optimizer = portfolio_optimizer if portfolio_optimizer else PortfolioOptimizer()
            self.analytics_risk_analyzer = risk_analyzer if risk_analyzer else RiskAnalyzer()
            self.simulation_engine = simulation_engine if simulation_engine else SimulationEngine()

            logger.info("✓ Analytics initialized")
            logger.info("  - Portfolio Optimizer: Ready")
            logger.info("  - Risk Analyzer: Ready")
            logger.info("  - Simulation Engine: Ready")

        except Exception as e:
            logger.warning(f"⚠ Analytics initialization failed: {e}")
            self.portfolio_optimizer = None
            self.analytics_risk_analyzer = None
            self.simulation_engine = None

    def _init_monetization(self, step: int, total: int):
        """Initialize monetization and subscription management"""
        logger.info(f"[{step}/{total}] Initializing monetization...")

        try:
            # Initialize pricing and subscription managers
            self.pricing_manager = PricingManager()
            self.subscription_manager = SubscriptionManager()
            self.license_validator = LicenseValidator()

            logger.info("✓ Monetization initialized")
            logger.info("  - Pricing Manager: Ready")
            logger.info("  - Subscription Manager: Ready")
            logger.info("  - License Validator: Ready")

        except Exception as e:
            logger.warning(f"⚠ Monetization initialization failed: {e}")
            self.pricing_manager = None
            self.subscription_manager = None
            self.license_validator = None

    def _init_payments(self, step: int, total: int):
        """Initialize payment processing"""
        logger.info(f"[{step}/{total}] Initializing payments...")

        try:
            # Initialize payment components
            self.wallet_manager = WalletManager()
            self.payment_gateway = PaymentGateway()

            logger.info("✓ Payments initialized")
            logger.info("  - Wallet Manager: Ready")
            logger.info("  - Payment Gateway: Ready")
            logger.info("  - Compliance Manager: Available")

        except Exception as e:
            logger.warning(f"⚠ Payments initialization failed: {e}")
            self.wallet_manager = None
            self.payment_gateway = None

    def _init_social_trading(self, step: int, total: int):
        """Initialize social trading features"""
        logger.info(f"[{step}/{total}] Initializing social trading...")

        try:
            # Use pre-instantiated instances or create new ones
            self.copy_trading_engine = copy_trading_engine if copy_trading_engine else CopyTradingEngine()
            self.strategy_marketplace = marketplace if marketplace else StrategyMarketplace()
            self.leaderboard_manager = leaderboard_manager if leaderboard_manager else LeaderboardManager()

            logger.info("✓ Social trading initialized")
            logger.info("  - Copy Trading: Ready")
            logger.info("  - Strategy Marketplace: Ready")
            logger.info("  - Leaderboards: Ready")

        except Exception as e:
            logger.warning(f"⚠ Social trading initialization failed: {e}")
            self.copy_trading_engine = None
            self.strategy_marketplace = None
            self.leaderboard_manager = None

    def _init_mobile(self, step: int, total: int):
        """Initialize mobile API and push notifications"""
        logger.info(f"[{step}/{total}] Initializing mobile services...")

        try:
            # Use pre-instantiated instances or create new ones
            self.mobile_api = mobile_api if mobile_api else MobileAPI()

            logger.info("✓ Mobile services initialized")
            logger.info("  - Mobile API: Ready")
            logger.info("  - Push Notifications: Available")

        except Exception as e:
            logger.warning(f"⚠ Mobile services initialization failed: {e}")
            self.mobile_api = None

    def _init_charting(self, step: int, total: int):
        """Initialize charting and technical analysis"""
        logger.info(f"[{step}/{total}] Initializing charting...")

        try:
            # Use pre-instantiated instances or create new ones
            self.chart_engine = chart_engine if chart_engine else ChartEngine()
            self.indicator_library = indicator_library if indicator_library else IndicatorLibrary()

            logger.info("✓ Charting initialized")
            logger.info("  - Chart Engine: Ready")
            logger.info("  - Indicator Library: Ready")

        except Exception as e:
            logger.warning(f"⚠ Charting initialization failed: {e}")
            self.chart_engine = None
            self.indicator_library = None

    # =========================================================================
    # APPLICATION RUNTIME
    # =========================================================================

    def run(self):
        """Run the main application"""
        logger.info("\n" + "=" * 70)
        logger.info("STARTING TRADING APPLICATION")
        logger.info("=" * 70)

        try:
            # Display comprehensive status
            self._display_status()

            # Example: Load a strategy (commented out - for demonstration)
            # from strategies import MovingAverageCrossover, StrategyConfig
            #
            # ma_config = StrategyConfig(
            #     symbol="EUR/USD",
            #     timeframe="1H",
            #     parameters={
            #         'fast_period': 10,
            #         'slow_period': 20,
            #     }
            # )
            # strategy = MovingAverageCrossover(config=ma_config)
            # self.strategy_manager.add_strategy("MA_Crossover_EURUSD", strategy)
            # self.strategy_manager.start_strategy("MA_Crossover_EURUSD")

            logger.info("\n✓ Application ready!")
            logger.info("\nQuick Start Guide:")
            logger.info("  1. To add a strategy:")
            logger.info("     - Use strategy_manager.add_strategy(name, strategy)")
            logger.info("     - Then strategy_manager.start_strategy(name)")
            logger.info("\n  2. To start the API server:")
            logger.info("     - Run: python app.py")
            logger.info("     - Visit: http://localhost:5000/admin")
            logger.info("\n  3. To use the CLI:")
            logger.info("     - Run: python cli.py --help")
            logger.info("\n  4. To run in production:")
            logger.info("     - Run: docker-compose up -d")

            logger.info("\n" + "=" * 70)
            logger.info("Framework is running. Press Ctrl+C to stop.")
            logger.info("=" * 70)

            # Keep application running
            import time
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("\n\nShutdown requested...")
            self.shutdown()
        except Exception as e:
            logger.error(f"Application error: {e}", exc_info=True)
            self.shutdown()
            raise

    def _display_status(self):
        """Display application status"""
        logger.info("\n" + "=" * 70)
        logger.info("SYSTEM STATUS")
        logger.info("=" * 70)

        # Infrastructure
        logger.info("\n📦 INFRASTRUCTURE:")
        logger.info(f"  ✓ Config: Loaded ({self.config.environment})")
        logger.info(f"  ✓ Database: Connected ({self.config.database.db_type})")
        logger.info(f"  {'✓' if self.cache else '⚠'} Cache: {'Connected' if self.cache else 'Not available'}")

        # Core Trading Components
        logger.info("\n💹 CORE TRADING:")
        logger.info(f"  ✓ Notifications: {len(self.notification_manager.channels) if self.notification_manager else 0} channels active")
        logger.info(f"  ✓ Risk Manager: {self.risk_manager.config.max_open_positions} max positions, {self.risk_manager.config.max_drawdown*100}% max drawdown")
        logger.info(f"  ✓ Broker: {type(self.broker).__name__} (Balance: ${self.broker.balance:,.2f})")
        logger.info(f"  ✓ Strategies: {len(self.strategy_manager.strategies)} loaded")

        # Extended Components
        logger.info("\n🔌 EXTENDED MODULES:")

        # ML/AI
        if self.available_modules['ml']:
            ml_status = "✓" if self.feature_engineer else "⚠"
            logger.info(f"  {ml_status} ML/AI: Feature Engineering + Models")

        # Backtesting
        if self.available_modules['backtesting']:
            bt_status = "✓" if self.backtest_engine else "⚠"
            logger.info(f"  {bt_status} Backtesting: Engine + Optimizer")

        # News
        if self.available_modules['news']:
            news_status = "✓" if self.news_aggregator else "⚠"
            logger.info(f"  {news_status} News: Aggregator + Sentiment + Calendar")

        # Analytics
        if self.available_modules['analytics']:
            analytics_status = "✓" if self.portfolio_optimizer else "⚠"
            logger.info(f"  {analytics_status} Analytics: Portfolio + Risk + Simulation")

        # Monetization
        if self.available_modules['monetization']:
            monetization_status = "✓" if self.subscription_manager else "⚠"
            logger.info(f"  {monetization_status} Monetization: Subscriptions + Pricing")

        # Payments
        if self.available_modules['payments']:
            payments_status = "✓" if self.wallet_manager else "⚠"
            logger.info(f"  {payments_status} Payments: Wallet + Gateway")

        # Social
        if self.available_modules['social']:
            social_status = "✓" if self.copy_trading_engine else "⚠"
            logger.info(f"  {social_status} Social: Copy Trading + Marketplace")

        # Mobile
        if self.available_modules['mobile']:
            mobile_status = "✓" if self.mobile_api else "⚠"
            logger.info(f"  {mobile_status} Mobile: API + Push Notifications")

        # Charting
        if self.available_modules['charting']:
            charting_status = "✓" if self.chart_engine else "⚠"
            logger.info(f"  {charting_status} Charting: Engine + Indicators")

        # Module Summary
        available_count = sum(1 for v in self.available_modules.values() if v)
        total_modules = len(self.available_modules)
        logger.info(f"\n📊 MODULES: {available_count}/{total_modules} available")

        # Component Versions
        if UTILS_AVAILABLE:
            self._display_component_versions()

        # Configuration
        logger.info("\n⚙️ CONFIGURATION:")
        logger.info(f"  - Trading enabled: {self.config.trading.trading_enabled}")
        logger.info(f"  - Paper trading: {self.config.trading.paper_trading_mode}")
        logger.info(f"  - API configs: {len(self.config.api_configs)}")

        logger.info("=" * 70)

    def _display_component_versions(self):
        """Display component versions from the utils module"""
        logger.info("\n📋 COMPONENT VERSIONS:")
        logger.info(f"  Framework: v{get_framework_version()}")
        
        try:
            statuses = get_all_component_statuses()
            core_components = ['config', 'cache', 'database', 'brokers', 'strategies', 'risk', 'notifications']
            
            for name in core_components:
                if name in statuses:
                    status = statuses[name]
                    icon = "✓" if status.available else "✗"
                    logger.info(f"  {icon} {name}: v{status.version}")
                    
        except Exception as e:
            logger.debug(f"Could not display component versions: {e}")

    def shutdown(self):
        """Gracefully shutdown the application"""
        logger.info("\n" + "=" * 70)
        logger.info("SHUTTING DOWN")
        logger.info("=" * 70)

        # Stop all strategies
        if self.strategy_manager:
            logger.info("Stopping all strategies...")
            for strategy_name in self.strategy_manager.strategies.keys():
                try:
                    self.strategy_manager.stop_strategy(strategy_name)
                except Exception as e:
                    logger.error(f"  Error stopping strategy {strategy_name}: {e}")
            logger.info("  ✓ All strategies stopped")

        # Send shutdown notification
        if self.notification_manager:
            try:
                self.notification_manager.send_notification(
                    title="🛑 HOPEFX Trading Stopped",
                    message=f"Trading framework shutting down from {self.environment} mode",
                    level=NotificationLevel.INFO
                )
            except Exception as e:
                logger.error(f"  Error sending shutdown notification: {e}")

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

        # Close broker connection
        if self.broker:
            # Paper trading broker doesn't need explicit close, but real brokers would
            logger.info("  ✓ Broker connection closed")

        logger.info("\n" + "=" * 70)
        logger.info("SHUTDOWN COMPLETE")
        logger.info("=" * 70)


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
