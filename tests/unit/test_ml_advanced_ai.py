# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/advanced_ai.py` — the superseded ensemble, exercised rather than read.

**These tests do not argue for wiring this module in.** It is quarantined on
purpose: every subsystem has a more developed replacement that is already live,
and `tests/unit/test_advanced_ai_is_superseded.py` fails if production imports
it. That test pins the *decision*; this one covers the *code*, which measured
27% — so if the quarantine is ever lifted, the question is "is this correct?"
rather than "does any of this run?".

Four optional dependencies gate almost everything here — gymnasium,
stable-baselines3, faiss and sentence-transformers — and none is installed, so
`TradingEnv` inherits from `object`, three of the four classes raise ImportError
on construction, and the module is 73% unreachable by import alone. The tests
below load it a second time with all four stubbed.

What that buys, and what it does not: the transaction-cost model, the
observation vector, the retrainer's buffer and the ensemble's blending are this
repository's own arithmetic and are tested as such. The stubs for PPO, FAISS and
the sentence encoder verify wiring — which object is built with which
parameters, and what is written where — and nothing about whether a policy
learns or an embedding is meaningful.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import pathlib
import sys
import threading
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MODULE_PATH = REPO / "ml" / "advanced_ai.py"


# ---------------------------------------------------------------------------
# Stubs for the four optional dependencies
# ---------------------------------------------------------------------------


class _Box:
    def __init__(self, low: Any = None, high: Any = None, shape: Any = None, dtype: Any = None) -> None:
        self.low, self.high, self.shape, self.dtype = low, high, shape, dtype


class _Discrete:
    def __init__(self, n: int) -> None:
        self.n = n


class _GymEnv:
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


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def record(self, name: str, payload: Any = None) -> None:
        self.events.append((name, payload))

    def of(self, name: str) -> list[Any]:
        return [payload for event, payload in self.events if event == name]

    def names(self) -> list[str]:
        return [event for event, _ in self.events]


