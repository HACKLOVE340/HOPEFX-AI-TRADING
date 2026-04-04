# API Reference

> Base URL: `http://localhost:8000` (development) | `https://yourdomain.com` (production)
> Interactive docs: `/docs` (Swagger UI) | `/redoc` (ReDoc)
> Last updated: 2026-07-14

All endpoints except `/health`, `/docs`, `/openapi.json`, and `/redoc`
require a valid JWT in the `Authorization: Bearer <token>` header.

All trading, signal, and ML endpoints additionally require an active HOPEFX subscription.
Requests without a valid subscription return `403 Subscription Required`.

---

## Endpoint Groups

| Group | Prefix | Description |
|-------|--------|-------------|
| [Authentication](#authentication) | `/api/auth/` | Login, token refresh, logout, user profile |
| [Two-Factor Auth](#two-factor-authentication) | `/api/2fa/` | TOTP setup, verify, backup codes |
| [Signals](#signals) | `/api/signals/` | Latest signal, history, performance |
| [ML Models](#ml-models) | `/api/ml/` | Accuracy, predict, health, regime, retrain |
| [Online Learner](#online-learner) | `/api/online-learner/` | Status, partial-fit, reset |
| [Trading](#trading) | `/api/trading/` | Orders, positions, account, brain state, kill switch |
| [Advanced Trading](#advanced-trading) | `/api/ab-test/`, `/api/indicators/`, `/api/correlation/`, `/api/cot/`, `/api/backtest/` | A/B tests, custom indicators, correlation, Monte Carlo |
| [Broker](#broker) | `/api/broker/` | Connection test, status, accounts, switch |
| [Backtesting](#backtesting) | `/api/backtest/` | Run, walk-forward, results, multi-symbol |
| [Risk / Prop Firm](#risk--prop-firm) | `/api/risk/` | Risk status, drawdown, CVaR |
| [Alerts](#alerts) | `/api/alerts/` | Create, list, pause, resume, trigger history |
| [Economic Calendar](#economic-calendar) | `/api/calendar/` | Events, auto-pause, FOMC regime |
| [Macro Data](#macro-data) | `/api/macro/` | Snapshot, history, features, gold signal |
| [Watchlist](#watchlist) | `/api/watchlist/` | Add, remove, prices |
| [Social Feed](#social-feed) | `/api/feed/`, `/api/social/` | Signal feed, reactions, leaderboard |
| [Profiles](#profiles) | `/api/profiles/` | Trader profiles, follow, signal history |
| [Performance](#performance) | `/api/performance/` | Summary, equity curve |
| [Trade Journal](#trade-journal) | `/api/journal/` | Entries, stats, mistakes |
| [Payments](#payments) | `/api/payments/` | Crypto address, status, rates |
| [Monetization](#monetization) | `/api/monetization/` | Pricing, subscribe, subscription, activate code |
| [Billing](#billing) | `/api/billing/` | Subscription, Stripe webhook, Flutterwave, affiliate |
| [Mobile](#mobile) | `/api/mobile/` | Push registration, test push, status |
| [AI Brain](#ai-brain) | `/api/brain/` | Generate strategy, deploy strategy |
| [AI Chat](#ai-chat) | `/api/chat/` | Message, history, status |
| [Explainability](#explainability) | `/api/explain/` | SHAP signal explanation, global feature importance |
| [Settings](#settings) | `/api/settings/` | Notification settings |
| [Admin](#admin) | `/api/admin/` | Dashboard, logs, KYC, activity |
| [Status](#status) | `/health`, `/api/status/` | Health check, paper trading clock, Sharpe progress |
| [WebSocket](#websocket) | `/ws/` | Signals, prices, positions, alerts |

---

## Authentication

### POST /api/auth/login
Authenticate and receive a JWT access token.

**Request:**
```json
{ "username": "admin", "password": "your_password" }
```
**Response:**
```json
{ "access_token": "eyJ...", "token_type": "bearer", "expires_in": 1800 }
```

### POST /api/auth/refresh
Refresh an expired access token using a refresh token.

### POST /api/auth/logout
Invalidate the current token.

### GET /api/auth/me
Return the authenticated user's profile.

---

## Two-Factor Authentication

### POST /api/2fa/setup
Generate a TOTP secret and QR code URI.

### POST /api/2fa/verify
Verify a TOTP code and enable 2FA.

### POST /api/2fa/disable
Disable 2FA (requires current TOTP code).

### GET /api/2fa/backup-codes
Return one-time backup codes.

### GET /api/2fa/status
Return whether 2FA is enabled for the current user.

---

## Signals

### GET /api/signals/latest
Get the latest signal for a symbol.

**Query params:** `symbol` (default: `XAUUSD`)

**Response:**
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

### GET /api/signals/history
Get historical signals.

**Query params:** `symbol`, `limit` (default: 100), `from_ts`, `to_ts`

### POST /api/signals/subscribe
Subscribe to real-time signals via WebSocket channel.

### GET /api/signals/performance
Signal performance metrics (win rate, avg R/R, accuracy).

---

## ML Models

### GET /api/ml/accuracy
Return OOS accuracy and metadata for the loaded model.

**Response:**
```json
{
  "model_id": "advanced_oos",
  "accuracy": 0.664,
  "oos_period_start": "2019-04-12",
  "oos_period_end": "2026-03-24",
  "oos_bars": 1260,
  "p_value": 0.0,
  "features": 176,
  "ci_mode": false
}
```

### GET /api/ml/models
List all loaded models and their status (production / fallback).

### POST /api/ml/predict/{symbol}
Run ML inference for a symbol.

**Path param:** `symbol` (e.g., `XAUUSD`)

**Response:**
```json
{
  "symbol": "XAUUSD",
  "probability_up": 0.68,
  "direction": "BUY",
  "abstain": false,
  "model_id": "advanced_oos",
  "features_used": 176
}
```

### GET /api/ml/health
ML subsystem health: model loaded, macro store populated, feature cache status.

### GET /api/ml/feature-importance
Top feature importances from the production model.

### GET /api/ml/regime
Current market regime (trending / ranging / volatile).

### POST /api/ml/retrain
Trigger a model retrain (admin only). Runs `ml/train_advanced.py` asynchronously.

---

## Online Learner

### GET /api/online-learner/status
Return online learner state: last update time, samples seen, current accuracy.

### POST /api/online-learner/partial-fit
Submit a labelled sample for incremental learning.

**Request:**
```json
{ "symbol": "XAUUSD", "features": {...}, "label": 1 }
```

### GET /api/online-learner/accuracy
Online learner rolling accuracy (last 100 predictions).

### POST /api/online-learner/reset
Reset the online learner to the base model state (admin only).

---

## Trading

### POST /api/trading/order
Place a market order.

**Request:**
```json
{
  "symbol": "XAUUSD",
  "side": "buy",
  "units": 1000,
  "stop_loss": 2330.00,
  "take_profit": 2375.00
}
```

### GET /api/trading/positions
List all open positions.

### DELETE /api/trading/positions/{position_id}
Close a specific position.

### DELETE /api/trading/positions
Close all open positions.

### GET /api/trading/account
Get broker account snapshot (balance, equity, margin).

### GET /api/trading/trades
Get trade history.

### GET /api/trading/trades/export
Export trade history as CSV.

### GET /api/trading/brain-state
Get the current HOPEFXBrain state (active strategies, consensus, regime).

### POST /api/trading/emergency-stop
Activate the kill switch — halts all trading immediately.

### GET /api/trading/market-data/{symbol}
Get current OHLCV data for a symbol.

### GET /api/trading/regime
Get current market regime analysis.

### GET /api/trading/risk-metrics
Get current risk metrics (VaR, CVaR, drawdown, exposure).

---

## Advanced Trading

### POST /api/ab-test/start
Start an A/B test between two strategies.

### GET /api/ab-test
List all A/B tests.

### GET /api/ab-test/{test_id}
Get A/B test results.

### POST /api/backtest/{run_id}/share
Share a backtest result (generates a public slug).

### GET /api/backtest/shared/{slug}
Get a shared backtest result by slug.

### POST /api/indicators/preview
Preview a custom indicator on historical data.

### GET /api/indicators
List saved custom indicators.

### POST /api/indicators
Save a custom indicator.

### DELETE /api/indicators/{ind_id}
Delete a custom indicator.

### GET /api/correlation
Get cross-asset correlation matrix.

### GET /api/cot/gold
Get COT (Commitment of Traders) proxy data for gold.

### POST /api/backtest/{run_id}/monte-carlo
Run Monte Carlo simulation on a backtest result.

### GET /api/backtest/{run_id}/monte-carlo
Get Monte Carlo simulation results.

---

## Broker

### POST /api/broker/test-connection
Test broker connectivity with current credentials.

### GET /api/broker/status
Current broker connection status, balance, and data feed health.

### GET /api/broker/accounts
List all configured broker accounts.

### POST /api/broker/switch
Switch the active broker.

---

## Backtesting

### GET /api/backtest/strategies
List available strategies for backtesting.

### POST /api/backtest/run
Run a backtest.

**Request:**
```json
{
  "symbol": "XAUUSD",
  "strategy": "ma_crossover",
  "years": 5,
  "initial_capital": 100000,
  "commission_bps": 35,
  "slippage_bps": 5
}
```

### GET /api/backtest/walk-forward/latest
Get the latest walk-forward validation results.

### GET /api/backtest/walk-forward/{run_id}
Get walk-forward results for a specific run.

### GET /api/backtest/results
List all backtest results.

### GET /api/backtest/results/{run_id}
Get a specific backtest result.

### GET /api/backtest/multi-symbol
Get multi-symbol backtest results (XAU+BTC+ETH+EUR/USD+GBP/USD+Silver+Oil).

### POST /api/backtest/multi-symbol
Run a new multi-symbol backtest.

---

## Risk / Prop Firm

### GET /api/risk/status
Current risk status: drawdown, daily loss, CVaR, kill switch state.

---

## Alerts

### POST /api/alerts/
Create a new alert.

**Request:**
```json
{
  "symbol": "XAUUSD",
  "condition": "price_above",
  "threshold": 2400.00,
  "channels": ["discord", "telegram", "email"]
}
```

### GET /api/alerts/
List all alerts for the current user.

### GET /api/alerts/history/triggers
Get alert trigger history.

### GET /api/alerts/active
List currently active (untriggered) alerts.

### GET /api/alerts/{alert_id}
Get a specific alert.

### DELETE /api/alerts/{alert_id}
Delete an alert.

### POST /api/alerts/{alert_id}/pause
Pause an alert.

### POST /api/alerts/{alert_id}/resume
Resume a paused alert.

---

## Economic Calendar

### GET /api/calendar/upcoming
Get upcoming economic events.

**Query params:** `days` (default: 7), `impact` (low/medium/high)

### GET /api/calendar/today
Get today's economic events.

### GET /api/calendar/high-impact
Get high-impact events for the next 7 days.

### POST /api/calendar/auto-pause
Configure auto-pause trading around high-impact events.

### GET /api/calendar/auto-pause
Get current auto-pause configuration.

### GET /api/calendar/fomc
Get upcoming FOMC meeting dates.

### POST /api/calendar/fomc/regime
Set FOMC regime mode (risk-on / risk-off).

### GET /api/calendar/fomc/regime
Get current FOMC regime status.

### DELETE /api/calendar/fomc/regime
Clear FOMC regime override.

---

## Macro Data

### GET /api/macro/snapshot
Current macro snapshot: DXY, VIX, US10Y, US2Y, SPX, GLD.

### GET /api/macro/history
Historical macro data for a series.

**Query params:** `series` (dxy/vix/us10y/us2y/spx/gld), `days` (default: 90)

### GET /api/macro/features
Macro features formatted for ML inference.

### GET /api/macro/gold-signal
Geopolitical gold signal from World Monitor integration.

### POST /api/macro/store/update
Upsert a macro observation into MacroStore.

---

## Watchlist

All watchlist endpoints require JWT auth.

### GET /api/watchlist
Get the current user's watchlist.

### POST /api/watchlist/{symbol}
Add a symbol to the watchlist.

### DELETE /api/watchlist/{symbol}
Remove a symbol from the watchlist.

### GET /api/watchlist/prices
Get current prices for all watchlist symbols.

---

## Social Feed

### GET /api/feed
Get the social signal feed (signals shared by opted-in users).

### POST /api/feed/{signal_id}/react
React to a signal (like/dislike).

### POST /api/feed/{signal_id}/comment
Comment on a signal.

### GET /api/feed/{signal_id}/comments
Get comments on a signal.

### POST /api/feed/opt-in
Opt in to sharing your signals on the social feed.

### POST /api/feed/opt-out
Opt out of the social feed.

### GET /api/feed/status/me
Get your social feed opt-in status.

### GET /api/feed/status
Get global social feed statistics.

### GET /api/social/leaderboard
Get the trader leaderboard (win rate, Sharpe, total return).

---

## Profiles

### GET /api/profiles/me
Get the current user's profile.

### PUT /api/profiles/me
Update the current user's profile.

### GET /api/profiles/{trader_id}
Get a trader's public profile.

### GET /api/profiles/{trader_id}/signals
Get a trader's public signal history.

### POST /api/profiles/{trader_id}/follow
Follow a trader.

### DELETE /api/profiles/{trader_id}/follow
Unfollow a trader.

---

## Performance

### GET /api/performance/summary
Performance summary: total return, Sharpe, win rate, max drawdown.

### GET /api/performance/equity-curve
Equity curve data points for charting.

---

## Trade Journal

### GET /api/journal/trades
Get journal entries.

**Query params:** `limit`, `offset`, `symbol`, `from_date`, `to_date`

### POST /api/journal/trades
Add a journal entry with notes and tags.

### GET /api/journal/trades/{trade_id}
Get a specific journal entry.

### PATCH /api/journal/trades/{trade_id}
Update a journal entry (add notes, tags, rating).

### GET /api/journal/stats
Journal statistics: most common mistakes, best/worst setups.

### GET /api/journal/mistakes
Get trades tagged as mistakes.

---

## Payments

### POST /api/payments/crypto/address
Generate a crypto payment address (BTC/ETH/USDT).

**Request:**
```json
{ "currency": "USDT", "amount": 99.00, "plan": "pro" }
```

### GET /api/payments/crypto/status/{payment_id}
Check payment status.

### GET /api/payments/crypto/rates
Get current crypto exchange rates.

---

## Monetization

### GET /api/monetization/pricing
List all pricing tiers.

### GET /api/monetization/pricing/{tier}
Get details for a specific tier (free/starter/pro/enterprise).

### POST /api/monetization/subscribe
Subscribe to a plan.

### GET /api/monetization/subscription/{user_id}
Get subscription status.

### POST /api/monetization/subscription/{subscription_id}/cancel
Cancel a subscription.

### GET /api/monetization/subscription/{user_id}/limits
Get feature limits for the current subscription.

### POST /api/monetization/activate-code
Activate an access code.

### GET /api/monetization/validate-code/{code}
Validate an access code without activating it.

### POST /api/monetization/affiliate/signup
Sign up as an affiliate.

---

## Billing

### GET /api/billing/subscription
Get current subscription and billing details.

### POST /api/billing/webhook/stripe
Stripe webhook endpoint (for Stripe to call — not for direct use).

### POST /api/billing/affiliate/generate-link
Generate an affiliate referral link.

### POST /api/billing/auth/activate-free-tier
Activate the free tier for a new user.

### POST /api/billing/payments/flutterwave/init
Initialize a Flutterwave payment.

### POST /api/billing/payments/flutterwave/verify
Verify a Flutterwave payment.

### GET /api/billing/payments/flutterwave/status
Get Flutterwave payment status.

---

## Mobile

### POST /api/mobile/register-push
Register a device for push notifications.

**Request:**
```json
{ "device_token": "fcm_token_here", "platform": "android" }
```

### DELETE /api/mobile/register-push
Unregister a device from push notifications.

### POST /api/mobile/test-push
Send a test push notification to the current device.

### GET /api/mobile/push-status
Get push notification registration status.

---

## AI Brain

### POST /api/brain/generate-strategy
Generate a new trading strategy using AI.

**Request:**
```json
{ "description": "A mean reversion strategy for gold using RSI and Bollinger Bands" }
```

### POST /api/brain/deploy-strategy
Deploy a generated strategy to the live engine.

---

## AI Chat

### POST /api/chat/message
Send a message to the AI trading assistant.

**Request:**
```json
{ "message": "What is the current gold trend?", "session_id": "abc123" }
```

### DELETE /api/chat/history
Clear conversation history for a session.

### GET /api/chat/status
AI chat readiness check (model loaded, API key configured).

---

## Explainability

### GET /api/explain/signal/{signal_id}
Get SHAP explanation for a specific signal.

### GET /api/explain/model
Get global model feature importance with SHAP values.

---

## Settings

### POST /api/settings/notifications
Save notification settings (channels, thresholds, quiet hours).

### GET /api/settings/notifications
Get current notification settings.

### POST /api/notifications/test
Send a test notification to all configured channels.

---

## Admin

### GET /api/admin/
Admin dashboard (HTML).

### GET /api/admin/strategies
Strategy management page (HTML).

### GET /api/admin/settings
Settings page (HTML).

### GET /api/admin/monitoring
Monitoring page (HTML).

### GET /api/admin/logs
Get application logs.

### POST /api/admin/kyc/decide
Approve or reject a KYC submission.

### GET /api/admin/kyc/pending
List pending KYC submissions.

### GET /api/admin/kyc/{user_id}
Get KYC status for a user.

### GET /api/admin/activity
Get recent user activity.

### GET /api/admin/dashboard-data
Get admin dashboard metrics (users, revenue, trades).

---

## Status

### GET /health
Health check — returns status of all components.

**Response:**
```json
{
  "status": "healthy",
  "environment": "production",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "ml_model": "healthy",
    "broker": "oanda_practice"
  }
}
```

### GET /api/status/paper-trading
Paper trading clock status.

**Response:**
```json
{
  "elapsed_days": 12,
  "remaining_days": 18,
  "complete": false,
  "started_at": "2026-03-27T00:00:00Z"
}
```

### GET /api/status/sharpe-progress
Sharpe gate progress (N trades accumulated vs target).

### GET /metrics
Prometheus metrics endpoint.

---

## WebSocket

### WS /ws/signals
Real-time signal stream.

**Message format:**
```json
{
  "type": "signal",
  "symbol": "XAUUSD",
  "direction": "BUY",
  "confidence": 0.72,
  "timestamp": "2026-07-14T10:30:00Z"
}
```

### WS /ws/prices
Real-time price tick stream.

### WS /ws/positions
Real-time position update stream.

### WS /ws/alerts
Real-time alert trigger stream.

---

## Error Responses

All errors follow this format:

```json
{
  "detail": "Human-readable error message",
  "error_code": "MACHINE_READABLE_CODE",
  "timestamp": "2026-07-14T10:30:00Z"
}
```

| HTTP Status | Meaning |
|-------------|---------|
| 400 | Bad request — invalid parameters |
| 401 | Unauthorized — missing or invalid JWT |
| 403 | Forbidden — insufficient permissions |
| 404 | Not found |
| 422 | Validation error — request body schema mismatch |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Service unavailable — broker disconnected or kill switch active |

---

## Rate Limits

| Endpoint Group | Limit |
|----------------|-------|
| Unauthenticated | 100 req/min |
| Authenticated | 1,000 req/min |
| Order placement (`/api/trading/order`) | 10 req/min |
| ML inference (`/api/ml/predict`) | 30 req/min |
| Backtest runs (`/api/backtest/run`) | 5 req/min |

Rate limit headers on every response:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 987
X-RateLimit-Reset: 1720000060
```
