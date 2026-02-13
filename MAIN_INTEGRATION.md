# Main.py Integration Guide

## Overview

The `main.py` file is the **complete entry point** for the HOPEFX AI Trading Framework. It initializes and coordinates **all** framework components.

## Answer to "Do we need to add everything to code under our main?"

**YES!** The main.py now includes initialization of ALL core components:

### ✅ What's Integrated

1. **Infrastructure Components**
   - ✅ Configuration Manager
   - ✅ Database (SQLAlchemy)
   - ✅ Cache (Redis)

2. **Trading Components** (NEW)
   - ✅ Notification Manager
   - ✅ Risk Manager
   - ✅ Broker Connector (Paper Trading by default)
   - ✅ Strategy Manager

## Component Initialization Order

The framework initializes components in a specific order to ensure proper dependencies:

```
[1/7] Configuration
      ↓
[2/7] Database
      ↓
[3/7] Cache
      ↓
[4/7] Notifications
      ↓
[5/7] Risk Manager
      ↓
[6/7] Broker
      ↓
[7/7] Strategy Manager
```

## Why This Matters

### Before Integration
The old main.py only initialized:
- Config
- Database  
- Cache

This meant:
- Strategies had to be manually initialized
- No risk management on startup
- No broker connection
- No notifications
- Manual coordination required

### After Integration
The new main.py initializes:
- ✅ Everything automatically
- ✅ All components properly connected
- ✅ Ready to trade immediately
- ✅ Proper lifecycle management
- ✅ Graceful shutdown

## Usage

### Basic Usage
```bash
# Development mode (default)
python main.py

# Production mode
python main.py --env production

# Staging mode
python main.py --env staging
```

### What Happens on Startup

```
======================================================================
HOPEFX AI TRADING FRAMEWORK - INITIALIZATION
======================================================================

[1/7] Loading configuration...
✓ Configuration loaded: HOPEFX AI Trading v1.0.0
  - Environment: development
  - Debug mode: True
  - Database: sqlite
  - Trading enabled: True
  - Paper trading: True

[2/7] Initializing database...
✓ Database initialized: sqlite
  - Connection: data/hopefx_trading.db

[3/7] Initializing cache...
✓ Cache initialized: Redis at localhost:6379

[4/7] Initializing notifications...
✓ Notifications initialized
  - Active channels: 1

[5/7] Initializing risk manager...
✓ Risk manager initialized
  - Max positions: 5
  - Max daily loss: $1000
  - Max drawdown: 10.0%

[6/7] Initializing broker...
✓ Broker initialized: Paper Trading
  - Initial balance: $100,000.00

[7/7] Initializing strategies...
✓ Strategy manager initialized
  - Active strategies: 0
  - Ready to load and run trading strategies

======================================================================
INITIALIZATION COMPLETE - ALL SYSTEMS READY
======================================================================
```

## Component Details

### 1. Configuration (Step 1/7)
- Loads environment-specific config
- Sets up encryption
- Validates settings
- Manages API credentials

### 2. Database (Step 2/7)
- Creates SQLAlchemy engine
- Creates all tables
- Establishes session
- Configures connection pool

### 3. Cache (Step 3/7)
- Connects to Redis
- Implements retry logic
- Tests connection health
- Falls back gracefully if unavailable

### 4. Notifications (Step 4/7)
**NEW!** Now initialized automatically:
- Sets up notification channels
- Configures console output
- Ready for Discord, Telegram, Email, SMS
- Sends startup notification

### 5. Risk Manager (Step 5/7)
**NEW!** Now initialized automatically:
- Configures position limits
- Sets max daily loss
- Defines max drawdown
- Calculates position sizes
- Monitors portfolio risk

### 6. Broker (Step 6/7)
**NEW!** Now initialized automatically:
- Connects to trading broker
- Paper trading by default ($100k balance)
- Ready for live trading configuration
- Manages orders and positions

### 7. Strategy Manager (Step 7/7)
**NEW!** Now initialized automatically:
- Coordinates all strategies
- Manages strategy lifecycle
- Distributes signals
- Tracks performance

