# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ML Training Manager — tracks and manages ML training jobs.

Provides a live registry of running/completed training jobs backed by
the database SystemEvent table (same source as superadmin UI).  Supports
triggering new training runs via background threads.

Usage
-----
    from ml.training_manager import get_training_manager

    mgr = get_training_manager()
    jobs = mgr.list_jobs()           # → list of job dicts
    mgr.start_job("advanced_oos")    # → triggers retraining in background
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.model_paths import find_model_file

logger = logging.getLogger(__name__)

UTC = timezone.utc

# The RL agent is a stable-baselines3 zip under ``rl/`` rather than a pickle
# named after the model — every other known model is ``<name>.pkl``/``.pt``.
_RL_ARTIFACT = "rl/hopefx_ppo.zip"

_KNOWN_MODELS = [
    "advanced_oos",
    "lstm_signal",
    "rl_ppo",
    "hybrid_ensemble",
    "rf_macro",
    "xgb_macro",
]


def _job_from_event(rec: Any) -> dict[str, Any]:
    """Render a stored ``system_events`` row as a training-job dict.

    ``list_jobs`` and ``get_job`` each built this shape by hand, from columns
    that do not exist (``created_at``, ``status``, ``metadata``). One function,
    one mapping — see ``database/system_events.py`` for why the row looks the
    way it does.
    """
    payload = rec.payload
    return {
        "id": rec.ref_id,
        "model": rec.component,
        "status": rec.status or "completed",
        "started_at": rec.started_at,
        "finished_at": payload.get("finished_at"),
        "duration_s": payload.get("duration_s", 0),
        "metrics": payload.get("metrics", {}),
        "error": payload.get("error"),
    }


class TrainingJob:
    def __init__(
        self,
        job_id: str,
        model: str,
        status: str = "pending",
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_s: float = 0.0,
        metrics: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.job_id = job_id
        self.model = model
        self.status = status
        self.started_at = started_at or datetime.now(UTC).isoformat()
        self.finished_at = finished_at
        self.duration_s = duration_s
        self.metrics = metrics or {}
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.job_id,
            "model": self.model,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(self.duration_s, 1),
            "metrics": self.metrics,
            "error": self.error,
        }


