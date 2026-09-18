# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/train_rl_nuclear.py` — the trainer for the nuclear escalation agent.

The agent this trains maps a 7-dim observation to one of four actions: NORMAL,
PAUSE, HEDGE, NUCLEAR. NUCLEAR is full liquidation plus a trading halt, so the
reward function in this file is the specification of when the platform should
pull that lever. It is domain logic, not plumbing, and it measured 14%.

**What is and is not stubbed here.** `gymnasium` and `stable-baselines3` are not
installed — sb3 needs PyTorch, which `requirements-ci.txt` deliberately omits —
and `NuclearDecisionEnv` is defined inside `if _GYM_AVAILABLE:`, so with the
real imports the class does not exist to be tested at all. These tests load the
module a second time with both libraries stubbed.

That stub buys two different things, and they are worth separating:

  * For `NuclearDecisionEnv`, it buys nothing false. The reward function, the
    escalation state machine and the observation sampler call into gymnasium
    exactly twice — for a base class and for two space descriptors. Every
    assertion below is on this repository's own arithmetic.
  * For `train()` and `walk_forward_train()`, it verifies *wiring*: which
    objects are constructed with which parameters, what is saved where, and in
    what order. It does not verify that PPO learns anything, and no test here
    should be read as saying it does.

`np_random` is stubbed as a real `numpy.random.Generator` seeded from
`reset(seed=...)`, which is gymnasium's own contract, so the reproducibility
tests mean what they say.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import pathlib
import sys
import types
from typing import Any

import numpy as np
import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MODULE_PATH = REPO / "ml" / "train_rl_nuclear.py"

# Action codes, as the module's docstring defines them.
NORMAL, PAUSE, HEDGE, NUCLEAR = 0, 1, 2, 3


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _Box:
    def __init__(self, low: Any, high: Any, dtype: Any = None) -> None:
        self.low, self.high, self.dtype = low, high, dtype


class _Discrete:
    def __init__(self, n: int) -> None:
        self.n = n


class _Env:
    """The two pieces of `gymnasium.Env` this module actually uses."""

    def __init__(self) -> None:
        self._np_random: np.random.Generator | None = None

    @property
    def np_random(self) -> np.random.Generator:
        if self._np_random is None:
            self._np_random = np.random.default_rng()
        return self._np_random

    def reset(self, *, seed: int | None = None, options: Any = None) -> None:
        if seed is not None:
            self._np_random = np.random.default_rng(seed)
        elif self._np_random is None:
            self._np_random = np.random.default_rng()


