# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Vector Feature Store — real ChromaDB embeddings + RAG retrieval.

What it does
------------
* Ingests OHLCV candle windows and computes a feature vector for each window
  (RSI, MACD, Bollinger, ATR, volume z-score, return momentum, regime label).
* Stores those vectors in a persistent ChromaDB collection.
* Provides semantic search: given the current market state, retrieve the N
  most similar historical windows and their outcomes (next-bar return).
* The LLM agent and RL agent both call ``query_similar_regimes()`` to get
  RAG context before making decisions.

Usage
-----
    from research.vector_store import MarketVectorStore

    store = MarketVectorStore(persist_dir="data/vectordb")
    await store.ingest_candles(candles, symbol="XAU_USD", timeframe="H1")

    # retrieve 5 most similar past windows to the current market state
    results = store.query_similar_regimes(current_candles, top_k=5)
    for r in results:
        logger.info(r["regime"], r["next_return"], r["distance"])
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── feature engineering ───────────────────────────────────────────────────────

_WINDOW = 50  # candles per feature vector


def _compute_features(df) -> np.ndarray | None:
    """
    Compute a 32-dimensional feature vector from a candle DataFrame.

    Requires columns: open, high, low, close, volume.
    Returns None if there are fewer than _WINDOW rows.
    """
    try:
        import ta

        if len(df) < _WINDOW:
            return None

        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        v = df["volume"].astype(float)

        # ── momentum ──────────────────────────────────────────────────────────
        rsi = ta.momentum.RSIIndicator(c, window=14).rsi().iloc[-1]
        stoch = ta.momentum.StochasticOscillator(h, l, c).stoch().iloc[-1]

        # ── trend ─────────────────────────────────────────────────────────────
        macd_obj = ta.trend.MACD(c)
        macd = macd_obj.macd().iloc[-1]
        macd_sig = macd_obj.macd_signal().iloc[-1]
        macd_hist = macd_obj.macd_diff().iloc[-1]
        ema20 = ta.trend.EMAIndicator(c, window=20).ema_indicator().iloc[-1]
        ema50 = ta.trend.EMAIndicator(c, window=50).ema_indicator().iloc[-1]
        adx = ta.trend.ADXIndicator(h, l, c).adx().iloc[-1]

        # ── volatility ────────────────────────────────────────────────────────
        bb = ta.volatility.BollingerBands(c, window=20)
        bb_pct = bb.bollinger_pband().iloc[-1]
        bb_width = bb.bollinger_wband().iloc[-1]
        atr = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range().iloc[-1]

        # ── volume ────────────────────────────────────────────────────────────
        v_clean = v.dropna()
        vol_mean = float(np.nan_to_num(v_clean.rolling(20).mean().iloc[-1], nan=0.0))
        vol_std = float(np.nan_to_num(v_clean.rolling(20).std().iloc[-1], nan=0.0)) + 1e-9
        vol_z = (v.iloc[-1] - vol_mean) / vol_std

        # ── price returns ─────────────────────────────────────────────────────
        ret1 = float(c.pct_change(1).iloc[-1])
        ret5 = float(c.pct_change(5).iloc[-1])
        ret20 = float(c.pct_change(20).iloc[-1])

        # ── normalised price position ─────────────────────────────────────────
        last = float(c.iloc[-1])
        hi20 = float(h.rolling(20).max().iloc[-1])
        lo20 = float(l.rolling(20).min().iloc[-1])
        rng = hi20 - lo20 + 1e-9
        price_pos = (last - lo20) / rng

        # ── regime flags ──────────────────────────────────────────────────────
        trending = 1.0 if adx > 25 else 0.0
        bull = 1.0 if ema20 > ema50 else 0.0
        overbought = 1.0 if rsi > 70 else 0.0
        oversold = 1.0 if rsi < 30 else 0.0

        # ── higher-timeframe momentum (5-bar, 10-bar slopes) ──────────────────
        slope5 = float(np.polyfit(range(5), c.iloc[-5:].values, 1)[0]) / (last + 1e-9)
        slope10 = float(np.polyfit(range(10), c.iloc[-10:].values, 1)[0]) / (last + 1e-9)

        vec = np.array(
            [
                rsi / 100,
                stoch / 100,
                macd / (last + 1e-9),
                macd_sig / (last + 1e-9),
                macd_hist / (last + 1e-9),
                (ema20 - last) / (last + 1e-9),
                (ema50 - last) / (last + 1e-9),
                adx / 100,
                bb_pct,
                bb_width / (last + 1e-9),
                atr / (last + 1e-9),
                np.clip(vol_z, -3, 3) / 3,
                np.clip(ret1, -0.05, 0.05) / 0.05,
                np.clip(ret5, -0.10, 0.10) / 0.10,
                np.clip(ret20, -0.20, 0.20) / 0.20,
                price_pos,
                trending,
                bull,
                overbought,
                oversold,
                np.clip(slope5, -0.01, 0.01) / 0.01,
                np.clip(slope10, -0.01, 0.01) / 0.01,
                # padding to 32 dims
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ],
            dtype=np.float32,
        )

        # replace NaN/Inf with 0
        vec = np.nan_to_num(vec, nan=0.0, posinf=1.0, neginf=-1.0)
        return vec

    except Exception as exc:
        logger.debug("Feature computation error: %s", exc)
        return None


