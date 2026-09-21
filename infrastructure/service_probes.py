# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
infrastructure/service_probes.py
================================
One implementation per component, shared by every page that reports health.

Why this exists
---------------
Four pages reported four different answers about the same Celery, and three
about the same Redis, because each page had written its own probe:

    System Health   Celery DOWN — RuntimeError, 8ms
    Reliability     Celery WARNING — "inspect failed: Connection closed by server"
    Health Engine   Celery OK — workers=1 active, 3280ms

The disagreement was not noise, and the failing probes were not wrong. The
Redis service runs with ``--timeout 300``, so it closes any connection idle for
five minutes. A Celery *control* connection from the app container is idle far
longer than that — nothing touches it until an operator opens a health page —
so the server has already hung up, and the client only finds out when it
writes. **The 8ms is the proof**: a probe with a 2-second inspect timeout that
fails in 8ms never waited for anything.

Health Engine returned OK because it happened to reconnect; the others hit the
dead socket first. Same broker, same second, opposite verdicts, all three
"correct" about what they observed.

Two things follow, and this module is the second:

1. ``celery_app.py`` now sets ``health_check_interval`` on the broker so
   redis-py refreshes or replaces an idle connection before handing it out.
   That addresses the cause.
2. A probe still has to survive the race, and — more importantly — every page
   has to run *the same check*. Three implementations with three timeouts and
   three execution models cannot agree even when the component is healthy.

Every probe here retries once on a connection-shaped error before reporting a
failure, and says so in its detail, so a transient reconnect is distinguishable
from an outage.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Kept below the Redis server's own `--timeout 300` so a connection is refreshed
# before the server reaps it.
CELERY_INSPECT_TIMEOUT = 3.0
CELERY_WAIT_TIMEOUT = 5.0

# Error text that means "the connection died", as opposed to "the service
# answered and said no". These warrant one retry; a genuine outage does not
# become healthy on a second attempt, so retrying costs one round trip.
_RECONNECTABLE = (
    "connection closed by server",
    "connection reset",
    "broken pipe",
    "connection refused",
    "connection aborted",
    "not connected",
    "eof occurred",
)


def is_reconnectable(exc: BaseException) -> bool:
    """Whether *exc* looks like a dropped connection rather than a real fault."""
    text = str(exc).lower()
    return any(marker in text for marker in _RECONNECTABLE)


def _inspect_stats() -> Any:
    """Blocking Celery broadcast. Never call this on the event loop.

    ``inspect.stats()`` waits for worker replies up to its timeout. Called
    directly inside ``async def`` it blocks the loop for the whole wait, and
    every probe gathered alongside it stalls behind it — measured in a deployed
    report as a dozen unrelated probes all landing at ~2.0s, including a Redis
    "timeout" that was really this function holding the loop.
    """
    from celery_app import celery_app

    return celery_app.control.inspect(timeout=CELERY_INSPECT_TIMEOUT).stats()


async def probe_celery() -> dict[str, Any]:
    """Canonical Celery health check. Never raises.

    Returns ``{status, detail, latency_ms, worker_count, workers, retried}``
    with ``status`` in ``ok`` | ``warning`` | ``error``.

    ``warning`` rather than ``error`` when the broker answers but reports no
    workers: the queue is reachable and the deployment is degraded, which is a
    different fact from the broker being unreachable.
    """
    t0 = time.perf_counter()
    retried = False
    last_exc: BaseException | None = None

    for attempt in (1, 2):
        try:
            loop = asyncio.get_running_loop()
            stats = await asyncio.wait_for(loop.run_in_executor(None, _inspect_stats), timeout=CELERY_WAIT_TIMEOUT)
            latency = round((time.perf_counter() - t0) * 1000, 2)
            note = " (after reconnect)" if retried else ""
            if stats:
                return {
                    "status": "ok",
                    "detail": f"workers={len(stats)} active{note}",
                    "latency_ms": latency,
                    "worker_count": len(stats),
                    "workers": sorted(stats.keys()),
                    "retried": retried,
                }
            return {
                "status": "warning",
                "detail": f"broker reachable but no workers responded{note}",
                "latency_ms": latency,
                "worker_count": 0,
                "workers": [],
                "retried": retried,
            }
        except TimeoutError as exc:
            last_exc = exc
            break  # a timeout is not a dropped connection; retrying doubles the wait
        except Exception as exc:  # a health probe must not raise
            last_exc = exc
            if attempt == 1 and is_reconnectable(exc):
                # The Redis broker closes idle connections after 300s. The first
                # write to a reaped socket fails immediately; the retry opens a
                # fresh one. Reporting the first failure as an outage is what
                # made System Health say DOWN while Health Engine said OK.
                retried = True
                logger.debug("probe_celery: reconnectable error, retrying once: %s", exc)
                continue
            break

    latency = round((time.perf_counter() - t0) * 1000, 2)
    detail = f"Celery inspect failed: {last_exc}"
    if retried:
        detail += " (retried once after a dropped connection)"
    return {
        "status": "error",
        "detail": detail,
        "latency_ms": latency,
        "worker_count": 0,
        "workers": [],
        "retried": retried,
    }
