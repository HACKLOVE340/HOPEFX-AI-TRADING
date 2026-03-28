# HOPEFX AI Trading - Frequently Asked Questions

> Your questions answered about the HOPEFX AI Trading Framework

---

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Installation & Setup](#installation--setup)
3. [Trading & Strategies](#trading--strategies)
4. [Broker Integration](#broker-integration)
5. [Machine Learning](#machine-learning)
6. [Security](#security)
7. [Technical Issues](#technical-issues)
8. [Pricing & Licensing](#pricing--licensing)

---

## Getting Started

### What is HOPEFX AI Trading?

HOPEFX AI Trading is an advanced, open-source AI-powered trading framework designed primarily for XAU/USD (Gold) trading. It combines machine learning, real-time market analysis, multi-broker integration, and intelligent trade execution to provide a complete automated trading solution.

### Who is HOPEFX for?

- **Retail traders** looking to automate their trading strategies
- **Prop firm traders** who need compliant trading automation
- **Algo developers** who want a Python-based framework
- **Quantitative analysts** building ML-based trading systems
- **Trading educators** teaching algorithmic trading

### How does HOPEFX compare to TradingView/MetaTrader?

| Feature | HOPEFX | TradingView | MetaTrader |
|---------|--------|-------------|------------|
| AI/ML Built-in | ✅ | ❌ | ❌ |
| Open Source | ✅ | ❌ | ❌ |
| Multi-Broker | ✅ | Limited | Limited |
| Prop Firm Support | ✅ | ❌ | ⚡ |
| Python-based | ✅ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ |
| Free | ✅ | Paid | Free |

See [COMPETITIVE_ANALYSIS.md](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/docs/archive/COMPETITIVE_ANALYSIS.md) for detailed comparison.

### Is HOPEFX really free?

HOPEFX is open-source under the **AGPL-3.0** license. You can:
- Use it for personal trading at no cost
- Modify the code to suit your needs
- Run it on your own servers
- Contribute to the project (see [CLA](../CLA.md))

Commercial use (proprietary products, SaaS, white-label) requires a separate Commercial License — see [LICENSE-COMMERCIAL.md](../LICENSE-COMMERCIAL.md).

---

## Installation & Setup

### What are the system requirements?

**Minimum:**
- Python 3.10, 3.11, or 3.12
- 4 GB RAM
- 2 CPU cores
- 10 GB disk space

**Recommended:**
- Python 3.12
- 8 GB RAM
- 4+ CPU cores
- SSD with 20 GB space
- Redis 7+ for caching
- PostgreSQL 16+ for production

### How do I install HOPEFX?

```bash
# Clone the repository
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Initialize
python cli.py init
```

See [INSTALLATION.md](INSTALLATION.md) for detailed instructions.

### Why am I getting import errors?

Common causes:
1. **Virtual environment not activated** - Run `source venv/bin/activate`
2. **Missing dependencies** - Run `pip install -r requirements.txt`
3. **Wrong Python version** — Ensure Python 3.10+

### How do I configure my broker API keys?

1. Create/edit your `.env` file
2. Add your API credentials:
```bash
# For OANDA
OANDA_API_KEY=your_key_here
OANDA_ACCOUNT_ID=your_account_id

# For Binance
BINANCE_API_KEY=your_key
BINANCE_SECRET_KEY=your_secret
```
3. Never commit `.env` to version control

### How do I run the API server?

```bash
# Development mode (auto-reload)
uvicorn app:app --reload --port 8000

# Production mode
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4

# With Docker (recommended)
docker-compose up -d
```

Access API docs at `http://localhost:8000/docs`

---

## Trading & Strategies

### What trading strategies are included?

HOPEFX includes 12+ built-in strategies:

| Strategy | Type | Description |
|----------|------|-------------|
| SMC/ICT | Institutional | Smart Money Concepts |
| ITS 8 OS | Advanced | Institutional trading system |
| EMA Crossover | Trend | Exponential MA crossover |
| MA Crossover | Trend | Simple MA crossover |
| MACD | Momentum | MACD-based signals |
| RSI | Oscillator | RSI oversold/overbought |
| Bollinger Bands | Volatility | Mean reversion |
| Breakout | Momentum | Price breakout detection |
| Mean Reversion | Statistical | Mean reversion trading |
| Strategy Brain | AI | AI-powered strategy selection |

### How do I create a custom strategy?

1. Create a new file in `strategies/`:

```python
from strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, config):
        super().__init__(config)
        self.name = "My Custom Strategy"

    def generate_signal(self, data):
        # Your logic here
        if should_buy:
            return {'action': 'buy', 'symbol': 'XAUUSD'}
        elif should_sell:
            return {'action': 'sell', 'symbol': 'XAUUSD'}
        return None
```

2. Register in `strategies/__init__.py`
3. Configure and test with backtesting

### How do I backtest a strategy?

```bash
# Using CLI
python cli.py backtest --strategy ma_crossover --symbol XAUUSD --start 2025-01-01 --end 2026-01-01

# Using Python
from backtesting import BacktestEngine

engine = BacktestEngine()
results = engine.run(
    strategy='ma_crossover',
    symbol='XAUUSD',
    start_date='2025-01-01',
    end_date='2026-01-01'
)
print(results.summary())
```

### What is paper trading and how do I use it?

Paper trading simulates real trading without risking real money.

```bash
# Start paper trading
python cli.py paper-trade --strategy smc_ict --balance 10000

# Or access the web dashboard
# Navigate to http://localhost:8000/docs (paper trading controls in the API)
```

### How does risk management work?

HOPEFX includes comprehensive risk management:

- **Position sizing:** Fixed, percentage, or Kelly criterion
- **Stop-loss:** Automatic or trailing
- **Take-profit:** Fixed or scaled
- **Daily loss limit:** Stop trading after X% loss
- **Max drawdown:** Emergency stop
- **Max positions:** Limit concurrent trades

Configure in your strategy:
```python
risk_config = {
    'risk_per_trade': 0.02,  # 2% per trade
    'max_daily_loss': 0.05,  # 5% daily limit
    'max_drawdown': 0.10,    # 10% max drawdown
    'max_positions': 3
}
```

---

## Broker Integration

### Which brokers are supported?

| Broker | Asset Types | Status |
|--------|-------------|--------|
| OANDA | Forex | ✅ Integrated |
| MetaTrader 5 | Multi-asset | ✅ Integrated |
| Interactive Brokers | Stocks/Forex/Options | ✅ Integrated |
| Alpaca | Stocks/Crypto | ✅ Integrated |
| Binance | Crypto | ✅ Integrated |
| Paper Trading | All | ✅ Built-in |

### Can I use multiple brokers?

Yes! HOPEFX supports multi-broker trading:

```python
from brokers import BrokerFactory

# Create broker instances
oanda = BrokerFactory.create('oanda', config)
binance = BrokerFactory.create('binance', config)

# Trade on both
oanda.place_order(order1)
binance.place_order(order2)
```

### How do I connect to a prop firm?

HOPEFX supports major prop firms:

```python
from brokers.prop_firms import FTMOConnector

ftmo = FTMOConnector(
    api_key='your_key',
    account_id='your_account',
    challenge_type='100k'
)

# Prop-firm specific risk checks are automatic
ftmo.place_order(order)
```

Supported prop firms: FTMO, MyForexFunds, The5ers, TopStep

### Why is my broker connection failing?

1. **Check credentials:** Verify API key and secret
2. **Check network:** Ensure broker API is accessible
3. **Check sandbox mode:** Development should use sandbox
4. **Check permissions:** API key may need trading permissions
5. **Check rate limits:** Reduce request frequency

---

## Machine Learning

### What ML models are included?

The production model is `ml/saved_models/advanced_oos.pkl`:

- **Architecture:** XGBoost + isotonic calibration (CalibratedClassifierCV)
- **Features:** 176 stationary-tested features (ADF + KPSS)
- **OOS accuracy:** 66.4% (p=0.0000, N=1,260 bars, 2019–2026)
- **Sharpe gate:** PASSED — N=1,260 ≥ 600, SE=0.041 ≤ 0.10
- **Multi-symbol backtest:** N=628 trades (XAU+BTC+ETH, 10-yr real data)

Additional models used as fallbacks: `rf_macro.pkl`, `xgb_macro.pkl`.

### How do I retrain the production model?

```bash
# Smoke test (~30 s)
python ml/train_advanced.py --smoke

# Full production retrain (50 years, 3-year OOS)
python ml/train_advanced.py --years 50 --oos-years 3

# Multi-symbol backtest
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

### How does online learning work?

Set `ML_HOURLY_ENABLED=true` to activate:

- **Hourly:** `SklearnOnlineLearner` (SGDClassifier) receives the last 24 bars via `HourlyTrainer._online_update()` and calls `partial_fit()`.
- **Daily at 00:05 UTC:** EWC regime-adaptation loop detects the current market regime (volatile / ranging / trending) and adjusts model plasticity accordingly.
- Learner state is persisted to `ml/saved_models/online_learner_{symbol}.pkl` and reloaded at startup.

### How accurate are the ML predictions?

The production model achieves **66.4% OOS accuracy** (p=0.0000) on 1,260 held-out bars spanning 2019–2026. The model abstains on low-confidence bars — only signals above the confidence threshold reach execution.

Key points:
- Cite OOS accuracy (66.4%, p=0.0000) as the credible performance number
- Sharpe ratio is only reported after N ≥ 600 trades (gate PASSED at N=628)
- Always backtest before live trading
- Monitor live signal distribution against OOS backtest distribution

---

## Security

### How are my API keys stored?

API keys are encrypted using Fernet encryption:
- Keys stored in encrypted configuration
- Environment variables recommended
- Never stored in plain text
- Never committed to version control

### Is my trading data secure?

Yes:
- All data stored locally (self-hosted)
- Optional encryption at rest
- SSL/TLS for API communications
- No data shared with third parties

### How do I enable 2FA?

```python
from config import SecurityConfig

security = SecurityConfig()
security.enable_2fa(method='totp')  # Google Authenticator compatible
```

### Best practices for security?

1. Use environment variables for secrets
2. Enable sandbox mode for development
3. Use paper trading first
4. Set conservative risk limits
5. Monitor trades regularly
6. Rotate API keys periodically

---

## Technical Issues

### Why is my strategy not generating signals?

1. **Check data:** Ensure market data is loading
2. **Check timeframe:** Strategy may need more historical data
3. **Check parameters:** Verify strategy configuration
4. **Check logs:** Review `logs/` for errors
5. **Debug mode:** Enable verbose logging

### Why are orders not executing?

1. **Broker connection:** Verify broker is connected
2. **Market hours:** Check if market is open
3. **Margin:** Ensure sufficient margin
4. **Position limits:** Check max positions
5. **Risk limits:** Order may exceed risk parameters

### How do I view logs?

```bash
# View recent logs
tail -f logs/hopefx.log

# Filter by level
grep ERROR logs/hopefx.log

# Use CLI
python cli.py logs --level ERROR --tail 100
```

### How do I report a bug?

1. Check existing [GitHub Issues](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues)
2. Create a new issue with:
   - Steps to reproduce
   - Expected vs actual behavior
   - Error logs
   - Environment details (Python version, OS)

---

## Pricing & Licensing

### Is HOPEFX free to use?

HOPEFX is open-source under **AGPL-3.0**. You can:
- Use for personal trading at no cost
- Modify the code
- Distribute your modifications (source must be disclosed under AGPL-3.0)

Commercial use without AGPL-3.0 source disclosure requires a [Commercial License](../LICENSE-COMMERCIAL.md).

### Are there any premium features?

Currently, all features are free. Future premium features may include:
- Cloud hosting
- Premium support
- Enterprise features
- Advanced ML models

### Can I sell strategies built with HOPEFX?

Yes! You can:
- Sell custom strategies
- Offer trading signals
- Build commercial products
- Charge for consulting services

Just ensure you comply with local financial regulations.

### How do I contribute?

See [CONTRIBUTING.md](CONTRIBUTING.md):
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## Still Have Questions?

### Community Support
- **Discord:** [Join HOPEFX Community](https://discord.gg/hopefx)
- **Telegram:** [HOPEFX Announcements](https://t.me/hopefx)
- **GitHub Discussions:** [Ask Questions](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/discussions)

### Documentation
- [Installation Guide](INSTALLATION.md)
- [API Guide](./API_GUIDE.md)
- [Security Guide](SECURITY.md)
- [Debugging Guide](DEBUGGING.md)

### Contact
- **Email:** support@hopefx.com
- **Twitter:** [@HOPEFX_Trading](https://twitter.com/HOPEFX_Trading)

---

*This FAQ is regularly updated. Last update: February 2026*
