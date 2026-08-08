# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_runtime_invariant_regressions.py
================================================
Four defects that `scripts/runtime_invariant_check.py` surfaced against a live
app, and that CI was reporting on every push to main.

Each one had gone unnoticed for the same reason: it happened inside a
``try/except Exception`` that logged at ``debug`` or ``warning`` and carried on,
so the symptom was a wrong number, an empty page or a slow request rather than a
traceback anybody would chase.

1. ``_get_ohlcv_for_symbol`` was unbounded in total. It carried independent 25s
   and 20s leg timeouts, which sum to 45s — long enough for one request to pin a
   worker while upstreams were degraded, and exactly the checker's
   ``HTTP_TIMEOUT``.

   Bounding it did **not** stop ``/api/trading/patterns`` timing out in CI; that
   probe still fails, from a cause upstream of this function that is still being
   tracked down. What the shared budget guarantees is that the fetch can no
   longer be the thing responsible.

2. ``api/superadmin/financial.py`` queried ``Configuration.key``. The column is
   ``config_key``; ``key``/``value``/``updated_at`` do not exist. Building the
   query raised ``AttributeError`` *inside* ``db_manager.session()``, whose
   ``except Exception`` books any error as a DATABASE failure — five of them
   tripped the circuit breaker and took ``/api/health``, ``/health/ready`` and
   ``/health/deep`` to 503.

3. The hot-standby promotion callback was written against the wrong
   ``HopeFXEngine``. Two classes share that name; the one that is wired has none
   of the attributes the callback used, so a promoted pod restored nothing.

4. The compliance hash chain reported ``INTEGRITY VIOLATION`` on logs nobody had
   tampered with, because the record held a reference to the caller's payload
   dict rather than a copy of it.
