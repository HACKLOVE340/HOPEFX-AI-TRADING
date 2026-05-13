# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/optimization.py
========================
Query analysis, slow-query logging, and index recommendations.

Three modes of operation
------------------------
1. **Dev CLI** — ``python -m database.optimization`` prints a full diagnostic
   report against DATABASE_URL.

2. **Runtime slow-query logger** — import ``SlowQueryLogger`` and attach it
   to a SQLAlchemy engine via ``slow_query_logger.attach(engine)``.  Every
   query exceeding the threshold is logged with its execution plan.

3. **Index advisor** — ``IndexAdvisor.recommend(engine)`` inspects
   pg_stat_user_indexes / pg_stat_user_tables and returns actionable
   recommendations (unused indexes to drop, missing indexes to create,
   tables needing VACUUM).

SECURITY RULES (non-negotiable):
1. Only hardcoded allowlist queries may be executed by the CLI.
2. SlowQueryLogger captures SQLAlchemy-emitted query text — never accepts
   query strings from external callers.
3. IndexAdvisor only reads pg_stat_* views — never modifies the schema.
4. No user input ever reaches a SQL string.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Hardcoded query allowlist ─────────────────────────────────────────────────
_ALLOWED_QUERIES: dict[str, str] = {
    "table_sizes": """
        SELECT relname AS table,
               pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
               pg_size_pretty(pg_relation_size(relid)) AS table_size,
               pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) AS index_size
        FROM pg_catalog.pg_statio_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 20;
    """,
    "slow_queries": """
        SELECT query,
               calls,
               round(total_exec_time::numeric, 2) AS total_ms,
               round(mean_exec_time::numeric, 2)  AS mean_ms,
               round(stddev_exec_time::numeric, 2) AS stddev_ms,
               rows
        FROM pg_stat_statements
        ORDER BY mean_exec_time DESC
        LIMIT 20;
    """,
    "index_usage": """
        SELECT schemaname,
               relname      AS table,
               indexrelname AS index,
               idx_scan,
               idx_tup_read,
               idx_tup_fetch,
               pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
        FROM pg_stat_user_indexes
        ORDER BY idx_scan ASC
        LIMIT 30;
    """,
    "missing_indexes": """
        SELECT schemaname,
               relname AS table,
               seq_scan,
               seq_tup_read,
               idx_scan,
               n_live_tup AS live_rows,
               round(seq_scan::numeric / NULLIF(seq_scan + idx_scan, 0) * 100, 1) AS seq_scan_pct
        FROM pg_stat_user_tables
        WHERE seq_scan > 100
          AND n_live_tup > 1000
        ORDER BY seq_scan DESC
        LIMIT 20;
    """,
    "bloat_estimate": """
        SELECT schemaname,
               tablename,
               pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size,
               n_dead_tup,
               n_live_tup,
               round(n_dead_tup::numeric / NULLIF(n_live_tup + n_dead_tup, 0) * 100, 1) AS dead_pct,
               last_autovacuum,
               last_autoanalyze
        FROM pg_stat_user_tables
        WHERE n_dead_tup > 1000
        ORDER BY n_dead_tup DESC
        LIMIT 20;
    """,
    "lock_waits": """
        SELECT pid,
               now() - pg_stat_activity.query_start AS duration,
               query,
               state,
               wait_event_type,
               wait_event
        FROM pg_stat_activity
        WHERE state != 'idle'
          AND query_start < now() - INTERVAL '5 seconds'
        ORDER BY duration DESC
        LIMIT 20;
    """,
    "connection_stats": """
        SELECT state,
               count(*) AS connections,
               max(now() - state_change) AS max_idle_time
        FROM pg_stat_activity
        WHERE datname = current_database()
        GROUP BY state
        ORDER BY connections DESC;
    """,
    "cache_hit_ratio": """
        SELECT sum(heap_blks_read)  AS heap_read,
               sum(heap_blks_hit)   AS heap_hit,
               round(
                   sum(heap_blks_hit)::numeric /
                   NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0) * 100,
                   2
               ) AS cache_hit_pct
        FROM pg_statio_user_tables;
    """,
}


