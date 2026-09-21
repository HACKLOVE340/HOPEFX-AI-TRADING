# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_nuclear_supervisor_rl.py
========================================
The RL half of `brain/nuclear_supervisor.py`, which was 343 statements at 50.82 %.

`tests/unit/test_nuclear_supervisor.py` covers the rule-based fallback — the
path taken when `stable-baselines3` is missing or the PPO model is absent,
which is what CI runs. The *other* path, taken in production once a model is
trained, was almost entirely unexercised: model loading, VecNormalize, the
observation vector, the severity override, and every degradation branch.

This is the component that can halt trading, so the two things worth stating
plainly are:

* **The severity override is a floor, not a suggestion.** `max(rl_action, ...)`
  means the agent can escalate beyond what severity demands but can never
  de-escalate below it. A model that has drifted, or been swapped for a
  differently-trained one, still cannot talk the supervisor out of halting on a
  severity-9 event. Written as `min`, or as a plain assignment, the whole
  safety property inverts silently.
* **Every dependency is optional and every failure degrades.** The kill switch,
  the risk orchestrator, the notifier, the model, the normaliser — each is
  wrapped in a try/except, so a broken one produces a *quieter* system rather
  than a louder one. Those are exactly the branches that must be proven to
  leave trading halted rather than accidentally resumed.

No model file is ever loaded here: the agent is a stub with a `predict`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

