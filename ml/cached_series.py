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

import numpy as np
import pandas as pd

__all__ = [
    "CLEAN_SINCE",
    "CachedSeries",
    "DEFAULT_FILES",
    "IntegrityReport",
    "load_cached_daily",
    "load_series_file",
]

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

#: The date from which each committed series needs no repair at all.
#:
#: XAUUSD_40Y.csv carries 441 impossible bars, every one of them before 2020
#: (416 in the 2000s, 25 in the 2010s). scripts/clamp_ohlc.py can reconstruct
#: them into a separate file with recorded provenance, but a clamped high is the
#: lowest high consistent with the body, not what the market reached. Training
#: and backtests should default to this window, where the bars are simply real.
CLEAN_SINCE: dict[str, dt.date] = {
    "XAUUSD": dt.date(2020, 1, 1),
}

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
    #: Bars with a NaN or infinite price in open/high/low/close.
    #:
    #: Counted apart from the three contradictions above because a missing value
    #: contradicts nothing — there is no impossible price to report, only an
    #: absent one. Folding it into `high_below_low` would put a violation in the
    #: record that the data does not contain.
    #:
    #: It has to be counted at all because every comparison against NaN is
    #: False, so such a bar satisfies all three checks and was reported as
    #: sound. A report that clears bad data is worse than no report.
    non_finite: int = 0

    @property
    def clean(self) -> bool:
        return self.malformed == 0

    def summary(self) -> str:
        if self.clean:
            return "no OHLC violations"
        pct = 100.0 * self.malformed / self.bars if self.bars else 0.0
        parts = [
            f"high<low={self.high_below_low}",
            f"high<body={self.high_below_body}",
            f"low>body={self.low_above_body}",
        ]
        if self.non_finite:
            parts.append(f"non-finite={self.non_finite}")
        return f"{self.malformed} malformed bars ({pct:.1f}%): " + ", ".join(parts)


def _check_integrity(frame: pd.DataFrame) -> IntegrityReport:
    """Count the bars that cannot have happened.

    Finiteness first, then the property — the order every predicate in
    `invariants/` uses, and for the same reason: `NaN < anything` is False, so a
    bar with a missing high passes `high < low`, passes `high < body`, passes
    `low > body`, and is counted as sound. Guarding after the comparisons would
    be no guard at all.
    """
    present = [c for c in ("open", "high", "low", "close") if c in frame.columns]
    finite = frame[present].apply(lambda col: np.isfinite(col.to_numpy(dtype="float64", na_value=np.nan))).all(axis=1)

    body_hi = frame[["open", "close"]].max(axis=1)
    body_lo = frame[["open", "close"]].min(axis=1)
    # Restricted to bars whose prices are all finite; on the rest there is
    # nothing to compare, and a False from a NaN comparison means "unknown",
    # never "fine".
    hl = finite & (frame["high"] < frame["low"])
    hb = finite & (frame["high"] < body_hi)
    lb = finite & (frame["low"] > body_lo)
    non_finite = ~finite
    return IntegrityReport(
        bars=len(frame),
        high_below_low=int(hl.sum()),
        high_below_body=int(hb.sum()),
        low_above_body=int(lb.sum()),
        # healer: ignore — the nan_leak rule wants a .dropna()/.fillna() next to the
        # aggregation and cannot see that these are boolean masks already
        # intersected with `finite` above; there is no NaN left to leak. The
        # rule was right about the original line, which compared prices with no
        # guard at all, and is what made this fix a fix rather than an opinion.
        malformed=int((hl | hb | lb | non_finite).sum()),  # healer: ignore
        non_finite=int(non_finite.sum()),  # healer: ignore
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
    def repaired(self) -> bool:
        """True when a provenance sidecar says bars in this file were edited.

        A repaired series must never read like an original one. The sidecar is
        written by scripts/clamp_ohlc.py and sits beside the CSV.
        """
        return self._provenance() is not None

    def _provenance(self) -> dict | None:
        sidecar = self.source.with_name(f"{self.source.stem}.provenance.json")
        if not sidecar.exists():
            return None
        try:
            import json

            return json.loads(sidecar.read_text())
        except Exception:
            return None

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
        prov = self._provenance()
        if prov is not None:
            line += f" · ⚑ repaired: {prov.get('bars_edited', '?')} bars reconstructed"
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


def load_series_file(path: Path | str, *, symbol: str, since: dt.date | None = None) -> CachedSeries:
    """Load one specific CSV, wherever it lives. Used for repaired outputs."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"cached series not found: {path}")
    frame = _read(path)
    if since is not None:
        frame = frame[frame.index >= pd.Timestamp(since, tz="UTC")]
    return CachedSeries(symbol=symbol.upper(), frame=frame, source=path)


def load_cached_daily(symbol: str, *, filename: str | None = None, since: dt.date | None = None) -> CachedSeries:
    """Load the committed daily series for *symbol*.

    ``since`` trims the series to bars on or after that date. Pass
    ``CLEAN_SINCE[symbol]`` to get the window that needs no repair — see that
    constant for why the earlier history is not simply usable.

    Raises rather than returning an empty frame. A caller that receives no bars
    cannot tell "this symbol has no cache" from "today had no trading", and the
    guessing that follows is how a fabricated series gets into a chart.
    """
    key = symbol.upper().replace("_", "").replace("/", "")

    if filename is not None:
        path = _DATA / filename
        if not path.exists():
            raise FileNotFoundError(f"cached series not found: {path} (requested {filename!r})")
        return load_series_file(path, symbol=key, since=since)

    candidates = DEFAULT_FILES.get(key)
    if not candidates:
        raise FileNotFoundError(
            f"no cached series is registered for {symbol!r}. Known symbols: {sorted(DEFAULT_FILES)}"
        )

    for name in candidates:
        path = _DATA / name
        if path.exists():
            return load_series_file(path, symbol=key, since=since)

    raise FileNotFoundError(f"no cached series file present for {key}; looked for {list(candidates)} in {_DATA}")