class Recorder:
    """Everything the training functions did, in the order they did it."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def record(self, name: str, payload: Any = None) -> None:
        self.events.append((name, payload))

    def of(self, name: str) -> list[Any]:
        return [payload for event, payload in self.events if event == name]

    def names(self) -> list[str]:
        return [event for event, _ in self.events]


def _make_sb3(recorder: Recorder) -> dict[str, types.ModuleType]:
    class _Model:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            recorder.record("PPO", kwargs)

        def learn(self, **kwargs: Any) -> None:
            recorder.record("learn", kwargs)

        def save(self, path: str) -> None:
            recorder.record("save", path)
            target = pathlib.Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"a saved policy")

        def predict(self, obs: Any, deterministic: bool = False) -> tuple[Any, None]:
            """Shaped as stable-baselines3 shapes it.

            `BasePolicy.predict` squeezes the batch axis when the observation
            is not vectorised, so a raw env gets a 0-d array and a VecEnv gets
            one entry per environment. `walk_forward_train` calls `int(action)`
            on the result, which only works for the 0-d case — a fake that
            returned a 1-element array either way would hide that.
            """
            recorder.record("predict", deterministic)
            batched = np.asarray(obs).ndim > 1
            return (np.array([NUCLEAR]) if batched else np.array(NUCLEAR)), None

        @staticmethod
        def load(path: str) -> _Model:
            recorder.record("load", path)
            return _Model()

    class _VecEnv:
        """Calls each factory, as DummyVecEnv does — so `make_env` runs."""

        def __init__(self, env_fns: list[Any]) -> None:
            self.envs = [fn() for fn in env_fns]
            recorder.record("DummyVecEnv", len(self.envs))

    class _VecNormalize:
        def __init__(self, venv: Any, **kwargs: Any) -> None:
            self.venv = venv
            self.kwargs = kwargs
            self._steps = 0
            recorder.record("VecNormalize", kwargs)

        def save(self, path: str) -> None:
            recorder.record("vecnorm_save", path)
            target = pathlib.Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"normalisation stats")

        def reset(self) -> Any:
            recorder.record("vec_reset")
            return np.zeros((1, 7), dtype=np.float32)

        def step(self, action: Any) -> tuple[Any, Any, Any, Any]:
            self._steps += 1
            done = self._steps % 200 == 0  # exercise the episode-boundary branch
            return np.zeros((1, 7), dtype=np.float32), np.array([0.5]), np.array([done]), [{}]

    def _callback(name: str) -> Any:
        class _Callback:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.args, self.kwargs = args, kwargs
                recorder.record(name, kwargs)

        return _Callback

    def _check_env(env: Any, warn: bool = False) -> None:
        recorder.record("check_env", type(env).__name__)

    def _monitor(env: Any) -> Any:
        recorder.record("Monitor", type(env).__name__)
        return env

    sb3 = types.ModuleType("stable_baselines3")
    sb3.PPO = _Model  # type: ignore[attr-defined]
    common = types.ModuleType("stable_baselines3.common")
    callbacks = types.ModuleType("stable_baselines3.common.callbacks")
    callbacks.CheckpointCallback = _callback("CheckpointCallback")  # type: ignore[attr-defined]
    callbacks.EvalCallback = _callback("EvalCallback")  # type: ignore[attr-defined]
    callbacks.StopTrainingOnRewardThreshold = _callback("StopTrainingOnRewardThreshold")  # type: ignore[attr-defined]
    env_checker = types.ModuleType("stable_baselines3.common.env_checker")
    env_checker.check_env = _check_env  # type: ignore[attr-defined]
    monitor = types.ModuleType("stable_baselines3.common.monitor")
    monitor.Monitor = _monitor  # type: ignore[attr-defined]
    vec_env = types.ModuleType("stable_baselines3.common.vec_env")
    vec_env.DummyVecEnv = _VecEnv  # type: ignore[attr-defined]
    vec_env.VecNormalize = _VecNormalize  # type: ignore[attr-defined]

    return {
        "stable_baselines3": sb3,
        "stable_baselines3.common": common,
        "stable_baselines3.common.callbacks": callbacks,
        "stable_baselines3.common.env_checker": env_checker,
        "stable_baselines3.common.monitor": monitor,
        "stable_baselines3.common.vec_env": vec_env,
    }


def _make_gym() -> dict[str, types.ModuleType]:
    spaces = types.ModuleType("gymnasium.spaces")
    spaces.Box = _Box  # type: ignore[attr-defined]
    spaces.Discrete = _Discrete  # type: ignore[attr-defined]
    gym = types.ModuleType("gymnasium")
    gym.Env = _Env  # type: ignore[attr-defined]
    gym.spaces = spaces  # type: ignore[attr-defined]
    return {"gymnasium": gym, "gymnasium.spaces": spaces}


@contextlib.contextmanager
def _stubs_installed(recorder: Recorder) -> Any:
    """Put the stub libraries in `sys.modules` for the duration of a test.

    They have to stay there for the whole test, not only for the import:
    `walk_forward_train` does its own `from stable_baselines3 import PPO` at
    call time, which is a second import several steps after module load.
    Everything is restored on the way out, so `ml.train_rl_nuclear` — which
    other tests import with the real (absent) libraries — is unaffected.
    """
    stubs = {**_make_gym(), **_make_sb3(recorder)}
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        yield
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def trainer(recorder: Recorder) -> Any:
    """The trainer loaded with both libraries present.

    Loaded under a private module name so the real `ml.train_rl_nuclear` is
    left alone. Coverage keys on the file, so both loads count toward it.
    """
    with _stubs_installed(recorder):
        spec = importlib.util.spec_from_file_location("_train_rl_nuclear_stubbed", MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module


@pytest.fixture
def env(trainer: Any) -> Any:
    instance = trainer.NuclearDecisionEnv(episode_length=200)
    instance.reset(seed=1234)
    return instance


# ---------------------------------------------------------------------------
# What the module says about itself
# ---------------------------------------------------------------------------


class TestTheModuleContract:
    def test_the_observation_width_matches_the_supervisor_that_feeds_it(self) -> None:
        """The docstring says this vector "matches `_build_rl_observation` in
        nuclear_supervisor.py". Two shapes that must agree and live in
        different files is exactly the pair that drifts — and a mismatch is not
        a crash, it is a policy reading somebody else's numbers.

        Built for real from `brain/nuclear_supervisor.py`, not compared as text.
        """
        import ml.train_rl_nuclear as real
        from brain.nuclear_supervisor import NuclearHopeFXSupervisor

        observation = NuclearHopeFXSupervisor._build_rl_observation(
            types.SimpleNamespace(nuclear_level=0, trading_paused=False),
            severity=9,
            vol=1.2,
            sentiment=-0.5,
            meta={"confidence": 0.8},
            current_exposure=0.4,
        )
        assert observation.shape == (real.OBS_DIM,)
        assert observation.dtype == np.float32

    def test_there_are_four_actions_because_there_are_four_escalation_levels(self) -> None:
        import ml.train_rl_nuclear as real

        assert real.N_ACTIONS == 4

    def test_it_is_a_training_script_not_a_production_import(self) -> None:
        """Its own docstring: "TRAINING SCRIPT ONLY — not imported by any
        production path." Checked rather than trusted, because an import from a
        serving path would pull gymnasium and stable-baselines3 — and therefore
        PyTorch — into production.

        Two production files mention it by name and neither imports it:
        `brain/nuclear_supervisor.py:235` names it in the log line that tells
        an operator how to train the missing model, and
        `security/global_fortress.py:59` names it in the comment tying its
        action constants to this action space. So the test looks for import
        statements rather than for the string.
        """
        import re
        import subprocess  # nosec B404 - fixed args, repo grep

        result = subprocess.run(  # nosec B603 B607
            ["git", "grep", "-l", "train_rl_nuclear", "--", "*.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        pattern = re.compile(r"^\s*(?:from|import)\s+\S*train_rl_nuclear", re.MULTILINE)
        importers = set()
        for name in result.stdout.split():
            if not name or name == "ml/train_rl_nuclear.py" or name.startswith("tests/"):
                continue
            if pattern.search((REPO / name).read_text()):
                importers.add(name)
        assert importers == set(), f"production code imports the trainer: {importers}"

    def test_the_fortress_action_constants_match_this_action_space(self) -> None:
        """`security/global_fortress.py:59` says its constants "must match
        train_rl_nuclear.py action space". They are named for a different
        domain — MONITOR, RATE_LIMIT, BLOCK, NUCLEAR against NORMAL, PAUSE,
        HEDGE, NUCLEAR — so the only thing that can be checked is the one thing
        that matters: the same four codes, with NUCLEAR at the same value."""
        import ml.train_rl_nuclear as real
        from security import global_fortress

        codes = [
            global_fortress.ACTION_MONITOR,
            global_fortress.ACTION_RATE_LIMIT,
            global_fortress.ACTION_BLOCK,
            global_fortress.ACTION_NUCLEAR,
        ]
        assert codes == [NORMAL, PAUSE, HEDGE, NUCLEAR]
        assert len(codes) == real.N_ACTIONS
        assert global_fortress.ACTION_NUCLEAR == NUCLEAR

    def test_the_docstring_declares_no_constants_that_do_not_exist(self) -> None:
        """This module used to open its docstring with a block headed "Module
        constants" — `_RL_LEARNING_RATE = 0.05`, `_RL_DISCOUNT = 0.15` and six
        others. They were inside the triple-quoted string, so none of them was
        a module attribute and nothing in the repository referenced any of
        them. The real PPO learning rate is 3e-4 and gamma is 0.99, so anyone
        tuning the numbers at the top of this file changed nothing while
        believing they had changed the agent. The block is gone; this test
        stops one coming back.

        The same pattern is still live in `ml/signal_filter.py` (thirteen
        inert constants, including `_RSI_OVERBOUGHT` and
        `_DEFAULT_CONFIDENCE_THRESHOLD`) and `brokers/prop_firms/all_brokers.py`
        (three, including `_MAX_LEVERAGE`). Neither is fixed here: editing
        `signal_filter.py` at 77% trips the coverage ratchet, which is the
        ratchet doing its job.
        """
        import re

        import ml.train_rl_nuclear as real

        declared = re.findall(r"^(_?[A-Z][A-Z0-9_]*)\s*=", real.__doc__ or "", re.MULTILINE)
        assert declared == [], f"the docstring declares constants that do not exist: {declared}"

    def test_the_numbers_a_reader_would_tune_are_the_ones_ppo_receives(self) -> None:
        """The counterpart to the test above: the hyperparameters live in
        `train()` and nowhere else, so there is one place to change them."""
        source = MODULE_PATH.read_text()
        assert "learning_rate=3e-4" in source
        assert "gamma=0.99" in source

    def test_the_save_paths_are_relative_to_the_working_directory(self) -> None:
        """Also a finding. `MODEL_SAVE_PATH` and the per-fold paths are
        relative, so where the trained model lands depends on where the
        trainer was invoked from, not on the repository."""
        import ml.train_rl_nuclear as real

        assert not real.MODEL_SAVE_PATH.is_absolute()
        assert not real.VECNORM_SAVE_PATH.is_absolute()
        assert str(real.MODEL_SAVE_PATH) == "ml/rl_models/nuclear_decision_ppo.zip"


# ---------------------------------------------------------------------------
# Refusal paths — what happens with no libraries, which is CI's situation
# ---------------------------------------------------------------------------


class TestTrainingRefusesWithoutItsLibraries:
    """CI has neither gymnasium nor stable-baselines3, so this is the only
    branch of `train()` that runs there. It must refuse loudly and return —
    not raise, and above all not proceed to write a model file."""

    def test_train_refuses_and_says_what_to_install(self, caplog) -> None:
        import ml.train_rl_nuclear as real

        with caplog.at_level(logging.ERROR, logger="ml.train_rl_nuclear"):
            assert real.train() is None
        assert "pip install gymnasium stable-baselines3" in caplog.text

    def test_walk_forward_refuses_too(self, caplog) -> None:
        import ml.train_rl_nuclear as real

        with caplog.at_level(logging.ERROR, logger="ml.train_rl_nuclear"):
            assert real.walk_forward_train() is None
        assert "required" in caplog.text

    def test_a_refusal_writes_nothing(self, tmp_path, monkeypatch) -> None:
        """The failure that would matter: a refused training run that still
        touches the production model path."""
        import ml.train_rl_nuclear as real

        monkeypatch.chdir(tmp_path)
        real.train()
        real.walk_forward_train()
        assert not (tmp_path / "ml").exists()

    def test_a_refusal_does_not_raise_into_the_shell(self) -> None:
        """`scripts/retrain.sh` reads exit codes. A traceback and a clean
        refusal are different things to a shell script."""
        import ml.train_rl_nuclear as real

        assert real.train(total_timesteps=1) is None

    @pytest.mark.parametrize("gym_ok,sb3_ok", [(False, False), (True, False), (False, True)])
    def test_either_library_missing_is_enough_to_refuse(self, monkeypatch, gym_ok: bool, sb3_ok: bool, caplog) -> None:
        """Half the stack is not a usable stack. Pinned because the guard is an
        `or` and an `and` there would try to train with one of them absent."""
        import ml.train_rl_nuclear as real

        monkeypatch.setattr(real, "_GYM_AVAILABLE", gym_ok)
        monkeypatch.setattr(real, "_SB3_AVAILABLE", sb3_ok)
        with caplog.at_level(logging.ERROR, logger="ml.train_rl_nuclear"):
            assert real.train() is None
            assert real.walk_forward_train() is None
        assert caplog.text != ""

    def test_with_both_present_it_does_not_refuse(self, trainer, recorder, tmp_path, monkeypatch) -> None:
        """The other side of the same guard — otherwise every test above passes
        against a `train()` that refuses unconditionally."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(trainer, "LOG_DIR", tmp_path / "logs")
        trainer.train(total_timesteps=10, save_path=tmp_path / "model.zip")
        assert recorder.of("learn"), "training was refused with both libraries available"