def _assert_dev_only() -> None:
    """Block execution in any non-development environment."""
    env = os.getenv("APP_ENV", "development").lower()
    if env not in ("development", "dev", "test"):
        raise RuntimeError(
            f"database/optimization.py is a dev/test-only tool and cannot run "
            f"in APP_ENV={env!r}. Use pg_stat_statements or your DBA tooling in production."
        )


def analyze_query_performance(query_name: str) -> list[dict]:
    """
    Run a named query from the allowlist and return rows as dicts.

    Args:
        query_name: Key from _ALLOWED_QUERIES. Raises ValueError for unknown names.

    Returns:
        List of row dicts with an extra ``_elapsed_ms`` key.
    """
    _assert_dev_only()

    if query_name not in _ALLOWED_QUERIES:
        raise ValueError(f"Unknown query {query_name!r}. Allowed: {sorted(_ALLOWED_QUERIES)}")

    query = _ALLOWED_QUERIES[query_name]
    database_uri = os.getenv("DATABASE_URL")
    if not database_uri:
        raise RuntimeError("DATABASE_URL environment variable is not set.")

    from sqlalchemy import create_engine, text

    engine = create_engine(database_uri)
    t0 = time.perf_counter()
    with engine.connect() as conn:
        result = conn.execute(text(query))
        rows = [dict(r._mapping) for r in result.fetchall()]
    elapsed_ms = (time.perf_counter() - t0) * 1000

    logger.info("Query %r: %d rows in %.2f ms", query_name, len(rows), elapsed_ms)
    for row in rows:
        logger.info("  %s", row)

    for row in rows:
        row["_elapsed_ms"] = round(elapsed_ms, 2)
    return rows


# ── Slow-query logger ─────────────────────────────────────────────────────────


@dataclass
class SlowQueryRecord:
    """A single slow-query capture."""

    query: str
    params: Any
    elapsed_ms: float
    timestamp: float = field(default_factory=time.time)
    explain_plan: str = ""


class SlowQueryLogger:
    """
    SQLAlchemy event listener that logs queries exceeding a threshold.

    Attach to an engine at startup::

        from database.optimization import slow_query_logger
        slow_query_logger.attach(engine)

    The last ``history_size`` slow queries are kept in memory and accessible
    via ``slow_query_logger.get_history()``.

    Environment variables:
        SLOW_QUERY_THRESHOLD_MS  — threshold in ms (default: 200)
        SLOW_QUERY_EXPLAIN       — set to "true" to capture EXPLAIN ANALYZE
    """

    def __init__(
        self,
        threshold_ms: float = 200.0,
        explain: bool = False,
        history_size: int = 100,
    ) -> None:
        self.threshold_ms = threshold_ms
        self.explain = explain
        self._history: deque[SlowQueryRecord] = deque(maxlen=history_size)
        self._lock = threading.Lock()
        self._total_slow = 0
        self._total_queries = 0

    def attach(self, engine: Any) -> None:
        """Register before/after cursor execute listeners on the engine."""
        from sqlalchemy import event

        event.listen(engine, "before_cursor_execute", self._before, retval=True)
        event.listen(engine, "after_cursor_execute", self._after)
        logger.info(
            "SlowQueryLogger attached (threshold=%.0f ms, explain=%s)",
            self.threshold_ms,
            self.explain,
        )

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        context._sqlog_t0 = time.perf_counter()
        return statement, parameters

    def _after(self, conn, cursor, statement, parameters, context, executemany):
        t0 = getattr(context, "_sqlog_t0", None)
        if t0 is None:
            return
        elapsed_ms = (time.perf_counter() - t0) * 1000
        with self._lock:
            self._total_queries += 1
        if elapsed_ms < self.threshold_ms:
            return

        explain_plan = ""
        if self.explain and "postgresql" in str(conn.engine.url):
            try:
                from sqlalchemy import text as _text

                # statement is SQLAlchemy-generated DDL/DML — never user input
                plan_rows = conn.execute(  # nosec B608
                    _text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {statement}")
                ).fetchall()
                explain_plan = "\n".join(r[0] for r in plan_rows)
            except Exception as exc:
                explain_plan = f"EXPLAIN failed: {exc}"

        record = SlowQueryRecord(
            query=statement[:2000],
            params=parameters,
            elapsed_ms=round(elapsed_ms, 2),
            explain_plan=explain_plan,
        )
        with self._lock:
            self._history.append(record)
            self._total_slow += 1

        logger.warning(
            "SLOW QUERY (%.2f ms > %.0f ms threshold):\n%s",
            elapsed_ms,
            self.threshold_ms,
            statement[:500],
        )
        if explain_plan:
            logger.warning("EXPLAIN PLAN:\n%s", explain_plan[:2000])

    def get_history(self) -> list[SlowQueryRecord]:
        """Return a snapshot of the slow-query history (newest last)."""
        with self._lock:
            return list(self._history)

    def stats(self) -> dict:
        """Return aggregate statistics."""
        with self._lock:
            return {
                "total_queries": self._total_queries,
                "total_slow": self._total_slow,
                "slow_pct": round(self._total_slow / max(self._total_queries, 1) * 100, 2),
                "threshold_ms": self.threshold_ms,
                "history_size": len(self._history),
            }

    def reset(self) -> None:
        """Clear history and counters."""
        with self._lock:
            self._history.clear()
            self._total_slow = 0
            self._total_queries = 0


