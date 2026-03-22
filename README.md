# HOPEFX-AI-TRADING

<div align="center">

![HOPEFX Logo](https://img.shields.io/badge/HOPEFX-AI%20Trading-26a69a?style=for-the-badge&logo=bitcoin&logoColor=white)

[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Discord](https://img.shields.io/badge/Discord-Join%20Us-7289da?logo=discord&logoColor=white)](https://discord.gg/hopefx)



## Backtest Results — XAUUSD RandomForest Strategy

> **Data**: 730 daily bars, Jan 2022 – Dec 2023 (synthetic GBM + Ornstein-Uhlenbeck, realistic gold parameters)  
> **Model**: RandomForestClassifier, 200 trees, trained on first 70% of bars (walk-forward split)  
> **Sizing**: 10% equity per trade, ATR-based stop (1.5×) and take-profit (2.5×), 2 bps commission

![Equity Curve](examples/results/equity_curve.png)

| Metric | Value |
|---|---|
| Backtest period | 2024-01-08 – 2024-10-18 |
| Total return | +0.68% |
| Trades | 17 |
| Win rate | 47.1% |
| Profit factor | 1.446 |
| Max drawdown | −0.6% |
| Sharpe ratio | 2.778 |
| Calmar ratio | 1.134 |
| ML accuracy (test) | 48.3% |

**Honest caveats**: ML accuracy is ~48% (near-random) — the positive result is driven by the asymmetric 2.5:1.5 TP:SL ratio, not prediction skill. Real gold has fat tails and macro regime shifts not present in synthetic data. Treat this as infrastructure proof, not a live-trading signal.

**Reproduce in one command:**
```bash
python examples/generate_proof_artifacts.py
```

**Full walkthrough**: [`examples/end_to_end.ipynb`](examples/end_to_end.ipynb)

---

## 📊 Key Features

### 🤖 Machine Learning & AI (Research-Grade)
- **LSTM Neural Networks** for time-series price prediction
- **Random Forest** for pattern recognition and classification
- **XGBoost** for feature importance and gradient boosting
- **Ensemble Methods** for robust, multi-model signals
- **Automated model training pipeline** with hyperparameter tuning
- **Feature engineering system** for technical indicators
- **Model evaluation metrics** (accuracy, Sharpe, profit factor)


### 📱 Mobile & API (Full-Featured)
- **Progressive Web App (PWA)** - Install on any device
- **REST API** with Swagger/OpenAPI documentation
- **WebSocket** real-time streaming
- **Push notifications** (Discord, Telegram, Email, SMS)
- **Mobile-optimized API** with data compression
- **Biometric authentication** support
- **Offline capabilities** via Service Worker
- **Touch-optimized** trading interface

---

## 📚 Documentation

### Getting Started
- **[INSTALLATION.md](./INSTALLATION.md)** - Complete installation guide
- **[docs/FAQ.md](./docs/FAQ.md)** - Frequently asked questions
- **[docs/API_GUIDE.md](./docs/API_GUIDE.md)** - Developer API guide

### Trading & Strategies
- **[docs/SAMPLE_STRATEGIES.md](./docs/SAMPLE_STRATEGIES.md)** - Ready-to-use strategies
- **[docs/ASSET_DIVERSIFICATION.md](./docs/ASSET_DIVERSIFICATION.md)** - Multi-asset trading
- **[COMPETITIVE_ANALYSIS.md](./COMPETITIVE_ANALYSIS.md)** - Platform comparison

### Development
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** - Contributing guidelines
- **[SECURITY.md](./SECURITY.md)** - Security best practices
- **[DEBUGGING.md](./DEBUGGING.md)** - Troubleshooting guide

### Community & Learning
- **[docs/COMMUNITY.md](./docs/COMMUNITY.md)** - Join our community
- **[docs/VIDEO_TUTORIALS.md](./docs/VIDEO_TUTORIALS.md)** - Video learning center
- **[docs/MOBILE_GUIDE.md](./docs/MOBILE_GUIDE.md)** - Mobile development
- **[docs/MONETIZATION.md](./docs/MONETIZATION.md)** - Business strategies

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git
- Redis (optional, for caching)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
```

### Configuration

**Set required environment variables:**

```bash
# Generate secure keys
export CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export CONFIG_SALT=$(python -c "import secrets; print(secrets.token_hex(16))")
export APP_ENV=development
```

### Initialize

```bash
# Initialize the application
python cli.py init

# Check system status
python cli.py status
```

### Run

```bash
# Run main application
python main.py

# Or start API server
python app.py  # Access docs at http://localhost:5000/docs

# Or use CLI
python cli.py --help
```

See [INSTALLATION.md](./INSTALLATION.md) for detailed setup instructions.

## 🐛 Recent Fixes

### Critical Security Issues (FIXED)
- ✅ Hardcoded encryption salt replaced with environment variable
- ✅ Weak SHA256 password hashing upgraded to PBKDF2-HMAC-SHA256
- ✅ Added proper encryption key validation

### High Priority Issues (FIXED)
- ✅ Fixed uninitialized threading lock in cache
- ✅ Added thread safety to all cache statistics operations
- ✅ Implemented Redis connection retry logic
- ✅ Resolved duplicate `TickData` class names

See [DEBUGGING.md](./DEBUGGING.md) for complete details.

## 📋 Features

- **Machine Learning**: Advanced AI models for market prediction
- **Real-time Analysis**: Live market data processing and analysis
- **Multi-broker Integration**: Support for multiple trading platforms
- **Intelligent Execution**: Smart order routing and execution
- **Risk Management**: Built-in position sizing and risk controls
- **Secure Configuration**: Encrypted credential storage
- **Redis Caching**: High-performance market data caching
- **Thread-safe Operations**: Safe for concurrent usage

## 🏗️ Architecture

The framework is now fully structured with a complete package setup:

```
HOPEFX-AI-TRADING/
├── config/              # Configuration management with encryption
│   ├── __init__.py
│   └── config_manager.py
├── cache/               # Redis-based market data caching
│   ├── __init__.py
│   └── market_data_cache.py
├── database/            # SQLAlchemy ORM models
│   ├── __init__.py
│   └── models.py
├── brokers/             # Broker integrations (OANDA, MT5, IB, Binance, etc.)
│   └── __init__.py
├── strategies/          # Trading strategy implementations
│   └── __init__.py
├── ml/                  # Machine learning models (LSTM, XGBoost, etc.)
│   └── __init__.py
├── risk/                # Risk management and position sizing
│   └── __init__.py
├── api/                 # REST API endpoints
│   └── __init__.py
├── notifications/       # Alert system (Discord, Telegram, Email, SMS)
│   └── __init__.py
├── logs/                # Application logs
├── data/                # Database and backtest data
├── credentials/         # Cloud service credentials
├── main.py              # Main application entry point
├── app.py               # FastAPI server
├── cli.py               # Command-line interface
├── setup.py             # Package setup
├── pyproject.toml       # Modern Python packaging
└── requirements.txt     # Dependencies
```

## 🚀 Application Entry Point (`main.py`)

`main.py` hosts the `HopeFXTradingApp` class and is the central entry point for
starting the full framework. Its initialization sequence is:

1. **Config** – loads encrypted per-environment configuration (`_init_config`)
2. **Database** – creates SQLAlchemy engine and all ORM tables (`_init_database`)
3. **Cache** – connects to Redis with retry logic (`_init_cache`)
4. **Notifications** – sets up alert channels (`_init_notifications`)
5. **Risk Manager** – configures position limits and drawdown rules (`_init_risk_manager`)
6. **Broker** – defaults to `PaperTradingBroker`; live broker wired here (`_init_broker`)
7. **Strategies** – creates a `StrategyManager` ready to load strategies (`_init_strategies`)

The following modules are loaded **conditionally** (only when the package is
importable in the current environment):

| Module | Initialized in | Components |
|--------|---------------|------------|
| ML/AI | `_init_ml_components` | `TechnicalFeatureEngineer`; LSTM & RF models lazy-loaded |
| Backtesting | `_init_backtesting` | `BacktestEngine`, `ParameterOptimizer`, `DataHandler` |
| News | `_init_news_integration` | `MultiSourceAggregator`, `ImpactPredictor`, `EconomicCalendar`, `FinancialSentimentAnalyzer` |
| Analytics | `_init_analytics` | `PortfolioOptimizer`, `RiskAnalyzer`, `SimulationEngine` |
| Monetization | `_init_monetization` | `PricingManager`, `SubscriptionManager`, `LicenseValidator` |
| Payments | `_init_payments` | `WalletManager`, `PaymentGateway` |
| Social | `_init_social_trading` | `CopyTradingEngine`, `StrategyMarketplace`, `LeaderboardManager` |
| Mobile | `_init_mobile` | `MobileAPI` |
| Charting | `_init_charting` | `ChartEngine`, `IndicatorLibrary` |

After initialization `run()` displays a full system status, then blocks until
interrupted (`Ctrl+C`), at which point `shutdown()` gracefully tears down all
components.

## 💻 CLI Commands

The framework includes a comprehensive CLI for easy management:

```bash
# Initialize the application
python cli.py init

# Check system status
python cli.py status

# Manage configuration
python cli.py config show
python cli.py config validate

# Manage cache
python cli.py cache stats
python cli.py cache clear
python cli.py cache health

# Manage database
python cli.py db create
python cli.py db drop --force
```

## 🌐 API Server

Start the FastAPI server for REST API access:

```bash
# Start server (development mode with auto-reload)
python app.py

# Access API documentation
# Swagger UI: http://localhost:5000/docs
# ReDoc: http://localhost:5000/redoc
```

### API Endpoints

- `GET /` - API information
- `GET /health` - Health check with component status
- `GET /status` - Detailed system status

## 🔧 Package Installation

The framework can be installed as a Python package:

```bash
# Install in development mode
pip install -e .

# Install with development dependencies
pip install -e ".[dev]"

# Use console scripts
hopefx --help
hopefx-server
```

## ⚙️ Configuration

Configuration files are stored in `config/` directory and are environment-specific:
- `config.development.json` - Development settings
- `config.staging.json` - Staging settings
- `config.production.json` - Production settings

All sensitive data (API keys, passwords) are encrypted using Fernet encryption.

## 🔒 Security Best Practices

1. **Never commit credentials** to version control
2. **Use environment variables** for sensitive configuration
3. **Enable SSL/TLS** for database connections (enabled by default)
4. **Rotate credentials** regularly
5. **Use sandbox mode** for development and testing
6. **Monitor security logs** for suspicious activity

See [SECURITY.md](./SECURITY.md) for comprehensive security guidelines.

## 🧪 Testing

```bash
# Run syntax checks
python -m py_compile config/config_manager.py
python -m py_compile cache/market_data_cache.py
python -m py_compile database/models.py

# Test configuration encryption
python config/config_manager.py

# Test cache connection (requires Redis)
python cache/market_data_cache.py
```

## 📝 License

MIT License - See [LICENSE](./LICENSE) for details. Use freely for personal or commercial trading.

---

## 🌍 Community

Join our growing community of traders and developers:

<div align="center">

[![Discord](https://img.shields.io/badge/Discord-Join%20Community-7289da?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/hopefx)
[![Telegram](https://img.shields.io/badge/Telegram-Join%20Channel-26a5e4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/hopefx)
[![Twitter](https://img.shields.io/badge/Twitter-Follow%20Us-1da1f2?style=for-the-badge&logo=twitter&logoColor=white)](https://twitter.com/HOPEFX_Trading)
[![YouTube](https://img.shields.io/badge/YouTube-Subscribe-ff0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com/@hopefx)

</div>

### Why Join?
- 💬 Real-time strategy discussions
- 🎓 Learn from experienced traders
- 🐛 Get help with technical issues
- 🚀 Early access to new features
- 🏆 Monthly trading challenges

---

## 📺 Learning Resources

### Video Tutorials
See [docs/VIDEO_TUTORIALS.md](./docs/VIDEO_TUTORIALS.md) for the complete video series:
- 🎬 **Episode 1:** Introduction to HOPEFX
- 🎬 **Episode 2:** Installation & Setup
- 🎬 **Episode 3:** Your First Backtest
- 🎬 **Episode 7:** Building Trading Strategies
- 🎬 **Episode 11:** Machine Learning Trading

### Sample Strategies
Get started quickly with [ready-to-use strategies](./docs/SAMPLE_STRATEGIES.md):
- MA Crossover (Beginner)
- Bollinger Bands Mean Reversion (Intermediate)
- SMC/ICT Smart Money (Advanced)
- LSTM Price Prediction (Expert)

---

## 🤝 Contributing

We welcome contributions from the community!

1. 🍴 Fork the repository
2. 🌿 Create a feature branch (`git checkout -b feature/amazing-feature`)
3. 💻 Make your changes
4. ✅ Run tests and linting
5. 📤 Submit a pull request

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed guidelines.

---

## ⭐ Show Your Support

If HOPEFX helps your trading, please consider:
- ⭐ **Star this repository** to help others discover it
- 🐦 **Share on social media** with #HOPEFX
- 💬 **Join our community** on Discord
- 🤝 **Contribute** code, docs, or ideas

---

## 📧 Support & Contact

| Type | Contact |
|------|---------|
| **General Questions** | [Discord](https://discord.gg/hopefx) or [GitHub Discussions](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/discussions) |
| **Bug Reports** | [GitHub Issues](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues) |
| **Security Issues** | See [SECURITY.md](./SECURITY.md) |
| **Partnerships** | partners@hopefx.com |

---

<div align="center">

**Built with ❤️ by the HOPEFX Community**

[🚀 Get Started](./INSTALLATION.md) • [📊 Features](#-key-features) • [💬 Discord](https://discord.gg/hopefx) • [⭐ Star Us](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING)

</div>
