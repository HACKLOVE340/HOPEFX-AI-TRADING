# Quick Start

Get HOPEFX running in under 5 minutes.

---

## Prerequisites

- Python 3.10+
- An [OANDA practice account](https://www.oanda.com/register/) (free, instant)
- Redis (optional — caching only)

---

## 1. Clone and install

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

---

## 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
OANDA_API_KEY=your_practice_api_key
OANDA_ACCOUNT_ID=your_account_id
OANDA_ENVIRONMENT=practice
```

Get your API key from **OANDA fxTrade Practice → Manage API Access**.

---

## 3. Start the application

```bash
python main.py
```

The API server starts on `http://localhost:8000`.
Visit `http://localhost:8000/` for the landing page or `http://localhost:8000/docs` for the interactive API explorer.

---

## 4. Run your first backtest

```bash
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "MovingAverageCrossover",
    "symbol": "GC=F",
    "start_date": "2023-01-01",
    "end_date": "2024-01-01",
    "initial_capital": 10000
  }'
```

Download the PDF report:

```bash
curl http://localhost:8000/api/backtest/{run_id}/report.pdf -o report.pdf
```

---

## 5. Enable paper trading

```bash
python scripts/validate_oanda.py
```

This validates your OANDA credentials and starts a 30-day paper trading session.
After 30 days of validated results, run:

```bash
python scripts/enable_live_trading.py
```

---

## Next steps

- [OANDA Paper Trading Setup](oanda_paper_trading_setup.md) — detailed broker configuration
- [Sample Strategies](SAMPLE_STRATEGIES.md) — explore built-in strategies
- [API Reference](API_REFERENCE.md) — full endpoint documentation
- [FAQ](FAQ.md) — common questions
