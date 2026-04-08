# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/tick_store.py
========================
Sub-millisecond tick store with a three-tier storage backend.

Tier 1 — TimescaleDB (PostgreSQL hypertable, partitioned by time)
-----------------------------------------------------------------
Best for production: compresses historical ticks to ~1/10 the raw size,
supports continuous aggregates for OHLCV roll-ups at any timeframe, and
provides microsecond-resolution ORDER BY ts_ns queries.

Required setup:
    CREATE EXTENSION IF NOT EXISTS timescaledb;
    -- tick_store.py calls _ensure_schema() on first connect, which
    -- creates the ticks table and hypertable automatically.

Configure via env var:
    TIMESCALEDB_URL=postgresql+psycopg2://user:pass@host:5432/hopefx

Tier 2 — Redis TimeSeries (via redis-py TS module)
--------------------------------------------------
Fast ring-buffer for the last N ticks per symbol.  Ideal when a full
PostgreSQL deployment is not available.  Configures a 48-hour retention
policy by default.

Configure via:
    REDIS_URL=redis://localhost:6379/0
    TICK_REDIS_RETENTION_MS=172800000   (48 h, default)

Tier 3 — In-memory deque (always available, no deps)
----------------------------------------------------
Last-resort fallback.  Ticks are lost on process restart.  Suitable for
unit tests and development machines without Redis or PostgreSQL.

Usage
-----
    from data_layer.tick_store import get_tick_store

    store = get_tick_store()

    # Insert a tick
    store.insert("XAUUSD", ts_ns=time.time_ns(), bid=2300.10, ask=2300.20)

    # Query last 1000 ticks
    df = store.query("XAUUSD", limit=1000)

    # Aggregate to OHLCV (1-minute bars)
    ohlcv_df = store.ohlcv("XAUUSD", timeframe_s=60, limit=200)

API
---
    TickStore.insert(symbol, ts_ns, bid, ask, *, volume=0.0, source="")
    TickStore.query(symbol, *, since_ns=0, until_ns=0, limit=500) → pd.DataFrame
    TickStore.ohlcv(symbol, timeframe_s, *, since_ns=0, limit=200)  → pd.DataFrame
    TickStore.latest(symbol) → dict | None
    TickStore.flush(symbol)   → int   (ticks deleted / evicted)
    TickStore.health()        → dict

