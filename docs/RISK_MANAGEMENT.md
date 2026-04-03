# Risk Management Guide

> How HOPEFX manages risk at every layer — from position sizing to kill switch.
> Last updated: 2026-04-01

---

## Overview

HOPEFX implements risk management in 4 layers:

1. **Pre-trade gate** — 8 sequential checks before every order
2. **Position sizing** — Kelly criterion with safety caps
3. **Portfolio limits** — daily loss, max drawdown, CVaR
4. **Kill switch** — emergency halt that survives restarts

All layers are active by default. Disabling any layer requires explicit configuration.

---

## Configuration

All risk parameters are set in `.env`:

```bash
# Position sizing
MAX_POSITION_SIZE_PCT=1.0          # Max % of account per trade
MAX_OPEN_POSITIONS=5               # Max concurrent open positions
KELLY_FRACTION=0.25                # Fractional Kelly (0.25 = 25% of full Kelly)

# Portfolio limits
DAILY_LOSS_LIMIT_PCT=2.0           # Halt if daily loss > 2% of account
MAX_DRAWDOWN_PCT=8.0               # Halt if drawdown > 8% from peak
CVAR_LIMIT_PCT=3.0                 # Block order if portfolio CVaR > 3%

# VaR settings
VAR_CONFIDENCE=0.95                # VaR confidence level
VAR_LOOKBACK_DAYS=252              # Historical VaR lookback window
ENFORCE_MULTIDAY_VAR=true          # Block sqrt(t) scaling for multi-day VaR

# Kill switch
HOPEFX_KILL_SWITCH_TOKEN=<secret>  # Required to activate/deactivate

# Prop firm mode (optional)
PROP_FIRM_MODE=false
PROP_FIRM_NAME=ftmo
PROP_FIRM_DAILY_LOSS_LIMIT=5.0
PROP_FIRM_MAX_DRAWDOWN=10.0
PROP_FIRM_PROFIT_TARGET=10.0
```

---

## Pre-Trade Gate

Every order passes through 8 sequential checks in `risk/pre_trade_gate.py`.
A failure at any check raises `TradeBlocked` and the order is cancelled.
There is no fallback — a blocked order never reaches the broker.

```
Check 1: Broker available and connected
Check 2: Kill switch not active
Check 3: Daily loss limit not exceeded
Check 4: Max drawdown not exceeded
Check 5: Max open positions not exceeded
Check 6: Position size within limits (Kelly + hard cap)
Check 7: CVaR within limits (adding this position)
Check 8: Prop firm rules (if PROP_FIRM_MODE=true)
```

Check the gate status:
```bash
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
{
  "kill_switch_active": false,
  "daily_loss_pct": 0.8,
  "daily_loss_limit_pct": 2.0,
  "drawdown_pct": 1.2,
  "max_drawdown_pct": 8.0,
  "open_positions": 2,
  "max_open_positions": 5,
  "cvar_pct": 1.4,
  "cvar_limit_pct": 3.0,
  "prop_firm_mode": false,
  "can_trade": true
}
```

---

## Position Sizing

### Kelly Criterion

The Kelly criterion calculates the theoretically optimal fraction of capital
to risk per trade based on win rate and average win/loss ratio:

```
Kelly % = Win Rate − (Loss Rate / Win/Loss Ratio)
```

HOPEFX uses fractional Kelly with a hard cap:

```python
# Effective position size
kelly_size = kelly_fraction * full_kelly_pct   # e.g., 0.25 × 4% = 1%
position_size = min(kelly_size, MAX_POSITION_SIZE_PCT)  # Hard cap at 1%
```

Configure:
```bash
KELLY_FRACTION=0.25          # 25% of full Kelly (conservative)
MAX_POSITION_SIZE_PCT=1.0    # Never more than 1% per trade
```

### Manual Override

To set a fixed position size (ignoring Kelly):
```bash
POSITION_SIZE_MODE=fixed
FIXED_POSITION_SIZE_PCT=0.5   # Always 0.5% per trade
```

### Lot Size Calculation

For OANDA (XAUUSD):
```python
# Account balance: $100,000
# Position size: 1% = $1,000 risk
# Stop loss: 15 pips = $15 per lot
# Lot size = $1,000 / $15 = 66.7 lots → rounded to 67 lots
```

