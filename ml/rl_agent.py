# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Deep RL Agent — Stable-Baselines3 PPO on a real Gymnasium environment.

Architecture
------------
* ``ForexTradingEnv``  — Gymnasium environment backed by real OHLCV candles.
  Observation: 32-dim feature vector (same as vector store).
  Action space: Discrete(3) — HOLD / BUY / SELL.
  Reward: risk-adjusted return (Sharpe-like incremental reward).

* ``RLAgent``          — wraps SB3 PPO with train / evaluate / predict API.
  Saves/loads models to ``ml/saved_models/rl/``.

* ``RLAgentTrainer``   — async trainer that fetches historical candles via any
  object with a ``get_candles(symbol, timeframe, count)`` coroutine, trains
  the agent, and reports metrics.

  The candle source is broker-agnostic.  Pass an ``OANDAStream`` execution
  broker for historical warm-up data, or any other async candle provider.
  Live price ticks come from ``data_feed.NuclearStreamer``, not from here.

Usage
-----
    from ml.rl_agent import RLAgentTrainer
    from brokers.oanda_stream import OANDAStream

    broker = OANDAStream(api_key=..., account_id=..., instruments=["XAU_USD"])
    await broker.__aenter__()
    await broker.connect()

    trainer = RLAgentTrainer(candle_source=broker)
    metrics = await trainer.train(
        symbol="XAU_USD", timeframe="H1", timesteps=50_000
    )
    print(metrics)

    # live inference
    action, confidence = trainer.agent.predict(current_candles)
    # action: 0=HOLD, 1=BUY, 2=SELL
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
from datetime import timezone

UTC = timezone.utc

logger = logging.getLogger(__name__)

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "saved_models", "rl")
os.makedirs(_MODEL_DIR, exist_ok=True)

_WINDOW = 50  # observation window (must match vector_store._WINDOW)
_FEATURE_DIM = 32


# ── Gymnasium environment ─────────────────────────────────────────────────────


