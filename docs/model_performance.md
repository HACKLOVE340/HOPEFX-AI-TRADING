# Model Performance

Last trained: 2026-03-25 on 8 years of XAUUSD daily data (GC=F, 2018–2026).

## Training Configuration

| Parameter | Value |
|-----------|-------|
| Symbol | GC=F (XAUUSD proxy) |
| Years of data | 8 |
| Total samples | 1,961 bars |
| Features | 85 (OHLCV indicators + macro) |
| Macro features | DXY, VIX, 10Y/2Y yields, SPX, Gold ETF |
| Walk-forward folds | 5 |

## Walk-Forward Results

### XGBoost

| Fold | Train | Test | Accuracy | F1 |
|------|-------|------|----------|----|
| 1 | 331 | 326 | 45.1% | 0.389 |
| 2 | 657 | 326 | 53.7% | 0.620 |
| 3 | 983 | 326 | 52.8% | 0.458 |
| 4 | 1,309 | 326 | 50.3% | 0.434 |
| 5 | 1,635 | 326 | 52.5% | 0.606 |
| **Mean** | | | **50.9% ± 3.1%** | **0.501** |

Final holdout (80/20 split): **53.7% accuracy, F1=0.606**

### Random Forest

| Fold | Train | Test | Accuracy | F1 |
|------|-------|------|----------|----|
| 1 | 331 | 326 | 46.6% | 0.356 |
| 2 | 657 | 326 | 53.1% | 0.647 |
| 3 | 983 | 326 | 53.7% | 0.552 |
| 4 | 1,309 | 326 | 40.8% | 0.157 |
| 5 | 1,635 | 326 | 55.8% | 0.695 |
| **Mean** | | | **50.0% ± 5.5%** | **0.481** |

Final holdout (80/20 split): **56.5% accuracy, F1=0.687**

## Top Features (RF)

1. `macro_gold_etf_ret` — Gold ETF daily return
2. `macro_spx_ret` — S&P 500 daily return
3. `returns` — XAUUSD daily return
4. `macro_vix_ret` — VIX daily change
5. `log_returns` — Log return

Macro features dominate the top-5, confirming that gold direction is driven more by risk-off flows than by price patterns alone.

## Saved Models

- `ml/saved_models/xgb_macro.pkl`
- `ml/saved_models/rf_macro.pkl`
- `ml/saved_models/training_report.json`

## Retrain

```bash
python ml/train_with_macro.py --years 8
```
