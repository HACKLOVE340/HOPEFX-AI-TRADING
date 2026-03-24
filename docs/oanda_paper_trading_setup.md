# OANDA Paper Trading Setup

Get HOPEFX running against a real broker API in paper (practice) mode.
No real money involved — OANDA practice accounts are free and instant.

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
# Broker
BROKER_TYPE=oanda
OANDA_PRACTICE=true

# OANDA credentials (practice)
OANDA_API_KEY=your_practice_api_token_here
OANDA_ACCOUNT_ID=001-001-XXXXXXX-001

# Optional: instruments to trade (comma-separated OANDA codes)
OANDA_INSTRUMENTS=XAU_USD,EUR_USD
```

Leave `OANDA_PRACTICE=true` — this ensures all orders go to the practice
environment, not live markets.

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

After 30 days of clean paper trading with zero execution failures,
you can enable live trading (Task 22).

---

## Troubleshooting

**`401 Unauthorized`** — API token is wrong or expired. Regenerate in OANDA portal.

**`Account not found`** — Account ID format must be `001-001-XXXXXXX-001`.
Copy it exactly from the OANDA dashboard.

**`Instrument not tradeable`** — Use OANDA instrument codes: `XAU_USD` not `XAUUSD`.
Full list: [https://developer.oanda.com/rest-live-v20/instrument-ep/](https://developer.oanda.com/rest-live-v20/instrument-ep/)

**No prices updating** — Check `BROKER_OANDA_TOKEN` and `BROKER_OANDA_ACCOUNT`
are set (the app also reads these aliases). Both env var names work.

---

## Data backfill (optional but recommended)

While paper trading runs, backfill 8 years of H1 data for better ML training:

```bash
python -m data.scheduler --backfill --symbol XAU_USD --from 2015-01-01
```

This takes ~30 minutes and downloads ~70,000 H1 bars from OANDA's free
historical data API.
