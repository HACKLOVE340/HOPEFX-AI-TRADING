# Quick Start

> Get HOPEFX running and producing your first signal in under 15 minutes.
> A valid subscription license key is required for trading endpoints.
> Last updated: 2026-04-01

---

## Prerequisites

- Python 3.10, 3.11, or 3.12
- Git
- 4 GB RAM minimum (8 GB recommended for ML training)

---

## Step 1 — Clone and Install

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# Create a virtual environment
python -m venv venv
source venv/bin/activate          # Linux/macOS
# venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt
```

If you want optional ML extras (TensorFlow, PyTorch, TA-Lib):
```bash
pip install -r requirements-optional.txt
```

---

## Step 2 — Configure Environment

```bash
cp .env.example .env
```

Open `.env` and set the minimum required values:

```bash
# Required — generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECURITY_JWT_SECRET=your_48_char_random_secret_here
CONFIG_ENCRYPTION_KEY=another_48_char_random_secret_here
HOPEFX_KILL_SWITCH_TOKEN=yet_another_48_char_random_secret_here

# Subscription license key — required for all trading, signal, and ML endpoints
# Obtain from hopefx.com/pricing or request a 14-day trial via GitHub Issues (label: trial-request)
# Without this, /api/trading/, /api/signals/, and /api/ml/ return 403 Subscription Required
HOPEFX_LICENSE_KEY=HOPEFX-PRO-XXXXXXXX-XXXX

# Database — SQLite works for local dev, PostgreSQL for production
DATABASE_URL=sqlite:///./hopefx.db

# App mode
APP_ENV=development
```

Generate all three security secrets at once:
```bash
python -c "
import secrets
print('SECURITY_JWT_SECRET=' + secrets.token_hex(32))
print('CONFIG_ENCRYPTION_KEY=' + secrets.token_hex(32))
print('HOPEFX_KILL_SWITCH_TOKEN=' + secrets.token_hex(32))
"
```

All other settings have safe defaults. See `.env.example` for the full list with descriptions.

---

## Step 2b — Activate Your License Key

After adding `HOPEFX_LICENSE_KEY` to `.env`, validate it before starting:

```bash
python scripts/manage_secrets.py validate
```

Expected output:
```
✓ SECURITY_JWT_SECRET: set (64 chars)
✓ CONFIG_ENCRYPTION_KEY: set (64 chars)
✓ HOPEFX_KILL_SWITCH_TOKEN: set (64 chars)
✓ HOPEFX_LICENSE_KEY: valid (plan=professional, expires=2026-08-14)
All required secrets are valid.
```

If you do not yet have a license key, the app will still start — but all trading,
signal, and ML endpoints will return `403 Subscription Required`. The `/health`,
`/docs`, and `/metrics` endpoints remain accessible without a key.

---

## Step 3 — Initialize the Database

```bash
alembic upgrade head
```

This creates all tables including the watchlists table (migration `f1a2b3c4d5e6`).

---

## Step 4 — Start the Server

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

You should see:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     ComponentRegistry: starting components...
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) to see the interactive API documentation.

---

## Step 5 — Verify Health

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "environment": "development",
  "components": {
    "database": "healthy",
    "redis": "unavailable",
    "ml_model": "healthy",
    "broker": "paper"
  }
}
```

`redis: unavailable` is fine for local development. Install Redis for production.

---

## Step 6 — Get Your First Signal

First, get a JWT token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Then fetch the latest signal (requires Starter+ subscription):

```bash
curl "http://localhost:8000/api/signals/latest?symbol=XAUUSD" \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
{
  "symbol": "XAUUSD",
  "direction": "BUY",
  "confidence": 0.72,
  "ml_probability": 0.68,
  "strategy": "strategy_brain",
  "timestamp": "2026-07-14T10:30:00Z",
  "entry": 2345.50,
  "stop_loss": 2330.00,
  "take_profit": 2375.00,
  "risk_reward": 2.0
}
```

If you see `403 Subscription Required`, your `HOPEFX_LICENSE_KEY` is missing or invalid.
If you see `401 Unauthorized`, your token is missing or expired — re-run the login command.

---

## Step 7 — Run a Backtest

