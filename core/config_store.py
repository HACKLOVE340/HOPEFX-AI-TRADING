# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/config_store.py
====================
Multi-pod-safe configuration store backed by Redis (primary) with DB fallback.

All pods read from the same Redis key on every request, so a change made on
Pod A is immediately visible to Pods B and C.  When Redis is unavailable the
store falls back to the ConfigStore DB table, which is also shared across pods.

Usage
-----
    from core.config_store import config_store

    # Read (always fresh — no in-process cache)
    settings = config_store.get("risk_settings", default={})

    # Write (publishes to Redis + persists to DB)
    config_store.set("risk_settings", {"max_risk_per_trade": 1.5}, changed_by="admin")

    # Delete
    config_store.delete("risk_settings")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "hopefx:config:"
_REDIS_PUBSUB_CHANNEL = "hopefx:config:changed"


class ConfigStore:
    """
    Shared configuration store: Redis primary, DB fallback.

    - get()  reads from Redis; falls back to DB on Redis miss/error.
    - set()  writes to Redis AND DB atomically (best-effort Redis).
    - delete() removes from both.

    No in-process TTL cache — every read hits Redis so all pods see the
    same value immediately after a write.
    """

    # ── Redis helpers ─────────────────────────────────────────────────────────

    def _redis(self):
        """
        Return a synchronous Redis client, or None if unavailable.

        Injects REDIS_PASSWORD when it is not already embedded in REDIS_URL,
        matching the same logic used by EventBus and MarketDataCache so all
        components authenticate consistently.
        """
        try:
            import redis as _redis

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            password = os.getenv("REDIS_PASSWORD", "") or None

            # Inject password into URL when not already embedded.
            if password and "@" not in url.split("://", 1)[-1]:
                scheme, rest = url.split("://", 1)
                url = f"{scheme}://:{password}@{rest}"

            return _redis.from_url(
                url,
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
        except Exception as exc:
            logger.debug("ConfigStore: Redis unavailable: %s", exc)
            return None

    def _redis_key(self, key: str) -> str:
        return f"{_REDIS_KEY_PREFIX}{key}"

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _db_session(self):
        """Return a SQLAlchemy session, or None if DB unavailable."""
        try:
            from core.app_state import app_state

            if app_state and app_state.db_session_factory:
                return app_state.db_session_factory()  # pylint: disable=not-callable
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        return None

    def _db_get(self, key: str) -> Any | None:
        session = self._db_session()
        if session is None:
            return None
        try:
            from database.models import ConfigStore as ConfigStoreModel

            record = session.query(ConfigStoreModel).filter(ConfigStoreModel.key == key).first()
            if record:
                return json.loads(record.value_json)
            return None
        except Exception as exc:
            logger.debug("ConfigStore._db_get(%s) failed: %s", key, exc)
            return None
        finally:
            session.close()

    def _db_set(self, key: str, value: Any, changed_by: str = "system") -> bool:
        session = self._db_session()
        if session is None:
            return False
        try:
            from database.models import ConfigStore as ConfigStoreModel

            serialised = json.dumps(value)
            record = session.query(ConfigStoreModel).filter(ConfigStoreModel.key == key).first()
            if record:
                record.value_json = serialised
                record.changed_by = changed_by
                record.updated_at = datetime.now(UTC)
            else:
                record = ConfigStoreModel(
                    key=key,
                    value_json=serialised,
                    changed_by=changed_by,
                )
                session.add(record)
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            logger.warning("ConfigStore._db_set(%s) failed: %s", key, exc)
            return False
        finally:
            session.close()

    def _db_delete(self, key: str) -> bool:
        session = self._db_session()
        if session is None:
            return False
        try:
            from database.models import ConfigStore as ConfigStoreModel

            session.query(ConfigStoreModel).filter(ConfigStoreModel.key == key).delete()
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            logger.warning("ConfigStore._db_delete(%s) failed: %s", key, exc)
            return False
        finally:
            session.close()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any | None = None) -> Any:
        """
        Read a config value.

        Tries Redis first (O(1), shared across pods).
        Falls back to DB on Redis miss or error.
        Returns *default* if neither source has the key.
        """
        # Try Redis
        r = self._redis()
        if r is not None:
            try:
                raw = r.get(self._redis_key(key))
                if raw is not None:
                    return json.loads(raw)
            except Exception as exc:
                logger.debug("ConfigStore.get Redis read failed: %s", exc)

        # Fall back to DB
        value = self._db_get(key)
        if value is not None:
            # Warm Redis cache from DB
            if r is not None:
                try:
                    r.set(self._redis_key(key), json.dumps(value))
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
            return value

        return default

    def set(self, key: str, value: Any, changed_by: str = "system") -> bool:
        """
        Write a config value to Redis and DB.

        Redis write is best-effort — DB write is the source of truth.
        Publishes a change notification to hopefx:config:changed so other
        pods can invalidate local caches if they maintain any.

        Returns True if at least the DB write succeeded.
        """
        # Write to DB first (source of truth)
        db_ok = self._db_set(key, value, changed_by=changed_by)

        # Write to Redis (best-effort)
        r = self._redis()
        if r is not None:
            try:
                r.set(self._redis_key(key), json.dumps(value))
                # Notify other pods
                r.publish(
                    _REDIS_PUBSUB_CHANNEL,
                    json.dumps({"key": key, "changed_by": changed_by}),
                )
            except Exception as exc:
                logger.warning("ConfigStore.set Redis write failed (DB write succeeded): %s", exc)

        if db_ok:
            logger.info("ConfigStore.set: key=%s changed_by=%s", key, changed_by)
        else:
            logger.error("ConfigStore.set: DB write failed for key=%s", key)

        return db_ok

    def delete(self, key: str) -> bool:
        """Remove a config value from Redis and DB."""
        r = self._redis()
        if r is not None:
            try:
                r.delete(self._redis_key(key))
                r.publish(
                    _REDIS_PUBSUB_CHANNEL,
                    json.dumps({"key": key, "deleted": True}),
                )
            except Exception as exc:
                logger.debug("ConfigStore.delete Redis failed: %s", exc)

        return self._db_delete(key)


# Module-level singleton
config_store = ConfigStore()
