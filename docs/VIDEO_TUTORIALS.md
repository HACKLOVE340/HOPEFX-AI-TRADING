# Video Tutorials

> Complete guide to the HOPEFX video tutorial series.
> Each episode includes a full script outline, screen recording guide, and all commands shown.

---

## Series Overview

| # | Title | Level | Duration | Status |
|---|-------|-------|----------|--------|
| 1 | Introduction to HOPEFX | Beginner | 15 min | Script ready |
| 2 | Installation & Setup | Beginner | 20 min | Script ready |
| 3 | Your First Backtest | Beginner | 25 min | Script ready |
| 4 | Interactive Charting | Beginner–Intermediate | 30 min | Script ready |
| 5 | Technical Indicators Deep Dive | Intermediate | 45 min | Script ready |
| 6 | Building Your First Strategy | Intermediate | 45 min | Script ready |
| 7 | SMC/ICT Strategy | Advanced | 60 min | Script ready |
| 8 | ML Trading Introduction | Intermediate | 35 min | Script ready |
| 9 | Training the ML Model | Advanced | 50 min | Script ready |
| 10 | Connecting OANDA | Beginner | 30 min | Script ready |
| 11 | Risk Management Masterclass | All levels | 50 min | Script ready |
| 12 | Deploying to Production | Advanced | 40 min | Script ready |
| 13 | Prop Firm Challenge Guide | Intermediate | 45 min | Script ready |
| 14 | Social Trading & Copy Trading | Intermediate | 30 min | Script ready |
| 15 | Monitoring with Grafana | Advanced | 35 min | Script ready |

---

## Episode 1 — Introduction to HOPEFX

**Duration:** 15 min | **Level:** Beginner

### What to Show
- Open the GitHub repository page
- Show the README badges (CI, tests, Python version)
- Show the architecture diagram
- Show the `/docs` Swagger UI running locally
- Show a live signal response from `/api/signals/latest`

### Script Outline

**[0:00–1:00] Hook**
"Most trading bots are backtested on in-sample data and blow up on live markets.
HOPEFX is different — it's walk-forward validated with 66.4% out-of-sample accuracy
on 1,260 held-out bars. Let me show you what that means and how to use it."

**[1:00–4:00] What is HOPEFX?**
- Self-hosted algorithmic trading framework
- Python-based, open source (AGPL-3.0)
- Combines ML, 10 built-in strategies, risk management, and broker integration
- Runs on your own server — you control your data and your trades

**[4:00–8:00] Architecture walkthrough**
- Show the architecture diagram from `docs/index.md`
- Explain the 4 layers: Signal Engine → Risk Engine → Execution → Data
- Point out: ML model (176 features), CVaR gate, kill switch, OANDA/IBKR

**[8:00–12:00] Live demo**
```bash
# Start the server
uvicorn app:app --host 0.0.0.0 --port 8000

# Get a signal
curl http://localhost:8000/api/signals/latest?symbol=XAUUSD

# Check ML model
curl http://localhost:8000/api/ml/accuracy

# Open Swagger UI
open http://localhost:8000/docs
```

**[12:00–15:00] What's next**
- Point to QUICKSTART.md
- Mention the 10 built-in strategies
- Mention paper trading (no real money needed to start)

---

## Episode 2 — Installation & Setup

**Duration:** 20 min | **Level:** Beginner

### What to Show
- Terminal on Ubuntu 22.04 (or macOS)
- VS Code with the repository open
- Browser showing `/health` endpoint

### Script Outline

**[0:00–2:00] Prerequisites check**
```bash
python --version    # Need 3.10+
git --version
```

