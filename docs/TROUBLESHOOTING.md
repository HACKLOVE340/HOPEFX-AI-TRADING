# Troubleshooting

Common problems and their fixes. If your issue isn't here, check [DEBUGGING.md](DEBUGGING.md) or open a GitHub Issue.

---

## Installation Issues

### `ModuleNotFoundError: No module named 'fastapi'`
The virtual environment is not activated or dependencies are not installed.
```bash
source venv/bin/activate          # Linux/macOS
venv\Scripts\activate             # Windows
pip install -r requirements.txt
```

### `pip install` fails with `error: legacy-install-failure`
Some packages (TA-Lib, psycopg2) require system libraries.
```bash
# Ubuntu
sudo apt install libta-lib-dev libpq-dev python3-dev build-essential -y

# macOS
brew install ta-lib postgresql
```

### `alembic: command not found`
```bash
pip install alembic
# or
python -m alembic upgrade head
```

### `ERROR: Could not find a version that satisfies the requirement MetaTrader5`
MT5 is Windows-only. On Linux/macOS, it's in `requirements-optional.txt` and will be skipped.
```bash
# This is expected on non-Windows — ignore it
pip install -r requirements.txt  # MT5 is not in the core requirements
```

---

## Startup Issues

### `sys.exit(1): SECURITY_JWT_SECRET must be at least 32 characters`
Generate a proper secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Add the output to `.env` as `SECURITY_JWT_SECRET=<value>`.

### `sys.exit(1): DATABASE_URL is not set`
Add to `.env`:
```bash
DATABASE_URL=sqlite:///./hopefx.db    # Development
# or
DATABASE_URL=postgresql://user:pass@localhost:5432/hopefx_db  # Production
```

### `alembic.exc.CommandError: Can't locate revision identified by 'f1a2b3c4d5e6'`
Run all migrations from scratch:
```bash
alembic downgrade base
alembic upgrade head
```

### `Address already in use: port 8000`
Another process is using port 8000:
```bash
# Find and kill it
lsof -ti:8000 | xargs kill -9
# or use a different port
uvicorn app:app --port 8001
```

### Server starts but `/health` returns `{"status": "degraded"}`
Check which component is unhealthy:
```bash
curl http://localhost:8000/health | python3 -m json.tool
```
- `redis: unavailable` — Redis is not running (optional for dev, required for production)
- `ml_model: unavailable` — ML model file missing, run `python ml/train_advanced.py --smoke`
- `database: unhealthy` — check `DATABASE_URL` and run `alembic upgrade head`

---

## ML Model Issues

### `FileNotFoundError: ml/saved_models/advanced_oos.pkl`
The production model file is not present. Generate it:
```bash
# Quick smoke test model (~30 seconds)
python ml/train_advanced.py --smoke

# Full production model (10–30 minutes)
python ml/train_advanced.py --years 50 --oos-years 3
```

### `UnpicklingError` or `ModuleNotFoundError` when loading model
The model was saved with a different Python/sklearn version. Re-save it:
```bash
python -c "
import joblib
import pickle
# Load with pickle fallback
try:
    model = joblib.load('ml/saved_models/advanced_oos.pkl')
except:
    with open('ml/saved_models/advanced_oos.pkl', 'rb') as f:
        model = pickle.load(f)
# Re-save with current joblib
joblib.dump(model, 'ml/saved_models/advanced_oos.pkl', compress=3)
print('Model re-saved successfully')
"
```

### `GET /api/ml/accuracy` returns `model_id: xgb_macro` instead of `advanced_oos`
The production model failed to load and the system fell back. Check logs:
```bash
docker compose logs app | grep "ML model"
# or
journalctl -u hopefx-trading | grep "ML model"
```
Fix: re-run `python ml/train_advanced.py --smoke` and restart.

### ML predictions always return `direction: NEUTRAL`
The model is abstaining on all bars. This happens when:
1. The abstain threshold is too high — lower it in `.env`: `ML_ABSTAIN_THRESHOLD=0.52`
2. Macro features are missing — check `GET /api/macro/snapshot`
3. The model is in CI mode — check `advanced_oos_meta.json` for `"ci_mode": true`

---

## Broker Issues

### `OANDA: 401 Unauthorized`
Your API token is invalid or expired:
1. Log in to OANDA → Manage API Access → Generate a new token
2. Update `BROKER_OANDA_TOKEN` in `.env`
3. Restart the application

