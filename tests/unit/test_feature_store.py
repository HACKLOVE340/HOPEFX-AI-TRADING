# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for data_layer/feature_store.py

Coverage:
- FeatureDefinition fields + defaults
- FeatureRegistry: register, register_many, get, list_features, schema
- OnlineStore: write/read (in-memory fallback, no Redis required)
- OnlineStore: read with feature_names filter
- OfflineStore: write, get_history (full + date-filtered)
- OfflineStore: as_dataframe (all columns + subset + empty)
- FeatureStore: write propagates to online + offline
- FeatureStore: get_online, get_training_df
- FeatureStore: health() reports correct counts
- Module-level feature_store singleton exists
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data_layer.feature_store import (
    FeatureDefinition,
    FeatureRegistry,
    FeatureSnapshot,
    FeatureStore,
    OfflineStore,
    OnlineStore,
    feature_store,
)

UTC = timezone.utc

# ── helpers ───────────────────────────────────────────────────────────────────

def _ts(offset_days: float = 0) -> datetime:
    return datetime.now(UTC) - timedelta(days=offset_days)


def _make_def(name: str = "dxy", dtype: str = "float") -> FeatureDefinition:
    return FeatureDefinition(
        name=name,
        dtype=dtype,
        description=f"{name} test feature",
        source="tests",
        tags=["macro"],
    )


# ── FeatureDefinition ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFeatureDefinition:
    def test_required_fields(self):
        defn = _make_def("vix", "float")
        assert defn.name == "vix"
        assert defn.dtype == "float"
        assert defn.source == "tests"

    def test_version_default_is_1(self):
        defn = _make_def()
        assert defn.version == 1

    def test_tags_default_empty(self):
        defn = FeatureDefinition(
            name="x", dtype="float", description="x", source="tests"
        )
        assert defn.tags == []

    def test_created_at_is_iso_string(self):
        defn = _make_def()
        # Should be a valid ISO datetime string
        dt = datetime.fromisoformat(defn.created_at)
        assert dt.year >= 2025


# ── FeatureRegistry ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFeatureRegistry:
    def test_register_and_get(self):
        reg = FeatureRegistry()
        reg.register(_make_def("dxy"))
        assert reg.get("dxy") is not None
        assert reg.get("dxy").dtype == "float"

    def test_get_missing_returns_none(self):
        reg = FeatureRegistry()
        assert reg.get("nonexistent") is None

    def test_register_many(self):
        reg = FeatureRegistry()
        defs = [_make_def("a"), _make_def("b"), _make_def("c")]
        reg.register_many(defs)
        assert len(reg.list_features()) == 3

    def test_list_features_no_filter(self):
        reg = FeatureRegistry()
        reg.register(_make_def("x"))
        reg.register(_make_def("y"))
        features = reg.list_features()
        assert "x" in features
        assert "y" in features

    def test_list_features_with_tag_filter(self):
        reg = FeatureRegistry()
        d_macro = FeatureDefinition("dxy", "float", "DXY", "fred", tags=["macro"])
        d_tech = FeatureDefinition("rsi", "float", "RSI", "ta", tags=["technical"])
        reg.register(d_macro)
        reg.register(d_tech)
        macro_feats = reg.list_features(tag="macro")
        assert "dxy" in macro_feats
        assert "rsi" not in macro_feats

    def test_schema_returns_name_dtype_dict(self):
        reg = FeatureRegistry()
        reg.register(_make_def("dxy", "float"))
        reg.register(_make_def("trend", "int"))
        schema = reg.schema()
        assert schema["dxy"] == "float"
        assert schema["trend"] == "int"

    def test_register_overwrites_existing(self):
        reg = FeatureRegistry()
        reg.register(_make_def("x"))
        updated = FeatureDefinition("x", "int", "updated", "tests")
        reg.register(updated)
        assert reg.get("x").dtype == "int"


# ── OnlineStore (in-memory fallback) ─────────────────────────────────────────

@pytest.mark.unit
class TestOnlineStore:
    def test_write_and_read_all_features(self):
        store = OnlineStore()
        store.write("XAUUSD", {"dxy": 104.2, "vix": 18.5})
        result = store.read("XAUUSD")
        assert result["dxy"] == 104.2
        assert result["vix"] == 18.5

    def test_read_missing_entity_returns_empty(self):
        store = OnlineStore()
        result = store.read("MISSING")
        assert result == {}

    def test_read_with_feature_names_filter(self):
        store = OnlineStore()
        store.write("XAUUSD", {"dxy": 104.2, "vix": 18.5, "gold_vol": 0.12})
        result = store.read("XAUUSD", feature_names=["dxy"])
        assert "dxy" in result
        assert "vix" not in result

    def test_write_overwrites_previous_values(self):
        store = OnlineStore()
        store.write("XAUUSD", {"dxy": 100.0})
        store.write("XAUUSD", {"dxy": 105.0})
        result = store.read("XAUUSD")
        assert result["dxy"] == 105.0

    def test_multiple_entities_independent(self):
        store = OnlineStore()
        store.write("XAUUSD", {"dxy": 104.0})
        store.write("EURUSD", {"dxy": 100.0})
        assert store.read("XAUUSD")["dxy"] == 104.0
        assert store.read("EURUSD")["dxy"] == 100.0

    def test_read_filter_for_nonexistent_features(self):
        store = OnlineStore()
        store.write("XAUUSD", {"dxy": 104.2})
        # Requesting a feature that doesn't exist should not raise
        result = store.read("XAUUSD", feature_names=["nonexistent"])
        assert isinstance(result, dict)


