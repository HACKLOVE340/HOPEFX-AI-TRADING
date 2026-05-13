# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_auto_rollback.py
==================================
Unit tests for resilience/auto_rollback.py.

Covers:
- RollbackStrategy constants
- RollbackResult dataclass and to_dict()
- RollbackTrigger.should_trigger() — enabled/disabled, cooldown, condition
- RollbackTrigger.mark_triggered() — updates last triggered time
- AutoRollbackManager.register_trigger()
- AutoRollbackManager.rollback() — soft/medium/hard/full/unknown strategies
- AutoRollbackManager.get_status()
- AutoRollbackManager._check_triggers() — fires when condition met
"""

from __future__ import annotations

import time
import pytest


# ---------------------------------------------------------------------------
# RollbackStrategy
# ---------------------------------------------------------------------------


class TestRollbackStrategy:
    def test_strategy_constants_defined(self):
        from resilience.auto_rollback import RollbackStrategy

        assert RollbackStrategy.SOFT == "soft"
        assert RollbackStrategy.MEDIUM == "medium"
        assert RollbackStrategy.HARD == "hard"
        assert RollbackStrategy.FULL == "full"


# ---------------------------------------------------------------------------
# RollbackResult
# ---------------------------------------------------------------------------


class TestRollbackResult:
    def test_to_dict_contains_required_keys(self):
        from resilience.auto_rollback import RollbackResult

        r = RollbackResult(success=True, strategy="soft", reason="test")
        d = r.to_dict()
        assert "success" in d
        assert "strategy" in d
        assert "reason" in d
        assert "actions_taken" in d
        assert "errors" in d
        assert "rolled_back_at" in d
        assert "duration_ms" in d

    def test_to_dict_values(self):
        from resilience.auto_rollback import RollbackResult

        r = RollbackResult(
            success=True,
            strategy="soft",
            reason="manual",
            actions_taken=["disabled_flags"],
            errors=[],
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["strategy"] == "soft"
        assert d["reason"] == "manual"
        assert d["actions_taken"] == ["disabled_flags"]
        assert d["errors"] == []

    def test_default_actions_and_errors_empty(self):
        from resilience.auto_rollback import RollbackResult

        r = RollbackResult(success=False, strategy="medium", reason="auto")
        assert r.actions_taken == []
        assert r.errors == []

    def test_rolled_back_at_is_iso_string(self):
        from resilience.auto_rollback import RollbackResult

        r = RollbackResult(success=True, strategy="soft", reason="test")
        # Should be parseable as ISO datetime
        from datetime import datetime

        dt = datetime.fromisoformat(r.rolled_back_at)
        assert dt is not None


# ---------------------------------------------------------------------------
# RollbackTrigger
# ---------------------------------------------------------------------------


class TestRollbackTrigger:
    def test_should_trigger_when_condition_true(self):
        from resilience.auto_rollback import RollbackTrigger

        t = RollbackTrigger(
            name="test",
            condition=lambda: True,
            cooldown_seconds=0.0,
        )
        assert t.should_trigger() is True

    def test_should_not_trigger_when_condition_false(self):
        from resilience.auto_rollback import RollbackTrigger

        t = RollbackTrigger(
            name="test",
            condition=lambda: False,
            cooldown_seconds=0.0,
        )
        assert t.should_trigger() is False

    def test_should_not_trigger_when_disabled(self):
        from resilience.auto_rollback import RollbackTrigger

        t = RollbackTrigger(
            name="test",
            condition=lambda: True,
            enabled=False,
            cooldown_seconds=0.0,
        )
        assert t.should_trigger() is False

    def test_should_not_trigger_within_cooldown(self):
        from resilience.auto_rollback import RollbackTrigger

        t = RollbackTrigger(
            name="test",
            condition=lambda: True,
            cooldown_seconds=300.0,
        )
        t.mark_triggered()
        assert t.should_trigger() is False

    def test_should_trigger_after_cooldown_expires(self):
        from resilience.auto_rollback import RollbackTrigger

        t = RollbackTrigger(
            name="test",
            condition=lambda: True,
            cooldown_seconds=0.001,
        )
        t.mark_triggered()
        time.sleep(0.01)
        assert t.should_trigger() is True

    def test_condition_exception_returns_false(self):
        from resilience.auto_rollback import RollbackTrigger

        def bad_condition():
            raise RuntimeError("broken")

        t = RollbackTrigger(
            name="test",
            condition=bad_condition,
            cooldown_seconds=0.0,
        )
        assert t.should_trigger() is False

    def test_mark_triggered_updates_last_triggered(self):
        from resilience.auto_rollback import RollbackTrigger

        t = RollbackTrigger(name="test", condition=lambda: True)
        before = t._last_triggered
        t.mark_triggered()
        assert t._last_triggered > before


# ---------------------------------------------------------------------------
# AutoRollbackManager
# ---------------------------------------------------------------------------


class TestAutoRollbackManager:
    def _make_manager(self):
        from resilience.auto_rollback import AutoRollbackManager

        return AutoRollbackManager()

    def test_register_trigger_adds_to_list(self):
        from resilience.auto_rollback import RollbackTrigger

        mgr = self._make_manager()
        t = RollbackTrigger(name="my_trigger", condition=lambda: False)
        mgr.register_trigger(t)
        assert any(tr.name == "my_trigger" for tr in mgr._triggers)

    @pytest.mark.asyncio
    async def test_soft_rollback_succeeds(self):
        mgr = self._make_manager()
        result = await mgr.rollback(strategy="soft", reason="test")
        assert result.strategy == "soft"
        assert result.reason == "test"
        assert isinstance(result.success, bool)
        assert result.duration_ms >= 0.0

    @pytest.mark.asyncio
    async def test_medium_rollback_runs(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mgr = self._make_manager()
        mock_healer = MagicMock()
        mock_healer._run_code_analysis = AsyncMock(return_value=None)
        mock_healer._drift_events = []
        mock_healer.apply_config = MagicMock()
        with patch("security.self_healer.get_healer", return_value=mock_healer):
            result = await mgr.rollback(strategy="medium", reason="test")
        assert result.strategy == "medium"
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_hard_rollback_runs(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mgr = self._make_manager()
        mock_healer = MagicMock()
        mock_healer._run_code_analysis = AsyncMock(return_value=None)
        mock_healer.rebuild_baseline = AsyncMock(return_value=None)
        mock_healer._drift_events = []
        mock_healer.apply_config = MagicMock()
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("security.self_healer.get_healer", return_value=mock_healer),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = await mgr.rollback(strategy="hard", reason="test", target_files=[])
        assert result.strategy == "hard"
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_full_rollback_runs(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mgr = self._make_manager()
        mock_healer = MagicMock()
        mock_healer._run_code_analysis = AsyncMock(return_value=None)
        mock_healer.rebuild_baseline = AsyncMock(return_value=None)
        mock_healer._drift_events = []
        mock_healer.apply_config = MagicMock()
        mock_proc = MagicMock(returncode=0, stdout="v10.0.0", stderr="")
        with (
            patch("security.self_healer.get_healer", return_value=mock_healer),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = await mgr.rollback(strategy="full", reason="test")
        assert result.strategy == "full"
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_unknown_strategy_fails(self):
        mgr = self._make_manager()
        result = await mgr.rollback(strategy="unknown_xyz", reason="test")
        assert result.success is False
        assert any("Unknown strategy" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_rollback_increments_count(self):
        mgr = self._make_manager()
        before = mgr._rollback_count
        await mgr.rollback(strategy="soft", reason="test")
        assert mgr._rollback_count == before + 1

    @pytest.mark.asyncio
    async def test_rollback_records_history(self):
        mgr = self._make_manager()
        await mgr.rollback(strategy="soft", reason="history_test")
        assert len(mgr._history) >= 1
        assert mgr._history[-1]["reason"] == "history_test"

    def test_get_status_returns_dict(self):
        mgr = self._make_manager()
        status = mgr.get_status()
        assert isinstance(status, dict)
        assert "rollback_count" in status
        assert "in_rollback" in status
        assert "triggers" in status

    def test_get_status_trigger_count(self):
        from resilience.auto_rollback import RollbackTrigger

        mgr = self._make_manager()
        initial_count = len(mgr._triggers)
        mgr.register_trigger(RollbackTrigger(name="extra", condition=lambda: False))
        status = mgr.get_status()
        # triggers is a list of dicts — one per registered trigger
        triggers = status["triggers"]
        assert len(triggers) == initial_count + 1
        assert any(t["name"] == "extra" for t in triggers)

    @pytest.mark.asyncio
    async def test_check_triggers_fires_when_condition_met(self):
        from resilience.auto_rollback import RollbackTrigger

        mgr = self._make_manager()
        fired = []

        async def _patched_rollback(strategy, reason, target_files=None):
            fired.append(reason)
            from resilience.auto_rollback import RollbackResult

            return RollbackResult(success=True, strategy=strategy, reason=reason)

        mgr.rollback = _patched_rollback

        trigger = RollbackTrigger(
            name="fire_me",
            condition=lambda: True,
            cooldown_seconds=0.0,
        )
        mgr._triggers = [trigger]
        await mgr._check_triggers()
        assert len(fired) == 1
        assert "fire_me" in fired[0]

    @pytest.mark.asyncio
    async def test_check_triggers_skips_when_condition_false(self):
        from resilience.auto_rollback import RollbackTrigger

        mgr = self._make_manager()
        fired = []

        async def _patched_rollback(strategy, reason, target_files=None):
            fired.append(reason)
            from resilience.auto_rollback import RollbackResult

            return RollbackResult(success=True, strategy=strategy, reason=reason)

        mgr.rollback = _patched_rollback

        trigger = RollbackTrigger(
            name="no_fire",
            condition=lambda: False,
            cooldown_seconds=0.0,
        )
        mgr._triggers = [trigger]
        await mgr._check_triggers()
        assert len(fired) == 0
