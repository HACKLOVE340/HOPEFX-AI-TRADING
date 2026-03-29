# Debugging Guide

> How to diagnose and fix issues in a running HOPEFX instance.
> Last updated: 2026-07-14

---

## Log Levels

Set the log level in `.env`:

```bash
LOG_LEVEL=DEBUG    # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

In production, use `INFO`. Use `DEBUG` only when actively diagnosing an issue —
it generates significant output and may log sensitive data.

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

# Filter for errors
docker compose logs app 2>&1 | grep -E "ERROR|CRITICAL|Exception"
```

### systemd (VPS)

```bash
journalctl -u hopefx-trading -f
journalctl -u hopefx-trading --since "1 hour ago"
journalctl -u hopefx-trading -p err   # errors only
```

### Admin API

```bash
curl http://localhost:8000/api/admin/logs \
  -H "Authorization: Bearer $TOKEN"
```

---

## Health Check Breakdown

```bash
curl http://localhost:8000/health | python3 -m json.tool
```

```json
{
  "status": "healthy",
  "environment": "production",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "ml_model": "healthy",
    "broker": "oanda_practice",
    "kill_switch": "inactive",
    "online_learner": "active"
  }
}
```

| Component | Unhealthy Cause | Fix |
|-----------|----------------|-----|
| `database` | DB unreachable or migrations not run | Check `DATABASE_URL`, run `alembic upgrade head` |
| `redis` | Redis not running | `sudo systemctl start redis-server` |
| `ml_model` | `advanced_oos.pkl` missing or corrupt | Run `python ml/train_advanced.py --smoke` |
| `broker` | Broker credentials invalid | Check `BROKER_OANDA_TOKEN`, run `python scripts/validate_oanda.py` |
| `kill_switch` | Kill switch is active | Check `risk/halt_state.json`, investigate cause before clearing |
| `online_learner` | `ML_HOURLY_ENABLED=false` | Enable if needed, or ignore if not using online learning |

---

## Diagnosing Signal Issues

### No signals being generated

```bash
# Check signal engine status
curl http://localhost:8000/api/signals/latest \
  -H "Authorization: Bearer $TOKEN"

# Check ML model
curl http://localhost:8000/api/ml/health \
  -H "Authorization: Bearer $TOKEN"

# Check regime
curl http://localhost:8000/api/ml/regime \
  -H "Authorization: Bearer $TOKEN"

# Check broker data feed
curl http://localhost:8000/api/broker/status \
  -H "Authorization: Bearer $TOKEN"
```

Common causes:
- ML model is abstaining (confidence below threshold) — normal on 27.5% of bars
- Kill switch is active — check `GET /api/risk/status`
- Broker data feed is stale — check `GET /api/broker/status`
- Market is closed — check `GET /api/calendar/today`

### Signals not reaching the broker

```bash
# Check execution engine
curl http://localhost:8000/api/trading/brain-state \
  -H "Authorization: Bearer $TOKEN"

# Check risk status
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Check recent orders
curl http://localhost:8000/api/trading/trades \
  -H "Authorization: Bearer $TOKEN"
```

Common causes:
- CVaR gate blocking orders — check `risk_metrics.cvar_pct` vs `CVAR_LIMIT_PCT`
- Daily loss limit hit — check `daily_loss_pct` vs `DAILY_LOSS_LIMIT_PCT`
- `FEATURE_LIVE_TRADING=false` — orders go to paper broker, not real broker

---

## Diagnosing ML Issues

### Model accuracy degraded

```bash
# Check current model
curl http://localhost:8000/api/ml/accuracy \
  -H "Authorization: Bearer $TOKEN"

# Check if fallback is active
# If model_id is "xgb_macro" instead of "advanced_oos", fallback is active
```

If fallback is active:
```bash
# Check logs for the cause
docker compose logs app | grep "ML model"

# Retrain
python ml/train_advanced.py --smoke   # Quick test first
python ml/train_advanced.py --years 50 --oos-years 3  # Full retrain
```

### Macro features missing

```bash
# Check macro store
curl http://localhost:8000/api/macro/snapshot \
  -H "Authorization: Bearer $TOKEN"

# Force refresh
python -m ml.macro_bootstrap

# Check data files
ls -la data/macro/
```