# ---------------------------------------------------------------------------
# The reward function — the specification of when to pull the nuclear lever
# ---------------------------------------------------------------------------


def _reward(env: Any, action: int, severity: float, vol: float = 1.0, exposure: float = 0.0) -> float:
    """Reward with every stochastic term suppressed.

    The random P&L term fires only when the agent is unpaused *and* severity is
    below 5; the drawdown term is zero while equity is at its peak, which it is
    immediately after a reset. So for severity >= 5 on a fresh episode the
    figure is exact, and the tests below can assert equality rather than a band.
    """
    return env._compute_reward(action, severity, vol, exposure)


class TestTheRewardForACriticalEvent:
    """Severity >= 9. The agent is meant to liquidate."""

    @pytest.mark.parametrize("severity", [9.0, 9.5, 10.0])
    def test_going_nuclear_is_rewarded(self, env: Any, severity: float) -> None:
        assert _reward(env, NUCLEAR, severity) == 5.0

    @pytest.mark.parametrize("severity", [9.0, 9.9])
    def test_staying_normal_is_penalised_the_same_amount(self, env: Any, severity: float) -> None:
        assert _reward(env, NORMAL, severity) == -5.0

    def test_nuclear_is_the_strictly_best_action(self, env: Any) -> None:
        """The property the whole reward function exists to produce. Asserted
        as an ordering rather than as four separate numbers, because it is the
        ordering the policy learns."""
        rewards = {action: _reward(env, action, 9.5) for action in (NORMAL, PAUSE, HEDGE, NUCLEAR)}
        assert rewards[NUCLEAR] > rewards[HEDGE]
        assert rewards[NUCLEAR] > rewards[PAUSE]
        assert rewards[HEDGE] > rewards[NORMAL]

    def test_high_exposure_makes_inaction_worse(self, env: Any) -> None:
        """Doing nothing with the book fully loaded costs more than doing
        nothing flat."""
        assert _reward(env, NORMAL, 9.0, exposure=1.0) < _reward(env, NORMAL, 9.0, exposure=0.0)

    def test_the_exposure_penalty_scales_with_both_exposure_and_severity(self, env: Any) -> None:
        assert _reward(env, NORMAL, 9.0, exposure=1.0) == pytest.approx(-5.0 - 1.0 * 9.0 * 0.1)
        assert _reward(env, NORMAL, 10.0, exposure=0.8) == pytest.approx(-5.0 - 0.8 * 10.0 * 0.1)

    def test_exposure_at_half_is_not_yet_penalised(self, env: Any) -> None:
        """The condition is `> 0.5`, so half the book is the boundary. Pinned
        so it is a decision."""
        assert _reward(env, NORMAL, 9.0, exposure=0.5) == -5.0
        assert _reward(env, NORMAL, 9.0, exposure=0.51) < -5.0

    def test_hedging_a_critical_event_earns_nothing(self, env: Any) -> None:
        """A gap in the shaping, pinned rather than changed: the hedge bonus
        band is `7 <= severity < 9`, so hedging at 9 and above is neither
        rewarded nor punished. It still beats NORMAL by 5, so the ordering
        holds — but the agent is told nothing about hedging versus going
        nuclear on the worst events."""
        assert _reward(env, HEDGE, 9.0) == 0.0
        assert _reward(env, HEDGE, 8.99) == 2.0


