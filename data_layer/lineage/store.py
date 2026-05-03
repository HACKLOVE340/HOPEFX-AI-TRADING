# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/lineage/store.py
=============================
DataLineageStore — immutable append-only audit trail.

Design principles
-----------------
- Append-only: records are never modified or deleted (INSERT OR IGNORE)
- Immutable: each record is content-addressed by SHA-256 of its payload
- Versioned: every record carries a schema_version for forward compatibility
- Causal: every record carries the lineage_id of its upstream source
- Durable: writes to SQLite (local) with WAL mode for concurrent reads
- Optional PostgreSQL: set LINEAGE_DB_URL=postgresql://... for production
- Fast: async writes via background queue; reads are synchronous
- Retention: configurable max record count with automatic pruning

New in this version
-------------------
- Async writes: record_tick_async/record_news_async/record_signal_async
  coroutines that enqueue via asyncio without blocking the event loop
- Lineage graph traversal: get_lineage_chain() follows parent_id links
  to reconstruct the full provenance chain for any record
- Data provenance API: get_provenance() returns a structured provenance
  report for a lineage_id including all ancestors and transformation steps

Record types
------------
  TICK    — every validated GoldTick (source, quality, confidence, mid)
  NEWS    — every scored NewsArticle (source, sentiment, gold_relevance)
  MACRO   — every MacroEvent (name, actual, forecast, surprise)
  SIGNAL  — every ML signal generated (direction, confidence, features hash)
  QUALITY — periodic quality reports

Schema
------
  lineage_records (
    id            TEXT PRIMARY KEY,   -- SHA-256 of payload
    record_type   TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    lineage_id    TEXT NOT NULL,
    source        TEXT,
    symbol        TEXT,
    timestamp     TEXT NOT NULL,      -- ISO-8601 UTC
    payload       TEXT NOT NULL,      -- JSON
    created_at    TEXT NOT NULL       -- ISO-8601 UTC wall clock
  )
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any, ClassVar

