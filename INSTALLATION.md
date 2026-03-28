# INSTALLATION GUIDE

Complete installation guide for the HOPEFX AI Trading Framework.

## Prerequisites

- Python 3.10, 3.11, or 3.12
- pip (Python package manager)
- Git
- Redis 7+ (optional — rate limiting and caching fall back to in-memory without it)
- PostgreSQL 16+ (optional — SQLite used automatically in development)

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
# Standard install
pip install -r requirements.txt

# CI / lightweight environments (no C extensions, no GPU deps)
pip install -r requirements-ci.txt

# Development mode (editable install + dev tools)
pip install -e ".[dev]"
```

### 4. Configure Environment Variables

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env  # or use your preferred editor
```

**Minimum required variables (app will not start without these):**

```bash
# JWT signing key
SECURITY_JWT_SECRET=<48-char random>   # python -c "import secrets; print(secrets.token_urlsafe(48))"

# Config encryption key
CONFIG_ENCRYPTION_KEY=<48-char random>

# Application mode
APP_ENV=development
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
# Start the API server (development, auto-reload)
uvicorn app:app --reload --port 8000
# Swagger UI: http://localhost:8000/docs

# Or use the quickstart script for paper trading
python quickstart.py
```

## Detailed Installation

All dependencies are declared in `requirements.txt` (full) and `requirements-ci.txt` (lightweight, no C extensions). Do not install packages individually — use the requirements files to ensure version compatibility.

Optional broker-specific packages not included by default:

| Broker | Package | Install |
|---|---|---|
| MetaTrader 5 | `MetaTrader5` | `pip install MetaTrader5` |
| Interactive Brokers | `ib_insync` | `pip install ib_insync` |
| Binance / CCXT | `ccxt` | `pip install ccxt` |

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
python --version  # Should be 3.10+

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
# API server with auto-reload
uvicorn app:app --reload --port 8000
```

Access API documentation at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Production Mode

```bash
# Set environment variables
export APP_ENV=production
export SECURITY_JWT_SECRET=<your-secret>
export CONFIG_ENCRYPTION_KEY=<your-key>

# Run with Gunicorn (recommended for production)
gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# Or use the systemd service (see DEPLOYMENT.md)
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
   - [README.md](./README.md) — Overview and quick start
   - [SETUP_GUIDE.md](./SETUP_GUIDE.md) — Detailed environment configuration
   - [SECURITY.md](./SECURITY.md) — Security configuration and hardening
   - [DEBUGGING.md](./DEBUGGING.md) — Known issues and fixes
   - [DEPLOYMENT.md](./DEPLOYMENT.md) — Production deployment guide

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