Environment variables
---------------------
    TIMESCALEDB_URL          — PostgreSQL connection URL (enables Tier 1)
    REDIS_URL                — Redis URL (enables Tier 2, default: redis://localhost:6379/0)
    TICK_REDIS_RETENTION_MS  — Redis TS retention in ms (default: 172800000)
    TICK_MEMORY_MAX          — In-memory ring-buffer size per symbol (default: 10000)
    TICK_STORE_BACKEND       — Force a backend: timescaledb | redis | memory
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import timezone
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Environment configuration ────────────────────────────────────────────────
_TIMESCALEDB_URL: str = os.getenv("TIMESCALEDB_URL", "")
_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_REDIS_RETENTION_MS: int = int(os.getenv("TICK_REDIS_RETENTION_MS", str(48 * 3600 * 1000)))
_MEMORY_MAX: int = int(os.getenv("TICK_MEMORY_MAX", "10000"))
_FORCE_BACKEND: str = os.getenv("TICK_STORE_BACKEND", "").lower()

# ── Schema DDL for TimescaleDB ────────────────────────────────────────────────
_TIMESCALE_DDL = """
CREATE TABLE IF NOT EXISTS ticks (
    ts_ns       BIGINT        NOT NULL,
    symbol      TEXT          NOT NULL,
    bid         DOUBLE PRECISION NOT NULL,
    ask         DOUBLE PRECISION NOT NULL,
    mid         DOUBLE PRECISION GENERATED ALWAYS AS ((bid + ask) / 2.0) STORED,
    spread      DOUBLE PRECISION GENERATED ALWAYS AS (ask - bid) STORED,
    volume      DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    source      TEXT          NOT NULL DEFAULT ''
);
"""
# TimescaleDB hypertable — partitioned on (symbol, ts_ns expressed as TIMESTAMPTZ)
_TIMESCALE_HYPERTABLE = """
SELECT create_hypertable(
    'ticks', 'ts_ns',
    chunk_time_interval => 86400000000000,   -- 1 day in nanoseconds
    if_not_exists => TRUE
);
"""
_TIMESCALE_IDX = """
CREATE INDEX IF NOT EXISTS ticks_symbol_ts
    ON ticks (symbol, ts_ns DESC);
"""


# ── Tier 1: TimescaleDB backend ──────────────────────────────────────────────
class _TimescaleBackend:
    """
    TimescaleDB hypertable backend.

    Connects via psycopg2 (synchronous).  Uses a single persistent connection
    protected by a threading.Lock.  For production deployments with high tick
    ingestion rates, replace with a connection pool (psycopg2.pool.ThreadedConnectionPool).
    """

    def __init__(self, url: str) -> None:
        import threading

        try:
            import psycopg2  # type: ignore[import]
            import psycopg2.extras  # type: ignore[import]

            self._psycopg2 = psycopg2
            self._extras = psycopg2.extras
        except ImportError as exc:
            raise ImportError(
                "psycopg2 is required for TimescaleDB backend. Install with: pip install 'psycopg2-binary>=2.9'"
            ) from exc

        self._url = url
        self._conn = None
        self._lock = threading.Lock()
        self._connect()
        self._ensure_schema()
        logger.info("TickStore: TimescaleDB backend ready (%s)", url.split("@")[-1])

    def _connect(self) -> None:
        """Establish or re-establish the database connection."""
        try:
            self._conn = self._psycopg2.connect(self._url)
            self._conn.autocommit = True
        except Exception as exc:
            logger.error("TickStore: TimescaleDB connect failed: %s", exc)
            raise

    def _cur(self):
        """Return a DictCursor, reconnecting if the connection was lost."""
        with self._lock:
            try:
                _ = self._conn.isolation_level  # type: ignore[union-attr]  # poke the connection
            except Exception:
                logger.warning("TickStore: reconnecting to TimescaleDB")
                self._connect()
            return self._conn.cursor(cursor_factory=self._extras.RealDictCursor)  # type: ignore[union-attr]

    def _ensure_schema(self) -> None:
        with self._cur() as cur:
            cur.execute(_TIMESCALE_DDL)
            try:
                cur.execute(_TIMESCALE_HYPERTABLE)
            except Exception as exc:
                # May fail if TimescaleDB extension is not installed
                logger.warning("TickStore: could not create hypertable (is timescaledb installed?): %s", exc)
            cur.execute(_TIMESCALE_IDX)

    # ------------------------------------------------------------------

    def insert(
        self,
        symbol: str,
        ts_ns: int,
        bid: float,
        ask: float,
        volume: float = 0.0,
        source: str = "",
    ) -> None:
        sql = "INSERT INTO ticks (ts_ns, symbol, bid, ask, volume, source) VALUES (%s, %s, %s, %s, %s, %s)"
        with self._cur() as cur:
            cur.execute(sql, (ts_ns, symbol, bid, ask, volume, source))

    def query(
        self,
        symbol: str,
        *,
        since_ns: int = 0,
        until_ns: int = 0,
        limit: int = 500,
    ) -> list[dict]:
        conditions = ["symbol = %s"]
        params: list[Any] = [symbol]
        if since_ns:
            conditions.append("ts_ns >= %s")
            params.append(since_ns)
        if until_ns:
            conditions.append("ts_ns <= %s")
            params.append(until_ns)
        where = " AND ".join(conditions)
        sql = (
            f"SELECT ts_ns, bid, ask, mid, spread, volume, source FROM ticks WHERE {where} ORDER BY ts_ns DESC LIMIT %s"  # nosec B608 — clause built from hardcoded literals only; values are parameterized
        )
        params.append(limit)
        with self._cur() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def ohlcv(
        self,
        symbol: str,
        timeframe_s: int,
        *,
        since_ns: int = 0,
        limit: int = 200,
    ) -> list[dict]:
        """Aggregate ticks into OHLCV bars using SQL time bucketing."""
        bucket_ns = timeframe_s * 1_000_000_000
        conditions = ["symbol = %s"]
        params: list[Any] = [symbol]
        if since_ns:
            conditions.append("ts_ns >= %s")
            params.append(since_ns)
        where = " AND ".join(conditions)
        # where is built exclusively from hardcoded literal strings above —
        # no user input enters the clause text. Values use %s placeholders.
        sql = (
            "SELECT"
            " (ts_ns / %s) * %s AS bar_ts_ns,"
            " FIRST(mid, ts_ns) AS open,"
            " MAX(mid) AS high,"
            " MIN(mid) AS low,"
            " LAST(mid, ts_ns) AS close,"
            " SUM(volume) AS volume,"
            " COUNT(*) AS tick_count"
            " FROM ticks"
            " WHERE "
            + where  # nosec B608
            + " GROUP BY bar_ts_ns"
            " ORDER BY bar_ts_ns DESC"
            " LIMIT %s"
        )
        params = [bucket_ns, bucket_ns] + params + [limit]
        with self._cur() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def latest(self, symbol: str) -> dict | None:
        sql = "SELECT ts_ns, bid, ask, mid, spread, volume FROM ticks WHERE symbol = %s ORDER BY ts_ns DESC LIMIT 1"
        with self._cur() as cur:
            cur.execute(sql, (symbol,))
            row = cur.fetchone()
            return dict(row) if row else None

    def flush(self, symbol: str) -> int:
        sql = "DELETE FROM ticks WHERE symbol = %s"
        with self._cur() as cur:
            cur.execute(sql, (symbol,))
            return cur.rowcount

    def health(self) -> dict:
        try:
            with self._cur() as cur:
                cur.execute("SELECT 1")
            return {"backend": "timescaledb", "status": "ok"}
        except Exception as exc:
            return {"backend": "timescaledb", "status": "error", "detail": str(exc)}


# ── Tier 2: Redis TimeSeries backend ─────────────────────────────────────────
class _RedisTimeSeriesBackend:
    """
    Redis TimeSeries backend.

    Each symbol gets a Redis TimeSeries key per field (bid, ask, volume).
    The key format is:  ticks:{symbol}:{field}

    Requires Redis Stack or the RedisTimeSeries module.  Falls back gracefully
    to plain Redis sorted sets if TimeSeries commands are unavailable.
    """

    _TS_PREFIX = "ticks"

    def __init__(self, url: str, retention_ms: int = _REDIS_RETENTION_MS) -> None:
        try:
            import redis  # type: ignore[import]

            self._redis = redis
        except ImportError as exc:
            raise ImportError(
                "redis is required for Redis TimeSeries backend. Install with: pip install 'redis[hiredis]>=4.2'"
            ) from exc

        self._retention_ms = retention_ms
        self._url = url
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._has_ts = self._check_timeseries()
        logger.info(
            "TickStore: Redis backend ready | timeseries=%s retention=%ds",
            self._has_ts,
            retention_ms // 1000,
        )

    def _check_timeseries(self) -> bool:
        """Return True if the RedisTimeSeries module is available."""
        try:
            self._client.execute_command("TS.INFO", "probe_key_hopefx_init")
            return True
        except Exception as exc:
            if "Unknown command" in str(exc) or "ERR" in str(exc):
                logger.info("TickStore: RedisTimeSeries module not available — using sorted set fallback")
                return False
            # Key does not exist but command is known
            return True

    def _ts_key(self, symbol: str, field: str) -> str:
        return f"{self._TS_PREFIX}:{symbol}:{field}"

    def _ensure_ts_key(self, key: str) -> None:
        """Create a TimeSeries key with retention if it does not exist."""
        try:
            self._client.execute_command(
                "TS.CREATE",
                key,
                "RETENTION",
                self._retention_ms,
                "ON_DUPLICATE",
                "LAST",
                "DUPLICATE_POLICY",
                "LAST",
            )
        except Exception as exc:
            if "already exists" not in str(exc).lower():
                logger.debug("TickStore: TS.CREATE %s: %s", key, exc)

    def insert(
        self,
        symbol: str,
        ts_ns: int,
        bid: float,
        ask: float,
        volume: float = 0.0,
        source: str = "",
    ) -> None:
        ts_ms = ts_ns // 1_000_000
        if self._has_ts:
            for field, val in (("bid", bid), ("ask", ask), ("volume", volume)):
                key = self._ts_key(symbol, field)
                self._ensure_ts_key(key)
                try:
                    self._client.execute_command("TS.ADD", key, ts_ms, val)
                except Exception as exc:
                    logger.debug("TickStore: TS.ADD %s %s: %s", key, ts_ms, exc)
        else:
            # Sorted-set fallback: score = ts_ms, value = "bid|ask|volume|source"
            key = f"{self._TS_PREFIX}:{symbol}:ticks"
            val_str = f"{bid}|{ask}|{volume}|{source}"
            self._client.zadd(key, {f"{ts_ms}:{val_str}": ts_ms})
            # Trim to retention window
            cutoff = ts_ms - self._retention_ms
            self._client.zremrangebyscore(key, "-inf", cutoff)

    def query(
        self,
        symbol: str,
        *,
        since_ns: int = 0,
        until_ns: int = 0,
        limit: int = 500,
    ) -> list[dict]:
        since_ms = (since_ns // 1_000_000) if since_ns else "-"
        until_ms = (until_ns // 1_000_000) if until_ns else "+"
        rows: list[dict] = []

        if self._has_ts:
            try:
                bid_key = self._ts_key(symbol, "bid")
                ask_key = self._ts_key(symbol, "ask")
                bids = self._client.execute_command("TS.RANGE", bid_key, since_ms, until_ms, "COUNT", limit)
                asks_raw = self._client.execute_command("TS.RANGE", ask_key, since_ms, until_ms, "COUNT", limit)
                asks = {int(r[0]): float(r[1]) for r in asks_raw}
                for ts_ms_raw, bid_val in reversed(bids[-limit:]):
                    ts_ms = int(ts_ms_raw)
                    bid = float(bid_val)
                    ask = asks.get(ts_ms, bid)
                    mid = (bid + ask) / 2.0
                    rows.append(
                        {
                            "ts_ns": ts_ms * 1_000_000,
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "spread": ask - bid,
                            "volume": 0.0,
                        }
                    )
            except Exception as exc:
                logger.warning("TickStore: Redis TS.RANGE failed: %s", exc)
        else:
            key = f"{self._TS_PREFIX}:{symbol}:ticks"
            since_score = (since_ns // 1_000_000) if since_ns else "-inf"
            until_score = (until_ns // 1_000_000) if until_ns else "+inf"
            raw = self._client.zrangebyscore(
                key,
                since_score,
                until_score,
                start=0,
                num=limit,
                withscores=True,
            )
            for member, score in reversed(raw):
                parts = str(member).split("|", 3)
                if len(parts) >= 2:
                    bid = float(parts[0].split(":")[-1])
                    ask = float(parts[1])
                    volume = float(parts[2]) if len(parts) > 2 else 0.0
                    rows.append(
                        {
                            "ts_ns": int(score) * 1_000_000,
                            "bid": bid,
                            "ask": ask,
                            "mid": (bid + ask) / 2.0,
                            "spread": ask - bid,
                            "volume": volume,
                        }
                    )
        return rows

    def ohlcv(
        self,
        symbol: str,
        timeframe_s: int,
        *,
        since_ns: int = 0,
        limit: int = 200,
    ) -> list[dict]:
        """Aggregate tick data into OHLCV bars."""
        ticks = self.query(symbol, since_ns=since_ns, limit=limit * 200)
        return _aggregate_ohlcv(ticks, timeframe_s, limit)

    def latest(self, symbol: str) -> dict | None:
        rows = self.query(symbol, limit=1)
        return rows[0] if rows else None

    def flush(self, symbol: str) -> int:
        deleted = 0
        for field in ("bid", "ask", "volume", "ticks"):
            key = self._ts_key(symbol, field)
            deleted += self._client.delete(key)
        return deleted

    def health(self) -> dict:
        try:
            self._client.ping()
            return {"backend": "redis_timeseries", "status": "ok", "ts_module": self._has_ts}
        except Exception as exc:
            return {"backend": "redis_timeseries", "status": "error", "detail": str(exc)}


# ── Tier 3: In-memory deque backend ──────────────────────────────────────────
class _MemoryBackend:
    """
    In-memory ring-buffer backend.

    Ticks are stored in per-symbol deques of fixed maximum size.
    Data is lost on process restart.  Suitable for unit tests and
    development environments without Redis or PostgreSQL.
    """

    def __init__(self, max_per_symbol: int = _MEMORY_MAX) -> None:
        self._max = max_per_symbol
        self._store: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=self._max))
        logger.info("TickStore: in-memory backend ready (max_per_symbol=%d)", max_per_symbol)

    def insert(
        self,
        symbol: str,
        ts_ns: int,
        bid: float,
        ask: float,
        volume: float = 0.0,
        source: str = "",
    ) -> None:
        self._store[symbol].append(
            {
                "ts_ns": ts_ns,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2.0,
                "spread": ask - bid,
                "volume": volume,
                "source": source,
            }
        )

    def query(
        self,
        symbol: str,
        *,
        since_ns: int = 0,
        until_ns: int = 0,
        limit: int = 500,
    ) -> list[dict]:
        ticks = list(self._store[symbol])
        if since_ns:
            ticks = [t for t in ticks if t["ts_ns"] >= since_ns]
        if until_ns:
            ticks = [t for t in ticks if t["ts_ns"] <= until_ns]
        return list(reversed(ticks[-limit:]))

    def ohlcv(
        self,
        symbol: str,
        timeframe_s: int,
        *,
        since_ns: int = 0,
        limit: int = 200,
    ) -> list[dict]:
        ticks = self.query(symbol, since_ns=since_ns, limit=limit * 500)
        return _aggregate_ohlcv(ticks, timeframe_s, limit)

    def latest(self, symbol: str) -> dict | None:
        try:
            return self._store[symbol][-1]
        except IndexError:
            return None

    def flush(self, symbol: str) -> int:
        n = len(self._store[symbol])
        self._store[symbol].clear()
        return n

    def health(self) -> dict:
        total = sum(len(v) for v in self._store.values())
        return {
            "backend": "memory",
            "status": "ok",
            "symbols": len(self._store),
            "total_ticks": total,
        }


# ── Shared OHLCV aggregation ──────────────────────────────────────────────────
def _aggregate_ohlcv(ticks: list[dict], timeframe_s: int, limit: int) -> list[dict]:
    """
    Aggregate a list of tick dicts (with 'ts_ns' and 'mid' fields) into
    OHLCV bars of ``timeframe_s`` seconds.  Returns the most recent ``limit``
    bars, newest first.

    Open and close are determined by the earliest and latest tick timestamps
    within each bar, independent of the input ordering.
    """
    if not ticks:
        return []

    bucket_ns = timeframe_s * 1_000_000_000
    bars: dict[int, dict] = {}

    for tick in ticks:
        bar_key = (tick["ts_ns"] // bucket_ns) * bucket_ns
        mid = tick["mid"]
        vol = tick.get("volume", 0.0)
        ts = tick["ts_ns"]
        if bar_key not in bars:
            bars[bar_key] = {
                "bar_ts_ns": bar_key,
                "open": mid,
                "high": mid,
                "low": mid,
                "close": mid,
                "volume": vol,
                "tick_count": 1,
                "_open_ts": ts,
                "_close_ts": ts,
            }
        else:
            b = bars[bar_key]
            b["high"] = max(b["high"], mid)
            b["low"] = min(b["low"], mid)
            b["volume"] += vol
            b["tick_count"] += 1
            # open = mid at the earliest timestamp in the bar
            if ts < b["_open_ts"]:
                b["open"] = mid
                b["_open_ts"] = ts
            # close = mid at the latest timestamp in the bar
            if ts > b["_close_ts"]:
                b["close"] = mid
                b["_close_ts"] = ts

    # Remove internal tracking keys before returning
    for b in bars.values():
        b.pop("_open_ts", None)
        b.pop("_close_ts", None)

    sorted_bars = sorted(bars.values(), key=lambda b: b["bar_ts_ns"], reverse=True)
    return sorted_bars[:limit]


# ── Public TickStore façade ───────────────────────────────────────────────────
class TickStore:
    """
    Unified tick store with automatic backend selection and graceful fallback.

    Backend priority (highest to lowest):
        1. TimescaleDB  (TIMESCALEDB_URL set and psycopg2 installed)
        2. Redis TimeSeries  (Redis reachable, redis-py installed)
        3. In-memory deque  (always available)

    Override selection with TICK_STORE_BACKEND=timescaledb|redis|memory.
    """

    def __init__(self) -> None:
        self._backend = self._init_backend()
        self._backend_name: str = self._backend.__class__.__name__

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    @staticmethod
    def _init_backend():
        """Select and initialise the highest-priority available backend."""
        if _FORCE_BACKEND == "timescaledb" or (not _FORCE_BACKEND and _TIMESCALEDB_URL):
            try:
                return _TimescaleBackend(_TIMESCALEDB_URL)
            except Exception as exc:
                logger.warning("TickStore: TimescaleDB unavailable (%s) — trying Redis", exc)

        if _FORCE_BACKEND == "redis" or not _FORCE_BACKEND:
            try:
                b = _RedisTimeSeriesBackend(_REDIS_URL)
                b._client.ping()  # confirm Redis is reachable
                return b
            except Exception as exc:
                logger.warning("TickStore: Redis unavailable (%s) — using memory backend", exc)

        return _MemoryBackend()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def insert(
        self,
        symbol: str,
        ts_ns: int | None = None,
        bid: float = 0.0,
        ask: float = 0.0,
        *,
        volume: float = 0.0,
        source: str = "",
    ) -> None:
        """
        Insert a single tick.

        Parameters
        ----------
        symbol : Instrument symbol (e.g. ``"XAUUSD"``).
        ts_ns  : Timestamp in nanoseconds.  Defaults to ``time.time_ns()``.
        bid    : Bid price.
        ask    : Ask price.
        volume : Trade volume (0.0 for quote ticks).
        source : Data source tag (e.g. ``"oanda"``, ``"ibkr"``).
        """
        if ts_ns is None:
            ts_ns = time.time_ns()
        try:
            self._backend.insert(symbol, ts_ns, bid, ask, volume=volume, source=source)
        except Exception as exc:
            logger.error("TickStore.insert: %s", exc)

    def query(
        self,
        symbol: str,
        *,
        since_ns: int = 0,
        until_ns: int = 0,
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        Return recent ticks as a DataFrame.

        Columns: ts_ns, bid, ask, mid, spread, volume, [source]
        Sorted by ts_ns descending (newest first).
        """
        try:
            rows = self._backend.query(symbol, since_ns=since_ns, until_ns=until_ns, limit=limit)
        except Exception as exc:
            logger.error("TickStore.query: %s", exc)
            rows = []
        if not rows:
            return pd.DataFrame(columns=["ts_ns", "bid", "ask", "mid", "spread", "volume"])
        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["ts_ns"], unit="ns", utc=True)
        return df.sort_values("ts_ns", ascending=False).reset_index(drop=True)

    def ohlcv(
        self,
        symbol: str,
        timeframe_s: int = 60,
        *,
        since_ns: int = 0,
        limit: int = 200,
    ) -> pd.DataFrame:
        """
        Aggregate ticks into OHLCV bars.

        Parameters
        ----------
        symbol      : Instrument symbol.
        timeframe_s : Bar duration in seconds (e.g. 60 for 1-minute bars).
        since_ns    : Only aggregate ticks after this nanosecond timestamp.
        limit       : Maximum number of bars to return.

        Returns
        -------
        DataFrame with columns: bar_ts_ns, open, high, low, close, volume, tick_count.
        Sorted by bar_ts_ns descending (newest first).
        """
        try:
            bars = self._backend.ohlcv(symbol, timeframe_s, since_ns=since_ns, limit=limit)
        except Exception as exc:
            logger.error("TickStore.ohlcv: %s", exc)
            bars = []
        if not bars:
            return pd.DataFrame(columns=["bar_ts_ns", "open", "high", "low", "close", "volume", "tick_count"])
        df = pd.DataFrame(bars)
        df["bar_ts"] = pd.to_datetime(df["bar_ts_ns"], unit="ns", utc=True)
        return df.sort_values("bar_ts_ns", ascending=False).reset_index(drop=True)

    def latest(self, symbol: str) -> dict | None:
        """Return the most recent tick for a symbol, or None."""
        try:
            return self._backend.latest(symbol)
        except Exception as exc:
            logger.error("TickStore.latest: %s", exc)
            return None

    def flush(self, symbol: str) -> int:
        """Delete / evict all ticks for a symbol.  Returns count removed."""
        try:
            return self._backend.flush(symbol)
        except Exception as exc:
            logger.error("TickStore.flush: %s", exc)
            return 0

    def health(self) -> dict:
        """Return a health-check dict for the active backend."""
        try:
            info = self._backend.health()
        except Exception as exc:
            info = {"backend": "unknown", "status": "error", "detail": str(exc)}
        info["backend_class"] = self._backend_name
        return info

    def to_ohlcv_df(
        self,
        symbol: str,
        timeframe_s: int = 3600,
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        Convenience method that returns an OHLCV DataFrame compatible with the
        format expected by OHLCVStore and the ML inference pipeline.

        Columns: open, high, low, close, volume  (DatetimeIndex).
        """
        df = self.ohlcv(symbol, timeframe_s, limit=limit)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = df.rename(columns={"bar_ts": "datetime"})
        df = df.set_index("datetime")[["open", "high", "low", "close", "volume"]]
        return df.sort_index()


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: TickStore | None = None


def get_tick_store() -> TickStore:
    """
    Return the process-wide TickStore singleton.

    Thread-safe: the first call initialises the backend; subsequent calls
    return the cached instance.
    """
    global _instance
    if _instance is None:
        _instance = TickStore()
    return _instance