class ForexTradingEnv:
    """
    A Gymnasium-compatible trading environment for forex/gold.

    Observation
    -----------
    32-dim normalised feature vector (RSI, MACD, BB, ATR, volume-z, …)
    plus 3 position state dims: [position (-1/0/1), unrealised_pnl, steps_held]
    → total 35 dims.

    Action space
    ------------
    Discrete(3): 0=HOLD, 1=BUY (go long), 2=SELL (go short)

    Reward
    ------
    Incremental Sharpe contribution with full transaction cost accounting:

        transaction_cost = commission + slippage   (on open and close)
        holding_cost     = overnight_cost_daily * notional  (per bar held)
        delta_pnl_net    = delta_pnl_gross - holding_cost

        r_t = clip(delta_pnl_net / (rolling_std_20 + ε), -10, +10) * reward_scaling

    Reward is clipped to [-10, +10] before scaling to prevent gradient
    explosions from outlier bars (e.g. news spikes).

    Cost defaults are calibrated to XAUUSD H1 live trading:
      - commission 35 bps round-trip (spread ~20 bps + broker commission ~15 bps)
      - slippage   5 bps per trade (market-order fill slippage on H1 bars)
      - overnight  2 bps/day swap ≈ 7.3% annualised (typical leveraged XAUUSD)

    The previous implementation used 1 bp holding cost which was far below
    real swap rates and caused the agent to overhold losing positions.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        candles: list[dict],
        initial_balance: float = 10_000.0,
        position_pct: float = 0.10,
        commission: float = 0.0035,  # 35 bps round-trip (spread + broker fee)
        slippage_bps: float = 0.0005,  # 5 bps per trade (market-order slippage)
        overnight_cost_daily: float = 0.0002,  # 2 bps/day ≈ 7.3% annualised (XAUUSD swap)
        reward_scaling: float = 100.0,
        reward_clip: float = 10.0,  # clip reward to [-clip, +clip] before scaling
    ):
        try:
            import gymnasium as gym
            from gymnasium import spaces
        except ImportError:
            raise ImportError("gymnasium required: pip install gymnasium") from None

        import pandas as pd

        from research.vector_store import _WINDOW as W
        from research.vector_store import _compute_features

        self._gym = gym
        self._spaces = spaces

        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        self._df = df

        self.initial_balance = initial_balance
        self.position_pct = position_pct
        self.commission = commission
        self.slippage_bps = slippage_bps
        self.overnight_cost_daily = overnight_cost_daily  # per-bar holding cost
        self.reward_scaling = reward_scaling
        self.reward_clip = reward_clip
        self._window = W

        # pre-compute feature vectors for every valid window
        self._features: list[np.ndarray] = []
        self._prices: list[float] = []
        for i in range(W, len(df)):
            window = df.iloc[i - W : i]
            vec = _compute_features(window)
            if vec is not None:
                self._features.append(vec)
                self._prices.append(float(df.at[i, "close"]))

        if len(self._features) < 10:
            raise ValueError(
                f"Not enough valid windows: {len(self._features)} (need at least 10, have {len(df)} candles)",
            )

        obs_dim = _FEATURE_DIM + 3
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_dim,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(3)

        self._step_idx = 0
        self._position = 0  # -1 short, 0 flat, 1 long
        self._entry_price = 0.0
        self._balance = initial_balance
        self._steps_held = 0
        self._pnl_history: list[float] = []

    # ── Gymnasium API ─────────────────────────────────────────────────────────

    def reset(self, *, seed=None, options=None):
        self._step_idx = 0
        self._position = 0
        self._entry_price = 0.0
        self._balance = self.initial_balance
        self._steps_held = 0
        self._pnl_history = []
        return self._obs(), {}

    def step(self, action: int):
        price = self._prices[self._step_idx]
        prev_equity = self._equity(price)

        # ── execute action ────────────────────────────────────────────────────
        if action == 1 and self._position != 1:  # BUY
            self._close_position(price)
            self._open_position(1, price)
        elif action == 2 and self._position != -1:  # SELL
            self._close_position(price)
            self._open_position(-1, price)
        # action == 0 → HOLD

        self._step_idx += 1
        done = self._step_idx >= len(self._features) - 1

        new_price = self._prices[self._step_idx] if not done else price
        new_equity = self._equity(new_price)
        delta_pnl = new_equity - prev_equity

        # ── Overnight financing cost ──────────────────────────────────────────
        # Deduct holding cost for every bar an open position is carried.
        # overnight_cost_daily is expressed as a fraction of notional per bar.
        # At 2 bps/day this is ~7.3% annualised — realistic for leveraged XAUUSD.
        # The previous implementation used 0 bps, causing the agent to overhold
        # positions that would be unprofitable in live trading.
        if self._position != 0:
            notional = self._balance * self.position_pct
            holding_cost = notional * self.overnight_cost_daily
            self._balance -= holding_cost
            delta_pnl -= holding_cost
            self._steps_held += 1
        else:
            self._steps_held = 0

        self._pnl_history.append(delta_pnl)

        # ── Sharpe-like incremental reward with clipping ──────────────────────
        # Normalise by rolling 20-bar PnL std so the reward is scale-invariant.
        # Clip to [-reward_clip, +reward_clip] before scaling to prevent gradient
        # explosions from outlier bars (news spikes, data errors).
        if len(self._pnl_history) > 20:
            std = float(np.std(self._pnl_history[-20:])) + 1e-9
            raw_reward = float(delta_pnl / std)
        else:
            # Insufficient history — normalise by initial balance
            raw_reward = float(delta_pnl / self.initial_balance)

        reward = float(np.clip(raw_reward, -self.reward_clip, self.reward_clip)) * self.reward_scaling

        info = {
            "equity": new_equity,
            "position": self._position,
            "price": new_price,
            "delta_pnl": delta_pnl,
            "raw_reward": raw_reward,
        }
        return self._obs(), reward, done, False, info

    def render(self):
        pass

    # ── internals ─────────────────────────────────────────────────────────────

    def _obs(self) -> np.ndarray:
        feat = self._features[self._step_idx].copy()
        price = self._prices[self._step_idx]
        upnl = (
            self._position * (price - self._entry_price) / (self._entry_price + 1e-9) if self._entry_price > 0 else 0.0
        )
        extra = np.array(
            [
                float(self._position),
                np.clip(upnl, -1.0, 1.0),
                min(self._steps_held / 100.0, 1.0),
            ],
            dtype=np.float32,
        )
        return np.concatenate([feat, extra])

    def _equity(self, price: float) -> float:
        if self._position == 0 or self._entry_price == 0:
            return self._balance
        size = (self._balance * self.position_pct) / self._entry_price
        return self._balance + self._position * size * (price - self._entry_price)

    def _open_position(self, direction: int, price: float) -> None:
        # Total entry cost = commission (spread + broker fee) + slippage.
        # Slippage is modelled as an adverse fill: the effective entry price
        # is worse by slippage_bps in the direction of the trade.
        notional = self._balance * self.position_pct
        total_cost_rate = self.commission + self.slippage_bps
        cost = notional * total_cost_rate
        self._balance -= cost
        self._position = direction
        # Effective entry price includes slippage adverse fill
        slip = price * self.slippage_bps * direction  # positive for BUY, negative for SELL
        self._entry_price = price + slip
        self._steps_held = 0

    def _close_position(self, price: float) -> None:
        if self._position == 0:
            return
        size = (self._balance * self.position_pct) / (self._entry_price + 1e-9)
        pnl = self._position * size * (price - self._entry_price)
        # Exit cost = commission + slippage (adverse fill on close)
        total_cost_rate = self.commission + self.slippage_bps
        cost = size * price * total_cost_rate
        self._balance += pnl - cost
        self._position = 0
        self._entry_price = 0.0


# ── metrics ───────────────────────────────────────────────────────────────────


@dataclass
class RLMetrics:
    sharpe: float
    total_return: float
    max_drawdown: float
    win_rate: float
    episodes: int
    timesteps: int
    model_path: str

    def __str__(self) -> str:
        return (
            f"Sharpe={self.sharpe:.3f}  Return={self.total_return * 100:.2f}%  "
            f"MaxDD={self.max_drawdown * 100:.2f}%  WinRate={self.win_rate * 100:.1f}%  "
            f"Timesteps={self.timesteps:,}"
        )


# ── agent wrapper ─────────────────────────────────────────────────────────────


class RLAgent:
    """
    Wraps a Stable-Baselines3 PPO model with train / evaluate / predict.

    Parameters
    ----------
    model_name : filename stem for saving/loading (no extension)
    """

    def __init__(self, model_name: str = "hopefx_ppo"):
        self.model_name = model_name
        self.model_path = os.path.join(_MODEL_DIR, f"{model_name}.zip")
        self._model: Any = None

    # ── training ──────────────────────────────────────────────────────────────

    def train(
        self,
        env: ForexTradingEnv,
        timesteps: int = 100_000,
        n_envs: int = 1,
        verbose: int = 1,
    ) -> None:
        """Train PPO on the given environment."""
        try:
            from stable_baselines3 import PPO

        except ImportError:
            raise ImportError(
                "stable-baselines3 required: pip install stable-baselines3",
            ) from None

        logger.info("Training PPO for %d timesteps …", timesteps)
        self._model = PPO(
            policy="MlpPolicy",
            env=env,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            verbose=verbose,
            tensorboard_log=os.path.join(_MODEL_DIR, "tb_logs"),
        )
        self._model.learn(total_timesteps=timesteps)
        self._model.save(self.model_path)
        logger.info("Model saved to %s", self.model_path)

    def load(self) -> bool:
        """Load a previously saved model. Returns True if successful."""
        if not os.path.exists(self.model_path):
            logger.warning("No saved model at %s", self.model_path)
            return False
        try:
            from stable_baselines3 import PPO

            self._model = PPO.load(self.model_path)
            logger.info("Loaded RL model from %s", self.model_path)
            return True
        except Exception as exc:
            logger.error("Model load failed: %s", exc)
            return False

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(
        self,
        candles: list[dict],
    ) -> tuple[int, float]:
        """
        Predict the next action given recent candles.

        Returns
        -------
        (action, confidence)
            action     : 0=HOLD, 1=BUY, 2=SELL
            confidence : probability of the chosen action (0–1)
        """
        if self._model is None:
            raise RuntimeError(
                "Model not trained or loaded — call train() or load() first",
            )

        import pandas as pd

        from research.vector_store import _WINDOW as W
        from research.vector_store import _compute_features

        df = pd.DataFrame(candles).sort_values("timestamp").reset_index(drop=True)
        vec = _compute_features(df.iloc[-W:])
        if vec is None:
            return 0, 0.0

        # Append position state: [position=0 (flat), unrealised_pnl=0, steps_held=0]
        obs = np.concatenate([vec, np.zeros(3, dtype=np.float32)])
        action, _states = self._model.predict(obs, deterministic=True)

        # get action probabilities from policy
        try:
            import torch

            obs_tensor = self._model.policy.obs_to_tensor(obs[None])[0]
            with torch.no_grad():
                dist = self._model.policy.get_distribution(obs_tensor)
                probs = dist.distribution.probs.cpu().numpy()[0]
            confidence = float(probs[int(action)])
        except Exception:
            confidence = 1.0 / 3

        return int(action), confidence

    # ── evaluation ────────────────────────────────────────────────────────────

    def evaluate(self, env: ForexTradingEnv) -> dict[str, float]:
        """Run one full episode and return performance metrics."""
        if self._model is None:
            raise RuntimeError("Model not trained or loaded")

        obs, _ = env.reset()
        equity_curve = [env.initial_balance]
        wins = losses = 0
        prev_equity = env.initial_balance

        while True:
            action, _ = self._model.predict(obs, deterministic=True)
            obs, _, done, _, info = env.step(int(action))
            eq = info.get("equity", prev_equity)
            equity_curve.append(eq)
            if eq > prev_equity:
                wins += 1
            elif eq < prev_equity:
                losses += 1
            prev_equity = eq
            if done:
                break

        eq = np.array(equity_curve, dtype=float)
        ret = np.diff(eq) / (eq[:-1] + 1e-9)

        sharpe = float(np.mean(ret) / (np.std(ret) + 1e-9) * np.sqrt(252 * 24))
        total_return = float((eq[-1] - eq[0]) / eq[0])
        peak = np.maximum.accumulate(eq)
        max_dd = float(np.min((eq - peak) / (peak + 1e-9)))
        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0.0

        return {
            "sharpe": sharpe,
            "total_return": total_return,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "trades": total_trades,
        }


# ── async trainer ─────────────────────────────────────────────────────────────


class RLAgentTrainer:
    """
    Fetches historical candles, trains the RL agent, and returns metrics.

    Parameters
    ----------
    candle_source : Any object with a ``get_candles(symbol, timeframe, count)``
                    coroutine.  Typically an ``OANDAStream`` execution broker
                    used for historical warm-up data only — not for live ticks.
                    Live price ticks come from ``data_feed.NuclearStreamer``.
    model_name    : name for saving the trained model.

    Deprecated parameter
    --------------------
    ``oanda_stream`` is accepted as a keyword alias for ``candle_source`` to
    preserve backwards compatibility with existing call sites.  It will be
    removed in a future release.
    """

    def __init__(
        self,
        candle_source: Any = None,
        model_name: str = "hopefx_ppo",
        # Backwards-compat alias — remove after all call sites are updated.
        oanda_stream: Any = None,
    ):
        if candle_source is None and oanda_stream is not None:
            logger.warning("RLAgentTrainer: 'oanda_stream' parameter is deprecated — use 'candle_source' instead.")
            candle_source = oanda_stream
        if candle_source is None:
            raise ValueError(
                "RLAgentTrainer requires a 'candle_source' with a get_candles(symbol, timeframe, count) coroutine."
            )
        self.stream = candle_source
        self.agent = RLAgent(model_name=model_name)

    async def train(
        self,
        symbol: str = "XAU_USD",
        timeframe: str = "H1",
        candles: int = 2000,
        timesteps: int = 100_000,
        train_split: float = 0.8,
    ) -> RLMetrics:
        """
        Fetch candles, build env, train PPO, evaluate on hold-out set.

        Returns RLMetrics with Sharpe, return, drawdown, win-rate.
        """
        logger.info(
            "Fetching %d %s %s candles for RL training …",
            candles,
            symbol,
            timeframe,
        )
        raw = await self.stream.get_candles(symbol, timeframe, candles)
        if len(raw) < 200:
            raise ValueError(f"Only {len(raw)} candles returned — need at least 200")

        split = int(len(raw) * train_split)
        train_candles = raw[:split]
        test_candles = raw[split:]

        logger.info(
            "Train: %d candles  Test: %d candles",
            len(train_candles),
            len(test_candles),
        )

        train_env = ForexTradingEnv(train_candles)
        test_env = ForexTradingEnv(test_candles)

        self.agent.train(train_env, timesteps=timesteps)

        metrics_dict = self.agent.evaluate(test_env)
        logger.info("RL evaluation: %s", metrics_dict)

        return RLMetrics(
            sharpe=metrics_dict["sharpe"],
            total_return=metrics_dict["total_return"],
            max_drawdown=metrics_dict["max_drawdown"],
            win_rate=metrics_dict["win_rate"],
            episodes=1,
            timesteps=timesteps,
            model_path=self.agent.model_path,
        )

    def predict(self, candles: list[dict]) -> tuple[int, float]:
        """Predict action from recent candles. 0=HOLD 1=BUY 2=SELL."""
        return self.agent.predict(candles)


# ── Walk-forward evaluation ───────────────────────────────────────────────────


@dataclass
class WalkForwardFold:
    """Results for a single walk-forward fold."""

    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    sharpe: float
    total_return: float
    max_drawdown: float
    win_rate: float
    trades: int
    model_path: str


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward evaluation results."""

    symbol: str
    timeframe: str
    n_folds: int
    folds: list[WalkForwardFold]
    avg_sharpe: float
    avg_return: float
    avg_drawdown: float
    avg_win_rate: float
    stability_score: float  # 0–100: 100 = perfectly consistent across folds
    timesteps_per_fold: int
    completed_at: str

    def __str__(self) -> str:
        return (
            f"WalkForward({self.n_folds} folds)  "
            f"AvgSharpe={self.avg_sharpe:.3f}  "
            f"AvgReturn={self.avg_return * 100:.2f}%  "
            f"Stability={self.stability_score:.1f}/100"
        )


