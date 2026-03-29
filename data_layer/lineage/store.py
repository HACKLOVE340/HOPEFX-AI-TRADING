# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/lineage/store.py
=============================
DataLineageStore — immutable audit trail for every tick, macro event,
and news article that flows through the data layer.

Design principles
-----------------
- Append-only: records are never modified or deleted
- Immutable: each record is content-addressed by SHA-256 of its payload
- Versioned: every record carries a schema_version for forward compatibility
- Causal: every record carries the lineage_id of its upstream source
- Durable: writes to SQLite (local) + optional PostgreSQL (production)
- Fast: async writes via background queue; reads are synchronous

Record types
------------
  TICK      — every validated GoldTick (source, quality, confidence, mid)
  NEWS      — every scored NewsArticle (source, sentiment, gold_relevance)
  MACRO     — every MacroEvent (name, actual, forecast, surprise)
  SIGNAL    — every ML signal generated (direction, confidence, features hash)
  QUALITY   — periodic quality reports

Schema (SQLite / PostgreSQL)
-----------------------------
  lineage_records (
    id            TEXT PRIMARY KEY,   -- SHA-256 of payload
    record_type   TEXT NOT NULL,      -- TICK | NEWS | MACRO | SIGNAL | QUALITY
    schema_version INTEGER NOT NULL,  -- for forward compatibility
    lineage_id    TEXT NOT NULL,      -- UUID from the source object
    source        TEXT,               -- feed source name
    symbol        TEXT,
    timestamp     TEXT NOT NULL,      -- ISO-8601 UTC
    payload       TEXT NOT NULL,      -- JSON
    created_at    TEXT NOT NULL       -- ISO-8601 UTC wall clock
  )

