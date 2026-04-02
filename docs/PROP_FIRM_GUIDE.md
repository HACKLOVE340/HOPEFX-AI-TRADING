# Prop Firm Guide

> How to use HOPEFX to pass prop firm challenges and manage funded accounts.
> Last updated: 2026-04-01

---

## Supported Prop Firms

| Firm | Type | Profit Target | Daily Loss | Max Drawdown | Status |
|------|------|--------------|------------|--------------|--------|
| FTMO | Forex/CFD | 10% | 5% | 10% | ✅ Integrated |
| MyForexFunds | Forex/CFD | 8% | 5% | 12% | ✅ Integrated |
| The5ers | Forex/CFD | 6% | 4% | 6% | ✅ Integrated |
| TopStep | Futures | $3,000 | $1,500 | $2,000 | ✅ Integrated |
| FundedNext | Forex/CFD | 10% | 5% | 10% | ✅ Integrated |

---

## Quick Setup

### 1. Enable Prop Firm Mode

Add to `.env`:
```bash
PROP_FIRM_MODE=true
PROP_FIRM_NAME=ftmo                    # ftmo | myforexfunds | the5ers | topstep | fundednext
PROP_FIRM_DAILY_LOSS_LIMIT=5.0         # % of starting balance
PROP_FIRM_MAX_DRAWDOWN=10.0            # % of starting balance
PROP_FIRM_PROFIT_TARGET=10.0           # % of starting balance
PROP_FIRM_STARTING_BALANCE=100000      # Account starting balance
```

### 2. Verify Configuration

```bash
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
{
  "prop_firm_mode": true,
  "prop_firm": "ftmo",
  "current_balance": 100000,
  "profit_pct": 0.0,
  "daily_loss_pct": 0.0,
  "max_drawdown_pct": 0.0,
  "daily_loss_limit": 5.0,
  "max_drawdown_limit": 10.0,
  "profit_target": 10.0,
  "challenge_status": "in_progress",
  "days_remaining": 30
}
```

### 3. Start Trading

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

The risk engine will automatically enforce all prop firm rules. Any order that
would breach a limit is blocked before it reaches the broker.

---

## Firm-Specific Configuration

### FTMO

```bash
PROP_FIRM_NAME=ftmo
PROP_FIRM_DAILY_LOSS_LIMIT=5.0
PROP_FIRM_MAX_DRAWDOWN=10.0
PROP_FIRM_PROFIT_TARGET=10.0
PROP_FIRM_CHALLENGE_DAYS=30
PROP_FIRM_MIN_TRADING_DAYS=10
```

FTMO rules:
- Daily loss limit: 5% of initial balance (not current balance)
- Max drawdown: 10% of initial balance (trailing from highest equity)
- Profit target: 10% in Phase 1, 5% in Phase 2
- Minimum trading days: 10 days in Phase 1
- No time limit in Phase 2

### MyForexFunds

```bash
PROP_FIRM_NAME=myforexfunds
PROP_FIRM_DAILY_LOSS_LIMIT=5.0
PROP_FIRM_MAX_DRAWDOWN=12.0
PROP_FIRM_PROFIT_TARGET=8.0
```

MyForexFunds rules:
- Daily loss: 5% of account balance (resets daily at midnight EST)
- Max drawdown: 12% trailing from highest equity
- No minimum trading days

### The5ers

```bash
PROP_FIRM_NAME=the5ers
PROP_FIRM_DAILY_LOSS_LIMIT=4.0
PROP_FIRM_MAX_DRAWDOWN=6.0
PROP_FIRM_PROFIT_TARGET=6.0
```

The5ers rules:
- Daily loss: 4% of starting balance
- Max drawdown: 6% of starting balance
- No time limit — trade at your own pace

### TopStep (Futures)

```bash
PROP_FIRM_NAME=topstep
PROP_FIRM_DAILY_LOSS_LIMIT_USD=1500
PROP_FIRM_MAX_DRAWDOWN_USD=2000
PROP_FIRM_PROFIT_TARGET_USD=3000
PROP_FIRM_STARTING_BALANCE=50000
```

TopStep rules:
- Daily loss: fixed dollar amount (not percentage)
- Max drawdown: trailing from highest equity
- Profit target: fixed dollar amount

---

## Risk Engine Integration

In prop firm mode, the pre-trade gate adds 3 additional checks:

1. **Daily loss check** — blocks any order that would push daily loss past the limit
2. **Max drawdown check** — blocks any order that would push drawdown past the limit
3. **Profit target check** — optionally pauses trading when target is reached (configurable)

These checks run before every order, independently of the standard CVaR gate.
A breach blocks the order with `TradeBlocked: prop_firm_daily_loss_limit`.

---

## Monitoring Challenge Progress

### Via API

```bash
# Full risk status
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Performance summary
curl http://localhost:8000/api/performance/summary \
  -H "Authorization: Bearer $TOKEN"
```