"""

from __future__ import annotations

import tempfile
import time

import pytest

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# 1. Shared OHLCV fetch budget
# ─────────────────────────────────────────────────────────────────────────────


class TestOhlcvFetchBudget:
    """The whole fetch is bounded, not each leg independently."""

    def test_budget_is_under_the_invariant_checker_timeout(self):
        """Legs summed to exactly the probe timeout; the total must stay under it.

        `scripts/runtime_invariant_check.py` uses HTTP_TIMEOUT = 45, and the old
        25s + 20s legs summed to exactly that. Pin the relationship, not just the
        number, so the sum cannot silently creep back up to it.
        """
        import api.trading as t

        assert t._OHLCV_TOTAL_BUDGET_S < 45, (
            "total OHLCV budget must stay below the runtime invariant checker's 45s HTTP_TIMEOUT"
        )
        # And below the sum of the individual legs, which is the whole point.
        assert t._OHLCV_TOTAL_BUDGET_S < (t._OHLCV_ENGINE_TIMEOUT_S + t._OHLCV_YFINANCE_TIMEOUT_S)

    def test_a_misconfigured_budget_cannot_take_down_the_api(self):
        """The knob is parsed at import time, so a typo must not break the module.

        `float(os.getenv(...))` at module scope turns a bad env var into a
        ValueError that stops `api.trading` — and therefore every trading route —
        from importing at all. A tuning knob must never be able to do that.
        """
        import api.trading as t

        assert t._ohlcv_budget_from_env("not-a-number") == 20.0
        assert t._ohlcv_budget_from_env("") == 20.0
        assert t._ohlcv_budget_from_env(None) == 20.0
        assert t._ohlcv_budget_from_env("   ") == 20.0

    def test_a_non_positive_budget_is_rejected(self):
        """Zero or negative would skip every leg and silently return no data."""
        import api.trading as t

        assert t._ohlcv_budget_from_env("0") == 20.0
        assert t._ohlcv_budget_from_env("-5") == 20.0

    def test_a_valid_budget_is_honoured(self):
        import api.trading as t

        assert t._ohlcv_budget_from_env("8") == 8.0
        assert t._ohlcv_budget_from_env("12.5") == 12.5

    def test_fresh_deadline_is_capped_by_remaining_budget(self):
        import api.trading as t

        deadline = time.monotonic() + t._OHLCV_TOTAL_BUDGET_S
        leg = t._ohlcv_leg_timeout(deadline, t._OHLCV_ENGINE_TIMEOUT_S)
        assert leg is not None
        # Engine cap is 25s but only the budget is actually available.
        assert leg <= t._OHLCV_TOTAL_BUDGET_S

    def test_leg_is_capped_by_its_own_limit_when_budget_is_larger(self):
        import api.trading as t

        leg = t._ohlcv_leg_timeout(time.monotonic() + 600, 5.0)
        assert leg == pytest.approx(5.0, abs=0.05)

    def test_second_leg_only_gets_what_the_first_left(self):
        import api.trading as t

        deadline = time.monotonic() + 8.0  # 8s notionally left
        leg = t._ohlcv_leg_timeout(deadline, t._OHLCV_YFINANCE_TIMEOUT_S)
        assert leg is not None
        assert leg == pytest.approx(8.0, abs=0.1)

    def test_exhausted_budget_skips_the_leg(self):
        """None means "skip" — so the local CSV is reached instead of being starved."""
        import api.trading as t

        assert t._ohlcv_leg_timeout(time.monotonic() - 1, 20.0) is None

    def test_sub_second_remainder_skips_rather_than_starting_a_doomed_request(self):
        import api.trading as t

        assert t._ohlcv_leg_timeout(time.monotonic() + 0.2, 20.0) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Configuration column names
# ─────────────────────────────────────────────────────────────────────────────


class TestConfigurationColumnNames:
    def test_configuration_has_no_key_value_or_updated_at(self):
        """Pins why the old query could never work."""
        from database.models import Configuration

        cols = {c.name for c in Configuration.__table__.columns}
        assert "config_key" in cols
        assert "config_value" in cols
        for absent in ("key", "value", "updated_at"):
            assert absent not in cols, f"{absent!r} is not a Configuration column"

    def test_environment_is_not_null_so_naive_inserts_fail(self):
        """The old write path never set `environment`, so the INSERT could not commit."""
        from database.models import Configuration

        env_col = Configuration.__table__.c.environment
        assert env_col.nullable is False

    def test_financial_module_no_longer_references_the_phantom_columns(self):
        """Guard against the pattern coming back as a hand-rolled query.

        Checked against the parsed AST rather than the raw text, so the
        explanatory comments in that module (which necessarily *name* the broken
        attributes) do not trip the guard.
        """
        import ast
        from pathlib import Path

        tree = ast.parse(Path("api/superadmin/financial.py").read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            # Configuration.key / Configuration.value / Configuration.updated_at
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "Configuration"
            ):
                assert node.attr not in {"key", "value", "updated_at"}, f"Configuration.{node.attr} is not a column"
            # Configuration(key=..., value=...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Configuration":
                for kw in node.keywords:
                    assert kw.arg not in {"key", "value", "updated_at"}, f"Configuration({kw.arg}=...) is not a column"

    def test_fee_config_goes_through_db_store(self):
        from pathlib import Path

        src = Path("api/superadmin/financial.py").read_text(encoding="utf-8")
        assert "from api.db_store import db_get" in src
        assert "from api.db_store import db_set" in src

    def test_db_store_uses_the_real_column_names(self):
        """The accessor that was already correct, and is now the single owner."""
        from pathlib import Path

        src = Path("api/db_store.py").read_text(encoding="utf-8")
        assert "config_key" in src
        assert "config_value" in src


class TestCallerErrorsCountAsDatabaseFailures:
    """Why a wrong column name took three health endpoints to 503.

    `DatabaseManager.session()` yields inside a `try`, and its trailing
    `except Exception` calls `_record_failure()`. So an exception raised by the
    *caller's* code inside the with-block — an AttributeError from touching a
    column that does not exist — is booked as a DATABASE failure. Five of them
    open the circuit breaker, and from then on every DB consumer in the process
    gets `ConnectionError: Database circuit breaker is open`, which is exactly
    what appeared in the CI logs alongside the 503s.

    This test pins the mechanism rather than asserting it is desirable. The
    caller bug is fixed (see TestConfigurationColumnNames), but the conflation
    itself is still latent: any future bad query re-creates it. Narrowing the
    breaker to genuine database errors is a change to a resilience gate and is
    deliberately left as a separate decision.
    """

    @staticmethod
    def _manager():
        import threading

        from database.connection import DatabaseManager

        class _Session:
            def execute(self, *a, **k): ...
            def commit(self): ...
            def rollback(self): ...
            def close(self): ...

        class _Metrics:
            query_count = 0
            slow_query_count = 0
            error_count = 0

            def record_latency(self, *a): ...

        m = DatabaseManager.__new__(DatabaseManager)
        m._session_factory = lambda: _Session()
        m.connection_string = "sqlite://"
        m.query_timeout = 30
        m.max_retries = 1
        m._circuit_open = False
        m._circuit_half_open = False
        m._circuit_threshold = 5
        m._circuit_recovery_time = 60.0
        m._failure_count = 0
        m._last_failure_time = None
        m._success_count = 0
        m._metrics_lock = threading.Lock()
        m._metrics = _Metrics()
        return m

    def test_five_caller_side_attribute_errors_open_the_breaker(self):
        from database.models import Configuration

        mgr = self._manager()
        assert mgr._circuit_open is False

        for _ in range(mgr._circuit_threshold):
            with pytest.raises(AttributeError), mgr.session():
                Configuration.key  # noqa: B018 — the exact defect, an app-level bug

        assert mgr._failure_count == 5
        assert mgr._circuit_open is True, "an application bug was booked as database unhealthiness"

    def test_once_open_every_other_db_consumer_is_refused(self):
        """The `ConnectionError` string that showed up in the CI logs."""
        from database.models import Configuration

        mgr = self._manager()
        for _ in range(mgr._circuit_threshold):
            with pytest.raises(AttributeError), mgr.session():
                Configuration.key  # noqa: B018

        with pytest.raises(ConnectionError, match="circuit breaker is open"), mgr.session():
            pass  # pragma: no cover — session() raises before yielding


# ─────────────────────────────────────────────────────────────────────────────
# 3. Hot-standby promotion restores state onto the engine that is actually wired
# ─────────────────────────────────────────────────────────────────────────────


class _Snapshot:
    def __init__(self, positions=None, equity=100_000.0):
        self.positions = positions if positions is not None else {"XAU_USD": {"units": 1}}
        self.equity = equity


class _FakeRiskManager:
    """Stands in for RiskManager: records that the halt-arming path was used."""

    def __init__(self):
        self.equity_updates: list[float] = []

    def update_equity(self, equity: float) -> None:
        self.equity_updates.append(equity)


class _RootShapedEngine:
    """What `init_engine` actually wires: only `_risk_manager`."""

    def __init__(self):
        self._risk_manager = _FakeRiskManager()


class _ExecutionShapedEngine:
    """What the callback was written against."""

    def __init__(self):
        self._open_positions: dict = {}
        self._current_equity = 0.0
        self._dd_tracker = self._Tracker()
        self._intra_monitor = self._Monitor()

    class _Tracker:
        def __init__(self):
            self.updates: list[float] = []

        def update(self, equity: float):
            self.updates.append(equity)

    class _Monitor:
        def __init__(self):
            self.updates: list[float] = []

        def update_equity(self, equity: float):
            self.updates.append(equity)


class TestHotStandbyPromotionRestore:
    def test_two_distinct_classes_really_do_share_the_name(self):
        """The trap the original callback fell into."""
        import execution.hopefx_engine as ex
        import hopefx_engine as root

        assert root.HopeFXEngine is not ex.HopeFXEngine

    def test_root_engine_lacks_every_attribute_the_old_callback_used(self):
        import ast
        from pathlib import Path

        tree = ast.parse(Path("hopefx_engine.py").read_text(encoding="utf-8"))
        cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "HopeFXEngine")
        assigned = set()
        for node in ast.walk(cls):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else ([node.target] if isinstance(node, ast.AnnAssign) else [])
            )
            for t in targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    assigned.add(t.attr)

        for attr in ("_dd_tracker", "_intra_monitor", "_open_positions", "_current_equity"):
            assert attr not in assigned, f"root HopeFXEngine unexpectedly has {attr}"
        assert "_risk_manager" in assigned

    def test_root_shaped_engine_restores_through_the_risk_manager(self):
        """This is the case that used to raise AttributeError and restore nothing."""
        from core.startup_factories import restore_engine_state_after_promotion

        engine = _RootShapedEngine()
        restored = restore_engine_state_after_promotion(engine, _Snapshot(equity=92_500.0))

        assert engine._risk_manager.equity_updates == [92_500.0]
        assert any("equity" in r for r in restored)

    def test_risk_manager_path_is_preferred_because_it_arms_the_halt_gates(self):
        """`update_equity` syncs the drawdown tracker AND re-evaluates auto-halt.

        Poking `_dd_tracker.update()` directly, as the original did, skips the
        halt evaluation — a pod promoted into a drawdown breach would carry on
        trading. Assert the real RiskManager still routes through the tracker.
        """
        import inspect

        from risk.manager import RiskManager

        src = inspect.getsource(RiskManager.update_equity)
        assert "_dd_tracker" in src
        assert "_halt_trading" in src

    def test_execution_shaped_engine_still_fully_restores(self):
        """The other shape must not regress."""
        from core.startup_factories import restore_engine_state_after_promotion

        engine = _ExecutionShapedEngine()
        snap = _Snapshot(positions={"XAU_USD": {"units": 3}}, equity=88_000.0)
        restored = restore_engine_state_after_promotion(engine, snap)

        assert engine._open_positions == snap.positions
        assert engine._current_equity == 88_000.0
        assert engine._dd_tracker.updates == [88_000.0]
        assert engine._intra_monitor.updates == [88_000.0]
        assert "positions" in restored

    def test_missing_engine_is_reported_not_swallowed(self):
        from core.startup_factories import restore_engine_state_after_promotion

        assert restore_engine_state_after_promotion(None, _Snapshot()) == []

    def test_unrecognised_engine_restores_nothing_and_says_so(self):
        from core.startup_factories import restore_engine_state_after_promotion

        class _Opaque:
            pass

        assert restore_engine_state_after_promotion(_Opaque(), _Snapshot()) == []

    def test_restore_does_not_raise_on_the_wired_shape(self):
        """The original symptom: AttributeError aborting the callback."""
        from core.startup_factories import restore_engine_state_after_promotion

        restore_engine_state_after_promotion(_RootShapedEngine(), _Snapshot())


# ─────────────────────────────────────────────────────────────────────────────
# 4. Audit hash chain: no false violations, real tampering still caught
# ─────────────────────────────────────────────────────────────────────────────


def _fresh_log():
    from compliance.auditor import ImmutableAuditLog

    return ImmutableAuditLog(log_path=tempfile.mkdtemp() + "/")


class TestAuditChainIntegrity:
    def test_clean_appends_verify(self):
        from compliance.auditor import AuditLevel

        log = _fresh_log()
        for i in range(3):
            log.append(AuditLevel.INFO, "cat", "actor", "act", {"i": i})
        assert log.verify_integrity() is True

    def test_caller_mutating_its_payload_is_not_a_violation(self):
        """Regression: this reported tampering on an untampered log."""
        from compliance.auditor import AuditLevel

        log = _fresh_log()
        payload = {"qty": 1}
        log.append(AuditLevel.INFO, "trade", "actor", "order", payload)
        payload["qty"] = 999

        assert log.verify_integrity() is True

    def test_caller_reusing_one_scratch_dict_is_not_a_violation(self):
        from compliance.auditor import AuditLevel

        log = _fresh_log()
        buf: dict = {}
        for i in range(3):
            buf["i"] = i
            log.append(AuditLevel.INFO, "cat", "actor", "act", buf)

        assert log.verify_integrity() is True

    def test_deep_mutation_is_not_a_violation(self):
        """A shallow copy would not have been enough."""
        from compliance.auditor import AuditLevel

        log = _fresh_log()
        nested = {"order": {"legs": [{"qty": 1}]}}
        log.append(AuditLevel.INFO, "trade", "actor", "order", nested)
        nested["order"]["legs"][0]["qty"] = 42

        assert log.verify_integrity() is True

    def test_the_record_keeps_the_value_as_it_was_at_append_time(self):
        from compliance.auditor import AuditLevel

        log = _fresh_log()
        payload = {"qty": 1}
        rec = log.append(AuditLevel.INFO, "trade", "actor", "order", payload)
        payload["qty"] = 999

        assert rec.data["qty"] == 1

    def test_actual_tampering_is_still_detected(self):
        """The detector must not have been softened into uselessness."""
        from compliance.auditor import AuditLevel

        log = _fresh_log()
        for i in range(3):
            log.append(AuditLevel.INFO, "cat", "actor", "act", {"i": i})

        log.records[1].data["i"] = 99
        assert log.verify_integrity() is False

    def test_rewriting_a_stored_hash_is_still_detected(self):
        from compliance.auditor import AuditLevel

        log = _fresh_log()
        for i in range(3):
            log.append(AuditLevel.INFO, "cat", "actor", "act", {"i": i})

        log.records[1].hash_chain = "0" * 64
        assert log.verify_integrity() is False
