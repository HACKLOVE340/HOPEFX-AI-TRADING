# API Overview

> HOPEFX REST API — base URL: `https://your-domain.com` (or `http://localhost:8000` locally).
> All endpoints require a valid JWT unless noted. Trading endpoints also require an active subscription.
> Last updated: 2026-04-01

---

## Authentication

All requests (except `/health`, `/docs`, `/openapi.json`) require:

```
Authorization: Bearer <access_token>
```

### Get a Token

```bash
POST /api/auth/login
Content-Type: application/json

{"username": "your_user", "password": "your_pass"}
```

Response:
```json
{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 1800}
```

### Subscription Requirement

Trading, signal, ML, and backtest endpoints additionally require a valid
`HOPEFX_LICENSE_KEY` set in the server's `.env`. Without it, these endpoints
return `403 Subscription Required`.

Plan-gated endpoints return `403 Plan Limit Exceeded` with:
```json
{"error": "PLAN_LIMIT_EXCEEDED", "required_plan": "professional", "current_plan": "starter"}
```

---

## Core Endpoints

### Health & Status

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Component health check |
| GET | `/metrics` | None | Prometheus metrics |
| GET | `/api/status` | JWT | Full platform status |
| GET | `/api/status/paper-trading` | JWT | Paper trading clock |
| GET | `/api/calendar/today` | JWT | Market calendar (open/closed) |

```bash
# Health check
curl http://localhost:8000/health

# Full status
curl http://localhost:8000/api/status \
  -H "Authorization: Bearer $TOKEN"
```

---

## Authentication Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/login` | None | Get JWT token |
| POST | `/api/auth/refresh` | JWT | Refresh access token |
| POST | `/api/auth/logout` | JWT | Invalidate token |
| GET | `/api/auth/me` | JWT | Current user profile |
| POST | `/api/auth/register` | None | Create account |
| POST | `/api/auth/2fa/setup` | JWT | Generate TOTP secret (returns `provisioning_uri`) |
| POST | `/api/auth/2fa/confirm` | JWT | Activate 2FA with a valid code |
| POST | `/api/auth/2fa/disable` | JWT | Disable 2FA |
| POST | `/api/auth/change-password` | JWT | Change password (`api/settings_extended.py`) |
| POST | `/api/auth/forgot-password` | None | Request a password-reset link |
| POST | `/api/auth/reset-password` | None | Set a new password with the emailed token |
| POST | `/api/auth/logout-all` | JWT | Revoke every session |
| GET | `/api/auth/sessions` | JWT | List active sessions |
| DELETE | `/api/auth/sessions/{session_id}` | JWT | Revoke one session |
| GET | `/api/auth/verify-email` | None | Verify an email address from its link |
| POST | `/api/auth/resend-verification` | None | Re-send the verification email |
| GET | `/api/auth/csrf-token` | None | Issue the CSRF token the SPA echoes as `X-CSRF-Token` |

A second, separate TOTP implementation is mounted at `/api/2fa`
(`api/two_factor.py`): `POST /setup`, `POST /verify`, `POST /disable`,
`GET /backup-codes`, `POST /backup-codes/regenerate`, `GET /status`. Backup
codes live only on that surface. The rows above were `/2fa/enable` and
`/2fa/verify`, which exist under neither prefix — see docs/SECURITY.md.
The password rows were `/api/auth/password/change` and
`/api/auth/password/reset`, which also do not exist; the table above is now
the full set of routes `auth/router.py` registers, plus the change-password
endpoint that lives in `api/settings_extended.py`.


---

## Signal Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| GET | `/api/signals/latest` | Starter+ | Latest signal for a symbol |
| GET | `/api/signals/history` | Starter+ | Signal history (paginated) |
| GET | `/api/signals/performance` | Starter+ | Signal win rate and metrics |
| GET | `/api/signals/feed` | Professional+ | Social signal feed |
| POST | `/api/signals/subscribe` | Starter+ | Subscribe to signal alerts |

```bash
# Latest signal
curl "http://localhost:8000/api/signals/latest?symbol=XAUUSD" \
  -H "Authorization: Bearer $TOKEN"

# Signal history (last 50)
curl "http://localhost:8000/api/signals/history?symbol=XAUUSD&limit=50" \
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

---

## Trading Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| GET | `/api/trading/account` | Starter+ | Account balance and equity |
| GET | `/api/trading/positions` | Starter+ | Open positions |
| GET | `/api/trading/trades` | Starter+ | Trade history |
| GET | `/api/trading/brain-state` | Starter+ | Strategy Brain state |
| GET | `/api/trading/risk-metrics` | Starter+ | CVaR, VaR, drawdown |
| POST | `/api/trading/reconcile` | Starter+ | Trigger OMS reconciliation |
| POST | `/api/trading/emergency-stop` | Starter+ | Activate kill switch |
| DELETE | `/api/trading/positions` | Starter+ | Close all positions |

```bash
# Account info
curl http://localhost:8000/api/trading/account \
  -H "Authorization: Bearer $TOKEN"

