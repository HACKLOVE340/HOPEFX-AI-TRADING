# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/hourly_trainer.py
====================
Hourly incremental ML model retraining pipeline.

Runs as a background asyncio task inside the FastAPI app (wired via
core/startup_factories.py → init_hourly_trainer). Also runnable as a
standalone script for manual or cron-triggered retraining.

Strategy
--------
Full retraining every N hours is expensive. This pipeline uses a two-tier
approach:

  Tier 1 — Online update (every hour, ~2 seconds):
    Feeds the last 24 bars to the OnlineLearner (SGD-based incremental
    model). No disk I/O beyond appending to the rolling buffer.

  Tier 2 — Full retrain (every FULL_RETRAIN_HOURS hours, default 24):
    Runs run_training.run_pipeline() on the full H1 CSV. Saves new weights
    to ml/models/{symbol}/. Triggers a live-inference reload so the signal
    engine picks up the new model without a restart.

Environment variables
---------------------
ML_HOURLY_ENABLED          — "true" to enable (default: false in dev)
ML_HOURLY_INTERVAL_SECONDS — online update interval (default: 3600)
ML_FULL_RETRAIN_HOURS      — full retrain every N hours (default: 24)
ML_SYMBOLS                 — comma-separated symbols (default: XAU_USD)
ML_MODEL_DIR               — model output directory (default: ml/models)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_ENABLED = os.getenv("ML_HOURLY_ENABLED", "false").lower() in ("true", "1", "yes")
_INTERVAL_SECS = int(os.getenv("ML_HOURLY_INTERVAL_SECONDS", "3600"))
_FULL_RETRAIN_HRS = int(os.getenv("ML_FULL_RETRAIN_HOURS", "24"))
_SYMBOLS = [s.strip() for s in os.getenv("ML_SYMBOLS", "XAU_USD").split(",") if s.strip()]
_MODEL_DIR = os.getenv("ML_MODEL_DIR", "ml/models")


