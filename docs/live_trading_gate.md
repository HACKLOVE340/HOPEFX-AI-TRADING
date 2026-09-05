# Live Trading Gate — 30-Day Paper Trade Requirement

!!! warning "This is one required gate, not the only readiness check"
    A live-trading decision also depends on successful model retraining,
    reviewed model promotion, broker reconciliation, restart recovery, and
    end-to-end execution tests. The 30-day paper-trading period is required,
    but it cannot substitute for those technical and operational controls.

---

## Why this gate exists

`scripts/enable_live_trading.py` will refuse to activate live execution until:

1. Paper trading has been running for **≥ 30 days** (checked via log timestamps)
2. **Zero execution errors** appear in paper trading logs
3. OANDA credentials are set and pass live validation
4. Risk limits (`MAX_POSITION_SIZE_PCT`, `MAX_DRAWDOWN_PCT`, `DAILY_LOSS_LIMIT_PCT`) are configured
5. You **type a confirmation phrase** — the script will not proceed silently

This is intentional. Deploying an algorithmic trading system to a live account
without a validated paper trading period is how accounts get blown up.

---

## Step 1 — Create a free OANDA practice account

1. Go to [https://www.oanda.com/register/](https://www.oanda.com/register/)
2. Select **"Practice Account"** (free, instant, no real money)
3. From the dashboard: **Manage API Access → Generate Token**
4. Copy your **API token** and **Account ID**

---

## Step 2 — Configure credentials

```bash
# .env
OANDA_API_KEY=your_practice_api_token
OANDA_ACCOUNT_ID=001-001-XXXXXXX-001
OANDA_ENVIRONMENT=practice
```

---

## Step 3 — Validate connectivity

```bash
python scripts/validate_oanda.py
```

Expected output:

```
OANDA practice API validation
========================================
✓ API key present
✓ Account reachable: balance $100,000.00
✓ XAU_USD pricing available: bid=2048.12 ask=2048.34
✓ Test order placed and cancelled
All checks passed — ready for paper trading.
```

If any check fails, see [DEBUGGING.md](DEBUGGING.md) for OANDA-specific troubleshooting.

---

## Step 4 — Start paper trading

```bash
# Unified paper-trading entry point; keep the broker explicit.
python run.py --broker oanda --mode paper
```

The application logs a `paper_trading_started_at` timestamp on first run.
`enable_live_trading.py` reads this timestamp to enforce the 30-day gate.

**Leave it running.** The 30-day clock only counts days the process is actually
running and logging trades. Gaps in uptime extend the clock.

---

## Step 5 — Monitor during the 30 days

Check progress at any time:

```bash
python scripts/enable_live_trading.py --check-only
```

Example output at day 12:

```
Live trading prerequisites
========================================
✓ OANDA credentials valid
✓ Risk limits configured
✓ Zero execution errors in logs
✗ Paper trading duration: 12 days (need 30)

18 days remaining. Re-run after 2025-02-14.
```

---

## Step 6 — Enable live trading (after 30 days)

Once all checks pass:

```bash
python scripts/enable_live_trading.py
```

The script will:

1. Re-run all prerequisite checks
2. Print a summary of paper trading performance
3. Ask you to type: **`I understand the risks and want to enable live trading`**
4. Set `FEATURE_LIVE_TRADING=true` in `.env`
5. Restart the application in live mode

!!! danger "Real money"
    After this step, the application will place real orders on your OANDA live
    account. Ensure your risk limits are set conservatively before proceeding.

---

## Risk limit recommendations before going live

| Parameter | Conservative | Moderate |
|---|---|---|
| `MAX_POSITION_SIZE_PCT` | 1% | 2% |
| `MAX_DRAWDOWN_PCT` | 5% | 10% |
| `DAILY_LOSS_LIMIT_PCT` | 2% | 5% |
| `MAX_OPEN_POSITIONS` | 2 | 5 |

Start conservative. You can always increase limits after observing live behaviour.

---

## Frequently asked questions

**Can I skip the 30-day requirement?**

```bash
python scripts/enable_live_trading.py --force
```

`--force` bypasses the duration check. Use only in development environments
with a practice account — never on a live account.

**What counts as an "execution error"?**

Any log line at `ERROR` level from `execution/`, `brokers/`, or `brain/` modules.
Review `logs/trading.log` before enabling live trading.

**Does the 30-day clock reset if I restart the app?**

No. The clock is based on the earliest `paper_trading_started_at` timestamp in
the logs, not continuous uptime. Restarts are fine.

**What if I want to run paper trading indefinitely?**

Leave `FEATURE_LIVE_TRADING` unset or `false`. The application runs in paper
mode by default and will never place real orders.
