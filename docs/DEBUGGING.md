# Debugging Guide

> How to diagnose and resolve issues in a running HOPEFX instance.
> Last updated: 2026-04-01

---

## Contents

1. [Log Configuration](#log-configuration)
2. [Reading Logs](#reading-logs)
3. [Health Check Breakdown](#health-check-breakdown)
4. [Signal Issues](#signal-issues)
5. [ML Issues](#ml-issues)
6. [Broker Issues](#broker-issues)
7. [Risk Engine Issues](#risk-engine-issues)
8. [Database Issues](#database-issues)
9. [Redis Issues](#redis-issues)
10. [API Issues](#api-issues)
11. [WebSocket Issues](#websocket-issues)
12. [Subscription & License Issues](#subscription--license-issues)
13. [Debug Mode](#debug-mode)
14. [Useful One-Liners](#useful-one-liners)

---

## Log Configuration

Set the log level in `.env`:

```bash
LOG_LEVEL=INFO    # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

Use `INFO` in production. Use `DEBUG` only when actively diagnosing — it generates
significant output and may log sensitive data. Always restore `INFO` before returning
to production.

Structured log format (JSON) for log aggregation:

```bash
LOG_FORMAT=json    # json | text (default: text)
```

---

## Reading Logs

### Docker Compose

```bash
# All services
docker compose logs -f

# App only
docker compose logs -f app

# Last 200 lines
docker compose logs --tail=200 app

# Filter for errors only
docker compose logs app 2>&1 | grep -E "ERROR|CRITICAL|Exception|Traceback"

# Filter by component
docker compose logs app 2>&1 | grep "signal_engine"
docker compose logs app 2>&1 | grep "risk_manager"
docker compose logs app 2>&1 | grep "broker"
```

### systemd (VPS)

```bash
journalctl -u hopefx-trading -f
journalctl -u hopefx-trading --since "1 hour ago"
journalctl -u hopefx-trading -p err        # errors only
journalctl -u hopefx-trading --since today  # today's logs
```

### Admin API

```bash
curl http://localhost:8000/api/admin/logs \
  -H "Authorization: Bearer $TOKEN"
```

---

## Health Check Breakdown

The health endpoint is the first place to check when something is wrong:

```bash
curl http://localhost:8000/health | python3 -m json.tool
```

```json
{
  "status": "healthy",
  "version": "2.0.0",
  "environment": "production",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "ml_model": "healthy",
    "broker": "oanda_practice",
    "kill_switch": "inactive",
    "online_learner": "active",
    "license": "valid"
  }
}
```

| Component | Unhealthy Cause | Fix |
|-----------|----------------|-----|
| `database` | DB unreachable or migrations not run | Check `DATABASE_URL`; run `alembic upgrade head` |
| `redis` | Redis not running | `sudo systemctl start redis-server` or `docker compose up redis -d` |
| `ml_model` | `advanced_oos.pkl` missing or corrupt | Run `python ml/train_advanced.py --smoke` |
| `broker` | Broker credentials invalid or expired | Check `OANDA_API_KEY`; run `python scripts/validate_oanda.py` |
| `kill_switch` | Kill switch is active | Check `risk/halt_state.json`; investigate cause before clearing |
| `online_learner` | `ML_HOURLY_ENABLED=false` | Enable if needed, or ignore if not using online learning |
| `license` | License key invalid or expired | Check `HOPEFX_LICENSE_KEY` in `.env`; renew subscription |

---

## Signal Issues

### No signals being generated

```bash
# Check signal engine status
curl http://localhost:8000/api/signals/latest \
  -H "Authorization: Bearer $TOKEN"

# Check ML model
curl http://localhost:8000/api/ml/health \
  -H "Authorization: Bearer $TOKEN"

# Check current market regime
curl http://localhost:8000/api/ml/regime \
  -H "Authorization: Bearer $TOKEN"

# Check broker data feed freshness
curl http://localhost:8000/api/broker/status \
  -H "Authorization: Bearer $TOKEN"

# Check market calendar (is market open?)
curl http://localhost:8000/api/calendar/today \
  -H "Authorization: Bearer $TOKEN"
```

Common causes:

| Cause | How to confirm | Fix |
|-------|---------------|-----|
| ML model abstaining (normal) | `abstain_rate` in `/api/ml/health` | Normal — model abstains on ~27.5% of bars |
| Kill switch active | `kill_switch: active` in `/health` | Investigate halt reason in `risk/halt_state.json` |
| Broker data feed stale | `last_price_age_seconds > 60` in `/api/broker/status` | Restart broker connector |
| Market closed | `is_open: false` in `/api/calendar/today` | Wait for market open |
| Confidence below threshold | `confidence < ML_ABSTAIN_THRESHOLD` | Lower threshold or wait for clearer setup |

### Signals not reaching the broker

```bash
# Check execution engine state
curl http://localhost:8000/api/trading/brain-state \
  -H "Authorization: Bearer $TOKEN"

# Check risk gate status
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Check recent orders (look for TradeBlocked entries)
curl http://localhost:8000/api/trading/trades \
  -H "Authorization: Bearer $TOKEN"
```

Common causes:

| Cause | How to confirm | Fix |
|-------|---------------|-----|
| CVaR gate blocking | `cvar_pct > CVAR_LIMIT_PCT` in risk status | Close some positions to reduce CVaR |
| Daily loss limit hit | `daily_loss_pct >= DAILY_LOSS_LIMIT_PCT` | Wait for next trading day or adjust limit |
| `FEATURE_LIVE_TRADING=false` | Check `.env` | Set `FEATURE_LIVE_TRADING=true` for live trading |
| Paper broker active | `broker_type: paper` in brain state | Set `BROKER_TYPE=oanda` (or your broker) |

---

## ML Issues

### Model accuracy degraded

```bash
# Check current model accuracy
curl http://localhost:8000/api/ml/accuracy \
  -H "Authorization: Bearer $TOKEN"
# {"model_id":"advanced_oos","accuracy":0.664,...}
# If model_id is "xgb_macro", the fallback is active

# Check logs for the cause
docker compose logs app | grep -E "ML model|fallback|advanced_oos"
```

If fallback is active:
```bash
# Quick smoke test
python ml/train_advanced.py --smoke

# Full retrain (Elite only — takes ~2 hours)
python ml/train_advanced.py --years 50 --oos-years 3
```

### Macro features missing or stale

```bash
# Check macro data snapshot
curl http://localhost:8000/api/macro/snapshot \
  -H "Authorization: Bearer $TOKEN"

# Check data file ages
ls -la data/macro/

# Force refresh
python -m ml.macro_bootstrap
```

Macro data older than 24 hours triggers a Grafana alert (`hopefx_macro_features_age_seconds > 86400`).

### Online learner not updating

```bash
# Check learner status
curl http://localhost:8000/api/online-learner/status \
  -H "Authorization: Bearer $TOKEN"

# Verify flag is set
grep ML_HOURLY_ENABLED .env

# Check logs for hourly update
docker compose logs app | grep "online_learner"
```

Online learning requires Elite plan. If `ML_HOURLY_ENABLED=true` but updates are not
happening, check that the learner state file exists:

```bash
ls -la ml/saved_models/online_learner_*.pkl
```

If missing, the learner initialises on the next hourly tick.

### Feature count mismatch

If the model reports fewer than 176 features:

```bash
curl http://localhost:8000/api/ml/health \
  -H "Authorization: Bearer $TOKEN"
# {"feature_count": 154, ...}  <-- mismatch
```

This usually means macro features failed to load. Check:
```bash
python -c "from ml.feature_engineering import build_features; print('OK')"
python -m ml.macro_bootstrap
```

---

## Broker Issues

### OANDA connectivity

```bash
# Full validation
python scripts/validate_oanda.py

# Quick API test
curl http://localhost:8000/api/broker/test-connection \
  -H "Authorization: Bearer $TOKEN"

# Check account balance
curl http://localhost:8000/api/trading/account \
  -H "Authorization: Bearer $TOKEN"
```

Common OANDA errors:

| Error | Cause | Fix |
|-------|-------|-----|
| `401 Unauthorized` | API token expired or wrong | Regenerate token in OANDA portal |
| `Account not found` | Wrong account ID format | Must be `001-001-XXXXXXX-001` |
| `Instrument not tradeable` | Wrong instrument code | Use `XAU_USD` not `XAUUSD` |
| `No prices updating` | Wrong env var name | Check both `OANDA_API_KEY` and `BROKER_OANDA_TOKEN` |

### Position mismatch (OMS vs broker)

If the OMS shows positions that don't match the broker:

```bash
# Trigger manual reconciliation
curl -X POST http://localhost:8000/api/trading/reconcile \
  -H "Authorization: Bearer $TOKEN"

# Check reconciliation log
docker compose logs app | grep "reconcil"
```

The `PositionReconciler` runs automatically every 5 minutes. If mismatches persist after
reconciliation, check `core/position_reconciler.py` logs for the specific discrepancy.

### FIX protocol issues (IBKR)

```bash
# Check FIX session state
curl http://localhost:8000/api/broker/fix/status \
  -H "Authorization: Bearer $TOKEN"

# Check FIX log
tail -100 logs/fix_session.log
```

FIX sessions require the TWS or IB Gateway to be running and logged in. The session
resets daily at 23:45 ET — reconnection is automatic.

---

## Risk Engine Issues

### Kill switch fired unexpectedly

```bash
# Check halt state
cat risk/halt_state.json

# Check risk status
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Find the log entry when it fired
docker compose logs app | grep -E "kill switch|halt|HALT|emergency"
```

The halt state file shows: timestamp, reason, and which limit was breached.

**Do not clear the kill switch without investigating the cause.** Clearing it while
the underlying condition persists will cause it to fire again immediately.

To clear after investigation:
```bash
curl -X DELETE http://localhost:8000/api/risk/halt \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

### CVaR gate blocking all orders

```bash
# Check current CVaR
curl http://localhost:8000/api/trading/risk-metrics \
  -H "Authorization: Bearer $TOKEN"
# {"cvar_pct": 3.2, "cvar_limit": 2.0, ...}

# If CVaR is too high, close some positions to reduce exposure
curl -X DELETE http://localhost:8000/api/trading/positions \
  -H "Authorization: Bearer $TOKEN"
```

### Daily loss limit hit

```bash
# Check daily P&L
curl http://localhost:8000/api/trading/account \
  -H "Authorization: Bearer $TOKEN"
# {"daily_loss_pct": 2.1, "daily_loss_limit": 2.0, ...}
```

The limit resets at midnight UTC. If you need to trade before midnight, adjust
`DAILY_LOSS_LIMIT_PCT` in `.env` and restart the app — but only after reviewing
why the limit was hit.

---

## Database Issues

### Slow queries

```bash
# Enable query logging temporarily
# In .env:
SQLALCHEMY_ECHO=true

# Restart and watch for slow queries
docker compose restart app
docker compose logs -f app | grep "SELECT\|INSERT\|UPDATE" | head -50

# PostgreSQL slow query log
sudo -u postgres psql hopefx_db -c "
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;"
```

Disable `SQLALCHEMY_ECHO` after debugging — it logs every query.

### Migration state

```bash
# Check current revision
alembic current

# Check pending migrations
alembic history --verbose

# Apply all pending
alembic upgrade head

# Roll back one step (if needed)
alembic downgrade -1
```

### Database size

```bash
# PostgreSQL
sudo -u postgres psql hopefx_db -c "\l+"

# SQLite
ls -lh hopefx.db

# Check largest tables (PostgreSQL)
sudo -u postgres psql hopefx_db -c "
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;"
```

### Connection pool exhausted

If you see `QueuePool limit of size X overflow Y reached`:

```bash
# In .env, increase pool size
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
```

Or check for connection leaks:
```bash
sudo -u postgres psql hopefx_db -c "SELECT count(*) FROM pg_stat_activity WHERE datname='hopefx_db';"
```

---

## Redis Issues

```bash
# Check Redis is running
redis-cli ping   # Expected: PONG

# Check memory usage
redis-cli info memory | grep used_memory_human

# Check cache hit rate
redis-cli info stats | grep keyspace_hits

# Check all keys (development only — do not run on large production Redis)
redis-cli keys "hopefx:*" | head -20

# Flush feature cache (forces recompute on next tick)
# WARNING: clears all Redis data for this DB
redis-cli flushdb
```

If Redis is unavailable, the app falls back to in-memory caching automatically.
This adds ~200ms to ML inference requests. Check logs for:
```
WARNING: Redis unavailable, falling back to in-memory cache
```

---

## API Issues

### Slow API responses

```bash
# Check p99 latency via Prometheus
curl http://localhost:9090/api/v1/query \
  --data-urlencode 'query=histogram_quantile(0.99, rate(hopefx_request_duration_seconds_bucket[5m]))'

# Check via app metrics endpoint
curl http://localhost:8000/metrics | grep hopefx_request_duration
```

Target: p99 < 200ms. If above:
1. Check Redis is running (cache miss adds ~200ms)
2. Check database query time (`SQLALCHEMY_ECHO=true`)
3. Check if ML model is loading on every request (should be cached in memory)
4. Check for N+1 query patterns in logs

### 500 errors

```bash
# Find the full traceback
docker compose logs app | grep -A 30 "Traceback"

# Check Sentry for grouped errors (if configured)
# SENTRY_DSN must be set in .env
```

### 401 Unauthorized

```bash
# Check token is valid
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer $TOKEN"

# Generate a new token
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "your_user", "password": "your_pass"}'
```

Tokens expire after 24 hours. If you see 401 on a fresh token, check `SECURITY_JWT_SECRET`
is set and has not changed since the token was issued.

### 403 Plan Limit Exceeded

```bash
# Check your current plan
curl http://localhost:8000/api/monetization/subscription/me \
  -H "Authorization: Bearer $TOKEN"

# Check what plan a feature requires
curl http://localhost:8000/api/monetization/pricing \
  -H "Authorization: Bearer $TOKEN"
```

---

## WebSocket Issues

### WebSocket disconnects frequently

```bash
# Check WebSocket status
curl http://localhost:8000/api/ws/status \
  -H "Authorization: Bearer $TOKEN"

# Check logs for disconnect reasons
docker compose logs app | grep -E "websocket|ws|disconnect"
```

Common causes:
- Nginx proxy timeout (default 60s) — add `proxy_read_timeout 3600;` to Nginx config
- Load balancer idle timeout — configure sticky sessions or increase timeout
- Client not sending ping frames — implement client-side heartbeat every 30s

### WebSocket not receiving data

```bash
# Test WebSocket directly
python3 -c "
import asyncio, websockets, json

async def test():
    uri = 'ws://localhost:8000/ws/prices?token=YOUR_TOKEN'
    async with websockets.connect(uri) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        print(json.loads(msg))

asyncio.run(test())
"
```

If no data arrives within 10 seconds, check that the broker data feed is active
(`GET /api/broker/status`) and that the symbol is in `OANDA_INSTRUMENTS`.

---

## Subscription & License Issues

### `403 Subscription Required` on all endpoints

```bash
# Check license key is set
grep HOPEFX_LICENSE_KEY .env

# Validate the key
python scripts/manage_secrets.py validate

# Check license status via API
curl http://localhost:8000/api/monetization/subscription/me \
  -H "Authorization: Bearer $TOKEN"
```

If the key is set but still failing:
- Verify the key format: `HOPEFX-{TIER}-{RANDOM}-{CHECKSUM}`
- Check the key has not expired (30-day validity)
- Check the machine fingerprint matches (keys are device-bound)

### License key expired

Renew your subscription at `hopefx.com/billing` or via:
```bash
POST /api/monetization/subscribe
```

A new key is emailed on successful payment. Update `.env` with the new key and restart.

### Machine fingerprint mismatch

If you moved the installation to a new server, the license key is bound to the old
machine fingerprint. Contact support@hopefx.io to transfer the key to the new machine.

---

## Debug Mode

For deep debugging, enable structured debug logging:

```bash
# .env
LOG_LEVEL=DEBUG
SQLALCHEMY_ECHO=true
BROKER_DEBUG=true
```

Restart and watch logs:
```bash
docker compose restart app
docker compose logs -f app | grep -E "DEBUG|signal_engine|risk|broker"
```

**Always disable debug mode before returning to production.** Debug mode logs:
- Full SQL queries (may contain user data)
- Broker API request/response bodies (may contain account details)
- ML feature vectors (large output)

---

## Useful One-Liners

```bash
# Count errors in the last hour
docker compose logs app --since 1h | grep -c ERROR

# Find the last exception with context
docker compose logs app | grep -A 20 "Traceback" | tail -25

# Check all component statuses at once
curl -s http://localhost:8000/health | python3 -m json.tool

# Watch signal generation in real time
docker compose logs -f app | grep -E "signal|BUY|SELL|NEUTRAL|abstain"

# Watch order placement in real time
docker compose logs -f app | grep -E "order|fill|TradeBlocked|CVaR"

# Check kill switch state
cat risk/halt_state.json 2>/dev/null || echo "Kill switch not active"

# Check current drawdown
curl -s http://localhost:8000/api/trading/risk-metrics \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep drawdown

# Tail the last 50 trades
curl -s "http://localhost:8000/api/trading/trades?limit=50" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Check Redis cache hit rate
redis-cli info stats | grep -E "keyspace_hits|keyspace_misses"

# Check PostgreSQL active connections
sudo -u postgres psql hopefx_db -c "SELECT count(*) FROM pg_stat_activity WHERE state='active';"

# Verify all migrations applied
alembic current && alembic heads
```

---

*Last updated: 2026-04-01*
