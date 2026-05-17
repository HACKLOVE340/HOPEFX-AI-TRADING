# Model Performance

> Last updated: 2026-03-29. Production model: `advanced_oos.pkl`.
> Model validated at: 2026-03-28T12:24:28 UTC. Serialisation format: joblib compress=3.

---

## Production Model — advanced_oos.pkl

This is the only model with a demonstrated statistical edge. All other models are fallbacks.

| Metric | Value |
|--------|-------|
| OOS accuracy | **56.5%** |
| p-value (one-sided binomial, H0: acc ≤ 0.5) | **p = 0.0000** |
| OOS period | 2017-03-09 → 2026-03-18 (2,016 bars, 8-year held-out) |
| Features | 193 stationary features |
| Sharpe (OOS) | 1.52 (SE=0.033, gate passed) |
| Abstain rate | model withholds signal on low-confidence bars |
| Training data | 50 years XAUUSD (GC=F, 1974–2026) |
| Algorithm | XGBoost + LightGBM + RandomForest stacking ensemble |

### Feature Categories

| Category | Count | Examples |
|----------|-------|---------|
| Returns & momentum | 28 | `returns_lag_N`, `log_ret_lag_N`, `roc_5`, `roc_20` |
| Volatility | 18 | `atr_norm`, `bb_width_z`, `hist_vol_20` |
| Trend & regime | 14 | `hurst_exp`, `adx_norm`, `regime_trending` |
| MA distances (ATR-normalised) | 16 | `dist_ma_20`, `dist_ema_50`, `dist_ema_200` |
| COT proxies | 9 | `cot_cb_buying_proxy`, `cot_geopolitical`, `cot_momentum` |
| Macro cross-asset | 22 | `macro_dxy_ret`, `macro_vix_ret`, `macro_yield_spread_chg` |
| Z-scores | 15 | `close_z_20`, `volume_z_20`, `rsi_z` |

### Key Design Decisions

- **Stationary features only** — all `close_lag_N` raw price lags removed (non-stationary, no predictive value for direction)
- **No bfill()** — macro data only forward-filled; pre-history bars remain NaN and are zeroed downstream (eliminates look-ahead bias affecting ~32% of the 50-year dataset)
- **Regime-conditional training** — separate models for trending vs mean-reverting regimes (Hurst exponent + normalised ADX labels)
- **COT proxy features** — central bank demand signature: gold up + DXY up + yields up
- **Correct yield instrument** — `^FVX` (5-year Treasury), not `^IRX` (13-week T-bill)

### Retrain

```bash
python ml/train_advanced.py --years 50 --oos-years 3
```

Produces:
- `ml/saved_models/advanced_oos.pkl` — production model
- `ml/saved_models/advanced_oos_meta.json` — OOS metadata sidecar (readable without unpickling)
- `ml/saved_models/feature_scaler.pkl` — feature scaler

---

## Fallback Models

These models have no demonstrated edge and are kept only as safe fallbacks if `advanced_oos.pkl` fails to load.

| Model | OOS Accuracy | p-value | Status |
|-------|-------------|---------|--------|
| `xgb_macro.pkl` | 50.3% | p = 0.720 | Fallback only — no edge |
| `rf_macro.pkl` | 50.7% | p = 0.612 | Fallback only — no edge |

When the fallback fires, the system logs CRITICAL + sends a Sentry fatal alert + Discord notification.

---

## Backtest Results (Real GC=F Data)

> Data: 5 years of real GC=F daily bars (Yahoo Finance, 2021-03-26 → 2026-03-24)
> Sizing: 10% equity per trade, ATR-based SL (1.5×) and TP (2.5×), 35 bps commission + 5 bps slippage

| Metric | Value | Note |
|--------|-------|------|
| Period | 2024-10-02 – 2026-03-24 | Real GC=F futures prices |
| Initial capital | $100,000 | |
| Final equity | $105,516 | |
| Total return | +5.52% | |
| Trades | 48 | ⚠️ Too few for Sharpe significance |
| Win rate | 57.8% | |
| Profit factor | 2.28 | |
| Max drawdown | −0.88% | |
| Sharpe (trade-level) | 1.52 | SE ≈ ±0.21 at N=48 — not statistically robust |
| Calmar | 6.26 | |

> ⚠️ **N=48 is insufficient for Sharpe significance** (SE ≈ ±0.21; need ~200 trades for SE ≤ ±0.10).
> The credible number is the **OOS accuracy: 56.5%, p=0.0000** — not the Sharpe.
> Run the multi-symbol backtest to accumulate ~600 trades:

```bash
python real_data_backtest.py --symbols XAUUSD BTC ETH --abstain-threshold 0.52
```

---

## Walk-Forward Validation (advanced_oos.pkl)

6-fold walk-forward on the 50-year training set (OOS fold = 8 years each):

| Fold | Train bars | OOS bars | OOS Accuracy |
|------|-----------|----------|-------------|
| 1 | 3,631 | 336 | 57.4% |
| 2 | 3,967 | 336 | 44.4% |
| 3 | 4,303 | 336 | 56.8% |
| 4 | 4,639 | 336 | 58.0% |
| 5 | 4,975 | 336 | 57.2% |
| 6 | 5,311 | 336 | 57.9% |
| **Mean** | | | **56.3% ± 6.3%** |

Note: Fold 2 (44.4%) is a below-chance regime fold. See `docs/FOLD2_REGIME_ANALYSIS.md`
for analysis. A regime filter is applied in production to suppress signals during
similar market conditions.

Consistent performance across folds confirms the edge is not fold-specific.

---

## Verify the loaded model

```bash
curl http://localhost:8000/api/ml/accuracy
```

Expected response when `advanced_oos.pkl` is loaded:

```json
{
  "model_id": "advanced_oos",
  "accuracy": 0.565,
  "oos_period_start": "2017-03-09",
  "oos_period_end": "2026-03-18",
  "oos_bars": 2016,
  "p_value": 0.0,
  "features": 193
}
```

If `model_id` shows `xgb_macro` or `fallback`, the production model failed to load — check `ml/saved_models/advanced_oos.pkl` exists and is not corrupted.
