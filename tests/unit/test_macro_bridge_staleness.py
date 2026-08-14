# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_macro_bridge_staleness.py
=========================================
The macro pipeline serves data from March and reports itself freshly refreshed.

Traced through the running system rather than assumed. The bridge **is** wired —
``data_layer/orchestrator.py`` awaits ``self._macro_bridge.start()`` at startup,
so "MacroStoreBridge may not be running" was wrong. What is actually happening:

1. ``FRED_API_KEY`` is unset, so ``FREDFeed.fetch_series`` returns an empty
   Series immediately — logged at **DEBUG**, invisible at production log level.
   This is the root cause of every downstream macro symptom and nothing says so.
2. ``data/macro/fred_cache.json`` is literally ``{}`` — no last-known-good.
3. ``start()`` therefore falls through to ``_load_csv_fallback()``, which loads
   the bundled CSVs in ``data/macro/``. Every one of them ends **2026-03-25**.

Then the part that makes it invisible. ``_load_csv_fallback`` sets::

    self._last_refresh = datetime.now(UTC)

That is when the *file was read*, not how old the *data* is. ``health()`` and
``snapshot()`` publish it as ``last_refresh``, so a health endpoint reports
``loaded: true`` with a timestamp of seconds ago while serving observations
142 days old. The freshness signal measures the wrong thing entirely.

``get_ml_features()`` then zero-fills anything missing, which is the same
fabrication already fixed one layer up: ``macro_vix = 0.0`` is not "unknown", it
is a VIX of zero, and ``_classify_macro`` reads it as LOW_VOL.

``analysis/chart_analysis.load_macro()`` already computes the true age from the
newest observation date and refuses past ``CHART_MACRO_MAX_AGE_DAYS`` — which is
why the chart bot alone got this right. That check belongs in the bridge, where
every consumer benefits from it, rather than in one page.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

UTC = timezone.utc


class _Store:
    """Stand-in for ml.macro_store.macro_store."""

    def __init__(self, dates: dict[str, date | None]):
        self._dates = dates
        self._series = dict.fromkeys(dates, object())

    def snapshot(self):
        return {
            name: (None if d is None else {"value": 1.23, "date": d.isoformat()}) for name, d in self._dates.items()
        }

    def load_defaults(self):
        return None


def _bridge(dates: dict[str, date | None], monkeypatch):
    """A bridge whose MacroStore reports the given observation dates."""
    import ml.macro_store as ms
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    monkeypatch.setattr(ms, "macro_store", _Store(dates))
    b = MacroStoreBridge()
    b._loaded = True
    b._series_loaded = len(dates)
    return b


def _days_ago(n: int) -> date:
    return (datetime.now(tz=UTC) - timedelta(days=n)).date()


# ── The age of the data, not the age of the read ─────────────────────────────


def test_data_age_is_measured_from_the_newest_observation(monkeypatch):
    b = _bridge({"vix": _days_ago(3), "dxy": _days_ago(9)}, monkeypatch)
    assert b.data_age_days() == 3, "age must come from the newest series, not the oldest"


def test_data_age_is_none_when_nothing_is_loaded(monkeypatch):
    b = _bridge({}, monkeypatch)
    assert b.data_age_days() is None, "no data must be 'unknown', never 0 days old"


def test_undated_series_do_not_count_as_fresh(monkeypatch):
    b = _bridge({"vix": None, "dxy": None}, monkeypatch)
    assert b.data_age_days() is None


def test_health_reports_the_true_age_not_the_load_time(monkeypatch):
    """The deployed failure: last_refresh said "seconds ago" for March data."""
    b = _bridge({"vix": _days_ago(142)}, monkeypatch)
    b._last_refresh = datetime.now(tz=UTC)  # what the CSV fallback sets

    h = b.health()
    assert h["data_age_days"] == 142
    assert h["stale"] is True
    assert h["newest_observation"] == _days_ago(142).isoformat()