class TestTheRewardForAnElevatedEvent:
    """7 <= severity < 9. The agent is meant to hedge."""

    @pytest.mark.parametrize("severity", [7.0, 8.0, 8.99])
    def test_hedging_is_rewarded(self, env: Any, severity: float) -> None:
        assert _reward(env, HEDGE, severity) == 2.0

    def test_staying_normal_is_penalised_but_less_than_at_critical(self, env: Any) -> None:
        assert _reward(env, NORMAL, 8.0) == -2.0
        assert _reward(env, NORMAL, 8.0) > _reward(env, NORMAL, 9.0)

    def test_hedging_is_the_best_action(self, env: Any) -> None:
        rewards = {action: _reward(env, action, 8.0) for action in (NORMAL, PAUSE, HEDGE, NUCLEAR)}
        assert rewards[HEDGE] == max(rewards.values())

    def test_severity_seven_is_the_boundary(self, env: Any) -> None:
        assert _reward(env, HEDGE, 7.0) == 2.0
        assert _reward(env, HEDGE, 6.99) == 0.0
        assert _reward(env, NORMAL, 7.0) == -2.0
        assert _reward(env, NORMAL, 6.99) == 0.0


class TestTheRewardForAModerateEvent:
    """5 <= severity < 7. The agent is meant to pause."""

    @pytest.mark.parametrize("severity", [5.0, 6.0, 6.99])
    def test_pausing_is_rewarded(self, env: Any, severity: float) -> None:
        assert _reward(env, PAUSE, severity) == 1.0

    def test_pausing_is_the_best_action(self, env: Any) -> None:
        rewards = {action: _reward(env, action, 6.0) for action in (NORMAL, PAUSE, HEDGE, NUCLEAR)}
        assert rewards[PAUSE] == max(rewards.values())

    def test_a_false_nuclear_on_a_moderate_event_is_free(self, env: Any) -> None:
        """A second gap, pinned rather than changed.

        The false-nuclear penalty is `action == 3 and severity < 5`, so a full
        liquidation at severity 5 through 8.99 costs the agent nothing. Those
        are the severities where a halt is most expensive relative to the
        event — a routine data release, not a war — and the shaping is silent
        about it. Raised for the owner; changing a reward function changes what
        the next trained agent does.
        """
        for severity in (5.0, 6.0, 7.0, 8.0, 8.99):
            assert _reward(env, NUCLEAR, severity) == 0.0

    def test_pausing_outside_the_band_earns_nothing(self, env: Any) -> None:
        assert _reward(env, PAUSE, 7.0) == 0.0
        assert _reward(env, PAUSE, 9.0) == 0.0


class TestTheRewardForANormalMarket:
    """severity < 5. The agent is meant to stay in the market."""

    def test_a_false_nuclear_is_the_most_expensive_mistake_here(self, env: Any) -> None:
        env._trading_paused = True  # suppress the stochastic in-market term
        assert _reward(env, NUCLEAR, 4.99) == -3.0

    def test_a_needless_hedge_costs_less_than_a_needless_liquidation(self, env: Any) -> None:
        env._trading_paused = True
        assert _reward(env, HEDGE, 2.0) == -1.0
        assert _reward(env, HEDGE, 2.0) > _reward(env, NUCLEAR, 2.0)

    def test_severity_five_is_the_boundary_for_both_penalties(self, env: Any) -> None:
        env._trading_paused = True
        assert _reward(env, NUCLEAR, 4.99) == -3.0
        assert _reward(env, NUCLEAR, 5.0) == 0.0
        assert _reward(env, HEDGE, 4.99) == -1.0
        assert _reward(env, HEDGE, 5.0) == 0.0

    def test_staying_in_the_market_pays_something_when_unpaused(self, env: Any) -> None:
        """The only stochastic term. Over many draws its mean is positive —
        that is the incentive to keep trading when nothing is wrong."""
        env._trading_paused = False
        rewards = [_reward(env, NORMAL, 1.0) for _ in range(2000)]
        assert np.mean(rewards) > 0.0

    def test_a_paused_agent_earns_nothing_for_choosing_normal(self, env: Any) -> None:
        """The reward is computed from the state *before* the action is
        applied, so an agent that is currently paused gets no in-market credit
        on the step where it chooses to resume. Pinned because it is subtle,
        and because it means resuming costs a step."""
        env._trading_paused = True
        assert _reward(env, NORMAL, 1.0) == 0.0

    def test_the_market_term_shrinks_as_volatility_rises(self, env: Any) -> None:
        """`pnl / (vol + 1e-6)` — the Sharpe-like shape the docstring claims.
        The same P&L in a calmer market must be worth more."""
        env._trading_paused = False
        calm = [abs(_reward(env, NORMAL, 1.0, vol=0.5)) for _ in range(3000)]
        wild = [abs(_reward(env, NORMAL, 1.0, vol=5.0)) for _ in range(3000)]
        assert np.mean(calm) > np.mean(wild)


class TestTheDrawdownPenalty:
    def test_no_drawdown_costs_nothing(self, env: Any) -> None:
        assert env._peak_equity == env._equity
        assert _reward(env, PAUSE, 6.0) == 1.0

    def test_a_drawdown_is_subtracted_at_twice_its_size(self, env: Any) -> None:
        env._equity = 90_000.0  # 10% below the peak
        assert _reward(env, PAUSE, 6.0) == pytest.approx(1.0 - 0.2, abs=1e-6)

    def test_a_deeper_drawdown_costs_more(self, env: Any) -> None:
        env._equity = 90_000.0
        shallow = _reward(env, PAUSE, 6.0)
        env._equity = 50_000.0
        assert _reward(env, PAUSE, 6.0) < shallow

    def test_it_applies_to_every_action(self, env: Any) -> None:
        """A penalty that only reached some actions would bias the policy
        toward the ones it skipped."""
        for action in (NORMAL, PAUSE, HEDGE, NUCLEAR):
            env._equity = 100_000.0
            baseline = _reward(env, action, 9.5)
            env._equity = 80_000.0
            assert _reward(env, action, 9.5) < baseline