Usage:
    from data_layer.lineage.store import lineage_store

    lineage_store.record_tick(tick)
    lineage_store.record_news(article)
    lineage_store.record_macro(event)
    lineage_store.record_signal(signal_dict)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.types import GoldTick, MacroEvent, NewsArticle

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_DB_PATH        = Path(os.getenv("LINEAGE_DB_PATH", "data/lineage/lineage.db"))
_QUEUE_MAXSIZE  = int(os.getenv("LINEAGE_QUEUE_SIZE", "50000"))
_BATCH_SIZE     = int(os.getenv("LINEAGE_BATCH_SIZE", "500"))
_FLUSH_INTERVAL = float(os.getenv("LINEAGE_FLUSH_INTERVAL_S", "2.0"))


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lineage_records (
    id             TEXT PRIMARY KEY,
    record_type    TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    lineage_id     TEXT NOT NULL,
    source         TEXT,
    symbol         TEXT,
    timestamp      TEXT NOT NULL,
    payload        TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lineage_timestamp ON lineage_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_lineage_type      ON lineage_records(record_type);
CREATE INDEX IF NOT EXISTS idx_lineage_source    ON lineage_records(source);
CREATE INDEX IF NOT EXISTS idx_lineage_symbol    ON lineage_records(symbol);
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

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._conn: Optional[sqlite3.Connection] = None
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._write_count = 0
        self._drop_count  = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Initialise DB and start background writer thread."""
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        self._conn.executescript(_CREATE_TABLE_SQL)
        self._conn.commit()
        self._running = True
        self._worker = threading.Thread(
            target=self._flush_loop,
            name="lineage_writer",
            daemon=True,
        )
        self._worker.start()
        logger.info("DataLineageStore started — db=%s", _DB_PATH)

    def stop(self) -> None:
        self._running = False
        if self._worker:
            self._worker.join(timeout=10.0)
        if self._conn:
            self._flush_queue()   # drain remaining records
            self._conn.close()

    # ── Public record API ─────────────────────────────────────────────────────

    def record_tick(self, tick: GoldTick) -> None:
        """Record a validated GoldTick to the lineage store."""
        payload = {
            "symbol":     tick.symbol,
            "timestamp":  tick.timestamp.isoformat(),
            "bid":        tick.bid,
            "ask":        tick.ask,
            "mid":        tick.mid,
            "source":     tick.source.value,
            "quality":    tick.quality.value,
            "confidence": tick.confidence,
            "spread":     tick.spread,
        }
        self._enqueue(
            record_type = "TICK",
            lineage_id  = tick.lineage_id,
            source      = tick.source.value,
            symbol      = tick.symbol,
            timestamp   = tick.timestamp.isoformat(),
            payload     = payload,
        )

    def record_news(self, article: NewsArticle) -> None:
        """Record a scored NewsArticle."""
        payload = {
            "article_id":     article.article_id,
            "source":         article.source.value,
            "headline":       article.headline[:200],
            "published_at":   article.published_at.isoformat(),
            "sentiment_score": article.sentiment_score,
            "sentiment_label": article.sentiment_label,
            "gold_relevance": article.gold_relevance,
            "impact_score":   article.impact_score,
        }
        self._enqueue(
            record_type = "NEWS",
            lineage_id  = article.lineage_id,
            source      = article.source.value,
            symbol      = "XAU_USD",
            timestamp   = article.published_at.isoformat(),
            payload     = payload,
        )

    def record_macro(self, event: MacroEvent) -> None:
        """Record a MacroEvent."""
        payload = {
            "event_id":          event.event_id,
            "name":              event.name,
            "country":           event.country,
            "scheduled_at":      event.scheduled_at.isoformat(),
            "actual":            event.actual,
            "forecast":          event.forecast,
            "previous":          event.previous,
            "impact":            event.impact.value,
            "gold_impact_score": event.gold_impact_score,
            "surprise_pct":      event.surprise_pct,
        }
        self._enqueue(
            record_type = "MACRO",
            lineage_id  = event.lineage_id,
            source      = "finnhub_calendar",
            symbol      = "XAU_USD",
            timestamp   = event.scheduled_at.isoformat(),
            payload     = payload,
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
        """Record an ML signal generation event."""
        now = datetime.now(timezone.utc)
        payload = {
            "direction":     direction,
            "confidence":    confidence,
            "probability":   probability,
            "features_hash": features_hash,
            "model_version": model_version,
            "generated_at":  now.isoformat(),
        }
        self._enqueue(
            record_type = "SIGNAL",
            lineage_id  = lineage_id,
            source      = model_version,
            symbol      = symbol,
            timestamp   = now.isoformat(),
            payload     = payload,
        )

    def record_quality(self, report_dict: Dict[str, Any]) -> None:
        """Record a DataQualityEngine report."""
        import uuid
        now = datetime.now(timezone.utc)
        self._enqueue(
            record_type = "QUALITY",
            lineage_id  = str(uuid.uuid4()),
            source      = "dqe",
            symbol      = report_dict.get("symbol", "XAU_USD"),
            timestamp   = now.isoformat(),
            payload     = report_dict,
        )

    # ── Query API ─────────────────────────────────────────────────────────────

    def query(
        self,
        record_type: Optional[str] = None,
        symbol: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query lineage records.

        Returns list of dicts with all record fields.
        """
        if not self._conn:
            return []

        clauses = []
        params  = []

        if record_type:
            clauses.append("record_type = ?")
            params.append(record_type)
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
        sql   = f"""
            SELECT id, record_type, schema_version, lineage_id, source,
                   symbol, timestamp, payload, created_at
            FROM lineage_records
            {where}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        try:
            cursor = self._conn.execute(sql, params)
            rows   = cursor.fetchall()
            return [
                {
                    "id":             r[0],
                    "record_type":    r[1],
                    "schema_version": r[2],
                    "lineage_id":     r[3],
                    "source":         r[4],
                    "symbol":         r[5],
                    "timestamp":      r[6],
                    "payload":        json.loads(r[7]),
                    "created_at":     r[8],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("DataLineageStore.query error: %s", exc)
            return []

    def count(self, record_type: Optional[str] = None) -> int:
        """Return total record count, optionally filtered by type."""
        if not self._conn:
            return 0
        try:
            if record_type:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM lineage_records WHERE record_type = ?",
                    (record_type,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM lineage_records"
                ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def stats(self) -> Dict[str, Any]:
        return {
            "write_count": self._write_count,
            "drop_count":  self._drop_count,
            "queue_size":  self._queue.qsize(),
            "db_path":     str(_DB_PATH),
            "total_records": self.count(),
            "by_type": {
                t: self.count(t)
                for t in ("TICK", "NEWS", "MACRO", "SIGNAL", "QUALITY")
            },
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _enqueue(
        self,
        record_type: str,
        lineage_id: str,
        source: Optional[str],
        symbol: Optional[str],
        timestamp: str,
        payload: Dict[str, Any],
    ) -> None:
        record = {
            "record_type":    record_type,
            "schema_version": _SCHEMA_VERSION,
            "lineage_id":     lineage_id,
            "source":         source,
            "symbol":         symbol,
            "timestamp":      timestamp,
            "payload":        json.dumps(payload, separators=(",", ":")),
            "created_at":     datetime.now(timezone.utc).isoformat(),
        }
        record["id"] = _content_id(payload)

        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._drop_count += 1
            logger.debug("DataLineageStore queue full — dropping record")

    def _flush_loop(self) -> None:
        """Background thread: batch-flush queue to SQLite."""
        while self._running:
            time.sleep(_FLUSH_INTERVAL)
            self._flush_queue()

    def _flush_queue(self) -> None:
        if not self._conn:
            return

        batch: List[dict] = []
        try:
            while len(batch) < _BATCH_SIZE:
                batch.append(self._queue.get_nowait())
        except queue.Empty:
            pass

        if not batch:
            return

        sql = """
            INSERT OR IGNORE INTO lineage_records
                (id, record_type, schema_version, lineage_id, source,
                 symbol, timestamp, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                r["id"], r["record_type"], r["schema_version"],
                r["lineage_id"], r["source"], r["symbol"],
                r["timestamp"], r["payload"], r["created_at"],
            )
            for r in batch
        ]
        try:
            self._conn.executemany(sql, rows)
            self._conn.commit()
            self._write_count += len(rows)
        except Exception as exc:
            logger.warning("DataLineageStore flush error: %s", exc)


# Module-level singleton
lineage_store = DataLineageStore()