### Via Grafana

The Risk Monitor dashboard shows:
- Current drawdown vs limit (gauge)
- Daily loss vs limit (gauge)
- Profit progress vs target (gauge)
- Equity curve with drawdown limit line

Open Grafana at `http://localhost:3000` → Risk Monitor dashboard.

---

## Recommended Settings for Prop Firm Challenges

### Conservative (recommended for Phase 1)

```bash
# Position sizing
MAX_POSITION_SIZE_PCT=0.5          # 0.5% per trade
MAX_OPEN_POSITIONS=3               # Max 3 concurrent positions
KELLY_FRACTION=0.1                 # Very conservative Kelly

# Risk limits (tighter than firm limits)
DAILY_LOSS_LIMIT_PCT=2.5           # Half the firm's 5% limit
MAX_DRAWDOWN_PCT=5.0               # Half the firm's 10% limit

# ML settings
ML_ABSTAIN_THRESHOLD=0.60          # Only trade high-confidence signals
```

### Moderate (for Phase 2 or funded accounts)

```bash
MAX_POSITION_SIZE_PCT=1.0
MAX_OPEN_POSITIONS=5
KELLY_FRACTION=0.25
DAILY_LOSS_LIMIT_PCT=3.5
MAX_DRAWDOWN_PCT=7.0
ML_ABSTAIN_THRESHOLD=0.55
```

**Key principle:** Set your internal limits at 50–60% of the firm's limits.
This gives you a buffer — if the system hits your internal limit, you still
have room before the firm's limit is breached.

---

## Common Mistakes to Avoid

### 1. Trading during high-impact news
Configure auto-pause around FOMC, NFP, and CPI releases:
```bash
curl -X POST http://localhost:8000/api/calendar/auto-pause \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "pause_minutes_before": 30,
    "resume_minutes_after": 15,
    "impact_levels": ["high"]
  }'
```

### 2. Overriding the kill switch
The kill switch exists for a reason. If it fires, investigate before resuming:
```bash
# Check why it fired
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Check logs
docker compose logs app | grep "kill switch"
```

### 3. Ignoring the abstain signal
When the ML model abstains (27.5% of bars), don't force a trade. The model
abstains because confidence is low. Forcing trades on low-confidence bars
is how challenges get failed.

### 4. Not accounting for spread and commission
HOPEFX models 35 bps commission + 5 bps slippage by default. Verify your
broker's actual spread and commission match:
```bash
COMMISSION_BPS=35
SLIPPAGE_BPS=5
```

### 5. Trading too many pairs simultaneously
Correlated pairs (XAUUSD + XAGUSD, EURUSD + GBPUSD) amplify drawdown.
Stick to 1–2 uncorrelated instruments during the challenge.

---

## Passing the Challenge

### Phase 1 Checklist (FTMO example)
- [ ] Profit target: 10% reached
- [ ] Daily loss limit: never breached (5%)
- [ ] Max drawdown: never breached (10%)
- [ ] Minimum trading days: 10 days completed
- [ ] No rule violations in the trading history

### After Passing
1. Download your Phase 1 certificate
2. Start Phase 2 with the same conservative settings
3. Phase 2 profit target: 5% (easier)
4. Same loss limits apply

### Getting Funded
After passing both phases:
1. Sign the funding agreement
2. Update `.env` with your funded account credentials
3. Keep `MAX_POSITION_SIZE_PCT` conservative (start at 0.5%)
4. Scale up only after 30+ profitable trades

---

## Prop Firm Mode vs Standard Mode

| Feature | Standard Mode | Prop Firm Mode |
|---------|--------------|----------------|
| Daily loss limit | Configurable | Enforced at firm's limit |
| Max drawdown | Configurable | Enforced at firm's limit |
| Profit target tracking | No | Yes |
| Challenge day counter | No | Yes |
| Auto-pause on news | Optional | Recommended |
| Position size | Configurable | Capped at firm's max lot |
| Kill switch | Manual | Auto-fires at 80% of daily limit |

---

## Troubleshooting

### `TradeBlocked: prop_firm_daily_loss_limit`
You've hit your internal daily loss limit. Trading is paused until midnight.
Check your current loss:
```bash
curl http://localhost:8000/api/risk/status | grep daily_loss_pct
```

### `TradeBlocked: prop_firm_max_drawdown`
You've hit your internal max drawdown limit. The kill switch has fired.
Review your open positions and close any that are in loss before resuming.

### Challenge failed — drawdown breached
This means a position moved against you beyond the limit. Post-mortem:
1. Check which trade caused the breach: `GET /api/journal/trades`
2. Was the ML model in fallback mode? Check `GET /api/ml/accuracy`
3. Was there a high-impact news event? Check `GET /api/calendar/today`
4. Adjust `MAX_POSITION_SIZE_PCT` down for the next attempt

---

*Last updated: 2026-04-01*