def test_fresh_data_is_not_marked_stale(monkeypatch):
    """Control — without it the assertions above pass by always saying stale."""
    b = _bridge({"vix": _days_ago(1)}, monkeypatch)
    h = b.health()
    assert h["data_age_days"] == 1
    assert h["stale"] is False


def test_unknown_age_is_stale_not_fresh(monkeypatch):
    """Fail closed: if the age cannot be established, do not claim freshness."""
    b = _bridge({}, monkeypatch)
    assert b.health()["stale"] is True


def test_last_refresh_still_reports_when_we_last_loaded(monkeypatch):
    """Both facts are useful and they are different. Keep the load time, but
    stop letting it stand in for data freshness."""
    b = _bridge({"vix": _days_ago(142)}, monkeypatch)
    stamp = datetime.now(tz=UTC)
    b._last_refresh = stamp
    h = b.health()
    assert h["last_refresh"] == stamp.isoformat()
    assert h["data_age_days"] == 142


def test_the_threshold_is_configurable(monkeypatch):
    import data_layer.feeds.macro.store_bridge as sb

    b = _bridge({"vix": _days_ago(10)}, monkeypatch)
    monkeypatch.setattr(sb, "MACRO_MAX_AGE_DAYS", 30)
    assert b.health()["stale"] is False
    monkeypatch.setattr(sb, "MACRO_MAX_AGE_DAYS", 7)
    assert b.health()["stale"] is True


# ── Which source the numbers came from ───────────────────────────────────────


def test_the_source_is_reported(monkeypatch):
    """ "loaded: true" does not distinguish live FRED from months-old bundled
    CSVs, and the remedy is completely different."""
    b = _bridge({"vix": _days_ago(1)}, monkeypatch)
    assert b.health()["source"] in ("fred", "csv_fallback", "cache", "none")


def test_the_csv_fallback_marks_itself_as_the_source(monkeypatch):
    b = _bridge({"vix": _days_ago(142)}, monkeypatch)
    b._loaded = False
    b._load_csv_fallback()
    assert b.health()["source"] == "csv_fallback"


def test_the_csv_fallback_warns_about_the_age_of_what_it_loaded(monkeypatch, caplog):
    """Loading 142-day-old CSVs at INFO with no age is how this stayed hidden."""
    b = _bridge({"vix": _days_ago(142)}, monkeypatch)
    b._loaded = False
    with caplog.at_level(logging.WARNING):
        b._load_csv_fallback()
    text = caplog.text
    assert "142" in text, f"the age of the loaded data was not logged: {text!r}"


def test_a_fresh_csv_fallback_does_not_warn(monkeypatch, caplog):
    b = _bridge({"vix": _days_ago(1)}, monkeypatch)
    b._loaded = False
    with caplog.at_level(logging.WARNING):
        b._load_csv_fallback()
    assert "stale" not in caplog.text.lower()


# ── The root cause must be visible ───────────────────────────────────────────


async def test_a_missing_fred_key_is_stated_once_at_warning(caplog, monkeypatch):
    """Logged at DEBUG, this was invisible in production — and it is the reason
    the entire macro pipeline is degraded."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    from data_layer.feeds.macro.fred import FREDFeed

    feed = FREDFeed()
    with caplog.at_level(logging.WARNING):
        await feed.fetch_series("DTWEXBGS")

    assert "FRED_API_KEY" in caplog.text, "a missing API key is still only visible at DEBUG"


async def test_the_missing_key_warning_does_not_repeat_per_series(caplog, monkeypatch):
    """There are many series and a daily refresh loop — one warning, not a flood."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    from data_layer.feeds.macro.fred import FREDFeed

    feed = FREDFeed()
    with caplog.at_level(logging.WARNING):
        for sid in ("DTWEXBGS", "DGS10", "DGS2", "VIXCLS"):
            await feed.fetch_series(sid)

    assert caplog.text.count("FRED_API_KEY") == 1, f"warning repeated: {caplog.text.count('FRED_API_KEY')} times"