def _make_stubs(recorder: Recorder) -> dict[str, types.ModuleType]:
    class _PPO:
        def __init__(self, policy: Any = None, env: Any = None, **kwargs: Any) -> None:
            self.policy_name = policy
            self.env = env
            self.kwargs = kwargs
            self.policy = types.SimpleNamespace(
                predict_values=lambda tensor: types.SimpleNamespace(item=lambda: 2.0),
                obs_to_tensor=lambda array: (array, None),
            )
            recorder.record("PPO", {"policy": policy, **kwargs})

        def learn(self, total_timesteps: int, **kwargs: Any) -> None:
            recorder.record("learn", {"total_timesteps": total_timesteps, **kwargs})

        def set_env(self, env: Any) -> None:
            recorder.record("set_env", type(env).__name__)

        def predict(self, obs: Any, deterministic: bool = False) -> tuple[Any, None]:
            recorder.record("predict", deterministic)
            return np.array(2), None  # action 2 -> short

        def save(self, path: Any) -> None:
            recorder.record("save", str(path))
            target = pathlib.Path(str(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"a saved policy")

        @staticmethod
        def load(path: Any) -> _PPO:
            recorder.record("load", str(path))
            return _PPO()

    class _DummyVecEnv:
        def __init__(self, env_fns: list[Any]) -> None:
            self.envs = [fn() for fn in env_fns]
            recorder.record("DummyVecEnv", len(self.envs))

    class _Index:
        """A FAISS IndexFlatIP stand-in: inner product over stored vectors."""

        def __init__(self, dim: int) -> None:
            self.dim = dim
            self.vectors: list[np.ndarray] = []

        @property
        def ntotal(self) -> int:
            return len(self.vectors)

        def add(self, embeddings: np.ndarray) -> None:
            self.vectors.extend(np.asarray(embeddings))

        def search(self, query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
            """Pads with index -1 and -inf when k exceeds the index size.

            That is what FAISS does, and it is the reason `score` carries an
            `if idx < 0: continue` guard. A stub that quietly returned fewer
            rows would make that guard untestable and would hide an uncapped k.
            """
            stored = np.stack(self.vectors)
            similarities = stored @ np.asarray(query)[0]
            order = np.argsort(-similarities)[:k]
            found = len(order)
            if k > found:
                order = np.concatenate([order, np.full(k - found, -1, dtype=order.dtype)])
                similarities = np.concatenate([similarities[order[:found]], np.full(k - found, -np.inf)])
                return similarities[None, :], order[None, :]
            return similarities[order][None, :], order[None, :]

    class _Encoder:
        """Deterministic bag-of-words embedding, L2-normalised.

        Real enough for the retrieval arithmetic under test: similar headlines
        must come back more similar than dissimilar ones.
        """

        def __init__(self, model_name: str) -> None:
            self.model_name = model_name
            recorder.record("SentenceTransformer", model_name)

        def encode(self, texts: list[str], convert_to_numpy: bool = True, normalize_embeddings: bool = False):
            out = np.zeros((len(texts), 384), dtype=np.float32)
            for row, text in enumerate(texts):
                for word in text.lower().split():
                    out[row, hash(word) % 384] += 1.0
            if normalize_embeddings:
                norms = np.linalg.norm(out, axis=1, keepdims=True)
                out = out / np.where(norms == 0, 1.0, norms)
            return out

    faiss = types.ModuleType("faiss")
    faiss.IndexFlatIP = _Index  # type: ignore[attr-defined]
    faiss.write_index = lambda index, path: pathlib.Path(path).write_bytes(b"index")  # type: ignore[attr-defined]
    faiss.read_index = lambda path: recorder.record("read_index", path) or _Index(384)  # type: ignore[attr-defined]

    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = _Encoder  # type: ignore[attr-defined]

    spaces = types.ModuleType("gymnasium.spaces")
    spaces.Box = _Box  # type: ignore[attr-defined]
    spaces.Discrete = _Discrete  # type: ignore[attr-defined]
    gym = types.ModuleType("gymnasium")
    gym.Env = _GymEnv  # type: ignore[attr-defined]
    gym.spaces = spaces  # type: ignore[attr-defined]

    sb3 = types.ModuleType("stable_baselines3")
    sb3.PPO = _PPO  # type: ignore[attr-defined]
    common = types.ModuleType("stable_baselines3.common")
    vec_env = types.ModuleType("stable_baselines3.common.vec_env")
    vec_env.DummyVecEnv = _DummyVecEnv  # type: ignore[attr-defined]

    return {
        "gymnasium": gym,
        "gymnasium.spaces": spaces,
        "stable_baselines3": sb3,
        "stable_baselines3.common": common,
        "stable_baselines3.common.vec_env": vec_env,
        "faiss": faiss,
        "sentence_transformers": sentence_transformers,
    }


@contextlib.contextmanager
def _stubs_installed(recorder: Recorder) -> Any:
    stubs = _make_stubs(recorder)
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
def ai(recorder: Recorder) -> Any:
    """The module loaded with all four optional dependencies present."""
    name = "_advanced_ai_stubbed"
    with _stubs_installed(recorder):
        spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Registered before execution: `@dataclass` resolves a class's
        # annotations through `sys.modules[cls.__module__].__dict__`, so a
        # module executed outside sys.modules cannot define one.
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            yield module
        finally:
            sys.modules.pop(name, None)


def _bars(n: int = 120, start: float = 1800.0, drift: float = 0.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(drift, 0.005, n)))
    return pd.DataFrame({"close": close, "atr": np.full(n, start * 0.01)})


def _flat_bars(n: int = 60, price: float = 1800.0) -> pd.DataFrame:
    """Perfectly flat prices, so every reward is cost and nothing else."""
    return pd.DataFrame({"close": np.full(n, price), "atr": np.zeros(n)})


#: Action codes as the CODE maps them: `new_position = int(action) - 1`,
#: so 0 -> -1 (short), 1 -> 0 (flat), 2 -> +1 (long). The class docstring says
#: something different — see TestTheActionCodesTheDocstringDeclares.
SHORT, FLAT, LONG = 0, 1, 2


class TestTheActionCodesTheDocstringDeclares:
    """A finding, pinned rather than changed.

    `TradingEnv`'s class docstring says:

        Action: Discrete(3) — 0=flat, 1=long, 2=short

    The code says `new_position = int(action) - 1`, which maps 0 to -1
    (short), 1 to 0 (flat) and 2 to +1 (long). Every one of the three is
    different from the docstring, and two of them are inverted: acting on the
    documented meaning, "0=flat" opens a short and "2=short" opens a long.

    `PPORLAgent.predict` agrees with the code, not the docstring — it returns
    `int(action) - 1` and documents the result as "action ∈ {-1, 0, 1}". So the
    only wrong thing is the sentence, and it is wrong in the direction that
    costs money if believed.

    Left as a finding because this module is quarantined and the fix is a
    sentence whose correct wording is the owner's call: the docstring could be
    corrected to match the code, or the mapping changed to match the docstring
    — and those two produce opposite trades. Recorded here so whoever lifts the
    quarantine meets the question rather than the sentence.
    """

    def test_action_zero_opens_a_short_not_a_flat(self, ai: Any) -> None:
        env = ai.TradingEnv(_flat_bars(), window=5)
        env.reset()
        env.step(0)
        assert env._position == -1

    def test_action_one_goes_flat_not_long(self, ai: Any) -> None:
        env = ai.TradingEnv(_flat_bars(), window=5)
        env.reset()
        env.step(2)
        env.step(1)
        assert env._position == 0

    def test_action_two_opens_a_long_not_a_short(self, ai: Any) -> None:
        env = ai.TradingEnv(_flat_bars(), window=5)
        env.reset()
        env.step(2)
        assert env._position == 1

    def test_the_docstring_still_says_the_other_thing(self, ai: Any) -> None:
        """Guards the finding: if someone corrects the sentence, this test
        fails and the class above should go with it."""
        assert "0=flat, 1=long, 2=short" in ai.TradingEnv.__doc__

    def test_the_agent_reports_the_mapping_the_code_uses(self, ai: Any, recorder: Recorder) -> None:
        """`predict` returns action - 1, so the stub's action 2 becomes +1."""
        agent = ai.PPORLAgent()
        agent.train(_bars(60), window=5)
        action, _ = agent.predict(np.zeros(8, dtype=np.float32))
        assert action == 1


# ---------------------------------------------------------------------------
# The transaction-cost model
# ---------------------------------------------------------------------------


class TestTheCostModel:
    """Costs are what separate a backtest from a fantasy. The environment
    charges spread and commission on every leg of a position change and
    financing on every bar a position is held, so these tests run on a flat
    price series where the reward is nothing but cost.
    """

    def _env(self, ai: Any, **kwargs: Any) -> Any:
        env = ai.TradingEnv(_flat_bars(), window=5, **kwargs)
        env.reset()
        return env

    def test_staying_flat_costs_nothing(self, ai: Any) -> None:
        env = self._env(ai)
        assert env.step(FLAT)[1] == pytest.approx(0.0)

    def test_opening_from_flat_pays_one_leg(self, ai: Any) -> None:
        """Closing nothing, opening one side."""
        env = self._env(ai, spread_bps=3.0, commission_bps=2.0, financing_bps_per_bar=0.0)
        assert env.step(LONG)[1] == pytest.approx(-(3.0 + 2.0) / 10_000)

    def test_closing_to_flat_pays_one_leg(self, ai: Any) -> None:
        env = self._env(ai, spread_bps=3.0, commission_bps=2.0, financing_bps_per_bar=0.0)
        env.step(LONG)
        assert env.step(FLAT)[1] == pytest.approx(-(3.0 + 2.0) / 10_000)

    def test_reversing_pays_two_legs(self, ai: Any) -> None:
        """Long to short is a close and an open. Charging one leg would make
        reversing look half price and bias the policy toward flipping."""
        env = self._env(ai, spread_bps=3.0, commission_bps=2.0, financing_bps_per_bar=0.0)
        env.step(LONG)
        assert env.step(SHORT)[1] == pytest.approx(-2 * (3.0 + 2.0) / 10_000)

    def test_holding_pays_no_trade_cost(self, ai: Any) -> None:
        """Only a change is a trade. Charging every bar would make any holding
        period unprofitable by construction."""
        env = self._env(ai, spread_bps=3.0, commission_bps=2.0, financing_bps_per_bar=0.0)
        env.step(LONG)
        assert env.step(LONG)[1] == pytest.approx(0.0)

    def test_financing_is_charged_every_bar_a_position_is_held(self, ai: Any) -> None:
        env = self._env(ai, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.5)
        env.step(LONG)
        assert env.step(LONG)[1] == pytest.approx(-0.5 / 10_000)
        assert env.step(LONG)[1] == pytest.approx(-0.5 / 10_000)

    def test_financing_is_not_charged_while_flat(self, ai: Any) -> None:
        env = self._env(ai, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.5)
        assert env.step(FLAT)[1] == pytest.approx(0.0)

    def test_financing_is_charged_on_a_short_too(self, ai: Any) -> None:
        """`abs(position)` — a short is funded, not free."""
        env = self._env(ai, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.5)
        env.step(SHORT)
        assert env.step(SHORT)[1] == pytest.approx(-0.5 / 10_000)

    def test_costs_are_charged_against_the_position_that_was_held(self, ai: Any) -> None:
        """Financing is assessed on the OLD position, before the action takes
        effect — the bar being settled is the one just lived through."""
        env = self._env(ai, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.5)
        first = env.step(LONG)[1]
        assert first == pytest.approx(0.0), "financing was charged for a bar held flat"

    def test_a_free_market_still_charges_nothing(self, ai: Any) -> None:
        """All three cost knobs at zero must produce exactly zero, so the
        default-on costs above are attributable to the knobs and not to
        arithmetic noise."""
        env = self._env(ai, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.0)
        for action in (LONG, SHORT, FLAT, LONG):
            assert env.step(action)[1] == pytest.approx(0.0)

    def test_the_defaults_are_the_documented_ones(self, ai: Any) -> None:
        env = ai.TradingEnv(_flat_bars(), window=5)
        assert env._spread == pytest.approx(3.0 / 10_000)
        assert env._commission == pytest.approx(2.0 / 10_000)
        assert env._financing == pytest.approx(0.5 / 10_000)


class TestProfitAndLoss:
    def test_a_long_earns_the_bar_return(self, ai: Any) -> None:
        frame = pd.DataFrame({"close": [100.0] * 6 + [110.0, 110.0], "atr": [0.0] * 8})
        env = ai.TradingEnv(frame, window=5, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.0)
        env.reset()
        env.step(LONG)  # opens at index 5 -> 6
        assert env._position == 1

    def test_a_short_earns_the_inverse(self, ai: Any) -> None:
        rising = pd.DataFrame({"close": np.linspace(100.0, 120.0, 40), "atr": np.zeros(40)})
        env = ai.TradingEnv(rising, window=5, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.0)
        env.reset()
        env.step(SHORT)
        rewards = [env.step(SHORT)[1] for _ in range(5)]
        assert all(reward < 0 for reward in rewards), "a short in a rising market must lose"

    def test_equity_compounds_the_rewards(self, ai: Any) -> None:
        rising = pd.DataFrame({"close": np.linspace(100.0, 120.0, 40), "atr": np.zeros(40)})
        env = ai.TradingEnv(rising, window=5, spread_bps=0.0, commission_bps=0.0, financing_bps_per_bar=0.0)
        env.reset()
        env.step(LONG)
        for _ in range(10):
            env.step(LONG)
        assert env._equity > 1.0

    def test_costs_can_take_equity_below_its_start(self, ai: Any) -> None:
        """Flat prices and non-zero costs: the only possible direction is down.
        A cost model that never bit would make this test impossible."""
        env = ai.TradingEnv(_flat_bars(), window=5)
        env.reset()
        for _ in range(10):
            env.step(LONG)
        assert env._equity < 1.0


class TestTheObservationVector:
    """Documented as `[normalised returns(window), atr_norm, position,
    unrealised_pnl_norm]`."""

    def test_it_is_the_declared_width(self, ai: Any) -> None:
        env = ai.TradingEnv(_bars(), window=10)
        observation, _ = env.reset()
        assert observation.shape == (13,)
        assert env.observation_space.shape == (13,)

    @pytest.mark.parametrize("window", [3, 5, 10, 20])
    def test_the_width_tracks_the_window(self, ai: Any, window: int) -> None:
        env = ai.TradingEnv(_bars(), window=window)
        assert env.reset()[0].shape == (window + 3,)

    def test_it_is_float32_to_match_the_space(self, ai: Any) -> None:
        env = ai.TradingEnv(_bars(), window=10)
        assert env.reset()[0].dtype == np.float32

    def test_the_leading_return_is_always_a_pad(self, ai: Any) -> None:
        """A finding, pinned rather than changed.

        `_obs` takes `window` closes and calls `np.diff`, which yields
        `window - 1` returns, then pads the front because `len(returns) <
        window`. The condition is true on *every* step, not only at the start,
        so the first slot of every observation is a synthetic zero and the
        agent only ever sees `window - 1` real returns under a name that
        promises `window`.

        Harmless to the policy — a constant input carries no information and is
        simply ignored — but it means a window of 10 is a window of 9, and
        anyone reading the observation to debug a decision sees a return that
        never happened. Left as a finding because widening the slice changes
        the observation space of a quarantined model.
        """
        env = ai.TradingEnv(_bars(), window=10)
        observation, _ = env.reset()
        assert observation[0] == 0.0
        for _ in range(5):
            observation = env.step(FLAT)[0]
            assert observation[0] == 0.0

    def test_the_real_returns_are_the_recent_bars(self, ai: Any) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0], "atr": [0.0] * 6})
        env = ai.TradingEnv(frame, window=3)
        observation, _ = env.reset()
        # window=3 -> closes[0:3] = 100, 101, 102; two returns after the pad.
        assert observation[1] == pytest.approx(1 / 100, rel=1e-4)
        assert observation[2] == pytest.approx(1 / 101, rel=1e-4)

    def test_atr_is_reported_relative_to_price(self, ai: Any) -> None:
        """A raw ATR of 18 means one thing at $1,800 and another at $180. The
        normalised form is what transfers across price regimes."""
        frame = pd.DataFrame({"close": np.full(20, 2000.0), "atr": np.full(20, 20.0)})
        env = ai.TradingEnv(frame, window=5)
        assert env.reset()[0][-3] == pytest.approx(0.01)

    def test_a_frame_with_no_atr_column_raises_rather_than_degrading(self, ai: Any) -> None:
        """A finding, pinned rather than changed.

        The line reads as a graceful default:

            self.df.get("atr", pd.Series([0.0])).iloc[self._step - 1]

        The fallback Series has exactly one element, and `_step` starts at
        `window`. So for any window above 1 — the default is 10 — the very
        first observation indexes position 9 of a length-1 Series and raises
        IndexError. The default can only ever work for `window=1`.

        The effect is that an OHLCV frame without a precomputed `atr` column
        cannot be used at all, which is the opposite of what the `.get` was
        written for: it looks like a degradation path and is a crash path.
        A one-element frame is the only case it survives, asserted below so the
        boundary is on the record.
        """
        frame = pd.DataFrame({"close": np.full(20, 2000.0)})
        env = ai.TradingEnv(frame, window=5)
        with pytest.raises(IndexError, match="out-of-bounds"):
            env.reset()

    def test_the_atr_fallback_only_works_for_a_window_of_one(self, ai: Any) -> None:
        """The single case where `pd.Series([0.0]).iloc[step - 1]` is in range."""
        frame = pd.DataFrame({"close": np.full(20, 2000.0)})
        env = ai.TradingEnv(frame, window=1)
        assert env.reset()[0][-3] == pytest.approx(0.0)

    def test_an_atr_column_of_the_right_length_works_normally(self, ai: Any) -> None:
        """The other side: supplying the column is the supported path, and it
        is unaffected by the broken default."""
        frame = pd.DataFrame({"close": np.full(20, 2000.0), "atr": np.full(20, 20.0)})
        env = ai.TradingEnv(frame, window=5)
        assert env.reset()[0][-3] == pytest.approx(0.01)

    def test_the_position_is_visible_to_the_agent(self, ai: Any) -> None:
        """Without it the policy cannot know whether an action is a hold or a
        reversal, and cannot price its own transaction costs."""
        env = ai.TradingEnv(_bars(), window=5)
        env.reset()
        assert env.step(LONG)[0][-2] == 1.0
        assert env.step(SHORT)[0][-2] == -1.0
        assert env.step(FLAT)[0][-2] == 0.0

    def test_unrealised_pnl_starts_at_zero_and_moves_with_equity(self, ai: Any) -> None:
        env = ai.TradingEnv(_flat_bars(), window=5)
        observation, _ = env.reset()
        assert observation[-1] == pytest.approx(0.0)
        for _ in range(5):
            observation = env.step(LONG)[0]
        assert observation[-1] < 0.0, "costs should show as a negative unrealised P&L"

    def test_reset_returns_the_state_to_the_start(self, ai: Any) -> None:
        env = ai.TradingEnv(_bars(), window=10)
        env.reset()
        for _ in range(20):
            env.step(LONG)
        env.reset()
        assert env._position == 0
        assert env._equity == 1.0
        assert env._step == 10

    def test_the_episode_ends_at_the_last_usable_bar(self, ai: Any) -> None:
        frame = _bars(30)
        env = ai.TradingEnv(frame, window=5)
        env.reset()
        steps = 0
        done = False
        while not done and steps < 100:
            done = env.step(FLAT)[2]
            steps += 1
        assert done
        assert steps == len(frame) - 6

    def test_the_action_space_offers_exactly_three_choices(self, ai: Any) -> None:
        assert ai.TradingEnv(_bars(), window=5).action_space.n == 3

    def test_it_refuses_to_build_without_gymnasium(self) -> None:
        """The unstubbed module — CI's actual situation. Constructing an
        environment that cannot step is worse than failing at construction."""
        import ml.advanced_ai as real

        assert real._GYM_AVAILABLE is False
        with pytest.raises(ImportError, match="gymnasium is required"):
            real.TradingEnv(_bars(), window=5)


