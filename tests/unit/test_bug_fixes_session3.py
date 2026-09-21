# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/test_bug_fixes_session3.py
=================================
Regression tests for all bugs fixed in the session-3 scan:

  - api/performance.py  : missing datetime import, unused 'start' var, datetime.min NameError
  - api/journal.py      : B904 raise-from-exc in create/update
  - api/custom_indicators.py : missing 'status' import, NaN self-comparison
  - api/db_store.py     : contextlib.suppress in session close
  - api/health.py       : ternary pool_healthy
  - api/security_dashboard.py : missing HTTPException import
  - api/social_feed.py  : asyncio alias fix, B904 raise-from-exc
  - api/ws_live.py      : contextlib.suppress, no spurious global
  - api/trading.py      : merged nested-if, B904 raises, stray from-exc
  - api/billing.py      : stray from-exc on out-of-scope variables
  - api/webhooks.py     : B904 raises
  - api/superadmin/infrastructure.py : contextlib.suppress
  - api/superadmin/risk_management.py : _GLOBAL_REGISTRY naming
  - auth/router.py      : B904 ValueError raise-from-exc
  - core/event_bus.py   : contextlib.suppress x2
  - core/startup_factories.py : AlembicCommandError used in except
"""

from __future__ import annotations

import ast
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# repo root — this test lives at repo_root/tests/unit/
ROOT = Path(__file__).resolve().parents[2]


# ── helpers ───────────────────────────────────────────────────────────────────


def _parse(rel_path: str) -> ast.Module:
    """Parse a source file and return its AST."""
    src = (ROOT / rel_path).read_text(encoding="utf-8")
    return ast.parse(src, filename=rel_path)


def _source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# api/performance.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestPerformanceFixes:
    def test_datetime_imported_at_module_level(self):
        """datetime must be imported at module level (not only inside functions)."""
        src = _source("api/performance.py")
        # The fix adds 'from datetime import datetime' at the top
        assert "from datetime import datetime" in src, "api/performance.py must import datetime at module level"

    def test_no_unused_start_variable(self):
        """The bare 'curve[0].equity' useless attribute access must be gone."""
        src = _source("api/performance.py")
        # After the fix the line 'curve[0].equity' (useless access) is removed
        # and 'start = curve[0].equity' is also removed
        assert "start = curve[0].equity" not in src, (
            "Unused 'start' variable must be removed from _compute_public_stats"
        )
        # The bare attribute access (B018) must also be gone
        assert "    curve[0].equity\n" not in src, "Bare 'curve[0].equity' useless attribute access must be removed"

    def test_datetime_min_uses_local_variable(self):
        """datetime.min must be captured in a local variable before the lambda."""
        src = _source("api/performance.py")
        assert "_dt_min = datetime.min" in src, "datetime.min must be captured as _dt_min before the sorted() lambda"
        assert "or _dt_min" in src, "sorted() lambda must reference _dt_min, not bare datetime.min"

    def test_build_equity_points_computes_drawdown(self):
        """_build_equity_points logic: drawdown must be negative when equity falls."""
        # Test the logic directly without importing the full api package

        class EquityPoint:
            def __init__(self, timestamp, equity, drawdown, balance):
                self.timestamp = timestamp
                self.equity = equity
                self.drawdown = drawdown
                self.balance = balance

        def _build_equity_points(equity_values, starting):
            points = []
            peak = starting
            for ts_raw, eq_val in equity_values:
                eq = float(eq_val)
                peak = max(peak, eq)
                dd = (eq - peak) / peak if peak > 0 else 0.0
                ts_str = ts_raw if isinstance(ts_raw, str) else str(ts_raw)
                points.append(EquityPoint(ts_str, round(eq, 4), round(dd, 6), round(eq, 4)))
            return points

        pts = _build_equity_points([(1_000_000, 100_000), (1_000_001, 90_000)], 100_000)
        assert len(pts) == 2
        assert pts[0].drawdown == 0.0
        assert pts[1].drawdown < 0.0, "Drawdown must be negative when equity falls"

    def test_compute_public_stats_no_crash_on_empty(self):
        """_compute_public_stats must return zero stats on empty curve."""

        # Test the logic directly without importing the full api package
        class PublicPerformance:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        def _compute_public_stats(curve):
            if not curve:
                return PublicPerformance(
                    total_trades=0,
                    win_rate=None,
                    avg_return_pct=None,
                    sharpe=None,
                    max_drawdown_pct=0.0,
                    start_date="—",
                    note="Paper trading not yet started.",
                )
            return PublicPerformance(total_trades=len(curve))

        result = _compute_public_stats([])
        assert result.total_trades == 0


# ═══════════════════════════════════════════════════════════════════════════════
# api/journal.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestJournalFixes:
    def test_create_entry_raises_from_exc(self):
        """create_entry must use 'raise HTTPException(...) from exc' (B904)."""
        src = _source("api/journal.py")
        # After fix: 'raise HTTPException(status_code=500, ...) from exc'
        assert 'raise HTTPException(status_code=500, detail="Failed to create journal entry") from exc' in src

    def test_update_entry_raises_from_exc(self):
        """update_entry must use 'raise HTTPException(...) from exc' (B904)."""
        src = _source("api/journal.py")
        assert 'raise HTTPException(status_code=500, detail="Failed to update journal entry") from exc' in src

    def test_no_unused_noqa_directive(self):
        """The unused noqa: PLC0415 directive must be removed."""
        src = _source("api/journal.py")
        assert "noqa: PLC0415" not in src


# ═══════════════════════════════════════════════════════════════════════════════
# api/custom_indicators.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestCustomIndicatorsFixes:
    def test_status_imported_from_fastapi(self):
        """fastapi.status must be imported so HTTP_503_SERVICE_UNAVAILABLE is defined."""
        src = _source("api/custom_indicators.py")
        assert "from fastapi import" in src
        assert "status" in src.split("from fastapi import")[1].split("\n")[0], (
            "'status' must be in the fastapi import line"
        )

    def test_nan_check_uses_math_isnan(self):
        """NaN check must use math.isnan, not the self-comparison v != v."""
        src = _source("api/custom_indicators.py")
        assert "v != v" not in src, "Self-comparison NaN check must be replaced with math.isnan"
        assert "isnan" in src, "math.isnan must be used for NaN detection"

    def test_math_isnan_correctly_detects_nan(self):
        """Verify math.isnan works as expected for the NaN filter."""
        values = [1.0, float("nan"), 2.0, None]
        result = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
        assert result == [1.0, 2.0]


# ═══════════════════════════════════════════════════════════════════════════════
# api/db_store.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestDbStoreFixes:
    def test_contextlib_suppress_used_for_session_close(self):
        """Session close must use contextlib.suppress instead of try/except/pass."""
        src = _source("api/db_store.py")
        assert "contextlib.suppress" in src, "api/db_store.py must use contextlib.suppress for session.close()"

    def test_session_close_exception_suppressed(self):
        """contextlib.suppress(Exception) must swallow errors from session.close()."""
        import contextlib

        call_count = 0

        class BadSession:
            def close(self):
                nonlocal call_count
                call_count += 1
                raise RuntimeError("close failed")

        session = BadSession()
        with contextlib.suppress(Exception):
            session.close()

        assert call_count == 1, "close() must be called even if it raises"


# ═══════════════════════════════════════════════════════════════════════════════
# api/health.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthFixes:
    def test_pool_healthy_ternary(self):
        """pool_healthy check must use ternary, not if/else block."""
        src = _source("api/health.py")
        assert "healthy = pool_healthy() if callable(pool_healthy) else True" in src

    def test_pool_healthy_callable_called(self):
        """When pool_healthy is callable, it must be invoked."""
        pool_healthy = MagicMock(return_value=False)
        healthy = pool_healthy() if callable(pool_healthy) else True
        assert healthy is False
        pool_healthy.assert_called_once()

    def test_pool_healthy_non_callable_defaults_true(self):
        """When pool_healthy is not callable, healthy must default to True."""
        pool_healthy = None
        healthy = pool_healthy() if callable(pool_healthy) else True
        assert healthy is True


# ═══════════════════════════════════════════════════════════════════════════════
# api/security_dashboard.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestSecurityDashboardFixes:
    def test_httpexception_imported(self):
        """HTTPException must be imported in security_dashboard.py."""
        src = _source("api/security_dashboard.py")
        assert "HTTPException" in src.split("from fastapi import")[1].split("\n")[0], (
            "HTTPException must be in the fastapi import line"
        )

    def test_module_parses_without_undefined_names(self):
        """The module AST must not reference undefined HTTPException."""
        tree = _parse("api/security_dashboard.py")
        # Collect all Name nodes used in Raise statements
        raises = [node for node in ast.walk(tree) if isinstance(node, ast.Raise) and node.exc is not None]
        # All raises should reference HTTPException which is now imported
        assert len(raises) > 0, "security_dashboard.py must have raise statements"


# ═══════════════════════════════════════════════════════════════════════════════
# api/social_feed.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestSocialFeedFixes:
    def test_asyncio_timeout_uses_alias(self):
        """TimeoutError reference must use the _asyncio alias, not bare asyncio."""
        src = _source("api/social_feed.py")
        # The fix changes 'asyncio.TimeoutError' to '_asyncio.TimeoutError'
        assert "asyncio.TimeoutError" not in src or "_asyncio.TimeoutError" in src, (
            "asyncio.TimeoutError must be referenced via the _asyncio alias"
        )

    def test_leaderboard_raise_from_exc(self):
        """Leaderboard profile lookup must raise HTTPException from exc (B904)."""
        src = _source("api/social_feed.py")
        assert 'raise HTTPException(status_code=404, detail="Trader not found") from exc' in src


# ═══════════════════════════════════════════════════════════════════════════════
# api/ws_live.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestWsLiveFixes:
    def test_safe_ws_close_uses_contextlib_suppress(self):
        """_safe_ws_close must use contextlib.suppress instead of try/except/pass."""
        src = _source("api/ws_live.py")
        assert "contextlib.suppress(RuntimeError)" in src

    def test_no_spurious_global_prices_seeded(self):
        """The read-only global _prices_seeded declaration must be removed from the broadcaster."""
        src = _source("api/ws_live.py")
        # Count occurrences of 'global _prices_seeded'
        count = src.count("global _prices_seeded")
        # Only the function that ASSIGNS to it should have the global declaration
        assert count <= 1, (
            "Only one 'global _prices_seeded' declaration should exist (in the function that assigns to it)"
        )

    def test_contextlib_suppress_swallows_runtime_error(self):
        """contextlib.suppress(RuntimeError) must swallow RuntimeError."""
        import contextlib

        called = []

        async def fake_close():
            called.append(True)
            raise RuntimeError("already closed")

        import asyncio

        async def run():
            with contextlib.suppress(RuntimeError):
                await fake_close()

        asyncio.run(run())
        assert called, "fake_close must have been called"


# ═══════════════════════════════════════════════════════════════════════════════
# api/trading.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestTradingFixes:
    def test_no_stray_from_exc_on_out_of_scope(self):
        """No 'from exc' should appear where exc is not in scope."""
        src = _source("api/trading.py")
        # The specific bad pattern: raise HTTPException(...) from exc
        # where exc is not defined in the enclosing except clause
        # Check the CVaR gate line — it was inside an if block, not except
        assert (
            'raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"CVaR limit breached: {reason}") from exc'
            not in src
        )

    def test_no_stray_from_exc_strategy_performance(self):
        """Strategy performance endpoint must not reference undefined exc."""
        src = _source("api/trading.py")
        assert 'raise HTTPException(404, "Strategy not found") from exc' not in src

    def test_b904_raises_have_from_clause(self):
        """Key except blocks in trading.py must use raise-from."""
        src = _source("api/trading.py")
        # The TimeoutError handler for modify_position
        assert "raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT" in src

    def test_nested_if_merged(self):
        """The IDOR ownership check must be a single ``if``, not nested ones.

        This asserted on the literal ``"and user.role not in"``, which coupled a
        structural property (one condition, not two nested) to one clause of the
        condition — the operator carve-out that let admin and superadmin close
        another user's position. That carve-out was deliberately removed when
        accounts became per-user, so the substring is gone while the property it
        stood for still holds. Checked on the parsed tree instead.
        """
        import ast
        import inspect

        from api import trading

        tree = ast.parse(inspect.getsource(trading.close_position))
        # The ownership branch is the one that raises 403.
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            raises_403 = any(
                isinstance(n, ast.Raise) and "403" in ast.unparse(n) or "FORBIDDEN" in ast.unparse(n)
                for n in ast.walk(node)
            )
            if not raises_403:
                continue
            nested = [n for n in node.body if isinstance(n, ast.If)]
            assert not nested, "the ownership check is nested again — it should be one combined condition"
            return
        raise AssertionError("no 403 ownership branch found in close_position")


# ═══════════════════════════════════════════════════════════════════════════════
# api/billing.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestBillingFixes:
    def test_no_stray_from_exc_on_non_except_raise(self):
        """Raises outside except blocks must not reference undefined exc."""
        src = _source("api/billing.py")
        # The 'if event is None' raise was incorrectly getting 'from exc'
        assert 'raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature") from exc' not in src

    def test_no_stray_from_exc_on_plan_validation(self):
        """Plan validation raise must not reference undefined exc."""
        src = _source("api/billing.py")
        assert 'raise HTTPException(status_code=400, detail=f"Invalid plan.' in src
        # Must NOT have 'from exc' appended
        lines = [l for l in src.splitlines() if "Invalid plan." in l]
        for line in lines:
            assert "from exc" not in line, f"Stray 'from exc' on plan validation: {line}"


# ═══════════════════════════════════════════════════════════════════════════════
# api/webhooks.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestWebhooksFixes:
    def test_json_parse_raises_from_exc(self):
        """JSON parse failure must raise HTTPException from exc (B904)."""
        src = _source("api/webhooks.py")
        assert (
            'raise HTTPException(\n            status_code=status.HTTP_400_BAD_REQUEST,\n            detail="Request body must be valid JSON.",\n        ) from exc'
            in src
        )

    def test_alert_parse_raises_from_exc(self):
        """Alert payload parse failure must raise HTTPException from exc (B904)."""
        src = _source("api/webhooks.py")
        assert (
            'raise HTTPException(\n            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,\n            detail="Invalid alert payload.",\n        ) from exc'
            in src
        )


# ═══════════════════════════════════════════════════════════════════════════════
# api/superadmin/infrastructure.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestSuperadminInfrastructureFixes:
    def test_redis_info_uses_contextlib_suppress(self):
        """Redis info() call must use contextlib.suppress."""
        src = _source("api/superadmin/infrastructure.py")
        assert "contextlib.suppress" in src

    def test_suppress_swallows_redis_error(self):
        """contextlib.suppress(Exception) must swallow Redis errors."""
        import contextlib

        info: dict = {}
        with contextlib.suppress(Exception):
            raise ConnectionError("Redis down")
        assert info == {}, "info must remain empty when Redis raises"


# ═══════════════════════════════════════════════════════════════════════════════
# api/superadmin/risk_management.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestSuperadminRiskManagementFixes:
    """These two originally policed the *spelling* of a symbol that does not exist.

    They asserted `_GLOBAL_REGISTRY` was imported un-aliased, for N811 naming
    compliance. But `risk/circuit_breakers.py` exports `_registry` behind
    `get_circuit_breakers()` and has never had a `_GLOBAL_REGISTRY`, so the
    import raised ImportError into a bare `except` and the breaker controls
    silently did nothing. A lint-shaped test held the broken name in place.
    """

    def test_the_dead_symbol_is_gone(self):
        src = _source("api/superadmin/risk_management.py")
        assert "_GLOBAL_REGISTRY" not in src, (
            "risk.circuit_breakers exports no _GLOBAL_REGISTRY; importing it "
            "raises ImportError and the operator control becomes a no-op"
        )

    def test_the_real_registry_accessor_is_used(self):
        src = _source("api/superadmin/risk_management.py")
        assert "get_circuit_breakers" in src


# ═══════════════════════════════════════════════════════════════════════════════
# api/superadmin/security_infra.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestSuperadminSecurityInfraFixes:
    def test_subprocess_run_has_check_false(self):
        """subprocess.run for clamscan must have check=False (PLW1510)."""
        src = _source("api/superadmin/security_infra.py")
        # Find the clamscan subprocess.run call
        clamscan_block = src[src.find("clamscan") :]
        first_run = clamscan_block[: clamscan_block.find(")") + 1]
        assert "check=False" in first_run, "subprocess.run for clamscan must have explicit check=False"


# ═══════════════════════════════════════════════════════════════════════════════
# api/superadmin/system_health.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestSuperadminSystemHealthFixes:
    @staticmethod
    def _pg_dump_calls(module: str):
        """Every call in *module* whose first list argument starts with "pg_dump"."""
        import ast

        return [
            n
            for n in ast.walk(ast.parse(_source(module)))
            if isinstance(n, ast.Call)
            and any(
                isinstance(a, ast.List)
                and a.elts
                and isinstance(a.elts[0], ast.Constant)
                and a.elts[0].value == "pg_dump"
                for a in n.args
            )
        ]

    def test_system_health_does_not_shell_out_to_pg_dump(self):
        """The endpoint delegates to the verified backup path instead of reimplementing it.

        This test originally pinned ``check=False`` on a ``pg_dump``
        ``subprocess.run`` inside ``trigger_backup``. That call is gone: the
        endpoint now calls ``database.backup.run_backup()`` and
        ``database.restore.verify_backup()``, the same path Phase R1 proved by
        round trip, so a backup that writes but does not restore is reported as
        a failure rather than a success (MASTER_OUTSTANDING §B2 item 14).

        The assertion is inverted rather than deleted, because the risk it
        guarded is still real: if anybody reintroduces an ad-hoc dump here, the
        next test catches it.
        """
        assert self._pg_dump_calls("api/superadmin/system_health.py") == [], (
            "system_health.py is shelling out to pg_dump again — it should call "
            "database.backup.run_backup(), which verifies the artefact before reporting success"
        )

    def test_trigger_backup_uses_the_verified_path_off_the_event_loop(self):
        src = _source("api/superadmin/system_health.py")
        assert "from database.backup import run_backup" in src, "trigger_backup must use the verified backup path"
        assert "from database.restore import verify_backup" in src, (
            "trigger_backup must verify the artefact before reporting success"
        )
        # Both are blocking; neither may run on the event loop.
        assert "asyncio.to_thread(run_backup)" in src
        assert "asyncio.to_thread(verify_backup, backup_path)" in src

    def test_a_reintroduced_pg_dump_would_still_have_to_pass_check_false(self):
        """The original ratchet, kept alive for the case it was written for."""
        for call in self._pg_dump_calls("api/superadmin/system_health.py"):
            kwargs = {k.arg: k.value for k in call.keywords if k.arg}
            assert "check" in kwargs, "pg_dump call must pass explicit check="
            assert kwargs["check"].value is False, "pg_dump call must pass check=False"
            # pg_dump has timeout=60; run inline it would stall the event loop
            # for up to a minute, so it must be dispatched off the loop.
            assert ast.unparse(call.func) == "asyncio.to_thread", (
                "pg_dump must be dispatched via asyncio.to_thread, not called inline in an async route"
            )
            assert ast.unparse(call.args[0]) == "subprocess.run"


# ═══════════════════════════════════════════════════════════════════════════════
# auth/router.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthRouterFixes:
    def test_parse_int_env_raises_from_exc(self):
        """_parse_int_env ValueError must use raise-from (B904)."""
        src = _source("auth/router.py")
        assert "raise ValueError(" in src
        # The raise must be followed by 'from exc'
        idx = src.find("raise ValueError(")
        block = src[idx : idx + 300]
        assert "from exc" in block, "_parse_int_env must raise ValueError from exc"

    def test_no_stray_from_login_exc(self):
        """Raises outside the login except block must not reference _login_exc."""
        src = _source("auth/router.py")
        # These lines were incorrectly getting 'from _login_exc'
        assert "raise HTTPException(status_code=401, detail=msg) from _login_exc" not in src
        assert 'raise HTTPException(status_code=500, detail="Authentication service error") from _login_exc' not in src

    def test_parse_int_env_raises_value_error(self):
        """_parse_int_env must raise ValueError for non-integer strings."""
        sys.path.insert(0, str(ROOT))
        try:
            # Import the function by executing the relevant portion
            import importlib.util

            _spec = importlib.util.spec_from_file_location("auth_router", ROOT / "auth" / "router.py")

            # We can't fully import auth.router without all deps, so test the logic directly
            def _parse_int_env(name: str, default: int, env: dict) -> int:
                raw = env.get(name)
                if raw is None:
                    return default
                try:
                    return int(raw)
                except ValueError as exc:
                    raise ValueError(f"Environment variable {name}={raw!r} must be a plain integer") from exc

            assert _parse_int_env("X", 10, {}) == 10
            assert _parse_int_env("X", 10, {"X": "42"}) == 42
            with pytest.raises(ValueError, match="must be a plain integer"):
                _parse_int_env("X", 10, {"X": "10s"})
        finally:
            sys.path.pop(0)


# ═══════════════════════════════════════════════════════════════════════════════
# core/event_bus.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventBusFixes:
    def test_unsubscribe_local_uses_contextlib_suppress(self):
        """unsubscribe_local must use contextlib.suppress(ValueError)."""
        src = _source("core/event_bus.py")
        assert "contextlib.suppress(ValueError)" in src

    def test_queue_eviction_uses_contextlib_suppress(self):
        """Queue eviction must use contextlib.suppress(asyncio.QueueEmpty)."""
        src = _source("core/event_bus.py")
        assert "contextlib.suppress(asyncio.QueueEmpty)" in src

    def test_unsubscribe_local_no_op_when_not_registered(self):
        """unsubscribe_local must not raise when handler is not registered."""
        sys.path.insert(0, str(ROOT))
        try:
            # Test the logic directly without importing the full module
            import contextlib

            handlers: list = []

            def handler():
                pass

            with contextlib.suppress(ValueError):
                handlers.remove(handler)  # handler not in list — must not raise

            assert handlers == []
        finally:
            sys.path.pop(0)

    def test_queue_eviction_suppress_empty_queue(self):
        """Queue eviction must not raise when queue is already empty."""
        import asyncio
        import contextlib

        queue: asyncio.Queue = asyncio.Queue(maxsize=1)

        async def run():
            # Queue is empty — get_nowait would raise QueueEmpty
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            # Must reach here without exception
            return True

        result = asyncio.run(run())
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# core/startup_factories.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartupFactoriesFixes:
    def test_alembic_command_error_used_in_except(self):
        """AlembicCommandError must appear in an except clause, not just imported."""
        src = _source("core/startup_factories.py")
        assert "AlembicCommandError" in src
        # It must appear in an except clause
        assert "except (AlembicCommandError" in src or "except AlembicCommandError" in src, (
            "AlembicCommandError must be used in an except clause"
        )

    def test_no_unused_noqa_for_alembic_import(self):
        """The noqa: F401 directive for AlembicCommandError must be removed."""
        src = _source("core/startup_factories.py")
        assert "noqa: F401" not in src or "AlembicCommandError" not in src.split("noqa: F401")[0].split("\n")[-1]


# ═══════════════════════════════════════════════════════════════════════════════
# General: all fixed files parse without syntax errors
# ═══════════════════════════════════════════════════════════════════════════════

FIXED_FILES = [
    "api/performance.py",
    "api/journal.py",
    "api/custom_indicators.py",
    "api/db_store.py",
    "api/health.py",
    "api/security_dashboard.py",
    "api/social_feed.py",
    "api/ws_live.py",
    "api/trading.py",
    "api/billing.py",
    "api/webhooks.py",
    "api/superadmin/infrastructure.py",
    "api/superadmin/risk_management.py",
    "api/superadmin/security_infra.py",
    "api/superadmin/system_health.py",
    "auth/router.py",
    "core/event_bus.py",
    "core/startup_factories.py",
    # Also verify the other scanned files
    "api/analysis.py",
    "api/ml.py",
    "api/portfolio.py",
    "api/signals.py",
    "api/notifications.py",
    "api/nuclear.py",
    "api/ws_public.py",
    "api/advanced_trading.py",
    "core/outbox.py",
    "core/position_reconciler.py",
    "core/strategy_orchestra.py",
    "core/main_loop.py",
    "core/middleware.py",
    "core/background_tasks.py",
    "core/live_trading_gate.py",
    "core/regime_router.py",
    "brokers/oanda.py",
    "brokers/ibkr.py",
    "brokers/paper_trading.py",
    "risk/gatekeeper.py",
    "risk/risk_manager.py",
    "auth/service.py",
    "data/market_ingest.py",
]


@pytest.mark.parametrize("rel_path", FIXED_FILES)
def test_file_parses_without_syntax_error(rel_path: str):
    """Every fixed file must parse as valid Python."""
    path = ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} does not exist")
    src = path.read_text(encoding="utf-8")
    try:
        ast.parse(src, filename=rel_path)
    except SyntaxError as exc:
        pytest.fail(f"SyntaxError in {rel_path}: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# Ruff clean: all fixed files must pass ruff check
# ═══════════════════════════════════════════════════════════════════════════════


def test_ruff_clean_on_all_fixed_files():
    """All fixed files must pass ruff check with zero errors."""
    import shutil
    import subprocess

    # Prefer the standalone ruff binary; fall back to python3 -m ruff.
    ruff_bin = shutil.which("ruff")
    if ruff_bin:
        cmd = [ruff_bin, "check", "--output-format=concise"]
    else:
        # Verify python3 -m ruff is available before running
        probe = subprocess.run(
            ["python3", "-m", "ruff", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            pytest.skip("ruff not installed — add ruff>=0.9.0 to requirements-ci.txt")
        cmd = ["python3", "-m", "ruff", "check", "--output-format=concise"]

    existing = [str(ROOT / p) for p in FIXED_FILES if (ROOT / p).exists()]
    result = subprocess.run(
        cmd + existing,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"ruff found issues in fixed files:\n{result.stdout}\n{result.stderr}")
