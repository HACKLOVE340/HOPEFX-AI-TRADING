# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Committed historical price series, loaded with their age attached.

`data/XAUUSD_40Y.csv` and its siblings have been in the repository for a long
time, and the model predicts on them without complaint — `advanced_oos_v1`,
`fallback: False`, 222 features, a real probability. What was missing was a way
to reach them that says where the data came from and when it ends.

Every existing reader drops that. `api/trading.py` opens the same file inline
for charts; `backtesting/cli_runner.py` has its own `load_ohlcv_csv`; neither
returns an as-of date. The caller receives a DataFrame indistinguishable from a
live one.

That is the hazard here, and it is this repository's most common defect shape: a
stale value presented as a current one. The committed series ends months before
today. Rendering it as the live price, or letting it satisfy a freshness check,
fabricates a market that does not exist.

So nothing here returns a bare DataFrame. `load_cached_daily()` returns a
`CachedSeries` carrying `source`, `as_of`, `age_days` and `is_stale`, and its
`describe()` says the word "cached" out loud. The provenance travels with the
data rather than being something the caller is trusted to remember.

Deliberately **not** wired into the live inference path. Cached history reaching
`RiskManager.size_order()` would undo MASTER_OUTSTANDING §E12: that gate refuses
when data quality is unmeasured, and a CSV has no tick confidence to measure, so
a silent fallback to cache would put the fabricated-perfect-data defect back one
layer down. Offline prediction is an explicit caller's choice — see
`scripts/predict_offline.py`.

    from ml.cached_series import load_cached_daily
    s = load_cached_daily("XAUUSD")
    print(s.describe())        # XAUUSD · cached daily · 6415 bars · as of 2026-03-25 (168d old)
    engine.predict(s.frame.tail(400), symbol="XAU_USD")
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

__all__ = ["CachedSeries", "DEFAULT_FILES", "IntegrityReport", "load_cached_daily"]

#: Repository root — this file lives at <root>/ml/cached_series.py.
_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"

#: Preferred file per symbol, best first.
#:
#: XAUUSD_50Y.csv is deliberately absent: its pre-2000 bars carry isolated bad
#: prints (e.g. $43 when gold was ~$270), the same reason api/trading.py prefers
#: the 40Y file for charts. 40Y covers 2000→ cleanly.
DEFAULT_FILES: dict[str, tuple[str, ...]] = {
    "XAUUSD": ("XAUUSD_40Y.csv", "XAUUSD_5Y.csv", "XAUUSD_2Y.csv"),
}

_COLUMNS = ["open", "high", "low", "close", "volume"]

#: Daily bars older than this are stale for any purpose that implies "recent".
#: Three days rather than one, so an ordinary weekend is not an alarm.
DEFAULT_STALE_AFTER = dt.timedelta(days=3)


@dataclass(frozen=True)
class IntegrityReport:
    """How many bars in a series are impossible, and in what way.

    Not a repair. `XAUUSD_40Y.csv` carries 441 malformed bars out of 6415 — one
    with high < low outright, 236 where high sits below the open/close body,
    227 where low sits above it — all before 2020. Quietly dropping or
    rewriting them would be inventing prices for a market that had already
    closed. Counting them lets a caller decide, and lets anyone reading a
    backtest over 2000-2010 know the rolling highs, lows, ATR and true ranges
    across those windows are computed from bars that never happened.
    """

    bars: int
    high_below_low: int
    high_below_body: int
    low_above_body: int
    malformed: int

    @property
    def clean(self) -> bool:
        return self.malformed == 0

    def summary(self) -> str:
        if self.clean:
            return "no OHLC violations"
        pct = 100.0 * self.malformed / self.bars if self.bars else 0.0
        return (
            f"{self.malformed} malformed bars ({pct:.1f}%): "
            f"high<low={self.high_below_low}, high<body={self.high_below_body}, "
            f"low>body={self.low_above_body}"
        )


