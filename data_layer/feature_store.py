# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feature_store.py
============================
Feature store — online/offline feature serving layer.

Provides a unified interface for:
  - Online serving: latest feature values for live inference
  - Offline retrieval: historical feature snapshots for training
  - Feature registration: define features with metadata and lineage
  - Point-in-time correctness: no future data leakage

Architecture:
  FeatureStore
  ├── FeatureRegistry: metadata, schema, lineage
  ├── OnlineStore: Redis-backed latest values
  └── OfflineStore: in-memory + optional persistence for training
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_FEATURE_TTL_S = int(os.getenv("FEATURE_STORE_TTL", "86400"))  # 24h default
_FEATURE_STORE_PREFIX = "hopefx:features:"


@dataclass
class FeatureDefinition:
    """Metadata for a registered feature."""
    name: str
    dtype: str
    """'float', 'int', 'bool', 'str'"""
    description: str
    source: str
    """Origin module/feed (e.g. 'ml.macro_features', 'data_layer.feeds.macro.fred')."""
    tags: list[str] = field(default_factory=list)
    version: int = 1
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass
class FeatureSnapshot:
    """A point-in-time snapshot of feature values."""
    entity_id: str
    """e.g. 'XAU_USD'"""
    timestamp: datetime
    features: dict[str, Any]
    """Feature name → value."""


class FeatureRegistry:
    """Stores feature metadata and schema."""

    def __init__(self) -> None:
        self._features: dict[str, FeatureDefinition] = {}

    def register(self, definition: FeatureDefinition) -> None:
        """Register or update a feature definition."""
        self._features[definition.name] = definition
        logger.debug("FeatureStore: registered feature '%s'", definition.name)

    def register_many(self, definitions: list[FeatureDefinition]) -> None:
        """Bulk register features."""
        for d in definitions:
            self.register(d)

    def get(self, name: str) -> FeatureDefinition | None:
        return self._features.get(name)

    def list_features(self, tag: str | None = None) -> list[str]:
        if tag is None:
            return list(self._features.keys())
        return [k for k, v in self._features.items() if tag in v.tags]

    def schema(self) -> dict[str, str]:
        """Return {name: dtype} for all registered features."""
        return {k: v.dtype for k, v in self._features.items()}


class OnlineStore:
    """
    Redis-backed online feature store for real-time serving.

    Falls back to in-memory dict if Redis is unavailable.
    """

    def __init__(self, redis_url: str = _REDIS_URL, ttl: int = _FEATURE_TTL_S) -> None:
        self._ttl = ttl
        self._client = None
        self._memory: dict[str, dict[str, Any]] = {}
        try:
            import redis  # noqa: PLC0415
            self._client = redis.from_url(redis_url, socket_timeout=2.0)
            self._client.ping()
            logger.info("FeatureStore: connected to Redis at %s", redis_url)
        except Exception as exc:
            logger.warning(
                "FeatureStore: Redis unavailable (%s), using in-memory fallback", exc
            )
            self._client = None

    def _entity_key(self, entity_id: str) -> str:
        """Return the Redis hash key for all features of *entity_id*."""
        return f"{_FEATURE_STORE_PREFIX}{entity_id}"

    def write(self, entity_id: str, features: dict[str, Any]) -> None:
        """Write feature values for entity_id."""
        if self._client is not None:
            try:
                hkey = self._entity_key(entity_id)
                mapping = {name: json.dumps(val) for name, val in features.items()}
                self._client.hset(hkey, mapping=mapping)
                self._client.expire(hkey, self._ttl)
            except Exception as exc:
                logger.warning("OnlineStore.write error: %s", exc)
                self._memory.setdefault(entity_id, {}).update(features)
        else:
            self._memory.setdefault(entity_id, {}).update(features)

    def read(self, entity_id: str, feature_names: list[str] | None = None) -> dict[str, Any]:
        """Read latest feature values for entity_id."""
        if self._client is not None:
            try:
                hkey = self._entity_key(entity_id)
                if feature_names:
                    raw_vals = self._client.hmget(hkey, feature_names)
                    result: dict[str, Any] = {}
                    for name, val in zip(feature_names, raw_vals):
                        if val is None:
                            continue
                        try:
                            result[name] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    return result
                else:
                    raw = self._client.hgetall(hkey)
                    if not raw:
                        return {}
                    result = {}
                    for key, val in raw.items():
                        if val is None:
                            continue
                        feat_name = key.decode() if isinstance(key, bytes) else key
                        try:
                            result[feat_name] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    return result
            except Exception as exc:
                logger.warning("OnlineStore.read error: %s", exc)
                return dict(self._memory.get(entity_id, {}))
        return dict(self._memory.get(entity_id, {}))


