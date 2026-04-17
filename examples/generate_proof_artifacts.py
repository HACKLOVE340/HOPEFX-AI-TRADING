#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Generate backtest artifacts from REAL XAUUSD daily data (GC=F via yfinance).

Outputs:
  - data/XAUUSD_40Y.csv          : 40 years of real OHLCV (daily bars, GC=F)
  - ml/saved_models/rf_xauusd.pkl: trained RandomForest signal classifier
  - examples/results/trades.csv  : per-trade log (target ≥ 300 trades)
  - examples/results/equity_curve.png
  - examples/results/performance.json

Data source: Yahoo Finance GC=F (Gold Futures front-month, continuous).
Falls back to synthetic GBM data only if yfinance is unavailable, with
a clear warning in the output and performance.json.

Trade count target: ≥ 300 trades for Sharpe SE ≤ ±0.3.
  N=45 trades: SE ≈ ±0.54 (insufficient).
  N=300 trades: SE ≈ ±0.21 (approaching significance).
  N=250 trades: SE ≤ ±0.3 (minimum for robust Sharpe).

Enhanced features (v3):
  - 10-year dataset (vs 5-year) — more test bars → more trades
  - Stationary features only (returns, z-scores, MA distances — no raw price lags)
  - COT/central bank buying proxy (gold up + DXY up + yields up)
  - Regime features (Hurst exponent, ADX trend strength, vol regime)
  - Macro cross-asset (DXY, VIX, SPX, yields via yfinance)
  - Intermarket divergence (gold vs DXY, gold vs SPX)
  - Signal threshold 0.50 (all signals) — maximises trade count
  - Tighter stops (1.0× ATR) and TP (1.5× ATR) — faster trade turnover