### `OANDA: Account not found`
Check your account ID format. It should be `001-001-XXXXXXX-001`:
```bash
python scripts/validate_oanda.py
```

### `OANDA: Instrument not tradeable`
Some instruments are not available on practice accounts. Use `XAU_USD` (not `XAUUSD`):
```bash
OANDA_DEFAULT_INSTRUMENT=XAU_USD
```

### `IBKR: Connection refused on port 7496`
TWS or IB Gateway is not running, or the port is wrong:
- TWS live: port 7496
- TWS paper: port 7497
- IB Gateway live: port 4001
- IB Gateway paper: port 4002

Enable API connections in TWS: Edit → Global Configuration → API → Settings → Enable ActiveX and Socket Clients.

### `FIX adapter: credential validation failed`
In production, the FIX adapter requires real broker credentials:
```bash
FIX_SENDER_COMP_ID=your_sender_comp_id
FIX_TARGET_COMP_ID=broker_target_comp_id
FIX_HOST=broker-fix-gateway.com
FIX_PORT=1234
```
For development/paper trading, set `APP_ENV=development` to skip this check.

---

## Database Issues

### `sqlite3.OperationalError: database is locked`
SQLite only supports one writer at a time. Use PostgreSQL for multi-process setups:
```bash
DATABASE_URL=postgresql://hopefx:password@localhost:5432/hopefx_db
```

### `psycopg2.OperationalError: could not connect to server`
PostgreSQL is not running or credentials are wrong:
```bash
sudo systemctl start postgresql
sudo -u postgres psql -c "\l"  # List databases
```

### `alembic.exc.CommandError: Target database is not up to date`
```bash
alembic upgrade head
```

### `sqlalchemy.exc.ProgrammingError: column "position_metadata" does not exist`
Run migrations:
```bash
alembic upgrade head
```

---

## Redis Issues

### `redis.exceptions.ConnectionError: Error connecting to Redis`
Redis is not running:
```bash
# Ubuntu
sudo systemctl start redis-server
sudo systemctl status redis-server

# macOS
brew services start redis

# Docker
docker compose up -d redis
```

### `redis.exceptions.AuthenticationError`
Set the Redis password in `.env`:
```bash
REDIS_URL=redis://:your_password@localhost:6379/0
```

---

## API Issues

### `401 Unauthorized` on all endpoints
Get a token first:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl http://localhost:8000/api/signals/latest \
  -H "Authorization: Bearer $TOKEN"
```

### `422 Unprocessable Entity`
The request body doesn't match the expected schema. Check `/docs` for the correct format.

### `429 Too Many Requests`
You've hit the rate limit. Wait for the `X-RateLimit-Reset` timestamp, or reduce request frequency.

### `503 Service Unavailable`
The kill switch is active or the broker is disconnected:
```bash
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"
```

---

## Docker Issues

### `docker compose up` fails with `port is already allocated`
A service is already using that port:
```bash
# Find what's using port 8000
lsof -ti:8000
# Change the port in docker-compose.yml
ports:
  - "8001:8000"
```

### Container exits immediately
Check logs:
```bash
docker compose logs app
```
Common causes: missing `.env` file, invalid secrets, database not ready.

### `docker compose up` is slow on first run
The ML model training runs on first startup if no model file exists. This is expected.
Pre-build the model before deploying:
```bash
python ml/train_advanced.py --smoke
# Then copy ml/saved_models/ to your server before docker compose up
```

---

## Performance Issues

### API response time > 500ms
1. Check Redis is running (feature cache reduces ML inference from ~200ms to ~5ms)
2. Check database query time: `GET /metrics | grep hopefx_db_query`
3. Check if ML model is loading on every request (should be cached in memory)

### High memory usage
The ML model uses ~500MB RAM. If you're on a 4GB VPS:
```bash
# Check memory usage
docker stats
# Reduce worker count
uvicorn app:app --workers 1
```

### `OOM Killed` in Docker
Increase the memory limit in `docker-compose.yml`:
```yaml
services:
  app:
    mem_limit: 2g
```

---

## Getting More Help

1. Check [DEBUGGING.md](DEBUGGING.md) for detailed debugging procedures
2. Check [FAQ.md](FAQ.md) for common questions
3. Search [GitHub Issues](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues)
4. Open a new issue with: Python version, OS, error traceback, and reproduction steps
