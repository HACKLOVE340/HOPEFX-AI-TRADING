# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_macro_bridge_startup_retry.py
==============================================
``MacroStoreBridge.start()`` retried a fetch it already knew, before making
any request, could not succeed.

Measured on the real server with ``FRED_API_KEY`` unset (every fresh
checkout, every developer laptop): ``fred.py`` logs "FRED_API_KEY is not
set — no macro series can be fetched" *before* the first attempt, and
``start()`` then retried three times anyway — 5s + 10s = 15s of the FRED
startup retry loop's own guaranteed-failing backoff on every cold start
without a key (measured directly with ``asyncio.sleep`` instrumented;
see also the manual run in the task report, whose observed FRED-retry
window was 11594ms → 26611ms, i.e. 15.0s).

Retry exists for *transient* failures — a network error, a 5xx, a rate
limit — where the next attempt might succeed. A missing API key is not
transient: ``FREDFeed.is_configured()`` can answer the question with no
request at all, and the answer cannot change between one retry and the
next within the same process run.

This module distinguishes the two:
  * unconfigured  → no retry, no sleep, fall back to CSV/cache immediately.
  * configured but failing (a stand-in for a transient network failure)
    → retry exactly as before, with the same backoff.

The second case is the positive control: it proves the retry-and-backoff
path in ``start()`` is still live and can still fail, so the fix above is
not "delete the retry loop" — it is a comment on the wrong branch — but has
actually preserved a functioning retry path.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _FakeWGC:
    """Stand-in for WGCFeed — WGC has no bearing on this defect."""

    async def fetch_all(self):
        return {}

    def inject_into_macro_store(self, series):
        return 0

    def health(self):
        return {}


class _ScriptedFred:
    """A FRED feed whose configuration state is fixed for the test."""

    def __init__(self, configured: bool) -> None:
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    async def close(self) -> None:
        return None


def _bridge(monkeypatch, *, configured: bool):
    """A bridge with load/csv-fallback/sleep all spied, and the daily-refresh
    task neutralised so it cannot itself invoke the patched sleep with an
    unrelated (~24h) wait and confuse the assertions."""
    import data_layer.feeds.macro.store_bridge as sb

    bridge = sb.MacroStoreBridge(fred=_ScriptedFred(configured), wgc=_FakeWGC())

    load_calls: list[int] = []

    async def _fake_load_fred_into_store():
        load_calls.append(1)
        bridge._loaded = False  # every attempt fails

    csv_calls: list[int] = []

    def _fake_load_csv_fallback():
        csv_calls.append(1)

    async def _noop_daily_loop():
        return None

    bridge._load_fred_into_store = _fake_load_fred_into_store
    bridge._load_csv_fallback = _fake_load_csv_fallback
    bridge._daily_refresh_loop = _noop_daily_loop

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(sb.asyncio, "sleep", _fake_sleep)

    return bridge, load_calls, csv_calls, sleep_calls


# ── The defect: retrying a fetch already known to be unsucceedable ──────────


async def test_unconfigured_fred_does_not_sleep_or_retry(monkeypatch):
    """No FRED_API_KEY is known before any request is made — retrying cannot
    change that answer, so start() must not sleep waiting to try again."""
    bridge, load_calls, csv_calls, sleep_calls = _bridge(monkeypatch, configured=False)

    await bridge.start()

    assert sleep_calls == [], f"unconfigured FRED must not retry-sleep, but slept: {sleep_calls}"
    assert len(load_calls) == 1, f"unconfigured FRED should be attempted exactly once, got {len(load_calls)}"
    assert len(csv_calls) == 1, "CSV/cache fallback must still run immediately when unconfigured"


# ── Positive control: the retry path is live and can still fail ────────────


async def test_configured_fred_still_retries_transient_failures(monkeypatch):
    """A stand-in for a real transient failure (network error, 5xx, rate
    limit): the key IS present, so the next attempt might succeed. This must
    still retry with the existing backoff — proving the retry mechanism
    itself was not gutted by the unconfigured-skip fix, only bypassed for the
    one case that can never succeed."""
    bridge, load_calls, csv_calls, sleep_calls = _bridge(monkeypatch, configured=True)

    await bridge.start()

    assert len(load_calls) == 3, f"configured FRED failing transiently must still retry 3 times, got {len(load_calls)}"
    assert sleep_calls == [5.0, 10.0], f"expected the existing 5s/10s backoff, got {sleep_calls}"
    assert len(csv_calls) == 1, "CSV/cache fallback must still run after retries are exhausted"
