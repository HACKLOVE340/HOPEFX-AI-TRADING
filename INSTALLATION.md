# INSTALLATION GUIDE

Complete installation guide for the HOPEFX AI Trading Framework.

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git
- Redis (optional, for caching)
- PostgreSQL (optional, for production database)

## Quick Installation

### 1. Clone the Repository

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
```

### 2. Create Virtual Environment (Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate on Linux/macOS
source venv/bin/activate

# Activate on Windows
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt

# Or install package in development mode
pip install -e .
```

### 4. Configure Environment Variables

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env  # or use your preferred editor
```

**Required Environment Variables:**

```bash
# Security (REQUIRED)
export CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export CONFIG_SALT=$(python -c "import secrets; print(secrets.token_hex(16))")

# Application
export APP_ENV=development
```

### 5. Initialize the Application

```bash
# Initialize configuration and database
python cli.py init

# Check system status
python cli.py status
```

### 6. Run the Application

```bash
# Run main application
python main.py

# Or start the API server
python app.py
```

## Detailed Installation

### Installing Individual Components

#### 1. Core Dependencies

```bash
# Install core trading and financial libraries
pip install yfinance pandas numpy ta-lib pandas-ta

# Install machine learning libraries
pip install scikit-learn tensorflow keras torch xgboost lightgbm catboost

# Install web framework
pip install fastapi uvicorn flask
```

#### 2. Broker Integrations

```bash
# Install broker APIs
pip install alpaca-trade-api python-binance ccxt

# For MetaTrader 5
pip install MetaTrader5

# For Interactive Brokers
pip install ibapi
```

#### 3. Database

```bash
# Install database drivers
pip install sqlalchemy pymongo redis

# For PostgreSQL
pip install psycopg2-binary

# For MySQL
pip install pymysql
```

#### 4. Additional Services

```bash
# Notifications
pip install python-telegram-bot discord.py twilio

# Utilities
pip install python-dotenv loguru pyyaml
```

### Optional: Install Redis

#### On Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

#### On macOS:
```bash
brew install redis
brew services start redis
```

#### On Windows:
Download from https://github.com/microsoftarchive/redis/releases

### Optional: Install PostgreSQL

#### On Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### On macOS:
```bash
brew install postgresql
brew services start postgresql
```

## Configuration

### 1. Environment Variables

Edit `.env` file with your configuration:

```bash
# Database Configuration
DB_TYPE=sqlite  # or postgresql
SQLITE_DB_PATH=./data/hopefx_trading.db

# For PostgreSQL
POSTGRES_USER=hopefx_admin
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=hopefx_trading

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=  # leave empty if no password

# Trading Parameters
RISK_PER_TRADE=2
DAILY_LOSS_LIMIT=500
MAX_DRAWDOWN_PERCENT=15
```

### 2. Create Configuration Files

The application will automatically create configuration files on first run:

```bash
python cli.py init
```

This creates:
- `config/config.development.json`
- `logs/` directory
- `data/` directory
- `credentials/` directory

### 3. Configure Brokers

Add your broker credentials to `.env`:

```bash
# Example: OANDA
OANDA_API_KEY=your_api_key
OANDA_ACCOUNT_ID=your_account_id
OANDA_ENVIRONMENT=practice

# Example: Binance
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
```

## Verification

### 1. Check Installation

```bash
# Check Python version
python --version  # Should be 3.8+

# Check pip version
pip --version

# List installed packages
pip list | grep -E "fastapi|sqlalchemy|redis"
```

### 2. Test Components

```bash
# Test configuration
python -c "from config import initialize_config; print('Config OK')"

# Test CLI
python cli.py --version

# Test main application
python main.py --help
```

### 3. Run Health Check

```bash
# Check system status
python cli.py status

# Expected output:
# ✓ Configuration: HOPEFX AI Trading v1.0.0
# ✓ Database: Connected (sqlite)
# ✓ Cache: Connected (or ⚠ Not available if Redis not running)
```

## Running the Application

### Development Mode

```bash
# Run main application
python main.py --env development

# Run API server with auto-reload
python app.py
```

Access API documentation at:
- Swagger UI: http://localhost:5000/docs
- ReDoc: http://localhost:5000/redoc

### Production Mode

```bash
# Set environment variables
export APP_ENV=production
export CONFIG_ENCRYPTION_KEY=your_production_key
export CONFIG_SALT=your_production_salt

# Run with production settings
python main.py --env production

# Or use systemd service (see DEPLOYMENT.md)
```

## Troubleshooting

### Common Issues

#### 1. ImportError: No module named 'X'

**Solution:** Install missing package
```bash
pip install <package-name>
```

#### 2. CONFIG_ENCRYPTION_KEY not set

**Solution:** Set required environment variables
```bash
export CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

#### 3. Redis connection failed

**Solution:** 
- Check if Redis is running: `redis-cli ping`
- Start Redis: `sudo systemctl start redis-server`
- Or run without cache (will use fallback mode)

#### 4. Database connection failed

**Solution:**
- For SQLite: Ensure `data/` directory exists
- For PostgreSQL: Check credentials and ensure PostgreSQL is running

#### 5. Permission denied errors

**Solution:** 
```bash
# Fix directory permissions
chmod 755 logs data credentials
```

### Getting Help

1. Check documentation:
   - [README.md](./README.md) - Overview
   - [SECURITY.md](./SECURITY.md) - Security configuration
   - [DEBUGGING.md](./DEBUGGING.md) - Known issues and fixes

2. Check logs:
   ```bash
   tail -f logs/hopefx_ai.log
   ```

3. Enable debug mode:
   ```bash
   export DEBUG=true
   python main.py
   ```

## Next Steps

After installation:

1. **Configure Trading**
   - Review [.env.example](./.env.example) for all available options
   - Set your risk parameters
   - Configure broker API credentials

2. **Test with Paper Trading**
   ```bash
   # Ensure paper trading is enabled
   # In .env: PAPER_TRADING_MODE=true
   python main.py
   ```

3. **Implement Strategies**
   - Add strategy files to `strategies/` directory
   - Implement signal generation logic
   - Backtest before live trading

4. **Set Up Monitoring**
   - Configure notifications (Discord, Telegram, Email)
   - Set up logging and alerting
   - Monitor system health

5. **Deploy to Production**
   - See [DEPLOYMENT.md](./DEPLOYMENT.md) for production deployment guide
   - Use environment-specific configuration
   - Enable security features

## Uninstallation

```bash
# Deactivate virtual environment
deactivate

# Remove virtual environment
rm -rf venv/

# Remove application data (CAUTION: This deletes all data!)
rm -rf logs/ data/

# Remove configuration
rm -rf config/config.*.json
```

## Support

For issues and questions:
- GitHub Issues: https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues
- Documentation: https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/README.md
