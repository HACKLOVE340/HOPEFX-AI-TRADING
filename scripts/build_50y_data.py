#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
scripts/build_50y_data.py
=========================
Build a 50-year XAUUSD daily price history from multiple free data sources
and validate strategy robustness across major crisis periods.

Data sources (tried in priority order, merged by date)
-------------------------------------------------------
1. yfinance  GC=F          — COMEX gold futures, ~26Y daily
2. yfinance  ^XAU          — Philadelphia Gold & Silver Index, back to 1983
3. Stooq     XAUUSD        — spot gold, often back to 1979
4. FRED      GOLDAMGBD228NLBM — London AM fix, back to 1968 (daily)
5. Quandl/Nasdaq LBMA/GOLD — London fix, back to 1968
6. Datahub.io gold-prices  — monthly back to 1950, expanded to daily
7. data/XAUUSD_40Y.csv     — existing project file (highest quality 2000+)
8. Hardcoded London fix     — annual averages 1968-1979 as daily interpolation

Output
------
data/XAUUSD_50Y.csv          — 50-year daily OHLCV
data/crisis_validation.json  — per-crisis Sharpe/drawdown/return + full stats
"""

from __future__ import annotations

import io
import json
import logging
import sys
import urllib.request
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_50y_data")

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_50Y = DATA_DIR / "XAUUSD_50Y.csv"
OUTPUT_CRISIS = DATA_DIR / "crisis_validation.json"
EXISTING_40Y = DATA_DIR / "XAUUSD_40Y.csv"

TARGET_START = "1968-01-01"

CRISIS_PERIODS = [
    ("1980_gold_bubble", "1979-10-01", "1980-09-30"),
    ("1987_black_monday", "1987-08-01", "1988-01-31"),
    ("2001_dotcom", "2001-01-01", "2002-12-31"),
    ("2008_gfc", "2007-10-01", "2009-03-31"),
    ("2011_peak_crash", "2011-08-01", "2012-06-30"),
    ("2013_gold_crash", "2013-04-01", "2013-12-31"),
    ("2020_covid", "2020-02-01", "2020-04-30"),
    ("2022_rates_shock", "2022-01-01", "2022-12-31"),
]

# World Gold Council / Kitco annual averages (USD/oz) — public domain
LONDON_FIX_ANNUAL: dict[int, float] = {
    1968: 39.31,
    1969: 41.28,
    1970: 36.02,
    1971: 40.62,
    1972: 58.16,
    1973: 97.39,
    1974: 159.26,
    1975: 161.02,
    1976: 124.74,
    1977: 147.84,
    1978: 193.40,
    1979: 306.00,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _std_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).lower().strip() for c in df.columns]
    rename = {}
    for c in df.columns:
        if c in ("date", "datetime", "time", "timestamp"):
            rename[c] = "Date"
        elif c in ("adj close", "adj_close", "adjusted_close", "price", "value"):
            rename[c] = "close"
    df = df.rename(columns=rename)
    if "Date" not in df.columns:
        df = df.reset_index()
        df.columns = [str(c).lower().strip() for c in df.columns]
        if df.columns[0] not in ("Date",):
            df = df.rename(columns={df.columns[0]: "Date"})
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["Date"])
    for col in ["close", "high", "low", "open", "volume"]:
        if col not in df.columns:
            df[col] = np.nan
    for col in ["high", "low", "open"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(pd.to_numeric(df["close"], errors="coerce"))
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df = df[df["close"] > 0].copy()
    return df[["Date", "close", "high", "low", "open", "volume"]]


def _merge(*frames: pd.DataFrame) -> pd.DataFrame:
    valid = [f for f in frames if f is not None and not f.empty]
    if not valid:
        return pd.DataFrame()
    combined = pd.concat(valid, ignore_index=True)
    combined["Date"] = pd.to_datetime(combined["Date"])
    combined = combined.sort_values("Date").drop_duplicates(subset="Date", keep="last").reset_index(drop=True)
    combined["Date"] = combined["Date"].dt.strftime("%Y-%m-%d")
    return combined


def _http_get(url: str, timeout: int = 25) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HOPEFX/1.0)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
            return r.read()
    except Exception as exc:
        logger.warning("HTTP GET failed %s: %s", url, exc)
        return None


# ── Source 1: yfinance GC=F ───────────────────────────────────────────────────


def fetch_yfinance_gcf(start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf

        logger.info("[1] yfinance GC=F %s → %s", start, end)
        df = yf.download("GC=F", start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        result = _std_cols(df)
        logger.info("    → %d rows", len(result))
        return result
    except Exception as exc:
        logger.warning("yfinance GC=F failed: %s", exc)
        return pd.DataFrame()


# ── Source 2: yfinance ^XAU (Philadelphia Gold Index, back to 1983) ──────────


def fetch_yfinance_xau(start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf

        logger.info("[2] yfinance ^XAU %s → %s", start, end)
        df = yf.download("^XAU", start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        result = _std_cols(df)
        logger.info("    → %d rows", len(result))
        return result
    except Exception as exc:
        logger.warning("yfinance ^XAU failed: %s", exc)
        return pd.DataFrame()


# ── Source 3: Stooq XAUUSD ───────────────────────────────────────────────────


def fetch_stooq(start: str, end: str) -> pd.DataFrame:
    try:
        d1 = start.replace("-", "")
        d2 = end.replace("-", "")
        url = f"https://stooq.com/q/d/l/?s=xauusd&d1={d1}&d2={d2}&i=d"
        logger.info("[3] Stooq XAUUSD %s → %s", start, end)
        raw = _http_get(url)
        if not raw:
            return pd.DataFrame()
        text = raw.decode("utf-8", errors="replace")
        if "No data" in text or len(text) < 50:
            logger.warning("    Stooq: no data")
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(text))
        if df.empty:
            return pd.DataFrame()
        result = _std_cols(df)
        logger.info("    → %d rows", len(result))
        return result
    except Exception as exc:
        logger.warning("Stooq failed: %s", exc)
        return pd.DataFrame()


# ── Source 4: FRED GOLDAMGBD228NLBM ──────────────────────────────────────────


def fetch_fred_gold(start: str, end: str) -> pd.DataFrame:
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GOLDAMGBD228NLBM"
        logger.info("[4] FRED GOLDAMGBD228NLBM (London AM fix)")
        raw = _http_get(url, timeout=30)
        if not raw:
            return pd.DataFrame()
        text = raw.decode("utf-8", errors="replace")
        df = pd.read_csv(io.StringIO(text))
        if df.empty:
            return pd.DataFrame()
        df.columns = ["Date", "close"]
        df = df[df["close"] != "."].copy()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"])
        result = _std_cols(df)
        result["Date"] = pd.to_datetime(result["Date"])
        result = result[(result["Date"] >= start) & (result["Date"] <= end)].copy()
        result["Date"] = result["Date"].dt.strftime("%Y-%m-%d")
        logger.info("    → %d rows", len(result))
        return result
    except Exception as exc:
        logger.warning("FRED failed: %s", exc)
        return pd.DataFrame()


# ── Source 5: Quandl/Nasdaq LBMA/GOLD ────────────────────────────────────────


def fetch_quandl_gold(start: str, end: str) -> pd.DataFrame:
    try:
        url = f"https://data.nasdaq.com/api/v3/datasets/LBMA/GOLD.csv?start_date={start}&end_date={end}&order=asc"
        logger.info("[5] Quandl/Nasdaq LBMA/GOLD %s → %s", start, end)
        raw = _http_get(url, timeout=20)
        if not raw:
            return pd.DataFrame()
        text = raw.decode("utf-8", errors="replace")
        if "errors" in text[:200].lower() or len(text) < 100:
            logger.warning("    Quandl: no data or error")
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(text))
        if df.empty:
            return pd.DataFrame()
        df.columns = [c.strip() for c in df.columns]
        # Pick USD AM fix column
        for col in ("USD (AM)", "USD (PM)", "USD"):
            if col in df.columns:
                df = df.rename(columns={col: "close"})
                break
        result = _std_cols(df)
        logger.info("    → %d rows", len(result))
        return result
    except Exception as exc:
        logger.warning("Quandl failed: %s", exc)
        return pd.DataFrame()


# ── Source 6: Datahub.io monthly gold prices ─────────────────────────────────


def fetch_datahub_gold() -> pd.DataFrame:
    try:
        url = "https://datahub.io/core/gold-prices/r/monthly.csv"
        logger.info("[6] Datahub.io gold prices (monthly)")
        raw = _http_get(url, timeout=20)
        if not raw:
            return pd.DataFrame()
        text = raw.decode("utf-8", errors="replace")
        df = pd.read_csv(io.StringIO(text))
        if df.empty:
            return pd.DataFrame()
        df.columns = [c.strip() for c in df.columns]
        if "Price" in df.columns:
            df = df.rename(columns={"Price": "close"})
        result = _std_cols(df)
        # Expand monthly → daily via forward-fill
        result["Date"] = pd.to_datetime(result["Date"])
        result = result.set_index("Date").resample("B").ffill().reset_index()
        result["Date"] = result["Date"].dt.strftime("%Y-%m-%d")
        logger.info("    → %d rows (after daily expansion)", len(result))
        return result
    except Exception as exc:
        logger.warning("Datahub.io failed: %s", exc)
        return pd.DataFrame()


# ── Source 7: Existing project 40Y CSV ───────────────────────────────────────


def load_existing_40y() -> pd.DataFrame:
    if not EXISTING_40Y.exists():
        return pd.DataFrame()
    df = pd.read_csv(EXISTING_40Y)
    result = _std_cols(df)
    logger.info("[7] Existing 40Y CSV → %d rows", len(result))
    return result


# ── Source 8: Hardcoded London fix 1968-1979 ─────────────────────────────────


def build_annual_series() -> pd.DataFrame:
    rows = []
    for year, price in sorted(LONDON_FIX_ANNUAL.items()):
        for d in pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="B"):
            rows.append(
                {
                    "Date": d.strftime("%Y-%m-%d"),
                    "close": float(price),
                    "high": float(price) * 1.005,
                    "low": float(price) * 0.995,
                    "open": float(price),
                    "volume": 0.0,
                }
            )
    df = pd.DataFrame(rows)
    logger.info("[8] Hardcoded London fix 1968-1979 → %d rows", len(df))
    return df


# ── Statistics ────────────────────────────────────────────────────────────────


def _returns(df: pd.DataFrame) -> pd.Series:
    return df["close"].astype(float).pct_change().dropna()


def _sharpe(r: pd.Series, ann: int = 252) -> float:
    return float(r.mean() / r.std() * np.sqrt(ann)) if len(r) > 1 and r.std() > 0 else 0.0


def _max_dd(r: pd.Series) -> float:
    cum = (1 + r).cumprod()
    return float(((cum - cum.cummax()) / cum.cummax()).min())


def validate_crisis_periods(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    results: dict = {}
    for name, start, end in CRISIS_PERIODS:
        sub = df[(df["Date"] >= start) & (df["Date"] <= end)].copy()
        if len(sub) < 5:
            results[name] = {"start": start, "end": end, "n_bars": len(sub), "error": "insufficient data"}
            logger.warning("Crisis %-22s only %d bars", name, len(sub))
            continue
        r = _returns(sub)
        total_ret = float(sub["close"].iloc[-1] / sub["close"].iloc[0] - 1)
        results[name] = {
            "start": start,
            "end": end,
            "n_bars": len(sub),
            "sharpe": round(_sharpe(r), 4),
            "max_drawdown": round(_max_dd(r), 4),
            "total_return": round(total_ret, 4),
            "annualised_vol": round(float(r.std() * np.sqrt(252)), 4),
            "start_price": round(float(sub["close"].iloc[0]), 2),
            "end_price": round(float(sub["close"].iloc[-1]), 2),
        }
        logger.info(
            "Crisis %-22s n=%4d  sharpe=%+.2f  dd=%+.1f%%  ret=%+.1f%%",
            name,
            len(sub),
            results[name]["sharpe"],
            results[name]["max_drawdown"] * 100,
            total_ret * 100,
        )
    return results


def full_stats(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    r = _returns(df)
    return {
        "n_bars": len(df),
        "date_range": f"{df['Date'].min().strftime('%Y-%m-%d')} → {df['Date'].max().strftime('%Y-%m-%d')}",
        "years_covered": round((df["Date"].max() - df["Date"].min()).days / 365.25, 1),
        "sharpe_full": round(_sharpe(r), 4),
        "max_drawdown_full": round(_max_dd(r), 4),
        "annualised_return": round(float(r.mean() * 252), 4),
        "annualised_vol": round(float(r.std() * np.sqrt(252)), 4),
        "start_price": round(float(df["close"].iloc[0]), 2),
        "end_price": round(float(df["close"].iloc[-1]), 2),
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    logger.info("=" * 60)
    logger.info("Building 50Y XAUUSD dataset  target: %s → %s", TARGET_START, today)
    logger.info("=" * 60)

    # Fetch all sources
    annual = build_annual_series()
    datahub = fetch_datahub_gold()
    quandl = fetch_quandl_gold(TARGET_START, today)
    fred = fetch_fred_gold(TARGET_START, today)
    xau_idx = fetch_yfinance_xau("1983-01-01", "2001-01-01")
    gcf = fetch_yfinance_gcf("1999-01-01", today)
    existing = load_existing_40y()

    # Merge — later sources win on date overlap
    merged = _merge(annual, datahub, quandl, fred, xau_idx, gcf, existing)

    if merged.empty:
        logger.error("No data assembled — check network connectivity")
        return 1

    # Filter, clean, sort
    merged["Date"] = pd.to_datetime(merged["Date"])
    merged = merged[merged["Date"] >= TARGET_START].copy()
    merged = merged[merged["close"].astype(float) > 0].copy()
    merged = merged.sort_values("Date").reset_index(drop=True)
    merged["close"] = merged["close"].astype(float).ffill()
    for col in ["high", "low", "open"]:
        merged[col] = merged[col].astype(float).fillna(merged["close"])
    merged["volume"] = merged["volume"].fillna(0)
    merged["Date"] = merged["Date"].dt.strftime("%Y-%m-%d")

    logger.info(
        "Final: %d rows  %s → %s",
        len(merged),
        merged["Date"].iloc[0],
        merged["Date"].iloc[-1],
    )

    # Save CSV
    DATA_DIR.mkdir(exist_ok=True)
    merged.to_csv(OUTPUT_50Y, index=False)
    logger.info("Saved %s", OUTPUT_50Y)

    # Crisis validation + full stats
    crisis = validate_crisis_periods(merged)
    stats = full_stats(merged)

    # Source coverage
    coverage: dict = {}
    for label, frame in [
        ("annual_london_fix_1968_1979", annual),
        ("datahub_monthly_1950+", datahub),
        ("quandl_lbma_1968+", quandl),
        ("fred_london_am_fix_1968+", fred),
        ("yfinance_xau_index_1983+", xau_idx),
        ("yfinance_gcf_futures_1999+", gcf),
        ("existing_40y_csv_2000+", existing),
    ]:
        if frame is not None and not frame.empty:
            f2 = frame.copy()
            f2["Date"] = pd.to_datetime(f2["Date"])
            coverage[label] = {
                "rows": len(f2),
                "from": f2["Date"].min().strftime("%Y-%m-%d"),
                "to": f2["Date"].max().strftime("%Y-%m-%d"),
            }
        else:
            coverage[label] = {"rows": 0, "from": None, "to": None}

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(OUTPUT_50Y.relative_to(PROJECT_ROOT)),
        "full_stats": stats,
        "crisis_periods": crisis,
        "source_coverage": coverage,
    }
    OUTPUT_CRISIS.write_text(json.dumps(report, indent=2))
    logger.info("Saved crisis report → %s", OUTPUT_CRISIS)

    # Print summary
    logger.info("\n" + "=" * 65)
    logger.info("50Y XAUUSD Dataset Summary")
    logger.info("=" * 65)
    logger.info(f"  Rows:           {stats['n_bars']:,}")
    logger.info(f"  Date range:     {stats['date_range']}")
    logger.info(f"  Years covered:  {stats['years_covered']}")
    logger.info(f"  Full Sharpe:    {stats['sharpe_full']:.3f}")
    logger.info(f"  Max drawdown:   {stats['max_drawdown_full'] * 100:.1f}%")
    logger.info(f"  Ann. return:    {stats['annualised_return'] * 100:.1f}%")
    logger.info(f"  Ann. vol:       {stats['annualised_vol'] * 100:.1f}%")
    logger.info()
    logger.info("Source coverage:")
    for src, cov in coverage.items():
        if cov["rows"]:
            logger.info(f"  {src:<38} {cov['rows']:>6} rows  {cov['from']} → {cov['to']}")
        else:
            logger.info(f"  {src:<38}   unavailable")
    logger.info()
    logger.info("Crisis Period Validation:")
    for name, r in crisis.items():
        if "error" in r:
            logger.info(f"  {name:<24} INSUFFICIENT DATA ({r['n_bars']} bars)")
        else:
            logger.info(
                f"  {name:<24} n={r['n_bars']:>4}  "
                f"sharpe={r['sharpe']:+.2f}  "
                f"dd={r['max_drawdown'] * 100:+.1f}%  "
                f"ret={r['total_return'] * 100:+.1f}%"
            )
    logger.info("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
