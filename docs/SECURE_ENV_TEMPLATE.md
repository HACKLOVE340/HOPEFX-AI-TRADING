# .env.example - NEVER COMMIT REAL VALUES
# Copy to .env and fill with your secrets

# =============================================================================
# REQUIRED: Application Security
# =============================================================================
# Generate: openssl rand -hex 32
SECURITY_SECRET_KEY=your-64-char-hex-key-here-never-use-defaults

# Optional: Fernet encryption key (for at-rest encryption)
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SECURITY_ENCRYPTION_KEY=your-44-char-fernet-key-here=

# =============================================================================
# REQUIRED: Database (TimescaleDB/PostgreSQL)
# =============================================================================
DB_HOST=localhost
DB_PORT=5432
DB_NAME=hopefx
DB_USER=hopefx
# STRONG PASSWORD REQUIRED - min 8 chars
DB_PASSWORD=your-secure-db-password-here

# =============================================================================
# REQUIRED: Redis
# =============================================================================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password-here

# =============================================================================
# Broker Credentials
# =============================================================================
# Default broker: Interactive Brokers (IBKR) via ib_insync
# Set BROKER_TYPE=ibkr (default) or BROKER_TYPE=paper for paper trading.
BROKER_TYPE=paper
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# =============================================================================
# Optional: HashiCorp Vault (Production Recommended)
# =============================================================================
VAULT_ENABLED=false
VAULT_ADDR=https://vault.your-domain.com:8200
VAULT_TOKEN=your-vault-token
VAULT_MOUNT_POINT=secret
VAULT_PATH=hopefx/production

# =============================================================================
# Trading Configuration
# =============================================================================
TRADING_PAPER_TRADING=true
TRADING_MAX_POSITION_SIZE=10.0
TRADING_MAX_DAILY_LOSS_PCT=2.0
TRADING_MAX_DRAWDOWN_PCT=5.0

# =============================================================================
# Live Trading Confirmation (REQUIRED for live trading)
# =============================================================================
# Set to exactly: I_UNDERSTAND_RISKS
# LIVE_TRADING_CONFIRMED=I_UNDERSTAND_RISKS
