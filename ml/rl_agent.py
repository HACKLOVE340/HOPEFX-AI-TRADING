"""
HOPEFX Deep RL Agent — Stable-Baselines3 PPO on a real Gymnasium environment.

Architecture
------------
* ``ForexTradingEnv``  — Gymnasium environment backed by real OANDA candles.
  Observation: 32-dim feature vector (same as vector store).
  Action space: Discrete(3) — HOLD / BUY / SELL.
  Reward: risk-adjusted return (Sharpe-like incremental reward).

* ``RLAgent``          — wraps SB3 PPO with train / evaluate / predict API.
  Saves/loads models to ``ml/saved_models/rl/``.

* ``RLAgentTrainer``   — async trainer that fetches live candles from OANDA,
  trains the agent, and reports metrics.

Usage
-----
    from ml.rl_agent import RLAgentTrainer

    trainer = RLAgentTrainer(oanda_stream=stream)
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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "saved_models", "rl")
os.makedirs(_MODEL_DIR, exist_ok=True)

_WINDOW    = 50    # observation window (must match vector_store._WINDOW)
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
    Incremental Sharpe contribution:
        r_t = Δpnl / (rolling_std(Δpnl) + ε)
    Penalty for excessive trading (commission).
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        candles:              List[Dict],
        initial_balance:      float = 10_000.0,
        position_pct:         float = 0.10,
        commission:           float = 0.0035,   # 35 bps — realistic XAUUSD spread + commission
        overnight_cost_daily: float = 0.0002,   # 2 bps/day ≈ 7.3% annualised (realistic XAUUSD swap)
        reward_scaling:       float = 100.0,
    ):
        try:
            import gymnasium as gym
            from gymnasium import spaces
        except ImportError:
            raise ImportError("gymnasium required: pip install gymnasium")

        import pandas as pd
        from research.vector_store import _compute_features, _WINDOW as W

        self._gym    = gym
        self._spaces = spaces

        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        self._df = df

        self.initial_balance      = initial_balance
        self.position_pct         = position_pct
        self.commission           = commission
        self.overnight_cost_daily = overnight_cost_daily  # per-bar holding cost
        self.reward_scaling       = reward_scaling
        self._window              = W

        # pre-compute feature vectors for every valid window
        self._features: List[np.ndarray] = []
        self._prices:   List[float]      = []
        for i in range(W, len(df)):
            window = df.iloc[i - W : i]
            vec    = _compute_features(window)
            if vec is not None:
                self._features.append(vec)
                self._prices.append(float(df.at[i, "close"]))

        if len(self._features) < 10:
            raise ValueError(
                f"Not enough valid windows: {len(self._features)} "
                f"(need at least 10, have {len(df)} candles)"
            )

        obs_dim = _FEATURE_DIM + 3
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)

        self._step_idx    = 0
        self._position    = 0      # -1 short, 0 flat, 1 long
        self._entry_price = 0.0
        self._balance     = initial_balance
        self._steps_held  = 0
        self._pnl_history: List[float] = []

    # ── Gymnasium API ─────────────────────────────────────────────────────────

    def reset(self, *, seed=None, options=None):
        self._step_idx    = 0
        self._position    = 0
        self._entry_price = 0.0
        self._balance     = self.initial_balance
        self._steps_held  = 0
        self._pnl_history = []
        return self._obs(), {}

    def step(self, action: int):
        price = self._prices[self._step_idx]
        prev_equity = self._equity(price)

        # ── execute action ────────────────────────────────────────────────────
        if action == 1 and self._position != 1:    # BUY
            self._close_position(price)
            self._open_position(1, price)
        elif action == 2 and self._position != -1: # SELL
            self._close_position(price)
            self._open_position(-1, price)
        # action == 0 → HOLD

        self._step_idx += 1
        done = self._step_idx >= len(self._features) - 1

        new_price  = self._prices[self._step_idx] if not done else price
        new_equity = self._equity(new_price)
        delta_pnl  = new_equity - prev_equity

        # ── Overnight financing cost ──────────────────────────────────────────
        # Deduct holding cost for every bar an open position is carried.
        # overnight_cost_daily is expressed as a fraction of notional per bar.
        # At 2 bps/day this is ~7.3% annualised — realistic for leveraged XAUUSD.
        # The previous implementation used 0 bps, causing the agent to overhold
        # positions that would be unprofitable in live trading.
        if self._position != 0:
            notional = (self._balance * self.position_pct)
            holding_cost = notional * self.overnight_cost_daily
            self._balance -= holding_cost
            delta_pnl    -= holding_cost
            self._steps_held += 1
        else:
            self._steps_held = 0

        self._pnl_history.append(delta_pnl)

        # Sharpe-like incremental reward
        if len(self._pnl_history) > 20:
            std = float(np.std(self._pnl_history[-20:])) + 1e-9
            reward = float(delta_pnl / std) * self.reward_scaling
        else:
            reward = float(delta_pnl / self.initial_balance) * self.reward_scaling

        info = {
            "equity":   new_equity,
            "position": self._position,
            "price":    new_price,
        }
        return self._obs(), reward, done, False, info

    def render(self):
        pass

    # ── internals ─────────────────────────────────────────────────────────────

    def _obs(self) -> np.ndarray:
        feat = self._features[self._step_idx].copy()
        price = self._prices[self._step_idx]
        upnl  = self._position * (price - self._entry_price) / (self._entry_price + 1e-9) \
                if self._entry_price > 0 else 0.0
        extra = np.array([
            float(self._position),
            np.clip(upnl, -1.0, 1.0),
            min(self._steps_held / 100.0, 1.0),
        ], dtype=np.float32)
        return np.concatenate([feat, extra])

    def _equity(self, price: float) -> float:
        if self._position == 0 or self._entry_price == 0:
            return self._balance
        size = (self._balance * self.position_pct) / self._entry_price
        return self._balance + self._position * size * (price - self._entry_price)

    def _open_position(self, direction: int, price: float) -> None:
        cost = (self._balance * self.position_pct) * self.commission
        self._balance   -= cost
        self._position   = direction
        self._entry_price= price
        self._steps_held = 0

    def _close_position(self, price: float) -> None:
        if self._position == 0:
            return
        size = (self._balance * self.position_pct) / (self._entry_price + 1e-9)
        pnl  = self._position * size * (price - self._entry_price)
        cost = size * price * self.commission
        self._balance  += pnl - cost
        self._position  = 0
        self._entry_price = 0.0


# ── metrics ───────────────────────────────────────────────────────────────────

@dataclass
class RLMetrics:
    sharpe:       float
    total_return: float
    max_drawdown: float
    win_rate:     float
    episodes:     int
    timesteps:    int
    model_path:   str

    def __str__(self) -> str:
        return (
            f"Sharpe={self.sharpe:.3f}  Return={self.total_return*100:.2f}%  "
            f"MaxDD={self.max_drawdown*100:.2f}%  WinRate={self.win_rate*100:.1f}%  "
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
        self.model_name  = model_name
        self.model_path  = os.path.join(_MODEL_DIR, f"{model_name}.zip")
        self._model: Any = None

    # ── training ──────────────────────────────────────────────────────────────

    def train(
        self,
        env:        ForexTradingEnv,
        timesteps:  int  = 100_000,
        n_envs:     int  = 1,
        verbose:    int  = 1,
    ) -> None:
        """Train PPO on the given environment."""
        try:
            from stable_baselines3 import PPO
            from stable_baselines3.common.env_checker import check_env
        except ImportError:
            raise ImportError("stable-baselines3 required: pip install stable-baselines3")

        logger.info("Training PPO for %d timesteps …", timesteps)
        self._model = PPO(
            policy          = "MlpPolicy",
            env             = env,
            learning_rate   = 3e-4,
            n_steps         = 2048,
            batch_size      = 64,
            n_epochs        = 10,
            gamma           = 0.99,
            gae_lambda      = 0.95,
            clip_range      = 0.2,
            ent_coef        = 0.01,
            verbose         = verbose,
            tensorboard_log = os.path.join(_MODEL_DIR, "tb_logs"),
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
        candles: List[Dict],
    ) -> Tuple[int, float]:
        """
        Predict the next action given recent candles.

        Returns
        -------
        (action, confidence)
            action     : 0=HOLD, 1=BUY, 2=SELL
            confidence : probability of the chosen action (0–1)
        """
        if self._model is None:
            raise RuntimeError("Model not trained or loaded — call train() or load() first")

        from research.vector_store import _compute_features, _WINDOW as W
        import pandas as pd

        df  = pd.DataFrame(candles).sort_values("timestamp").reset_index(drop=True)
        vec = _compute_features(df.iloc[-W:])
        if vec is None:
            return 0, 0.0

        # append dummy position state (flat, no pnl, 0 steps)
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

    def evaluate(self, env: ForexTradingEnv) -> Dict[str, float]:
        """Run one full episode and return performance metrics."""
        if self._model is None:
            raise RuntimeError("Model not trained or loaded")

        obs, _ = env.reset()
        equity_curve = [env.initial_balance]
        wins = losses = 0
        prev_equity = env.initial_balance

        while True:
            action, _ = self._model.predict(obs, deterministic=True)
            obs, reward, done, _, info = env.step(int(action))
            eq = info.get("equity", prev_equity)
            equity_curve.append(eq)
            if eq > prev_equity:
                wins += 1
            elif eq < prev_equity:
                losses += 1
            prev_equity = eq
            if done:
                break

        eq  = np.array(equity_curve, dtype=float)
        ret = np.diff(eq) / (eq[:-1] + 1e-9)

        sharpe       = float(np.mean(ret) / (np.std(ret) + 1e-9) * np.sqrt(252 * 24))
        total_return = float((eq[-1] - eq[0]) / eq[0])
        peak         = np.maximum.accumulate(eq)
        max_dd       = float(np.min((eq - peak) / (peak + 1e-9)))
        total_trades = wins + losses
        win_rate     = wins / total_trades if total_trades > 0 else 0.0

        return {
            "sharpe":       sharpe,
            "total_return": total_return,
            "max_drawdown": max_dd,
            "win_rate":     win_rate,
            "trades":       total_trades,
        }


# ── async trainer ─────────────────────────────────────────────────────────────

class RLAgentTrainer:
    """
    Fetches live OANDA candles, trains the RL agent, and returns metrics.

    Parameters
    ----------
    oanda_stream : OANDAStream instance (must be connected)
    model_name   : name for saving the model
    """

    def __init__(
        self,
        oanda_stream: Any,
        model_name:   str = "hopefx_ppo",
    ):
        self.stream    = oanda_stream
        self.agent     = RLAgent(model_name=model_name)

    async def train(
        self,
        symbol:     str   = "XAU_USD",
        timeframe:  str   = "H1",
        candles:    int   = 2000,
        timesteps:  int   = 100_000,
        train_split:float = 0.8,
    ) -> RLMetrics:
        """
        Fetch candles, build env, train PPO, evaluate on hold-out set.

        Returns RLMetrics with Sharpe, return, drawdown, win-rate.
        """
        logger.info(
            "Fetching %d %s %s candles for RL training …",
            candles, symbol, timeframe,
        )
        raw = await self.stream.get_candles(symbol, timeframe, candles)
        if len(raw) < 200:
            raise ValueError(
                f"Only {len(raw)} candles returned — need at least 200"
            )

        split = int(len(raw) * train_split)
        train_candles = raw[:split]
        test_candles  = raw[split:]

        logger.info(
            "Train: %d candles  Test: %d candles",
            len(train_candles), len(test_candles),
        )

        train_env = ForexTradingEnv(train_candles)
        test_env  = ForexTradingEnv(test_candles)

        self.agent.train(train_env, timesteps=timesteps)

        metrics_dict = self.agent.evaluate(test_env)
        logger.info("RL evaluation: %s", metrics_dict)

        return RLMetrics(
            sharpe       = metrics_dict["sharpe"],
            total_return = metrics_dict["total_return"],
            max_drawdown = metrics_dict["max_drawdown"],
            win_rate     = metrics_dict["win_rate"],
            episodes     = 1,
            timesteps    = timesteps,
            model_path   = self.agent.model_path,
        )

    def predict(self, candles: List[Dict]) -> Tuple[int, float]:
        """Predict action from recent candles. 0=HOLD 1=BUY 2=SELL."""
        return self.agent.predict(candles)
