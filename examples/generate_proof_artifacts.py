#!/usr/bin/env python3
"""
Generate all proof-of-concept artifacts:
  - data/XAUUSD_2Y.csv          : 2 years of synthetic OHLCV (daily bars)
  - ml/saved_models/rf_xauusd.pkl: trained RandomForest signal classifier
  - examples/results/trades.csv  : per-trade log
  - examples/results/equity_curve.png
  - examples/results/performance.json
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "ml" / "saved_models"
RESULTS_DIR = ROOT / "examples" / "results"

for d in [DATA_DIR, MODEL_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ── 1. Synthetic XAUUSD dataset ───────────────────────────────────────────────

def generate_xauusd(start="2022-01-03", n_days=730, seed=42) -> pd.DataFrame:
    """
    Simulate 2 years of daily XAUUSD OHLCV.
    Uses geometric Brownian motion with realistic gold parameters:
      - annualised vol ~15%
      - slight upward drift ~5% p.a.
      - mean-reversion component (Ornstein-Uhlenbeck overlay)
    """
    rng = np.random.default_rng(seed)
    dt = 1 / 252          # daily step
    mu = 0.05             # annual drift
    sigma = 0.15          # annual vol
    theta = 0.03          # mean-reversion speed
    long_run = 2050.0     # long-run mean price

    dates = []
    d = datetime.strptime(start, "%Y-%m-%d")
    while len(dates) < n_days:
        if d.weekday() < 5:   # Mon–Fri only
            dates.append(d)
        d += timedelta(days=1)

    price = 1830.0
    rows = []
    for date in dates:
        # GBM + OU mean-reversion
        gbm = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rng.standard_normal()
        ou  = theta * (long_run - price) * dt
        price *= np.exp(gbm)
        price += ou

        # Intraday range: ~0.6% of price on average
        daily_range = price * rng.uniform(0.003, 0.012)
        direction   = rng.choice([-1, 1])
        open_  = price + direction * daily_range * rng.uniform(0, 0.3)
        close  = price
        high   = max(open_, close) + daily_range * rng.uniform(0.1, 0.5)
        low    = min(open_, close) - daily_range * rng.uniform(0.1, 0.5)
        volume = int(rng.integers(8_000, 35_000))

        rows.append({
            "date":   date.strftime("%Y-%m-%d"),
            "open":   round(open_, 2),
            "high":   round(high,  2),
            "low":    round(low,   2),
            "close":  round(close, 2),
            "volume": volume,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df


print("Generating XAUUSD dataset …")
df = generate_xauusd()
csv_path = DATA_DIR / "XAUUSD_2Y.csv"
df.to_csv(csv_path)
print(f"  Saved {len(df)} bars → {csv_path}")


# ── 2. Feature engineering ────────────────────────────────────────────────────

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    # Trend
    for n in [5, 10, 20, 50]:
        d[f"sma_{n}"] = d["close"].rolling(n).mean()
        d[f"ema_{n}"] = d["close"].ewm(span=n, adjust=False).mean()

    # Momentum
    d["rsi_14"] = _rsi(d["close"], 14)
    d["roc_5"]  = d["close"].pct_change(5)
    d["roc_20"] = d["close"].pct_change(20)

    # Volatility
    d["atr_14"]  = _atr(d, 14)
    d["bb_width"] = _bb_width(d["close"], 20, 2.0)

    # MACD
    ema12 = d["close"].ewm(span=12, adjust=False).mean()
    ema26 = d["close"].ewm(span=26, adjust=False).mean()
    d["macd"]        = ema12 - ema26
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"]   = d["macd"] - d["macd_signal"]

    # Price position
    d["close_vs_sma20"] = (d["close"] - d["sma_20"]) / d["sma_20"]
    d["close_vs_sma50"] = (d["close"] - d["sma_50"]) / d["sma_50"]

    # Volume
    d["vol_ratio"] = d["volume"] / d["volume"].rolling(20).mean()

    # Target: 1 if next-day close > today's close, else 0
    d["target"] = (d["close"].shift(-1) > d["close"]).astype(int)

    return d.dropna()


def _rsi(series, period):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df, period):
    hl  = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift()).abs()
    lpc = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _bb_width(series, period, std_mult):
    sma  = series.rolling(period).mean()
    std  = series.rolling(period).std()
    return (std_mult * std * 2) / sma


print("Engineering features …")
dff = add_features(df)

FEATURE_COLS = [
    "sma_5", "sma_10", "sma_20", "sma_50",
    "ema_5", "ema_10", "ema_20", "ema_50",
    "rsi_14", "roc_5", "roc_20",
    "atr_14", "bb_width",
    "macd", "macd_signal", "macd_hist",
    "close_vs_sma20", "close_vs_sma50",
    "vol_ratio",
]

X = dff[FEATURE_COLS].values
y = dff["target"].values
print(f"  {len(X)} samples, {len(FEATURE_COLS)} features, class balance: {y.mean():.2%} up-days")


# ── 3. Train RandomForest ─────────────────────────────────────────────────────

# Walk-forward split: train on first 70%, test on last 30%
split = int(len(X) * 0.70)
X_train, X_test = X[:split], X[split:]
y_train, y_test = y[:split], y[split:]

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s  = scaler.transform(X_test)

print("Training RandomForest …")
clf = RandomForestClassifier(
    n_estimators=200,
    max_depth=6,
    min_samples_leaf=10,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
)
clf.fit(X_train_s, y_train)

y_pred = clf.predict(X_test_s)
y_prob = clf.predict_proba(X_test_s)[:, 1]

report = classification_report(y_test, y_pred, target_names=["Down", "Up"], output_dict=True)
print(f"  Test accuracy: {report['accuracy']:.3f}")
print(f"  Up precision:  {report['Up']['precision']:.3f}  recall: {report['Up']['recall']:.3f}")

# Save model + scaler
model_path = MODEL_DIR / "rf_xauusd.pkl"
joblib.dump({"model": clf, "scaler": scaler, "features": FEATURE_COLS}, model_path)
print(f"  Saved model → {model_path}")


# ── 4. Backtest ───────────────────────────────────────────────────────────────

print("Running backtest …")

test_df   = dff.iloc[split:].copy()
test_df["signal_prob"] = y_prob
test_df["signal"]      = (y_prob > 0.52).astype(int)   # slight confidence threshold

INITIAL_CAPITAL = 100_000.0
POSITION_SIZE   = 0.10          # 10% of equity per trade
COMMISSION_PCT  = 0.0002        # 2 bps round-trip
STOP_LOSS_ATR   = 1.5           # stop = 1.5× ATR below entry
TAKE_PROFIT_ATR = 2.5           # TP  = 2.5× ATR above entry

equity   = INITIAL_CAPITAL
peak     = INITIAL_CAPITAL
trades   = []
equity_curve = [(test_df.index[0] - timedelta(days=1), equity)]

in_trade    = False
entry_price = 0.0
stop_price  = 0.0
tp_price    = 0.0
entry_date  = None
trade_size  = 0.0

for i, (date, row) in enumerate(test_df.iterrows()):
    if in_trade:
        # Check stop / TP on today's bar
        hit_stop = row["low"]  <= stop_price
        hit_tp   = row["high"] >= tp_price
        exit_price = None

        if hit_stop and hit_tp:
            # Both hit — assume stop first (conservative)
            exit_price = stop_price
        elif hit_stop:
            exit_price = stop_price
        elif hit_tp:
            exit_price = tp_price
        elif i == len(test_df) - 1:
            exit_price = row["close"]   # force close at end

        if exit_price is not None:
            pnl = (exit_price - entry_price) * trade_size
            commission = entry_price * trade_size * COMMISSION_PCT
            net_pnl = pnl - commission
            equity += net_pnl
            peak = max(peak, equity)

            trades.append({
                "entry_date":  entry_date.strftime("%Y-%m-%d"),
                "exit_date":   date.strftime("%Y-%m-%d"),
                "entry_price": round(entry_price, 2),
                "exit_price":  round(exit_price, 2),
                "stop_price":  round(stop_price, 2),
                "tp_price":    round(tp_price, 2),
                "size_oz":     round(trade_size, 4),
                "gross_pnl":   round(pnl, 2),
                "commission":  round(commission, 2),
                "net_pnl":     round(net_pnl, 2),
                "equity":      round(equity, 2),
                "result":      "win" if net_pnl > 0 else "loss",
            })
            equity_curve.append((date, equity))
            in_trade = False

    if not in_trade and row["signal"] == 1:
        atr = row["atr_14"]
        entry_price = row["close"]
        stop_price  = entry_price - STOP_LOSS_ATR   * atr
        tp_price    = entry_price + TAKE_PROFIT_ATR * atr
        trade_size  = (equity * POSITION_SIZE) / entry_price
        entry_date  = date
        in_trade    = True

trades_df = pd.DataFrame(trades)
eq_dates  = [e[0] for e in equity_curve]
eq_values = [e[1] for e in equity_curve]

# ── 5. Performance metrics ────────────────────────────────────────────────────

n_trades   = len(trades_df)
if n_trades > 0:
    wins       = (trades_df["net_pnl"] > 0).sum()
    win_rate   = wins / n_trades
    avg_win    = trades_df.loc[trades_df["net_pnl"] > 0, "net_pnl"].mean() if wins > 0 else 0
    avg_loss   = trades_df.loc[trades_df["net_pnl"] <= 0, "net_pnl"].mean() if (n_trades - wins) > 0 else 0
    profit_factor = (
        trades_df.loc[trades_df["net_pnl"] > 0, "net_pnl"].sum() /
        abs(trades_df.loc[trades_df["net_pnl"] <= 0, "net_pnl"].sum())
        if abs(trades_df.loc[trades_df["net_pnl"] <= 0, "net_pnl"].sum()) > 0 else float("inf")
    )
    total_return = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL
    # Max drawdown
    eq_series = pd.Series(eq_values)
    roll_max  = eq_series.cummax()
    drawdowns = (eq_series - roll_max) / roll_max
    max_dd    = drawdowns.min()
    # Annualised Sharpe (daily returns on equity curve)
    eq_s = pd.Series(eq_values, index=eq_dates)
    daily_ret = eq_s.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0
    # Calmar
    calmar = (total_return / abs(max_dd)) if max_dd != 0 else 0.0
else:
    win_rate = profit_factor = total_return = max_dd = sharpe = calmar = 0.0
    avg_win = avg_loss = 0.0

perf = {
    "dataset":          "XAUUSD_2Y synthetic (2022-01-03 – 2023-12-29)",
    "model":            "RandomForestClassifier (200 trees, depth 6)",
    "backtest_period":  f"{test_df.index[0].date()} – {test_df.index[-1].date()}",
    "initial_capital":  INITIAL_CAPITAL,
    "final_equity":     round(equity, 2),
    "total_return_pct": round(total_return * 100, 2),
    "n_trades":         n_trades,
    "win_rate_pct":     round(win_rate * 100, 2),
    "profit_factor":    round(profit_factor, 3),
    "avg_win_usd":      round(avg_win, 2),
    "avg_loss_usd":     round(avg_loss, 2),
    "max_drawdown_pct": round(max_dd * 100, 2),
    "sharpe_ratio":     round(sharpe, 3),
    "calmar_ratio":     round(calmar, 3),
    "ml_test_accuracy": round(report["accuracy"], 3),
    "ml_up_precision":  round(report["Up"]["precision"], 3),
    "ml_up_recall":     round(report["Up"]["recall"], 3),
}

perf_path = RESULTS_DIR / "performance.json"
with open(perf_path, "w") as f:
    json.dump(perf, f, indent=2)
print(f"  Saved performance → {perf_path}")

trades_path = RESULTS_DIR / "trades.csv"
if n_trades > 0:
    trades_df.to_csv(trades_path, index=False)
    print(f"  Saved {n_trades} trades → {trades_path}")

# ── 6. Equity curve plot ──────────────────────────────────────────────────────

fig, axes = plt.subplots(3, 1, figsize=(12, 10),
                          gridspec_kw={"height_ratios": [3, 1, 1]})
fig.suptitle("HOPEFX · XAUUSD RandomForest Strategy · Backtest Results",
             fontsize=14, fontweight="bold", y=0.98)

# Panel 1: equity curve
ax1 = axes[0]
ax1.plot(eq_dates, eq_values, color="#2196F3", linewidth=1.8, label="Strategy equity")
ax1.axhline(INITIAL_CAPITAL, color="#9E9E9E", linewidth=0.8, linestyle="--", label="Initial capital")
ax1.fill_between(eq_dates, INITIAL_CAPITAL, eq_values,
                 where=[v >= INITIAL_CAPITAL for v in eq_values],
                 alpha=0.15, color="#4CAF50")
ax1.fill_between(eq_dates, INITIAL_CAPITAL, eq_values,
                 where=[v < INITIAL_CAPITAL for v in eq_values],
                 alpha=0.15, color="#F44336")
ax1.set_ylabel("Portfolio Value (USD)")
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
ax1.legend(loc="upper left", fontsize=9)
ax1.grid(True, alpha=0.3)

# Annotate final return
ret_color = "#4CAF50" if total_return >= 0 else "#F44336"
ax1.annotate(
    f"Return: {total_return*100:+.1f}%\nSharpe: {sharpe:.2f}\nMax DD: {max_dd*100:.1f}%",
    xy=(0.02, 0.97), xycoords="axes fraction",
    va="top", fontsize=9,
    bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.8, edgecolor=ret_color),
)

# Panel 2: drawdown
ax2 = axes[1]
eq_s2 = pd.Series(eq_values, index=eq_dates)
roll_max2 = eq_s2.cummax()
dd_series = (eq_s2 - roll_max2) / roll_max2 * 100
ax2.fill_between(eq_dates, dd_series.values, 0, color="#F44336", alpha=0.5)
ax2.set_ylabel("Drawdown (%)")
ax2.set_ylim(min(dd_series.min() * 1.2, -1), 1)
ax2.grid(True, alpha=0.3)

# Panel 3: XAUUSD price
ax3 = axes[2]
ax3.plot(test_df.index, test_df["close"], color="#FF9800", linewidth=1.2)
if n_trades > 0:
    entry_dates = pd.to_datetime(trades_df["entry_date"])
    exit_dates  = pd.to_datetime(trades_df["exit_date"])
    win_mask    = trades_df["result"] == "win"
    ax3.scatter(entry_dates, trades_df["entry_price"],
                marker="^", color="#4CAF50", s=30, zorder=5, label="Entry")
    ax3.scatter(exit_dates[win_mask],  trades_df.loc[win_mask,  "exit_price"],
                marker="o", color="#2196F3", s=20, zorder=5, label="Win exit")
    ax3.scatter(exit_dates[~win_mask], trades_df.loc[~win_mask, "exit_price"],
                marker="x", color="#F44336", s=30, zorder=5, label="Loss exit")
    ax3.legend(loc="upper left", fontsize=8)
ax3.set_ylabel("XAUUSD (USD/oz)")
ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
ax3.grid(True, alpha=0.3)

for ax in axes:
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)

plt.tight_layout()
chart_path = RESULTS_DIR / "equity_curve.png"
plt.savefig(chart_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"  Saved equity curve → {chart_path}")

# ── 7. Print summary ──────────────────────────────────────────────────────────

print("\n" + "="*55)
print("  BACKTEST SUMMARY")
print("="*55)
for k, v in perf.items():
    print(f"  {k:<28} {v}")
print("="*55)
print("\nAll artifacts saved. Ready to commit.")