class OfflineStore:
    """
    In-memory offline feature store for training data retrieval.

    Maintains a history of feature snapshots per entity for ML training.
    Supports point-in-time retrieval to prevent look-ahead bias.
    """

    def __init__(self, max_history: int = 10_000) -> None:
        self._max_history = max_history
        self._history: dict[str, list[FeatureSnapshot]] = {}

    def write(self, snapshot: FeatureSnapshot) -> None:
        """Append a feature snapshot to history."""
        entity = snapshot.entity_id
        if entity not in self._history:
            self._history[entity] = []
        history = self._history[entity]
        history.append(snapshot)
        if len(history) > self._max_history:
            history.pop(0)

    def get_history(
        self,
        entity_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[FeatureSnapshot]:
        """Return snapshots for entity within [start, end]."""
        snaps = self._history.get(entity_id, [])
        if start is not None:
            snaps = [s for s in snaps if s.timestamp >= start]
        if end is not None:
            snaps = [s for s in snaps if s.timestamp <= end]
        return snaps

    def as_dataframe(
        self,
        entity_id: str,
        feature_names: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ):  # -> pd.DataFrame
        """Return feature history as DataFrame (training-ready)."""
        import pandas as pd  # noqa: PLC0415
        snaps = self.get_history(entity_id, start, end)
        if not snaps:
            return pd.DataFrame()
        records = [
            {"timestamp": s.timestamp, **s.features}
            for s in snaps
        ]
        df = pd.DataFrame(records).set_index("timestamp").sort_index()
        if feature_names:
            cols = [c for c in feature_names if c in df.columns]
            df = df[cols]
        return df


class FeatureStore:
    """
    Unified feature store with online and offline serving.

    Usage:
        from data_layer.feature_store import feature_store

        # Register features
        feature_store.register(FeatureDefinition('dxy', 'float', 'DXY', 'fred'))

        # Write features (online + offline)
        feature_store.write('XAU_USD', {'dxy': 104.2, 'vix': 18.5}, timestamp=now)

        # Serve online (live inference)
        features = feature_store.get_online('XAU_USD')

        # Retrieve offline (training)
        df = feature_store.get_training_df('XAU_USD', feature_names=['dxy', 'vix'])
    """

    def __init__(self) -> None:
        self.registry = FeatureRegistry()
        self.online = OnlineStore()
        self.offline = OfflineStore()

    def register(self, definition: FeatureDefinition) -> None:
        self.registry.register(definition)

    def write(
        self,
        entity_id: str,
        features: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        """Write features to both online and offline stores."""
        ts = timestamp or datetime.now(UTC)
        self.online.write(entity_id, features)
        self.offline.write(FeatureSnapshot(
            entity_id=entity_id,
            timestamp=ts,
            features=features,
        ))

    def get_online(
        self,
        entity_id: str,
        feature_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve latest feature values for live inference."""
        return self.online.read(entity_id, feature_names)

    def get_training_df(
        self,
        entity_id: str,
        feature_names: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ):  # -> pd.DataFrame
        """Retrieve historical features as DataFrame for training."""
        return self.offline.as_dataframe(entity_id, feature_names, start, end)

    def health(self) -> dict[str, Any]:
        """Return health status of feature store."""
        return {
            "registered_features": len(self.registry.list_features()),
            "redis_available": self.online._client is not None,
            "offline_entities": len(self.offline._history),
            "offline_total_snapshots": sum(
                len(v) for v in self.offline._history.values()
            ),
        }


# Module-level singleton
feature_store = FeatureStore()
