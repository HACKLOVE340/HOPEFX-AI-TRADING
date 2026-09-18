# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Where a job goes so it can outlive the process that ran it. §14.

`JobRunner` keeps jobs in an in-process dict, which is right for the live path
and wrong for the thing §14 actually asks for: an hour-long research job dies
with the process and its result is not recoverable. The scheduling half — any
deadline at `background` priority, an ageing queue so neither tier starves the
other — landed in Phase B and was honest about this gap in its own note.

The precedent is `ai/gateway/budget_store.py`, and it is the same lesson twice:
spend lived in a module global, every restart reset the month to zero, and at
`API_WORKERS=4` each worker kept its own dict so the ceiling in the settings
form silently meant four times what it said.

## A job that was RUNNING did not survive

Its thread is gone. Bringing it back as `running` is the worst of the available
answers — a job that says running for ever is one nobody can act on, and the
screen spins against a worker that does not exist. `recovered_state` promotes
every non-terminal state to `interrupted`, which is terminal and carries a
reason.

`queued` gets the same treatment for a different reason: nothing was lost,
because it never started, but nothing is going to start it either. Leaving it
queued promises a worker that is not coming.

## The store is never the source of truth for a live job

It is behind by design — written after each transition, not during. So
`JobRunner.recover` prefers what this process is actually running, and consults
the store only for jobs it has never heard of. A reader that preferred the
store would show `interrupted` for a job that succeeded in the very process
doing the reading.

## Operator is part of the key, not a filter applied afterwards

`ai/jobs/runner.py` is where a P0 was found: one operator's prompt and the
model's answer could reach another operator's screen, because the scoping was
applied at the read and anything that forgot to apply it leaked everything. So
a record is stored under its operator, and a recovery that forgets the operator
finds nothing rather than finding everybody.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

logger = logging.getLogger(__name__)

#: What a job becomes when it is found in a store after the process that was
#: running it has gone. Terminal, and distinct from `failed`: the work did not
#: fail, nobody ever saw whether it would have.
INTERRUPTED: Final = "interrupted"

#: Outcomes that mean the job reached an end somebody observed. Mirrors
#: `runner.TERMINAL_STATES` and is defined here so this module does not import
#: the runner it is injected into.
_OBSERVED_TERMINAL: Final[frozenset[str]] = frozenset({"succeeded", "failed", "cancelled", "timed_out"})

_INTERRUPTED_REASON: Final = (
    "the process running this job restarted before it finished, so its worker is gone; "
    "nothing was recorded about how it would have ended"
)


@dataclass
class JobRecord:
    """The part of a job worth keeping across a restart.

    Deliberately not the whole `Job`. `deadline` is a monotonic instant that
    means nothing in another process, and the `on_change` callback and future
    are not serialisable at all — a record that carried them would look
    complete and be unusable.
    """

    id: str
    operator: str
    prompt: str
    state: str
    result: Any = None
    error: str = ""
    progress: list[str] = field(default_factory=list)
    partial: str = ""
    submitted_at: str = ""
    finished_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operator": self.operator,
            "prompt": self.prompt,
            "state": self.state,
            "result": self.result,
            "error": self.error,
            "progress": list(self.progress),
            "partial": self.partial,
            "submitted_at": self.submitted_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> JobRecord:
        """Rebuild a record, or raise.

        Raises rather than returning a half-formed record with empty strings in
        it: a record whose id is `""` would be stored, listed and shown as a
        job that cannot be opened. `read_for` catches this per record, so one
        bad entry costs its own recovery and not the other nine.
        """
        if not isinstance(payload, dict):
            raise ValueError(f"a job record must be a mapping, got {type(payload).__name__}")
        for required in ("id", "operator", "prompt", "state"):
            value = payload.get(required)
            if not isinstance(value, str) or not value:
                raise ValueError(f"a job record needs a non-empty {required}")
        progress = payload.get("progress") or []
        if not isinstance(progress, list):
            progress = []
        return cls(
            id=payload["id"],
            operator=payload["operator"],
            prompt=payload["prompt"],
            state=payload["state"],
            result=payload.get("result"),
            error=payload.get("error") or "",
            progress=[str(p) for p in progress],
            partial=payload.get("partial") or "",
            submitted_at=payload.get("submitted_at") or "",
            finished_at=payload.get("finished_at") or "",
        )


def recovered_state(record: JobRecord) -> str:
    """What a stored job's state means now that its process has gone.

    Terminal states are returned unchanged — those outcomes were observed.
    Everything else becomes `interrupted`. See the module docstring for why
    `running` and `queued` both land there.
    """
    return record.state if record.state in _OBSERVED_TERMINAL else INTERRUPTED