### Online learner not updating

```bash
# Check status
curl http://localhost:8000/api/online-learner/status \
  -H "Authorization: Bearer $TOKEN"

# Verify flag is set
grep ML_HOURLY_ENABLED .env

# Check logs for hourly update
docker compose logs app | grep "online_learner"
```

---

## Diagnosing Broker Issues

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

### Position mismatch (OMS vs broker)

If the OMS shows positions that don't match the broker:

```bash
# Trigger reconciliation
curl -X POST http://localhost:8000/api/trading/reconcile \
  -H "Authorization: Bearer $TOKEN"

# Check reconciliation log
docker compose logs app | grep "reconcil"
```

The `PositionReconciler` runs automatically every 5 minutes. If mismatches persist,
check `core/position_reconciler.py` logs for the specific discrepancy.

---

## Diagnosing Database Issues

### Slow queries

```bash
# Enable query logging in .env
SQLALCHEMY_ECHO=true

# Check slow query log (PostgreSQL)
sudo -u postgres psql hopefx_db -c "
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;"
```

### Migration state

```bash
# Check current revision
alembic current

# Check pending migrations
alembic history --verbose

# Apply all pending
alembic upgrade head
```

### Database size

```bash
# PostgreSQL
sudo -u postgres psql hopefx_db -c "\l+"

# SQLite
ls -lh hopefx.db
```

---

## Diagnosing Redis Issues

```bash
# Check Redis is running
redis-cli ping   # Expected: PONG

# Check memory usage
redis-cli info memory | grep used_memory_human

# Check feature cache hit rate
redis-cli info stats | grep keyspace_hits

# Flush feature cache (forces recompute on next tick)
redis-cli flushdb   # WARNING: clears all Redis data for this DB
```

---

## Diagnosing API Issues

### Slow API responses

```bash
# Check Prometheus metrics
curl http://localhost:9090/metrics | grep hopefx_api_latency

# Check p99 latency
curl http://localhost:8000/metrics | grep hopefx_request_duration_seconds
```

Target: p99 < 200ms. If above:
1. Check Redis is running (feature cache miss adds ~200ms)
2. Check database query time
3. Check if ML model is loading on every request (should be cached in memory)

### 500 errors

```bash
# Check Sentry for the full traceback
# Or check logs
docker compose logs app | grep "500\|Internal Server Error\|Traceback"
```

---

## Diagnosing Risk Engine Issues

### Kill switch fired unexpectedly

```bash
# Check halt state
cat risk/halt_state.json

# Check risk status
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Check logs around the time it fired
docker compose logs app | grep "kill switch\|halt\|HALT"
```

The halt state file shows: timestamp, reason, and which limit was breached.

### CVaR gate blocking all orders

```bash
# Check current CVaR
curl http://localhost:8000/api/trading/risk-metrics \
  -H "Authorization: Bearer $TOKEN"

# If CVaR is too high, close some positions
curl -X DELETE http://localhost:8000/api/trading/positions \
  -H "Authorization: Bearer $TOKEN"
```

---

## Enabling Debug Mode

For deep debugging, enable structured debug logging:

```bash
# .env
LOG_LEVEL=DEBUG
SQLALCHEMY_ECHO=true
BROKER_DEBUG=true
```

Then restart and watch logs:
```bash
docker compose restart app
docker compose logs -f app | grep -E "DEBUG|signal_engine|risk|broker"
```

Disable debug mode before returning to production — it logs sensitive data.

---

## Useful One-Liners

```bash
# Count errors in last hour
docker compose logs app --since 1h | grep -c ERROR

# Find the last exception
docker compose logs app | grep -A 20 "Traceback" | tail -25

# Check all component statuses at once
curl -s http://localhost:8000/health | python3 -m json.tool

# Watch signal generation in real time
docker compose logs -f app | grep "signal\|BUY\|SELL\|NEUTRAL"

# Watch order placement in real time
docker compose logs -f app | grep "order\|fill\|TradeBlocked"

# Check kill switch state
cat risk/halt_state.json 2>/dev/null || echo "Kill switch not active"
```