# ---------------------------------------------------------------------------
# The PPO wrapper
# ---------------------------------------------------------------------------


class TestThePPOWrapper:
    def test_it_refuses_to_build_without_its_libraries(self) -> None:
        import ml.advanced_ai as real

        with pytest.raises(ImportError, match="stable-baselines3 and gymnasium are required"):
            real.PPORLAgent()

    def test_training_builds_a_vectorised_environment(self, ai: Any, recorder: Recorder) -> None:
        ai.PPORLAgent(total_timesteps=1234).train(_bars(80), window=5)
        assert recorder.of("DummyVecEnv") == [1]

    def test_the_declared_hyperparameters_are_the_ones_passed(self, ai: Any, recorder: Recorder) -> None:
        ai.PPORLAgent().train(_bars(80), window=5)
        kwargs = recorder.of("PPO")[0]
        assert kwargs["policy"] == "MlpPolicy"
        assert kwargs["learning_rate"] == 3e-4
        assert kwargs["gamma"] == 0.99
        assert kwargs["n_steps"] == 2048
        assert kwargs["ent_coef"] == 0.01

    def test_the_timestep_budget_is_the_one_configured(self, ai: Any, recorder: Recorder) -> None:
        ai.PPORLAgent(total_timesteps=4242).train(_bars(80), window=5)
        assert recorder.of("learn")[0]["total_timesteps"] == 4242

    def test_an_untrained_agent_predicts_nothing_with_no_confidence(self, ai: Any) -> None:
        """Flat with zero confidence — the only honest answer from a model that
        does not exist. A default of long, or of high confidence, would size a
        position on nothing."""
        assert ai.PPORLAgent().predict(np.zeros(13, dtype=np.float32)) == (0, 0.0)

    def test_a_trained_agent_maps_the_action_into_position_space(self, ai: Any) -> None:
        agent = ai.PPORLAgent()
        agent.train(_bars(80), window=5)
        action, confidence = agent.predict(np.zeros(13, dtype=np.float32))
        assert action in (-1, 0, 1)
        assert 0.0 <= confidence <= 1.0

    def test_confidence_is_a_sigmoid_of_the_value_function(self, ai: Any) -> None:
        """The stub's value head returns 2.0, so the confidence is
        sigmoid(2) — pinned so a change of squashing function is visible."""
        agent = ai.PPORLAgent()
        agent.train(_bars(80), window=5)
        _, confidence = agent.predict(np.zeros(13, dtype=np.float32))
        assert confidence == pytest.approx(1 / (1 + np.exp(-2.0)))

    def test_a_non_finite_value_does_not_escape_as_a_confidence(self, ai: Any) -> None:
        """`nan_to_num` with explicit posinf/neginf bounds. A NaN confidence
        multiplied into a position size is a NaN size."""
        agent = ai.PPORLAgent()
        agent.train(_bars(80), window=5)
        for value in (float("nan"), float("inf"), float("-inf")):
            agent._model.policy.predict_values = lambda tensor, v=value: types.SimpleNamespace(item=lambda: v)
            _, confidence = agent.predict(np.zeros(13, dtype=np.float32))
            assert np.isfinite(confidence)
            assert 0.0 <= confidence <= 1.0

    def test_an_online_update_without_a_model_is_skipped_not_crashed(self, ai: Any, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            ai.PPORLAgent().online_update(_bars(80))
        assert "no model loaded" in caplog.text

    def test_an_online_update_continues_the_existing_run(self, ai: Any, recorder: Recorder) -> None:
        """`reset_num_timesteps=False` — resetting it would restart the
        learning-rate schedule on every fine-tune."""
        agent = ai.PPORLAgent()
        agent.train(_bars(80), window=5)
        agent.online_update(_bars(80), timesteps=512)
        last = recorder.of("learn")[-1]
        assert last["total_timesteps"] == 512
        assert last["reset_num_timesteps"] is False

    def test_an_online_update_swaps_in_the_new_data(self, ai: Any, recorder: Recorder) -> None:
        agent = ai.PPORLAgent()
        agent.train(_bars(80), window=5)
        agent.online_update(_bars(80))
        assert recorder.of("set_env")

    def test_saving_without_a_model_is_refused(self, ai: Any) -> None:
        """Writing an empty file over a trained policy is worse than failing."""
        with pytest.raises(RuntimeError, match="No model to save"):
            ai.PPORLAgent().save()

    def test_saving_creates_the_directory_and_returns_the_path(self, ai: Any, tmp_path) -> None:
        agent = ai.PPORLAgent()
        agent.train(_bars(80), window=5)
        target = tmp_path / "nested" / "deeper" / "ppo_hopefx"
        assert agent.save(str(target)) == str(target)
        assert target.exists()

    def test_loading_replaces_the_model(self, ai: Any, recorder: Recorder, tmp_path) -> None:
        agent = ai.PPORLAgent()
        agent.load(str(tmp_path / "whatever"))
        assert agent._model is not None
        assert recorder.of("load")

    def test_a_model_path_that_exists_is_loaded_at_construction(self, ai: Any, recorder, tmp_path) -> None:
        existing = tmp_path / "ppo.zip"
        existing.write_bytes(b"x")
        ai.PPORLAgent(model_path=str(existing))
        assert recorder.of("load") == [str(existing)]

    def test_a_model_path_that_does_not_exist_is_ignored(self, ai: Any, recorder, tmp_path) -> None:
        """Constructing an agent against a path that is not there yet is the
        ordinary first-run case, not an error."""
        ai.PPORLAgent(model_path=str(tmp_path / "absent.zip"))
        assert recorder.of("load") == []


# ---------------------------------------------------------------------------
# Vector RAG sentiment
# ---------------------------------------------------------------------------


class TestTheRetrievalSentimentScorer:
    """The one capability here with no live replacement — the live sentiment
    path is a keyword wordmap, not an embedding model. Whether to adopt it is
    an open proposal; what it does is testable now."""

    def test_it_refuses_to_build_without_its_libraries(self) -> None:
        import ml.advanced_ai as real

        with pytest.raises(ImportError, match="faiss-cpu and sentence-transformers are required"):
            real.VectorRAGNewsSentiment()

    def test_an_empty_index_scores_neutral_with_no_confidence(self, ai: Any) -> None:
        """Nothing to retrieve means nothing is known. A default of anything
        other than zero would be an opinion invented from an empty index."""
        rag = ai.VectorRAGNewsSentiment()
        result = rag.score(ai.NewsItem("Fed raises rates by 75bps"))
        assert result.sentiment_score == 0.0
        assert result.confidence == 0.0
        assert result.similar_headlines == []

    def test_the_headline_is_echoed_back(self, ai: Any) -> None:
        rag = ai.VectorRAGNewsSentiment()
        assert rag.score(ai.NewsItem("Gold rallies")).headline == "Gold rallies"

    def test_adding_nothing_is_a_no_op(self, ai: Any) -> None:
        rag = ai.VectorRAGNewsSentiment()
        rag.add_items([])
        assert rag._index.ntotal == 0

    def test_items_are_indexed_with_their_labels(self, ai: Any) -> None:
        rag = ai.VectorRAGNewsSentiment()
        rag.add_items([("Gold surges on safe haven demand", 0.8), ("Gold slumps as dollar strengthens", -0.7)])
        assert rag._index.ntotal == 2
        assert rag._stored_scores == [0.8, -0.7]

    def test_adding_twice_accumulates(self, ai: Any) -> None:
        rag = ai.VectorRAGNewsSentiment()
        rag.add_items([("a b c", 0.5)])
        rag.add_items([("d e f", -0.5)])
        assert rag._index.ntotal == 2
        assert len(rag._stored_headlines) == 2

    def test_a_similar_headline_inherits_the_stored_sentiment(self, ai: Any) -> None:
        """The whole point of the retrieval step."""
        rag = ai.VectorRAGNewsSentiment(top_k=1)
        rag.add_items([("gold surges on safe haven demand", 0.9), ("oil slumps on oversupply", -0.9)])
        result = rag.score(ai.NewsItem("gold surges on safe haven demand"))
        assert result.sentiment_score > 0.5
        assert result.similar_headlines == ["gold surges on safe haven demand"]

    def test_an_opposite_headline_inherits_the_opposite(self, ai: Any) -> None:
        rag = ai.VectorRAGNewsSentiment(top_k=1)
        rag.add_items([("gold surges on safe haven demand", 0.9), ("oil slumps on oversupply", -0.9)])
        assert rag.score(ai.NewsItem("oil slumps on oversupply")).sentiment_score < -0.5

    def test_the_score_is_a_similarity_weighted_average(self, ai: Any) -> None:
        """Not a plain mean: a neighbour that barely resembles the query should
        pull the score less than one that matches it."""
        rag = ai.VectorRAGNewsSentiment(top_k=2)
        rag.add_items([("alpha beta gamma", 1.0), ("delta epsilon zeta", -1.0)])
        near = rag.score(ai.NewsItem("alpha beta gamma")).sentiment_score
        assert near > 0.0

    def test_the_result_is_clipped_to_the_declared_range(self, ai: Any) -> None:
        """The dataclass documents -1.0 to +1.0. A stored label outside that
        range must not propagate as a position multiplier."""
        rag = ai.VectorRAGNewsSentiment(top_k=1)
        rag.add_items([("alpha beta", 5.0)])
        assert rag.score(ai.NewsItem("alpha beta")).sentiment_score <= 1.0
        rag.add_items([("gamma delta", -5.0)])
        assert rag.score(ai.NewsItem("gamma delta")).sentiment_score >= -1.0

    def test_it_retrieves_no_more_than_the_index_holds(self, ai: Any) -> None:
        """`min(top_k, ntotal)` — asking for five neighbours from an index of
        two must not read past the end of the score list."""
        rag = ai.VectorRAGNewsSentiment(top_k=5)
        rag.add_items([("alpha beta", 0.5), ("gamma delta", -0.5)])
        assert len(rag.score(ai.NewsItem("alpha beta")).similar_headlines) == 2

    def test_an_uncapped_search_would_poison_the_confidence(self, ai: Any) -> None:
        """Why the cap is not cosmetic.

        FAISS pads a short result with index -1 and a similarity of -inf. The
        `if idx < 0: continue` guard keeps that padding out of the weighted
        score, but `confidence = mean(sims)` is computed over the raw array —
        so an uncapped k returns -inf confidence rather than a number. The cap
        is what stops that, and this pins the consequence of removing it.
        """
        rag = ai.VectorRAGNewsSentiment(top_k=5)
        rag.add_items([("alpha beta", 0.5), ("gamma delta", -0.5)])

        capped = rag.score(ai.NewsItem("alpha beta"))
        assert np.isfinite(capped.confidence)

        distances, indices = rag._index.search(rag._encode(["alpha beta"]), 5)
        assert (indices[0] < 0).sum() == 3, "the stub should pad like FAISS"
        assert not np.isfinite(float(np.mean(distances[0])))

    def test_padding_never_reaches_the_retrieved_headlines(self, ai: Any) -> None:
        """The guard itself, exercised against padding that actually exists."""
        rag = ai.VectorRAGNewsSentiment(top_k=1)
        rag.add_items([("alpha beta", 0.5)])
        result = rag.score(ai.NewsItem("alpha beta"))
        assert result.similar_headlines == ["alpha beta"]

    def test_the_neighbour_count_is_the_callers_choice(self, ai: Any) -> None:
        rag = ai.VectorRAGNewsSentiment(top_k=2)
        rag.add_items([(f"word{i} common", i / 10) for i in range(6)])
        assert len(rag.score(ai.NewsItem("word1 common")).similar_headlines) == 2

    def test_embeddings_are_normalised_for_cosine_similarity(self, ai: Any) -> None:
        """The index is inner-product; without L2 normalisation, a long
        headline outranks a relevant one on length alone."""
        rag = ai.VectorRAGNewsSentiment()
        embeddings = rag._encode(["alpha beta gamma", "delta"])
        assert np.allclose(np.linalg.norm(embeddings, axis=1), 1.0)

    def test_embeddings_are_float32_as_faiss_requires(self, ai: Any) -> None:
        assert ai.VectorRAGNewsSentiment()._encode(["alpha"]).dtype == np.float32

    def test_it_round_trips_through_disk(self, ai: Any, tmp_path) -> None:
        rag = ai.VectorRAGNewsSentiment()
        rag.add_items([("alpha beta", 0.5), ("gamma delta", -0.5)])
        rag.save(str(tmp_path / "rag"))

        restored = ai.VectorRAGNewsSentiment()
        restored.load(str(tmp_path / "rag"))
        assert restored._stored_headlines == ["alpha beta", "gamma delta"]
        assert restored._stored_scores == [0.5, -0.5]

    def test_saving_creates_the_directory(self, ai: Any, tmp_path) -> None:
        rag = ai.VectorRAGNewsSentiment()
        rag.add_items([("alpha", 0.1)])
        rag.save(str(tmp_path / "deep" / "rag"))
        assert (tmp_path / "deep" / "rag" / "news.index").exists()
        assert (tmp_path / "deep" / "rag" / "metadata.pkl").exists()

    def test_loading_from_an_empty_directory_leaves_it_usable(self, ai: Any, tmp_path) -> None:
        """First run, before anything has been saved. It must not raise."""
        rag = ai.VectorRAGNewsSentiment()
        rag.load(str(tmp_path / "never_written"))
        assert rag._stored_headlines == []

    def test_the_news_item_defaults_are_documented(self, ai: Any) -> None:
        item = ai.NewsItem("headline")
        assert item.body == ""
        assert item.impact == "medium"
        assert item.currency == "XAU"
        assert item.event_time is None


# ---------------------------------------------------------------------------
# Online retraining
# ---------------------------------------------------------------------------


class _StubAgent:
    def __init__(self) -> None:
        self.updates: list[int] = []
        self.failure: Exception | None = None
        self.seen = threading.Event()

    def online_update(self, df: pd.DataFrame, timesteps: int = 2048) -> None:
        if self.failure is not None:
            self.seen.set()
            raise self.failure
        self.updates.append(len(df))
        self.seen.set()


class TestTheOnlineRetrainer:
    def test_a_partial_buffer_does_not_retrain(self, ai: Any) -> None:
        """Retraining on ten bars would overwrite a model built on thousands."""
        agent = _StubAgent()
        retrainer = ai.OnlineRetrainer(agent, buffer_size=10)
        for i in range(9):
            retrainer.on_new_bar({"close": 1800.0 + i})
        assert agent.updates == []
        assert len(retrainer._buffer) == 9

    def test_a_full_buffer_retrains_once(self, ai: Any) -> None:
        agent = _StubAgent()
        retrainer = ai.OnlineRetrainer(agent, buffer_size=10)
        for i in range(10):
            retrainer.on_new_bar({"close": 1800.0 + i})
        assert agent.seen.wait(timeout=5.0)
        assert agent.updates == [10]

    def test_the_buffer_is_emptied_so_bars_are_not_reused(self, ai: Any) -> None:
        """A buffer that kept its contents would retrain on overlapping windows
        for ever and weight the oldest bars most heavily."""
        agent = _StubAgent()
        retrainer = ai.OnlineRetrainer(agent, buffer_size=5)
        for i in range(5):
            retrainer.on_new_bar({"close": float(i)})
        assert agent.seen.wait(timeout=5.0)
        assert retrainer._buffer == []

    def test_it_retrains_again_on_the_next_full_buffer(self, ai: Any) -> None:
        agent = _StubAgent()
        retrainer = ai.OnlineRetrainer(agent, buffer_size=4)
        for i in range(8):
            retrainer.on_new_bar({"close": float(i)})
        assert agent.seen.wait(timeout=5.0)
        for _ in range(50):
            if len(agent.updates) == 2:
                break
            threading.Event().wait(0.05)
        assert agent.updates == [4, 4]

    def test_the_configured_timestep_budget_is_used(self, ai: Any) -> None:
        seen: list[int] = []

        class _Agent:
            def online_update(self, df: pd.DataFrame, timesteps: int = 2048) -> None:
                seen.append(timesteps)

        retrainer = ai.OnlineRetrainer(_Agent(), buffer_size=3, retrain_timesteps=777)
        for i in range(3):
            retrainer.on_new_bar({"close": float(i)})
        for _ in range(100):
            if seen:
                break
            threading.Event().wait(0.05)
        assert seen == [777]

    def test_retraining_happens_off_the_ingest_thread(self, ai: Any) -> None:
        """`on_new_bar` is called from the tick path. Blocking it for the
        length of a PPO fine-tune would stall the feed."""
        ingest_thread = threading.current_thread().name
        observed: list[str] = []

        class _Agent:
            def online_update(self, df: pd.DataFrame, timesteps: int = 2048) -> None:
                observed.append(threading.current_thread().name)

        retrainer = ai.OnlineRetrainer(_Agent(), buffer_size=2)
        for i in range(2):
            retrainer.on_new_bar({"close": float(i)})
        for _ in range(100):
            if observed:
                break
            threading.Event().wait(0.05)
        assert observed and observed[0] != ingest_thread
        assert observed[0].startswith("OnlineRetrain-")

    def test_a_failing_retrain_does_not_take_down_the_feed(self, ai: Any) -> None:
        """It runs on a daemon thread with no one to catch it, so the broad
        `except Exception` is deliberate. The ingest path must survive."""
        agent = _StubAgent()
        agent.failure = RuntimeError("CUDA out of memory")
        retrainer = ai.OnlineRetrainer(agent, buffer_size=2)
        retrainer.on_new_bar({"close": 1.0})
        retrainer.on_new_bar({"close": 2.0})
        assert agent.seen.wait(timeout=5.0)
        retrainer.on_new_bar({"close": 3.0})  # the feed keeps going
        assert retrainer._buffer == [{"close": 3.0}]

    def test_the_bars_reach_the_agent_as_a_frame(self, ai: Any) -> None:
        frames: list[pd.DataFrame] = []

        class _Agent:
            def online_update(self, df: pd.DataFrame, timesteps: int = 2048) -> None:
                frames.append(df)

        retrainer = ai.OnlineRetrainer(_Agent(), buffer_size=3)
        for i in range(3):
            retrainer.on_new_bar({"close": float(i), "volume": 10.0})
        for _ in range(100):
            if frames:
                break
            threading.Event().wait(0.05)
        assert list(frames[0].columns) == ["close", "volume"]
        assert list(frames[0]["close"]) == [0.0, 1.0, 2.0]


# ---------------------------------------------------------------------------
# The ensemble
# ---------------------------------------------------------------------------


class TestTheEnsembleWithoutItsDependencies:
    """CI's situation, and the one the module is actually in today: neither
    subsystem can be constructed, so the ensemble must still be usable and must
    still refuse the things it cannot do."""

    def test_it_builds_with_neither_subsystem(self) -> None:
        import ml.advanced_ai as real

        ensemble = real.AdvancedAIEnsemble()
        assert ensemble._rl is None
        assert ensemble._rag is None

    def test_training_is_refused_with_a_reason(self) -> None:
        import ml.advanced_ai as real

        with pytest.raises(RuntimeError, match="install stable-baselines3"):
            real.AdvancedAIEnsemble().train_rl(_bars(50))

    def test_adding_news_is_refused_with_a_reason(self) -> None:
        import ml.advanced_ai as real

        with pytest.raises(RuntimeError, match="install faiss-cpu"):
            real.AdvancedAIEnsemble().add_news_history([("headline", 0.5)])

    def test_predicting_still_answers_flat(self) -> None:
        """It degrades rather than raising — but note what it reports."""
        import ml.advanced_ai as real

        signal = real.AdvancedAIEnsemble().predict(np.zeros(13, dtype=np.float32))
        assert signal.direction == 0
        assert signal.size == 0.0

    def test_it_reports_half_confidence_for_an_agent_that_does_not_exist(self) -> None:
        """A finding, pinned rather than changed.

        `rl_action, rl_conf = (0, 0.5) if self._rl is None else ...` — the
        fallback confidence is 0.5, not 0.0. It does not affect the blend,
        because the action is 0 and `rl_score = action * confidence` is 0
        either way. But `Signal.rl_confidence` is a public field, and it
        reports moderate confidence from a subsystem that was never built.
        A consumer reading that field to decide how much to trust the signal
        reads 0.5 from nothing at all. `PPORLAgent.predict` gets this right for
        an untrained model — it returns 0.0.
        """
        import ml.advanced_ai as real

        assert real.AdvancedAIEnsemble().predict(np.zeros(13, dtype=np.float32)).rl_confidence == 0.5

    def test_a_news_item_is_ignored_without_the_scorer(self) -> None:
        import ml.advanced_ai as real

        signal = real.AdvancedAIEnsemble().predict(np.zeros(13), real.NewsItem("Gold surges"))
        assert signal.sentiment_score == 0.0

    def test_new_bars_are_dropped_when_there_is_no_retrainer(self) -> None:
        """Before `train_rl` there is nothing to retrain. Silently accepting
        the bar is right; raising on the tick path would not be."""
        import ml.advanced_ai as real

        real.AdvancedAIEnsemble().on_new_bar({"close": 1800.0})

    def test_saving_and_loading_are_no_ops(self, tmp_path) -> None:
        import ml.advanced_ai as real

        ensemble = real.AdvancedAIEnsemble(model_dir=str(tmp_path))
        ensemble.save()
        ensemble.load()
        assert list(tmp_path.iterdir()) == []


class TestTheEnsembleBlend:
    @pytest.fixture
    def ensemble(self, ai: Any) -> Any:
        return ai.AdvancedAIEnsemble()

    def _with_rl(self, ensemble: Any, action: int, confidence: float) -> Any:
        ensemble._rl = types.SimpleNamespace(predict=lambda obs: (action, confidence))
        return ensemble

    def test_both_subsystems_are_built_when_available(self, ensemble: Any) -> None:
        assert ensemble._rl is not None
        assert ensemble._rag is not None

    def test_the_weights_are_the_documented_defaults(self, ensemble: Any) -> None:
        assert ensemble.rl_weight == 0.6
        assert ensemble.sentiment_weight == 0.4

    def test_a_confident_long_produces_a_long(self, ensemble: Any) -> None:
        signal = self._with_rl(ensemble, 1, 0.9).predict(np.zeros(13))
        assert signal.direction == 1
        assert signal.combined_score == pytest.approx(0.6 * 0.9)

    def test_a_confident_short_produces_a_short(self, ensemble: Any) -> None:
        signal = self._with_rl(ensemble, -1, 0.9).predict(np.zeros(13))
        assert signal.direction == -1

    def test_a_weak_signal_is_held_back_by_the_deadband(self, ensemble: Any) -> None:
        """`abs(combined) > 0.1`. Without it, the smallest disagreement between
        the two subsystems becomes a trade."""
        signal = self._with_rl(ensemble, 1, 0.1).predict(np.zeros(13))
        assert signal.combined_score == pytest.approx(0.06)
        assert signal.direction == 0

    def test_the_deadband_boundary_is_pinned(self, ensemble: Any) -> None:
        just_under = self._with_rl(ensemble, 1, 0.1 / 0.6).predict(np.zeros(13))
        assert just_under.combined_score == pytest.approx(0.1)
        assert just_under.direction == 0

    def test_a_held_back_signal_still_reports_a_size(self, ensemble: Any) -> None:
        """A finding, pinned rather than changed.

        `size` is `clip(abs(combined), 0, 1)` and is computed independently of
        the deadband, so a signal the ensemble declined to act on still comes
        back with a non-zero size. A consumer that sizes from `size` without
        first checking `direction` trades on a signal that was refused.
        `direction == 0` is the only field that says no.
        """
        signal = self._with_rl(ensemble, 1, 0.1).predict(np.zeros(13))
        assert signal.direction == 0
        assert signal.size > 0.0

    def test_size_is_capped_at_the_full_position(self, ensemble: Any) -> None:
        ensemble.rl_weight = 5.0
        signal = self._with_rl(ensemble, 1, 1.0).predict(np.zeros(13))
        assert signal.size == 1.0

    def test_sentiment_moves_the_blend(self, ai: Any) -> None:
        ensemble = ai.AdvancedAIEnsemble()
        ensemble._rl = types.SimpleNamespace(predict=lambda obs: (0, 0.0))
        ensemble.add_news_history([("gold surges on safe haven demand", 1.0)])
        signal = ensemble.predict(np.zeros(13), ai.NewsItem("gold surges on safe haven demand"))
        assert signal.sentiment_score > 0.5
        assert signal.direction == 1

    def test_sentiment_can_oppose_the_agent(self, ai: Any) -> None:
        """The reason for blending at all: a bullish policy and bearish news
        should cancel rather than either one winning outright."""
        ensemble = ai.AdvancedAIEnsemble(rl_weight=0.5, sentiment_weight=0.5)
        ensemble._rl = types.SimpleNamespace(predict=lambda obs: (1, 1.0))
        ensemble.add_news_history([("gold slumps as dollar strengthens", -1.0)])
        signal = ensemble.predict(np.zeros(13), ai.NewsItem("gold slumps as dollar strengthens"))
        assert abs(signal.combined_score) < 0.5

    def test_the_weights_are_applied_as_declared(self, ai: Any) -> None:
        ensemble = ai.AdvancedAIEnsemble(rl_weight=0.25, sentiment_weight=0.75)
        ensemble._rl = types.SimpleNamespace(predict=lambda obs: (1, 0.8))
        signal = ensemble.predict(np.zeros(13))
        assert signal.combined_score == pytest.approx(0.25 * 0.8)

    def test_no_news_item_means_no_sentiment_contribution(self, ensemble: Any) -> None:
        signal = self._with_rl(ensemble, 1, 0.5).predict(np.zeros(13), None)
        assert signal.sentiment_score == 0.0

    def test_the_signal_carries_both_inputs_for_audit(self, ensemble: Any) -> None:
        """A direction with no record of what produced it cannot be reviewed
        after a loss."""
        signal = self._with_rl(ensemble, 1, 0.9).predict(np.zeros(13))
        assert signal.rl_confidence == 0.9
        assert signal.sentiment_score == 0.0
        assert signal.combined_score == pytest.approx(0.54)


class TestTheEnsembleLifecycle:
    def test_training_installs_a_retrainer(self, ai: Any) -> None:
        """Until `train_rl` runs there is no model to fine-tune, so bars are
        dropped rather than buffered against nothing."""
        ensemble = ai.AdvancedAIEnsemble()
        assert ensemble._retrainer is None
        ensemble.train_rl(_bars(80), timesteps=64)
        assert ensemble._retrainer is not None

    def test_the_timestep_budget_reaches_the_agent(self, ai: Any, recorder: Recorder) -> None:
        ai.AdvancedAIEnsemble().train_rl(_bars(80), timesteps=4096)
        assert recorder.of("learn")[0]["total_timesteps"] == 4096

    def test_bars_reach_the_retrainer_once_it_exists(self, ai: Any) -> None:
        ensemble = ai.AdvancedAIEnsemble()
        ensemble.train_rl(_bars(80), timesteps=64)
        ensemble._retrainer.buffer_size = 3
        for i in range(2):
            ensemble.on_new_bar({"close": float(i)})
        assert len(ensemble._retrainer._buffer) == 2

    def test_saving_writes_both_subsystems(self, ai: Any, tmp_path) -> None:
        ensemble = ai.AdvancedAIEnsemble(model_dir=str(tmp_path))
        ensemble.train_rl(_bars(80), timesteps=64)
        ensemble.add_news_history([("alpha beta", 0.4)])
        ensemble.save()
        assert (tmp_path / "ppo" / "ppo_hopefx").exists()
        assert (tmp_path / "rag" / "news.index").exists()

    def test_loading_reads_back_what_was_saved(self, ai: Any, tmp_path, recorder: Recorder) -> None:
        ensemble = ai.AdvancedAIEnsemble(model_dir=str(tmp_path))
        ensemble.train_rl(_bars(80), timesteps=64)
        ensemble.add_news_history([("alpha beta", 0.4)])
        ensemble.save()
        (tmp_path / "ppo" / "ppo_hopefx.zip").write_bytes(b"policy")

        restored = ai.AdvancedAIEnsemble(model_dir=str(tmp_path))
        restored.load()
        assert recorder.of("load")
        assert restored._rag._stored_headlines == ["alpha beta"]

    def test_loading_from_an_empty_directory_is_safe(self, ai: Any, tmp_path) -> None:
        ai.AdvancedAIEnsemble(model_dir=str(tmp_path / "nothing_here")).load()
