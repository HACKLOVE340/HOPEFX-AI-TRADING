# HOPEFX-AI-TRADING

ADVANCED AI POWER XAUUSD trading framework with machine learning, real time analysis, multi broker integration, and intelligent trade execution.

## 📚 Documentation

- **[INSTALLATION.md](./INSTALLATION.md)** - Complete installation guide
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** - Contributing guidelines
- **[SECURITY.md](./SECURITY.md)** - Security configuration and best practices
- **[DEBUGGING.md](./DEBUGGING.md)** - Debugging guide with solutions
- **[COMPETITIVE_ANALYSIS.md](./COMPETITIVE_ANALYSIS.md)** - How we compare to MetaTrader, TradingView, QuantConnect & more
- **[.env.example](./.env.example)** - Environment variable template

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

See [LICENSE](./LICENSE) for details.

## 🌍 Community

Join our growing community of traders and developers:

- 💬 **Discord**: [Join HOPEFX Community](https://discord.gg/hopefx) *(Coming Soon)*
- 📢 **Telegram**: [HOPEFX Announcements](https://t.me/hopefx) *(Coming Soon)*
- 🐦 **Twitter/X**: [@HOPEFX_Trading](https://twitter.com/HOPEFX_Trading) *(Coming Soon)*
- 📺 **YouTube**: [HOPEFX Tutorials](https://youtube.com/@hopefx) *(Coming Soon)*

## 📚 Learning Resources

### Documentation
- [Installation Guide](./INSTALLATION.md) - Getting started
- [Competitive Analysis](./COMPETITIVE_ANALYSIS.md) - How we compare to MetaTrader, TradingView, QuantConnect
- [Security Best Practices](./SECURITY.md) - Secure configuration

### Video Tutorials *(Coming Soon)*
- 🎬 Getting Started with HOPEFX
- 🎬 Building Your First Trading Strategy
- 🎬 ML Model Training Tutorial
- 🎬 Prop Firm Integration Guide
- 🎬 Backtesting Masterclass

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run security and syntax checks
5. Submit a pull request

## 📧 Support

For security issues, please see [SECURITY.md](./SECURITY.md) for reporting guidelines.