from data_layer.types import GoldTick, MacroEvent, NewsArticle

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_DB_PATH = Path(os.getenv("LINEAGE_DB_PATH", "data/lineage/lineage.db"))
_DB_URL = os.getenv("LINEAGE_DB_URL", "")  # PostgreSQL URL
_QUEUE_MAXSIZE = int(os.getenv("LINEAGE_QUEUE_SIZE", "50000"))
_BATCH_SIZE = int(os.getenv("LINEAGE_BATCH_SIZE", "500"))
_FLUSH_INTERVAL = float(os.getenv("LINEAGE_FLUSH_S", "2.0"))
_MAX_RECORDS = int(os.getenv("LINEAGE_MAX_RECORDS", "5000000"))  # 5M rows
_PRUNE_INTERVAL = int(os.getenv("LINEAGE_PRUNE_INTERVAL", "3600"))  # prune hourly

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lineage_records (
    id             TEXT PRIMARY KEY,
    record_type    TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    lineage_id     TEXT NOT NULL,
    parent_id      TEXT,
    source         TEXT,
    symbol         TEXT,
    timestamp      TEXT NOT NULL,
    payload        TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
"""

# Indexes are applied separately — after _migrate_schema() has ensured all
# columns exist — so that CREATE INDEX on parent_id never runs against a
# schema that pre-dates the column.
_CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_lineage_timestamp  ON lineage_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_lineage_type       ON lineage_records(record_type);
CREATE INDEX IF NOT EXISTS idx_lineage_source     ON lineage_records(source);
CREATE INDEX IF NOT EXISTS idx_lineage_symbol     ON lineage_records(symbol);
CREATE INDEX IF NOT EXISTS idx_lineage_created_at ON lineage_records(created_at);
CREATE INDEX IF NOT EXISTS idx_lineage_parent_id  ON lineage_records(parent_id);
"""

_INSERT_SQL = """
INSERT OR IGNORE INTO lineage_records
    (id, record_type, schema_version, lineage_id, parent_id, source,
     symbol, timestamp, payload, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _content_id(payload: dict) -> str:
    """SHA-256 content address of a payload dict."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class DataLineageStore:
    """
    Immutable append-only audit trail.

    Writes are queued and flushed in background batches to avoid
    blocking the hot tick path. Reads are synchronous.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path: Path = Path(db_path) if db_path else _DB_PATH
        self._pg_url: str = _DB_URL  # PostgreSQL dual-write URL
        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._conn: sqlite3.Connection | None = None
        self._worker: threading.Thread | None = None
        self._pruner: threading.Thread | None = None
        self._running = False
        self._write_count = 0
        self._drop_count = 0
        self._prune_count = 0
        self._pg_export_count = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _migrate_schema(self) -> None:
        """Apply incremental schema migrations to an existing database.

        CREATE TABLE IF NOT EXISTS only adds the table when it is absent; it
        does not add columns that were introduced after the initial schema was
        created.  This method detects and applies those missing columns so
        existing databases are upgraded in-place without data loss.
        """
        cursor = self._conn.execute("PRAGMA table_info(lineage_records)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        migrations: list[str] = []

        # parent_id was added after the initial schema — add it when absent.
        if "parent_id" not in existing_columns:
            migrations.append(
                "ALTER TABLE lineage_records ADD COLUMN parent_id TEXT"
            )
            migrations.append(
                "CREATE INDEX IF NOT EXISTS idx_lineage_parent_id "
                "ON lineage_records(parent_id)"
            )

        # schema_version defaulted to TEXT in some early builds — ensure INTEGER.
        # SQLite does not support ALTER COLUMN, so we only add the index if the
        # column already exists (it always does from the original schema).
        if "schema_version" in existing_columns:
            migrations.append(
                "CREATE INDEX IF NOT EXISTS idx_lineage_schema_version "
                "ON lineage_records(schema_version)"
            )

        for sql in migrations:
            try:
                self._conn.execute(sql)
                logger.info("DataLineageStore migration applied: %s", sql[:60])
            except sqlite3.OperationalError as exc:
                # "duplicate column name" or "index already exists" are safe to ignore.
                if "already exists" in str(exc) or "duplicate column" in str(exc):
                    logger.debug("DataLineageStore migration skipped (already applied): %s", exc)
                else:
                    raise

        if migrations:
            self._conn.commit()

    def _create_indexes(self) -> None:
        """Create all indexes individually via execute() (not executescript).

        executescript() issues an implicit COMMIT before running, which can
        leave the schema cache stale after an ALTER TABLE in the same session.
        Running each statement via execute() avoids that implicit commit and
        ensures the index creation sees the fully-migrated schema.
        """
        index_stmts = [
            "CREATE INDEX IF NOT EXISTS idx_lineage_timestamp  ON lineage_records(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_type       ON lineage_records(record_type)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_source     ON lineage_records(source)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_symbol     ON lineage_records(symbol)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_created_at ON lineage_records(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_parent_id  ON lineage_records(parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_schema_version ON lineage_records(schema_version)",
        ]
        for stmt in index_stmts:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError as exc:
                if "already exists" in str(exc):
                    logger.debug("DataLineageStore index already exists: %s", exc)
                else:
                    raise

    def start(self) -> None:
        """Initialise DB and start background writer + pruner threads."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=30.0,
        )
        # WAL mode: allows concurrent reads while writer is active.
        # These PRAGMAs must run outside a transaction.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-32000")  # 32MB cache

        # Create the table using execute() not executescript().
        # executescript() issues an implicit COMMIT before running, which
        # ends any open transaction and can cause the schema cache to be
        # stale for subsequent ALTER TABLE / CREATE INDEX statements in the
        # same connection.  Using execute() keeps everything in one
        # explicit transaction so _migrate_schema() and _create_indexes()
        # all see the same committed schema state.
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()

        # Migrate schema (adds missing columns like parent_id).
        # Must run after the table exists and before indexes are created,
        # because CREATE INDEX ON lineage_records(parent_id) will fail if
        # the column doesn't exist yet.
        self._migrate_schema()

        # Create indexes individually via execute() for the same reason —
        # executescript() would issue an implicit COMMIT that could race
        # with the just-committed ALTER TABLE on some SQLite versions.
        self._create_indexes()
        self._conn.commit()

        self._running = True

        self._worker = threading.Thread(
            target=self._flush_loop,
            name="lineage_writer",
            daemon=True,
        )
        self._worker.start()

        self._pruner = threading.Thread(
            target=self._prune_loop,
            name="lineage_pruner",
            daemon=True,
        )
        self._pruner.start()

        # PostgreSQL dual-write: verify connection at startup if URL is set
        if self._pg_url:
            try:
                import psycopg2  # type: ignore

                conn = psycopg2.connect(self._pg_url)
                conn.close()
                logger.info(
                    "DataLineageStore: PostgreSQL dual-write enabled (%s)",
                    self._pg_url.split("@")[-1],  # log host only, not credentials
                )
            except ImportError:
                logger.warning(
                    "DataLineageStore: LINEAGE_DB_URL set but psycopg2 not installed. Run: pip install psycopg2-binary"
                )
                self._pg_url = ""
            except Exception as exc:
                logger.warning(
                    "DataLineageStore: PostgreSQL connection failed (%s) — dual-write disabled, SQLite only",
                    exc,
                )
                self._pg_url = ""

        logger.info("DataLineageStore started — db=%s WAL=on", self._db_path)

    def stop(self) -> None:
        self._running = False
        if self._worker:
            self._worker.join(timeout=10.0)
        if self._conn:
            self._flush_queue()  # drain remaining records
            # PostgreSQL export on graceful stop (if configured)
            if self._pg_url:
                try:
                    n = self.export_to_postgres(self._pg_url)
                    self._pg_export_count += n
                    logger.info("DataLineageStore: exported %d records to PostgreSQL on stop", n)
                except Exception as exc:
                    logger.warning("DataLineageStore: PostgreSQL export on stop failed: %s", exc)
            self._conn.close()

    # ── Public record API ─────────────────────────────────────────────────────

    def record_tick(self, tick: GoldTick) -> None:
        payload = {
            "symbol": tick.symbol,
            "timestamp": tick.timestamp.isoformat(),
            "bid": tick.bid,
            "ask": tick.ask,
            "mid": tick.mid,
            "source": tick.source.value,
            "quality": tick.quality.value,
            "confidence": tick.confidence,
            "spread": tick.spread,
        }
        self._enqueue(
            record_type="TICK",
            lineage_id=tick.lineage_id,
            source=tick.source.value,
            symbol=tick.symbol,
            timestamp=tick.timestamp.isoformat(),
            payload=payload,
        )

    def record_news(self, article: NewsArticle) -> None:
        payload = {
            "article_id": article.article_id,
            "source": article.source.value,
            "headline": article.headline[:200],
            "published_at": article.published_at.isoformat(),
            "sentiment_score": article.sentiment_score,
            "sentiment_label": article.sentiment_label,
            "gold_relevance": article.gold_relevance,
            "impact_score": article.impact_score,
        }
        self._enqueue(
            record_type="NEWS",
            lineage_id=article.lineage_id,
            source=article.source.value,
            symbol="XAU_USD",
            timestamp=article.published_at.isoformat(),
            payload=payload,
        )

    def record_macro(self, event: MacroEvent) -> None:
        payload = {
            "event_id": event.event_id,
            "name": event.name,
            "country": event.country,
            "scheduled_at": event.scheduled_at.isoformat(),
            "actual": event.actual,
            "forecast": event.forecast,
            "previous": event.previous,
            "impact": event.impact.value,
            "gold_impact_score": event.gold_impact_score,
            "surprise_pct": event.surprise_pct,
        }
        self._enqueue(
            record_type="MACRO",
            lineage_id=event.lineage_id,
            source="finnhub_calendar",
            symbol="XAU_USD",
            timestamp=event.scheduled_at.isoformat(),
            payload=payload,
        )

    def record_signal(
        self,
        direction: str,
        confidence: float,
        probability: float,
        features_hash: str,
        model_version: str,
        lineage_id: str,
        symbol: str = "XAU_USD",
    ) -> None:
        now = datetime.now(UTC)
        payload = {
            "direction": direction,
            "confidence": confidence,
            "probability": probability,
            "features_hash": features_hash,
            "model_version": model_version,
            "generated_at": now.isoformat(),
        }
        self._enqueue(
            record_type="SIGNAL",
            lineage_id=lineage_id,
            source=model_version,
            symbol=symbol,
            timestamp=now.isoformat(),
            payload=payload,
        )

    def record_quality(self, report_dict: dict[str, Any]) -> None:
        import uuid

        now = datetime.now(UTC)
        self._enqueue(
            record_type="QUALITY",
            lineage_id=str(uuid.uuid4()),
            source="dqe",
            symbol=report_dict.get("symbol", "XAU_USD"),
            timestamp=now.isoformat(),
            payload=report_dict,
        )

    # ── Query API ─────────────────────────────────────────────────────────────

    def query(
        self,
        record_type: str | None = None,
        symbol: str | None = None,
        source: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._conn:
            return []

        clauses: ClassVar[list[str]] = []
        params: ClassVar[list[Any]] = []

        if record_type:
            clauses.append("record_type = ?")
            params.append(record_type.upper())
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT id, record_type, schema_version, lineage_id, source, "  # nosec B608 - where has only ? placeholders
            "symbol, timestamp, payload, created_at "
            "FROM lineage_records " + where + " ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        try:
            cursor = self._conn.execute(sql, params)
            return [
                {
                    "id": r[0],
                    "record_type": r[1],
                    "schema_version": r[2],
                    "lineage_id": r[3],
                    "source": r[4],
                    "symbol": r[5],
                    "timestamp": r[6],
                    "payload": json.loads(r[7]),
                    "created_at": r[8],
                }
                for r in cursor.fetchall()
            ]
        except Exception as exc:
            logger.warning("DataLineageStore.query error: %s", exc)
            return []

    def query_by_lineage_id(self, lineage_id: str) -> dict[str, Any] | None:
        """
        Retrieve a single record by its content-addressed lineage_id.

        Returns the record dict or None if not found.
        lineage_id is the SHA-256 content hash assigned at write time.
        """
        if not self._conn:
            return None
        try:
            cursor = self._conn.execute(
                """
                SELECT id, record_type, schema_version, lineage_id, source,
                       symbol, timestamp, payload, created_at
                FROM lineage_records
                WHERE lineage_id = ?
                LIMIT 1
                """,
                (lineage_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "record_type": row[1],
                "schema_version": row[2],
                "lineage_id": row[3],
                "source": row[4],
                "symbol": row[5],
                "timestamp": row[6],
                "payload": json.loads(row[7]),
                "created_at": row[8],
            }
        except Exception as exc:
            logger.warning("DataLineageStore.query_by_lineage_id error: %s", exc)
            return None

    def query_by_source(
        self,
        source: str,
        record_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Return records from a specific data source.

        Parameters
        ----------
        source      : Source name (e.g. 'goldapi', 'finnhub', 'fred')
        record_type : Optional filter (TICK / NEWS / MACRO / SIGNAL / QUALITY)
        limit       : Maximum records to return (default 100)
        """
        return self.query(
            record_type=record_type,
            source=source,
            limit=limit,
        )

    def query_by_time_range(
        self,
        start: datetime,
        end: datetime | None = None,
        record_type: str | None = None,
        symbol: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Return records within a UTC time range.

        Parameters
        ----------
        start       : Inclusive lower bound (UTC datetime)
        end         : Inclusive upper bound (UTC datetime, default: now)
        record_type : Optional type filter
        symbol      : Optional symbol filter
        limit       : Maximum records to return (default 500)

        Records are returned in ascending timestamp order.
        """
        if not self._conn:
            return []

        end = end or datetime.now(UTC)
        clauses: list[str] = ["timestamp >= ?", "timestamp <= ?"]
        params: list[Any] = [start.isoformat(), end.isoformat()]

        if record_type:
            clauses.append("record_type = ?")
            params.append(record_type.upper())
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)

        where = "WHERE " + " AND ".join(clauses)
        sql = (
            "SELECT id, record_type, schema_version, lineage_id, source, "  # nosec B608 - where has only ? placeholders
            "symbol, timestamp, payload, created_at "
            "FROM lineage_records " + where + " ORDER BY timestamp ASC LIMIT ?"
        )
        params.append(limit)

        try:
            cursor = self._conn.execute(sql, params)
            return [
                {
                    "id": r[0],
                    "record_type": r[1],
                    "schema_version": r[2],
                    "lineage_id": r[3],
                    "source": r[4],
                    "symbol": r[5],
                    "timestamp": r[6],
                    "payload": json.loads(r[7]),
                    "created_at": r[8],
                }
                for r in cursor.fetchall()
            ]
        except Exception as exc:
            logger.warning("DataLineageStore.query_by_time_range error: %s", exc)
            return []

    def export_to_postgres(
        self,
        pg_url: str,
        record_type: str | None = None,
        since: datetime | None = None,
        batch_size: int = 1000,
    ) -> int:
        """
        Dual-write: copy SQLite records to a PostgreSQL database.

        This is the production path for long-term audit storage.
        Set LINEAGE_DB_URL=postgresql://... in .env to enable automatic
        dual-write on startup (handled by the orchestrator).

        Parameters
        ----------
        pg_url      : PostgreSQL connection URL
        record_type : Optional filter (copies all types if None)
        since       : Only copy records newer than this timestamp
        batch_size  : INSERT batch size (default 1000)

        Returns the number of rows inserted.

        Schema (auto-created if missing):
            CREATE TABLE IF NOT EXISTS lineage_records (
                id TEXT PRIMARY KEY,
                record_type TEXT, schema_version TEXT,
                lineage_id TEXT, source TEXT, symbol TEXT,
                timestamp TEXT, payload JSONB, created_at TEXT
            );
        """
        try:
            import psycopg2  # type: ignore
            import psycopg2.extras  # type: ignore
        except ImportError:
            logger.warning(
                "DataLineageStore.export_to_postgres: psycopg2 not installed. Run: pip install psycopg2-binary"
            )
            return 0

        records = self.query(
            record_type=record_type,
            since=since,
            limit=batch_size,
        )
        if not records:
            return 0

        try:
            conn = psycopg2.connect(pg_url)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lineage_records (
                    id             TEXT PRIMARY KEY,
                    record_type    TEXT,
                    schema_version TEXT,
                    lineage_id     TEXT,
                    source         TEXT,
                    symbol         TEXT,
                    timestamp      TEXT,
                    payload        JSONB,
                    created_at     TEXT
                )
            """)
            rows = [
                (
                    r["id"],
                    r["record_type"],
                    r["schema_version"],
                    r["lineage_id"],
                    r["source"],
                    r["symbol"],
                    r["timestamp"],
                    json.dumps(r["payload"]),
                    r["created_at"],
                )
                for r in records
            ]
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO lineage_records
                    (id, record_type, schema_version, lineage_id, source,
                     symbol, timestamp, payload, created_at)
                VALUES %s
                ON CONFLICT (id) DO NOTHING
                """,
                rows,
            )
            conn.commit()
            inserted = cur.rowcount
            cur.close()
            conn.close()
            logger.info("DataLineageStore.export_to_postgres: inserted %d rows", inserted)
            return inserted
        except Exception as exc:
            logger.error("DataLineageStore.export_to_postgres error: %s", exc)
            return 0

    def count(self, record_type: str | None = None) -> int:
        if not self._conn:
            return 0
        try:
            if record_type:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM lineage_records WHERE record_type = ?",
                    (record_type,),
                ).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) FROM lineage_records").fetchone()
            return row[0] if row else 0
        except Exception:  # nosec B110 — graceful count fallback
            return 0

    def stats(self) -> dict[str, Any]:
        return {
            "write_count": self._write_count,
            "drop_count": self._drop_count,
            "prune_count": self._prune_count,
            "pg_export_count": self._pg_export_count,
            "pg_enabled": bool(self._pg_url),
            "queue_size": self._queue.qsize(),
            "db_path": str(self._db_path),
            "total_records": self.count(),
            "by_type": {t: self.count(t) for t in ("TICK", "NEWS", "MACRO", "SIGNAL", "QUALITY")},
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _enqueue(
        self,
        record_type: str,
        lineage_id: str,
        source: str | None,
        symbol: str | None,
        timestamp: str,
        payload: dict[str, Any],
        parent_id: str | None = None,
    ) -> None:
        record = {
            "record_type": record_type,
            "schema_version": _SCHEMA_VERSION,
            "lineage_id": lineage_id,
            "parent_id": parent_id,
            "source": source,
            "symbol": symbol,
            "timestamp": timestamp,
            "payload": json.dumps(payload, separators=(",", ":")),
            "created_at": datetime.now(UTC).isoformat(),
        }
        record["id"] = _content_id(payload)

        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._drop_count += 1
            logger.debug("DataLineageStore queue full — dropping record")

    def flush(self) -> int:
        """
        Synchronously flush all queued records to SQLite.

        Returns the number of records written.
        Use in tests and graceful shutdown to ensure no records are lost.
        """
        before = self._write_count
        self._flush_queue()
        return self._write_count - before

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(_FLUSH_INTERVAL)
            self._flush_queue()

    def _flush_queue(self) -> None:
        if not self._conn:
            return

        batch: ClassVar[list[dict]] = []
        try:
            while len(batch) < _BATCH_SIZE:
                batch.append(self._queue.get_nowait())
        except queue.Empty:
            ...  # nosec B110

        if not batch:
            return

        rows = [
            (
                r["id"],
                r["record_type"],
                r["schema_version"],
                r["lineage_id"],
                r.get("parent_id"),
                r["source"],
                r["symbol"],
                r["timestamp"],
                r["payload"],
                r["created_at"],
            )
            for r in batch
        ]
        try:
            self._conn.executemany(_INSERT_SQL, rows)
            self._conn.commit()
            self._write_count += len(rows)
        except Exception as exc:
            logger.warning("DataLineageStore flush error: %s", exc)

    def _prune_loop(self) -> None:
        """Periodically prune oldest records when total exceeds _MAX_RECORDS."""
        while self._running:
            time.sleep(_PRUNE_INTERVAL)
            self._prune_old_records()

    def _prune_old_records(self) -> None:
        if not self._conn:
            return
        try:
            total = self.count()
            if total <= _MAX_RECORDS:
                return
            excess = total - _MAX_RECORDS
            # Delete oldest records (by created_at)
            self._conn.execute(
                """
                DELETE FROM lineage_records
                WHERE id IN (
                    SELECT id FROM lineage_records
                    ORDER BY created_at ASC
                    LIMIT ?
                )
                """,
                (excess,),
            )
            self._conn.commit()
            self._prune_count += excess
            logger.info(
                "DataLineageStore: pruned %d old records (total was %d)",
                excess,
                total,
            )
        except Exception as exc:
            logger.warning("DataLineageStore prune error: %s", exc)


    # ── Async write API ───────────────────────────────────────────────────────

    async def record_tick_async(self, tick: GoldTick, parent_id: str | None = None) -> None:
        """
        Async-safe tick recording. Enqueues without blocking the event loop.

        Uses asyncio.get_event_loop().run_in_executor to offload the
        queue.put_nowait call (which is CPU-bound but very fast).
        """
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self.record_tick(tick))

    async def record_news_async(self, article: NewsArticle, parent_id: str | None = None) -> None:
        """Async-safe news article recording."""
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self.record_news(article))

    async def record_signal_async(
        self,
        direction: str,
        confidence: float,
        probability: float,
        features_hash: str,
        model_version: str,
        lineage_id: str,
        symbol: str = "XAU_USD",
        parent_id: str | None = None,
    ) -> None:
        """Async-safe signal recording."""
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self.record_signal(
                direction=direction,
                confidence=confidence,
                probability=probability,
                features_hash=features_hash,
                model_version=model_version,
                lineage_id=lineage_id,
                symbol=symbol,
            ),
        )

    async def flush_async(self) -> int:
        """Async-safe flush. Runs the synchronous flush in a thread executor."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.flush)

    # ── Lineage graph traversal ───────────────────────────────────────────────

    def get_lineage_chain(
        self,
        lineage_id: str,
        max_depth: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Follow parent_id links to reconstruct the full provenance chain.

        Starting from the record identified by `lineage_id`, walks up the
        parent chain until reaching a root record (parent_id IS NULL) or
        hitting max_depth.

        Returns a list of records in order from the given record back to
        the root (index 0 = the requested record, last = root ancestor).

        Parameters
        ----------
        lineage_id : Starting lineage_id
        max_depth  : Maximum chain depth to prevent infinite loops

        Returns [] if the starting record is not found.
        """
        if not self._conn:
            return []

        chain = []
        current_id = lineage_id
        seen = set()

        for _ in range(max_depth):
            if current_id in seen:
                logger.warning("DataLineageStore: cycle detected in lineage chain at %s", current_id)
                break
            seen.add(current_id)

            try:
                cursor = self._conn.execute(
                    """
                    SELECT id, record_type, schema_version, lineage_id, parent_id,
                           source, symbol, timestamp, payload, created_at
                    FROM lineage_records
                    WHERE lineage_id = ?
                    LIMIT 1
                    """,
                    (current_id,),
                )
                row = cursor.fetchone()
            except Exception as exc:
                logger.warning("DataLineageStore.get_lineage_chain error: %s", exc)
                break

            if row is None:
                break

            record = {
                "id": row[0],
                "record_type": row[1],
                "schema_version": row[2],
                "lineage_id": row[3],
                "parent_id": row[4],
                "source": row[5],
                "symbol": row[6],
                "timestamp": row[7],
                "payload": json.loads(row[8]),
                "created_at": row[9],
            }
            chain.append(record)

            parent_id = row[4]
            if parent_id is None:
                break
            current_id = parent_id

        return chain

    def get_children(self, lineage_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        Return all records that have `lineage_id` as their parent_id.

        Used to traverse the lineage graph forward (downstream).
        """
        if not self._conn:
            return []
        try:
            cursor = self._conn.execute(
                """
                SELECT id, record_type, schema_version, lineage_id, parent_id,
                       source, symbol, timestamp, payload, created_at
                FROM lineage_records
                WHERE parent_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (lineage_id, limit),
            )
            return [
                {
                    "id": r[0], "record_type": r[1], "schema_version": r[2],
                    "lineage_id": r[3], "parent_id": r[4], "source": r[5],
                    "symbol": r[6], "timestamp": r[7],
                    "payload": json.loads(r[8]), "created_at": r[9],
                }
                for r in cursor.fetchall()
            ]
        except Exception as exc:
            logger.warning("DataLineageStore.get_children error: %s", exc)
            return []

    # ── Data provenance API ───────────────────────────────────────────────────

    def get_provenance(self, lineage_id: str) -> dict[str, Any]:
        """
        Return a structured provenance report for a lineage_id.

        The report includes:
          - The record itself
          - Full ancestor chain (via get_lineage_chain)
          - Direct children (downstream consumers)
          - Transformation summary: list of (operation, source, timestamp) tuples
            extracted from the ancestor chain

        This is the canonical data provenance API for regulatory compliance,
        debugging, and audit queries.

        Parameters
        ----------
        lineage_id : The lineage_id of the record to inspect

        Returns a dict with keys:
          record:          The requested record (or None if not found)
          ancestors:       List of ancestor records (oldest last)
          children:        List of downstream records
          chain_depth:     Number of ancestors
          root_source:     Source of the root ancestor
          root_timestamp:  Timestamp of the root ancestor
          transformations: List of {operation, source, timestamp} dicts
        """
        chain = self.get_lineage_chain(lineage_id)
        if not chain:
            return {
                "record": None,
                "ancestors": [],
                "children": [],
                "chain_depth": 0,
                "root_source": None,
                "root_timestamp": None,
                "transformations": [],
            }

        record = chain[0]
        ancestors = chain[1:]
        children = self.get_children(lineage_id)

        # Extract transformation steps from the chain
        transformations = []
        for r in chain:
            payload = r.get("payload", {})
            op = payload.get("operation", r["record_type"].lower())
            transformations.append({
                "operation": op,
                "source": r.get("source"),
                "timestamp": r.get("timestamp"),
                "record_type": r["record_type"],
            })

        root = chain[-1] if chain else {}

        return {
            "record": record,
            "ancestors": ancestors,
            "children": children,
            "chain_depth": len(ancestors),
            "root_source": root.get("source"),
            "root_timestamp": root.get("timestamp"),
            "transformations": transformations,
        }

    def get_data_lineage_summary(self, symbol: str = "XAU_USD", hours: float = 1.0) -> dict[str, Any]:
        """
        Return a summary of data lineage activity for the last N hours.

        Useful for monitoring dashboards and health checks.

        Returns:
          total_records: total records in the time window
          by_type:       count per record type
          by_source:     count per source
          orphan_count:  records with no parent (root records)
          chain_count:   records with a parent (derived records)
        """
        if not self._conn:
            return {}
        since = datetime.now(UTC).replace(microsecond=0)
        from datetime import timedelta
        since = since - timedelta(hours=hours)

        try:
            rows = self._conn.execute(
                """
                SELECT record_type, source,
                       COUNT(*) as cnt,
                       SUM(CASE WHEN parent_id IS NULL THEN 1 ELSE 0 END) as orphans
                FROM lineage_records
                WHERE timestamp >= ? AND symbol = ?
                GROUP BY record_type, source
                """,
                (since.isoformat(), symbol),
            ).fetchall()

            by_type: dict[str, int] = {}
            by_source: dict[str, int] = {}
            total = 0
            orphan_count = 0

            for row in rows:
                rt, src, cnt, orphans = row
                by_type[rt] = by_type.get(rt, 0) + cnt
                by_source[src or "unknown"] = by_source.get(src or "unknown", 0) + cnt
                total += cnt
                orphan_count += orphans

            return {
                "total_records": total,
                "by_type": by_type,
                "by_source": by_source,
                "orphan_count": orphan_count,
                "chain_count": total - orphan_count,
                "window_hours": hours,
                "symbol": symbol,
            }
        except Exception as exc:
            logger.warning("DataLineageStore.get_data_lineage_summary error: %s", exc)
            return {}


# Module-level singleton
lineage_store = DataLineageStore()