def _regime_label(df) -> str:
    """Classify the last window into a human-readable regime."""
    try:
        import ta

        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        adx = ta.trend.ADXIndicator(h, l, c).adx().iloc[-1]
        rsi = ta.momentum.RSIIndicator(c, window=14).rsi().iloc[-1]
        ema20 = ta.trend.EMAIndicator(c, window=20).ema_indicator().iloc[-1]
        ema50 = ta.trend.EMAIndicator(c, window=50).ema_indicator().iloc[-1]

        if adx > 30 and ema20 > ema50:
            return "trending_up"
        if adx > 30 and ema20 < ema50:
            return "trending_down"
        if rsi > 70:
            return "overbought"
        if rsi < 30:
            return "oversold"
        return "ranging"
    except (ValueError, TypeError):
        return "unknown"


# ── result dataclass ──────────────────────────────────────────────────────────


@dataclass
class SimilarWindow:
    window_id: str
    symbol: str
    timeframe: str
    timestamp: str
    regime: str
    next_return: float  # actual return in the bar AFTER this window
    distance: float  # cosine distance (lower = more similar)
    features: list[float]


# ── vector store ──────────────────────────────────────────────────────────────


class MarketVectorStore:
    """
    Persistent ChromaDB-backed market feature store.

    Parameters
    ----------
    persist_dir : Directory where ChromaDB stores its data.
    collection  : ChromaDB collection name.
    """

    def __init__(
        self,
        persist_dir: str = "data/vectordb",
        collection: str = "market_features",
    ):
        self.persist_dir = persist_dir
        self.collection_name = collection
        self._client = None
        self._collection = None
        Path(persist_dir).mkdir(parents=True, exist_ok=True)

    def _ensure_connected(self) -> None:
        if self._collection is not None:
            return
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB connected — collection '%s' has %d documents",
                self.collection_name,
                self._collection.count(),
            )
        except Exception as exc:
            raise RuntimeError(f"ChromaDB init failed: {exc}") from exc

    # ── ingestion ─────────────────────────────────────────────────────────────

    async def ingest_candles(
        self,
        candles: list[dict],
        symbol: str,
        timeframe: str,
        stride: int = 10,
    ) -> int:
        """
        Ingest a list of OHLCV candle dicts into the vector store.

        Slides a window of size _WINDOW over the candles with the given
        stride, computes features for each window, and upserts into ChromaDB.

        Returns the number of windows ingested.
        """
        self._ensure_connected()

        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("pandas required for ingestion") from exc

        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        ids, embeddings, metadatas = [], [], []

        for start in range(0, len(df) - _WINDOW - 1, stride):
            window = df.iloc[start : start + _WINDOW]
            next_bar = df.iloc[start + _WINDOW]

            vec = _compute_features(window)
            if vec is None:
                continue

            next_ret = float((next_bar["close"] - window.iloc[-1]["close"]) / (window.iloc[-1]["close"] + 1e-9))
            regime = _regime_label(window)
            ts = str(window.iloc[-1]["timestamp"])

            # deterministic ID based on content
            uid = hashlib.md5(f"{symbol}:{timeframe}:{ts}".encode(), usedforsecurity=False).hexdigest()

            ids.append(uid)
            embeddings.append(vec.tolist())
            metadatas.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": ts,
                    "regime": regime,
                    "next_return": next_ret,
                }
            )

        if not ids:
            logger.warning("No windows extracted from %d candles", len(candles))
            return 0

        # upsert in batches of 500
        batch = 500
        for i in range(0, len(ids), batch):
            self._collection.upsert(
                ids=ids[i : i + batch],
                embeddings=embeddings[i : i + batch],
                metadatas=metadatas[i : i + batch],
            )

        logger.info(
            "Ingested %d windows from %s %s (%d candles)",
            len(ids),
            symbol,
            timeframe,
            len(candles),
        )
        return len(ids)

    # ── retrieval ─────────────────────────────────────────────────────────────

    def query_similar_regimes(
        self,
        candles: list[dict],
        top_k: int = 5,
        symbol_filter: str | None = None,
    ) -> list[SimilarWindow]:
        """
        Given the most recent candles, find the top-k most similar historical
        windows and return their metadata + outcomes.

        Parameters
        ----------
        candles       : Recent OHLCV candles (at least _WINDOW bars).
        top_k         : Number of results to return.
        symbol_filter : If set, restrict results to this symbol.
        """
        self._ensure_connected()

        try:
            import pandas as pd
        except ImportError:
            return []

        df = pd.DataFrame(candles).sort_values("timestamp").reset_index(drop=True)
        vec = _compute_features(df.iloc[-_WINDOW:])
        if vec is None:
            logger.warning("Not enough candles for query (%d < %d)", len(df), _WINDOW)
            return []

        where = {"symbol": symbol_filter} if symbol_filter else None

        try:
            results = self._collection.query(
                query_embeddings=[vec.tolist()],
                n_results=top_k,
                where=where,
                include=["metadatas", "distances", "embeddings"],
            )
        except Exception as exc:
            logger.error("ChromaDB query failed: %s", exc)
            return []

        out = []
        for i, uid in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            dist = results["distances"][0][i]
            emb = results["embeddings"][0][i]
            out.append(
                SimilarWindow(
                    window_id=uid,
                    symbol=meta.get("symbol", ""),
                    timeframe=meta.get("timeframe", ""),
                    timestamp=meta.get("timestamp", ""),
                    regime=meta.get("regime", "unknown"),
                    next_return=float(meta.get("next_return", 0.0)),
                    distance=float(dist),
                    features=emb,
                )
            )
        return out

    def rag_context_for_llm(
        self,
        candles: list[dict],
        top_k: int = 5,
    ) -> str:
        """
        Return a formatted string suitable for injecting into an LLM prompt.

        Example output
        --------------
        ## Similar Historical Regimes (RAG context)
        1. 2022-03-15 XAU_USD H1 | regime=trending_up | next_bar_return=+0.42%
        2. 2022-08-03 XAU_USD H1 | regime=ranging     | next_bar_return=-0.11%
        ...
        Average next-bar return across similar regimes: +0.18%
        """
        windows = self.query_similar_regimes(candles, top_k=top_k)
        if not windows:
            return "No similar historical regimes found in vector store."

        lines = ["## Similar Historical Regimes (RAG context)"]
        returns = []
        for i, w in enumerate(windows, 1):
            sign = "+" if w.next_return >= 0 else ""
            lines.append(
                f"{i}. {w.timestamp[:10]} {w.symbol} {w.timeframe} | "
                f"regime={w.regime} | "
                f"next_bar_return={sign}{w.next_return * 100:.2f}% | "
                f"similarity={1 - w.distance:.3f}"
            )
            returns.append(w.next_return)

        avg = float(np.mean(returns))
        sign = "+" if avg >= 0 else ""
        lines.append(f"\nAverage next-bar return across {len(windows)} similar regimes: {sign}{avg * 100:.2f}%")
        return "\n".join(lines)

    # ── stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        self._ensure_connected()
        count = self._collection.count()
        return {
            "collection": self.collection_name,
            "persist_dir": self.persist_dir,
            "documents": count,
            "feature_dims": 32,
            "window_size": _WINDOW,
        }
