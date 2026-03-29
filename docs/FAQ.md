# FAQ

> Frequently asked questions about HOPEFX AI Trading.
> Last updated: 2026-07-14

---

## Contents

1. [Pricing & Subscriptions](#pricing--subscriptions)
2. [Getting Started](#getting-started)
3. [Trading & Signals](#trading--signals)
4. [ML & AI](#ml--ai)
5. [Brokers](#brokers)
6. [Risk Management](#risk-management)
7. [Prop Firms](#prop-firms)
8. [Technical](#technical)
9. [Licensing](#licensing)

---

## Pricing & Subscriptions

### How much does HOPEFX cost?

| Plan | Price |
|------|-------|
| Starter | $49/month |
| Pro | $149/month |
| Elite | $349/month |
| Enterprise | Custom |

Annual billing saves 2 months (pay 10, get 12). See [MONETIZATION.md](MONETIZATION.md) for the full feature comparison.

### Is there a free tier?

No. HOPEFX is a professional paid platform. There is no free tier.

If you want to evaluate the platform, request a trial access code via GitHub Issues (label: `trial-request`). Trial codes give 7 days of Pro access.

### What payment methods are accepted?

- Credit/debit card (Visa, Mastercard, Amex) via Stripe
- Crypto: BTC, ETH, USDT
- Flutterwave (Africa and emerging markets)

### Can I cancel anytime?

Yes. Cancel via `POST /api/monetization/subscription/{id}/cancel` or contact support. Cancellation takes effect at the end of the current billing period. No partial-month refunds.

### What happens to my data if I cancel?

Your trades, journal entries, and settings are retained for 90 days after cancellation. Resubscribe within 90 days to restore full access. After 90 days, data is permanently deleted.

### Can I switch plans?

Yes. Upgrading is immediate and prorated. Downgrading takes effect at the next billing cycle.

### Do you offer refunds?

No refunds for partial months. If the platform is unavailable for more than 24 hours due to our infrastructure (not your broker or internet connection), we credit the affected days.

### Is there an affiliate program?

Yes. Earn 30% recurring commission on every subscriber you refer. Sign up via `POST /api/monetization/affiliate/signup`. See [MONETIZATION.md](MONETIZATION.md) for details.

---

## Getting Started

### What are the system requirements?

- Python 3.10, 3.11, or 3.12
- 4 GB RAM minimum (8 GB recommended)
- 2 CPU cores minimum
- 10 GB storage
- Linux, macOS, or Windows

### How do I install HOPEFX?

See [INSTALLATION.md](INSTALLATION.md) for the full guide. Quick version:

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your secrets and subscription key
alembic upgrade head
uvicorn app:app --host 0.0.0.0 --port 8000
```

### How do I activate my subscription?

After subscribing, you receive a `HOPEFX_LICENSE_KEY`. Add it to `.env`:

```bash
HOPEFX_LICENSE_KEY=your_license_key_here
```

The application validates the key at startup. Without a valid key, the API returns `403 Subscription Required` on all trading endpoints.

### Do I need a broker account to start?

No. Paper trading is active by default — no broker credentials needed. You can receive signals, run backtests, and simulate trades without connecting a real broker.

To trade with real money, connect OANDA, IBKR, Alpaca, Binance, or MT5. See [SETUP_GUIDE.md](SETUP_GUIDE.md).

---

## Trading & Signals

### What markets does HOPEFX trade?

| Symbol | Market | Available From |
|--------|--------|---------------|
| XAUUSD | Gold | Starter |
| BTCUSD | Bitcoin | Pro |
| ETHUSD | Ethereum | Pro |
| EURUSD | EUR/USD Forex | Pro |
| GBPUSD | GBP/USD Forex | Pro |
| Silver | Silver | Elite |
| Oil (WTI) | Crude Oil | Elite |

### How often are signals generated?

Signals are generated on every completed H1 (1-hour) bar. The ML model abstains on ~27.5% of bars (low confidence). Expect 3–8 actionable signals per day on XAUUSD.

### What is the win rate?

The production model achieves 66.4% OOS accuracy on XAUUSD H1 (1,260 held-out bars, 7-year OOS period, p=0.0000). This translates to a win rate of approximately 57–62% in live trading after accounting for spread and slippage.

### Can I use my own strategy?

Yes, on Pro and above. Add your strategy to `strategies/` following the `BaseStrategy` interface. See [SAMPLE_STRATEGIES.md](SAMPLE_STRATEGIES.md) and [VIDEO_TUTORIALS.md](VIDEO_TUTORIALS.md) Episode 6.

### What is the "abstain" signal?

When the ML model's confidence is below the threshold (`ML_ABSTAIN_THRESHOLD`, default 0.55), it returns no signal. This is intentional — the model only acts when confident. Abstaining on uncertain bars is why the win rate exceeds 50%.

### Can I copy other traders' signals?

Yes, on Pro and above. The social trading feed shows signals from opted-in traders. You can follow traders and optionally auto-copy their trades (scaled to your account size). See [MONETIZATION.md](MONETIZATION.md) for plan details.

---

## ML & AI

### What ML model does HOPEFX use?

A calibrated XGBoost stacking ensemble (XGBoost + LightGBM + RandomForest + isotonic calibration) trained on 50 years of XAUUSD data with 176 stationary features.

OOS accuracy: **66.4%** (p=0.0000, N=1,260 bars, 7-year held-out period).

### How is the model validated?

Walk-forward validation with an expanding training window. The final 7-year period (2019–2026) is held out and never used during training or optimisation.

### Can I retrain the model on my own data?

Yes, on Elite and above:

```bash
python ml/train_advanced.py --years 50 --oos-years 3
```

See [ML_GUIDE.md](ML_GUIDE.md) for the full training guide.

### What is online learning?

The `SklearnOnlineLearner` (SGD + EWC) updates the model incrementally every hour using recent trade outcomes. Enable with `ML_HOURLY_ENABLED=true`. Available on Elite and above.

### Does the model use macro data?

Yes. DXY, VIX, US10Y, US2Y, SPX, and GLD are fetched daily from yfinance and wired into the ML inference pipeline as 22 macro cross-asset features.

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

OANDA practice account. It's free, has no minimum deposit for practice, and supports XAUUSD (gold) which is the primary instrument. See [oanda_paper_trading_setup.md](oanda_paper_trading_setup.md).

### Does HOPEFX support MT5?

Yes, on Windows only. The MT5 Python API (`MetaTrader5` package) is Windows-exclusive. On Linux/macOS, use OANDA or IBKR instead.

---

## Risk Management

### How does the kill switch work?

The kill switch immediately halts all trading and blocks new orders. It persists to `risk/halt_state.json` — it survives application restarts.

Activate:
```bash
curl -X POST http://localhost:8000/api/trading/emergency-stop \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

### What is the CVaR gate?

Before every order, the system computes Conditional Value at Risk (CVaR) for the proposed position. If adding the position would push portfolio CVaR above the configured limit, the order is blocked. This runs independently of all other risk checks — a CVaR breach always blocks.

### Can I set a daily loss limit?

Yes:
```bash
DAILY_LOSS_LIMIT_PCT=2.0    # Halt if daily loss exceeds 2% of account
MAX_DRAWDOWN_PCT=8.0        # Halt if drawdown exceeds 8%
```

When either limit is hit, the kill switch fires automatically.

### What is Kelly criterion?

Kelly criterion calculates the optimal position size based on win rate and average win/loss ratio. HOPEFX uses a fractional Kelly with a safety cap:

```bash
KELLY_FRACTION=0.25    # Use 25% of full Kelly (conservative)
MAX_POSITION_SIZE_PCT=1.0  # Hard cap: never more than 1% per trade
```

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

Pro and above. Prop firm mode is not available on Starter.

### Has anyone passed a prop firm challenge with HOPEFX?

The platform is in paper trading mode (started 2026-03-27). Live prop firm results will be published after the 30-day paper run completes and live trading is enabled.

---

## Technical

### What database does HOPEFX use?

SQLite for development (zero config), PostgreSQL for production. Switch by setting `DATABASE_URL` in `.env`.

### Does HOPEFX require Redis?

Redis is optional. Without it, the ML feature cache falls back to in-memory (slower), WebSocket pub/sub uses in-process channels, and rate limiting uses in-memory counters. For production, Redis is strongly recommended.

### How do I run the tests?

```bash
pytest tests/ -q
# Expected: 2560 passed, 0 failed
```

### What Python version is required?

Python 3.10, 3.11, or 3.12. Python 3.9 and below are not supported.

### Is there a Docker image?

Yes. Use Docker Compose for the full stack:
```bash
docker compose up -d
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full deployment guide.

### How do I report a bug?

Open a GitHub Issue with: Python version, OS, full error traceback, and reproduction steps. For security vulnerabilities, use GitHub's private vulnerability reporting — do not open a public issue.

---

## Licensing

### What license is HOPEFX under?

The source code is licensed under **AGPL-3.0**. The hosted service requires a paid subscription.

Under AGPL-3.0 you can:
- Self-host for personal trading at no cost
- Modify the code
- Distribute your modifications (source must be disclosed under AGPL-3.0)

You **cannot** under AGPL-3.0 without a Commercial License:
- Build a proprietary SaaS product on top of HOPEFX
- White-label it without disclosing source
- Sell it as part of a closed-source product

### What is the Commercial License?

The Commercial License allows proprietary use, white-labeling, and SaaS deployment without AGPL-3.0 source disclosure requirements. See [LICENSE-COMMERCIAL.md](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE-COMMERCIAL.md). Enterprise plan includes the Commercial License.

### Do I need to sign a CLA to contribute?

Yes. Before your first pull request is merged, include this statement in the PR description:

> "I have read and agree to the HOPEFX-AI-TRADING Contributor License Agreement."

The CLA enables the dual-license model (AGPL-3.0 open source + commercial). See [CONTRIBUTING.md](CONTRIBUTING.md).
