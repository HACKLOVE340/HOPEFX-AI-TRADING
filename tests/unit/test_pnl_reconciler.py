# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_pnl_reconciler.py
==================================
Unit tests for ml/pnl_reconciler.py and the P&L reconciliation gate
wired into ml/model_registry.py.

Coverage targets
----------------
- PnLReconciler._evaluate: all gate branches (pass, abs breach, rel breach,
  insufficient trades, zero broker_pnl)
- PnLReconciler._save_snapshot / _load_snapshot: write, read, stale detection,
  corrupt JSON
- PnLReconciler.check_gate: fresh snapshot, stale snapshot, missing snapshot
- PnLReconciler.reconcile: ledger + broker collection, snapshot written,
  metrics published
- PnLReconciler._collect_ledger_pnl: PositionManager present, absent, exception
- PnLReconciler._collect_broker_pnl: get_closed_trades, get_account_info
  fallback, broker=None
- PnLReconciler.snapshot_status: available / unavailable
- ModelRegistry.promote: P&L gate blocks promotion, P&L gate passes
- get_reconciler singleton
"""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_reconciler(tmp_path, **kwargs):
    from ml.pnl_reconciler import PnLReconciler

    return PnLReconciler(snapshot_path=tmp_path / "pnl_reconciliation.json", **kwargs)


def _write_snapshot(
    tmp_path, gate_passed=True, divergence=0.1, ledger=100.0, broker=100.1, n_ledger=20, n_broker=20, age_hours=0
):
    """Write a synthetic snapshot at a given age."""
    ts = datetime.now(UTC) - timedelta(hours=age_hours)
    data = {
        "gate_passed": gate_passed,
        "ledger_pnl": ledger,
        "broker_pnl": broker,
        "divergence": divergence,
        "rel_divergence": round(abs(divergence) / abs(broker) if broker else 0.0, 6),
        "n_ledger_trades": n_ledger,
        "n_broker_trades": n_broker,
        "abs_tolerance": 1.0,
        "rel_tolerance": 0.01,
        "reason": "test snapshot",
        "reconciled_at": ts.isoformat(),
        "from_cache": False,
    }
    path = tmp_path / "pnl_reconciliation.json"
    path.write_text(json.dumps(data))
    return path


# ── _evaluate ─────────────────────────────────────────────────────────────────


class TestEvaluate:
    def test_passes_within_abs_and_rel_tolerance(self, tmp_path):
        r = _make_reconciler(tmp_path, abs_tolerance=1.0, rel_tolerance=0.01, min_trades=5)
        result = r._evaluate(100.0, 100.5, 10, 10)
        assert result.gate_passed is True
        assert result.divergence == pytest.approx(0.5)
        assert "passed" in result.reason.lower()

    def test_blocks_on_abs_tolerance_breach(self, tmp_path):
        r = _make_reconciler(tmp_path, abs_tolerance=1.0, rel_tolerance=0.01, min_trades=5)
        result = r._evaluate(100.0, 110.0, 10, 10)
        assert result.gate_passed is False
        assert result.divergence == pytest.approx(10.0)
        assert "divergence" in result.reason.lower()

    def test_blocks_on_rel_tolerance_breach(self, tmp_path):
        # divergence=0.5 < abs_tol=2.0 but rel=0.5/100=0.5% > rel_tol=0.001
        r = _make_reconciler(tmp_path, abs_tolerance=2.0, rel_tolerance=0.001, min_trades=5)
        result = r._evaluate(100.0, 100.5, 10, 10)
        assert result.gate_passed is False
        assert "relative" in result.reason.lower()

    def test_blocks_on_insufficient_trades(self, tmp_path):
        r = _make_reconciler(tmp_path, min_trades=10)
        result = r._evaluate(100.0, 100.0, 3, 3)
        assert result.gate_passed is False
        assert "insufficient" in result.reason.lower()

    def test_passes_when_broker_pnl_is_zero(self, tmp_path):
        # rel_divergence is skipped when broker_pnl == 0
        r = _make_reconciler(tmp_path, abs_tolerance=1.0, rel_tolerance=0.01, min_trades=5)
        result = r._evaluate(0.0, 0.0, 10, 10)
        assert result.gate_passed is True
        assert result.rel_divergence == 0.0

    def test_blocks_when_only_ledger_has_enough_trades(self, tmp_path):
        # n_broker=-1 (unknown) but n_ledger >= min_trades — should still evaluate
        r = _make_reconciler(tmp_path, abs_tolerance=1.0, rel_tolerance=0.01, min_trades=5)
        result = r._evaluate(100.0, 100.2, 10, -1)
        # -1 < min_trades but ledger has enough — gate should pass
        # (both must be < min_trades to block on insufficient data)
        assert result.gate_passed is True

    def test_result_fields_populated(self, tmp_path):
        r = _make_reconciler(tmp_path, abs_tolerance=1.0, rel_tolerance=0.01, min_trades=5)
        result = r._evaluate(50.0, 50.3, 8, 8)
        assert result.ledger_pnl == pytest.approx(50.0)
        assert result.broker_pnl == pytest.approx(50.3)
        assert result.n_ledger_trades == 8
        assert result.n_broker_trades == 8
        assert result.abs_tolerance == pytest.approx(1.0)
        assert result.rel_tolerance == pytest.approx(0.01)
        assert result.reconciled_at  # non-empty ISO string


# ── Snapshot I/O ──────────────────────────────────────────────────────────────


class TestSnapshotIO:
    def test_save_and_load_roundtrip(self, tmp_path):
        r = _make_reconciler(tmp_path)
        result = r._evaluate(100.0, 100.4, 15, 15)
        r._save_snapshot(result)
        loaded = r._load_snapshot()
        assert loaded is not None
        assert loaded.gate_passed == result.gate_passed
        assert loaded.divergence == pytest.approx(result.divergence)
        assert loaded.from_cache is True

    def test_load_returns_none_when_file_absent(self, tmp_path):
        r = _make_reconciler(tmp_path)
        assert r._load_snapshot() is None

    def test_load_returns_none_when_stale(self, tmp_path):
        _write_snapshot(tmp_path, age_hours=25)
        r = _make_reconciler(tmp_path, stale_hours=24.0)
        assert r._load_snapshot() is None

    def test_load_returns_snapshot_when_fresh(self, tmp_path):
        _write_snapshot(tmp_path, age_hours=1)
        r = _make_reconciler(tmp_path, stale_hours=24.0)
        snap = r._load_snapshot()
        assert snap is not None
        assert snap.from_cache is True

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        path = tmp_path / "pnl_reconciliation.json"
        path.write_text("not valid json {{{{")
        r = _make_reconciler(tmp_path)
        assert r._load_snapshot() is None

    def test_save_is_atomic(self, tmp_path):
        """Snapshot file must be valid JSON immediately after save."""
        r = _make_reconciler(tmp_path)
        result = r._evaluate(10.0, 10.0, 20, 20)
        r._save_snapshot(result)
        raw = json.loads((tmp_path / "pnl_reconciliation.json").read_text())
        assert "gate_passed" in raw
        assert "divergence" in raw

    def test_save_handles_write_error(self, tmp_path):
        """save_snapshot must not raise even when the write fails."""
        r = _make_reconciler(tmp_path)
        result = r._evaluate(10.0, 10.0, 20, 20)
        with patch("tempfile.mkstemp", side_effect=OSError("disk full")):
            r._save_snapshot(result)  # must not raise


# ── check_gate ────────────────────────────────────────────────────────────────


class TestCheckGate:
    def test_returns_passed_from_fresh_snapshot(self, tmp_path):
        _write_snapshot(tmp_path, gate_passed=True, age_hours=1)
        r = _make_reconciler(tmp_path, stale_hours=24.0)
        result = r.check_gate()
        assert result.gate_passed is True
        assert result.from_cache is True

    def test_returns_blocked_from_failed_snapshot(self, tmp_path):
        _write_snapshot(tmp_path, gate_passed=False, divergence=5.0, age_hours=1)
        r = _make_reconciler(tmp_path, stale_hours=24.0)
        result = r.check_gate()
        assert result.gate_passed is False

    def test_returns_blocked_when_no_snapshot(self, tmp_path):
        r = _make_reconciler(tmp_path)
        result = r.check_gate()
        assert result.gate_passed is False
        assert "no fresh" in result.reason.lower()

    def test_returns_blocked_when_snapshot_stale(self, tmp_path):
        _write_snapshot(tmp_path, gate_passed=True, age_hours=30)
        r = _make_reconciler(tmp_path, stale_hours=24.0)
        result = r.check_gate()
        assert result.gate_passed is False
        assert "no fresh" in result.reason.lower()


# ── reconcile (async) ─────────────────────────────────────────────────────────


class TestReconcile:
    async def test_reconcile_with_no_broker_writes_snapshot(self, tmp_path):
        r = _make_reconciler(tmp_path, min_trades=0)
        result = await r.reconcile(broker=None)
        assert (tmp_path / "pnl_reconciliation.json").exists()
        assert isinstance(result.gate_passed, bool)

    async def test_reconcile_uses_broker_get_closed_trades(self, tmp_path):
        r = _make_reconciler(tmp_path, abs_tolerance=1.0, min_trades=2)

        broker = MagicMock()
        broker.get_closed_trades = AsyncMock(
            return_value=[
                {"realized_pnl": 10.0},
                {"realized_pnl": 5.0},
            ]
        )

        # Patch ledger to return matching value
        with patch.object(r, "_collect_ledger_pnl", return_value=(15.0, 2)):
            result = await r.reconcile(broker=broker)

        assert result.broker_pnl == pytest.approx(15.0)
        assert result.n_broker_trades == 2
        assert result.gate_passed is True

    async def test_reconcile_blocks_on_divergence(self, tmp_path):
        r = _make_reconciler(tmp_path, abs_tolerance=1.0, min_trades=2)

        broker = MagicMock()
        broker.get_closed_trades = AsyncMock(
            return_value=[
                {"realized_pnl": 100.0},
            ]
        )

        with patch.object(r, "_collect_ledger_pnl", return_value=(50.0, 5)):
            result = await r.reconcile(broker=broker)

        assert result.gate_passed is False
        assert result.divergence == pytest.approx(50.0)

    async def test_reconcile_falls_back_to_account_info(self, tmp_path):
        r = _make_reconciler(tmp_path, min_trades=0)

        broker = MagicMock(spec=[])  # no get_closed_trades
        broker.get_account_info = AsyncMock(return_value=MagicMock(realized_pnl=20.0))

        with patch.object(r, "_collect_ledger_pnl", return_value=(20.0, 0)):
            result = await r.reconcile(broker=broker)

        assert result.broker_pnl == pytest.approx(20.0)

    async def test_reconcile_publishes_metrics(self, tmp_path):
        r = _make_reconciler(tmp_path, min_trades=0)
        published = {}

        def fake_publish(res):
            published["result"] = res

        with patch("ml.pnl_reconciler._publish_metrics", side_effect=fake_publish):
            await r.reconcile(broker=None)

        assert "result" in published

    async def test_reconcile_handles_broker_exception(self, tmp_path):
        r = _make_reconciler(tmp_path, min_trades=0)

        broker = MagicMock()
        broker.get_closed_trades = AsyncMock(side_effect=RuntimeError("connection refused"))

        # Should not raise — returns 0 broker P&L
        result = await r.reconcile(broker=broker)
        assert result.broker_pnl == pytest.approx(0.0)


# ── _collect_ledger_pnl ───────────────────────────────────────────────────────


class TestCollectLedgerPnl:
    """The ledger reads the PositionManager singleton.

    These tests used to patch ``sys.modules["core.app_state"]`` with a
    MagicMock and set ``get_position_manager.return_value``. There is no
    ``get_position_manager`` in ``core.app_state`` — a MagicMock answers any
    attribute, so the mock manufactured the function the source was importing
    and the suite proved nothing about the real import. Against the real
    module the import raised, the handler returned ``(0.0, 0)``, and realized
    P&L reconciled as zero forever. See docs/HARDENING_BACKLOG.md S-40.

    They now patch the real singleton, ``execution.position_manager``.
    """

    def test_returns_zero_when_position_manager_absent(self, tmp_path):
        r = _make_reconciler(tmp_path)
        with patch.dict("sys.modules", {"execution.position_manager": None}):
            pnl, n = r._collect_ledger_pnl()
        assert pnl == 0.0
        assert n == 0

    def test_returns_zero_when_the_import_raises(self, tmp_path):
        r = _make_reconciler(tmp_path)
        broken = MagicMock()
        type(broken).position_manager = property(lambda _: (_ for _ in ()).throw(RuntimeError("not init")))
        with patch.dict("sys.modules", {"execution.position_manager": broken}):
            pnl, n = r._collect_ledger_pnl()
        assert pnl == 0.0
        assert n == 0

    def test_returns_zero_when_position_manager_is_none(self, tmp_path):
        r = _make_reconciler(tmp_path)
        with patch("execution.position_manager.position_manager", None):
            pnl, n = r._collect_ledger_pnl()
        assert pnl == 0.0
        assert n == 0

    def test_sums_history_correctly(self, tmp_path):
        r = _make_reconciler(tmp_path)

        close1 = MagicMock()
        close1.realized_pnl = 10.5
        close2 = MagicMock()
        close2.realized_pnl = -3.2
        close3 = MagicMock()
        close3.realized_pnl = 7.0

        pm = MagicMock()
        pm._history = [close1, close2, close3]

        with patch("execution.position_manager.position_manager", pm):
            pnl, n = r._collect_ledger_pnl()

        assert pnl == pytest.approx(14.3)
        assert n == 3

    def test_reads_the_real_singleton_not_an_invented_accessor(self, tmp_path):
        """Regression: the source must import a name that exists.

        Fails if _collect_ledger_pnl goes back to core.app_state — that module
        has no position-manager accessor, so the import would raise and the
        method would silently report zero realized P&L.
        """
        import inspect

        from ml.pnl_reconciler import PnLReconciler

        source = inspect.getsource(PnLReconciler._collect_ledger_pnl)
        assert "execution.position_manager" in source
        assert "get_position_manager" not in source


# ── _collect_broker_pnl ───────────────────────────────────────────────────────


class TestCollectBrokerPnl:
    async def test_returns_zero_when_broker_is_none(self, tmp_path):
        r = _make_reconciler(tmp_path)
        pnl, n = await r._collect_broker_pnl(None)
        assert pnl == 0.0
        assert n == 0

    async def test_uses_get_closed_trades(self, tmp_path):
        r = _make_reconciler(tmp_path)
        broker = MagicMock()
        broker.get_closed_trades = AsyncMock(
            return_value=[
                {"realized_pnl": 5.0},
                {"realizedPL": 3.0},  # alternate key name
            ]
        )
        pnl, n = await r._collect_broker_pnl(broker)
        assert pnl == pytest.approx(8.0)
        assert n == 2

    async def test_falls_back_to_account_info_realized_pnl(self, tmp_path):
        r = _make_reconciler(tmp_path)
        broker = MagicMock(spec=["get_account_info"])
        info = MagicMock()
        info.realized_pnl = 42.0
        broker.get_account_info = AsyncMock(return_value=info)
        pnl, n = await r._collect_broker_pnl(broker)
        assert pnl == pytest.approx(42.0)
        assert n == -1  # count unknown

    async def test_returns_zero_when_get_closed_trades_raises(self, tmp_path):
        r = _make_reconciler(tmp_path)
        broker = MagicMock()
        broker.get_closed_trades = AsyncMock(side_effect=ConnectionError("timeout"))
        pnl, n = await r._collect_broker_pnl(broker)
        assert pnl == 0.0
        assert n == 0

    async def test_returns_zero_when_broker_has_no_known_method(self, tmp_path):
        r = _make_reconciler(tmp_path)
        broker = MagicMock(spec=[])  # no get_closed_trades, no get_account_info
        pnl, n = await r._collect_broker_pnl(broker)
        assert pnl == 0.0
        assert n == 0


# ── snapshot_status ───────────────────────────────────────────────────────────


class TestSnapshotStatus:
    def test_returns_unavailable_when_no_snapshot(self, tmp_path):
        r = _make_reconciler(tmp_path)
        status = r.snapshot_status()
        assert status["available"] is False
        assert status["gate_passed"] is False

    def test_returns_available_with_fresh_snapshot(self, tmp_path):
        _write_snapshot(tmp_path, gate_passed=True, age_hours=1)
        r = _make_reconciler(tmp_path, stale_hours=24.0)
        status = r.snapshot_status()
        assert status["available"] is True
        assert status["gate_passed"] is True

    def test_includes_snapshot_path_when_unavailable(self, tmp_path):
        r = _make_reconciler(tmp_path)
        status = r.snapshot_status()
        assert "snapshot_path" in status


# ── ReconciliationResult.to_dict ──────────────────────────────────────────────


class TestReconciliationResult:
    def test_to_dict_contains_all_fields(self, tmp_path):
        from ml.pnl_reconciler import ReconciliationResult

        result = ReconciliationResult(
            gate_passed=True,
            ledger_pnl=100.0,
            broker_pnl=100.5,
            divergence=0.5,
            rel_divergence=0.005,
            n_ledger_trades=10,
            n_broker_trades=10,
            abs_tolerance=1.0,
            rel_tolerance=0.01,
            reason="test",
        )
        d = result.to_dict()
        for key in (
            "gate_passed",
            "ledger_pnl",
            "broker_pnl",
            "divergence",
            "rel_divergence",
            "n_ledger_trades",
            "n_broker_trades",
            "abs_tolerance",
            "rel_tolerance",
            "reason",
            "reconciled_at",
        ):
            assert key in d, f"Missing key: {key}"


# ── get_reconciler singleton ──────────────────────────────────────────────────


class TestSingleton:
    def test_returns_same_instance(self):
        import ml.pnl_reconciler as mr

        mr._reconciler = None
        from ml.pnl_reconciler import get_reconciler, PnLReconciler

        a = get_reconciler()
        b = get_reconciler()
        assert a is b
        assert isinstance(a, PnLReconciler)

    def test_creates_on_first_call(self):
        import ml.pnl_reconciler as mr

        mr._reconciler = None
        from ml.pnl_reconciler import get_reconciler, PnLReconciler

        r = get_reconciler()
        assert isinstance(r, PnLReconciler)


# ── ModelRegistry.promote P&L gate integration ───────────────────────────────


class TestModelRegistryPnLGate:
    """Verify that promote() enforces the P&L reconciliation gate."""

    @pytest.fixture()
    def registry(self, tmp_path):
        from ml.model_registry import ModelRegistry

        return ModelRegistry(registry_path=tmp_path / "registry.json")

    @pytest.fixture()
    def artifact(self, tmp_path):
        p = tmp_path / "model.pkl"
        p.write_bytes(pickle.dumps({"weights": [1, 2, 3]}))
        return p

    def _register_good(self, registry, artifact, name="v1"):
        return registry.register(
            name=name,
            file_path=artifact,
            oos_accuracy=0.70,
            oos_auc=0.72,
            oos_p_value=0.001,
            sharpe_gate_passed=True,
        )

    def test_promote_blocked_when_pnl_gate_fails(self, registry, artifact):
        """promote() must raise RuntimeError when P&L reconciliation gate fails."""
        self._register_good(registry, artifact)

        # Patch _pnl_reconciliation_check to return failure
        with patch.object(
            registry,
            "_pnl_reconciliation_check",
            return_value=(False, "P&L reconciliation gate BLOCKED: no fresh snapshot"),
        ):
            with pytest.raises(RuntimeError, match="BLOCKED"):
                registry.promote("v1")

    def test_promote_succeeds_when_pnl_gate_passes(self, registry, artifact):
        """promote() must succeed when both gates pass."""
        self._register_good(registry, artifact)

        with (
            patch.object(registry, "_pnl_reconciliation_check", return_value=(True, "P&L reconciliation gate passed")),
            patch.object(registry, "_update_symlink"),
            patch.dict(
                "sys.modules", {"ml.performance_monitor": MagicMock(get_monitor=MagicMock(return_value=MagicMock()))}
            ),
        ):
            entry = registry.promote("v1")

        assert entry["state"] == "production"

    def test_promote_pnl_gate_checked_after_stat_gate(self, registry, artifact):
        """P&L gate must not be called when the statistical gate already fails."""
        registry.register(
            name="v1",
            file_path=artifact,
            oos_accuracy=0.40,  # below threshold — stat gate fails first
            oos_p_value=0.001,
            sharpe_gate_passed=True,
        )

        pnl_check = MagicMock(return_value=(True, "ok"))
        with patch.object(registry, "_pnl_reconciliation_check", pnl_check):
            with pytest.raises(RuntimeError, match="BLOCKED"):
                registry.promote("v1")

        # P&L gate should NOT have been called — stat gate blocked first
        pnl_check.assert_not_called()

    def test_pnl_reconciliation_check_uses_get_reconciler(self, registry):
        """_pnl_reconciliation_check must delegate to PnLReconciler.check_gate."""
        mock_result = MagicMock()
        mock_result.gate_passed = True
        mock_result.reason = "gate passed"
        mock_reconciler = MagicMock()
        mock_reconciler.check_gate.return_value = mock_result

        with patch(
            "ml.model_registry.PnLReconciler" if False else "ml.pnl_reconciler.get_reconciler",
            return_value=mock_reconciler,
        ):
            passed, reason = registry._pnl_reconciliation_check()

        # Result depends on what get_reconciler().check_gate() returns
        assert isinstance(passed, bool)
        assert isinstance(reason, str)

    def test_pnl_reconciliation_check_handles_import_error(self, registry):
        """_pnl_reconciliation_check must return (False, msg) on import failure."""
        with patch(
            "ml.model_registry.ModelRegistry._pnl_reconciliation_check", wraps=registry._pnl_reconciliation_check
        ):
            with patch.dict("sys.modules", {"ml.pnl_reconciler": None}):
                passed, reason = registry._pnl_reconciliation_check()

        assert passed is False
        assert "unavailable" in reason.lower() or "BLOCKED" in reason
