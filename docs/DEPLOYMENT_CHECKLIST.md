# Deployment Checklist

Use this checklist before every production deployment. Items marked ❌ are blockers — do not deploy without resolving them.

---

## Pre-Deployment

### Secrets & Configuration
- [ ] `SECURITY_JWT_SECRET` set to a 48-char random value (not `CHANGE_ME`)
- [ ] `CONFIG_ENCRYPTION_KEY` set to a 48-char random value
- [ ] `HOPEFX_KILL_SWITCH_TOKEN` set to a 48-char random value
- [ ] `DATABASE_URL` points to production PostgreSQL (not SQLite)
- [ ] `REDIS_URL` points to production Redis
- [ ] `ALLOWED_ORIGINS` set to explicit https:// domain(s) — **not `*`**
- [ ] `APP_ENV=production`
- [ ] `SENTRY_DSN` set (error tracking)
- [ ] `TRUSTED_PROXY_IPS` set to your load balancer IPs

Validate all secrets:
```bash
python scripts/manage_secrets.py validate
```

### Database
- [ ] Alembic migrations applied: `alembic upgrade head`
- [ ] `alembic current` shows latest revision (`f1a2b3c4d5e6`)
- [ ] Database backup taken before migration

### Tests
- [ ] Full test suite passes: `python -m pytest tests/ -q`
- [ ] Zero failures (skips for optional deps are acceptable)
- [ ] Coverage ≥ 70%: `python -m pytest tests/ --cov --cov-fail-under=70`

### Security Scan
- [ ] TruffleHog: no secrets in git history
- [ ] bandit: no HIGH severity issues in `api/ auth/ brokers/ ml/ risk/`
- [ ] pip-audit: no known CVEs in dependencies

---

## Deployment

### Docker Compose
```bash
docker compose pull
docker compose up -d --no-deps --build app
docker compose logs -f app   # watch for startup errors
```

### Kubernetes (Helm)
```bash
helm upgrade hopefx helm/hopefx/ \
  --set image.tag=<new-tag> \
  --atomic \
  --timeout 5m
kubectl rollout status deployment/hopefx
```

### Health Check
```bash
curl https://your-domain.com/health
# Expected: {"status":"healthy","environment":"production",...}
```

All components should show `healthy`. `email` showing `unavailable` is acceptable if SendGrid is not configured.

---

## Post-Deployment

### Smoke Tests
```bash
# Health
curl https://your-domain.com/health

# ML endpoint
curl https://your-domain.com/api/ml/accuracy

# Auth (should return 401 without token)
curl https://your-domain.com/api/auth/me

# Metrics (Prometheus)
curl https://your-domain.com/metrics | grep hopefx_
```

### Monitoring
- [ ] Grafana dashboards loading (http://your-grafana:3000)
- [ ] Prometheus scraping `/metrics` endpoint
- [ ] Sentry receiving events (trigger a test error)
- [ ] Discord bot posting to alerts channel

### Broker Validation (if BROKER_TYPE=oanda)
```bash
python scripts/validate_oanda.py
```

---

## Rollback

If the deployment fails health checks:

```bash
# Docker Compose
docker compose up -d --no-deps app=<previous-image-tag>

# Kubernetes
helm rollback hopefx
```

If database migrations need reverting:
```bash
alembic downgrade -1   # revert one migration
```

---

## Live Trading Gate

**Do not enable `FEATURE_LIVE_TRADING=true` until:**

1. ✅ 30 days of OANDA paper trading completed (`data/oanda_paper_start.json` records the start date)
2. ✅ Zero execution errors in paper trading logs
3. ✅ Risk limits configured conservatively (start at 1% per trade, 5% max drawdown)

Check gate status:
```bash
python scripts/enable_live_trading.py --check-only
```

---

*Last updated: 2026-05-30 (V15)*
