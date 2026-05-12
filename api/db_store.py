# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/db_store.py
===============
Lightweight key-value persistence layer backed by the `configurations` table.

Used by journal, watchlist, and social feed to replace in-memory dicts with
DB-backed storage that survives restarts.

All operations degrade gracefully to in-memory fallback when the DB is
unavailable (dev mode, missing DB, etc.).

Session management
------------------
Each public function opens its own short-lived session via SessionLocal(),
performs the operation, and closes the session in a finally block.
The previous implementation called ctx.__enter__() on the context-manager
returned by mgr.session() but never called __exit__(), leaking a DB
connection on every call.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


@contextmanager
def _session_ctx() -> Generator:
    """Yield a SQLAlchemy Session and guarantee it is closed on exit.

    Yields None when the DB is unavailable so callers can guard with::

        with _session_ctx() as session:
            if session is None:
                return default_value
            ...
    """
    session = None
    try:
        from database.connection import SessionLocal  # type: ignore[import]

        session = SessionLocal()
        yield session
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("db_store: could not obtain DB session: %s", exc)
        yield None
    finally:
        if session is not None:
            import contextlib
            with contextlib.suppress(Exception):
                session.close()


def db_get(key: str) -> Any | None:
    """Retrieve a JSON-decoded value from the configurations table.

    Returns None on miss or error.
    """
    try:
        from database.models import Configuration

        with _session_ctx() as session:
            if session is None:
                return None
            record = session.query(Configuration).filter_by(config_key=key).first()
            if record and record.config_value:
                return json.loads(record.config_value)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("db_get failed: %s", type(exc).__name__)
    return None


def db_set(key: str, value: Any, changed_by: str = "system") -> bool:
    """Persist a JSON-serialisable value to the configurations table.

    Returns True on success, False on failure.
    """
    try:
        from database.models import Configuration

        with _session_ctx() as session:
            if session is None:
                return False

            serialised = json.dumps(value)
            existing = session.query(Configuration).filter_by(config_key=key).first()
            if existing:
                existing.config_value = serialised
                existing.changed_by = changed_by
            else:
                record = Configuration(
                    environment="production",
                    config_key=key,
                    config_value=serialised,
                    changed_by=changed_by,
                    change_reason="api_db_store",
                )
                session.add(record)
            session.commit()
            return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("db_set failed: %s", type(exc).__name__)
        return False


def db_delete(key: str) -> bool:
    """Delete a key from the configurations table."""
    try:
        from database.models import Configuration

        with _session_ctx() as session:
            if session is None:
                return False
            session.query(Configuration).filter_by(config_key=key).delete()
            session.commit()
            return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("db_delete failed: %s", type(exc).__name__)
        return False


def db_keys_prefix(prefix: str) -> list[str]:
    """Return all keys that start with the given prefix."""
    try:
        from database.models import Configuration

        with _session_ctx() as session:
            if session is None:
                return []
            records = (
                session.query(Configuration.config_key)
                .filter(Configuration.config_key.like(f"{prefix}%"))
                .all()
            )
            return [r[0] for r in records]
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("db_keys_prefix(%s) failed: %s", prefix, exc)
        return []