def _check_integrity(frame: pd.DataFrame) -> IntegrityReport:
    body_hi = frame[["open", "close"]].max(axis=1)
    body_lo = frame[["open", "close"]].min(axis=1)
    hl = frame["high"] < frame["low"]
    hb = frame["high"] < body_hi
    lb = frame["low"] > body_lo
    return IntegrityReport(
        bars=len(frame),
        high_below_low=int(hl.sum()),
        high_below_body=int(hb.sum()),
        low_above_body=int(lb.sum()),
        malformed=int((hl | hb | lb).sum()),
    )


@dataclass(frozen=True)
class CachedSeries:
    """A historical series that carries its own provenance.

    `as_of` describes the *data*, never the read. That distinction is the whole
    reason this type exists: a caller holding a DataFrame has no way to tell a
    series ending today from one ending last March.
    """

    symbol: str
    frame: pd.DataFrame
    source: Path

    @property
    def integrity(self) -> IntegrityReport:
        """OHLC sanity, measured on every load rather than assumed once."""
        return _check_integrity(self.frame)

    @property
    def as_of(self) -> pd.Timestamp:
        """Timestamp of the last bar — not the time this was loaded."""
        return self.frame.index[-1]

    @property
    def age_days(self) -> int:
        return (dt.datetime.now(dt.timezone.utc) - self.as_of).days

    @property
    def is_stale(self) -> bool:
        return self.is_stale_beyond(DEFAULT_STALE_AFTER)

    def is_stale_beyond(self, budget: dt.timedelta) -> bool:
        """Explicit budget, because "stale" means different things per caller.

        A backtest does not care that the series ends in March. Anything
        displaying a price, or deciding on one, cares a great deal.
        """
        return (dt.datetime.now(dt.timezone.utc) - self.as_of) > budget

    def describe(self) -> str:
        line = (
            f"{self.symbol} · cached daily · {len(self.frame)} bars · "
            f"{self.frame.index[0].date()} → {self.as_of.date()} "
            f"({self.age_days}d old) · {self.source.name}"
        )
        report = self.integrity
        return line if report.clean else f"{line} · ⚠ {report.summary()}"


def _read(path: Path) -> pd.DataFrame:
    """Normalise one committed CSV.

    The files disagree with each other: XAUUSD_2Y.csv heads its index column
    "date" and orders columns open/high/low/close, while the 5Y and 40Y files
    use "Date" and lead with close. Absorbing that here is the point — every
    caller that reads these files inline has had to know it.
    """
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip().lower() for c in frame.columns]

    if "date" not in frame.columns:
        raise ValueError(f"{path.name}: no date column (found {list(frame.columns)})")
    missing = [c for c in _COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {missing}")

    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    frame = frame.set_index("date").sort_index()
    # Duplicate dates would silently double-weight a bar in every rolling
    # feature downstream; keep the last observation for a repeated day.
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame[_COLUMNS].astype(float)


def load_cached_daily(symbol: str, *, filename: str | None = None) -> CachedSeries:
    """Load the committed daily series for *symbol*.

    Raises rather than returning an empty frame. A caller that receives no bars
    cannot tell "this symbol has no cache" from "today had no trading", and the
    guessing that follows is how a fabricated series gets into a chart.
    """
    key = symbol.upper().replace("_", "").replace("/", "")

    if filename is not None:
        path = _DATA / filename
        if not path.exists():
            raise FileNotFoundError(f"cached series not found: {path} (requested {filename!r})")
        return CachedSeries(symbol=key, frame=_read(path), source=path)

    candidates = DEFAULT_FILES.get(key)
    if not candidates:
        raise FileNotFoundError(
            f"no cached series is registered for {symbol!r}. Known symbols: {sorted(DEFAULT_FILES)}"
        )

    for name in candidates:
        path = _DATA / name
        if path.exists():
            return CachedSeries(symbol=key, frame=_read(path), source=path)

    raise FileNotFoundError(f"no cached series file present for {key}; looked for {list(candidates)} in {_DATA}")
