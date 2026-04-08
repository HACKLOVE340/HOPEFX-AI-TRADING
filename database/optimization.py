# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/optimization.py
========================
Local development tool for measuring query execution time.

SECURITY RULES (non-negotiable):
1. Only runs when APP_ENV=development. Raises RuntimeError in production.
2. Only accepts queries from a hardcoded allowlist. No user input, ever.
3. Never imported by the application — CLI use only.

Usage (local dev only):
    APP_ENV=development python -m database.optimization
"""

import logging
import os
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Hardcoded query allowlist — the ONLY queries this tool may run ────────────
# To add a query: add it here in code, commit, review. Never accept queries
# from function arguments, CLI args, env vars, or any external source.
_ALLOWED_QUERIES: dict[str, str] = {
    "table_sizes": """
        SELECT relname AS table, pg_size_pretty(pg_total_relation_size(relid)) AS size
        FROM pg_catalog.pg_statio_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 20;
    """,
    "slow_queries": """
        SELECT query, calls, total_exec_time, mean_exec_time, rows
        FROM pg_stat_statements
        ORDER BY mean_exec_time DESC
        LIMIT 10;
    """,
    "index_usage": """
        SELECT relname AS table, indexrelname AS index,
               idx_scan, idx_tup_read, idx_tup_fetch
        FROM pg_stat_user_indexes
        ORDER BY idx_scan ASC
        LIMIT 20;
    """,
}


def _assert_dev_only() -> None:
    """Block execution in any non-development environment."""
    env = os.getenv("APP_ENV", "development").lower()
    if env not in ("development", "dev"):
        raise RuntimeError(
            f"database/optimization.py is a dev-only tool and cannot run in APP_ENV={env!r}. "
            "Use pg_stat_statements or your DBA tooling in production."
        )


def analyze_query_performance(query_name: str) -> None:
    """
    Run a named query from the allowlist and log its execution time.

    Args:
        query_name: Key from _ALLOWED_QUERIES. Raises ValueError for unknown names.
    """
    _assert_dev_only()

    if query_name not in _ALLOWED_QUERIES:
        raise ValueError(f"Unknown query {query_name!r}. Allowed: {sorted(_ALLOWED_QUERIES)}")

    query = _ALLOWED_QUERIES[query_name]

    database_uri = os.getenv("DATABASE_URL")
    if not database_uri:
        raise RuntimeError("DATABASE_URL environment variable is not set.")

    # Import here — this module must never be imported at app startup
    from sqlalchemy import create_engine, text

    engine = create_engine(database_uri)
    start = time.time()
    with engine.connect() as conn:
        rows = conn.execute(text(query)).fetchall()
    elapsed = time.time() - start

    logger.info("Query %r returned %d rows in %.4fs", query_name, len(rows), elapsed)
    for row in rows:
        logger.info("  %s", row)


if __name__ == "__main__":
    _assert_dev_only()
    for name in _ALLOWED_QUERIES:
        try:
            analyze_query_performance(name)
        except Exception as exc:
            logger.warning("Skipped %r: %s", name, exc)