# Risk metrics
curl http://localhost:8000/api/trading/risk-metrics \
  -H "Authorization: Bearer $TOKEN"

# Emergency stop
curl -X POST http://localhost:8000/api/trading/emergency-stop \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

---

## ML Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| GET | `/api/ml/health` | Professional+ | Model health and feature count |
| GET | `/api/ml/accuracy` | Professional+ | OOS accuracy and metadata |
| GET | `/api/ml/regime` | Professional+ | Current market regime |
| GET | `/api/ml/feature-importance` | Professional+ | Top feature importances |
| POST | `/api/ml/predict/{symbol}` | Professional+ | Run inference on latest data |
| GET | `/api/ml/fallback-status` | Professional+ | Whether fallback model is active |
| POST | `/api/ml/retrain` | Elite | Trigger model retrain |
| GET | `/api/online-learner/status` | Elite | Online learner state |
| POST | `/api/online-learner/partial-fit` | Elite | Manual partial fit |

```bash
# Model health
curl http://localhost:8000/api/ml/health \
  -H "Authorization: Bearer $TOKEN"

# Run prediction
curl -X POST http://localhost:8000/api/ml/predict/XAUUSD \
  -H "Authorization: Bearer $TOKEN"

# Feature importance
curl http://localhost:8000/api/ml/feature-importance \
  -H "Authorization: Bearer $TOKEN"
```

---

## Broker Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| GET | `/api/broker/status` | Starter+ | Broker connection status |
| POST | `/api/broker/test-connection` | Starter+ | Test broker connectivity |
| GET | `/api/broker/fix/status` | Professional+ | FIX session state (IBKR) |
| GET | `/api/broker/instruments` | Starter+ | Available instruments |
| GET | `/api/broker/spread/{symbol}` | Starter+ | Current bid/ask spread |

```bash
# Broker status
curl http://localhost:8000/api/broker/status \
  -H "Authorization: Bearer $TOKEN"

# Test connection
curl -X POST http://localhost:8000/api/broker/test-connection \
  -H "Authorization: Bearer $TOKEN"
```

---

## Backtest Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| POST | `/api/backtest/run` | Starter+ | Run a single-symbol backtest |
| POST | `/api/backtest/multi-symbol` | Professional+ | Multi-symbol backtest |
| GET | `/api/backtest/results/latest` | Starter+ | Latest backtest results |
| GET | `/api/backtest/results/{id}` | Starter+ | Specific backtest result |
| GET | `/api/backtest/history` | Starter+ | Backtest run history |

```bash
# Run backtest
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "XAUUSD",
    "strategy": "ma_crossover",
    "years": 3,
    "initial_capital": 100000
  }'

# Multi-symbol backtest
curl -X POST http://localhost:8000/api/backtest/multi-symbol \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["XAUUSD", "BTCUSD", "EURUSD"],
    "years": 10,
    "oos_frac": 0.3
  }'
```

---

## Risk Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| GET | `/api/risk/status` | Starter+ | Risk engine status |
| GET | `/api/risk/halt` | Starter+ | Kill switch state |
| DELETE | `/api/risk/halt` | Starter+ | Clear kill switch (requires token) |
| GET | `/api/risk/limits` | Starter+ | Configured risk limits |
| POST | `/api/risk/limits` | Starter+ | Update risk limits |

```bash
# Risk status
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Clear kill switch
curl -X DELETE http://localhost:8000/api/risk/halt \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

---

## Monetization Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/monetization/pricing` | JWT | All subscription tiers |
| GET | `/api/monetization/pricing/{tier}` | JWT | Specific tier details |
| POST | `/api/monetization/subscribe` | JWT | Subscribe the caller to a plan |
| GET | `/api/billing/subscription` | JWT | The caller's current subscription |
| GET | `/api/monetization/subscription/{user_id}` | JWT | Subscription — self or staff |
| GET | `/api/monetization/subscription/{user_id}/limits` | JWT | Feature limits — self or staff |
| POST | `/api/monetization/subscription/{subscription_id}/cancel` | JWT | Cancel — subscriber or staff |
| POST | `/api/monetization/license/validate` | JWT | Validate a subscription license key and report entitlements |
| POST | `/api/monetization/activate-code` | JWT | Redeem an access code onto the caller |
| GET | `/api/monetization/validate-code/{code}` | JWT | Check an access code without redeeming it |
| GET | `/api/billing/invoices` | JWT | List the caller's invoices |
| GET | `/api/billing/invoices/{invoice_id}` | JWT | Invoice detail |
| POST | `/api/monetization/affiliate/signup` | JWT | Join affiliate program |
| GET | `/api/monetization/affiliate/{user_id}` | JWT | Affiliate account — self or staff |
| POST | `/api/billing/affiliate/generate-link` | JWT | Get referral link |
| POST | `/api/monetization/webhook/stripe` | Stripe signature | Stripe event receiver |

