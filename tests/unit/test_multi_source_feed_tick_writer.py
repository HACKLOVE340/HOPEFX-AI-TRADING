# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""MultiSourceTickFeed must START the Redis tick writer, not merely connect it.

Regression: start() previously called RedisTickWriter.connect(), which acquires
the Redis client but does NOT launch the background worker that drains the write
queue. write() therefore enqueued every tick and returned True — _redis was set,
so it reported success — while nothing consumed the queue. The queue filled to
maxsize and each subsequent tick evicted the oldest, so every tick the feed
fetched was silently discarded.

Nothing reached hopefx:tick, so ws_live had nothing to broadcast: frozen prices
in the UI, charts stuck on "Loading market data…", and "No OHLCV data available"
on the indicator builder. One silent failure presenting as a dozen broken pages.
"""

from __future__ import annotations

import inspect

import data_feed.multi_source_feed as msf


def test_start_calls_writer_start_not_just_connect():
    src = inspect.getsource(msf.MultiSourceTickFeed.start)
    assert "_tick_writer.start()" in src, (
        "MultiSourceTickFeed.start() must await RedisTickWriter.start() — "
        "connect() alone leaves the write queue with no consumer and silently "
        "discards every tick."
    )


def test_writer_start_launches_the_worker():
    """Guard the assumption the fix rests on."""
    from data_feed.redis_tick_writer import RedisTickWriter

    src = inspect.getsource(RedisTickWriter.start)
    assert "_write_worker" in src, "start() is expected to launch the drain worker"
    assert "_write_worker" not in inspect.getsource(RedisTickWriter.connect), (
        "connect() must NOT be relied on to start the worker"
    )
