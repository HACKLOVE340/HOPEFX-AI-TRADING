# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
celery_app.py — Optional Celery worker for periodic background tasks.

The FastAPI app runs all background jobs as asyncio tasks by default.
This module provides a Celery application so operators can optionally
offload periodic work to dedicated Celery workers + Beat scheduler,
which is preferable in multi-pod deployments.

Usage
-----
Install Celery (already in requirements-optional.txt):
    pip install "celery[redis]>=5.4.0"

Start the worker:
    celery -A celery_app worker --loglevel=info --concurrency=4

Start the Beat scheduler (periodic tasks):
    celery -A celery_app beat --loglevel=info

Or combined (single-process, dev only):
    celery -A celery_app worker --beat --loglevel=info

Environment variables
---------------------
CELERY_BROKER_URL    — Redis broker URL (default: redis://localhost:6379/1)
CELERY_RESULT_BACKEND — Redis result backend (default: redis://localhost:6379/2)
CELERY_TASK_ALWAYS_EAGER — "true" to run tasks synchronously in tests

Periodic schedule (Celery Beat)
--------------------------------
Task                          Schedule        Description
----                          --------        -----------
ml_hourly_online_update       every 1 h       Incremental online-learning update
ml_daily_full_retrain         every 24 h      Full model retrain + weight reload
subscription_expiry_check     every 1 h       Downgrade expired subscriptions to free
affiliate_commission_payout   every 24 h      Process pending affiliate payouts
pnl_reconciliation            every 6 h       P&L reconciliation gate check
database_backup               every 24 h      Trigger DB backup snapshot
self_healer_scan              every 5 min     SelfHealer anomaly scan
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

logger = logging.getLogger(__name__)

# ── Celery import guard ───────────────────────────────────────────────────────

try:
    from celery import Celery
    from celery.schedules import crontab

    _CELERY_AVAILABLE = True
except ImportError:
    _CELERY_AVAILABLE = False
    logger.warning(
        "celery package not installed — periodic tasks will run as asyncio tasks. "
        "Install with: pip install 'celery[redis]>=5.4.0'"
    )

# ── Configuration ─────────────────────────────────────────────────────────────

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() in ("true", "1")

# ── App factory ───────────────────────────────────────────────────────────────

if _CELERY_AVAILABLE:
    app = Celery(
        "hopefx",
        broker=BROKER_URL,
        backend=RESULT_BACKEND,
        include=["celery_app"],
    )

    app.conf.update(
        # ── Serialisation ─────────────────────────────────────────────────────
        # json only — never pickle.  Pickle allows arbitrary code execution
        # if the broker is compromised; json is safe and human-readable.
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Compress task payloads with gzip.  ML retrain tasks carry feature
        # arrays that can be several MB; compression cuts broker traffic ~70 %.
        # Workers must have the same setting to decompress results.
        task_compression="gzip",
        result_compression="gzip",

        # ── Timezone ──────────────────────────────────────────────────────────
        timezone="UTC",
        enable_utc=True,

        # ── Reliability ───────────────────────────────────────────────────────
        # task_acks_late: acknowledge only after the task completes so a
        #   worker crash re-queues the task rather than losing it.
        # task_reject_on_worker_lost: re-queue (not discard) when a worker
        #   process is killed mid-task (OOM, SIGKILL).
        # worker_prefetch_multiplier=1: fetch one task at a time so long-
        #   running ML tasks don't starve short billing/infra tasks.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,

        # worker_max_tasks_per_child: recycle the worker subprocess after N
        #   tasks to reclaim memory leaked by ML libraries (numpy, torch).
        #   Set via CELERY_MAX_TASKS_PER_CHILD; default 200 is conservative
        #   enough to prevent OOM on 2 GB workers without excessive fork cost.
        worker_max_tasks_per_child=int(
            os.getenv("CELERY_MAX_TASKS_PER_CHILD", "200")
        ),

        # ── Broker transport options ───────────────────────────────────────────
        # visibility_timeout: how long (seconds) a task can run before the
        #   broker re-queues it as "lost".  Must be longer than the slowest
        #   task (ml_daily_full_retrain can take ~30 min).  Default 1 h.
        # max_retries: number of broker reconnect attempts before giving up.
        # interval_start / interval_step / interval_max: exponential backoff
        #   for broker reconnects (0 s → 0.2 s → 0.4 s … → 2 s max).
        broker_transport_options={
            "visibility_timeout": int(
                os.getenv("CELERY_VISIBILITY_TIMEOUT", str(3600))
            ),
            "max_retries": 5,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 2.0,
        },

        # ── Result backend ────────────────────────────────────────────────────
        result_expires=timedelta(hours=24),

        # result_chord_join_timeout: seconds to wait for all chord subtasks
        #   before the chord callback fires.  Prevents chord callbacks from
        #   hanging indefinitely when a subtask is slow or lost.
        result_chord_join_timeout=int(
            os.getenv("CELERY_CHORD_JOIN_TIMEOUT", "300")  # 5 min
        ),

        # ── Queue routing ─────────────────────────────────────────────────────
        # Each task family gets its own queue so workers can be scaled
        # independently (e.g. more ML workers, fewer infra workers).
        task_routes={
            "celery_app.ml_hourly_online_update": {"queue": "ml"},
            "celery_app.ml_daily_full_retrain": {"queue": "ml"},
            "celery_app.subscription_expiry_check": {"queue": "billing"},
            "celery_app.affiliate_commission_payout": {"queue": "billing"},
            "celery_app.pnl_reconciliation": {"queue": "risk"},
            "celery_app.database_backup": {"queue": "infra"},
            "celery_app.self_healer_scan": {"queue": "infra"},
        },

        # ── Test mode ─────────────────────────────────────────────────────────
        # task_always_eager=True makes tasks run synchronously in the calling
        # process — no broker required.  Set CELERY_TASK_ALWAYS_EAGER=true
        # in test environments.
        task_always_eager=ALWAYS_EAGER,
        # Beat schedule
        beat_schedule={
            # ── ML ────────────────────────────────────────────────────────────
            "ml-hourly-online-update": {
                "task": "celery_app.ml_hourly_online_update",
                "schedule": timedelta(hours=1),
                "options": {"queue": "ml"},
            },
            "ml-daily-full-retrain": {
                "task": "celery_app.ml_daily_full_retrain",
                "schedule": crontab(hour=2, minute=0),  # 02:00 UTC daily
                "options": {"queue": "ml"},
            },
            # ── Billing ───────────────────────────────────────────────────────
            "subscription-expiry-check": {
                "task": "celery_app.subscription_expiry_check",
                "schedule": timedelta(hours=1),
                "options": {"queue": "billing"},
            },
            "affiliate-commission-payout": {
                "task": "celery_app.affiliate_commission_payout",
                "schedule": crontab(hour=3, minute=0),  # 03:00 UTC daily
                "options": {"queue": "billing"},
            },
            # ── Risk / compliance ─────────────────────────────────────────────
            "pnl-reconciliation": {
                "task": "celery_app.pnl_reconciliation",
                "schedule": timedelta(hours=6),
                "options": {"queue": "risk"},
            },
            # ── Infrastructure ────────────────────────────────────────────────
            "database-backup": {
                "task": "celery_app.database_backup",
                "schedule": crontab(hour=1, minute=0),  # 01:00 UTC daily
                "options": {"queue": "infra"},
            },
            "self-healer-scan": {
                "task": "celery_app.self_healer_scan",
                "schedule": timedelta(minutes=5),
                "options": {"queue": "infra"},
            },
        },
    )
else:
    # Provide a no-op stub so imports don't fail when Celery is absent.
    class _NoOpCelery:  # type: ignore[no-redef]
        def task(self, *args, **kwargs):
            def decorator(fn):
                return fn

            return decorator

        def conf(self):
            """No-op configuration accessor for the null Celery stub."""
            return None

    app = _NoOpCelery()  # type: ignore[assignment]


# ── Task decorator helper ─────────────────────────────────────────────────────


def _task(**kwargs):
    """Return app.task decorator, or a no-op if Celery is unavailable."""
    if _CELERY_AVAILABLE:
        return app.task(bind=True, max_retries=3, default_retry_delay=60, **kwargs)
    return lambda fn: fn


# ── ML tasks ─────────────────────────────────────────────────────────────────


@_task(name="celery_app.ml_hourly_online_update", queue="ml")
def ml_hourly_online_update(self=None):
    """
    Incremental online-learning update for all configured symbols.

    Feeds the last 24 bars to the OnlineLearner (SGD-based incremental
    model). Runs in ~2 seconds per symbol.
    """
    import asyncio

    try:
        from ml.hourly_trainer import HourlyTrainer

        trainer = HourlyTrainer()
        if not trainer.enabled:
            logger.info("ML hourly trainer disabled (ML_HOURLY_ENABLED not set)")
            return {"status": "disabled"}
        asyncio.run(trainer.run_online_update())
        return {"status": "ok"}
    except Exception as exc:
        logger.error("ml_hourly_online_update failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


@_task(name="celery_app.ml_daily_full_retrain", queue="ml")
def ml_daily_full_retrain(self=None):
    """
    Full model retrain on the complete historical dataset.

    Runs run_training.run_pipeline() for each symbol, saves new weights,
    and triggers a live-inference reload so the signal engine picks up
    the new model without a restart.
    """
    import asyncio

    try:
        from ml.hourly_trainer import HourlyTrainer

        trainer = HourlyTrainer()
        asyncio.run(trainer.run_full_retrain())
        return {"status": "ok"}
    except Exception as exc:
        logger.error("ml_daily_full_retrain failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


# ── Billing tasks ─────────────────────────────────────────────────────────────


@_task(name="celery_app.subscription_expiry_check", queue="billing")
def subscription_expiry_check(self=None):
    """
    Scan all subscriptions and downgrade expired ones to the free tier.

    Uses the SubscriptionManager to find expired subscriptions and
    updates their tier in both the database and Stripe.
    """
    try:
        from database.connection import SessionLocal
        from monetization.subscription import SubscriptionManager, SubscriptionTier

        db = SessionLocal()
        try:
            mgr = SubscriptionManager()
            expired = mgr.get_expired_subscriptions()
            downgraded = 0
            for sub in expired:
                try:
                    mgr.update_subscription(
                        user_id=sub.user_id,
                        new_tier=SubscriptionTier.FREE,
                        reason="subscription_expired",
                    )
                    downgraded += 1
                except Exception as exc:
                    logger.warning("Failed to downgrade user %s: %s", sub.user_id, exc)
            logger.info("subscription_expiry_check: downgraded %d subscriptions", downgraded)
            return {"status": "ok", "downgraded": downgraded}
        finally:
            db.close()
    except Exception as exc:
        logger.error("subscription_expiry_check failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


@_task(name="celery_app.affiliate_commission_payout", queue="billing")
def affiliate_commission_payout(self=None):
    """
    Process pending affiliate commission payouts.

    Finds affiliates with unpaid commissions above the minimum payout
    threshold and triggers the payout via the configured payment provider.
    """
    try:
        from monetization.affiliate import AffiliateManager

        mgr = AffiliateManager()
        result = mgr.process_pending_payouts()
        paid_count = result.get("paid_count", 0)
        total_paid = result.get("total_paid_usd", 0.0)
        logger.info(
            "affiliate_commission_payout: paid %d affiliates, total $%.2f",
            paid_count,
            total_paid,
        )
        return {"status": "ok", "paid_count": paid_count, "total_paid_usd": total_paid}
    except Exception as exc:
        logger.error("affiliate_commission_payout failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


# ── Risk / compliance tasks ───────────────────────────────────────────────────


@_task(name="celery_app.pnl_reconciliation", queue="risk")
def pnl_reconciliation(self=None):
    """
    Run the P&L reconciliation gate check.

    Compares model-predicted P&L against actual broker fills. Writes a
    snapshot to data/pnl_reconciliation.json and publishes Prometheus
    metrics. Blocks model promotion if the gate fails.
    """
    import asyncio

    try:
        from ml.pnl_reconciler import get_reconciler

        reconciler = get_reconciler()
        result = asyncio.run(reconciler.reconcile())
        logger.info(
            "pnl_reconciliation: passed=%s drift=%.4f",
            result.passed,
            result.drift_pct,
        )
        return {
            "status": "ok",
            "passed": result.passed,
            "drift_pct": result.drift_pct,
        }
    except Exception as exc:
        logger.error("pnl_reconciliation failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


# ── Infrastructure tasks ──────────────────────────────────────────────────────


@_task(name="celery_app.database_backup", queue="infra")
def database_backup(self=None):
    """
    Trigger a database backup snapshot.

    Calls the DatabaseBackupManager to create a compressed snapshot and
    upload it to the configured object store (S3 / GCS / local).
    """
    import asyncio

    try:
        from database.backup import DatabaseBackupManager

        mgr = DatabaseBackupManager()
        result = asyncio.run(mgr.create_backup())
        logger.info("database_backup: %s", result)
        return {"status": "ok", "backup": result}
    except Exception as exc:
        logger.error("database_backup failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


@_task(name="celery_app.self_healer_scan", queue="infra")
def self_healer_scan(self=None):
    """
    Run a SelfHealer anomaly scan.

    Checks all registered health monitors and triggers auto-remediation
    actions for any that are in a degraded state.
    """
    import asyncio

    try:
        from core.self_healer import get_self_healer

        healer = get_self_healer()
        result = asyncio.run(healer.scan())
        actions = result.get("actions_taken", [])
        if actions:
            logger.info("self_healer_scan: took %d actions: %s", len(actions), actions)
        return {"status": "ok", "actions_taken": len(actions)}
    except Exception as exc:
        logger.error("self_healer_scan failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


# ── Health-check registration ─────────────────────────────────────────────────


def register_celery_health(redis_client) -> None:
    """
    Write a heartbeat key to Redis so the superadmin health check can
    detect whether a Celery worker is alive.

    Called from the worker's ``worker_ready`` signal.
    """
    if not _CELERY_AVAILABLE:
        return
    try:
        from celery.signals import worker_ready, worker_shutdown

        @worker_ready.connect
        def on_worker_ready(sender, **kwargs):
            try:
                redis_client.set("celery:active_workers", "1", ex=300)
                logger.info("Celery worker registered in Redis health store")
            except Exception as exc:
                logger.warning("Failed to register Celery worker in Redis: %s", exc)

        @worker_shutdown.connect
        def on_worker_shutdown(sender, **kwargs):
            try:
                redis_client.delete("celery:active_workers")
            except Exception:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

    except Exception as exc:
        logger.warning("Celery signal registration failed: %s", exc)


# ── Standalone entry point ────────────────────────────────────────────────────

# Public alias — callers that do `from celery_app import celery_app` receive
# the same object as `from celery_app import app`.
celery_app = app


if __name__ == "__main__":
    if not _CELERY_AVAILABLE:
        print("Celery is not installed. Run: pip install 'celery[redis]>=5.4.0'")
        raise SystemExit(1)
    app.start()
