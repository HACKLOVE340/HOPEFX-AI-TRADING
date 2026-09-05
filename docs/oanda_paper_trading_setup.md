# OANDA Paper Trading Setup

> Last updated: 2026-07-14

Get HOPEFX running against a real broker API in paper (practice) mode.
No real money involved — OANDA practice accounts are free and instant.

**Important:** OANDA is used for **order execution only** (placing, cancelling, and querying positions). Live price ticks come from `NuclearStreamer` (Finnhub/Twelve Data/Polygon WebSocket feeds), not from OANDA. Set at least one streaming API key in `.env` before starting.

---

## Subscription Requirement

OANDA broker integration requires a **HOPEFX Starter subscription or above**.

| Feature | Trial | Starter | Professional | Enterprise | Elite |
|---------|-------|---------|-------------|------------|-------|
| Paper trading (no broker) | Limited | Yes | Yes | Yes | Yes |
| OANDA practice account | No | Yes | Yes | Yes | Yes |
| OANDA live account | No | Yes | Yes | Yes | Yes |
| Multi-broker (OANDA + others) | No | No | Yes (3) | Yes (unlimited) | Yes (unlimited) |

Without a valid Starter+ subscription, the `BROKER_TYPE=oanda` setting is ignored and
the app falls back to the internal paper broker. All OANDA API endpoints return
`403 Subscription Required`.

To subscribe: [hopefx.com/pricing](https://hopefx.com/pricing)
To request a trial: open a GitHub Issue with label `trial-request`

---

## Step 0 — Verify your subscription

Before connecting OANDA, confirm your HOPEFX license key is valid and your plan
includes broker access:

```bash
python scripts/manage_secrets.py validate
# Expected: ✓ HOPEFX_LICENSE_KEY: valid (plan=starter, expires=2026-08-14)

curl http://localhost:8000/api/monetization/subscription/me \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"plan": "starter", "status": "active", ...}
```

If the license key is missing or expired, set it in `.env`:
```bash
HOPEFX_LICENSE_KEY=HOPEFX-START-XXXXXXXX-XXXX
```

Then restart the app before proceeding.

---

## Step 1 — Create a free OANDA practice account

1. Go to [https://www.oanda.com/register/](https://www.oanda.com/register/)
2. Select **"Practice Account"** (not live)
3. Complete registration — no credit card required
4. Log in to the OANDA fxTrade Practice portal

---

## Step 2 — Get your API credentials

1. In the OANDA portal, click your name → **"Manage API Access"**
2. Click **"Generate"** to create a practice API token
3. Copy the token — you will not see it again
4. Note your **Account ID** (shown on the main dashboard, format: `001-001-XXXXXXX-001`)

---

## Step 3 — Configure HOPEFX

Copy `.env.example` to `.env` if you haven't already:

```bash
cp .env.example .env
```

Set these values in `.env`:

```env
# Broker (execution only)
BROKER_TYPE=oanda
OANDA_ENVIRONMENT=practice
OANDA_API_KEY=your_practice_api_token_here
OANDA_ACCOUNT_ID=001-001-XXXXXXX-001

# Optional: instruments to trade (comma-separated OANDA instrument codes)
OANDA_INSTRUMENTS=XAU_USD,EUR_USD

# Live price streaming (required — OANDA does NOT provide price ticks)
FINNHUB_API_KEY=your_finnhub_key_here   # https://finnhub.io — free tier
# TWELVE_API_KEY=                        # optional second source
# POLYGON_API_KEY=                       # optional third source

# Live trading safety gate — keep false for paper trading
LIVE_MODE_CONFIRMED=false
```

`OANDA_ENVIRONMENT=practice` routes all orders to the OANDA fxTrade Practice endpoint.
The `LIVE_MODE_CONFIRMED=false` gate blocks any accidental live order submission.

---

## Step 4 — Validate the connection

Run the built-in connection test:

```bash
python scripts/validate_oanda.py
```

Expected output:
```
✓ OANDA practice API reachable
✓ Account ID valid: 001-001-XXXXXXX-001
✓ Balance: $100,000.00 (practice)
✓ XAU_USD pricing: bid=2345.12 ask=2345.34
✓ Order placement test: PASSED (order placed and cancelled)
```

---

## Step 5 — Start paper trading

```bash
python app.py
```

The app will:
- Connect to OANDA practice API on startup
- Poll live XAU_USD prices every second
- Execute AI signals as real OANDA practice orders
- Log every order, fill, and rejection to `logs/paper_trading.log`

Monitor progress at:
- Dashboard: `http://localhost:8000/app`
- Performance: `http://localhost:8000/api/performance/public`
- Positions: `http://localhost:8000/api/trading/positions`

---

## Step 6 — Run for 30 days

Let the system run continuously for 30 days. Track:

| Metric | Target |
|--------|--------|
| Orders placed | > 0 (confirms execution pipeline works) |
| Fill rate | > 95% (confirms order routing works) |
| Execution errors | 0 (confirms no API bugs) |
| Daily loss limit triggers | Logged correctly |
| Drawdown protection | Fires at 80% / 95% / 99% thresholds |

After 30 days of clean paper trading, live trading is still not automatic. Fresh model-promotion evidence, broker reconciliation, restart recovery, security checks, conservative risk limits, and explicit operator approval must also pass. See [the live-trading gate](live_trading_gate.md).

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `403 Subscription Required` | No valid license key | Set `HOPEFX_LICENSE_KEY` in `.env` and restart |
| `403 Plan Limit Exceeded` | Plan does not include OANDA | Upgrade to Starter or above |
| `401 Unauthorized` (OANDA) | API key wrong or expired | Regenerate token in OANDA portal → Manage API Access |
| `Account not found` | Wrong account ID format | Must be `001-001-XXXXXXX-001` — copy exactly from OANDA dashboard |
| `Instrument not tradeable` | Wrong instrument code | Use `XAU_USD` not `XAUUSD` — OANDA uses underscore format |
| No price ticks | Streaming API key missing | Set `FINNHUB_API_KEY` (or `TWELVE_API_KEY`/`POLYGON_API_KEY`) — OANDA does not stream prices |
| App uses paper broker despite OANDA config | Subscription not active | Run `python scripts/manage_secrets.py validate` |
| `LIVE_MODE_CONFIRMED` error | Safety gate blocking orders | Expected for paper trading — set `LIVE_MODE_CONFIRMED=false` |

---

## Data backfill (optional but recommended)

While paper trading runs, backfill 8 years of H1 data for better ML training:

```bash
python -m data.scheduler --backfill --symbol XAU_USD --from 2015-01-01
```

This takes ~30 minutes and downloads ~70,000 H1 bars from OANDA's free
historical data API.