**[2:00–8:00] Clone and install**
```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
Show the packages installing. Explain what each major package does:
- `fastapi` — the web framework
- `xgboost` — the ML model
- `sqlalchemy` — database ORM
- `redis` — caching and pub/sub

**[8:00–13:00] Environment configuration**
```bash
cp .env.example .env
# Open .env in editor
python -c "import secrets; print(secrets.token_hex(32))"
```
Show setting `SECURITY_JWT_SECRET`, `CONFIG_ENCRYPTION_KEY`, `HOPEFX_KILL_SWITCH_TOKEN`.
Explain why these are required (startup validator will exit if missing).

**[13:00–17:00] Database and first run**
```bash
alembic upgrade head
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
Show the startup logs. Point out ComponentRegistry starting each component.

**[17:00–20:00] Verify**
```bash
curl http://localhost:8000/health
open http://localhost:8000/docs
```

---

## Episode 3 — Your First Backtest

**Duration:** 25 min | **Level:** Beginner

### What to Show
- Terminal running the backtest
- JSON output with metrics
- Equity curve chart (if available)

### Script Outline

**[0:00–3:00] What is backtesting?**
Explain: testing a strategy on historical data to see how it would have performed.
Warn about overfitting and in-sample vs out-of-sample.

**[3:00–10:00] Quick smoke test**
```bash
# Smoke test — uses synthetic data, ~30 seconds
python ml/train_advanced.py --smoke
```
Show the output: accuracy, features, OOS period.

**[10:00–18:00] Real data backtest**
```bash
# Full backtest on real GC=F (gold futures) data
python real_data_backtest.py --symbol XAUUSD --years 5
```
Walk through the output:
- Win rate: what it means
- Profit factor: > 1.0 is profitable
- Max drawdown: worst peak-to-trough loss
- Sharpe ratio: risk-adjusted return (and why N matters)

**[18:00–22:00] Via the API**
```bash
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "XAUUSD",
    "strategy": "ma_crossover",
    "years": 3,
    "initial_capital": 100000
  }'
```

**[22:00–25:00] Interpreting results**
- OOS accuracy is the credible number, not Sharpe (N=48 is too few)
- Walk-forward validation: why it matters
- Point to `docs/BACKTESTING_GUIDE.md` for more

---

## Episode 4 — Interactive Charting

**Duration:** 30 min | **Level:** Beginner–Intermediate

### What to Show
- Browser with Plotly charts
- Dark mode and light mode
- Adding indicators to a chart

### Script Outline

**[0:00–5:00] Chart engine overview**
```python
from charting.chart_engine import ChartEngine

engine = ChartEngine()
chart = engine.create_candlestick_chart("XAUUSD", timeframe="H1")
chart.show()
```

**[5:00–15:00] Adding indicators**
```python
# Add moving averages
chart.add_indicator("SMA", period=20, color="blue")
chart.add_indicator("EMA", period=50, color="orange")

# Add RSI in a sub-panel
chart.add_indicator("RSI", period=14, panel="below")

# Add Bollinger Bands
chart.add_indicator("BB", period=20, std=2)
```

**[15:00–22:00] Themes and export**
```python
# Dark mode (default)
chart.set_theme("dark")

# Light mode
chart.set_theme("light")

# Export as HTML
chart.export("xauusd_chart.html")

# Export as PNG
chart.export("xauusd_chart.png")
```

**[22:00–30:00] Real-time chart via WebSocket**
Show connecting to `ws://localhost:8000/ws/prices` and updating the chart live.

---

## Episode 5 — Technical Indicators Deep Dive

**Duration:** 45 min | **Level:** Intermediate

### Indicators Covered

**Moving Averages [0:00–10:00]**
```python
from charting.indicators import Indicators

ind = Indicators(df)
df['sma_20'] = ind.sma(period=20)
df['ema_50'] = ind.ema(period=50)
df['wma_14'] = ind.wma(period=14)
```

**Oscillators [10:00–20:00]**
```python
df['rsi'] = ind.rsi(period=14)
df['macd'], df['signal'], df['hist'] = ind.macd(12, 26, 9)
df['stoch_k'], df['stoch_d'] = ind.stochastic(14, 3)
```