# ── OfflineStore ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOfflineStore:
    def test_write_and_get_history(self):
        store = OfflineStore()
        snap = FeatureSnapshot(
            entity_id="XAUUSD",
            timestamp=_ts(),
            features={"dxy": 104.2},
        )
        store.write(snap)
        history = store.get_history("XAUUSD")
        assert len(history) == 1
        assert history[0].features["dxy"] == 104.2

    def test_get_history_empty_for_new_entity(self):
        store = OfflineStore()
        assert store.get_history("UNKNOWN") == []

    def test_get_history_date_filter_start(self):
        store = OfflineStore()
        old_snap = FeatureSnapshot("X", _ts(10), {"v": 1})
        new_snap = FeatureSnapshot("X", _ts(0),  {"v": 2})
        store.write(old_snap)
        store.write(new_snap)
        cutoff = _ts(5)
        result = store.get_history("X", start=cutoff)
        assert len(result) == 1
        assert result[0].features["v"] == 2

    def test_get_history_date_filter_end(self):
        store = OfflineStore()
        old_snap = FeatureSnapshot("X", _ts(10), {"v": 1})
        new_snap = FeatureSnapshot("X", _ts(0),  {"v": 2})
        store.write(old_snap)
        store.write(new_snap)
        cutoff = _ts(5)
        result = store.get_history("X", end=cutoff)
        assert len(result) == 1
        assert result[0].features["v"] == 1

    def test_max_history_trimming(self):
        store = OfflineStore(max_history=3)
        for i in range(5):
            store.write(FeatureSnapshot("X", _ts(5 - i), {"i": i}))
        history = store.get_history("X")
        assert len(history) == 3

    def test_as_dataframe_returns_dataframe(self):
        pytest.importorskip("pandas")
        store = OfflineStore()
        for i in range(5):
            store.write(FeatureSnapshot("XAUUSD", _ts(5 - i), {"dxy": float(i), "vix": float(i * 2)}))
        df = store.as_dataframe("XAUUSD")
        assert not df.empty
        assert "dxy" in df.columns
        assert "vix" in df.columns

    def test_as_dataframe_empty_for_new_entity(self):
        pytest.importorskip("pandas")
        store = OfflineStore()
        df = store.as_dataframe("UNKNOWN")
        assert df.empty

    def test_as_dataframe_feature_subset(self):
        pytest.importorskip("pandas")
        store = OfflineStore()
        for i in range(3):
            store.write(FeatureSnapshot("XAUUSD", _ts(3 - i), {"dxy": float(i), "vix": float(i)}))
        df = store.as_dataframe("XAUUSD", feature_names=["dxy"])
        assert "dxy" in df.columns
        assert "vix" not in df.columns


# ── FeatureStore (composite) ──────────────────────────────────────────────────

@pytest.mark.unit
class TestFeatureStore:
    def test_write_propagates_to_online(self):
        fs = FeatureStore()
        fs.write("XAUUSD", {"dxy": 104.2})
        result = fs.get_online("XAUUSD")
        assert result["dxy"] == 104.2

    def test_write_propagates_to_offline(self):
        fs = FeatureStore()
        ts = _ts()
        fs.write("XAUUSD", {"dxy": 104.2}, timestamp=ts)
        df = fs.get_training_df("XAUUSD")
        assert not df.empty

    def test_register_and_schema(self):
        fs = FeatureStore()
        fs.register(_make_def("dxy", "float"))
        assert "dxy" in fs.registry.list_features()

    def test_health_reports_counts(self):
        fs = FeatureStore()
        fs.register(_make_def("dxy"))
        fs.write("XAUUSD", {"dxy": 104.2})
        health = fs.health()
        assert health["registered_features"] >= 1
        assert health["offline_entities"] >= 1
        assert health["offline_total_snapshots"] >= 1
        assert "redis_available" in health

    def test_get_online_feature_filter(self):
        fs = FeatureStore()
        fs.write("XAUUSD", {"dxy": 104.2, "vix": 18.5})
        result = fs.get_online("XAUUSD", feature_names=["dxy"])
        assert "dxy" in result
        assert "vix" not in result

    def test_get_training_df_date_range(self):
        pytest.importorskip("pandas")
        fs = FeatureStore()
        fs.write("XAUUSD", {"dxy": 1.0}, timestamp=_ts(10))
        fs.write("XAUUSD", {"dxy": 2.0}, timestamp=_ts(0))
        df = fs.get_training_df("XAUUSD", start=_ts(5))
        # Only 1 snapshot is in range
        assert len(df) == 1


# ── module-level singleton ────────────────────────────────────────────────────

@pytest.mark.unit
class TestFeatureStoreSingleton:
    def test_singleton_exists(self):
        assert isinstance(feature_store, FeatureStore)

    def test_singleton_health_callable(self):
        health = feature_store.health()
        assert "registered_features" in health
        assert "redis_available" in health