class TestAnUnrecognisedRewardModeTrainsAgainstNothing:
    """A finding, pinned rather than changed.

    `_compute_reward` computes everything inside
    `if self.reward_mode == "sharpe_minus_drawdown"`. Any other value returns
    0.0 for every action at every severity — so training would run to
    completion, save a model, and report a mean reward of zero, having taught
    the agent nothing at all about when to liquidate.

    The CLI cannot reach it: `--reward` declares
    `choices=["sharpe_minus_drawdown"]`. `train(reward_mode=...)` is a public
    function with no such guard, and `walk_forward_train` passes its argument
    straight through.
    """

    @pytest.mark.parametrize("mode", ["sharpe", "pnl", "", "sharpe_minus_drawdwon"])
    def test_every_action_scores_zero_under_an_unknown_mode(self, trainer: Any, mode: str) -> None:
        env = trainer.NuclearDecisionEnv(reward_mode=mode)
        env.reset(seed=7)
        for action in (NORMAL, PAUSE, HEDGE, NUCLEAR):
            for severity in (0.0, 5.0, 8.0, 10.0):
                assert env._compute_reward(action, severity, 1.0, 0.5) == 0.0

    def test_the_command_line_cannot_select_one(self, monkeypatch) -> None:
        import ml.train_rl_nuclear as real

        monkeypatch.setattr(sys, "argv", ["train_rl_nuclear.py", "--reward", "pnl"])
        with pytest.raises(SystemExit):
            real._parse_args()

    def test_the_function_signature_accepts_one(self, trainer: Any) -> None:
        """No guard here — which is why the CLI's `choices` is the only thing
        standing between a typo and a zero-reward training run."""
        env = trainer.NuclearDecisionEnv(reward_mode="anything at all")
        assert env.reward_mode == "anything at all"


# ---------------------------------------------------------------------------
# The escalation state machine
# ---------------------------------------------------------------------------