**Volatility [20:00–30:00]**
```python
df['bb_upper'], df['bb_mid'], df['bb_lower'] = ind.bollinger_bands(20, 2)
df['atr'] = ind.atr(period=14)
df['keltner_upper'], df['keltner_lower'] = ind.keltner_channel(20, 2)
```

**Trend [30:00–38:00]**
```python
df['adx'] = ind.adx(period=14)
df['ichimoku'] = ind.ichimoku()  # Returns dict of all 5 components
```

**Volume [38:00–45:00]**
```python
df['obv'] = ind.obv()
df['vwap'] = ind.vwap()
df['volume_profile'] = ind.volume_profile(bins=20)
```

---

## Episode 6 — Building Your First Strategy

**Duration:** 45 min | **Level:** Intermediate

### What to Build
A simple RSI + EMA crossover strategy from scratch.

### Script Outline

**[0:00–8:00] Strategy structure**
```python
from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig

class MyRSIStrategy(BaseStrategy):
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self.rsi_period = config.parameters.get("rsi_period", 14)
        self.rsi_overbought = config.parameters.get("rsi_overbought", 70)
        self.rsi_oversold = config.parameters.get("rsi_oversold", 30)
```

**[8:00–20:00] Signal generation**
```python
    def analyze(self, data: pd.DataFrame) -> Signal:
        if len(data) < self.rsi_period + 1:
            return Signal(SignalType.NEUTRAL, confidence=0.0)

        rsi = self._calculate_rsi(data['close'], self.rsi_period)
        current_rsi = rsi.iloc[-1]

        if current_rsi < self.rsi_oversold:
            return Signal(
                signal_type=SignalType.BUY,
                confidence=min((self.rsi_oversold - current_rsi) / 30, 1.0),
                metadata={"rsi": current_rsi}
            )
        elif current_rsi > self.rsi_overbought:
            return Signal(
                signal_type=SignalType.SELL,
                confidence=min((current_rsi - self.rsi_overbought) / 30, 1.0),
                metadata={"rsi": current_rsi}
            )
        return Signal(SignalType.NEUTRAL, confidence=0.0)
```

**[20:00–30:00] Register and test**
```python
from strategies.manager import StrategyManager
from config.config_manager import ConfigManager

config = StrategyConfig(
    name="my_rsi",
    symbol="XAUUSD",
    parameters={"rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30}
)

manager = StrategyManager()
manager.register_strategy(MyRSIStrategy(config))
manager.start_strategy("my_rsi")
```

**[30:00–45:00] Backtest the strategy**
```bash
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"symbol": "XAUUSD", "strategy": "my_rsi", "years": 3}'
```

---

## Episode 7 — SMC/ICT Strategy

**Duration:** 60 min | **Level:** Advanced

### Concepts Covered

**[0:00–15:00] Smart Money Concepts theory**
- Order blocks: where institutions placed large orders
- Fair value gaps: price imbalances that tend to fill
- Liquidity sweeps: stop hunting before the real move
- Break of structure (BOS) vs Change of Character (CHoCh)

**[15:00–30:00] Using the built-in SMC strategy**
```python
from strategies.smc_ict import SMCICTStrategy, SMCConfig

config = SMCConfig(
    symbol="XAUUSD",
    timeframe="H1",
    ob_lookback=20,          # Order block lookback
    fvg_min_size=0.0005,     # Minimum FVG size (0.05%)
    ote_fib_levels=[0.62, 0.705, 0.79],  # OTE Fibonacci levels
    confluence_threshold=0.6  # Require 60% confluence
)

strategy = SMCICTStrategy(config)
signal = strategy.analyze(ohlcv_df)
print(f"Direction: {signal.signal_type}")
print(f"Confidence: {signal.confidence:.2%}")
print(f"Setup: {signal.metadata['setup_type']}")
```

