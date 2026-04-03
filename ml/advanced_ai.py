# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/advanced_ai.py
=================
Advanced AI ensemble for HOPEFX:

  1. PPO RL agent (stable-baselines3) for dynamic position sizing and hedging.
  2. Vector RAG pipeline (FAISS + sentence-transformers) for news sentiment
     from an economic calendar feed.
  3. Online retraining hook that updates the ensemble on new tick data.

All heavy dependencies are guarded with try/except so the module imports
cleanly even when optional packages are absent.

Dependencies (install as needed):
    pip install stable-baselines3 gymnasium
    pip install faiss-cpu sentence-transformers
    pip install numpy pandas
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

try:
    import gymnasium as gym
    from gymnasium import spaces

    _GYM_AVAILABLE = True
except ImportError:
    gym = None  # type: ignore
    spaces = None  # type: ignore
    _GYM_AVAILABLE = False
    logger.warning("gymnasium not installed — RL agent disabled")

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    _SB3_AVAILABLE = True
except ImportError:
    PPO = None  # type: ignore
    DummyVecEnv = None  # type: ignore
    _SB3_AVAILABLE = False
    logger.warning("stable-baselines3 not installed — RL agent disabled")

try:
    import faiss  # type: ignore

    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore
    _FAISS_AVAILABLE = False
    logger.warning("faiss-cpu not installed — vector RAG disabled")

try:
    from sentence_transformers import SentenceTransformer  # type: ignore

    _ST_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore
    _ST_AVAILABLE = False
    logger.warning("sentence-transformers not installed — vector RAG disabled")


# ---------------------------------------------------------------------------
# Trading environment for RL
# ---------------------------------------------------------------------------


class TradingEnv(gym.Env if _GYM_AVAILABLE else object):  # type: ignore[misc]
    """
    Gymnasium environment wrapping a price DataFrame.

    Observation: [normalised returns(window), atr_norm, position, unrealised_pnl_norm]
    Action:      Discrete(3) — 0=flat, 1=long, 2=short
    Reward:      Step P&L minus realistic transaction costs on position changes
                 and a per-step overnight financing charge for held positions.

    Transaction cost model (XAUUSD CFD defaults):
      - spread_bps:    half-spread paid on entry/exit (default 3 bps each way)
      - commission_bps: broker commission per trade (default 2 bps)
      - financing_bps:  overnight financing per bar held (default 0.5 bps)

    These defaults are calibrated to typical retail XAUUSD CFD conditions.
    Institutional desks should lower spread_bps to ~0.5 and commission_bps to ~0.5.
    """

    metadata = {"render_modes": []}

    # Realistic XAUUSD CFD cost defaults (in decimal, not bps)
    DEFAULT_SPREAD = 3e-4  # 3 bps half-spread each way
    DEFAULT_COMMISSION = 2e-4  # 2 bps per trade (round-turn = 4 bps)
    DEFAULT_FINANCING = 5e-5  # 0.5 bps per bar held (≈ 3% p.a. on H1 bars)

    def __init__(
        self,
        df: pd.DataFrame,
        window: int = 10,
        spread_bps: float = 3.0,
        commission_bps: float = 2.0,
        financing_bps_per_bar: float = 0.5,
    ) -> None:
        if not _GYM_AVAILABLE:
            raise ImportError("gymnasium is required for TradingEnv")

        super().__init__()
        self.df = df.reset_index(drop=True)
        self.window = window
        self._n = len(df)

        # Convert bps to decimal fractions
        self._spread = spread_bps / 10_000
        self._commission = commission_bps / 10_000
        self._financing = financing_bps_per_bar / 10_000

        # Observation: window returns + atr_norm + position + pnl_norm
        obs_dim = window + 3
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_dim,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(3)  # 0=flat, 1=long, 2=short

        self._reset_state()

    def _reset_state(self) -> None:
        self._step = self.window
        self._position = 0  # -1, 0, 1
        self._entry_price = 0.0
        self._equity = 1.0
        self._initial_equity = 1.0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._reset_state()
        return self._obs(), {}

    def step(self, action: int):
        new_position = int(action) - 1  # map {0,1,2} → {-1,0,1}

        prev_close = self.df["close"].iloc[self._step - 1]
        curr_close = self.df["close"].iloc[self._step]
        ret = (curr_close - prev_close) / (prev_close + 1e-9)

        # ── P&L from existing position ────────────────────────────────────────
        pnl = self._position * ret

        # ── Transaction costs ─────────────────────────────────────────────────
        position_changed = new_position != self._position
        trade_cost = 0.0
        if position_changed:
            # Spread cost: paid on both legs of a direction change
            # (close old + open new), or just one leg if going flat/from flat
            legs = 2 if (self._position != 0 and new_position != 0) else 1
            trade_cost = legs * (self._spread + self._commission)

        # Overnight financing: charged every bar a position is held
        financing_cost = abs(self._position) * self._financing

        total_cost = trade_cost + financing_cost
        reward = float(pnl - total_cost)
        self._equity *= 1 + pnl - total_cost

        # Update position after costs are assessed on the OLD position
        self._position = new_position  # pylint: disable=attribute-defined-outside-init

        self._step += 1
        done = self._step >= self._n - 1

        return self._obs(), reward, done, False, {}

    def _obs(self) -> np.ndarray:
        closes = self.df["close"].iloc[self._step - self.window : self._step].to_numpy()
        returns = np.diff(closes) / (closes[:-1] + 1e-9)
        if len(returns) < self.window:
            returns = np.pad(returns, (self.window - len(returns), 0))

        atr_norm = float(self.df.get("atr", pd.Series([0.0])).iloc[self._step - 1]) / (
            self.df["close"].iloc[self._step - 1] + 1e-9
        )
        pnl_norm = (self._equity - self._initial_equity) / (self._initial_equity + 1e-9)

        obs = np.concatenate([returns, [atr_norm, float(self._position), pnl_norm]])
        return obs.astype(np.float32)