---

## Daily Loss Limit

When daily losses exceed `DAILY_LOSS_LIMIT_PCT`, the kill switch fires automatically
and all trading halts until midnight (when the daily counter resets).

```bash
DAILY_LOSS_LIMIT_PCT=2.0    # Halt if daily P&L < -2% of account
```

The daily loss is calculated from midnight UTC. It resets automatically at 00:00 UTC.

Check current daily loss:
```bash
curl http://localhost:8000/api/risk/status | grep daily_loss_pct
```

---

## Max Drawdown

When the portfolio drawdown from its peak exceeds `MAX_DRAWDOWN_PCT`, the kill
switch fires and trading halts until manually cleared.

```bash
MAX_DRAWDOWN_PCT=8.0    # Halt if drawdown from peak > 8%
```

Unlike the daily loss limit, the drawdown halt does **not** reset automatically.
You must investigate and manually clear it:

```bash
# Check drawdown status
curl http://localhost:8000/api/risk/status | grep drawdown

# Clear the halt (after investigation)
curl -X DELETE http://localhost:8000/api/trading/emergency-stop \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

---

## CVaR Pre-Trade Gate

Conditional Value at Risk (CVaR, also called Expected Shortfall) measures the
expected loss in the worst `1 - confidence` percent of scenarios.

Before every order, the system computes the portfolio CVaR **including the proposed
position**. If it exceeds `CVAR_LIMIT_PCT`, the order is blocked.

```bash
CVAR_LIMIT_PCT=3.0       # Block if portfolio CVaR > 3% of account
VAR_CONFIDENCE=0.95      # CVaR at 95% confidence (worst 5% of scenarios)
```

The CVaR gate runs independently of all other checks. A CVaR breach always blocks,
even if all other checks pass.

Get current risk metrics:
```bash
curl http://localhost:8000/api/trading/risk-metrics \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
{
  "var_95_1day": 0.012,
  "cvar_95_1day": 0.018,
  "var_99_1day": 0.021,
  "es_99_1day": 0.028,
  "portfolio_volatility": 0.008,
  "sharpe_ratio": 1.52,
  "max_drawdown": 0.012,
  "current_drawdown": 0.008
}
```

---

## VaR Methods

HOPEFX implements 4 VaR methods in `risk/advanced_analytics.py`:

### Historical VaR
Uses the empirical distribution of past returns. No distributional assumptions.
```python
var = calculate_var_historical(returns, confidence=0.95)
```

### Parametric VaR (Variance-Covariance)
Assumes normally distributed returns. Fast but underestimates tail risk.
```python
var = calculate_var_parametric(returns, confidence=0.95)
```

### Monte Carlo VaR
Simulates 10,000 return paths. Most accurate for complex portfolios.
```python
var = calculate_var_monte_carlo(returns, confidence=0.95, n_simulations=10000)
```

### Multi-Day VaR (no sqrt(t) scaling)
Correct multi-day VaR using overlapping windows — not the incorrect `sqrt(t)` approximation.
```python
var = calculate_var_multiday(returns, confidence=0.95, time_horizon=5)
```

### EWMA VaR (RiskMetrics)
Exponentially weighted — more responsive to recent volatility.
```python
var = calculate_var_ewma(returns, confidence=0.95, lambda_=0.94)
```

> ⚠️ `ENFORCE_MULTIDAY_VAR=true` blocks `calculate_var_historical` and
> `calculate_var_parametric` for `time_horizon > 1`. Use `calculate_var_multiday`
> or `calculate_var_ewma` for multi-day risk limits.

---

## Kill Switch

The kill switch immediately halts all trading and blocks all new orders.
It persists to `risk/halt_state.json` — it survives application restarts.

### Activate

```bash
curl -X POST http://localhost:8000/api/trading/emergency-stop \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

Response:
```json
{
  "kill_switch_active": true,
  "activated_at": "2026-07-14T10:30:00Z",
  "reason": "manual",
  "open_positions_closed": false
}
```

The kill switch does **not** automatically close open positions. You must close
them manually after activating:

```bash
# Close all open positions
curl -X DELETE http://localhost:8000/api/trading/positions \
  -H "Authorization: Bearer $TOKEN"
```

### Deactivate

