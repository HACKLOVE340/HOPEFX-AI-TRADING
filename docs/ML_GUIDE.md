# ML Guide

> How to use, evaluate, retrain, and extend the HOPEFX ML pipeline.
> Last updated: 2026-04-01

---

## Production Model

The production model is `ml/saved_models/advanced_oos.pkl` — a calibrated XGBoost
stacking ensemble trained on 50 years of XAUUSD (GC=F) daily bars.

| Metric | Value |
|--------|-------|
| OOS accuracy | **66.4%** |
| p-value (one-sided binomial, H0: acc ≤ 0.5) | **p = 0.0000** |
| OOS period | 2019-04-12 → 2026-03-24 (1,260 bars, 7-year held-out) |
| Features | 176 stationary features |
| Abstain rate | 27.5% (model withholds signal on low-confidence bars) |
| Training data | 50 years XAUUSD (GC=F, 1974–2023) |
| Algorithm | XGBoost + LightGBM + RandomForest stacking ensemble + isotonic calibration |

The model abstains on 27.5% of bars. Only high-conviction signals reach execution.
This is why the win rate exceeds 50% — the model only acts when confident.

---

## Checking Model Status

```bash
# Via API
curl http://localhost:8000/api/ml/accuracy

# Expected response (production model loaded)
{
  "model_id": "advanced_oos",
  "accuracy": 0.664,
  "oos_bars": 1260,
  "p_value": 0.0,
  "features": 176,
  "ci_mode": false
}

# If model_id is "xgb_macro" or "fallback", the production model failed to load
# Check logs for the cause
```

```bash
# Via metadata sidecar (no unpickling needed)
cat ml/saved_models/advanced_oos_meta.json
```

---

## Running Inference

```bash
# Single prediction via API
curl -X POST http://localhost:8000/api/ml/predict/XAUUSD \
  -H "Authorization: Bearer $TOKEN"

# Response
{
  "symbol": "XAUUSD",
  "probability_up": 0.68,
  "direction": "BUY",
  "abstain": false,
  "model_id": "advanced_oos",
  "features_used": 176,
  "macro_features_present": true
}
```

```python
# Direct Python usage
from ml.live_inference import AdvancedModelPredictor
from ml.macro_store import MacroStore

predictor = AdvancedModelPredictor()
macro_store = MacroStore()

# Load OHLCV data
import pandas as pd
ohlcv_df = pd.read_csv("data/XAUUSD_H1.csv", index_col=0, parse_dates=True)

# Align macro features
macro_df = macro_store.align_to_hourly(ohlcv_df)

# Predict
result = predictor.predict_proba(ohlcv_df, macro_df=macro_df)
print(f"Direction: {result['direction']}")
print(f"Probability up: {result['probability_up']:.2%}")
print(f"Abstain: {result['abstain']}")
```

---

## Feature Categories

The 176 features are grouped into 7 categories. All are stationary (ADF + KPSS tested).

### Returns & Momentum (28 features)
```
returns_lag_1 ... returns_lag_20   — 1-day to 20-day lagged returns
log_ret_lag_1 ... log_ret_lag_5    — log return lags
roc_5, roc_10, roc_20              — rate of change
mom_roc                            — momentum rate of change
```

### Volatility (18 features)
```
atr_norm                           — ATR normalised by price
bb_width_z                         — Bollinger Band width z-score
hist_vol_5, hist_vol_20, hist_vol_60  — historical volatility
parkinson_vol                      — Parkinson volatility estimator
rvol_20, rvol_60                   — realised volatility
```

### Trend & Regime (14 features)
```
hurst_exp                          — Hurst exponent (fractal geometry)
frac_lyapunov_10                   — Lyapunov exponent (chaos measure)
frac_apen_10                       — approximate entropy
adx_norm                           — ADX normalised
regime_trending, regime_ranging    — regime labels (Hurst + ADX)
ri_bear_score, ri_bull_score       — regime bear/bull pressure composites
```

### MA Distances ATR-Normalised (16 features)
```
dist_ma_20, dist_ma_50, dist_ma_200   — distance from SMA (ATR units)
dist_ema_20, dist_ema_50, dist_ema_200 — distance from EMA (ATR units)
```

### COT Proxies (9 features)
```
cot_cb_buying_proxy    — central bank demand: gold up + DXY up + yields up
cot_geopolitical       — VIX spike + gold vs SPX divergence
cot_momentum           — COT momentum proxy
cot_net_long_proxy     — net long positioning proxy
```

### Macro Cross-Asset (22 features)
```
macro_dxy_ret          — DXY daily return
macro_vix_ret          — VIX daily return
macro_yield_spread_chg — 10Y–5Y yield spread change (^TNX - ^FVX)
macro_spx_ret          — SPX daily return
macro_gld_ret          — GLD ETF daily return
macro_gold_tailwind    — composite gold tailwind score
```

### Z-Scores (15 features)
```
close_z_20, close_z_50   — price z-score vs rolling mean
volume_z_20              — volume z-score
rsi_z                    — RSI z-score
```

---

## Training the Model

### Smoke Test (always run first)
```bash
# ~30 seconds, uses synthetic data, verifies the pipeline works
python ml/train_advanced.py --smoke
```

### Full Production Retrain
```bash
# 50 years of XAUUSD data, 3-year held-out OOS period
# Takes 10–30 minutes depending on hardware
python ml/train_advanced.py --years 50 --oos-years 3
```

Output files:
- `ml/saved_models/advanced_oos.pkl` — production model
- `ml/saved_models/advanced_oos_meta.json` — OOS metadata sidecar
- `ml/saved_models/feature_scaler.pkl` — feature scaler