def interrupted(record: JobRecord) -> JobRecord:
    """`record` as it should be shown after a restart, reason included."""
    state = recovered_state(record)
    if state == record.state:
        return record
    return JobRecord(
        id=record.id,
        operator=record.operator,
        prompt=record.prompt,
        state=state,
        result=record.result,
        # Never blank. An interrupted job with no reason is indistinguishable
        # from a bug in the recovery path.
        error=record.error or _INTERRUPTED_REASON,
        progress=list(record.progress),
        partial=record.partial,
        submitted_at=record.submitted_at,
        finished_at=record.finished_at,
    )


class JobStore(Protocol):
    """Somewhere a job record survives the process."""

    def write(self, record: JobRecord) -> None: ...

    def read_for(self, operator: str) -> list[JobRecord]: ...


class InMemoryJobStore:
    """A store that does not actually outlive anything.

    Useful in tests and as the shape a real backend implements. It is NOT
    installed as a default: a runner handed this would report `durable = True`
    and be wrong, which is the failure this whole module exists to prevent, so
    `JobRunner` treats it as durable only because a test asked for it
    explicitly — production wiring passes a Redis-backed one or none at all.
    """

    def __init__(self) -> None:
        self._by_operator: dict[str, dict[str, Any]] = {}
        self._extra: dict[str, list[Any]] = {}

    def write(self, record: JobRecord) -> None:
        self._by_operator.setdefault(record.operator, {})[record.id] = record.as_dict()

    def put_raw(self, operator: str, payload: Any) -> None:
        """Store something that is not a valid record, to prove one bad entry
        does not cost the others."""
        self._extra.setdefault(operator, []).append(payload)

    def read_for(self, operator: str) -> list[JobRecord]:
        out: list[JobRecord] = []
        for payload in list(self._by_operator.get(operator, {}).values()) + list(self._extra.get(operator, [])):
            try:
                out.append(JobRecord.from_dict(payload))
            except Exception as exc:
                logger.warning("ai.jobs.store: skipping a malformed record for %s: %s", operator, exc)
        return out


#: One hash per operator. The operator is in the KEY, so a read that forgot it
#: addresses nothing rather than addressing everybody — see the module
#: docstring and the P0 it refers to.
_KEY = "hopefx:ai:jobs:{operator}"

#: Long enough that an operator can come back the next morning for an overnight
#: research job, short enough that a store nobody prunes does not grow for ever.
_TTL_S = 7 * 24 * 3600


class RedisJobStore:
    """`JobStore` over a synchronous Redis client.

    Constructed with an already-connected client rather than building one, for
    the same reason `RedisBudgetStore` is: `cache/redis_client.py` stays the
    single place that knows how to reach Redis with TLS and a password.

    Synchronous because the runner's worker threads are what call it — the same
    threads that already run the model call. Reaching for the async client here
    would mean driving a loop from inside a thread standing in for one.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def write(self, record: JobRecord) -> None:
        key = _KEY.format(operator=record.operator)
        self._client.hset(key, record.id, json.dumps(record.as_dict(), default=str))
        # Refreshed on every write, so an operator still working keeps their
        # history and one who stopped a week ago does not.
        self._client.expire(key, _TTL_S)

    def read_for(self, operator: str) -> list[JobRecord]:
        raw = self._client.hgetall(_KEY.format(operator=operator)) or {}
        out: list[JobRecord] = []
        for value in raw.values():
            try:
                out.append(JobRecord.from_dict(json.loads(value)))
            except Exception as exc:
                logger.warning("ai.jobs.store: skipping a malformed record for %s: %s", operator, exc)
        return out


def build_from_env() -> RedisJobStore | None:
    """A store from this deployment's Redis, or None when there is none.

    None is a legitimate answer and the caller REPORTS it rather than treating
    it as an error: a dev box with no Redis runs exactly as it did before, with
    jobs that do not survive a restart and a runner that says so.

    Deliberately the same shape as `ai/gateway/budget_store.py:build_from_env`,
    including the ping. A store that cannot be reached should decline to
    install rather than install and then fail on every job for the life of the
    process — and, worse here, leave `durable` reporting True while nothing is
    being written.
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
        client = Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0, decode_responses=True)
        client.ping()
        return RedisJobStore(client)
    except Exception as exc:
        logger.error(
            "ai.jobs.store: could not build the shared Redis job store (%s); "
            "long-running jobs will not survive a restart until this is resolved",
            exc,
        )
        return None


__all__ = [
    "INTERRUPTED",
    "InMemoryJobStore",
    "JobRecord",
    "JobStore",
    "RedisJobStore",
    "build_from_env",
    "interrupted",
    "recovered_state",
]