```bash
curl -X DELETE http://localhost:8000/api/trading/emergency-stop \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"
```

### Halt State File

```bash
cat risk/halt_state.json
```

```json
{
  "active": true,
  "activated_at": "2026-07-14T10:30:00Z",
  "reason": "daily_loss_limit",
  "daily_loss_pct": 2.1,
  "drawdown_pct": 3.4
}
```

### Auto-Activation Triggers

The kill switch fires automatically when:
- Daily loss exceeds `DAILY_LOSS_LIMIT_PCT`
- Drawdown exceeds `MAX_DRAWDOWN_PCT`
- Prop firm daily loss limit breached (if `PROP_FIRM_MODE=true`)
- Prop firm max drawdown breached (if `PROP_FIRM_MODE=true`)
- Circuit breaker opens (3 execution failures in 60 seconds)

---

## Prop Firm Mode

Enable to enforce prop firm challenge rules on top of standard risk limits:

```bash
PROP_FIRM_MODE=true
PROP_FIRM_NAME=ftmo
PROP_FIRM_DAILY_LOSS_LIMIT=5.0     # % of starting balance
PROP_FIRM_MAX_DRAWDOWN=10.0        # % of starting balance
PROP_FIRM_PROFIT_TARGET=10.0       # % of starting balance
PROP_FIRM_STARTING_BALANCE=100000
```

In prop firm mode, the pre-trade gate adds 3 additional checks:
1. Prop firm daily loss limit
2. Prop firm max drawdown limit
3. Prop firm profit target (optionally pauses trading when reached)

**Recommended:** Set your internal limits at 50% of the firm's limits.
If `PROP_FIRM_DAILY_LOSS_LIMIT=5.0`, set `DAILY_LOSS_LIMIT_PCT=2.5`.

See [PROP_FIRM_GUIDE.md](PROP_FIRM_GUIDE.md) for firm-specific configuration.

---

## Auto-Pause on News Events

Automatically pause trading around high-impact economic events:

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

This pauses signal generation (not the kill switch) around FOMC, NFP, CPI,
and other high-impact events. Trading resumes automatically after the event.

---

## Risk Monitoring

### Via API

```bash
# Full risk status
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"

# Detailed risk metrics (VaR, CVaR, Sharpe, drawdown)
curl http://localhost:8000/api/trading/risk-metrics \
  -H "Authorization: Bearer $TOKEN"

# Performance summary
curl http://localhost:8000/api/performance/summary \
  -H "Authorization: Bearer $TOKEN"
```

### Via Grafana

The Risk Monitor dashboard shows:
- Current drawdown vs limit (gauge — red when > 80% of limit)
- Daily loss vs limit (gauge)
- CVaR vs limit (gauge)
- Kill switch status (green/red indicator)
- Open positions count
- Equity curve with drawdown limit line

Open Grafana at `http://localhost:3000` → Risk Monitor dashboard.

### Via Prometheus

```bash
curl http://localhost:9090/metrics | grep hopefx_risk
```

Key metrics:
```
hopefx_drawdown_pct          — current drawdown percentage
hopefx_daily_loss_pct        — current daily loss percentage
hopefx_cvar_pct              — current portfolio CVaR
hopefx_kill_switch_active    — 1 if active, 0 if not
hopefx_open_positions        — number of open positions
```

---

## Risk Checklist (Pre-Live Trading)

- [ ] `DAILY_LOSS_LIMIT_PCT` set to ≤ 2% (conservative start)
- [ ] `MAX_DRAWDOWN_PCT` set to ≤ 8%
- [ ] `MAX_POSITION_SIZE_PCT` set to ≤ 1%
- [ ] `KELLY_FRACTION` set to ≤ 0.25
- [ ] `CVAR_LIMIT_PCT` set to ≤ 3%
- [ ] `HOPEFX_KILL_SWITCH_TOKEN` is a strong secret (≥ 32 chars)
- [ ] Kill switch tested: activate → verify orders blocked → deactivate
- [ ] Daily loss limit tested: simulate loss → verify halt fires
- [ ] Prop firm mode configured (if applicable)
- [ ] Auto-pause on news configured
- [ ] Grafana Risk Monitor dashboard accessible
- [ ] Sentry alert configured for kill switch activation

---

*Last updated: 2026-04-01*