**[30:00–45:00] ITS-8-OS (8 Optimal Setups)**
```python
from strategies.its_8_os import ITS8OSStrategy

# The 8 setups: AMD, Power of 3, Judas Swing, Kill Zones,
# Turtle Soup, Silver Bullet, OTE, Session Analysis
strategy = ITS8OSStrategy(config)
signal = strategy.analyze(ohlcv_df)
print(f"Active setups: {signal.metadata['active_setups']}")
print(f"Confluence score: {signal.metadata['confluence_score']:.2%}")
```

**[45:00–60:00] Combining with ML**
Show how SMC signals feed into the Strategy Brain alongside ML probability.

---

## Episode 8 — ML Trading Introduction

**Duration:** 35 min | **Level:** Intermediate

### Script Outline

**[0:00–8:00] Why ML for trading?**
- Traditional indicators are lagging
- ML can combine 176 features simultaneously
- Walk-forward validation prevents overfitting
- The 66.4% OOS accuracy: what it means and what it doesn't

**[8:00–18:00] The production model**
```bash
# Check model status
curl http://localhost:8000/api/ml/accuracy

# Get a prediction
curl -X POST http://localhost:8000/api/ml/predict/XAUUSD \
  -H "Authorization: Bearer $TOKEN"

# Get feature importance
curl http://localhost:8000/api/ml/feature-importance \
  -H "Authorization: Bearer $TOKEN"
```

**[18:00–28:00] Feature categories**
Show the 176 features grouped by category:
- Returns & momentum (28 features)
- Volatility (18 features)
- Trend & regime (14 features)
- MA distances ATR-normalised (16 features)
- COT proxies (9 features)
- Macro cross-asset (22 features)
- Z-scores (15 features)

**[28:00–35:00] The abstain mechanism**
Explain: the model abstains on 27.5% of bars (low confidence).
Only high-conviction signals reach execution. This is why win rate > 50%.

---

## Episode 9 — Training the ML Model

**Duration:** 50 min | **Level:** Advanced

### Script Outline

**[0:00–5:00] When to retrain**
- After 6 months of live trading
- After a major market regime change
- After adding new features

**[5:00–20:00] Smoke test first**
```bash
# Always smoke test before full retrain (~30 seconds)
python ml/train_advanced.py --smoke
```
Show the output. Explain what each metric means.

**[20:00–40:00] Full retrain**
```bash
# Full production retrain (10–30 minutes)
python ml/train_advanced.py --years 50 --oos-years 3
```
Walk through the output:
- Walk-forward folds (5 folds × 756 OOS bars)
- OOS accuracy per fold
- Final OOS accuracy and p-value
- Sharpe gate check (N ≥ 600, SE ≤ 0.10)

**[40:00–48:00] Verify the new model**
```bash
# Check the new model loaded
curl http://localhost:8000/api/ml/accuracy

# Compare with previous
cat ml/saved_models/advanced_oos_meta.json
```

**[48:00–50:00] Fallback behaviour**
Explain: if the new model fails to load, the system falls back to `xgb_macro.pkl`
and fires a Sentry fatal alert + Discord critical alert.

---

## Episode 10 — Connecting OANDA

**Duration:** 30 min | **Level:** Beginner

### Script Outline

**[0:00–5:00] Create a practice account**
1. Go to oanda.com → Register → Practice Account
2. Dashboard → Manage API Access → Generate Token
3. Copy API token and Account ID

**[5:00–12:00] Configure credentials**
```bash
# Add to .env
BROKER_TYPE=oanda
BROKER_OANDA_TOKEN=your_practice_api_token
BROKER_OANDA_ACCOUNT=001-001-XXXXXXX-001
OANDA_ENVIRONMENT=practice
OANDA_REGION=us    # or eu, sg
```

