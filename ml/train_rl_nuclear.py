# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""

# ── Module constants ─────────────────────────────────────────────────────────
_RL_LOOKBACK_SHORT = 3
_RL_LOOKBACK_MED = 5
_RL_LOOKBACK_LONG = 7
_RL_LOOKBACK_XL = 9
_RL_MIN_EPISODES = 2
_RL_CONFIDENCE_THRESHOLD = 0.5
_RL_LEARNING_RATE = 0.05
_RL_DISCOUNT = 0.15

ml/train_rl_nuclear.py
======================
TRAINING SCRIPT ONLY — not imported by any production path.

Train the NuclearDecision PPO agent that powers NuclearHopeFXSupervisor.

The agent learns to map a 7-dim observation vector to one of four discrete
actions:

    0 — NORMAL      : continue trading
    1 — PAUSE       : halt new entries, keep existing positions
    2 — HEDGE       : reduce max risk to 15 %, open inverse hedges
    3 — NUCLEAR     : full liquidation + trading halt

Observation vector (matches _build_rl_observation in nuclear_supervisor.py):
    [0] severity / 10.0          normalised WORDMAP severity
    [1] volatility               current market vol (1.0 = normal)
    [2] sentiment                news sentiment [-1, 1]
    [3] confidence               scorer confidence [0, 1]
    [4] current_exposure         portfolio risk exposure [0, 1]
    [5] nuclear_level / 3.0      current nuclear escalation level
    [6] trading_paused           1.0 if paused, 0.0 otherwise

Reward function:
    Sharpe-like: reward = pnl_change / (vol + 1e-6) - drawdown_penalty
    Nuclear action on severity >= 9 → +5 bonus
    False nuclear (severity < 5) → -3 penalty

Usage
-----
    python ml/train_rl_nuclear.py                          # 200k steps default
    python ml/train_rl_nuclear.py --episodes 5000 --reward sharpe_minus_drawdown
    python ml/train_rl_nuclear.py --timesteps 500000 --eval-freq 10000
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

# ── Optional imports (graceful degradation) ───────────────────────────────────
try:
    import gymnasium as gym
    from gymnasium import spaces

    _GYM_AVAILABLE = True
except ImportError:
    _GYM_AVAILABLE = False
    logger.warning("gymnasium not installed — training unavailable")

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import (
        CheckpointCallback,
        EvalCallback,
        StopTrainingOnRewardThreshold,
    )
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    _SB3_AVAILABLE = True
except ImportError:
    _SB3_AVAILABLE = False
    logger.warning("stable-baselines3 not installed — training unavailable")

# ── Constants ─────────────────────────────────────────────────────────────────
MODEL_SAVE_PATH = Path("ml/rl_models/nuclear_decision_ppo.zip")
VECNORM_SAVE_PATH = Path("ml/rl_models/nuclear_decision_vecnorm.pkl")
LOG_DIR = Path("ml/rl_models/logs")
OBS_DIM = 7
N_ACTIONS = 4  # NORMAL, PAUSE, HEDGE, NUCLEAR

# ── Synthetic training environment ────────────────────────────────────────────