class TrainingManager:
    """
    Manages ML training jobs — tracks active runs and persists history.

    History is read from the database SystemEvent table (event_type='ml_training').
    Active in-process jobs are tracked in-memory.
    """

    def __init__(self) -> None:
        self._active: dict[str, TrainingJob] = {}
        self._lock = threading.Lock()

    # ── Query ─────────────────────────────────────────────────────────────────

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Return recent training jobs (active + database history).

        Active in-memory jobs are returned first (most recent), followed by
        historical records from the SystemEvent table.
        """
        jobs: list[dict[str, Any]] = []

        # Active in-memory jobs first
        with self._lock:
            for job in self._active.values():
                jobs.append(job.to_dict())

        # Historical jobs from database
        try:
            from database.connection import get_db_manager

            db_mgr = get_db_manager()
            if db_mgr:
                with db_mgr.session() as db:
                    from database.system_events import read_events

                    for rec in read_events(db, event_type="ml_training", limit=limit):
                        # Don't duplicate active jobs
                        if rec.ref_id not in self._active:
                            jobs.append(_job_from_event(rec))
        except Exception as exc:
            logger.debug("TrainingManager.list_jobs db query: %s", exc)

        # If nothing from DB, include a status entry per known model
        if not jobs:
            jobs = self._static_model_status()

        return jobs[:limit]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return a single job by ID."""
        with self._lock:
            if job_id in self._active:
                return self._active[job_id].to_dict()
        try:
            from database.connection import get_db_manager

            db_mgr = get_db_manager()
            if db_mgr:
                with db_mgr.session() as db:
                    from database.system_events import read_events

                    # The job id lives in trace_id, not the BigInteger primary
                    # key — see database/system_events.py. The old lookup
                    # compared a UUID string against that integer PK.
                    for rec in read_events(db, event_type="ml_training", limit=200):
                        if rec.ref_id == job_id:
                            return _job_from_event(rec)
        except Exception as exc:
            logger.debug("TrainingManager.get_job: %s", exc)
        return None

    # ── Training control ──────────────────────────────────────────────────────

    def start_job(self, model: str) -> str:
        """
        Start an async training job for the given model.

        Supported model names: advanced_oos, lstm_signal, rl_ppo, hybrid_ensemble.
        Returns the job_id (UUID).
        """
        import uuid

        job_id = str(uuid.uuid4())
        job = TrainingJob(job_id=job_id, model=model, status="running")

        with self._lock:
            self._active[job_id] = job

        t = threading.Thread(
            target=self._run_training,
            args=(job_id, model),
            daemon=True,
            name=f"train-{model}-{job_id[:8]}",
        )
        t.start()
        logger.info("TrainingManager: started job %s for model %s", job_id, model)
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job. Returns True if the job was active."""
        with self._lock:
            job = self._active.get(job_id)
            if job and job.status == "running":
                job.status = "cancelled"
                job.finished_at = datetime.now(UTC).isoformat()
                return True
        return False

    # ── Internals ─────────────────────────────────────────────────────────────

    def _run_training(self, job_id: str, model: str) -> None:
        t0 = time.perf_counter()
        try:
            metrics = self._dispatch_training(model)
            elapsed = time.perf_counter() - t0
            with self._lock:
                if job_id in self._active:
                    job = self._active[job_id]
                    if job.status == "running":
                        job.status = "completed"
                        job.finished_at = datetime.now(UTC).isoformat()
                        job.duration_s = elapsed
                        job.metrics = metrics
            self._persist_job(job_id, model, "completed", elapsed, metrics, None)
            logger.info("TrainingManager: job %s completed in %.1fs metrics=%s", job_id, elapsed, metrics)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            with self._lock:
                if job_id in self._active:
                    job = self._active[job_id]
                    job.status = "failed"
                    job.finished_at = datetime.now(UTC).isoformat()
                    job.duration_s = elapsed
                    job.error = str(exc)
            self._persist_job(job_id, model, "failed", elapsed, {}, str(exc))
            logger.error("TrainingManager: job %s failed: %s", job_id, exc)

    def _dispatch_training(self, model: str) -> dict[str, Any]:
        """Dispatch to the appropriate training module and return metrics."""
        if model == "advanced_oos":
            from ml.train_advanced import retrain_advanced_predictor

            return retrain_advanced_predictor()
        if model == "lstm_signal":
            # ml/lstm_signal_layer.py is inference-only — _load, _build_sequence,
            # predict, stats, is_available. There is no training code in it, and
            # AGENTS.md's model table records this model as "Architecture
            # complete, not trained". This used to import a `retrain_lstm` that
            # does not exist, so the job failed with an ImportError naming a
            # symbol nobody can find.
            raise RuntimeError(
                "lstm_signal has no training implementation: ml/lstm_signal_layer.py "
                "is inference-only and the model has never been trained. Training it "
                "requires building a trainer (and PyTorch, which is optional here) — "
                "see the ML Models table in AGENTS.md."
            )

        if model in ("rf_macro", "xgb_macro"):
            # Both are listed in _KNOWN_MODELS, so the caller was told they were
            # valid, and then fell through to "Unknown model for training".
            raise RuntimeError(
                f"{model} is listed in _KNOWN_MODELS but _dispatch_training has no "
                f"branch for it, so it cannot be trained through this manager. "
                f"Either add a dispatch branch or remove it from _KNOWN_MODELS."
            )
        if model in ("rl_ppo", "rl"):
            from ml.rl_agent import RLAgent
            import pandas as pd
            from pathlib import Path
            import research.ta_compat  # noqa: F401

            df = pd.read_csv(Path("data/XAUUSD_40Y.csv"), parse_dates=["Date"])
            df = df.rename(columns={"Date": "timestamp"})
            df = df[df["timestamp"] >= "2018-01-01"]
            from ml.rl_agent import ForexTradingEnv

            env = ForexTradingEnv(df.to_dict("records"), initial_balance=10000.0)
            agent = RLAgent(model_name="hopefx_ppo")
            agent.train(env, timesteps=100_000, verbose=0)
            return {"status": "ok", "windows": len(env._features)}
        if model == "hybrid_ensemble":
            from ml.advanced_predictor import get_hybrid_predictor

            hyb = get_hybrid_predictor()
            status = hyb.component_status
            return {"meta_trained": status["meta_trained"]}
        raise ValueError(f"Unknown model for training: {model!r}. Known: {_KNOWN_MODELS}")

    def _persist_job(
        self,
        job_id: str,
        model: str,
        status: str,
        duration_s: float,
        metrics: dict,
        error: str | None,
    ) -> None:
        try:
            from database.connection import get_db_manager

            db_mgr = get_db_manager()
            if not db_mgr:
                return
            with db_mgr.session() as db:
                from database.system_events import upsert_event

                upsert_event(
                    db,
                    ref_id=job_id,
                    event_type="ml_training",
                    component=model,
                    status=status,
                    level="ERROR" if error else "INFO",
                    message=f"training {model}: {status}",
                    payload={
                        "duration_s": round(duration_s, 1),
                        "metrics": metrics,
                        "error": error,
                        "finished_at": datetime.now(UTC).isoformat(),
                    },
                )
                db.commit()
        except Exception as exc:
            logger.warning("TrainingManager._persist_job failed, run not recorded: %s", exc)

    def _static_model_status(self) -> list[dict[str, Any]]:
        """Return a status list read from saved model files when the DB is unavailable.

        This is the model inventory a fresh deployment shows before any training
        run is recorded, so a model may only be reported as ``completed`` when
        that model's own artifact exists.

        Two things were wrong here. The RL zip was checked for every model, so a
        repository containing ``rl/hopefx_ppo.zip`` — which this one does, it is
        committed — reported all six models trained, ``lstm_signal`` included,
        the one AGENTS.md records as never trained and ``_dispatch_training``
        refuses to train. Four of the six also carried the zip's mtime as their
        training time. And the directory was the hardcoded relative
        ``ml/saved_models``, which ignores ``ML_MODEL_DIR`` (production points it
        at a mounted volume, see the Helm chart) and resolves against whatever
        the process working directory happens to be.
        """
        import os

        rows = []
        for name in _KNOWN_MODELS:
            found = self._model_artifact(name)
            mtime = datetime.fromtimestamp(os.path.getmtime(found), UTC).isoformat() if found is not None else None
            rows.append(
                {
                    "id": f"static_{name}",
                    "model": name,
                    "status": "completed" if found is not None else "not_trained",
                    "started_at": mtime,
                    "finished_at": mtime,
                    "duration_s": 0,
                    "metrics": {},
                    "error": None,
                }
            )
        return rows

    @staticmethod
    def _model_artifact(name: str) -> Path | None:
        """Locate the artifact belonging to *name*, or None when it is absent.

        Resolution goes through ``ml.model_paths.find_model_file`` so that
        ``ML_MODEL_DIR`` wins and the packaged ``ml/saved_models`` is the
        fallback — the same order inference uses to pick the model it serves.
        """
        candidates = (_RL_ARTIFACT,) if name in ("rl_ppo", "rl") else (f"{name}.pkl", f"{name}.pt")
        for candidate in candidates:
            path = find_model_file(candidate)
            if path is not None:
                return path
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: TrainingManager | None = None
_manager_lock = threading.Lock()


def get_training_manager() -> TrainingManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = TrainingManager()
    return _manager
