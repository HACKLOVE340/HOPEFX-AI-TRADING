# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Where the promotion gate's evidence lives between processes.

`api/safe_agent_platform._EVAL_REPORT` was a module global, which made the gate
blind in two ordinary situations that both look like the gate working:

* **After any restart** it is `None`, so canary promotion refuses
  `no_eval_report` until somebody remembers to run the suite by hand.
* **On a second worker** it is `None` too. `ai/gateway/budget_store.py` records
  the identical lesson: `API_WORKERS` above 1 means each process keeps its own
  copy, and the number in the settings form quietly stops meaning what it says.

Because the gate is fail-closed, this reads as an availability problem rather
than a safety one — which is exactly how it gets "fixed" by someone raising
`max_age_s` to a month. Then it is a safety problem.

## What this does not change

**Storing evidence durably does not make it newer.** `PromotionGate` bounds a
report at 24 hours and that bound binds on a restored report exactly as on a
fresh one. Persistence removes the need to re-run the suite after a deploy; it
does not extend how long a score counts.

## Failure posture

A store outage must not become an outage of the gate in either direction:

* a write that fails does not lose the run — six paid model calls are not
  discarded because Redis blipped, and the in-process copy is kept;
* a read that fails falls back to this process's own copy. Refusing to promote
  because Redis is down, while this worker holds a perfectly good report, is a
  gate refusing on the wrong evidence.

With no store installed — a dev box, a test — behaviour is exactly what it was:
one process, one report, gone on restart.

**Synchronous by design**, for the same reason `budget_store` is: the gateway
and the eval runner are synchronous and already run on worker threads.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from ai.evals.suite import SuiteReport

logger = logging.getLogger(__name__)

#: One key. There is only ever a latest report — history belongs in the audit
#: trail, which already records every model call the suite made.
REPORT_KEY = "hopefx:ai:evals:last_report"

#: Comfortably longer than the gate's 24h staleness bound, so expiry is never
#: what decides a promotion. The gate decides; this only stores.
REPORT_TTL_S = 14 * 24 * 3600


class EvalReportStore(Protocol):
    """What `save`/`load` need. A Protocol so a test can supply a dict."""

    def save_report(self, payload: str) -> None: ...

    def load_report(self) -> str | None: ...


class RedisEvalReportStore:
    """`EvalReportStore` over a synchronous Redis client.

    Constructed with an already-connected client rather than building one, so
    the TLS enforcement and password injection in `cache/redis_client.py` stay
    the single place that knows how to reach Redis safely — the same
    arrangement `RedisBudgetStore` uses.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def save_report(self, payload: str) -> None:
        self._client.set(REPORT_KEY, payload, ex=REPORT_TTL_S)

    def load_report(self) -> str | None:
        raw = self._client.get(REPORT_KEY)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)


def build_from_env() -> RedisEvalReportStore | None:
    """A store from this deployment's Redis, or None when there is none.

    None is a legitimate answer — a dev box keeps the in-process report exactly
    as before. Mirrors `ai/gateway/budget_store.build_from_env` deliberately,
    including the ping: a store that cannot be reached should decline to
    install rather than install and fail on every promotion check.
    """
    import os

    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        from redis import Redis

        from cache.redis_client import _enforce_tls, inject_redis_password

        url = _enforce_tls(url)
        url = inject_redis_password(url, os.getenv("REDIS_PASSWORD"))
        client = Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
        client.ping()
        return RedisEvalReportStore(client)
    except Exception as exc:
        logger.error(
            "ai.evals.store: could not build the shared report store (%s); the promotion gate's "
            "evidence will be per-process and lost on restart",
            exc,
        )
        return None


_STORE: EvalReportStore | None = None


def set_store(store: EvalReportStore | None) -> None:
    """Install (or clear) the shared store. Called once at startup."""
    global _STORE
    _STORE = store


def store_is_shared() -> bool:
    """For the health surface: whether the gate's evidence outlives this process."""
    return _STORE is not None


def _encode(report: SuiteReport) -> str:
    return json.dumps(
        {
            "score": float(report.score),
            "total": int(report.total),
            "passed": int(report.passed),
            "failed_case_ids": list(report.failed_case_ids),
            "ran_at": float(report.ran_at),
        }
    )


def _decode(payload: str) -> SuiteReport | None:
    """Rebuild a report, or None if the stored value is not one.

    Returning None rather than raising is deliberate: the gate refuses without
    a report, which is the right outcome for a value it cannot read. Raising
    inside the gate's evidence lookup would turn a schema change into a 500 on
    a promotion request.
    """
    try:
        data = json.loads(payload)
        return SuiteReport(
            score=float(data["score"]),
            total=int(data["total"]),
            passed=int(data["passed"]),
            failed_case_ids=tuple(str(c) for c in data.get("failed_case_ids", ())),
            ran_at=float(data["ran_at"]),
        )
    except Exception:
        logger.warning("ai.evals.store: stored report could not be read; the gate will refuse", exc_info=True)
        return None


def save(report: SuiteReport) -> bool:
    """Persist `report`. Returns whether it reached the store; never raises."""
    if _STORE is None:
        return False
    try:
        _STORE.save_report(_encode(report))
        return True
    except Exception:
        # ERROR, not WARNING: this is the gate's evidence. A deployment whose
        # store is failing needs to know its promotions will start refusing
        # after the next restart, and a quiet log line will not tell anyone.
        logger.error("ai.evals.store: could not persist the eval report", exc_info=True)
        return False


def load() -> SuiteReport | None:
    """Read the stored report, or None. Never raises."""
    if _STORE is None:
        return None
    try:
        payload = _STORE.load_report()
    except Exception:
        logger.error("ai.evals.store: could not read the eval report", exc_info=True)
        return None
    if not payload:
        return None
    return _decode(payload)


__all__ = [
    "REPORT_KEY",
    "REPORT_TTL_S",
    "EvalReportStore",
    "RedisEvalReportStore",
    "build_from_env",
    "load",
    "save",
    "set_store",
    "store_is_shared",
]