def walk_forward_eval(
    candles: list[dict],
    symbol: str = "XAU_USD",
    timeframe: str = "H1",
    n_folds: int = 5,
    timesteps_per_fold: int = 50_000,
    train_pct: float = 0.70,
    model_name_prefix: str = "hopefx_ppo_wf",
) -> WalkForwardResult:
    """
    Walk-forward evaluation of the PPO agent.

    Splits ``candles`` into ``n_folds`` anchored windows:
      - Each fold trains on the first ``train_pct`` of its window.
      - Tests on the remaining ``1 - train_pct``.
      - Windows are anchored (expanding train set) to avoid look-ahead bias.

    Parameters
    ----------
    candles           : list of OHLCV dicts (sorted ascending by timestamp)
    symbol            : instrument name (for logging)
    timeframe         : bar timeframe (for logging)
    n_folds           : number of walk-forward folds
    timesteps_per_fold: PPO training steps per fold
    train_pct         : fraction of each fold window used for training
    model_name_prefix : prefix for saved model filenames

    Returns
    -------
    WalkForwardResult with per-fold metrics and aggregate statistics.
    """
    import pandas as pd

    if len(candles) < 200:
        raise ValueError(f"Need at least 200 candles, got {len(candles)}")

    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    total = len(df)
    fold_size = total // n_folds
    folds_results: list[WalkForwardFold] = []

    logger.info(
        "Walk-forward eval: %d candles, %d folds, %d steps/fold",
        total,
        n_folds,
        timesteps_per_fold,
    )

    for fold_idx in range(n_folds):
        # Anchored expanding window: train on [0 .. fold_end * train_pct]
        fold_end = fold_size * (fold_idx + 1)
        fold_df = df.iloc[:fold_end].reset_index(drop=True)

        split = int(len(fold_df) * train_pct)
        if split < 100 or (len(fold_df) - split) < 50:
            logger.warning(
                "Fold %d: insufficient data (%d rows), skipping",
                fold_idx + 1,
                len(fold_df),
            )
            continue

        train_rows = fold_df.iloc[:split]
        test_rows = fold_df.iloc[split:]

        train_candles_fold = train_rows.to_dict("records")
        test_candles_fold = test_rows.to_dict("records")

        model_name = f"{model_name_prefix}_fold{fold_idx + 1}"
        agent = RLAgent(model_name=model_name)

        try:
            train_env = ForexTradingEnv(train_candles_fold)
            test_env = ForexTradingEnv(test_candles_fold)
        except ValueError as exc:
            logger.warning("Fold %d env creation failed: %s", fold_idx + 1, exc)
            continue

        logger.info("Fold %d/%d: training %d steps …", fold_idx + 1, n_folds, timesteps_per_fold)
        agent.train(train_env, timesteps=timesteps_per_fold, verbose=0)

        metrics = agent.evaluate(test_env)

        fold_result = WalkForwardFold(
            fold=fold_idx + 1,
            train_start=str(train_rows["timestamp"].iloc[0]),
            train_end=str(train_rows["timestamp"].iloc[-1]),
            test_start=str(test_rows["timestamp"].iloc[0]),
            test_end=str(test_rows["timestamp"].iloc[-1]),
            sharpe=metrics["sharpe"],
            total_return=metrics["total_return"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            trades=int(metrics["trades"]),
            model_path=agent.model_path,
        )
        folds_results.append(fold_result)
        logger.info(
            "Fold %d: Sharpe=%.3f  Return=%.2f%%  MaxDD=%.2f%%  WinRate=%.1f%%",
            fold_idx + 1,
            metrics["sharpe"],
            metrics["total_return"] * 100,
            metrics["max_drawdown"] * 100,
            metrics["win_rate"] * 100,
        )

    if not folds_results:
        raise RuntimeError("All walk-forward folds failed — check candle data quality")

    sharpes = [f.sharpe for f in folds_results]
    returns = [f.total_return for f in folds_results]
    drawdowns = [f.max_drawdown for f in folds_results]
    win_rates = [f.win_rate for f in folds_results]

    avg_sharpe = float(np.mean(sharpes))
    avg_return = float(np.mean(returns))
    avg_drawdown = float(np.mean(drawdowns))
    avg_win_rate = float(np.mean(win_rates))

    # Stability score: 100 - coefficient of variation of Sharpe ratios (capped 0–100)
    sharpe_std = float(np.std(sharpes)) if len(sharpes) > 1 else 0.0
    sharpe_mean = abs(avg_sharpe) + 1e-9
    cv = sharpe_std / sharpe_mean
    stability = float(max(0.0, min(100.0, 100.0 * (1.0 - cv))))

    from datetime import datetime

    completed_at = datetime.now(UTC).isoformat()

    result = WalkForwardResult(
        symbol=symbol,
        timeframe=timeframe,
        n_folds=len(folds_results),
        folds=folds_results,
        avg_sharpe=avg_sharpe,
        avg_return=avg_return,
        avg_drawdown=avg_drawdown,
        avg_win_rate=avg_win_rate,
        stability_score=stability,
        timesteps_per_fold=timesteps_per_fold,
        completed_at=completed_at,
    )
    logger.info("Walk-forward complete: %s", result)
    return result


# ── Module-level singleton ─────────────────────────────────────────────────────

_rl_agent_singleton: RLAgent | None = None
_rl_agent_lock = __import__("threading").Lock()


def get_rl_agent(model_name: str = "hopefx_ppo") -> RLAgent | None:
    """
    Return the module-level RLAgent singleton (thread-safe).

    Attempts to load the saved model on first call.  Returns None if
    stable-baselines3 is not installed or no saved model exists.
    """
    global _rl_agent_singleton
    if _rl_agent_singleton is None:
        with _rl_agent_lock:
            if _rl_agent_singleton is None:
                agent = RLAgent(model_name=model_name)
                loaded = agent.load()
                _rl_agent_singleton = agent if loaded else None
    return _rl_agent_singleton