class HourlyTrainer:
    """
    Manages the two-tier hourly ML training loop.

    Attributes
    ----------
    enabled          : Whether the trainer is active (from ML_HOURLY_ENABLED)
    interval_secs    : Seconds between online update cycles
    full_retrain_hrs : Hours between full retrains
    symbols          : List of instrument codes to train on
    model_dir        : Root directory for saved model weights
    """

    def __init__(
        self,
        enabled: bool = _ENABLED,
        interval_secs: int = _INTERVAL_SECS,
        full_retrain_hrs: int = _FULL_RETRAIN_HRS,
        symbols: list[str] | None = None,
        model_dir: str = _MODEL_DIR,
    ) -> None:
        self.enabled = enabled
        self.interval_secs = interval_secs
        self.full_retrain_hrs = full_retrain_hrs
        self.symbols = symbols or _SYMBOLS
        self.model_dir = model_dir

        self._last_full_retrain: dict[str, float] = {}  # symbol → epoch
        self._online_update_count: int = 0
        self._full_retrain_count: int = 0
        self._running: bool = False
        self._task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background training loop."""
        if not self.enabled:
            logger.info(
                "HourlyTrainer disabled — set ML_HOURLY_ENABLED=true to enable. "
                "Online updates and hourly retraining will not run.",
            )
            return

        logger.info(
            "HourlyTrainer starting: symbols=%s interval=%ds full_retrain_every=%dh",
            self.symbols,
            self.interval_secs,
            self.full_retrain_hrs,
        )
        self._running = True
        await self._loop()

    async def stop(self) -> None:
        """Signal the loop to stop after the current cycle."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def status(self) -> dict[str, Any]:
        """Return current trainer state for the admin dashboard."""
        return {
            "enabled": self.enabled,
            "running": self._running,
            "interval_secs": self.interval_secs,
            "full_retrain_hrs": self.full_retrain_hrs,
            "symbols": self.symbols,
            "online_update_count": self._online_update_count,
            "full_retrain_count": self._full_retrain_count,
            "last_full_retrain": {
                sym: datetime.fromtimestamp(ts, tz=UTC).isoformat() for sym, ts in self._last_full_retrain.items()
            },
        }

    # ── Internal loop ─────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("HourlyTrainer cycle error: %s")

            elapsed = time.monotonic() - cycle_start
            sleep_secs = max(0.0, self.interval_secs - elapsed)
            logger.debug(
                "HourlyTrainer cycle done in %.1fs — sleeping %.0fs",
                elapsed,
                sleep_secs,
            )
            try:
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                break

    async def _run_cycle(self) -> None:
        """Execute one training cycle for all symbols."""
        now = time.time()
        for symbol in self.symbols:
            try:
                await self._online_update(symbol)
                self._online_update_count += 1

                last_full = self._last_full_retrain.get(symbol, 0.0)
                hours_since = (now - last_full) / 3600
                if hours_since >= self.full_retrain_hrs:
                    await self._full_retrain(symbol)
                    self._last_full_retrain[symbol] = now
                    self._full_retrain_count += 1
            except Exception as exc:
                logger.warning("HourlyTrainer: error for %s: %s", symbol, exc)

    async def _online_update(self, symbol: str) -> None:
        """
        Feed the last 24 H1 bars to the OnlineLearner.

        This is a lightweight incremental update (~2 seconds) that keeps
        the model current without a full retrain.
        """
        try:
            from ml.online_learner import get_online_learner

            learner = get_online_learner(symbol)
            if learner is None:
                return

            bars = await self._fetch_recent_bars(symbol, n=24)
            if bars is None or len(bars) < 5:
                logger.debug(
                    "OnlineUpdate %s: insufficient bars (%s)",
                    symbol,
                    len(bars) if bars is not None else 0,
                )
                return

            learner.partial_fit(bars)
            logger.debug("OnlineUpdate %s: fed %d bars to OnlineLearner", symbol, len(bars))
        except ImportError:
            logger.debug("OnlineLearner not available — skipping online update for %s", symbol)
        except Exception as exc:
            logger.warning("OnlineUpdate %s failed: %s", symbol, exc)

    async def _full_retrain(self, symbol: str) -> None:
        """
        Run the full training pipeline for one symbol.

        Executes in a thread pool to avoid blocking the event loop.
        After training, triggers a live-inference model reload.
        """
        logger.info("HourlyTrainer: starting full retrain for %s", symbol)
        t0 = time.monotonic()

        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(
                None,
                self._run_pipeline_sync,
                symbol,
            )
            elapsed = time.monotonic() - t0
            model_names = list(results.keys()) if results else []
            logger.info(
                "HourlyTrainer: full retrain complete for %s in %.1fs — models: %s",
                symbol,
                elapsed,
                model_names,
            )

            # Reload live inference so the signal engine picks up new weights
            await self._reload_live_inference(symbol)

        except Exception as exc:
            logger.error(
                "HourlyTrainer: full retrain failed for %s: %s",
                symbol,
                exc,
                exc_info=True,
            )

    def _run_pipeline_sync(self, symbol: str) -> dict[str, Any]:
        """Synchronous wrapper around run_training.run_pipeline (runs in thread)."""
        from ml.run_training import run_pipeline

        return run_pipeline(
            symbol=symbol,
            model_types=["random_forest", "xgboost"],
            model_dir=self.model_dir,
        )

    async def _reload_live_inference(self, symbol: str) -> None:
        """Reload the live inference model after a full retrain."""
        try:
            from ml.live_inference import AdvancedModelPredictor

            model_path = Path(self.model_dir) / f"{symbol}_advanced_oos.pkl"
            infer = AdvancedModelPredictor(model_path=model_path if model_path.exists() else None)
            infer._load()  # pylint: disable=protected-access
            logger.info("LiveInference reloaded for %s", symbol)
        except Exception as exc:
            logger.warning("LiveInference reload failed for %s: %s", symbol, exc)

    async def _fetch_recent_bars(self, symbol: str, n: int = 24):
        """Fetch the last N H1 bars from the local CSV."""
        try:
            import pandas as pd

            csv_path = Path(f"data/{symbol}_H1.csv")
            if not csv_path.exists():
                return None
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            df.columns = [c.lower() for c in df.columns]
            return df.tail(n)
        except Exception as exc:
            logger.debug("_fetch_recent_bars %s: %s", symbol, exc)
            return None


# ── Module-level singleton ────────────────────────────────────────────────────

_hourly_trainer: HourlyTrainer | None = None


def get_hourly_trainer() -> HourlyTrainer:
    """Return the module-level HourlyTrainer singleton (created on first call)."""
    global _hourly_trainer
    if _hourly_trainer is None:
        _hourly_trainer = HourlyTrainer()
    return _hourly_trainer


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    _ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_ROOT))

    try:
        from dotenv import load_dotenv

        load_dotenv(_ROOT / ".env")
    except ImportError:
        ...  # nosec B110

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="HOPEFX hourly ML trainer")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--symbol", default=None, help="Override ML_SYMBOLS")
    parser.add_argument("--full-retrain", action="store_true", help="Force a full retrain now")
    args = parser.parse_args()

    _run_symbols = [args.symbol] if args.symbol else _SYMBOLS
    trainer = HourlyTrainer(enabled=True, symbols=_run_symbols)

    async def _main():
        if args.full_retrain:
            for sym in _run_symbols:
                await trainer._full_retrain(sym)
        elif args.once:
            await trainer._run_cycle()
        else:
            await trainer.start()

    asyncio.run(_main())