## Adding Strategies

### Option 1: Programmatically in main.py
```python
# In the run() method, uncomment and modify:
from strategies import MovingAverageCrossover, StrategyConfig

ma_config = StrategyConfig(
    symbol="EUR/USD",
    timeframe="1H",
    parameters={
        'fast_period': 10,
        'slow_period': 20,
    }
)
strategy = MovingAverageCrossover(config=ma_config)
self.strategy_manager.add_strategy("MA_Crossover_EURUSD", strategy)
self.strategy_manager.start_strategy("MA_Crossover_EURUSD")
```

### Option 2: Via API
```bash
# Start the API server
python app.py

# Use the admin panel
# Visit: http://localhost:5000/admin
```

### Option 3: Via CLI
```bash
# Use the command-line interface
python cli.py strategies add --name MA_EURUSD --type ma_crossover
python cli.py strategies start --name MA_EURUSD
```

## Shutdown Behavior

The framework handles graceful shutdown automatically:

```
======================================================================
SHUTTING DOWN
======================================================================
Stopping all strategies...
  ✓ All strategies stopped
  ✓ Database session closed
  ✓ Database engine disposed
  ✓ Cache connection closed
  ✓ Broker connection closed

======================================================================
SHUTDOWN COMPLETE
======================================================================
```

## Environment Variables

### Required
```bash
CONFIG_ENCRYPTION_KEY=your-32-character-minimum-key-here
```

### Optional
```bash
APP_ENV=development                # development, staging, production
REDIS_HOST=localhost               # Redis host
REDIS_PORT=6379                    # Redis port
REDIS_PASSWORD=secret              # Redis password (if needed)
REDIS_DB=0                         # Redis database number
```

## System Status Display

After initialization, the framework displays comprehensive status:

```
======================================================================
SYSTEM STATUS
======================================================================

Infrastructure:
  ✓ Config: Loaded (development)
  ✓ Database: Connected (sqlite)
  ✓ Cache: Connected

Trading Components:
  ✓ Notifications: 1 channels active
  ✓ Risk Manager: 5 max positions, 10.0% max drawdown
  ✓ Broker: PaperTradingBroker (Balance: $100,000.00)
  ✓ Strategies: 0 loaded

Configuration:
  - Trading enabled: True
  - Paper trading: True
  - API configs: 0

======================================================================
```

## Integration with Other Entry Points

### main.py
- **Purpose**: Run the full trading framework
- **Use case**: Production trading, backtesting
- **Components**: ALL (Config, DB, Cache, Strategies, Risk, Broker, Notifications)

### app.py
- **Purpose**: Run the API server
- **Use case**: Admin panel, REST API, dashboard
- **Components**: Config, DB, API routes, Admin panel

### cli.py
- **Purpose**: Command-line management
- **Use case**: Administration, configuration, debugging
- **Components**: Config, DB, Cache, selective component access

## Benefits of Complete Integration

### 1. Single Command Startup
```bash
python main.py  # Everything starts automatically
```

### 2. Proper Component Coordination
- All components can interact
- Strategies can access risk manager
- Broker can send notifications
- Cache serves all components

### 3. Lifecycle Management
- Components start in correct order
- Dependencies satisfied automatically
- Graceful shutdown of all systems

### 4. Production Ready
- Full monitoring
- Complete logging
- Error handling
- Status reporting

### 5. Developer Friendly
- No manual wiring needed
- Clear initialization flow
- Easy to extend
- Well documented

## Next Steps

1. **Configure environment variables** - Set CONFIG_ENCRYPTION_KEY
2. **Choose your broker** - Paper trading or configure live broker
3. **Add strategies** - Use API, CLI, or code
4. **Monitor performance** - Check logs and admin panel
5. **Scale up** - Deploy with Docker for production

## Conclusion

**YES**, we absolutely need all components in main.py. This creates:
- ✅ A complete, production-ready framework
- ✅ Single entry point for trading
- ✅ Proper component coordination
- ✅ Professional application structure
- ✅ Easy deployment and management

The framework is now truly **enterprise-grade** and ready for serious trading operations!