**[12:00–20:00] Validate connectivity**
```bash
python scripts/validate_oanda.py
```
Show expected output:
```
✓ API key present
✓ Account reachable: balance $100,000.00
✓ XAU_USD pricing available: bid=2345.12 ask=2345.34
✓ Test order placed and cancelled
All checks passed — ready for paper trading.
```

**[20:00–28:00] Start paper trading**
```bash
uvicorn app:app --host 0.0.0.0 --port 8000

# Check broker status
curl http://localhost:8000/api/broker/status

# Check paper trading clock
curl http://localhost:8000/api/status/paper-trading
```

**[28:00–30:00] The 30-day gate**
Explain: live trading requires 30 days of paper trading with zero execution errors.
Show `docs/live_trading_gate.md`.

---

## Episode 11 — Risk Management Masterclass

**Duration:** 50 min | **Level:** All levels

### Script Outline

**[0:00–10:00] Position sizing**
```bash
# Configure in .env
MAX_POSITION_SIZE_PCT=1.0      # 1% of account per trade
MAX_OPEN_POSITIONS=5           # Maximum concurrent positions
KELLY_FRACTION=0.25            # Kelly criterion safety cap
```

**[10:00–20:00] Daily loss limits**
```bash
DAILY_LOSS_LIMIT_PCT=2.0       # Halt if daily loss > 2%
MAX_DRAWDOWN_PCT=8.0           # Halt if drawdown > 8%
```

**[20:00–30:00] CVaR pre-trade gate**
Every order goes through 8 sequential checks before execution:
1. Broker available
2. Kill switch not active
3. Daily loss limit not hit
4. Max drawdown not hit
5. Max positions not exceeded
6. Position size within limits
7. CVaR within limits
8. Prop firm rules (if enabled)

**[30:00–40:00] Kill switch**
```bash
# Activate kill switch (halts all trading immediately)
curl -X POST http://localhost:8000/api/trading/emergency-stop \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Kill-Switch-Token: $HOPEFX_KILL_SWITCH_TOKEN"

# Check kill switch status
curl http://localhost:8000/api/risk/status
```
Kill switch state persists to `risk/halt_state.json` — survives restarts.

**[40:00–50:00] VaR and CVaR**
```bash
# Get current risk metrics
curl http://localhost:8000/api/trading/risk-metrics \
  -H "Authorization: Bearer $TOKEN"
```
Explain VaR 95% (1-day), ES 99%, and why CVaR is used as the pre-trade gate.

---

## Episode 12 — Deploying to Production

**Duration:** 40 min | **Level:** Advanced

### Script Outline

**[0:00–8:00] Pre-deployment checklist**
```bash
python scripts/manage_secrets.py validate
python deployment_guide.py
```
Walk through each check: Python version, env vars, kill switch, ML model, Alembic.

**[8:00–20:00] Docker Compose deployment**
```bash
# On your VPS
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
cp .env.example .env
# Edit .env with production values
docker compose up -d
docker compose logs -f app
curl http://localhost:8000/health
```

**[20:00–30:00] Nginx + TLS**
Show setting up Nginx reverse proxy and Let's Encrypt certificate.
```bash
sudo certbot --nginx -d yourdomain.com
curl https://yourdomain.com/health
```

**[30:00–40:00] Monitoring**
```bash
# Grafana dashboards
open http://localhost:3000

# Prometheus metrics
curl http://localhost:9090/metrics | grep hopefx_

# Check Sentry
# (show Sentry dashboard with ML fallback alert example)
```

---

## Episode 13 — Prop Firm Challenge Guide

**Duration:** 45 min | **Level:** Intermediate

### Script Outline

**[0:00–10:00] Prop firm overview**
- FTMO: 10% profit target, 5% daily loss, 10% max drawdown
- MyForexFunds: 8% profit target, 5% daily loss, 12% max drawdown
- The5ers: 6% profit target, 4% daily loss, 6% max drawdown
- TopStep: futures-focused, different rules

