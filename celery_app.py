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

import contextlib
import logging
import os
from datetime import timedelta

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _redis_lock(name: str, timeout: int = 3600):
    """Context manager: acquire a Redis SET NX distributed lock.

    Raises RuntimeError when the lock is already held so the caller
    can detect concurrent execution and exit early. Yields without
    locking when Redis is unavailable (dev/test environments).

    Args:
        name:    Lock key suffix (e.g. "ml_train").
        timeout: Lock TTL in seconds.  MUST be strictly greater than the
                 Celery task's ``time_limit`` — if the lock expires before
                 the task finishes, a second instance can start concurrently.
                 Rule: timeout = time_limit + 60 (minimum safe buffer).
    """
    try:
        import redis as _redis_mod  # type: ignore[import-untyped]

        _r = _redis_mod.from_url(os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"), socket_timeout=5)
        acquired = _r.set(f"celery_lock:{name}", "1", nx=True, ex=timeout)
        if not acquired:
            raise RuntimeError(f"celery_lock:{name} already held — skipping concurrent task")
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                _r.delete(f"celery_lock:{name}")
    except ImportError:
        yield  # Redis unavailable in test/dev — proceed without locking


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


def _redis_url_with_db(db: int) -> str:
    """Default a Celery URL from REDIS_URL, swapping in *db*.

    The literal defaults were ``redis://localhost:6379/1`` and ``/2``.
    docker-compose sets CELERY_BROKER_URL on the ``celery-worker`` and
    ``celery-beat`` services but **not** on ``app`` — so inside the app
    container the variable is unset, "localhost" means the app container
    itself, and nothing listens there. The deployed Reliability page showed:

        Celery Task Queue   WARNING
        Celery inspect failed: Error 111 connecting to localhost:6379.
        Connection refused.

    while every other component reached ``redis:6379`` perfectly well. The app
    always has REDIS_URL, so derive from it: one correctly-configured variable
    is enough, and adding a service to compose cannot silently miss this again.
    """
    raw = os.getenv("REDIS_URL", "").strip()
    if not raw:
        return f"redis://localhost:6379/{db}"
    base, _, _ = raw.partition("?")
    scheme_sep = base.find("://")
    if scheme_sep == -1:
        return f"redis://localhost:6379/{db}"
    host_part = base[scheme_sep + 3 :]
    # Strip any existing /<db> suffix, taking care not to cut into credentials.
    slash = host_part.rfind("/")
    if slash != -1 and host_part[slash + 1 :].isdigit():
        host_part = host_part[:slash]
    return f"{base[:scheme_sep]}://{host_part}/{db}"


BROKER_URL = os.getenv("CELERY_BROKER_URL") or _redis_url_with_db(1)
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND") or _redis_url_with_db(2)
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
        worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "200")),
        # ── Broker transport options ───────────────────────────────────────────
        # visibility_timeout: how long (seconds) a task can run before the
        #   broker re-queues it as "lost".  Must be longer than the slowest
        #   task (ml_daily_full_retrain can take ~30 min).  Default 1 h.
        # max_retries: number of broker reconnect attempts before giving up.
        # interval_start / interval_step / interval_max: exponential backoff
        #   for broker reconnects (0 s → 0.2 s → 0.4 s … → 2 s max).
        broker_transport_options={
            "visibility_timeout": int(os.getenv("CELERY_VISIBILITY_TIMEOUT", str(3600))),
            "max_retries": 5,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 2.0,
            # ── Idle-connection survival ──────────────────────────────────────
            # The Redis service runs with `--timeout 300`: it closes any
            # connection that has been idle for five minutes. A Celery control
            # connection from the app container is idle far longer than that —
            # nothing uses it until an operator opens a health page — so by the
            # time inspect() runs, the server has already hung up. The client
            # only discovers it on write, which fails instantly.
            #
            # That is the "Celery: DOWN, RuntimeError" at 8ms on System Health
            # and "Celery inspect failed: Connection closed by server" on
            # Reliability. Both were correct. The 8ms is the tell: a 2-second
            # inspect timeout that fails in 8ms never waited for anything, it
            # wrote to a socket the server had closed.
            #
            # health_check_interval makes redis-py PING a connection that has
            # been idle this long before handing it out, which both refreshes
            # the server's idle timer and detects a dead socket early enough to
            # reconnect transparently. It must stay comfortably below the
            # server's timeout.
            "socket_keepalive": True,
            "retry_on_timeout": True,
            "health_check_interval": int(os.getenv("CELERY_HEALTH_CHECK_INTERVAL", "60")),
        },
        result_backend_transport_options={
            "socket_keepalive": True,
            "retry_on_timeout": True,
            "health_check_interval": int(os.getenv("CELERY_HEALTH_CHECK_INTERVAL", "60")),
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
                "schedule": crontab(hour=22, minute=30),  # 22:30 UTC — post-US close, pre-Asia open
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

    class _NoOpInspect:
        """Returned by _NoOpControl.inspect() — all methods return None.

        Callers (reliability.py, system_health.py, health_engine.py) already
        guard against None returns, so this degrades gracefully to a
        "no workers" / "warning" status rather than raising AttributeError.
        """

        def stats(self) -> None:
            return None

        def active(self) -> None:
            return None

        def registered(self) -> None:
            return None

        def ping(self) -> None:
            return None

        def active_queues(self) -> None:
            return None

        def reserved(self) -> None:
            return None

        def scheduled(self) -> None:
            return None

        def revoked(self) -> None:
            return None

        def conf(self) -> None:
            return None

        def report(self) -> None:
            return None

    class _NoOpControl:
        """Stub for celery_app.control when Celery is not installed."""

        def inspect(self, timeout: float = 1.0, destination: list | None = None) -> _NoOpInspect:
            return _NoOpInspect()

        def broadcast(self, command: str, **kwargs) -> None:
            logger.debug("_NoOpControl.broadcast: Celery not installed, ignoring command=%s", command)

        def revoke(self, task_id: str, **kwargs) -> None:
            logger.debug("_NoOpControl.revoke: Celery not installed, ignoring task_id=%s", task_id)

        def purge(self) -> int:
            return 0

        def rate_limit(self, task_name: str, rate_limit: str, **kwargs) -> None:
            logger.debug("_NoOpControl.rate_limit: Celery not installed, ignoring task=%s", task_name)

        def time_limit(self, task_name: str, **kwargs) -> None:
            logger.debug("_NoOpControl.time_limit: Celery not installed, ignoring task=%s", task_name)

        def ping(self, destination: list | None = None, timeout: float = 1.0) -> list:
            return []

    class _NoOpCelery:  # type: ignore[no-redef]
        """Minimal Celery stub used when the celery package is not installed.

        Exposes the subset of the Celery API used by this codebase so all
        callers can import and call methods without conditional guards.
        """

        def __init__(self) -> None:
            self.control = _NoOpControl()

        def task(self, *args, **kwargs):
            def decorator(fn):
                return fn

            return decorator

        def conf(self):
            """No-op configuration accessor for the null Celery stub."""
            return None

        def send_task(self, name: str, *args, **kwargs) -> None:
            logger.debug("Celery not installed — send_task(%s) is a no-op", name)

        def signature(self, *args, **kwargs):
            return None

    app = _NoOpCelery()  # type: ignore[assignment]


# ── Task decorator helper ─────────────────────────────────────────────────────


def _task(**kwargs):
    """Return app.task decorator, or a no-op if Celery is unavailable."""
    if _CELERY_AVAILABLE:
        return app.task(bind=True, max_retries=3, default_retry_delay=60, **kwargs)
    return lambda fn: fn


# ── ML tasks ─────────────────────────────────────────────────────────────────


@_task(name="celery_app.ml_hourly_online_update", queue="ml", soft_time_limit=300, time_limit=360)
def ml_hourly_online_update(self=None):
    """
    Incremental online-learning update for all configured symbols.

    Feeds the last 24 bars to the OnlineLearner (SGD-based incremental
    model). Runs in ~2 seconds per symbol.
    """
    import asyncio

    try:
        # Lock TTL must exceed time_limit (360 s) so the lock does not expire
        # while the task is still running.  Use time_limit + 60 s buffer.
        with _redis_lock("ml_train", timeout=420):
            from ml.hourly_trainer import HourlyTrainer

            trainer = HourlyTrainer()
            if not trainer.enabled:
                logger.info("ML hourly trainer disabled (ML_HOURLY_ENABLED not set)")
                return {"status": "disabled"}
            asyncio.run(trainer.run_online_update())
        return {"status": "ok"}
    except RuntimeError as exc:
        if "already held" in str(exc):
            logger.info("ml_hourly_online_update skipped — ml_train lock already held by another task")
            return {"status": "skipped", "reason": "concurrent_lock"}
        raise
    except Exception as exc:
        logger.error("ml_hourly_online_update failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


@_task(name="celery_app.ml_daily_full_retrain", queue="ml", soft_time_limit=3600, time_limit=4200)
def ml_daily_full_retrain(self=None):
    """
    Full model retrain on the complete historical dataset.

    Runs run_training.run_pipeline() for each symbol, saves new weights,
    and triggers a live-inference reload so the signal engine picks up
    the new model without a restart.
    """
    import asyncio

    try:
        # Lock TTL must exceed time_limit so the lock does not expire while
        # the task is still running (which would allow a second instance to
        # start).  Use time_limit + 60 s as the minimum safe buffer.
        with _redis_lock("ml_train", timeout=4260):
            from ml.hourly_trainer import HourlyTrainer

            trainer = HourlyTrainer()
            asyncio.run(trainer.run_full_retrain())

            # Refresh the registry digest for the active model so that
            # verify_active() reflects the newly written artifact.
            # Without this, every integrity check after retrain reports
            # a SHA-256 mismatch against the stale pre-retrain digest.
            try:
                from ml.model_registry import get_registry

                reg = get_registry()
                active = reg.active_version()
                if active:
                    new_digest = reg.refresh_digest(active["name"])
                    logger.info(
                        "ml_daily_full_retrain: registry digest refreshed for '%s' — %s…",
                        active["name"],
                        new_digest[:16],
                    )
                else:
                    logger.warning(
                        "ml_daily_full_retrain: retrain complete but no active version in "
                        "registry — run registry.register() to add the new artifact."
                    )
            except Exception as reg_exc:
                logger.error("ml_daily_full_retrain: failed to refresh registry digest: %s", reg_exc)

        return {"status": "ok"}
    except RuntimeError as exc:
        if "already held" in str(exc):
            logger.info("ml_daily_full_retrain skipped — ml_train lock already held by another task")
            return {"status": "skipped", "reason": "concurrent_lock"}
        raise
    except Exception as exc:
        logger.error("ml_daily_full_retrain failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


# ── Billing tasks ─────────────────────────────────────────────────────────────


@_task(name="celery_app.subscription_expiry_check", queue="billing", soft_time_limit=120, time_limit=180)
def subscription_expiry_check(self=None):
    """
    Scan all subscriptions and downgrade expired ones to the free tier.

    Uses the SubscriptionManager to find expired subscriptions and
    updates their tier in both the database and Stripe.
    """
    try:
        # Lock TTL must exceed time_limit (180 s) so the lock does not expire
        # while the task is still running.  Use time_limit + 60 s buffer.
        with _redis_lock("subscription_expiry", timeout=240):
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
    except RuntimeError as exc:
        if "already held" in str(exc):
            logger.info("subscription_expiry_check skipped — already running")
            return {"status": "skipped", "reason": "concurrent_lock"}
        raise
    except Exception as exc:
        logger.error("subscription_expiry_check failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


@_task(name="celery_app.affiliate_commission_payout", queue="billing", soft_time_limit=300, time_limit=360)
def affiliate_commission_payout(self=None):
    """
    Process pending affiliate commission payouts.

    Finds affiliates with unpaid commissions above the minimum payout
    threshold and triggers the payout via the configured payment provider.
    """
    try:
        # Lock TTL must exceed time_limit (360 s) so the lock does not expire
        # while the task is still running.  Use time_limit + 60 s buffer.
        with _redis_lock("affiliate_payout", timeout=420):
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
    except RuntimeError as exc:
        if "already held" in str(exc):
            logger.info("affiliate_commission_payout skipped — already running")
            return {"status": "skipped", "reason": "concurrent_lock"}
        raise
    except Exception as exc:
        logger.error("affiliate_commission_payout failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


# ── Risk / compliance tasks ───────────────────────────────────────────────────


@_task(name="celery_app.pnl_reconciliation", queue="risk", soft_time_limit=300, time_limit=360)
def pnl_reconciliation(self=None):
    """
    Run the P&L reconciliation gate check.

    Compares model-predicted P&L against actual broker fills. Writes a
    snapshot to data/pnl_reconciliation.json and publishes Prometheus
    metrics. Blocks model promotion if the gate fails.
    """
    import asyncio

    try:
        # Lock TTL must exceed time_limit (360 s) so the lock does not expire
        # while the task is still running.  Use time_limit + 60 s buffer.
        with _redis_lock("pnl_reconciliation", timeout=420):
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
    except RuntimeError as exc:
        if "already held" in str(exc):
            logger.info("pnl_reconciliation skipped — lock already held by another task")
            return {"status": "skipped", "reason": "concurrent_lock"}
        raise
    except Exception as exc:
        logger.error("pnl_reconciliation failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


# ── Infrastructure tasks ──────────────────────────────────────────────────────


@_task(name="celery_app.database_backup", queue="infra", soft_time_limit=1800, time_limit=2100)
def database_backup(self=None):
    """
    Trigger a database backup snapshot.

    Calls database.backup.run_backup() to write a snapshot and returns its
    path. run_backup is synchronous and raises RuntimeError on failure.
    """
    try:
        # Lock TTL must exceed time_limit (2100 s) so the lock does not expire
        # while the task is still running.  Use time_limit + 60 s buffer.
        with _redis_lock("database_backup", timeout=2160):
            from database.backup import run_backup

            result = run_backup()
            logger.info("database_backup: %s", result)
            return {"status": "ok", "backup": str(result)}
    except RuntimeError as exc:
        if "already held" in str(exc):
            logger.info("database_backup skipped — lock already held by another task")
            return {"status": "skipped", "reason": "concurrent_lock"}
        raise
    except Exception as exc:
        logger.error("database_backup failed: %s", exc)
        if self is not None and _CELERY_AVAILABLE:
            raise self.retry(exc=exc)  # noqa: B904 — Celery retry idiom; chaining would alter exception type
        raise


@_task(name="celery_app.self_healer_scan", queue="infra", soft_time_limit=240, time_limit=300)
def self_healer_scan(self=None):
    """
    Run a SelfHealer anomaly scan.

    Checks all registered health monitors and triggers auto-remediation
    actions for any that are in a degraded state.
    """
    import asyncio

    try:
        # Lock TTL must exceed time_limit (300 s) so the lock does not expire
        # while the task is still running.  Use time_limit + 60 s buffer.
        with _redis_lock("self_healer_scan", timeout=360):
            from core.self_healer import get_self_healer

            healer = get_self_healer()
            result = asyncio.run(healer.scan())
            actions = result.get("actions_taken", [])
            if actions:
                logger.info("self_healer_scan: took %d actions: %s", len(actions), actions)
            return {"status": "ok", "actions_taken": len(actions)}
    except RuntimeError as exc:
        if "already held" in str(exc):
            logger.info("self_healer_scan skipped — lock already held by another task")
            return {"status": "skipped", "reason": "concurrent_lock"}
        raise
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