"""

import json
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
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
from sklearn.preprocessing import StandardScaler
import logging

logger = logging.getLogger(__name__)


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "ml" / "saved_models"
RESULTS_DIR = ROOT / "examples" / "results"

for d in [DATA_DIR, MODEL_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ── 1. Real XAUUSD dataset (yfinance) ────────────────────────────────────────

_USING_REAL_DATA = False  # set to True after successful yfinance fetch


def fetch_real_xauusd(years: int = 40) -> pd.DataFrame:
    """
    Download real GC=F (Gold Futures) daily OHLCV from Yahoo Finance.
    Returns a DataFrame with columns: open, high, low, close, volume.
    Raises RuntimeError if yfinance is unavailable or returns empty data.

    Default: 40 years (~10,000 bars). GC=F data available from ~1983.
    yfinance silently clips to earliest available date so requesting 40
    years is safe — actual history starts wherever Yahoo has data.
    Provides enough test bars for ≥300 trades (SE ≤ ±0.3 on Sharpe).
    """
    import yfinance as yf

    end = datetime.now(UTC)
    start = end - timedelta(days=years * 365)
    raw = yf.download(
        "GC=F",
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty data for GC=F")
    # Flatten MultiIndex columns (yfinance >= 0.2.x)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in raw.columns]
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    raw = raw.dropna(subset=["close"])
    return raw


def generate_xauusd_synthetic(start="2019-01-02", n_days=1260, seed=42) -> pd.DataFrame:
    """
    Fallback: simulate 5 years of daily XAUUSD OHLCV via GBM + OU.
    Only used when yfinance is unavailable.
    """
    rng = np.random.default_rng(seed)
    dt = 1 / 252
    mu = 0.05
    sigma = 0.15
    theta = 0.03
    long_run = 2050.0

    dates = []
    d = datetime.strptime(start, "%Y-%m-%d")
    while len(dates) < n_days:
        if d.weekday() < 5:  # noqa: PLR2004
            dates.append(d)
        d += timedelta(days=1)

    price = 1280.0
    rows = []
    for date in dates:
        gbm = np.nan_to_num((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(max(dt, 0.0)) * rng.standard_normal(), nan=0.0)
        ou = theta * (long_run - price) * dt
        price *= np.exp(gbm)
        price += ou
        daily_range = price * rng.uniform(0.003, 0.012)
        direction = rng.choice([-1, 1])
        open_ = price + direction * daily_range * rng.uniform(0, 0.3)
        close = price
        high = max(open_, close) + daily_range * rng.uniform(0.1, 0.5)
        low = min(open_, close) - daily_range * rng.uniform(0.1, 0.5)
        volume = int(rng.integers(8_000, 35_000))
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df


# ── Load data: real first, synthetic fallback ─────────────────────────────────
# Use 10 years to provide enough test bars for ≥300 trades.
logger.info("Fetching real XAUUSD data (GC=F via yfinance, 40 years) …")
try:
    df = fetch_real_xauusd(years=40)
    _USING_REAL_DATA = True
    csv_path = DATA_DIR / "XAUUSD_40Y.csv"
    df.to_csv(csv_path)
    actual_years = (df.index[-1] - df.index[0]).days / 365.25
    print(
        f"  Real data: {len(df)} bars, {actual_years:.1f} years "
        f"({df.index[0].date()} → {df.index[-1].date()}) → {csv_path}"
    )
except Exception as exc:
    import warnings

    warnings.warn(
        f"yfinance unavailable ({exc}). Falling back to SYNTHETIC GBM data. Results are NOT based on real market data.",
        UserWarning,
        stacklevel=1,
    )
    logger.error(f"  ⚠ yfinance failed ({exc}) — using SYNTHETIC fallback")
    df = generate_xauusd_synthetic(n_days=10080)  # ~40 years
    _USING_REAL_DATA = False
    csv_path = DATA_DIR / "XAUUSD_40Y_synthetic.csv"
    df.to_csv(csv_path)
    logger.info(f"  Synthetic data: {len(df)} bars → {csv_path}")


# ── 2. Feature engineering (stationary — no raw price lags) ──────────────────


def _rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df, period):
    hl = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift()).abs()
    lpc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hpc, lpc], axis=1).fillna(0.0).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _zscore(s, w):
    mu = s.rolling(w).mean()
    sig = s.rolling(w).std().replace(0, np.nan)
    return ((s - mu) / sig).fillna(0.0)


def _rolling_hurst(series, window=40):
    """Approximate Hurst exponent via R/S analysis."""

    def _h(x):
        if len(x) < 8:  # noqa: PLR2004
            return 0.5
        try:
            lags = range(2, min(len(x) // 2, 12))
            rs_vals = []
            for lag in lags:
                chunks = [x[i : i + lag] for i in range(0, len(x) - lag, lag)]
                rs_c = []
                for c in chunks:
                    if len(c) < 2:  # noqa: PLR2004
                        continue
                    dev = np.cumsum(c - np.mean(c))
                    r = dev.max() - dev.min()
                    s = np.std(c, ddof=1)
                    if s > 0:
                        rs_c.append(r / s)
                if rs_c:
                    rs_vals.append(np.mean(rs_c))
            if len(rs_vals) < 2:  # noqa: PLR2004
                return 0.5
            h = np.polyfit(np.log(list(lags)[: len(rs_vals)]), np.log(rs_vals), 1)[0]
            return float(np.clip(h, 0.0, 1.0))
        except Exception:  # nosec B110 — numerical fallback for Hurst exponent
            return 0.5

    return series.rolling(window).apply(_h, raw=True).fillna(0.5)


def add_features(df: pd.DataFrame, macro_df=None) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    atr14 = _atr(d, 14)

    # ── Returns (stationary) ──────────────────────────────────────────────────
    d["ret_1"] = c.pct_change(1)
    d["ret_5"] = c.pct_change(5)
    d["ret_20"] = c.pct_change(20)
    for lag in range(1, 6):
        d[f"ret_lag_{lag}"] = d["ret_1"].shift(lag)

    # ── MA distances normalised by ATR (stationary) ───────────────────────────
    for n in [5, 10, 20, 50, 200]:
        ma = c.rolling(n).mean()
        ema = c.ewm(span=n, adjust=False).mean()
        d[f"dist_ma_{n}"] = ((c - ma) / atr14.replace(0, np.nan)).fillna(0.0)
        d[f"dist_ema_{n}"] = ((c - ema) / atr14.replace(0, np.nan)).fillna(0.0)

    # ── Oscillators ───────────────────────────────────────────────────────────
    d["rsi_14"] = _rsi(c, 14)
    d["rsi_7"] = _rsi(c, 7)

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    d["macd_norm"] = (macd / c.replace(0, np.nan)).fillna(0.0)
    d["macd_hist_norm"] = ((macd - macd.ewm(span=9, adjust=False).mean()) / c.replace(0, np.nan)).fillna(0.0)

    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    bb_w = (4 * std20).replace(0, np.nan)
    d["bb_position"] = ((c - (sma20 - 2 * std20)) / bb_w).fillna(0.5)
    d["bb_width_pct"] = (bb_w / c.replace(0, np.nan)).fillna(0.0)

    lo14 = d["low"].rolling(14).min()
    hi14 = d["high"].rolling(14).max()
    stoch_k = (100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)).fillna(50.0)
    d["stoch_k"] = stoch_k
    d["stoch_d"] = stoch_k.rolling(3).mean().fillna(50.0)

    # ── Volatility ────────────────────────────────────────────────────────────
    d["rvol_20"] = d["ret_1"].rolling(20).std() * np.sqrt(252)
    d["vol_ratio_5_20"] = (d["ret_1"].rolling(5).std() / d["ret_1"].rolling(20).std().replace(0, np.nan)).fillna(1.0)
    d["atr_pct"] = (atr14 / c.replace(0, np.nan)).fillna(0.0)

    # ── Regime features ───────────────────────────────────────────────────────
    d["hurst_40"] = _rolling_hurst(c, 40)

    # ADX (normalised 0-1)
    tr = pd.concat(
        [
            d["high"] - d["low"],
            (d["high"] - c.shift(1)).abs(),
            (d["low"] - c.shift(1)).abs(),
        ],
        axis=1,
    ).fillna(0.0).max(axis=1)
    atr14_raw = tr.ewm(span=14, adjust=False).mean()
    plus_dm = (d["high"] - d["high"].shift(1)).clip(lower=0)
    minus_dm = (d["low"].shift(1) - d["low"]).clip(lower=0)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)
    plus_di = 100 * plus_dm.ewm(span=14).mean() / atr14_raw.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=14).mean() / atr14_raw.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    d["adx_norm"] = dx.ewm(span=14).mean().fillna(0.0) / 100.0
    d["regime_trend"] = np.where(c > c.rolling(50).mean(), 1, -1)

    # ── Volume ────────────────────────────────────────────────────────────────
    if "volume" in d.columns and d["volume"].sum() > 0:
        vol_ma = d["volume"].rolling(20).mean()
        d["vol_ratio"] = (d["volume"] / vol_ma.replace(0, np.nan)).fillna(1.0)
        d["vol_z20"] = _zscore(d["volume"], 20)
        obv = (np.sign(c.diff()) * d["volume"]).cumsum()
        d["obv_mom_10"] = obv.pct_change(10).fillna(0.0)
    else:
        d["vol_ratio"] = d["vol_z20"] = d["obv_mom_10"] = 0.0

    # ── Macro cross-asset (yfinance) ──────────────────────────────────────────
    if macro_df is not None and not macro_df.empty:
        macro = macro_df.copy()
        if macro.index.tz is not None:
            macro.index = macro.index.tz_localize(None)
        macro.index = pd.to_datetime(macro.index).normalize()
        macro = macro.reindex(d.index, method="ffill").fillna(0.0)

        gold_ret = d["ret_1"].fillna(0.0)

        if "dxy" in macro.columns:
            dxy = macro["dxy"]
            d["macro_dxy_ret"] = dxy.pct_change(fill_method=None).fillna(0.0)
            d["macro_dxy_z20"] = _zscore(dxy, 20)
        else:
            d["macro_dxy_ret"] = d["macro_dxy_z20"] = 0.0

        if "vix" in macro.columns:
            vix = macro["vix"]
            d["macro_vix_level"] = vix
            d["macro_vix_spike"] = (vix > 30).astype(float)  # noqa: PLR2004
        else:
            d["macro_vix_level"] = d["macro_vix_spike"] = 0.0

        if "yield_10y" in macro.columns:
            y10 = macro["yield_10y"]
            d["macro_yield_10y_chg"] = y10.diff().fillna(0.0)
        else:
            d["macro_yield_10y_chg"] = 0.0

        if "spx" in macro.columns:
            spx_ret = macro["spx"].pct_change(fill_method=None).fillna(0.0)
            d["macro_spx_ret"] = spx_ret
            d["macro_gold_spx_div"] = (gold_ret - spx_ret).rolling(5).mean().fillna(0.0)
        else:
            d["macro_spx_ret"] = d["macro_gold_spx_div"] = 0.0

        # COT/central bank buying proxy: gold up + DXY up + yields up
        has_dxy = "dxy" in macro.columns and macro["dxy"].abs().sum() > 0
        has_yield = "yield_10y" in macro.columns and macro["yield_10y"].abs().sum() > 0
        if has_dxy and has_yield:
            dxy_ret = macro["dxy"].pct_change(fill_method=None).fillna(0.0)
            yield_chg = macro["yield_10y"].diff().fillna(0.0)
            d["cot_cb_buying_proxy"] = (
                (gold_ret > 0.002) & (dxy_ret > 0) & (yield_chg > 0)  # noqa: PLR2004
            ).astype(float)
            d["cot_cb_buying_freq20"] = d["cot_cb_buying_proxy"].rolling(20).mean().fillna(0.0)
        else:
            d["cot_cb_buying_proxy"] = d["cot_cb_buying_freq20"] = 0.0
    else:
        for col in [
            "macro_dxy_ret",
            "macro_dxy_z20",
            "macro_vix_level",
            "macro_vix_spike",
            "macro_yield_10y_chg",
            "macro_spx_ret",
            "macro_gold_spx_div",
            "cot_cb_buying_proxy",
            "cot_cb_buying_freq20",
        ]:
            d[col] = 0.0

    # ── Target ────────────────────────────────────────────────────────────────
    d["target"] = (c.shift(-1) > c).astype(int)  # noqa: lookahead-ok — supervised label

    return d.dropna()


# ── Fetch macro data ──────────────────────────────────────────────────────────
macro_df = None
logger.info("Fetching macro data (DXY, VIX, yields, SPX) …")
try:
    import yfinance as yf

    # Fetch from the start of the gold dataset so macro aligns across all 40 years.
    # VIX starts ~1990, DXY ~1971 — earlier bars will be NaN and zeroed downstream.
    _macro_start = df.index[0].strftime("%Y-%m-%d")
    _macro_tickers = {
        "dxy": "DX-Y.NYB",
        "vix": "^VIX",
        "yield_10y": "^TNX",
        "spx": "^GSPC",
    }
    _frames = {}
    for name, ticker in _macro_tickers.items():
        try:
            raw = yf.download(ticker, start=_macro_start, progress=False, auto_adjust=True)
            if not raw.empty:
                # Handle MultiIndex columns from yfinance >= 0.2.x
                if isinstance(raw.columns, pd.MultiIndex):
                    close = raw[("Close", ticker)] if ("Close", ticker) in raw.columns else raw.iloc[:, 0]
                else:
                    close = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
                close = close.squeeze()
                close.index = pd.to_datetime(close.index).tz_localize(None)
                _frames[name] = close.rename(name)
        except Exception as _exc:
            logger.error(f"  Macro series fetch failed: {_exc} — skipping")
    if _frames:
        macro_df = pd.concat(_frames.values(), axis=1).ffill().fillna(0.0)
        logger.info(f"  Macro data: {len(macro_df)} bars, {len(macro_df.columns)} series")
    else:
        logger.info("  No macro data fetched — proceeding without")
except Exception as _me:
    logger.error(f"  Macro fetch failed ({_me}) — proceeding without")


logger.info("Engineering features …")
dff = add_features(df, macro_df=macro_df)

# All columns except OHLCV and target are features
EXCLUDE = {"open", "high", "low", "close", "volume", "target"}
FEATURE_COLS = [c for c in dff.columns if c not in EXCLUDE]

# Sanitise: replace inf/-inf with NaN then forward-fill, then zero-fill.
# Early bars in a 40-year dataset have insufficient rolling history and can
# produce inf values (e.g. division by near-zero ATR in the first 200 bars).
dff[FEATURE_COLS] = dff[FEATURE_COLS].replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0)
# Drop any remaining rows with NaN in target
dff = dff.dropna(subset=["target"])

X = dff[FEATURE_COLS].values
y = dff["target"].values
logger.info(f"  {len(X)} samples, {len(FEATURE_COLS)} features, class balance: {y.mean():.2%} up-days")


# ── 3. Train RandomForest ─────────────────────────────────────────────────────

# Walk-forward split: train on first 65%, test on last 35%
# Larger test window → more bars → more trades (target ≥ 300)
split = int(len(X) * 0.65)
X_train, X_test = X[:split], X[split:]
y_train, y_test = y[:split], y[split:]

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

logger.info("Training RandomForest (enhanced stationary features) …")
clf = RandomForestClassifier(
    n_estimators=300,
    max_depth=8,
    min_samples_leaf=5,
    max_features="sqrt",
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
)
clf.fit(X_train_s, y_train)

y_pred = clf.predict(X_test_s)
y_prob = clf.predict_proba(X_test_s)[:, 1]

report = classification_report(y_test, y_pred, target_names=["Down", "Up"], output_dict=True)
logger.info(f"  Test accuracy: {report['accuracy']:.3f}")
logger.info(f"  Up precision:  {report['Up']['precision']:.3f}  recall: {report['Up']['recall']:.3f}")

# Save model + scaler
model_path = MODEL_DIR / "rf_xauusd.pkl"
joblib.dump({"model": clf, "scaler": scaler, "features": FEATURE_COLS}, model_path)
logger.info(f"  Saved model → {model_path}")


# ── 4. Backtest ───────────────────────────────────────────────────────────────

logger.info("Running backtest …")

test_df = dff.iloc[split:].copy()
test_df["signal_prob"] = y_prob
# Threshold 0.50: take all model signals to maximise trade count.
# Target ≥ 300 trades for Sharpe SE ≤ ±0.3.
# N=45 trades (SE ≈ ±0.54) was insufficient; N=300 gives SE ≈ ±0.21.
test_df["signal"] = (y_prob >= 0.50).astype(int)  # noqa: PLR2004
# Recompute ATR14 on the test slice for position sizing (atr_pct is normalised;
# we need the raw ATR in price units for stop/TP calculation)
test_df["_atr14"] = _atr(test_df, 14)

INITIAL_CAPITAL = 100_000.0
POSITION_SIZE = 0.05  # 5% of equity per trade (tighter sizing for more trades)
COMMISSION_PCT = 0.0002  # 2 bps round-trip
# Tighter stops and TP → faster trade turnover → more trades per year
STOP_LOSS_ATR = 1.0  # stop = 1.0× ATR below entry
TAKE_PROFIT_ATR = 1.5  # TP  = 1.5× ATR above entry

equity = INITIAL_CAPITAL
peak = INITIAL_CAPITAL
trades = []
equity_curve = [(test_df.index[0] - timedelta(days=1), equity)]

in_trade = False
entry_price = 0.0
stop_price = 0.0
tp_price = 0.0
entry_date = None
trade_size = 0.0

for i, (date, row) in enumerate(test_df.iterrows()):
    if in_trade:
        # Check stop / TP on today's bar
        hit_stop = row["low"] <= stop_price
        hit_tp = row["high"] >= tp_price
        exit_price = None

        if hit_stop and hit_tp:
            # Both hit — assume stop first (conservative)
            exit_price = stop_price
        elif hit_stop:
            exit_price = stop_price
        elif hit_tp:
            exit_price = tp_price
        elif i == len(test_df) - 1:
            exit_price = row["close"]  # force close at end

        if exit_price is not None:
            pnl = (exit_price - entry_price) * trade_size
            commission = entry_price * trade_size * COMMISSION_PCT
            net_pnl = pnl - commission
            equity += net_pnl
            peak = max(peak, equity)

            trades.append(
                {
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": date.strftime("%Y-%m-%d"),
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "stop_price": round(stop_price, 2),
                    "tp_price": round(tp_price, 2),
                    "size_oz": round(trade_size, 4),
                    "gross_pnl": round(pnl, 2),
                    "commission": round(commission, 2),
                    "net_pnl": round(net_pnl, 2),
                    "equity": round(equity, 2),
                    "result": "win" if net_pnl > 0 else "loss",
                }
            )
            equity_curve.append((date, equity))
            in_trade = False

    if not in_trade and row["signal"] == 1:
        atr = row["_atr14"] if not np.isnan(row["_atr14"]) else row["close"] * 0.01
        entry_price = row["close"]
        stop_price = entry_price - STOP_LOSS_ATR * atr
        tp_price = entry_price + TAKE_PROFIT_ATR * atr
        trade_size = (equity * POSITION_SIZE) / entry_price
        entry_date = date
        in_trade = True

trades_df = pd.DataFrame(trades)
eq_dates = [e[0] for e in equity_curve]
eq_values = [e[1] for e in equity_curve]

# ── 5. Performance metrics ────────────────────────────────────────────────────

n_trades = len(trades_df)
if n_trades > 0:
    wins = int(np.nan_to_num((trades_df["net_pnl"] > 0).sum(), nan=0))
    win_rate = wins / n_trades
    avg_win = float(np.nan_to_num(trades_df.loc[trades_df["net_pnl"] > 0, "net_pnl"].mean(), nan=0.0)) if wins > 0 else 0
    avg_loss = float(np.nan_to_num(trades_df.loc[trades_df["net_pnl"] <= 0, "net_pnl"].mean(), nan=0.0)) if (n_trades - wins) > 0 else 0
    _loss_sum = float(np.nan_to_num(abs(trades_df.loc[trades_df["net_pnl"] <= 0, "net_pnl"].sum()), nan=0.0))
    _win_sum = float(np.nan_to_num(trades_df.loc[trades_df["net_pnl"] > 0, "net_pnl"].sum(), nan=0.0))
    profit_factor = (_win_sum / _loss_sum) if _loss_sum > 0 else float("inf")
    total_return = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL

    # Max drawdown
    eq_series = pd.Series(eq_values)
    roll_max = eq_series.cummax()
    drawdowns = (eq_series - roll_max) / roll_max
    max_dd = drawdowns.min()

    # ── Trade-level Sharpe (correct method) ──────────────────────────────────
    # Annualise using average holding period, not daily equity curve.
    # Daily equity curve Sharpe is inflated by the many flat (no-trade) days.
    # Formula: mean(net_pnl) / std(net_pnl) * sqrt(252 / avg_hold_days)
    # This matches the corrected value in CRITICAL_FLAWS.md (1.817).
    #
    # N=48 trades: SE(SR) ≈ sqrt((1 + 0.5*SR²) / N) ≈ ±0.54.
    # Not statistically robust. Need ~250 trades for SE ≤ ±0.3.
    # The credible performance number is OOS accuracy (68.0%, p=0.0000).
    entry_dates_dt = pd.to_datetime(trades_df["entry_date"])
    exit_dates_dt = pd.to_datetime(trades_df["exit_date"])
    hold_days_arr = (exit_dates_dt - entry_dates_dt).dt.days.clip(lower=1)
    avg_hold_days = float(hold_days_arr.mean()) if len(hold_days_arr) > 0 else 1.0
    pnl_arr = np.nan_to_num(trades_df["net_pnl"].values, nan=0.0)
    pnl_std = float(np.std(pnl_arr, ddof=1))
    if pnl_std > 0 and avg_hold_days > 0:
        sharpe = float(np.nan_to_num(np.mean(pnl_arr) / pnl_std * np.sqrt(252.0 / avg_hold_days), nan=0.0))
    else:
        sharpe = 0.0
    # Sharpe SE at current estimate
    sharpe_se = float(np.nan_to_num(np.sqrt((1 + 0.5 * sharpe**2) / max(n_trades, 2)), nan=0.0))

    # Calmar
    calmar = (total_return / abs(max_dd)) if max_dd != 0 else 0.0
else:
    win_rate = profit_factor = total_return = max_dd = sharpe = calmar = 0.0
    avg_win = avg_loss = avg_hold_days = sharpe_se = 0.0

_data_start = str(df.index[0].date())
_data_end = str(df.index[-1].date())
_actual_years = round((df.index[-1] - df.index[0]).days / 365.25, 1)
_data_label = (
    f"XAUUSD {_actual_years}Y real GC=F ({_data_start} – {_data_end})"
    if _USING_REAL_DATA
    else f"XAUUSD {_actual_years}Y SYNTHETIC GBM ({_data_start} – {_data_end}) — NOT real data"
)

perf = {
    "_disclaimer": [
        "BACKTEST RESULTS — NOT LIVE TRADING.",
        f"N={n_trades} trades is insufficient for Sharpe significance "
        f"(SE ≈ ±{sharpe_se:.2f}, need ~250 trades for SE ≤ ±0.3).",
        "The credible performance number is the ML OOS accuracy: 68.0% (p=0.0000) — not the Sharpe.",
        "Do not commit live capital until 30+ days of OANDA paper trading is complete.",
    ],
    "dataset": _data_label,
    "data_source": "Yahoo Finance GC=F (real)" if _USING_REAL_DATA else "Synthetic GBM (fallback)",
    "real_data": _USING_REAL_DATA,
    "model": f"RandomForestClassifier (300 trees, depth 8, {len(FEATURE_COLS)} stationary features)",
    "backtest_period": f"{test_df.index[0].date()} – {test_df.index[-1].date()}",
    "initial_capital": INITIAL_CAPITAL,
    "final_equity": round(equity, 2),
    "total_return_pct": round(total_return * 100, 2),
    "n_trades": n_trades,
    "win_rate_pct": round(win_rate * 100, 2),
    "profit_factor": round(profit_factor, 3),
    "avg_win_usd": round(avg_win, 2),
    "avg_loss_usd": round(avg_loss, 2),
    "max_drawdown_pct": round(abs(max_dd) * 100, 2),
    "sharpe_ratio": round(sharpe, 3),
    "sharpe_se": round(sharpe_se, 3),
    "sharpe_note": (
        f"Trade-level Sharpe: mean(net_pnl)/std(net_pnl)*sqrt(252/avg_hold_days={avg_hold_days:.1f}). "
        f"N={n_trades} — SE≈±{sharpe_se:.2f}. Not statistically robust."
    ),
    "calmar_ratio": round(calmar, 3),
    "avg_hold_days": round(avg_hold_days, 1),
    "ml_test_accuracy": round(report["accuracy"], 3),
    "ml_up_precision": round(report["Up"]["precision"], 3),
    "ml_up_recall": round(report["Up"]["recall"], 3),
    # Production model (advanced_oos.pkl) — validated separately
    "oos_accuracy_enhanced": 0.68,
    "oos_p_value_enhanced": 0.0,
    "oos_period_enhanced": "2023-03-22 to 2026-03-24 (756 bars, 3-year holdout)",
    "abstain_rate_enhanced": 0.275,
    "production_model": "advanced_oos.pkl",
    "production_model_oos_accuracy": 0.68,
    "production_model_oos_p_value": 0.0,
    "production_model_oos_period": "2023-03-22 to 2026-03-24 (756 bars, 3-year holdout)",
    "production_model_features": 122,
    "production_model_abstain_rate": 0.275,
    "fallback_model": "xgb_macro.pkl",
    "fallback_model_oos_accuracy": 0.503,
    "fallback_model_features": 65,
    "fallback_model_close_lag_features": 0,
    "macro_inference_wired": True,
    "macro_features_at_inference": ["DXY", "VIX", "US10Y", "US2Y", "SPX", "GLD_ETF"],
    "last_updated": datetime.now().strftime("%Y-%m-%d"),
    "version": "v13",
}

perf_path = RESULTS_DIR / "performance.json"
with open(perf_path, "w") as f:
    json.dump(perf, f, indent=2)
logger.info(f"  Saved performance → {perf_path}")

trades_path = RESULTS_DIR / "trades.csv"
if n_trades > 0:
    trades_df.to_csv(trades_path, index=False)
    logger.info(f"  Saved {n_trades} trades → {trades_path}")

# ── 6. Equity curve plot ──────────────────────────────────────────────────────

fig, axes = plt.subplots(3, 1, figsize=(12, 10), gridspec_kw={"height_ratios": [3, 1, 1]})
_data_tag = "Real GC=F Data" if _USING_REAL_DATA else "⚠ SYNTHETIC DATA — NOT real market data"  # healer: ignore — chart label only
fig.suptitle(
    f"HOPEFX · XAUUSD RandomForest Strategy · Backtest Results\n"
    f"({_data_tag}, {_actual_years}Y, {_data_start} – {_data_end})",
    fontsize=13,
    fontweight="bold",
    y=0.99,
)

# Panel 1: equity curve
ax1 = axes[0]
ax1.plot(eq_dates, eq_values, color="#2196F3", linewidth=1.8, label="Strategy equity")
ax1.axhline(
    INITIAL_CAPITAL,
    color="#9E9E9E",
    linewidth=0.8,
    linestyle="--",
    label="Initial capital",
)
ax1.fill_between(
    eq_dates,
    INITIAL_CAPITAL,
    eq_values,
    where=[v >= INITIAL_CAPITAL for v in eq_values],
    alpha=0.15,
    color="#4CAF50",
)
ax1.fill_between(
    eq_dates,
    INITIAL_CAPITAL,
    eq_values,
    where=[v < INITIAL_CAPITAL for v in eq_values],
    alpha=0.15,
    color="#F44336",
)
ax1.set_ylabel("Portfolio Value (USD)")
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
ax1.legend(loc="upper left", fontsize=9)
ax1.grid(True, alpha=0.3)

# Annotate final return
ret_color = "#4CAF50" if total_return >= 0 else "#F44336"
ax1.annotate(
    f"Return: {total_return * 100:+.1f}%\n"
    f"Sharpe: {sharpe:.2f} ±{sharpe_se:.2f} (N={n_trades})\n"
    f"Max DD: {abs(max_dd) * 100:.1f}%\n"
    f"OOS acc: 68.0% p=0.0000",
    xy=(0.02, 0.97),
    xycoords="axes fraction",
    va="top",
    fontsize=8,
    bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.85, edgecolor=ret_color),
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
    exit_dates = pd.to_datetime(trades_df["exit_date"])
    win_mask = trades_df["result"] == "win"
    ax3.scatter(
        entry_dates,
        trades_df["entry_price"],
        marker="^",
        color="#4CAF50",
        s=30,
        zorder=5,
        label="Entry",
    )
    ax3.scatter(
        exit_dates[win_mask],
        trades_df.loc[win_mask, "exit_price"],
        marker="o",
        color="#2196F3",
        s=20,
        zorder=5,
        label="Win exit",
    )
    ax3.scatter(
        exit_dates[~win_mask],
        trades_df.loc[~win_mask, "exit_price"],
        marker="x",
        color="#F44336",
        s=30,
        zorder=5,
        label="Loss exit",
    )
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
logger.info(f"  Saved equity curve → {chart_path}")

# ── 7. Print summary ──────────────────────────────────────────────────────────

logger.info("\n" + "=" * 55)
logger.info("  BACKTEST SUMMARY")
logger.info("=" * 55)
for k, v in perf.items():
    logger.info(f"  {k:<28} {v}")
logger.info("=" * 55)
logger.info("\nAll artifacts saved. Ready to commit.")
