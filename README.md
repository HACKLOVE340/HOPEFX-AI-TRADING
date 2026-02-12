# HOPEFX-AI-TRADING

ADVANCED AI POWER XAUUSD trading framework with machine learning, real time analysis, multi broker integration, and intelligent trade execution.

## 📚 Documentation

- **[DEBUGGING.md](./DEBUGGING.md)** - Comprehensive list of issues fixed and debugging guide
- **[SECURITY.md](./SECURITY.md)** - Security best practices and configuration guide
- **[.env.example](./.env.example)** - Environment variable template

## 🔐 Security Requirements

Before running the application, set these required environment variables:

```bash
export CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export CONFIG_SALT=$(python -c "import secrets; print(secrets.token_hex(16))")
export APP_ENV=development
```

See [SECURITY.md](./SECURITY.md) for detailed security configuration.

## 🚀 Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Set security variables:**
   ```bash
   export CONFIG_ENCRYPTION_KEY="your-secure-key-here"
   export CONFIG_SALT="your-random-salt-here"
   ```

4. **Initialize configuration:**
   ```bash
   python -c "from config.config_manager import initialize_config; initialize_config()"
   ```

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

```
HOPEFX-AI-TRADING/
├── config/              # Configuration management
│   └── config_manager.py
├── cache/               # Redis-based caching
│   └── market_data_cache.py
├── database/            # SQLAlchemy models
│   └── models.py
├── SECURITY.md          # Security guide
├── DEBUGGING.md         # Debugging guide
└── requirements.txt     # Dependencies
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

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run security and syntax checks
5. Submit a pull request

## 📧 Support

For security issues, please see [SECURITY.md](./SECURITY.md) for reporting guidelines.