import brain.nuclear_supervisor as ns
from brain.nuclear_supervisor import (
    ACTION_HEDGE,
    ACTION_NORMAL,
    ACTION_NUCLEAR,
    ACTION_PAUSE,
    NuclearHopeFXSupervisor,
    get_nuclear_supervisor,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Detach the supervisor from the kill switch, orchestrator and notifier."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ns, "_kill_switch", None, raising=False)
    monkeypatch.setattr(ns, "_risk_orchestrator", None, raising=False)
    monkeypatch.setattr(ns, "_notifications", None, raising=False)
    monkeypatch.setattr(ns, "_get_kill_switch", lambda: None)
    monkeypatch.setattr(ns, "_get_risk_orchestrator", lambda: None)
    monkeypatch.setattr(ns, "_get_notifications", lambda: None)


@pytest.fixture
def supervisor(isolated, tmp_path):
    return NuclearHopeFXSupervisor(
        model_path=tmp_path / "no-model.zip",
        vecnorm_path=tmp_path / "no-vecnorm.pkl",
        cooldown_seconds=0,
        auto_resume_seconds=0,
    )


def _agent(action):
    """A stand-in PPO whose predict() returns a fixed action."""
    agent = MagicMock()
    agent.predict.return_value = (np.int64(action), None)
    return agent


# ── model loading ─────────────────────────────────────────────────────────────


class TestModelLoading:
    def test_a_missing_model_falls_back_rather_than_raising(self, supervisor):
        assert supervisor.rl_agent is None
        assert supervisor.get_status()["rl_agent_loaded"] is False

    def test_a_missing_vecnorm_is_not_fatal(self, supervisor):
        assert supervisor._vec_normalize is None

    def test_without_stable_baselines_the_agent_is_disabled(self, isolated, tmp_path, monkeypatch):
        monkeypatch.setattr(ns, "_SB3_AVAILABLE", False)
        model = tmp_path / "model.zip"
        model.write_bytes(b"not really a model")

        assert NuclearHopeFXSupervisor(model_path=model).rl_agent is None

    def test_a_present_model_is_loaded_through_ppo(self, isolated, tmp_path, monkeypatch):
        model = tmp_path / "model.zip"
        model.write_bytes(b"stub")
        monkeypatch.setattr(ns, "_SB3_AVAILABLE", True)
        loaded = object()
        monkeypatch.setattr(ns, "PPO", SimpleNamespace(load=lambda path: loaded), raising=False)

        assert NuclearHopeFXSupervisor(model_path=model).rl_agent is loaded

    def test_a_corrupt_model_degrades_to_the_rule_based_path(self, isolated, tmp_path, monkeypatch):
        """A bad artifact must not take the process down — it must halt-capable-degrade."""
        model = tmp_path / "model.zip"
        model.write_bytes(b"corrupt")
        monkeypatch.setattr(ns, "_SB3_AVAILABLE", True)

        def _boom(path):
            raise RuntimeError("bad zip")

        monkeypatch.setattr(ns, "PPO", SimpleNamespace(load=_boom), raising=False)

        assert NuclearHopeFXSupervisor(model_path=model).rl_agent is None

    def test_reload_reports_whether_an_agent_is_now_present(self, supervisor):
        assert supervisor.reload_rl_agent() is False

    def test_reload_picks_up_a_model_written_after_startup(self, supervisor, tmp_path, monkeypatch):
        supervisor._model_path.write_bytes(b"stub")
        monkeypatch.setattr(ns, "_SB3_AVAILABLE", True)
        monkeypatch.setattr(ns, "PPO", SimpleNamespace(load=lambda p: object()), raising=False)

        assert supervisor.reload_rl_agent() is True


# ── observation vector ────────────────────────────────────────────────────────


class TestObservationVector:
    def test_it_is_seven_float32_dimensions(self, supervisor):
        obs = supervisor._build_rl_observation(5, 1.0, 0.0, {}, 0.5)

        assert obs.shape == (7,)
        assert obs.dtype == np.float32

    def test_severity_is_scaled_into_the_unit_interval(self, supervisor):
        assert supervisor._build_rl_observation(10, 1.0, 0.0, {}, 0.0)[0] == pytest.approx(1.0)
        assert supervisor._build_rl_observation(0, 1.0, 0.0, {}, 0.0)[0] == pytest.approx(0.0)

    def test_volatility_is_clipped_at_five(self, supervisor):
        assert supervisor._build_rl_observation(0, 99.0, 0.0, {}, 0.0)[1] == pytest.approx(5.0)

    @pytest.mark.parametrize(("given", "expected"), [(5.0, 1.0), (-5.0, -1.0), (0.25, 0.25)])
    def test_sentiment_is_clipped_to_plus_or_minus_one(self, supervisor, given, expected):
        assert supervisor._build_rl_observation(0, 1.0, given, {}, 0.0)[2] == pytest.approx(expected)

    def test_confidence_defaults_to_a_half_when_the_scorer_omits_it(self, supervisor):
        assert supervisor._build_rl_observation(0, 1.0, 0.0, {}, 0.0)[3] == pytest.approx(0.5)

    def test_confidence_is_read_from_the_scorer_meta(self, supervisor):
        assert supervisor._build_rl_observation(0, 1.0, 0.0, {"confidence": 0.9}, 0.0)[3] == pytest.approx(0.9)

    def test_exposure_is_clipped_to_the_unit_interval(self, supervisor):
        assert supervisor._build_rl_observation(0, 1.0, 0.0, {}, 9.0)[4] == pytest.approx(1.0)

    def test_the_current_level_and_pause_state_are_fed_back(self, supervisor):
        supervisor.nuclear_level = 3
        supervisor.trading_paused = True

        obs = supervisor._build_rl_observation(0, 1.0, 0.0, {}, 0.0)

        assert obs[5] == pytest.approx(1.0)
        assert obs[6] == pytest.approx(1.0)

    def test_every_dimension_is_finite(self, supervisor):
        obs = supervisor._build_rl_observation(10, 99.0, -9.0, {"confidence": 1.0}, 9.0)

        assert np.all(np.isfinite(obs))


class TestNormalizeObs:
    def test_without_a_normaliser_the_vector_passes_through(self, supervisor):
        obs = np.array([1.0] * 7, dtype=np.float32)

        assert np.array_equal(supervisor._normalize_obs(obs), obs)

    def test_the_normaliser_is_given_a_batch_dimension(self, supervisor):
        vecnorm = MagicMock()
        vecnorm.normalize_obs.side_effect = lambda batched: batched * 2
        supervisor._vec_normalize = vecnorm

        result = supervisor._normalize_obs(np.ones(7, dtype=np.float32))

        assert vecnorm.normalize_obs.call_args.args[0].shape == (1, 7)
        assert result.shape == (7,)
        assert result[0] == pytest.approx(2.0)

    def test_a_failing_normaliser_falls_back_to_the_raw_vector(self, supervisor):
        """Stale normaliser statistics must not stop the supervisor deciding."""
        vecnorm = MagicMock()
        vecnorm.normalize_obs.side_effect = RuntimeError("shape mismatch")
        supervisor._vec_normalize = vecnorm
        obs = np.ones(7, dtype=np.float32)

        assert np.array_equal(supervisor._normalize_obs(obs), obs)


# ── the severity override ─────────────────────────────────────────────────────


class TestSeverityOverride:
    @pytest.mark.asyncio
    async def test_the_agent_cannot_de_escalate_a_critical_event(self, supervisor, monkeypatch):
        """The whole safety property: `max`, never `min`."""
        supervisor.rl_agent = _agent(ACTION_NORMAL)
        monkeypatch.setattr(supervisor.scorer, "score_event", lambda *a, **k: (9, "nuclear_mode", 9.0, {}))
        supervisor.trigger_full_nuclear_mode = AsyncMock()

        record = await supervisor.on_new_event({"text": "x"})

        assert record["rl_action"] == "NUCLEAR"
        assert record["action_taken"] == "nuclear"
        supervisor.trigger_full_nuclear_mode.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_severity_seven_floors_the_action_at_hedge(self, supervisor, monkeypatch):
        supervisor.rl_agent = _agent(ACTION_NORMAL)
        monkeypatch.setattr(supervisor.scorer, "score_event", lambda *a, **k: (7, "hedge_mode", 7.0, {}))
        supervisor.trigger_hedge_mode = AsyncMock()

        record = await supervisor.on_new_event({"text": "x"})

        assert record["rl_action"] == "HEDGE"
        supervisor.trigger_hedge_mode.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_severity_five_floors_the_action_at_pause(self, supervisor, monkeypatch):
        supervisor.rl_agent = _agent(ACTION_NORMAL)
        monkeypatch.setattr(supervisor.scorer, "score_event", lambda *a, **k: (5, "pause", 5.0, {}))

        record = await supervisor.on_new_event({"text": "x"})

        assert record["action_taken"] == "pause"
        assert supervisor.trading_paused is True

    @pytest.mark.asyncio
    async def test_the_agent_may_still_escalate_beyond_the_floor(self, supervisor, monkeypatch):
        """The override is a floor, not a clamp."""
        supervisor.rl_agent = _agent(ACTION_NUCLEAR)
        monkeypatch.setattr(supervisor.scorer, "score_event", lambda *a, **k: (5, "pause", 5.0, {}))
        supervisor.trigger_full_nuclear_mode = AsyncMock()

        record = await supervisor.on_new_event({"text": "x"})

        assert record["action_taken"] == "nuclear"

    @pytest.mark.asyncio
    async def test_a_quiet_event_leaves_the_agent_s_choice_alone(self, supervisor, monkeypatch):
        supervisor.rl_agent = _agent(ACTION_NORMAL)
        monkeypatch.setattr(supervisor.scorer, "score_event", lambda *a, **k: (1, "normal", 1.0, {}))

        record = await supervisor.on_new_event({"text": "x"})

        assert record["action_taken"] == "normal"
        assert supervisor.trading_paused is False


# ── the action executor ───────────────────────────────────────────────────────


class TestExecuteAction:
    @pytest.mark.asyncio
    async def test_a_nuclear_action_inside_cooldown_is_suppressed(self, supervisor):
        supervisor.trigger_full_nuclear_mode = AsyncMock()

        result = await supervisor._execute_action(ACTION_NUCLEAR, severity=8, in_cooldown=True)

        assert result == "nuclear_cooldown_suppressed"
        supervisor.trigger_full_nuclear_mode.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_severity_nine_overrides_the_cooldown(self, supervisor):
        """Cooldown exists to stop flapping, not to swallow a real emergency."""
        supervisor.trigger_full_nuclear_mode = AsyncMock()

        result = await supervisor._execute_action(ACTION_NUCLEAR, severity=9, in_cooldown=True)

        assert result == "nuclear"
        assert supervisor.nuclear_level == 3
        supervisor.trigger_full_nuclear_mode.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_hedge_inside_cooldown_is_suppressed(self, supervisor):
        supervisor.trigger_hedge_mode = AsyncMock()

        result = await supervisor._execute_action(ACTION_HEDGE, severity=6, in_cooldown=True)

        assert result == "hedge_cooldown_suppressed"
        supervisor.trigger_hedge_mode.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_severity_seven_overrides_the_hedge_cooldown(self, supervisor):
        supervisor.trigger_hedge_mode = AsyncMock()

        result = await supervisor._execute_action(ACTION_HEDGE, severity=7, in_cooldown=True)

        assert result == "hedge"
        assert supervisor.nuclear_level == 2

    @pytest.mark.asyncio
    async def test_a_pause_never_lowers_an_existing_level(self, supervisor):
        supervisor.nuclear_level = 3

        await supervisor._execute_action(ACTION_PAUSE, severity=5, in_cooldown=False)

        assert supervisor.nuclear_level == 3
        assert supervisor.trading_paused is True

    @pytest.mark.asyncio
    async def test_de_escalation_steps_down_one_level_at_a_time(self, supervisor):
        """A single quiet headline must not clear a nuclear state outright."""
        supervisor.nuclear_level = 3

        await supervisor._execute_action(ACTION_NORMAL, severity=1, in_cooldown=False)

        assert supervisor.nuclear_level == 2
        assert supervisor.trading_paused is False or supervisor.nuclear_level > 0

    @pytest.mark.asyncio
    async def test_reaching_level_zero_unpauses_trading(self, supervisor):
        supervisor.nuclear_level = 1
        supervisor.trading_paused = True

        await supervisor._execute_action(ACTION_NORMAL, severity=1, in_cooldown=False)

        assert supervisor.nuclear_level == 0
        assert supervisor.trading_paused is False

    @pytest.mark.asyncio
    async def test_a_still_elevated_severity_does_not_de_escalate(self, supervisor):
        supervisor.nuclear_level = 2

        await supervisor._execute_action(ACTION_NORMAL, severity=4, in_cooldown=False)

        assert supervisor.nuclear_level == 2


# ── auto-resume ───────────────────────────────────────────────────────────────


class TestAutoResume:
    @pytest.mark.asyncio
    async def test_it_is_off_when_the_window_is_zero(self, supervisor):
        supervisor.trading_paused = True
        supervisor.nuclear_level = 1
        supervisor._pause_since_ts = 1.0

        await supervisor._maybe_auto_resume()

        assert supervisor.trading_paused is True

    @pytest.mark.asyncio
    async def test_a_long_enough_pause_resumes(self, isolated, tmp_path):
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip", auto_resume_seconds=1, cooldown_seconds=0)
        s.trading_paused = True
        s.nuclear_level = 1
        s._pause_since_ts = 1.0  # far in the past on the monotonic clock

        await s._maybe_auto_resume()

        assert s.trading_paused is False
        assert s.nuclear_level == 0

    @pytest.mark.asyncio
    async def test_a_nuclear_state_never_auto_resumes(self, isolated, tmp_path):
        """Only a level at or below PAUSE may clear itself. Level 3 needs a human."""
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip", auto_resume_seconds=1, cooldown_seconds=0)
        s.trading_paused = True
        s.nuclear_level = 3
        s._pause_since_ts = 1.0

        await s._maybe_auto_resume()

        assert s.trading_paused is True
        assert s.nuclear_level == 3

    @pytest.mark.asyncio
    async def test_an_unpaused_supervisor_is_left_alone(self, isolated, tmp_path):
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip", auto_resume_seconds=1)
        s.trading_paused = False
        s._pause_since_ts = 1.0

        await s._maybe_auto_resume()

        assert s.nuclear_level == 0

    @pytest.mark.asyncio
    async def test_resuming_announces_itself(self, isolated, tmp_path, monkeypatch):
        notif = MagicMock()
        notif.send_critical_alert = AsyncMock()
        monkeypatch.setattr(ns, "_get_notifications", lambda: notif)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip", auto_resume_seconds=1)
        s.trading_paused = True
        s.nuclear_level = 1
        s._pause_since_ts = 1.0

        await s._maybe_auto_resume()

        notif.send_critical_alert.assert_awaited_once()


# ── nuclear and hedge triggers ────────────────────────────────────────────────


class TestTriggerNuclearMode:
    @pytest.mark.asyncio
    async def test_it_activates_the_kill_switch_and_zeroes_risk(self, isolated, tmp_path, monkeypatch):
        ks, ro = MagicMock(), MagicMock()
        ro.set_max_risk = AsyncMock()
        monkeypatch.setattr(ns, "_get_kill_switch", lambda: ks)
        monkeypatch.setattr(ns, "_get_risk_orchestrator", lambda: ro)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")
        s._monitoring_task_running = True  # do not spawn the heartbeat loop

        await s.trigger_full_nuclear_mode()

        ks.activate.assert_called_once()
        ro.set_max_risk.assert_awaited_once_with(0.0)
        assert s.trading_paused is True
        assert s._monitoring_only is True

    @pytest.mark.asyncio
    async def test_a_failing_kill_switch_still_zeroes_risk(self, isolated, tmp_path, monkeypatch):
        """Belt and braces: if one block fails the other must still be applied."""
        ks, ro = MagicMock(), MagicMock()
        ks.activate.side_effect = RuntimeError("redis down")
        ro.set_max_risk = AsyncMock()
        monkeypatch.setattr(ns, "_get_kill_switch", lambda: ks)
        monkeypatch.setattr(ns, "_get_risk_orchestrator", lambda: ro)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")
        s._monitoring_task_running = True

        await s.trigger_full_nuclear_mode()

        ro.set_max_risk.assert_awaited_once_with(0.0)
        assert s.trading_paused is True

    @pytest.mark.asyncio
    async def test_no_kill_switch_at_all_still_pauses_trading(self, supervisor):
        supervisor._monitoring_task_running = True

        await supervisor.trigger_full_nuclear_mode()

        assert supervisor.trading_paused is True
        assert supervisor._monitoring_only is True

    @pytest.mark.asyncio
    async def test_a_failing_notifier_does_not_undo_the_halt(self, isolated, tmp_path, monkeypatch):
        notif = MagicMock()
        notif.send_critical_alert = AsyncMock(side_effect=RuntimeError("smtp down"))
        monkeypatch.setattr(ns, "_get_notifications", lambda: notif)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")
        s._monitoring_task_running = True

        await s.trigger_full_nuclear_mode()

        assert s.trading_paused is True


class TestTriggerHedgeMode:
    @pytest.mark.asyncio
    async def test_it_cuts_risk_and_opens_a_hedge(self, isolated, tmp_path, monkeypatch):
        ro = MagicMock()
        ro.set_max_risk = AsyncMock()
        ro.activate_hedge_mode = AsyncMock()
        monkeypatch.setattr(ns, "_get_risk_orchestrator", lambda: ro)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")

        await s.trigger_hedge_mode()

        ro.set_max_risk.assert_awaited_once_with(0.15)
        ro.activate_hedge_mode.assert_awaited_once_with(symbol="XAU_USD")

    @pytest.mark.asyncio
    async def test_a_failing_orchestrator_is_survivable(self, isolated, tmp_path, monkeypatch):
        ro = MagicMock()
        ro.set_max_risk = AsyncMock(side_effect=RuntimeError("bus down"))
        monkeypatch.setattr(ns, "_get_risk_orchestrator", lambda: ro)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")

        await s.trigger_hedge_mode()  # must not raise

    @pytest.mark.asyncio
    async def test_with_no_orchestrator_it_is_a_no_op(self, supervisor):
        await supervisor.trigger_hedge_mode()  # must not raise


# ── manual resume ─────────────────────────────────────────────────────────────


class TestManualResume:
    @pytest.mark.asyncio
    async def test_it_clears_every_piece_of_nuclear_state(self, supervisor):
        supervisor.nuclear_level = 3
        supervisor.trading_paused = True
        supervisor._monitoring_only = True
        supervisor._pause_since_ts = 5.0
        supervisor._last_trigger_ts = 5.0

        await supervisor.manual_resume()

        assert supervisor.nuclear_level == 0
        assert supervisor.trading_paused is False
        assert supervisor._monitoring_only is False
        assert supervisor._pause_since_ts == 0.0
        assert supervisor._last_trigger_ts == 0.0

    @pytest.mark.asyncio
    async def test_the_deactivation_token_is_passed_to_the_kill_switch(self, isolated, tmp_path, monkeypatch):
        ks = MagicMock()
        ks.is_active.return_value = True
        monkeypatch.setattr(ns, "_get_kill_switch", lambda: ks)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")

        await s.manual_resume(deactivation_token="secret")

        ks.deactivate.assert_called_once_with(token="secret")

    @pytest.mark.asyncio
    async def test_a_refused_deactivation_aborts_the_resume(self, isolated, tmp_path, monkeypatch):
        """If the kill switch will not clear, trading must not be told it is back.

        Returning early here is the difference between a halted system and one
        that believes it is live while every order path is still blocked.
        """
        ks = MagicMock()
        ks.is_active.return_value = True
        ks.deactivate.side_effect = PermissionError("token required")
        ro = MagicMock()
        ro.set_max_risk = AsyncMock()
        monkeypatch.setattr(ns, "_get_kill_switch", lambda: ks)
        monkeypatch.setattr(ns, "_get_risk_orchestrator", lambda: ro)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")

        await s.manual_resume()

        ro.set_max_risk.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_inactive_kill_switch_is_not_deactivated_again(self, isolated, tmp_path, monkeypatch):
        ks = MagicMock()
        ks.is_active.return_value = False
        monkeypatch.setattr(ns, "_get_kill_switch", lambda: ks)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")

        await s.manual_resume()

        ks.deactivate.assert_not_called()

    @pytest.mark.asyncio
    async def test_it_restores_the_full_risk_budget_and_closes_hedges(self, isolated, tmp_path, monkeypatch):
        ro = MagicMock()
        ro.set_max_risk = AsyncMock()
        ro.deactivate_hedge_mode = AsyncMock()
        monkeypatch.setattr(ns, "_get_risk_orchestrator", lambda: ro)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")

        await s.manual_resume()

        ro.set_max_risk.assert_awaited_once_with(1.0)
        ro.deactivate_hedge_mode.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_failing_notifier_does_not_block_the_resume(self, isolated, tmp_path, monkeypatch):
        notif = MagicMock()
        notif.send_info = AsyncMock(side_effect=RuntimeError("smtp down"))
        monkeypatch.setattr(ns, "_get_notifications", lambda: notif)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")
        s.nuclear_level = 2

        await s.manual_resume()

        assert s.nuclear_level == 0


# ── audit trail and status ────────────────────────────────────────────────────


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_every_event_is_recorded(self, supervisor):
        await supervisor.on_new_event({"text": "quiet day"})
        await supervisor.on_new_event({"text": "another quiet day"})

        assert len(supervisor.get_event_history()) == 2

    @pytest.mark.asyncio
    async def test_the_record_carries_the_inputs_and_the_decision(self, supervisor):
        record = await supervisor.on_new_event(
            {"text": "quiet", "volatility": 2.0, "sentiment": -0.5, "current_exposure": 0.25}
        )

        assert record["vol"] == pytest.approx(2.0)
        assert record["sentiment"] == pytest.approx(-0.5)
        assert record["exposure"] == pytest.approx(0.25)
        assert "action_taken" in record

    @pytest.mark.asyncio
    async def test_the_rule_based_path_records_no_rl_action(self, supervisor):
        record = await supervisor.on_new_event({"text": "quiet"})

        assert record["rl_action"] == "N/A"

    @pytest.mark.asyncio
    async def test_matched_terms_are_capped_at_five(self, supervisor, monkeypatch):
        """The audit trail must stay bounded; a keyword-stuffed article is a DoS otherwise."""
        meta = {"matched_terms": [{"term": f"t{i}"} for i in range(50)]}
        monkeypatch.setattr(supervisor.scorer, "score_event", lambda *a, **k: (1, "normal", 1.0, meta))

        record = await supervisor.on_new_event({"text": "x"})

        assert len(record["matched_terms"]) == 5

    @pytest.mark.asyncio
    async def test_the_history_window_is_honoured(self, supervisor):
        for i in range(10):
            await supervisor.on_new_event({"text": f"event {i}"})

        assert len(supervisor.get_event_history(n=3)) == 3

    @pytest.mark.asyncio
    async def test_an_event_with_no_text_is_handled(self, supervisor):
        record = await supervisor.on_new_event({})

        assert record["severity"] == 0


class TestStatus:
    def test_it_reports_a_clean_initial_state(self, supervisor):
        status = supervisor.get_status()

        assert status["nuclear_level"] == 0
        assert status["trading_paused"] is False
        assert status["monitoring_only"] is False
        assert status["event_history_count"] == 0
        assert status["last_event"] is None

    def test_the_kill_switch_fields_are_none_when_it_is_absent(self, supervisor):
        status = supervisor.get_status()

        assert status["kill_switch_active"] is None
        assert status["kill_switch_reason"] is None

    def test_the_kill_switch_state_is_surfaced_when_present(self, isolated, tmp_path, monkeypatch):
        ks = MagicMock()
        ks.is_active.return_value = True
        ks.reason = "nuclear event"
        monkeypatch.setattr(ns, "_get_kill_switch", lambda: ks)
        s = NuclearHopeFXSupervisor(model_path=tmp_path / "none.zip")

        status = s.get_status()

        assert status["kill_switch_active"] is True
        assert status["kill_switch_reason"] == "nuclear event"

    def test_the_cooldown_remaining_is_never_negative(self, supervisor):
        assert supervisor.get_status()["cooldown_remaining"] >= 0.0

    @pytest.mark.asyncio
    async def test_the_last_event_is_surfaced(self, supervisor):
        await supervisor.on_new_event({"text": "quiet day"})

        assert supervisor.get_status()["last_event"]["action_taken"] == "normal"


# ── lazy dependency resolution ────────────────────────────────────────────────


class TestLazyImports:
    def test_the_kill_switch_is_resolved_and_cached(self, monkeypatch):
        monkeypatch.setattr(ns, "_kill_switch", None, raising=False)

        first = ns._get_kill_switch()
        second = ns._get_kill_switch()

        assert first is second

    def test_a_failing_kill_switch_import_returns_none_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(ns, "_kill_switch", None, raising=False)
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def _no_kill_switch(name, *args, **kwargs):
            if name == "kill_switch":
                raise ImportError("gone")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", _no_kill_switch):
            assert ns._get_kill_switch() is None

    def test_the_risk_orchestrator_is_resolved_and_cached(self, monkeypatch):
        monkeypatch.setattr(ns, "_risk_orchestrator", None, raising=False)

        assert ns._get_risk_orchestrator() is ns._get_risk_orchestrator()

    def test_a_failing_orchestrator_import_returns_none(self, monkeypatch):
        monkeypatch.setattr(ns, "_risk_orchestrator", None, raising=False)
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def _no_orchestrator(name, *args, **kwargs):
            if name == "risk.orchestrator":
                raise ImportError("gone")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", _no_orchestrator):
            assert ns._get_risk_orchestrator() is None

    def test_the_notifier_is_resolved_and_cached(self, monkeypatch):
        monkeypatch.setattr(ns, "_notifications", None, raising=False)

        assert ns._get_notifications() is ns._get_notifications()


class TestSupervisorSingleton:
    def test_it_is_shared(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ns, "_supervisor_instance", None, raising=False)
        monkeypatch.chdir(tmp_path)

        assert get_nuclear_supervisor() is get_nuclear_supervisor()

    def test_the_action_names_cover_every_action_constant(self):
        assert set(ns._ACTION_NAMES) == {ACTION_NORMAL, ACTION_PAUSE, ACTION_HEDGE, ACTION_NUCLEAR}

    def test_the_action_constants_are_ordered_by_severity(self):
        """`max(rl_action, floor)` is only a safety floor if the ordering holds."""
        assert ACTION_NORMAL < ACTION_PAUSE < ACTION_HEDGE < ACTION_NUCLEAR