class TestTheDeclaredSpaces:
    def test_the_observation_space_is_seven_wide(self, env: Any) -> None:
        assert env.observation_space.low.shape == (7,)
        assert env.observation_space.high.shape == (7,)

    def test_the_bounds_describe_the_seven_components(self, env: Any) -> None:
        """Severity, exposure, level and paused are normalised to [0,1];
        sentiment is signed; volatility is the one that runs to 5."""
        assert list(env.observation_space.low) == [0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0]
        assert list(env.observation_space.high) == [1.0, 5.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    def test_the_action_space_has_one_entry_per_escalation_level(self, env: Any, trainer: Any) -> None:
        assert env.action_space.n == trainer.N_ACTIONS == 4


class TestWhatEachActionDoesToTheEscalationState:
    def test_nuclear_goes_to_the_top_and_halts_trading(self, env: Any) -> None:
        env.step(NUCLEAR)
        assert env._nuclear_level == 3
        assert env._trading_paused is True

    def test_pause_halts_trading_without_liquidating(self, env: Any) -> None:
        env.step(PAUSE)
        assert env._trading_paused is True
        assert env._nuclear_level <= 1

    def test_hedge_keeps_trading_open(self, env: Any) -> None:
        env.step(HEDGE)
        assert env._trading_paused is False
        assert env._nuclear_level <= 2

    def test_normal_resumes_trading(self, env: Any) -> None:
        env.step(NUCLEAR)
        env.step(NORMAL)
        assert env._trading_paused is False

    def test_de_escalation_from_nuclear_takes_three_normal_steps(self, env: Any) -> None:
        """`max(0, level - 1)` — one level per step. Coming down from a full
        liquidation is deliberately not instant."""
        env.step(NUCLEAR)
        assert env._nuclear_level == 3
        for expected in (2, 1, 0):
            env.step(NORMAL)
            assert env._nuclear_level == expected

    def test_the_level_never_goes_below_zero(self, env: Any) -> None:
        for _ in range(5):
            env.step(NORMAL)
        assert env._nuclear_level == 0

    def test_hedge_and_pause_can_only_lower_the_level(self, env: Any) -> None:
        """Both use `min(level, n)`, so neither escalates. Pinned because the
        names suggest otherwise: choosing HEDGE at level 0 leaves level 0."""
        env.step(NUCLEAR)
        env.step(HEDGE)
        assert env._nuclear_level == 2
        env.step(NUCLEAR)
        env.step(PAUSE)
        assert env._nuclear_level == 1
        env.step(NORMAL)
        env.step(HEDGE)
        assert env._nuclear_level == 0


class TestEquityOnlyMovesWhileTradingIsOpen:
    def test_a_halted_book_does_not_move(self, env: Any) -> None:
        """The point of the halt. Equity drifting while paused would teach the
        agent that halting is free."""
        before = env._equity
        for _ in range(50):
            env.step(NUCLEAR)
        assert env._equity == before

    def test_an_open_book_does_move(self, env: Any) -> None:
        before = env._equity
        for _ in range(50):
            env.step(NORMAL)
        assert env._equity != before

    def test_the_peak_only_ever_rises(self, env: Any) -> None:
        peaks = []
        for _ in range(200):
            env.step(NORMAL)
            peaks.append(env._peak_equity)
        assert peaks == sorted(peaks)

    def test_the_peak_is_at_least_the_equity(self, env: Any) -> None:
        """If it were not, the drawdown term could go negative and pay the
        agent for losing money."""
        for _ in range(200):
            env.step(NORMAL)
            assert env._peak_equity >= env._equity


class TestTheEpisodeBoundary:
    def test_it_terminates_at_the_declared_length(self, trainer: Any) -> None:
        env = trainer.NuclearDecisionEnv(episode_length=5)
        env.reset(seed=1)
        for step in range(1, 5):
            assert env.step(NORMAL)[2] is False, f"terminated early at step {step}"
        assert env.step(NORMAL)[2] is True

    def test_it_is_never_truncated(self, env: Any) -> None:
        """Truncation means "cut short by a time limit, bootstrap the value".
        This environment ends on its own terms, so the flag stays False."""
        assert env.step(NORMAL)[3] is False

    def test_reset_restores_every_piece_of_state(self, env: Any) -> None:
        for _ in range(20):
            env.step(NUCLEAR)
        env.reset(seed=99)
        assert env._step == 0
        assert env._equity == 100_000.0
        assert env._peak_equity == 100_000.0
        assert env._nuclear_level == 0
        assert env._trading_paused is False

    def test_reset_returns_an_observation_and_an_info_dict(self, env: Any) -> None:
        observation, info = env.reset(seed=3)
        assert observation.shape == (7,)
        assert info == {}

    def test_the_step_info_reports_the_state_an_operator_would_want(self, env: Any) -> None:
        _, _, _, _, info = env.step(HEDGE)
        assert set(info) == {"equity", "nuclear_level", "severity"}
        assert info["equity"] == env._equity
        assert info["nuclear_level"] == env._nuclear_level

    def test_the_reported_severity_is_the_one_that_was_acted_on(self, env: Any) -> None:
        """`step` reads severity off the observation the agent saw, then
        resamples. Reporting the *new* severity would attribute the action to
        an event that had not happened yet."""
        acted_on = float(env._obs[0]) * 10.0
        _, _, _, _, info = env.step(NUCLEAR)
        assert info["severity"] == pytest.approx(acted_on)

    def test_the_returned_observation_is_a_copy(self, env: Any) -> None:
        """Both `reset` and `step` return `.copy()`. Handing out the live array
        lets a caller — or a replay buffer holding a reference — mutate the
        environment's own state."""
        observation, _ = env.reset(seed=5)
        observation[0] = 99.0
        assert env._obs[0] != 99.0

        stepped = env.step(NORMAL)[0]
        stepped[1] = -42.0
        assert env._obs[1] != -42.0


class TestTheObservationSampler:
    def test_every_sample_sits_inside_the_declared_space(self, env: Any) -> None:
        """A sampler that emits outside its own Box trains the policy on states
        the normaliser was never fitted for."""
        low, high = env.observation_space.low, env.observation_space.high
        for _ in range(2000):
            observation = env._sample_training_obs()
            assert np.all(observation >= low), observation
            assert np.all(observation <= high), observation

    def test_the_severity_distribution_matches_the_documented_split(self, env: Any) -> None:
        """5% critical, 10% elevated, 85% normal. If the critical band were
        rare enough, the agent would never see the event it exists for."""
        severities = np.array([env._sample_training_obs()[0] * 10.0 for _ in range(20_000)])
        critical = float(np.mean(severities >= 8.0))
        elevated = float(np.mean((severities >= 5.0) & (severities < 8.0)))
        normal = float(np.mean(severities < 5.0))
        assert critical == pytest.approx(0.05, abs=0.01)
        assert elevated == pytest.approx(0.10, abs=0.015)
        assert normal == pytest.approx(0.85, abs=0.02)

    def test_no_severity_falls_in_the_gap_between_four_and_five(self, env: Any) -> None:
        """The normal band is [0, 4] and the elevated band starts at 5, so
        nothing is ever sampled in between — the moderate-event PAUSE bonus
        (5 <= severity < 7) is reachable, but only from the elevated draw."""
        severities = np.array([env._sample_training_obs()[0] * 10.0 for _ in range(20_000)])
        assert not np.any((severities > 4.0) & (severities < 5.0))

    def test_volatility_never_goes_non_positive(self, env: Any) -> None:
        """`max(0.1, normal(1.0, 0.5))` — the floor exists because volatility
        divides the reward. A zero would make the market term explode."""
        vols = np.array([env._sample_training_obs()[1] for _ in range(5000)])
        assert vols.min() >= 0.1

    def test_the_level_and_paused_components_report_the_live_state(self, env: Any) -> None:
        env.step(NUCLEAR)
        observation = env._sample_training_obs()
        assert observation[5] == pytest.approx(1.0)  # nuclear_level 3 / 3
        assert observation[6] == 1.0
        env.step(NORMAL)
        observation = env._sample_training_obs()
        assert observation[5] == pytest.approx(2 / 3)
        assert observation[6] == 0.0

    def test_it_is_float32_to_match_the_space(self, env: Any) -> None:
        assert env._sample_training_obs().dtype == np.float32


class TestSeedingMakesAnEpisodeReproducible:
    def test_the_same_seed_gives_the_same_episode(self, trainer: Any) -> None:
        """The docstring's claim: "fully reproducible when a seed is passed to
        reset()". Without it a bad training run cannot be re-examined."""

        def episode(seed: int) -> list[float]:
            env = trainer.NuclearDecisionEnv(episode_length=50)
            env.reset(seed=seed)
            return [float(env.step(NORMAL)[1]) for _ in range(50)]

        assert episode(4242) == episode(4242)

    def test_different_seeds_give_different_episodes(self, trainer: Any) -> None:
        def episode(seed: int) -> list[float]:
            env = trainer.NuclearDecisionEnv(episode_length=50)
            env.reset(seed=seed)
            return [float(env.step(NORMAL)[1]) for _ in range(50)]

        assert episode(1) != episode(2)

    def test_reseeding_mid_life_restarts_the_stream(self, trainer: Any) -> None:
        env = trainer.NuclearDecisionEnv(episode_length=50)
        first, _ = env.reset(seed=77)
        for _ in range(10):
            env.step(NUCLEAR)
        again, _ = env.reset(seed=77)
        assert np.array_equal(first, again)


# ---------------------------------------------------------------------------
# Training wiring — what is built, with what, and what is written where
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox(trainer: Any, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Run the trainer inside tmp_path.

    `MODEL_SAVE_PATH` and the per-fold paths are relative, so without this the
    tests would write into the repository's own `ml/rl_models/`.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(trainer, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(trainer, "MODEL_SAVE_PATH", tmp_path / "nuclear_decision_ppo.zip")
    monkeypatch.setattr(trainer, "VECNORM_SAVE_PATH", tmp_path / "nuclear_decision_vecnorm.pkl")
    return tmp_path


class TestWhatTrainingBuilds:
    """Wiring only. Nothing here asserts that PPO learns anything — the policy
    is a stub. What these check is that the objects the trainer hands to it
    describe the environment and the schedule the caller asked for.
    """

    @pytest.fixture(autouse=True)
    def _run(self, trainer: Any, sandbox: pathlib.Path, recorder: Recorder) -> None:
        trainer.train(total_timesteps=4096, eval_freq=512, n_eval_episodes=7, save_path=sandbox / "model.zip")

    def test_the_environment_is_validated_before_training(self, recorder: Recorder) -> None:
        """`check_env` is sb3's conformance check. Running it after training
        would find the problem an hour late."""
        assert "check_env" in recorder.names()
        assert recorder.names().index("check_env") < recorder.names().index("PPO")
        assert recorder.of("check_env") == ["NuclearDecisionEnv"]

    def test_both_environments_are_normalised(self, recorder: Recorder) -> None:
        """Observations are normalised on both; rewards on the training env
        only. Normalising eval rewards would make the eval number
        incomparable with the threshold the callback stops on."""
        train_kwargs, eval_kwargs = recorder.of("VecNormalize")
        assert train_kwargs["norm_obs"] is True and train_kwargs["norm_reward"] is True
        assert eval_kwargs["norm_obs"] is True and eval_kwargs["norm_reward"] is False

    def test_observations_are_clipped(self, recorder: Recorder) -> None:
        for kwargs in recorder.of("VecNormalize"):
            assert kwargs["clip_obs"] == 10.0

    def test_the_declared_hyperparameters_are_the_ones_passed(self, recorder: Recorder) -> None:
        """Pinned because the docstring block at the top of the module states a
        different learning rate and discount, and neither is a real constant —
        these are the numbers that reach PPO."""
        kwargs = recorder.of("PPO")[0]
        assert kwargs["policy"] == "MlpPolicy"
        assert kwargs["learning_rate"] == 3e-4
        assert kwargs["gamma"] == 0.99
        assert kwargs["n_steps"] == 2048
        assert kwargs["batch_size"] == 64
        assert kwargs["clip_range"] == 0.2
        assert kwargs["policy_kwargs"] == {"net_arch": [128, 128]}

    def test_the_caller_s_timestep_budget_is_what_is_trained(self, recorder: Recorder) -> None:
        assert recorder.of("learn")[0]["total_timesteps"] == 4096

    def test_the_caller_s_eval_settings_reach_the_callback(self, recorder: Recorder) -> None:
        kwargs = recorder.of("EvalCallback")[0]
        assert kwargs["eval_freq"] == 512
        assert kwargs["n_eval_episodes"] == 7
        assert kwargs["deterministic"] is True

    def test_checkpoints_are_taken_at_least_as_often_as_evaluations(self, recorder: Recorder) -> None:
        """`max(eval_freq // 2, 1000)` — the floor stops a tiny eval_freq from
        checkpointing every few steps and filling the disk."""
        assert recorder.of("CheckpointCallback")[0]["save_freq"] == 1000

    def test_a_large_eval_freq_halves_into_the_checkpoint_freq(
        self, trainer: Any, sandbox: pathlib.Path, recorder: Recorder
    ) -> None:
        recorder.events.clear()
        trainer.train(total_timesteps=10, eval_freq=10_000, save_path=sandbox / "m2.zip")
        assert recorder.of("CheckpointCallback")[0]["save_freq"] == 5000

    def test_both_callbacks_are_passed_to_learn(self, recorder: Recorder) -> None:
        """A callback constructed and not passed is a checkpoint nobody takes."""
        assert len(recorder.of("learn")[0]["callback"]) == 2

    def test_training_stops_early_on_a_good_enough_policy(self, recorder: Recorder) -> None:
        assert recorder.of("StopTrainingOnRewardThreshold")[0]["reward_threshold"] == 50.0

    def test_the_environment_is_wrapped_in_a_monitor(self, recorder: Recorder) -> None:
        """Without Monitor, episode rewards never reach the eval callback and
        the early-stop threshold can never be met."""
        assert recorder.of("Monitor") == ["NuclearDecisionEnv", "NuclearDecisionEnv"]


class TestWhatTrainingWrites:
    def test_the_policy_and_the_normalisation_stats_are_both_saved(
        self, trainer: Any, sandbox: pathlib.Path, recorder: Recorder
    ) -> None:
        """The stats are half the model. A policy restored without the
        VecNormalize state sees inputs on a different scale from the ones it
        was trained on, and behaves arbitrarily."""
        trainer.train(total_timesteps=10, save_path=sandbox / "model.zip")
        assert (sandbox / "model.zip").exists()
        assert pathlib.Path(recorder.of("vecnorm_save")[0]).exists()

    def test_the_save_directory_is_created(self, trainer: Any, sandbox: pathlib.Path) -> None:
        target = sandbox / "deep" / "nested" / "model.zip"
        trainer.train(total_timesteps=10, save_path=target)
        assert target.exists()

    def test_a_string_path_is_accepted(self, trainer: Any, sandbox: pathlib.Path) -> None:
        trainer.train(total_timesteps=10, save_path=str(sandbox / "as_string.zip"))
        assert (sandbox / "as_string.zip").exists()

    def test_the_model_is_saved_before_it_is_evaluated(self, recorder: Recorder, trainer: Any, sandbox) -> None:
        """A finding, pinned rather than changed.

        `train()` calls `model.save()` and only then runs its 500-step
        evaluation and logs the reward. The number therefore cannot gate
        anything — a policy that evaluates catastrophically has already
        overwritten the previous file by the time anyone sees the figure.
        There is no Sharpe-style floor here of the kind `ml/verify_model.py`
        applies to the XGB registry. Raised for the owner: adding one changes
        what a training run is allowed to publish.
        """
        recorder.events.clear()
        trainer.train(total_timesteps=10, save_path=sandbox / "model.zip")
        names = recorder.names()
        assert names.index("save") < names.index("predict")

    def test_the_post_training_evaluation_runs_a_fixed_five_hundred_steps(
        self, recorder: Recorder, trainer: Any, sandbox
    ) -> None:
        recorder.events.clear()
        trainer.train(total_timesteps=10, save_path=sandbox / "model.zip")
        assert len(recorder.of("predict")) == 500

    def test_the_evaluation_is_deterministic(self, recorder: Recorder, trainer: Any, sandbox) -> None:
        """A stochastic eval would report a different number for the same
        policy on every run."""
        recorder.events.clear()
        trainer.train(total_timesteps=10, save_path=sandbox / "model.zip")
        assert set(recorder.of("predict")) == {True}


class TestWalkForwardTraining:
    def test_it_trains_once_per_fold(self, trainer: Any, sandbox: pathlib.Path, recorder: Recorder) -> None:
        trainer.walk_forward_train(n_folds=3, timesteps_per_fold=100)
        assert len(recorder.of("learn")) == 3

    def test_each_fold_gets_its_own_file(self, trainer: Any, sandbox: pathlib.Path) -> None:
        trainer.walk_forward_train(n_folds=3, timesteps_per_fold=100)
        for fold in range(3):
            assert (sandbox / "ml" / "rl_models" / f"fold_{fold}_ppo.zip").exists()

    def test_the_fold_budget_is_what_the_caller_asked_for(
        self, trainer: Any, sandbox: pathlib.Path, recorder: Recorder
    ) -> None:
        trainer.walk_forward_train(n_folds=2, timesteps_per_fold=750)
        assert [call["total_timesteps"] for call in recorder.of("learn")] == [750, 750]

    def test_the_reward_mode_reaches_every_fold(self, trainer: Any, sandbox: pathlib.Path, recorder: Recorder) -> None:
        """`walk_forward_train` passes `reward_mode` straight through with no
        validation of its own — the same gap as `train()`."""
        trainer.walk_forward_train(n_folds=1, timesteps_per_fold=10, reward_mode="sharpe_minus_drawdown")
        assert recorder.of("learn")

    def test_the_best_fold_becomes_the_production_model(self, trainer: Any, sandbox: pathlib.Path) -> None:
        trainer.walk_forward_train(n_folds=2, timesteps_per_fold=100)
        assert (sandbox / "nuclear_decision_ppo.zip").exists()

    def test_the_production_model_is_published_with_no_floor_at_all(
        self, trainer: Any, sandbox: pathlib.Path, caplog
    ) -> None:
        """A finding, pinned rather than changed.

        Whatever fold scores highest is copied over the production path —
        `best_reward` is only ever compared with the other folds, never with a
        threshold. Five folds that all lose money still publish one of them.
        `ml/verify_model.py` enforces a Sharpe floor before the XGB model may
        serve; this path has no equivalent.
        """
        with caplog.at_level(logging.INFO, logger=trainer.__name__):
            trainer.walk_forward_train(n_folds=2, timesteps_per_fold=100)
        assert (sandbox / "nuclear_decision_ppo.zip").exists()
        assert "Best fold" in caplog.text

    def test_a_single_fold_still_publishes(self, trainer: Any, sandbox: pathlib.Path) -> None:
        trainer.walk_forward_train(n_folds=1, timesteps_per_fold=50)
        assert (sandbox / "nuclear_decision_ppo.zip").exists()

    def test_zero_folds_fails_rather_than_publishing_something_untrained(
        self, trainer: Any, sandbox: pathlib.Path
    ) -> None:
        """With no folds, `best_fold` stays -1 and the copy looks for
        `fold_-1_ppo.zip`. It raises, which is the right outcome — but it
        raises from `shutil.copy`, several steps after the mistake."""
        with pytest.raises(FileNotFoundError):
            trainer.walk_forward_train(n_folds=0, timesteps_per_fold=100)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


class TestTheArgumentParser:
    def _args(self, monkeypatch: pytest.MonkeyPatch, *argv: str) -> Any:
        import ml.train_rl_nuclear as real

        monkeypatch.setattr(sys, "argv", ["train_rl_nuclear.py", *argv])
        return real._parse_args()

    def test_the_defaults_are_the_documented_ones(self, monkeypatch) -> None:
        args = self._args(monkeypatch)
        assert args.timesteps == 200_000
        assert args.episodes is None
        assert args.reward == "sharpe_minus_drawdown"
        assert args.eval_freq == 10_000
        assert args.walk_forward is False
        assert args.folds == 5

    def test_timesteps_is_read_as_a_number(self, monkeypatch) -> None:
        assert self._args(monkeypatch, "--timesteps", "500000").timesteps == 500_000

    def test_a_non_numeric_budget_is_refused(self, monkeypatch) -> None:
        with pytest.raises(SystemExit):
            self._args(monkeypatch, "--timesteps", "lots")

    def test_walk_forward_is_a_flag(self, monkeypatch) -> None:
        assert self._args(monkeypatch, "--walk-forward").walk_forward is True

    def test_the_fold_count_is_settable(self, monkeypatch) -> None:
        assert self._args(monkeypatch, "--folds", "3").folds == 3

    def test_the_eval_frequency_is_settable(self, monkeypatch) -> None:
        assert self._args(monkeypatch, "--eval-freq", "250").eval_freq == 250

    def test_an_unknown_flag_is_refused(self, monkeypatch) -> None:
        with pytest.raises(SystemExit):
            self._args(monkeypatch, "--epochs", "10")


class TestTheEntryPointDispatch:
    """The `if __name__ == "__main__"` block, executed rather than read.

    It holds the one piece of arithmetic the CLI does — `--episodes` into
    timesteps — and the choice between the two training functions. Driven with
    `runpy` so the block actually runs, with both libraries stubbed so the
    dispatch is observable instead of refusing at the first guard.
    """

    def _run_main(self, recorder: Recorder, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, *argv: str):
        import runpy

        monkeypatch.setattr(sys, "argv", ["train_rl_nuclear.py", *argv])
        monkeypatch.chdir(tmp_path)
        with _stubs_installed(recorder):
            runpy.run_path(str(MODULE_PATH), run_name="__main__")

    def test_the_default_run_trains_the_declared_budget(self, recorder, monkeypatch, tmp_path) -> None:
        self._run_main(recorder, monkeypatch, tmp_path, "--timesteps", "1234")
        assert recorder.of("learn")[0]["total_timesteps"] == 1234

    def test_episodes_are_converted_at_two_hundred_steps_each(self, recorder, monkeypatch, tmp_path) -> None:
        """The help text says "1 episode ≈ 200 steps", and 200 is also the
        environment's default `episode_length`. Two places, one number."""
        self._run_main(recorder, monkeypatch, tmp_path, "--episodes", "5000")
        assert recorder.of("learn")[0]["total_timesteps"] == 5000 * 200

    def test_episodes_override_an_explicit_timestep_budget(self, recorder, monkeypatch, tmp_path) -> None:
        """The help text says so: "overrides --timesteps if set"."""
        self._run_main(recorder, monkeypatch, tmp_path, "--timesteps", "999", "--episodes", "10")
        assert recorder.of("learn")[0]["total_timesteps"] == 2000

    def test_walk_forward_splits_the_budget_across_the_folds(self, recorder, monkeypatch, tmp_path) -> None:
        self._run_main(recorder, monkeypatch, tmp_path, "--walk-forward", "--folds", "4", "--timesteps", "8000")
        budgets = [call["total_timesteps"] for call in recorder.of("learn")]
        assert budgets == [2000, 2000, 2000, 2000]

    def test_walk_forward_is_not_run_unless_asked_for(self, recorder, monkeypatch, tmp_path) -> None:
        self._run_main(recorder, monkeypatch, tmp_path, "--timesteps", "100")
        assert len(recorder.of("learn")) == 1