Paths above were re-read from the routers rather than carried forward. Six rows
in the previous version of this table named routes that do not exist:
`/api/monetization/subscription/me`, `/api/monetization/invoices/{user_id}`,
`/api/monetization/invoices/{id}/pdf`, `/api/monetization/affiliate/dashboard`,
`/api/monetization/subscription/{id}/cancel` (the path parameter is
`subscription_id`), and `/api/monetization/stripe/webhook` (the real path is
`/webhook/stripe`). The pricing endpoints were also listed as `Auth: None`;
both require a JWT — an unauthenticated `GET /api/monetization/pricing`
answers 401. A doc that under-states an endpoint's auth is worse than a
missing doc, since the obvious way to "make the code match" is to remove the
dependency.

---

## Social Trading Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| GET | `/api/social/leaderboard` | Professional+ | Trader rankings |
| GET | `/api/feed/signals` | Professional+ | Social signal feed |
| POST | `/api/feed/opt-in` | Professional+ | Share your signals |
| POST | `/api/feed/opt-out` | Professional+ | Stop sharing signals |
| GET | `/api/profiles/{username}` | Professional+ | Trader profile |
| POST | `/api/profiles/{username}/follow` | Professional+ | Follow a trader |
| DELETE | `/api/profiles/{username}/follow` | Professional+ | Unfollow a trader |
| GET | `/api/profiles/{username}/signals` | Professional+ | Trader's signal history |

---

## Mobile Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| POST | `/api/mobile/register-push` | Professional+ | Register device for push |
| DELETE | `/api/mobile/register-push` | Professional+ | Unregister device |
| POST | `/api/mobile/test-push` | Professional+ | Send test notification |
| GET | `/api/mobile/push-status` | Professional+ | Push registration status |

---

## Macro & Market Data Endpoints

| Method | Path | Plan | Description |
|--------|------|------|-------------|
| GET | `/api/macro/snapshot` | Professional+ | Latest macro data (DXY, VIX, etc.) |
| GET | `/api/market-data/prices/{symbol}` | Starter+ | Current price |
| GET | `/api/market-data/ohlcv/{symbol}` | Starter+ | OHLCV bars |
| GET | `/api/market-data/history/{symbol}` | Starter+ | Historical data |

---

## Admin Endpoints

> Requires admin JWT (separate admin role).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/logs` | Application logs |
| GET | `/api/admin/subscriptions` | All subscriptions |
| POST | `/api/admin/generate-code` | Manual license key generation |
| POST | `/api/admin/promo-codes` | Create promotional code |
| GET | `/api/admin/revenue/summary` | Revenue summary |
| POST | `/api/admin/users/{id}/override-plan` | Override user plan |

---

## WebSocket Endpoints

| Path | Plan | Description |
|------|------|-------------|
| `ws://host/ws/prices?token=<jwt>` | Starter+ | Real-time price stream |
| `ws://host/ws/signals?token=<jwt>` | Starter+ | Real-time signal stream |
| `ws://host/ws/positions?token=<jwt>` | Starter+ | Real-time position updates |
| `ws://host/ws/feed?token=<jwt>` | Professional+ | Social trading feed stream |

```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/prices?token=${token}`);
ws.onmessage = (e) => {
  const { symbol, bid, ask, timestamp } = JSON.parse(e.data);
  console.log(`${symbol}: ${bid}/${ask}`);
};
```

---

## Error Responses

| Status | Code | Meaning |
|--------|------|---------|
| 400 | `VALIDATION_ERROR` | Invalid request body or parameters |
| 401 | `UNAUTHORIZED` | Missing or expired JWT |
| 403 | `SUBSCRIPTION_REQUIRED` | No valid license key |
| 403 | `PLAN_LIMIT_EXCEEDED` | Feature requires higher plan |
| 404 | `NOT_FOUND` | Resource does not exist |
| 422 | `UNPROCESSABLE_ENTITY` | Request body failed validation |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Server error (check Sentry) |

All error responses follow this format:
```json
{
  "error": "PLAN_LIMIT_EXCEEDED",
  "message": "This feature requires a Professional subscription or above.",
  "required_plan": "professional",
  "current_plan": "starter"
}
```

---

## Rate Limits

| Plan | Requests/minute | WebSocket connections |
|------|----------------|----------------------|
| Starter | 60 | 2 |
| Professional | 300 | 10 |
| Enterprise | 1,000 | 50 |
| Elite | Unlimited | Unlimited |

Rate limit headers on every response:
```
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 287
X-RateLimit-Reset: 1720000060
```

---

## Interactive Documentation

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI JSON:** `http://localhost:8000/openapi.json`

For the full endpoint reference including request/response schemas, see [API_REFERENCE.md](API_REFERENCE.md).

---

*Last updated: 2026-04-01*