# ── An empty fetch is not a successful one ───────────────────────────────────


class _EmptyFred:
    """FRED with no API key: every series comes back empty, no exception."""

    async def fetch_all(self):
        import pandas as pd

        return {"dxy": pd.Series(dtype=float), "vix": pd.Series(dtype=float)}

    async def close(self):
        return None

    def health(self):
        return {}


async def test_an_all_empty_fred_response_does_not_count_as_loaded(tmp_path, monkeypatch):
    """`self._loaded = True` was set unconditionally, even with zero series
    injected. `start()` breaks its retry loop on `_loaded`, so an empty FRED
    response skipped the CSV fallback entirely."""
    import data_layer.feeds.macro.store_bridge as sb
    import ml.macro_store as ms
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    monkeypatch.setattr(sb, "_FRED_CACHE_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(ms, "macro_store", _Store({}))

    b = MacroStoreBridge(fred=_EmptyFred())
    await b._load_fred_into_store()

    assert b._loaded is False, "an empty FRED response was recorded as a successful load"


async def test_a_cache_of_empty_series_does_not_count_as_loaded(tmp_path, monkeypatch):
    """Isolates the `loaded == 0` guard.

    The test above does not: with all-empty series the `any_data` check diverts
    to the cache branch, which raises FileNotFoundError and returns before the
    injection loop is ever reached. Mutating the guard away left that test
    green. This drives the one path that does reach the loop with nothing
    usable — a cache file that reads successfully but holds only empty series.
    """
    import data_layer.feeds.macro.store_bridge as sb
    import ml.macro_store as ms
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    cache = tmp_path / "fred_cache.json"
    cache.write_text('{"vix": {}, "dxy": {}}')  # present, parseable, empty

    monkeypatch.setattr(sb, "_FRED_CACHE_PATH", str(cache))
    monkeypatch.setattr(ms, "macro_store", _Store({}))

    b = MacroStoreBridge(fred=_EmptyFred())
    await b._load_fred_into_store()

    assert b._loaded is False, "a cache holding only empty series was recorded as a successful load"
    assert b._source != "fred"


async def test_an_empty_fetch_does_not_clobber_the_last_known_good_cache(tmp_path, monkeypatch):
    """Why data/macro/fred_cache.json is 3 bytes of `{}`.

    With no API key every series is empty, `fetch_ok` is True, and the cache
    writer filters empty series out — leaving `{}`, which was then written over
    the real last-known-good snapshot. The fallback destroyed itself.
    """
    import data_layer.feeds.macro.store_bridge as sb
    import ml.macro_store as ms
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge

    cache = tmp_path / "fred_cache.json"
    cache.write_text('{"vix": {"2026-08-01": 15.5}}')

    monkeypatch.setattr(sb, "_FRED_CACHE_PATH", str(cache))
    monkeypatch.setattr(ms, "macro_store", _Store({}))

    b = MacroStoreBridge(fred=_EmptyFred())
    await b._load_fred_into_store()

    import json as _json

    assert _json.loads(cache.read_text()) == {"vix": {"2026-08-01": 15.5}}, (
        "an empty fetch overwrote the last-known-good cache"
    )


# ── The shipped data ─────────────────────────────────────────────────────────


def test_the_bundled_csvs_are_the_stale_ones_this_is_about():
    """Documents the deployed state. If someone refreshes them, this says so
    rather than silently passing."""
    import csv
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    newest: date | None = None
    for path in (root / "data" / "macro").glob("*.csv"):
        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        last = date.fromisoformat(rows[-1]["date"])
        newest = last if newest is None else max(newest, last)

    if newest is None:
        pytest.skip("no bundled macro CSVs")

    age = (datetime.now(tz=UTC).date() - newest).days
    if age <= 7:
        pytest.skip(f"bundled CSVs have been refreshed (newest {newest}, {age}d old)")

    assert age > 7, "sanity"