# ---------------------------------------------------------------------------
# PPO RL Agent
# ---------------------------------------------------------------------------


class PPORLAgent:
    """
    PPO agent for dynamic position sizing and hedging.

    Wraps stable-baselines3 PPO with:
      - Train on historical DataFrame
      - Predict action (flat/long/short) + confidence from value function
      - Online fine-tune on new tick batches
      - Persist / load model weights
    """

    MODEL_DIR = Path("ml/saved_models/ppo")

    def __init__(
        self,
        model_path: str | None = None,
        total_timesteps: int = 100_000,
        policy: str = "MlpPolicy",
    ) -> None:
        if not (_SB3_AVAILABLE and _GYM_AVAILABLE):
            raise ImportError(
                "stable-baselines3 and gymnasium are required for PPORLAgent. pip install stable-baselines3 gymnasium",
            )
        self.total_timesteps = total_timesteps
        self.policy = policy
        self._model: PPO | None = None
        self._env: DummyVecEnv | None = None

        if model_path and Path(model_path).exists():
            self.load(model_path)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame, window: int = 10) -> None:
        """Train PPO on the supplied OHLCV DataFrame."""
        logger.info(
            "ppo_agent.train bars=%d timesteps=%d",
            len(df),
            self.total_timesteps,
        )

        def _make_env():
            return TradingEnv(df, window=window)

        self._env = DummyVecEnv([_make_env])
        self._model = PPO(
            self.policy,
            self._env,
            verbose=0,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            learning_rate=3e-4,
            ent_coef=0.01,
        )
        self._model.learn(total_timesteps=self.total_timesteps)
        logger.info("ppo_agent.train complete")

    def online_update(self, df: pd.DataFrame, timesteps: int = 2048) -> None:
        """
        Fine-tune the existing model on new tick data.
        Creates a fresh env from `df` and continues learning.
        """
        if self._model is None:
            logger.warning("ppo_agent.online_update: no model loaded — skipping")
            return

        def _make_env():
            return TradingEnv(df)

        new_env = DummyVecEnv([_make_env])
        self._model.set_env(new_env)
        self._model.learn(total_timesteps=timesteps, reset_num_timesteps=False)
        logger.info("ppo_agent.online_update done timesteps=%d", timesteps)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, obs: np.ndarray) -> tuple[int, float]:
        """
        Predict action and a proxy confidence score.

        Returns:
            (action, confidence) where action ∈ {-1, 0, 1}
            and confidence ∈ [0, 1] derived from the value function.
        """
        if self._model is None:
            return 0, 0.0

        action, _states = self._model.predict(obs, deterministic=True)
        # Value function as a rough confidence proxy (normalised sigmoid)
        value = float(
            self._model.policy.predict_values(
                self._model.policy.obs_to_tensor(obs.reshape(1, -1))[0],
            ).item(),
        )
        confidence = float(1 / (1 + np.exp(-value)))
        return int(action) - 1, confidence  # map {0,1,2} → {-1,0,1}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | None = None) -> str:
        if self._model is None:
            raise RuntimeError("No model to save")
        save_path = path or str(self.MODEL_DIR / "ppo_hopefx")
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        self._model.save(save_path)
        logger.info("ppo_agent.saved path=%s", save_path)
        return save_path

    def load(self, path: str) -> None:
        self._model = PPO.load(path)
        logger.info("ppo_agent.loaded path=%s", path)