```bash
# Quick smoke test (~30 seconds)
python ml/train_advanced.py --smoke

# Full backtest on real GC=F data
python real_data_backtest.py --symbol XAUUSD --years 5
```

Or via the API (requires Starter+ subscription):
```bash
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "XAUUSD", "strategy": "ma_crossover", "years": 1}'
```

---

## Step 8 — Connect a Broker (Optional)

### Paper Trading (default — no credentials needed)
Paper trading is active by default. All signals are simulated with no real money.

### OANDA Practice Account (recommended first step)
1. Create a free practice account at [oanda.com](https://www.oanda.com/register/)
2. Generate an API token from your dashboard
3. Add to `.env`:
   ```bash
   BROKER_TYPE=oanda
   BROKER_OANDA_TOKEN=your_practice_api_token
   BROKER_OANDA_ACCOUNT=001-001-XXXXXXX-001
   OANDA_ENVIRONMENT=practice
   ```
4. Validate:
   ```bash
   python scripts/validate_oanda.py
   ```

See [OANDA Paper Trading Setup](oanda_paper_trading_setup.md) for the full guide.

### Other Brokers
| Broker | Env Var | Guide |
|--------|---------|-------|
| Interactive Brokers | `BROKER_TYPE=ibkr` | [Setup Guide](SETUP_GUIDE.md) |
| Alpaca | `BROKER_TYPE=alpaca` | [Setup Guide](SETUP_GUIDE.md) |
| Binance | `BROKER_TYPE=binance` | [Setup Guide](SETUP_GUIDE.md) |
| MetaTrader 5 | `BROKER_TYPE=mt5` | [Setup Guide](SETUP_GUIDE.md) |

---

## Step 9 — Enable ML Predictions

The production ML model (`advanced_oos.pkl`) is loaded automatically if present.
Check its status:

```bash
curl http://localhost:8000/api/ml/accuracy
```

To retrain the model on 50 years of XAUUSD data:
```bash
python ml/train_advanced.py --years 50 --oos-years 3
```

This takes 10–30 minutes depending on your hardware. See [ML Guide](ML_GUIDE.md) for details.

---

## Step 10 — Set Up Alerts

Configure Telegram alerts in `.env`:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token        # From @BotFather on Telegram
TELEGRAM_CHAT_ID=your_channel_id         # Your chat or channel ID
```

Configure email alerts (SendGrid):
```bash
SENDGRID_API_KEY=your_sendgrid_key
ALERT_EMAIL_FROM=alerts@yourdomain.com
ALERT_EMAIL_TO=you@yourdomain.com
```

Test alerts after configuring:
```bash
curl -X POST http://localhost:8000/api/notifications/test \
  -H "Authorization: Bearer $TOKEN"
```

---

## Common First-Run Issues

| Error | Fix |
|-------|-----|
| `403 Subscription Required` | Set `HOPEFX_LICENSE_KEY` in `.env` — see Step 2b |
| `403 Plan Limit Exceeded` | Feature requires a higher plan — check [MONETIZATION.md](MONETIZATION.md) |
| `401 Unauthorized` | JWT token missing or expired — re-run the login command |
| `ModuleNotFoundError: No module named 'fastapi'` | Run `pip install -r requirements.txt` |
| `alembic: command not found` | Run `pip install alembic` |
| `SECURITY_JWT_SECRET must be at least 32 characters` | Generate a proper secret (see Step 2) |
| `ML model not found` | Run `python ml/train_advanced.py --smoke` to create a test model |
| `Redis connection refused` | Redis is optional for dev — set `REDIS_URL=` to disable |
| `Database locked` | Only one process can use SQLite at a time — use PostgreSQL for multi-process |

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more.

---

## What's Next

| Goal | Guide |
|------|-------|
| Run a full backtest | [Backtesting Guide](BACKTESTING_GUIDE.md) |
| Connect OANDA for paper trading | [OANDA Paper Trading Setup](oanda_paper_trading_setup.md) |
| Understand the ML model | [Model Performance](model_performance.md) |
| Configure risk limits | [Risk Management](RISK_MANAGEMENT.md) |
| Deploy to a VPS | [Deployment](DEPLOYMENT.md) |
| Enable live trading | [Live Trading Gate](live_trading_gate.md) |
