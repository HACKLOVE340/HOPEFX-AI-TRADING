# Quick Start

Get HOPEFX running and producing your first signal in under 15 minutes.

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

# Database — SQLite works for local dev, PostgreSQL for production
DATABASE_URL=sqlite:///./hopefx.db

# App mode
APP_ENV=development
```

All other settings have safe defaults. See `.env.example` for the full list with descriptions.

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

```bash
curl http://localhost:8000/api/signals/latest?symbol=XAUUSD
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

---

## Step 7 — Run a Backtest

```bash
# Quick smoke test (~30 seconds)
python ml/train_advanced.py --smoke

# Full backtest on real GC=F data
python real_data_backtest.py --symbol XAUUSD --years 5
```

Or via the API:
```bash
curl -X POST http://localhost:8000/api/backtest/run \
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

Configure Discord alerts in `.env`:
```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_URL
```

Configure Telegram alerts:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_channel_id
```

Configure email alerts (SendGrid):
```bash
SENDGRID_API_KEY=your_sendgrid_key
ALERT_EMAIL_FROM=alerts@yourdomain.com
ALERT_EMAIL_TO=you@yourdomain.com
```

---

## Common First-Run Issues

| Error | Fix |
|-------|-----|
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