### Basic Model (faster, fewer features)
```bash
# 65 features, macro walk-forward, ~5 minutes
python ml/train_with_macro.py --years 50 --oos-years 3
```

### Multi-Symbol Backtest
```bash
# 7 symbols, 10-year real data, accumulates N>919 trades
python backtest/multi_symbol_backtest.py --years 10 --oos-frac 0.3
```

---

## Walk-Forward Validation

The model is validated using expanding-window walk-forward:

```
Fold 1: Train 1974–2016 | OOS 2016–2019 (756 bars)
Fold 2: Train 1974–2019 | OOS 2019–2022 (756 bars)
Fold 3: Train 1974–2022 | OOS 2022–2025 (756 bars)
...
```

Each fold's OOS accuracy is reported. Consistent performance across folds
confirms the edge is not fold-specific.

The final held-out OOS period (2019–2026, 1,260 bars) is never used during
training — it's the true out-of-sample test.

---

## Online Learning

The `SklearnOnlineLearner` (SGDClassifier-backed) updates incrementally every
hour via `HourlyTrainer._online_update()`.

Enable:
```bash
ML_HOURLY_ENABLED=true
```

A daily EWC (Elastic Weight Consolidation) regime-adaptation loop runs at
00:05 UTC, adjusting the model's plasticity based on the detected market regime.

Learner state is persisted to `ml/saved_models/online_learner_{symbol}.pkl`.

Check status:
```bash
curl http://localhost:8000/api/online-learner/status \
  -H "Authorization: Bearer $TOKEN"
```

Submit a labelled sample:
```bash
curl -X POST http://localhost:8000/api/online-learner/partial-fit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "XAUUSD", "features": {...}, "label": 1}'
```

---

## Macro Features

Macro features (DXY, VIX, US10Y, US2Y, SPX, GLD) are fetched from yfinance
and stored in `data/macro/` CSVs.

At startup, `ml/macro_bootstrap.py` fetches the latest data (non-blocking,
skips if files are < 24 hours old). A daily 18:00 UTC background job keeps
them current.

At inference, `MacroStore.align_to_hourly(ohlcv_df)` forward-fills daily
macro values onto the hourly OHLCV index.

Check macro status:
```bash
curl http://localhost:8000/api/macro/snapshot \
  -H "Authorization: Bearer $TOKEN"
```

Force a macro refresh:
```bash
python -m ml.macro_bootstrap
```

---

## Fallback Behaviour

If `advanced_oos.pkl` fails to load, the system falls back to `xgb_macro.pkl`
(65 features, ~50% OOS accuracy — no demonstrated edge).

When the fallback activates:
1. `CRITICAL` log: `ML model degraded — fallback active`
2. Sentry fatal-level issue fired via `capture_ml_fallback_event()`
3. Discord critical alert via `discord_signal_bot.post_ml_fallback_alert()`

The fallback model has all `close_lag_N` non-stationary features removed.
It will not blow up, but it has no demonstrated edge. Fix the production
model as soon as possible.

---

## Research Pipeline

Four research phases are wired in `core/signal_engine.py` and activate
after their respective paper trading gates are met.

| Phase | Component | Flag | Gate |
|-------|-----------|------|------|
| 1 | MTFFusionStore | `FEATURE_MTF_FUSION` | On by default |
| 2 | AnomalyWeightStore | `FEATURE_ANOMALY_WEIGHTING` | After 30-day paper run |
| 3 | OnlineLearnerStore | `FEATURE_ONLINE_LEARNING` | After 90-day paper run + 500 fills |
| 4 | DeepEnsembleStore | `FEATURE_DEEP_ENSEMBLE` | After LSTM OOS ≥ 70% |

The LSTM signal layer (`ml/lstm_signal_layer.py`) is wired as an optional
signal in `HOPEFXBrain`. Enable with `LSTM_SIGNAL_ENABLED=true`.

See `research/README.md` for gate conditions and enable instructions.

---

## Interpreting Results

### OOS Accuracy
The primary credible metric. 66.4% on 1,260 held-out bars with p=0.0000
means the model has a statistically significant edge above chance.

### Sharpe Ratio
Only meaningful when N ≥ 600 trades (SE ≤ ±0.10). With N=48 backtest trades,
SE ≈ ±0.21 — not statistically robust. Use OOS accuracy as the primary metric.

### Abstain Rate
27.5% of bars produce no signal. This is intentional — the model only acts
when confident. A lower abstain rate means more signals but lower average confidence.

### p-value
One-sided binomial test: H0 = accuracy ≤ 0.5 (no edge). p=0.0000 means the
probability of achieving 66.4% accuracy by chance is essentially zero.

---

## Adding New Features

To add a feature to the pipeline:

1. Add the feature computation to `ml/advanced_features.py`:
```python
def add_my_feature(df: pd.DataFrame) -> pd.DataFrame:
    df['my_feature'] = ...  # must be stationary
    return df
```

2. Call it in `FeatureEngineer.create_features()` in `ml/training.py`

3. Verify stationarity:
```python
from ml.training import StationarityTester
tester = StationarityTester()
result = tester.test(df['my_feature'])
print(f"Stationary: {result.is_stationary}")
```

4. Retrain and compare OOS accuracy:
```bash
python ml/train_advanced.py --years 50 --oos-years 3
```

Only add the feature if OOS accuracy improves. Never add non-stationary features
(raw price levels, cumulative sums) — they have no predictive value for direction.