# ---------------------------------------------------------------------------
# Vector RAG — News Sentiment
# ---------------------------------------------------------------------------


@dataclass
class NewsItem:
    headline: str
    body: str = ""
    event_time: datetime | None = None
    impact: str = "medium"  # low / medium / high
    currency: str = "XAU"


@dataclass
class SentimentResult:
    headline: str
    sentiment_score: float  # -1.0 (bearish) … +1.0 (bullish)
    similar_headlines: list[str] = field(default_factory=list)
    confidence: float = 0.0


class VectorRAGNewsSentiment:
    """
    Retrieval-Augmented Generation pipeline for news sentiment.

    1. Encodes news headlines with a sentence-transformer model.
    2. Stores embeddings in a FAISS index for fast similarity search.
    3. Scores new headlines by retrieving the k most similar past items
       and averaging their labelled sentiment.

    Usage:
        rag = VectorRAGNewsSentiment()
        rag.add_items(historical_news_with_labels)
        result = rag.score(NewsItem("Fed raises rates by 75bps"))
    """

    EMBED_MODEL = "all-MiniLM-L6-v2"  # 384-dim, fast, good quality
    EMBED_DIM = 384

    def __init__(self, model_name: str = EMBED_MODEL, top_k: int = 5) -> None:
        if not (_FAISS_AVAILABLE and _ST_AVAILABLE):
            raise ImportError(
                "faiss-cpu and sentence-transformers are required for VectorRAGNewsSentiment. "
                "pip install faiss-cpu sentence-transformers",
            )
        self.top_k = top_k
        self._encoder = SentenceTransformer(model_name)
        self._index = faiss.IndexFlatIP(
            self.EMBED_DIM,
        )  # Inner-product (cosine after norm)
        self._stored_headlines: list[str] = []
        self._stored_scores: list[float] = []  # Ground-truth sentiment labels
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def add_items(self, items: list[tuple[str, float]]) -> None:
        """
        Add (headline, sentiment_score) pairs to the index.

        sentiment_score: -1.0 = strongly bearish, +1.0 = strongly bullish.
        """
        if not items:
            return
        headlines = [h for h, _ in items]
        scores = [s for _, s in items]

        embeddings = self._encode(headlines)
        with self._lock:
            self._index.add(embeddings)
            self._stored_headlines.extend(headlines)
            self._stored_scores.extend(scores)

        logger.info(
            "rag.add_items count=%d total=%d",
            len(items),
            len(self._stored_headlines),
        )

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts and L2-normalise for cosine similarity via inner product."""
        emb = self._encoder.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return emb.astype(np.float32)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(self, item: NewsItem) -> SentimentResult:
        """
        Score a new news item by retrieving similar past items.

        Returns SentimentResult with weighted average sentiment.
        """
        if self._index.ntotal == 0:
            return SentimentResult(
                headline=item.headline,
                sentiment_score=0.0,
                confidence=0.0,
            )

        query_emb = self._encode([item.headline])
        k = min(self.top_k, self._index.ntotal)

        with self._lock:
            distances, indices = self._index.search(query_emb, k)

        # distances are cosine similarities (0–1 after normalisation)
        sims = distances[0]
        idxs = indices[0]

        weighted_score = 0.0
        total_weight = 0.0
        similar: list[str] = []

        for sim, idx in zip(sims, idxs, strict=False):
            if idx < 0:
                continue
            weight = float(sim)
            weighted_score += weight * self._stored_scores[idx]
            total_weight += weight
            similar.append(self._stored_headlines[idx])

        sentiment = weighted_score / (total_weight + 1e-9)
        confidence = float(np.mean(sims)) if len(sims) > 0 else 0.0

        return SentimentResult(
            headline=item.headline,
            sentiment_score=float(np.clip(sentiment, -1.0, 1.0)),
            similar_headlines=similar,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, directory: str = "ml/saved_models/rag") -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(Path(directory) / "news.index"))
        joblib.dump(
            {"headlines": self._stored_headlines, "scores": self._stored_scores},
            Path(directory) / "metadata.pkl",
            compress=3,
        )
        logger.info("rag.saved directory=%s", directory)

    def load(self, directory: str = "ml/saved_models/rag") -> None:
        index_path = Path(directory) / "news.index"
        meta_path = Path(directory) / "metadata.pkl"
        if index_path.exists():
            self._index = faiss.read_index(str(index_path))
        if meta_path.exists():
            meta = joblib.load(meta_path)
            self._stored_headlines = meta["headlines"]
            self._stored_scores = meta["scores"]
        logger.info(
            "rag.loaded directory=%s items=%d",
            directory,
            len(self._stored_headlines),
        )


# ---------------------------------------------------------------------------
# Online retraining scheduler
# ---------------------------------------------------------------------------


class OnlineRetrainer:
    """
    Accumulates new tick bars and triggers PPO fine-tuning when a
    configurable buffer threshold is reached.

    Usage:
        retrainer = OnlineRetrainer(agent, buffer_size=500)
        # Call on every new tick/bar:
        retrainer.on_new_bar(bar_dict)
    """

    def __init__(
        self,
        agent: PPORLAgent,
        buffer_size: int = 500,
        retrain_timesteps: int = 2048,
    ) -> None:
        self.agent = agent
        self.buffer_size = buffer_size
        self.retrain_timesteps = retrain_timesteps
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._retrain_count = 0

    def on_new_bar(self, bar: dict) -> None:
        """
        Ingest a new OHLCV bar dict.
        Triggers online retraining when buffer is full.
        """
        df = None
        with self._lock:
            self._buffer.append(bar)
            if len(self._buffer) >= self.buffer_size:
                df = pd.DataFrame(self._buffer)
                self._buffer.clear()

        if df is not None and len(df) >= self.buffer_size:
            threading.Thread(
                target=self._retrain_async,
                args=(df,),
                name=f"OnlineRetrain-{self._retrain_count}",
                daemon=True,
            ).start()

    def _retrain_async(self, df: pd.DataFrame) -> None:
        try:
            logger.info("online_retrainer.start bars=%d", len(df))
            self.agent.online_update(df, timesteps=self.retrain_timesteps)
            self._retrain_count += 1
            logger.info("online_retrainer.done count=%d", self._retrain_count)
        except Exception:
            logger.exception("online_retrainer.error: %s")


# ---------------------------------------------------------------------------
# Ensemble: combines RL signal + RAG sentiment
# ---------------------------------------------------------------------------


class AdvancedAIEnsemble:
    """
    Top-level ensemble that merges:
      - PPO RL agent signal (position direction + confidence)
      - RAG news sentiment score

    Final signal = weighted blend; weights are configurable.

    Usage:
        ensemble = AdvancedAIEnsemble()
        ensemble.train_rl(historical_df)
        ensemble.add_news_history(labelled_news)

        signal = ensemble.predict(obs, news_item)
        # signal.direction ∈ {-1, 0, 1}
        # signal.size      ∈ [0, 1]  (fraction of max position)
    """

    def __init__(
        self,
        rl_weight: float = 0.6,
        sentiment_weight: float = 0.4,
        model_dir: str = "ml/saved_models",
    ) -> None:
        self.rl_weight = rl_weight
        self.sentiment_weight = sentiment_weight
        self.model_dir = model_dir

        self._rl: PPORLAgent | None = None
        self._rag: VectorRAGNewsSentiment | None = None
        self._retrainer: OnlineRetrainer | None = None

        if _SB3_AVAILABLE and _GYM_AVAILABLE:
            self._rl = PPORLAgent()
        if _FAISS_AVAILABLE and _ST_AVAILABLE:
            self._rag = VectorRAGNewsSentiment()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def train_rl(self, df: pd.DataFrame, timesteps: int = 100_000) -> None:
        if self._rl is None:
            raise RuntimeError(
                "RL agent not available — install stable-baselines3 + gymnasium",
            )
        self._rl.total_timesteps = timesteps
        self._rl.train(df)
        self._retrainer = OnlineRetrainer(self._rl)

    def add_news_history(self, items: list[tuple[str, float]]) -> None:
        if self._rag is None:
            raise RuntimeError(
                "RAG not available — install faiss-cpu + sentence-transformers",
            )
        self._rag.add_items(items)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    @dataclass
    class Signal:
        direction: int  # -1 / 0 / 1
        size: float  # 0–1 fraction of max position
        rl_confidence: float
        sentiment_score: float
        combined_score: float

    def predict(
        self,
        obs: np.ndarray,
        news_item: NewsItem | None = None,
    ) -> AdvancedAIEnsemble.Signal:
        """
        Produce a blended trading signal.

        Args:
            obs:       Observation vector for the RL agent.
            news_item: Optional current news item for sentiment scoring.
        """
        # RL signal
        rl_action, rl_conf = (0, 0.5) if self._rl is None else self._rl.predict(obs)

        # Sentiment signal
        sentiment = 0.0
        if news_item is not None and self._rag is not None:
            result = self._rag.score(news_item)
            sentiment = result.sentiment_score

        # Blend
        rl_score = rl_action * rl_conf  # ∈ [-1, 1]
        combined = self.rl_weight * rl_score + self.sentiment_weight * sentiment

        direction = int(np.sign(combined)) if abs(combined) > 0.1 else 0
        size = float(np.clip(abs(combined), 0.0, 1.0))

        return self.Signal(
            direction=direction,
            size=size,
            rl_confidence=rl_conf,
            sentiment_score=sentiment,
            combined_score=float(combined),
        )

    # ------------------------------------------------------------------
    # Online tick ingestion
    # ------------------------------------------------------------------

    def on_new_bar(self, bar: dict) -> None:
        """Forward new bar to the online retrainer."""
        if self._retrainer is not None:
            self._retrainer.on_new_bar(bar)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        if self._rl is not None:
            self._rl.save(Path(self.model_dir) / "ppo/ppo_hopefx")
        if self._rag is not None:
            self._rag.save(Path(self.model_dir) / "rag")

    def load(self) -> None:
        rl_path = Path(self.model_dir) / "ppo/ppo_hopefx.zip"
        if self._rl is not None and Path(rl_path).exists():
            self._rl.load(rl_path)
        rag_dir = Path(self.model_dir) / "rag"
        if self._rag is not None and Path(rag_dir).exists():
            self._rag.load(rag_dir)