**[10:00–25:00] Configure prop firm mode**
```bash
# Enable prop firm mode
PROP_FIRM_MODE=true
PROP_FIRM_NAME=ftmo
PROP_FIRM_DAILY_LOSS_LIMIT=5.0
PROP_FIRM_MAX_DRAWDOWN=10.0
PROP_FIRM_PROFIT_TARGET=10.0
```

**[25:00–40:00] Monitor challenge progress**
```bash
curl http://localhost:8000/api/risk/status \
  -H "Authorization: Bearer $TOKEN"
```
Show: current drawdown, daily loss, profit progress, days remaining.

**[40:00–45:00] Passing the challenge**
- Conservative settings: 1% per trade, 2% daily loss limit
- Let the ML model do the work — don't override signals
- The kill switch is your safety net

---

## Episode 14 — Social Trading & Copy Trading

**Duration:** 30 min | **Level:** Intermediate

### Script Outline

**[0:00–8:00] Opt in to the social feed**
```bash
curl -X POST http://localhost:8000/api/feed/opt-in \
  -H "Authorization: Bearer $TOKEN"
```
Your signals now appear on the social feed for other users to see and copy.

**[8:00–18:00] Browse the leaderboard**
```bash
curl http://localhost:8000/api/social/leaderboard \
  -H "Authorization: Bearer $TOKEN"
```
Show: trader rankings by Sharpe, win rate, total return.

**[18:00–25:00] Follow a trader**
```bash
# Get a trader's profile
curl http://localhost:8000/api/profiles/trader123

# Follow them
curl -X POST http://localhost:8000/api/profiles/trader123/follow \
  -H "Authorization: Bearer $TOKEN"

# See their signals
curl http://localhost:8000/api/profiles/trader123/signals
```

**[25:00–30:00] Copy trading**
Show how copy trading works: when a followed trader places a trade,
the system can automatically mirror it (scaled to your account size).

---

## Episode 15 — Monitoring with Grafana

**Duration:** 35 min | **Level:** Advanced

### Script Outline

**[0:00–8:00] Start Grafana**
```bash
docker compose up -d grafana prometheus
open http://localhost:3000
# Default login: admin / admin
```

**[8:00–20:00] The 4 dashboards**
1. **Trading Overview** — signals per hour, win rate, P&L
2. **ML Performance** — model accuracy, abstain rate, feature drift
3. **Risk Monitor** — drawdown, CVaR, kill switch status
4. **System Health** — API latency, Redis hit rate, DB query time

**[20:00–30:00] Key metrics**
```bash
# Prometheus metrics
curl http://localhost:9090/metrics | grep hopefx_

# Key metrics:
# hopefx_signals_total — total signals generated
# hopefx_orders_filled_total — total orders filled
# hopefx_ml_accuracy — current ML accuracy
# hopefx_drawdown_pct — current drawdown percentage
# hopefx_api_latency_p99 — API p99 latency
```

**[30:00–35:00] Setting up alerts**
Show creating a Grafana alert: "notify Discord if drawdown > 5%".

---

## Recording Checklist

Before recording each episode:
- [ ] Terminal font size: 18pt minimum
- [ ] Screen resolution: 1920×1080
- [ ] Dark terminal theme (easier to read)
- [ ] Close all notifications
- [ ] Have all commands pre-typed in a script file
- [ ] Test all commands before recording
- [ ] Have `.env` configured with test credentials

After recording:
- [ ] Add chapter markers at each section timestamp
- [ ] Add captions/subtitles
- [ ] Add end screen with links to next episode and GitHub
- [ ] Pin the GitHub link in the video description

---

## Resources for Each Episode

All code shown in these tutorials is in the repository:
- Strategies: `strategies/`
- ML training: `ml/train_advanced.py`
- Backtesting: `real_data_backtest.py`, `backtesting/`
- API examples: `docs/API_REFERENCE.md`
- Configuration: `.env.example`

---

*Last updated: 2026-07-14*
