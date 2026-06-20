# HOPEFX — Enabling Real / Live Market Data

Why your panels show "Awaiting data": in a fresh/sandboxed environment the
platform has **no usable data feed** because of three independent things. Fix
all three and real data flows through the whole pipeline (dashboard, signals,
ML, risk, execution).

---

## 1. Network egress (the hard blocker)

The data feeds call external providers over HTTPS. In a locked-down environment
outbound is blocked (you'll see `403`/timeouts and `circuit OPEN after N
failures` in logs). **Your deployment must allow outbound HTTPS** to the
providers you use, e.g.:

- `api.gold-api.com`, `metals-api.com`, `api.metalpriceapi.com` (gold)
- `www.alphavantage.co`, `api.twelvedata.com`, `finnhub.io`, `api.polygon.io`
- `query1.finance.yahoo.com` (yfinance free fallback)
- `api-fxpractice.oanda.com` / `stream-fxpractice.oanda.com` (OANDA broker feed)

Quick check from inside the container/pod:
```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://query1.finance.yahoo.com/v8/finance/chart/GC=F
# 200 = egress OK · 403/000 = blocked by network policy
```

## 2. Real API keys (not the bootstrap placeholders)

`scripts/bootstrap_dev.py` writes **random placeholder** values for every key,
so even with egress the providers reject them. Set real keys in `.env`
(or your secrets manager). The data layer reads these:

| Env var | Provider | Used for |
|--------|----------|----------|
| `GOLDAPI_IO_KEY` | gold-api.com | gold spot (consensus) |
| `METALS_API_KEY` | metals-api.com | gold spot (consensus) |
| `METALPRICEAPI_KEY` | metalpriceapi.com | gold spot (consensus) |
| `TWELVE_DATA_API_KEY` | twelvedata.com | OHLCV / FX |
| `ALPHA_VANTAGE_KEY` (or `_API_KEY`) | alphavantage.co | OHLCV fallback |
| `FINNHUB_API_KEY` | finnhub.io | quotes / news |
| `POLYGON_API_KEY` | polygon.io | quotes (optional) |
| `OANDA_API_TOKEN` + account id | OANDA | live broker prices + execution |

The multi-source feed order and symbols live in
`config/multi_source_feed.yaml` (failover chain alpha_vantage → twelve_data →
yfinance per the circuit breaker).

## 3. Optional deps for the free fallback + sentiment

These are intentionally optional; install them to enable the no-key fallback and
real news sentiment (otherwise they degrade to keyword-only / disabled):
```bash
pip install yfinance vaderSentiment feedparser
```
- `yfinance` → free Yahoo OHLCV fallback (`GC=F` for gold) — works with no key.
- `vaderSentiment` + `feedparser` → real news-sentiment scoring (you saw
  "VADER not available — keyword-only scoring" in the logs without these).

---

## Verifying real data is flowing

1. **Readiness** (needs Postgres + Redis for full green; SQLite/fakeredis is
   degraded): `curl localhost:8000/api/health/ready` → `ready: true`.
2. **Live tick**: `curl 'localhost:8000/api/data-layer/tick?symbol=XAU_USD'`
   → a real `mid` with `quality: good` and `tick_source_count > 1` (consensus).
3. **UI**: the amber *"No live broker feed — prices via REST"* banner disappears,
   the price ticker animates, and the dashboard panels (Microstructure, Order
   Book, Sentiment, Signals) leave their "Awaiting…" states.
4. **WS**: the `no_live_feed` flag flips false; price/equity/risk channels stream.

---

## Don't have/​want live feeds? Use the real-data backtest (now wired)

You don't need network or keys to exercise the full strategy → risk → execution
pipeline on **real historical gold data** — that path is now fixed:

```bash
python run.py --mode backtest                          # full file (data/XAUUSD_5Y.csv)
python run.py --mode backtest --start-date 2023-01-01 --end-date 2024-12-31
python run.py --mode backtest --data-file data/XAUUSD_2Y.csv
```
It prints return / max-drawdown / Sharpe / trades / win-rate. Reusable from CI
via `from backtesting.cli_runner import run_backtest`.

---

## Infra note (so the safety features are *actually* real)

Several safety/defense guarantees are Redis/Postgres-backed and silently degrade
to single-process fallbacks without them:
- cross-pod **kill switch** + breach propagation (Redis pub/sub)
- **at-least-once** outbox delivery (Redis)
- **self-healer** integrity manifest + **honeypot/lockdown** active defense (Redis)
- readiness `db_pool` (needs an **async** Postgres driver — or `aiosqlite` for dev)

For a real deployment: provision Postgres + Redis, set the keys above, allow
egress, and (for live trading) set `BROKER=oanda` with real OANDA credentials —
plus turn the ML safety gates to blocking (`DRIFT_BLOCK=true`,
`STALE_MODEL_BLOCK=true`) before risking capital.