if _GYM_AVAILABLE:

    class NuclearDecisionEnv(gym.Env):
        """
        Synthetic Gymnasium environment for training the nuclear decision agent.

        Each episode simulates a sequence of news events with varying severity,
        volatility, and sentiment. The agent must learn to escalate correctly
        (nuclear on high severity) while avoiding false positives (nuclear on
        low severity costs P&L).
        """

        metadata = {"render_modes": []}

        def __init__(
            self,
            episode_length: int = 200,
            reward_mode: str = "sharpe_minus_drawdown",
        ) -> None:
            super().__init__()
            self.episode_length = episode_length
            self.reward_mode = reward_mode

            self.observation_space = spaces.Box(
                low=np.array([0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
                high=np.array([1.0, 5.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32),
                dtype=np.float32,
            )
            self.action_space = spaces.Discrete(N_ACTIONS)

            self._step = 0
            self._equity = 100_000.0
            self._peak_equity = 100_000.0
            self._nuclear_level = 0
            self._trading_paused = False
            self._obs: np.ndarray = np.zeros(OBS_DIM, dtype=np.float32)

        def reset(
            self,
            *,
            seed: int | None = None,
            options: dict[str, Any] | None = None,
        ) -> tuple[np.ndarray, dict]:
            super().reset(seed=seed)
            self._step = 0
            self._equity = 100_000.0
            self._peak_equity = 100_000.0
            self._nuclear_level = 0
            self._trading_paused = False
            self._obs = self._sample_training_obs()
            return self._obs.copy(), {}

        def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
            self._step += 1
            severity = float(self._obs[0]) * 10.0
            vol = float(self._obs[1])
            exposure = float(self._obs[4])

            reward = self._compute_reward(action, severity, vol, exposure)

            # Update internal state based on action
            if action == 3:  # NUCLEAR
                self._nuclear_level = 3
                self._trading_paused = True
            elif action == 2:  # HEDGE
                self._nuclear_level = min(self._nuclear_level, 2)
                self._trading_paused = False
            elif action == 1:  # PAUSE
                self._nuclear_level = min(self._nuclear_level, 1)
                self._trading_paused = True
            else:  # NORMAL
                self._nuclear_level = max(0, self._nuclear_level - 1)
                self._trading_paused = False

            # Simulate equity change using the seeded Gymnasium RNG
            if not self._trading_paused:
                pnl = self.np_random.normal(0.0002, 0.001) * self._equity
                self._equity += pnl
                self._peak_equity = max(self._peak_equity, self._equity)

            self._obs = self._sample_training_obs()
            terminated = self._step >= self.episode_length
            truncated = False
            info: dict[str, Any] = {
                "equity": self._equity,
                "nuclear_level": self._nuclear_level,
                "severity": severity,
            }
            return self._obs.copy(), reward, terminated, truncated, info

        def _compute_reward(self, action: int, severity: float, vol: float, exposure: float) -> float:
            reward = 0.0

            if self.reward_mode == "sharpe_minus_drawdown":
                # Base: small positive reward for staying in market when safe
                if not self._trading_paused and severity < 5:
                    pnl_sim = self.np_random.normal(0.0002, 0.001)
                    reward += pnl_sim / (vol + 1e-6)

                # Drawdown penalty
                dd = (self._peak_equity - self._equity) / (self._peak_equity + 1e-6)
                reward -= dd * 2.0

                # Correct nuclear action on critical event
                if action == 3 and severity >= 9:
                    reward += 5.0
                elif action == 3 and severity < 5:
                    reward -= 3.0  # false nuclear — unnecessary halt

                # Correct hedge on elevated event
                if action == 2 and 7 <= severity < 9:
                    reward += 2.0
                elif action == 2 and severity < 5:
                    reward -= 1.0

                # Correct pause on moderate event
                if action == 1 and 5 <= severity < 7:
                    reward += 1.0

                # Missed nuclear — stayed normal during critical event
                if action == 0 and severity >= 9:
                    reward -= 5.0
                elif action == 0 and severity >= 7:
                    reward -= 2.0

                # Exposure penalty: high exposure + high severity = bad
                if severity >= 7 and exposure > 0.5 and action == 0:
                    reward -= exposure * severity * 0.1

            return float(reward)

        def _sample_training_obs(self) -> np.ndarray:
            """
            Sample a stochastic observation for the current training step.

            Uses self.np_random (Gymnasium's seeded RNG) so episodes are
            fully reproducible when a seed is passed to reset().

            Severity distribution:
              5 % of steps → critical event  [8, 10]
             10 % of steps → elevated event  [5,  8]
             85 % of steps → normal market   [0,  4]
            """
            roll = self.np_random.random()
            if roll < 0.05:
                severity = self.np_random.uniform(8.0, 10.0)
            elif roll < 0.15:
                severity = self.np_random.uniform(5.0, 8.0)
            else:
                severity = self.np_random.uniform(0.0, 4.0)

            vol = max(0.1, self.np_random.normal(1.0, 0.5))
            sentiment = self.np_random.uniform(-1.0, 1.0)
            confidence = self.np_random.uniform(0.2, 1.0)
            exposure = self.np_random.uniform(0.0, 1.0)
            nuclear_level_norm = self._nuclear_level / 3.0
            paused = 1.0 if self._trading_paused else 0.0

            return np.array(
                [
                    severity / 10.0,
                    vol,
                    sentiment,
                    confidence,
                    exposure,
                    nuclear_level_norm,
                    paused,
                ],
                dtype=np.float32,
            )


# ── Training function ─────────────────────────────────────────────────────────


def train(
    total_timesteps: int = 200_000,
    reward_mode: str = "sharpe_minus_drawdown",
    eval_freq: int = 10_000,
    n_eval_episodes: int = 20,
    save_path: Path = MODEL_SAVE_PATH,
) -> None:
    """Train the PPO nuclear decision agent and save to disk."""
    if not _GYM_AVAILABLE or not _SB3_AVAILABLE:
        logger.error(
            "gymnasium and stable-baselines3 are required for training. "
            "Install with: pip install gymnasium stable-baselines3"
        )
        return

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Training NuclearDecision PPO | timesteps=%d reward=%s",
        total_timesteps,
        reward_mode,
    )

    # Build vectorised + normalised training env
    def make_env():
        env = NuclearDecisionEnv(episode_length=200, reward_mode=reward_mode)  # pylint: disable=possibly-used-before-assignment
        env = Monitor(env)
        return env

    train_env = DummyVecEnv([make_env])
    train_env = VecNormalize(train_env, norm_obs=True, norm_reward=True, clip_obs=10.0)

    eval_env = DummyVecEnv([make_env])
    eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0)

    # Validate env
    raw_env = NuclearDecisionEnv()
    check_env(raw_env, warn=True)

    # PPO hyperparameters tuned for discrete action + short episodes
    model = PPO(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        vf_coef=0.5,
        max_grad_norm=0.5,
        verbose=1,
        tensorboard_log=str(LOG_DIR),
        policy_kwargs={"net_arch": [128, 128]},
    )

    # Callbacks
    checkpoint_cb = CheckpointCallback(
        save_freq=max(eval_freq // 2, 1000),
        save_path=str(save_path.parent / "checkpoints"),
        name_prefix="nuclear_ppo",
    )
    stop_cb = StopTrainingOnRewardThreshold(reward_threshold=50.0, verbose=1)
    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path=str(save_path.parent / "best"),
        log_path=str(LOG_DIR),
        eval_freq=eval_freq,
        n_eval_episodes=n_eval_episodes,
        deterministic=True,
        callback_on_new_best=stop_cb,
    )

    # progress_bar requires tqdm+rich; degrade gracefully if absent
    try:
        import tqdm  # noqa: F401
        import rich  # noqa: F401

        _progress_bar = True
    except ImportError:
        _progress_bar = False

    model.learn(
        total_timesteps=total_timesteps,
        callback=[checkpoint_cb, eval_cb],
        progress_bar=_progress_bar,
    )

    # Save final model and VecNormalize stats
    model.save(str(save_path))
    train_env.save(str(VECNORM_SAVE_PATH))
    logger.info("Model saved → %s", save_path)
    logger.info("VecNormalize stats saved → %s", VECNORM_SAVE_PATH)

    # Quick evaluation
    obs = eval_env.reset()
    total_reward = 0.0
    for _ in range(500):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, _ = eval_env.step(action)
        total_reward += float(reward[0])
        if done[0]:
            obs = eval_env.reset()

    logger.info("Post-training eval reward (500 steps): %.4f", total_reward)


# ── Walk-forward wrapper ───────────────────────────────────────────────────────


def walk_forward_train(
    n_folds: int = 5,
    timesteps_per_fold: int = 100_000,
    reward_mode: str = "sharpe_minus_drawdown",
) -> None:
    """
    Walk-forward training: train on fold N, evaluate on fold N+1.
    Saves the best fold model as the production model.
    """
    if not _GYM_AVAILABLE or not _SB3_AVAILABLE:
        logger.error("gymnasium and stable-baselines3 required")
        return

    logger.info("Walk-forward training: %d folds × %d steps", n_folds, timesteps_per_fold)
    best_reward = float("-inf")
    best_fold = -1

    for fold in range(n_folds):
        fold_path = Path(f"ml/rl_models/fold_{fold}_ppo.zip")
        logger.info("--- Fold %d/%d ---", fold + 1, n_folds)
        train(
            total_timesteps=timesteps_per_fold,
            reward_mode=reward_mode,
            save_path=fold_path,
            eval_freq=max(timesteps_per_fold // 10, 1000),
        )

        # Evaluate fold model
        from stable_baselines3 import PPO as _PPO

        model = _PPO.load(str(fold_path))
        env = NuclearDecisionEnv(episode_length=200, reward_mode=reward_mode)
        obs, _ = env.reset()
        fold_reward = 0.0
        for _ in range(1000):
            action, _ = model.predict(obs, deterministic=True)
            obs, r, done, _, _ = env.step(int(action))
            fold_reward += r
            if done:
                obs, _ = env.reset()

        logger.info("Fold %d eval reward: %.4f", fold + 1, fold_reward)
        if fold_reward > best_reward:
            best_reward = fold_reward
            best_fold = fold

    # Copy best fold to production path
    import shutil

    best_path = Path(f"ml/rl_models/fold_{best_fold}_ppo.zip")
    shutil.copy(best_path, MODEL_SAVE_PATH)
    logger.info(
        "Best fold: %d (reward=%.4f) → saved as production model %s",
        best_fold + 1,
        best_reward,
        MODEL_SAVE_PATH,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train NuclearDecision PPO agent for HOPEFX")
    parser.add_argument(
        "--timesteps",
        type=int,
        default=200_000,
        help="Total training timesteps (default: 200000)",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=None,
        help="Approximate episodes (overrides --timesteps if set; 1 episode ≈ 200 steps)",
    )
    parser.add_argument(
        "--reward",
        type=str,
        default="sharpe_minus_drawdown",
        choices=["sharpe_minus_drawdown"],
        help="Reward function mode",
    )
    parser.add_argument(
        "--eval-freq",
        type=int,
        default=10_000,
        help="Evaluation frequency in steps (default: 10000)",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Run walk-forward training across 5 folds",
    )
    parser.add_argument(
        "--folds",
        type=int,
        default=5,
        help="Number of walk-forward folds (default: 5)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    timesteps = args.timesteps
    if args.episodes is not None:
        timesteps = args.episodes * 200  # 200 steps per episode

    if args.walk_forward:
        walk_forward_train(
            n_folds=args.folds,
            timesteps_per_fold=timesteps // args.folds,
            reward_mode=args.reward,
        )
    else:
        train(
            total_timesteps=timesteps,
            reward_mode=args.reward,
            eval_freq=args.eval_freq,
        )