# ── Index advisor ─────────────────────────────────────────────────────────────


@dataclass
class IndexRecommendation:
    """A single index recommendation."""

    table: str
    recommendation_type: str  # "drop_unused" | "create_missing" | "vacuum"
    reason: str
    sql: str = ""
    priority: str = "medium"  # "high" | "medium" | "low"


class IndexAdvisor:
    """
    Inspects pg_stat_* views and produces actionable index recommendations.

    Only reads system catalog views — never modifies the schema.
    Only works with PostgreSQL; returns an empty list for other engines.
    """

    UNUSED_INDEX_SCAN_THRESHOLD = 10
    SEQ_SCAN_THRESHOLD = 500
    MIN_LIVE_ROWS = 5_000
    SEQ_SCAN_PCT_THRESHOLD = 60.0

    @classmethod
    def recommend(cls, engine: Any) -> list[IndexRecommendation]:
        """
        Return index recommendations for the connected PostgreSQL database.

        Returns an empty list for non-PostgreSQL engines.
        """
        if "postgresql" not in str(engine.url):
            logger.info("IndexAdvisor: only supports PostgreSQL — skipping")
            return []

        recommendations: list[IndexRecommendation] = []

        try:
            from sqlalchemy import text

            with engine.connect() as conn:
                # 1. Unused indexes — candidates to drop
                unused = conn.execute(
                    text("""
                    SELECT schemaname, relname AS tbl, indexrelname AS idx,
                           idx_scan,
                           pg_size_pretty(pg_relation_size(indexrelid)) AS sz
                    FROM pg_stat_user_indexes
                    WHERE idx_scan < :threshold
                      AND indexrelname NOT LIKE '%_pkey'
                      AND indexrelname NOT LIKE '%_unique%'
                    ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC
                    LIMIT 30
                """),
                    {"threshold": cls.UNUSED_INDEX_SCAN_THRESHOLD},
                ).fetchall()

                for row in unused:
                    recommendations.append(
                        IndexRecommendation(
                            table=row.tbl,
                            recommendation_type="drop_unused",
                            reason=(f"Index {row.idx!r} has only {row.idx_scan} scans (size: {row.sz})"),
                            sql=f"DROP INDEX CONCURRENTLY IF EXISTS {row.schemaname}.{row.idx};",
                            priority="low" if row.idx_scan > 0 else "medium",
                        )
                    )

                # 2. Tables with high sequential scan rates — missing indexes
                missing = conn.execute(
                    text("""
                    SELECT schemaname, relname AS tbl,
                           seq_scan, idx_scan, n_live_tup,
                           round(
                               seq_scan::numeric /
                               NULLIF(seq_scan + idx_scan, 0) * 100, 1
                           ) AS seq_pct
                    FROM pg_stat_user_tables
                    WHERE seq_scan > :seq_threshold
                      AND n_live_tup > :min_rows
                    ORDER BY seq_scan DESC
                    LIMIT 20
                """),
                    {
                        "seq_threshold": cls.SEQ_SCAN_THRESHOLD,
                        "min_rows": cls.MIN_LIVE_ROWS,
                    },
                ).fetchall()

                for row in missing:
                    priority = "high" if (row.seq_pct or 0) > cls.SEQ_SCAN_PCT_THRESHOLD else "medium"
                    recommendations.append(
                        IndexRecommendation(
                            table=row.tbl,
                            recommendation_type="create_missing",
                            reason=(
                                f"Table {row.tbl!r} has {row.seq_scan} sequential scans "
                                f"({row.seq_pct}% of all scans) on {row.n_live_tup:,} rows"
                            ),
                            sql=(
                                f"-- Identify WHERE-clause columns from slow query log, then:\n"
                                f"-- CREATE INDEX CONCURRENTLY ON "
                                f"{row.schemaname}.{row.tbl} (col1, col2);"
                            ),
                            priority=priority,
                        )
                    )

                # 3. Tables with high dead-tuple ratio — need VACUUM
                bloat = conn.execute(
                    text("""
                    SELECT relname AS tbl, n_dead_tup, n_live_tup,
                           round(
                               n_dead_tup::numeric /
                               NULLIF(n_live_tup + n_dead_tup, 0) * 100, 1
                           ) AS dead_pct
                    FROM pg_stat_user_tables
                    WHERE n_dead_tup > 10000
                      AND n_dead_tup::numeric /
                          NULLIF(n_live_tup + n_dead_tup, 0) > 0.1
                    ORDER BY n_dead_tup DESC
                    LIMIT 10
                """)
                ).fetchall()

                for row in bloat:
                    recommendations.append(
                        IndexRecommendation(
                            table=row.tbl,
                            recommendation_type="vacuum",
                            reason=(f"Table {row.tbl!r} has {row.dead_pct}% dead tuples ({row.n_dead_tup:,} rows)"),
                            sql=f"VACUUM ANALYZE {row.tbl};",
                            priority="high" if (row.dead_pct or 0) > 30 else "medium",  # noqa: PLR2004
                        )
                    )

        except Exception as exc:
            logger.warning("IndexAdvisor.recommend failed: %s", exc)

        priority_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(key=lambda r: priority_order.get(r.priority, 3))
        return recommendations

    @classmethod
    def print_report(cls, engine: Any) -> None:
        """Print a human-readable recommendation report to the logger."""
        recs = cls.recommend(engine)
        if not recs:
            logger.info("IndexAdvisor: no recommendations (PostgreSQL required)")
            return
        logger.info("IndexAdvisor: %d recommendations", len(recs))
        for i, rec in enumerate(recs, 1):
            logger.info(
                "[%d] [%s] %s — %s\n  SQL: %s",
                i,
                rec.priority.upper(),
                rec.recommendation_type,
                rec.reason,
                rec.sql,
            )


# ── Module-level singleton ────────────────────────────────────────────────────
# Attach to the application engine at startup:
#   from database.optimization import slow_query_logger
#   slow_query_logger.attach(engine)
slow_query_logger = SlowQueryLogger(
    threshold_ms=float(os.getenv("SLOW_QUERY_THRESHOLD_MS", "200")),
    explain=os.getenv("SLOW_QUERY_EXPLAIN", "false").lower() == "true",
)


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    _assert_dev_only()
    for name in _ALLOWED_QUERIES:
        try:
            analyze_query_performance(name)
        except Exception as exc:
            logger.warning("Skipped %r: %s", name, exc)

    db_url = os.getenv("DATABASE_URL", "")
    if db_url and "postgresql" in db_url:
        try:
            from sqlalchemy import create_engine as _ce

            IndexAdvisor.print_report(_ce(db_url))
        except Exception as exc:
            logger.warning("IndexAdvisor skipped: %s", exc)
