# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_disaster_recovery.py
=======================================
Unit tests for utils/disaster_recovery.py.

Covers:
- SystemState dataclass — fields and checksum
- ContinuousBackup — snapshot creation, restore, cleanup
- FailoverManager — leader election, heartbeat, failover detection
"""

from __future__ import annotations

import gzip
import json
from datetime import timezone

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# SystemState
# ---------------------------------------------------------------------------


class TestSystemState:
    def test_fields_accessible(self):
        from utils.disaster_recovery import SystemState

        s = SystemState(
            timestamp="2025-01-01T00:00:00+00:00",
            event_store_position=42,
            strategy_states={"rsi": {"is_active": True}},
            open_positions=[],
            risk_metrics={"drawdown": 0.05},
            performance_cache={},
            checksum="abc123",
        )
        assert s.event_store_position == 42
        assert s.strategy_states["rsi"]["is_active"] is True
        assert s.checksum == "abc123"

    def test_dataclass_asdict(self):
        from dataclasses import asdict
        from utils.disaster_recovery import SystemState

        s = SystemState(
            timestamp="2025-01-01T00:00:00+00:00",
            event_store_position=0,
            strategy_states={},
            open_positions=[],
            risk_metrics={},
            performance_cache={},
            checksum="",
        )
        d = asdict(s)
        assert "timestamp" in d
        assert "event_store_position" in d
        assert "checksum" in d


# ---------------------------------------------------------------------------
# ContinuousBackup
# ---------------------------------------------------------------------------


class TestContinuousBackup:
    @pytest.fixture()
    def backup_dir(self, tmp_path):
        return tmp_path / "backups"

    def test_init_creates_backup_dir(self, backup_dir):
        from utils.disaster_recovery import ContinuousBackup

<<<<<<< HEAD
        ContinuousBackup(backup_path=str(backup_dir))
=======
        _cb = ContinuousBackup(backup_path=str(backup_dir))
>>>>>>> origin/main
        assert backup_dir.exists()

    @pytest.mark.asyncio
    async def test_create_snapshot_writes_file(self, backup_dir):
        from utils.disaster_recovery import ContinuousBackup

        cb = ContinuousBackup(backup_path=str(backup_dir))

        class FakeEventStore:
            _sequence = 100

        class FakeStrategy:
            is_active = True
            performance = {}

        class FakeOrchestra:
            strategies = {"rsi": FakeStrategy()}

        class FakeRiskEngine:
            current_risk = None

        state = await cb.create_snapshot(FakeEventStore(), FakeOrchestra(), FakeRiskEngine())
        snapshots = list(backup_dir.glob("snapshot_*.json.gz"))
        assert len(snapshots) == 1
        assert state.event_store_position == 100

    @pytest.mark.asyncio
    async def test_snapshot_checksum_is_sha256(self, backup_dir):
        from utils.disaster_recovery import ContinuousBackup

        cb = ContinuousBackup(backup_path=str(backup_dir))

        class FakeEventStore:
            _sequence = 0

        class FakeOrchestra:
            strategies = {}

        class FakeRiskEngine:
            current_risk = None

        state = await cb.create_snapshot(FakeEventStore(), FakeOrchestra(), FakeRiskEngine())
        assert len(state.checksum) == 64  # SHA-256 hex = 64 chars
        assert all(c in "0123456789abcdef" for c in state.checksum)

    @pytest.mark.asyncio
    async def test_restore_from_snapshot_roundtrip(self, backup_dir):
        from utils.disaster_recovery import ContinuousBackup

        cb = ContinuousBackup(backup_path=str(backup_dir))

        class FakeEventStore:
            _sequence = 77

        class FakeOrchestra:
            strategies = {}

        class FakeRiskEngine:
            current_risk = None

        state = await cb.create_snapshot(FakeEventStore(), FakeOrchestra(), FakeRiskEngine())
        snapshots = list(backup_dir.glob("snapshot_*.json.gz"))
        filename = snapshots[0].name

        restored = await cb.restore_from_snapshot(filename)
        assert restored.event_store_position == 77
        assert restored.checksum == state.checksum

    @pytest.mark.asyncio
    async def test_restore_raises_on_tampered_snapshot(self, backup_dir):
        from utils.disaster_recovery import ContinuousBackup

        cb = ContinuousBackup(backup_path=str(backup_dir))

        class FakeEventStore:
            _sequence = 0

        class FakeOrchestra:
            strategies = {}

        class FakeRiskEngine:
            current_risk = None

        await cb.create_snapshot(FakeEventStore(), FakeOrchestra(), FakeRiskEngine())
        snapshots = list(backup_dir.glob("snapshot_*.json.gz"))
        filepath = snapshots[0]

        # Tamper with the snapshot
        with open(filepath, "rb") as f:
            data = gzip.decompress(f.read())
        state_dict = json.loads(data)
        state_dict["event_store_position"] = 9999  # tamper
        tampered = gzip.compress(json.dumps(state_dict).encode())
        with open(filepath, "wb") as f:
            f.write(tampered)

        with pytest.raises(ValueError, match="checksum"):
            await cb.restore_from_snapshot(filepath.name)

    @pytest.mark.asyncio
    async def test_cleanup_keeps_last_100_snapshots(self, backup_dir):
        from utils.disaster_recovery import ContinuousBackup

        cb = ContinuousBackup(backup_path=str(backup_dir))

        # Create 105 fake snapshot files
        for i in range(105):
            fake = backup_dir / f"snapshot_2025-01-{i:03d}T00-00-00.json.gz"
            fake.write_bytes(gzip.compress(b"{}"))

        await cb._cleanup_old_snapshots()
        remaining = list(backup_dir.glob("snapshot_*.json.gz"))
        assert len(remaining) <= 100


# ---------------------------------------------------------------------------
# FailoverManager
# ---------------------------------------------------------------------------


class TestFailoverManager:
    def test_init_sets_node_id(self):
        from utils.disaster_recovery import FailoverManager

        fm = FailoverManager(node_id="node-1", peers=["node-2", "node-3"])
        assert fm.node_id == "node-1"
        assert fm.peers == ["node-2", "node-3"]
        assert fm.is_primary is False

    @pytest.mark.asyncio
    async def test_election_highest_node_id_wins(self):
        from utils.disaster_recovery import FailoverManager

        # node-3 is lexicographically highest
        fm = FailoverManager(node_id="node-3", peers=["node-1", "node-2"])
        await fm.start_election()
        assert fm.is_primary is True

    @pytest.mark.asyncio
    async def test_election_lower_node_id_loses(self):
        from utils.disaster_recovery import FailoverManager

        fm = FailoverManager(node_id="node-1", peers=["node-2", "node-3"])
        await fm.start_election()
        assert fm.is_primary is False

    @pytest.mark.asyncio
    async def test_election_single_node_wins(self):
        from utils.disaster_recovery import FailoverManager

        fm = FailoverManager(node_id="node-1", peers=[])
        await fm.start_election()
        assert fm.is_primary is True

    def test_heartbeat_port_constant(self):
        from utils.disaster_recovery import FailoverManager

        assert FailoverManager.HEARTBEAT_PORT == 8765

    def test_failover_timeout_default(self):
        from utils.disaster_recovery import FailoverManager

        fm = FailoverManager(node_id="node-1", peers=[])
        assert fm.failover_timeout == 15

    def test_heartbeat_interval_default(self):
        from utils.disaster_recovery import FailoverManager

        fm = FailoverManager(node_id="node-1", peers=[])
        assert fm.heartbeat_interval == 5

    def test_last_peer_heartbeat_initially_empty(self):
        from utils.disaster_recovery import FailoverManager

        fm = FailoverManager(node_id="node-1", peers=["node-2"])
        assert fm.last_peer_heartbeat == {}
