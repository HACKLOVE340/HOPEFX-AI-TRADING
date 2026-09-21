# FAQ

> Frequently asked questions about HOPEFX AI Trading.
> Last updated: 2026-07-14

---

## Contents

1. [Pricing & Subscriptions](#pricing--subscriptions)
2. [Plan Features & Limits](#plan-features--limits)
3. [Getting Started](#getting-started)
4. [Trading & Signals](#trading--signals)
5. [ML & AI](#ml--ai)
6. [Brokers](#brokers)
7. [Risk Management](#risk-management)
8. [Prop Firms](#prop-firms)
9. [Performance & Backtesting](#performance--backtesting)
10. [Technical](#technical)
11. [Security](#security)
12. [Licensing](#licensing)

---

## Pricing & Subscriptions

### How much does HOPEFX cost?

| Plan | Monthly | Annual | Annual Savings |
|------|---------|--------|----------------|
| Starter | $1,800 | $18,000 | $3,600 (2 months free) |
| Professional | $4,500 | $45,000 | $9,000 (2 months free) |
| Enterprise | $7,500 | $75,000 | $15,000 (2 months free) |
| Elite | $10,000 | $100,000 | $20,000 (2 months free) |

See [MONETIZATION.md](MONETIZATION.md) for the full feature comparison and add-on pricing.

### Is there a free tier?

Yes. A permanent Free tier exists at $0/month. It is activated automatically on signup via `POST /api/billing/auth/activate-free-tier`.

Free tier limits (enforced in code):
- Paper trading only — no live broker connections
- 1 strategy maximum (MA Crossover)
- No ML features, no API access, no pattern recognition, no news integration
- 1% commission on simulated trades
- No priority support

To access live trading, ML signals, or additional strategies, upgrade to a paid plan.

### What payment methods are accepted?

- Credit/debit card (Visa, Mastercard, Amex) via Stripe
- Cryptocurrency: BTC, ETH, USDT
- PayPal Business
- Wire transfer (Enterprise and Elite — contact sales@hopefx.io)
- Flutterwave (Africa and emerging markets)

### Can I cancel anytime?

Yes. Cancel via `POST /api/monetization/subscription/{id}/cancel` or contact support. Cancellation takes effect at the end of the current billing period. Access remains active until the period ends. No partial-month refunds.

### What happens to my data if I cancel?

Trades, journal entries, and settings are retained for 90 days after cancellation. Resubscribe within 90 days to restore full access. After 90 days, all data is permanently deleted per our data retention policy.

### Can I switch plans?

Yes. Upgrading is immediate and prorated — you are charged the difference for the remaining days in the current period. Downgrading takes effect at the next billing cycle.

### Do you offer refunds?

No refunds for partial months. If the platform is unavailable for more than 24 consecutive hours due to HOPEFX infrastructure failure (not your broker, internet connection, or third-party services), we credit the affected days to your account.

### Is there an affiliate program?

Yes. Earn recurring commissions on every subscriber you refer:

| Level | Commission | Requirement |
|-------|------------|-------------|
| Bronze | 10% | Starting level |
| Silver | 15% | 10+ active referrals or $18,000 revenue |
| Gold | 20% | 25+ active referrals or $50,000 revenue |
| Platinum | 25% | 50+ active referrals or $100,000 revenue |

Sign up: `POST /api/monetization/affiliate/signup`. See [MONETIZATION.md](MONETIZATION.md) for full details.

### What is the commission rate per trade?

| Plan | Commission Rate |
|------|----------------|
| Trial | 1.0% |
| Starter | 0.5% |
| Professional | 0.3% |
| Enterprise | 0.2% |
| Elite | 0.1% |

Commission is charged on trade volume and billed monthly.

---

## Plan Features & Limits

### What does each tier include?

Values sourced directly from `monetization/pricing.py` and `strategies/manager.py`.

| Feature | Free | Starter | Professional | Enterprise | Elite |
|---------|------|---------|-------------|------------|-------|
| **Monthly price** | $0 | $1,800 | $4,500 | $7,500 | $10,000 |
| **Commission rate** | 1.0% | 0.5% | 0.3% | 0.2% | 0.1% |
| **Max strategies** | 1 | 3 | 7 | Unlimited | Unlimited |
| **Max broker connections** | 1 | 1 | 3 | Unlimited | Unlimited |
| **ML features** | No | No | Yes | Yes | Yes |
| **API access** | No | No | Yes | Yes | Yes |
| **Pattern recognition** | No | No | Yes | Yes | Yes |
| **News integration** | No | No | No | Yes | Yes |
| **Unlimited backtesting** | No | No | Yes | Yes | Yes |
| **Priority support** | No | No | Yes | Yes | Yes |
| **Custom development** | No | No | No | No | Yes |
| **Dedicated support** | No | No | No | No | Yes |
| **Live trading** | No | Yes | Yes | Yes | Yes |
| **Online learning (RL)** | No | No | No | No | Yes (`FEATURE_ONLINE_LEARNING=true`) |
| **Strategy Brain (ML consensus)** | No | No | No | No | Yes |
| **SMC/ICT strategy** | No | No | No | Yes | Yes |
| **Commercial License** | No | No | No | No | Yes |

Strategies available per tier (from `strategies/manager.py`):
- **Starter**: MA Crossover, EMA Crossover, RSI Reversal, Ichimoku
- **Professional**: + MACD, Bollinger Bands, Breakout, Mean Reversion, Stochastic
- **Enterprise**: + SMC/ICT
- **Elite**: + Strategy Brain (ML consensus)

See [MONETIZATION.md](MONETIZATION.md) for the complete feature matrix including add-ons.

### What happens when I hit a plan limit?

All plan-gated endpoints return a structured error:

```json
{
  "detail": "Plan limit exceeded",
  "error_code": "PLAN_LIMIT_EXCEEDED",
  "required_plan": "professional",
  "current_plan": "starter"
}
```

The application never silently degrades — you always know exactly which plan is required. Upgrade via `POST /api/monetization/subscribe` or at [hopefx.com/pricing](https://hopefx.com/pricing).

### What is the difference between Starter and Professional?

Starter enables paper trading with up to 3 strategies (MA Crossover, EMA Crossover, RSI Reversal, Ichimoku) and 1 broker connection. Live execution remains subject to the operational live-trading gate; ML features, API access, pattern recognition, and news integration are not included.

Professional adds ML features, API access, pattern recognition, unlimited backtesting, priority support, up to 7 strategies (adds MACD, Bollinger Bands, Breakout, Mean Reversion, Stochastic), and 3 broker connections. It is the minimum tier for algorithmic trading with ML signals.

### What does Elite add over Enterprise?

Elite adds (sourced from `monetization/pricing.py` and `strategies/manager.py`):
- **Strategy Brain** — ML consensus engine (`strategies/strategy_brain.py`), the highest-accuracy signal source
- **Online learning** — `FEATURE_ONLINE_LEARNING=true` enables `SklearnOnlineLearner` (SGD + EWC), hourly incremental updates
- **Custom development** — dedicated engineering support for bespoke integrations
- **Dedicated support** — named account manager
- **Commercial License** — build proprietary products on top of HOPEFX without AGPL-3.0 source disclosure

### How do I activate my license key after subscribing?

After payment, a `HOPEFX_LICENSE_KEY` is emailed to you. Add it to `.env`:

```bash
HOPEFX_LICENSE_KEY=HOPEFX-PRO-A7B9C2D4-X8Y2
```

Restart the application. Validate the key:

```bash
python scripts/manage_secrets.py validate
# Expected: ✓ HOPEFX_LICENSE_KEY: valid (plan=professional, expires=2026-08-14)
```

Without a valid key, all `/api/trading/`, `/api/signals/`, and `/api/ml/` endpoints return `403 Subscription Required`. The `/health` and `/docs` endpoints remain accessible.

### What happens when my subscription expires?

Trading endpoints return `403 Subscription Required` immediately on expiry. Open positions are not automatically closed — the broker holds them. You retain read-only access to your trade history and journal for 90 days.

Renew at [hopefx.com/billing](https://hopefx.com/billing) or via `POST /api/monetization/subscribe`. A new license key is issued on successful payment.

### Can I run multiple instances on one subscription?

One subscription covers one installation (one machine fingerprint). To run multiple instances (e.g., staging + production), purchase additional seats or contact sales@hopefx.io for a multi-seat arrangement.

---

## Getting Started

### What are the system requirements?

- Python 3.10, 3.11, or 3.12
- 4 GB RAM minimum (8 GB recommended for ML features)
- 2 CPU cores minimum (4 recommended)
- 10 GB storage (50 GB recommended for full historical data)
- Linux, macOS, or Windows (MT5 integration requires Windows)

### How do I install HOPEFX?

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for the full guide. Quick version:

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set SECURITY_JWT_SECRET and HOPEFX_LICENSE_KEY
alembic upgrade head
uvicorn app:app --host 0.0.0.0 --port 8000
```

### How do I activate my subscription?

After subscribing, you receive a `HOPEFX_LICENSE_KEY` by email. Add it to `.env`:

```bash
HOPEFX_LICENSE_KEY=HOPEFX-PRO-A7B9C2D4-X8Y2
```

The application validates the key at startup. Without a valid key, all trading endpoints return `403 Subscription Required`. The `/health` and `/docs` endpoints remain accessible.

Validate your key:
```bash
python scripts/manage_secrets.py validate
```

### Do I need a broker account to start?

No. Paper trading is active by default — no broker credentials needed. You can receive signals, run backtests, and simulate trades without connecting a real broker.

To trade with real money, connect OANDA, IBKR, Alpaca, Binance, or MT5. See [SETUP_GUIDE.md](SETUP_GUIDE.md).

### How do I get support?

| Plan | Support Channel | Response Time |
|------|----------------|---------------|
| Starter | Email | Business hours |
| Professional | Email + chat | 24 hours |
| Enterprise | Priority | 12 hours |
| Elite | Dedicated manager | 4 hours, 24/7 |

Email: support@hopefx.io. For security issues, use GitHub's private vulnerability reporting.

---

## Trading & Signals

### What markets does HOPEFX trade?

| Symbol | Market | Available From |
|--------|--------|---------------|
| XAUUSD | Gold | Starter |
| EURUSD | EUR/USD Forex | Professional |
| GBPUSD | GBP/USD Forex | Professional |
| BTCUSD | Bitcoin | Professional |
| ETHUSD | Ethereum | Professional |
| Silver | Silver | Enterprise |
| Oil (WTI) | Crude Oil | Enterprise |

### How often are signals generated?

Signals are generated on every completed H1 (1-hour) bar. The ML model abstains on approximately 27.5% of bars when confidence is below the threshold. Expect 3–8 actionable signals per day on XAUUSD.

### What is the win rate?

Historical OOS reports describe model performance on specific held-out datasets; they are not a live-trading win-rate guarantee. Current model promotion requires fresh metadata, feature-stability evidence, a passing Sharpe gate, and reviewed artifact promotion. Past performance does not guarantee future results. Always use proper risk management.

### Can I use my own strategy?

Yes, on Professional and above. Add your strategy to `strategies/` following the `BaseStrategy` interface. See [SAMPLE_STRATEGIES.md](SAMPLE_STRATEGIES.md) for examples and [VIDEO_TUTORIALS.md](VIDEO_TUTORIALS.md) Episode 6 for a walkthrough.

### What is the "abstain" signal?

When the ML model's confidence is below `ML_ABSTAIN_THRESHOLD` (default: 0.55), it returns no signal. This is intentional — the model only acts when confident. Abstaining on uncertain bars is a key reason the win rate exceeds 50%.

### Can I copy other traders' signals?

Yes, on Professional and above. The social trading feed shows signals from opted-in traders. You can follow traders and optionally auto-copy their trades, scaled to your account size. See [MONETIZATION.md](MONETIZATION.md) for plan details.

### What timeframes are supported?

The primary timeframe is H1 (1-hour). The ML model is trained and validated on H1 data. Additional timeframes (M15, H4, D1) are available for charting and indicator calculation but are not used for ML signal generation in the current production model.

### How are stop loss and take profit calculated?

Stop loss is placed at the nearest significant structure level (swing high/low, order block, or ATR-based). Take profit targets a minimum 1.5:1 risk-reward ratio. The exact calculation depends on the active strategy. See [SAMPLE_STRATEGIES.md](SAMPLE_STRATEGIES.md) for per-strategy details.

---

## ML & AI

### What ML model does HOPEFX use?

A calibrated XGBoost + LightGBM + RandomForest stacking ensemble trained on 50 years of XAUUSD data with 193 stationary features.

OOS accuracy: **56.5%** (p=0.0000, N=2,016 bars, 8-year held-out period, 2017–2026).

### How is the model validated?

Walk-forward validation with an expanding training window. The final 7-year period (2019–2026) is held out and never used during training or optimisation. This prevents look-ahead bias and data leakage.

### Can I retrain the model on my own data?

Yes, on Elite only:

```bash
python ml/train_advanced.py --years 50 --oos-years 3
```

See [ML_GUIDE.md](ML_GUIDE.md) for the full training guide including data requirements, feature engineering, and validation methodology.

### What is online learning?

The `SklearnOnlineLearner` (SGD + EWC) updates the model incrementally every hour using recent trade outcomes. This keeps the model current without a full retrain. Enable with `ML_HOURLY_ENABLED=true`. Available on Elite only.

### Does the model use macro data?

Yes. DXY, VIX, US10Y, US2Y, SPX, and GLD are fetched daily from yfinance and wired into the ML inference pipeline as 22 macro cross-asset features. Macro data is refreshed daily at 00:05 UTC.

### What happens if the ML model fails?

A fallback model (`xgb_macro`) activates automatically if the primary model (`advanced_oos`) fails to load or produces invalid output. The fallback uses fewer features and has lower accuracy. The Grafana dashboard shows `hopefx_ml_fallback_active = 1` when the fallback is active.

### What are the 176 features?

The feature set includes:
- **Price-derived**: OHLCV ratios, returns, log-returns (multiple lookbacks)
- **Technical indicators**: RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, CCI, Williams %R
- **Ichimoku components**: Tenkan, Kijun, Senkou A/B, Chikou
- **Order flow**: Volume profile, VWAP, delta, imbalance
- **Macro cross-asset**: DXY, VIX, US10Y, US2Y, SPX, GLD (22 features)
- **Regime**: Market regime classification (ranging/trending/volatile)
- **Calendar**: Day of week, hour of day, session (London/NY/Tokyo/Sydney)
- **SMC/ICT**: Order blocks, fair value gaps, liquidity levels

All features are stationary (differenced or normalised) to prevent non-stationarity issues.

### How do I check model health?

```bash
curl http://localhost:8000/api/ml/health \
  -H "Authorization: Bearer $TOKEN"
# {"status":"ok","feature_count":176,"model_loaded":true,"model_id":"advanced_oos"}

curl http://localhost:8000/api/ml/accuracy \
  -H "Authorization: Bearer $TOKEN"
# {"model_id":"advanced_oos","accuracy":0.664,"oos_n":1260,"gate_passed":true}
```

---

## Brokers

### Which brokers are supported?

| Broker | Type | Notes |
|--------|------|-------|
| OANDA | Forex/CFD | Practice + live, region routing (US/EU/SG) |
| Interactive Brokers | Stocks/Forex/Futures | ib_insync + FIX 4.4 |
| Alpaca | Stocks/Crypto | Paper + live |
| Binance | Crypto | Spot + futures |
| MetaTrader 5 | Forex/CFD | Windows only |
| Paper | Simulated | Default, no credentials needed |

### Do I need a funded broker account?

No. Paper trading works without any broker account. For live trading, you need a funded account with one of the supported brokers.

### Which broker do you recommend for beginners?

OANDA practice account. It is free, requires no minimum deposit for practice, and supports XAUUSD (gold) — the primary instrument. See [oanda_paper_trading_setup.md](oanda_paper_trading_setup.md).

### Does HOPEFX support MT5?

Yes, on Windows only. The MT5 Python API (`MetaTrader5` package) is Windows-exclusive. On Linux/macOS, use OANDA or IBKR instead.

### How do I validate my broker connection?

```bash
# OANDA
python scripts/validate_oanda.py

# Generic broker test
curl http://localhost:8000/api/broker/test-connection \
  -H "Authorization: Bearer $TOKEN"
```

### What is the position reconciler?

The `PositionReconciler` runs every 5 minutes and compares the OMS (Order Management System) position state against the broker's actual positions. If a mismatch is detected, it logs the discrepancy and triggers a reconciliation. This prevents ghost positions and ensures the risk engine has accurate data.

Trigger manually:
```bash
curl -X POST http://localhost:8000/api/trading/reconcile \
  -H "Authorization: Bearer $TOKEN"
```

### Can I connect multiple brokers simultaneously?

Yes, on Enterprise and Elite. Professional supports up to 3 broker accounts. Starter supports 1. Each broker account is managed by a separate `BrokerConnector` instance and can run different strategies.

---

## Risk Management

### How does the kill switch work?

The kill switch immediately halts all trading and blocks new orders. It persists to `risk/halt_state.json` and survives application restarts.

Activate:
```bash
curl -X POST http://localhost:8000/api/trading/emergency-stop \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

Deactivate (after investigating the cause):
```bash
curl -X DELETE http://localhost:8000/api/risk/halt \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

### What is the CVaR gate?

Before every order, the system computes Conditional Value at Risk (CVaR) for the proposed position. If adding the position would push portfolio CVaR above the configured limit, the order is blocked. This runs independently of all other risk checks — a CVaR breach always blocks.

Configure:
```bash
CVAR_LIMIT_PCT=2.0    # Block if portfolio CVaR exceeds 2%
```

### Can I set a daily loss limit?

Yes:
```bash
DAILY_LOSS_LIMIT_PCT=2.0    # Halt if daily loss exceeds 2% of account
MAX_DRAWDOWN_PCT=8.0        # Halt if drawdown exceeds 8%
```

When either limit is hit, the kill switch fires automatically.

### What is Kelly criterion?

Kelly criterion calculates the optimal position size based on win rate and average win/loss ratio. HOPEFX uses fractional Kelly with a hard cap:

```bash
KELLY_FRACTION=0.25        # Use 25% of full Kelly (conservative)
MAX_POSITION_SIZE_PCT=1.0  # Hard cap: never more than 1% per trade
```

### What risk checks run before every order?

In order:
1. Kill switch check — blocked if active
2. Daily loss limit check — blocked if limit reached
3. Max drawdown check — blocked if limit reached
4. CVaR gate — blocked if portfolio CVaR would exceed limit
5. Position size check — capped at `MAX_POSITION_SIZE_PCT`
6. Correlation check — blocked if new position is too correlated with existing positions
7. Market hours check — blocked if market is closed (configurable)

All checks must pass for an order to reach the broker.

---

## Prop Firms

### Does HOPEFX support prop firm challenges?

Yes. Enable prop firm mode:
```bash
PROP_FIRM_MODE=true
PROP_FIRM_NAME=ftmo
PROP_FIRM_DAILY_LOSS_LIMIT=5.0
PROP_FIRM_MAX_DRAWDOWN=10.0
PROP_FIRM_PROFIT_TARGET=10.0
```

Supported firms: FTMO, MyForexFunds, The5ers, TopStep, FundedNext. See [PROP_FIRM_GUIDE.md](PROP_FIRM_GUIDE.md).

### Which plan do I need for prop firm mode?

Any authenticated plan. The prop firm status endpoint (`GET /api/risk/prop-firm-status`) requires only a valid JWT — there is no `require_plan` gate on it. Configuration is in `prop_firm_mode.json` and applies to all live trading sessions.

### What does prop firm mode change?

When `PROP_FIRM_MODE=true`:
- Daily loss limit is enforced at the firm's threshold (not your personal setting)
- Max drawdown is enforced at the firm's threshold
- Profit target tracking is enabled
- Conservative position sizing is applied (Kelly fraction reduced to 0.15)
- Weekend holding is disabled by default (configurable per firm)
- News event trading is disabled 30 minutes before/after high-impact events

---

## Performance & Backtesting

### What backtesting data is available?

| Plan | Data Range | Symbols |
|------|-----------|---------|
| Starter | 1 year | XAUUSD |
| Professional | 10 years | All supported symbols |
| Enterprise | 50 years | All supported symbols |
| Elite | 50 years | All + custom data upload |

### How do I run a backtest?

```bash
# Single symbol, 10 years
python real_data_backtest.py --symbol XAU_USD --years 10

# Multi-symbol, 7 symbols, 10 years
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3

# With specific strategy
python real_data_backtest.py --symbol XAU_USD --years 10 --strategy smc_ict
```

See [BACKTESTING_GUIDE.md](BACKTESTING_GUIDE.md) for full documentation.

### What backtest metrics are reported?

- Total return (%)
- Annualised return (%)
- Sharpe ratio
- Sortino ratio
- Max drawdown (%)
- Win rate (%)
- Profit factor
- Average win / average loss
- Number of trades
- OOS accuracy (for ML strategies)

### Is the backtest walk-forward validated?

Yes. The default backtest uses walk-forward validation with an expanding training window. The `--oos-frac` parameter controls the held-out fraction (default: 0.3 = 30% OOS).

### What is the multi-symbol backtest result?

The multi-symbol backtest across 7 symbols (XAUUSD, BTCUSD, ETHUSD, EURUSD, GBPUSD, Silver, Oil) over 10 years with 30% OOS shows N=919 OOS bars with statistically significant results (p < 0.01). Full results: `GET /api/backtest/results/latest`.

---

## Technical

### What database does HOPEFX use?

SQLite for development (zero config), PostgreSQL for production. Switch by setting `DATABASE_URL` in `.env`.

```bash
# Development (automatic)
# No DATABASE_URL needed — creates hopefx.db automatically

# Production
DATABASE_URL=postgresql://user:pass@localhost:5432/hopefx_db
```

### Does HOPEFX require Redis?

Redis is optional. Without it:
- ML feature cache falls back to in-memory (slower, ~200ms added per request)
- WebSocket pub/sub uses in-process channels (no multi-process support)
- Rate limiting uses in-memory counters (resets on restart)

For production, Redis is strongly recommended:
```bash
REDIS_URL=redis://localhost:6379/0
```

### How do I run the tests?

```bash
# Fast suite (skips slow ML training tests)
pytest tests/ -m "not slow" -q

# Full suite
pytest tests/ -q
# Expected: 2,560 passed, 0 failed

# With coverage
pytest tests/ --cov=. --cov-report=html -q
```

### What Python version is required?

Python 3.10, 3.11, or 3.12. Python 3.9 and below are not supported.

### Is there a Docker image?

Yes. Use Docker Compose for the full stack (app + PostgreSQL + Redis + Prometheus + Grafana):
```bash
docker compose up -d
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full deployment guide including Kubernetes/Helm.

### How do I report a bug?

Open a GitHub Issue with: Python version, OS, full error traceback, and reproduction steps. For security vulnerabilities, use GitHub's private vulnerability reporting — do not open a public issue.

### What is the API rate limit?

| Plan | Requests/minute | WebSocket connections |
|------|----------------|----------------------|
| Starter | 60 | 2 |
| Professional | 300 | 10 |
| Enterprise | 1,000 | 50 |
| Elite | Unlimited | Unlimited |

Rate limit headers are included in every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

### How do I access the API documentation?

Interactive API docs (Swagger UI): `http://localhost:8000/docs`
ReDoc: `http://localhost:8000/redoc`
OpenAPI JSON: `http://localhost:8000/openapi.json`

Full API reference: [API_REFERENCE.md](API_REFERENCE.md).

---

## Security

### How are API keys stored?

API keys (broker tokens, Stripe keys, etc.) are stored encrypted in the database using AES-256. The encryption key is derived from `CONFIG_ENCRYPTION_KEY` in `.env`. Keys are never logged or returned in API responses.

### How are JWTs signed?

JWTs are signed with HS256 using `SECURITY_JWT_SECRET`. Tokens expire after 24 hours by default (configurable via `JWT_EXPIRY_HOURS`). Refresh tokens are supported for mobile clients.

### Is there two-factor authentication?

TOTP-based 2FA is available on Professional and above. Enrol via `POST /api/2fa/setup` then `POST /api/2fa/verify` (or `POST /api/auth/2fa/setup` then `/confirm` on the other surface). Required for admin accounts.

Note that 2FA today gates the `/2fa/*` endpoints; there is **no** second-factor challenge on password login. See the 2FA section of docs/SECURITY.md.

### How is the kill switch token protected?

The kill switch token (`HOPEFX_KILL_SWITCH_TOKEN`) is required in the `X-Kill-Switch-Token` header for all kill switch operations. It is separate from the JWT to prevent a compromised user token from triggering an emergency stop.

### What security scanning is in place?

- **bandit**: Static analysis for Python security issues (runs in CI)
- **pip-audit**: Dependency vulnerability scanning (runs in CI)
- **Codacy**: Continuous code quality and security analysis
- **Sentry**: Runtime error tracking and alerting
- **Rate limiting**: All endpoints rate-limited per plan

---

## Licensing

### What license is HOPEFX under?

The source code is licensed under **AGPL-3.0**. The hosted service requires a paid subscription.

Under AGPL-3.0 you can:
- Self-host for personal trading
- Modify the code
- Distribute your modifications (source must be disclosed under AGPL-3.0)

You **cannot** under AGPL-3.0 without a Commercial License:
- Build a proprietary SaaS product on top of HOPEFX
- White-label it without disclosing source
- Sell it as part of a closed-source product

### What is the Commercial License?

The Commercial License allows proprietary use, white-labeling, and SaaS deployment without AGPL-3.0 source disclosure requirements. See [LICENSE-COMMERCIAL.md](../LICENSE-COMMERCIAL.md). The Elite plan includes the Commercial License.

### Do I need to sign a CLA to contribute?

Yes. Before your first pull request is merged, include this statement in the PR description:

> "I have read and agree to the HOPEFX-AI-TRADING Contributor License Agreement."

The CLA enables the dual-license model (AGPL-3.0 open source + commercial). See [CONTRIBUTING.md](CONTRIBUTING.md) and [CLA.md](../CLA.md).

### Can I self-host without a subscription?

Under AGPL-3.0, you can self-host for personal trading without a subscription. However, the hosted service, support, ML model updates, and commercial features require a paid subscription.

Self-hosting without a subscription key disables all trading endpoints. The application starts but returns `403 Subscription Required` on all `/api/trading/`, `/api/signals/`, and `/api/ml/` endpoints.

---

*Last updated: 2026-07-14*
