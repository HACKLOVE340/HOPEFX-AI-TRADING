# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.jobs — background jobs, queues & scheduled work.

Pure predicates for the framework's async-work categories: a job must run within
its SLA, scheduled jobs must actually fire, queue depth & age must stay bounded,
the dead-letter queue must not grow unbounded, jobs must be idempotent (no
double-effect on retry), stuck/zombie jobs must be detected, and a job must not
exceed its max attempts silently. Each returns ``list[Violation]``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Silent Failure"


def verify_job_within_sla(runtime_seconds: float, sla_seconds: float, job: str = "") -> list[Violation]:
    """A job must finish within its SLA."""
    if _is_finite_number(runtime_seconds) and runtime_seconds > sla_seconds:
        return [_v(_RULE, WARNING, f"job {job} ran {runtime_seconds}s exceeding SLA {sla_seconds}s")]
    return []


def verify_scheduled_job_fired(expected_runs: int, actual_runs: int, job: str = "") -> list[Violation]:
    """A scheduled job must have fired the expected number of times (no missed cron)."""
    if actual_runs < expected_runs:
        return [_v(_RULE, CRITICAL, f"scheduled job {job} fired {actual_runs}/{expected_runs} times (missed runs)")]
    return []


def verify_queue_depth(depth: int, max_depth: int, queue: str = "") -> list[Violation]:
    """Queue backlog must stay bounded (runaway backlog = silent processing failure)."""
    if depth > max_depth:
        return [_v(_RULE, CRITICAL, f"queue {queue} depth {depth} exceeds max {max_depth}")]
    return []


def verify_oldest_message_age(age_seconds: float, max_age_seconds: float, queue: str = "") -> list[Violation]:
    """The oldest unprocessed message must not exceed the staleness limit."""
    if _is_finite_number(age_seconds) and age_seconds > max_age_seconds:
        return [_v(_RULE, CRITICAL, f"queue {queue} oldest message age {age_seconds}s exceeds {max_age_seconds}s")]
    return []


def verify_dlq_bounded(dlq_count: int, max_dlq: int) -> list[Violation]:
    """The dead-letter queue must stay below the alert threshold."""
    if dlq_count > max_dlq:
        return [_v(_RULE, CRITICAL, f"dead-letter queue {dlq_count} exceeds threshold {max_dlq}")]
    return []


def verify_job_idempotent(job_id: Any, completed_ids: Iterable[Any]) -> list[Violation]:
    """A retried job whose id already completed must not re-run (double-effect)."""
    if job_id in set(completed_ids):
        return [_v(_RULE, CRITICAL, f"job {job_id!r} re-executed after completion (non-idempotent)")]
    return []


def verify_no_zombie_job(heartbeat_age_seconds: float, max_silence_seconds: float, job: str = "") -> list[Violation]:
    """A running job that stopped heart-beating is a zombie (stuck) job."""
    if _is_finite_number(heartbeat_age_seconds) and heartbeat_age_seconds > max_silence_seconds:
        return [_v(_RULE, CRITICAL, f"job {job} silent for {heartbeat_age_seconds}s (zombie/stuck)")]
    return []


def verify_attempts_bounded(attempts: int, max_attempts: int, job: str = "") -> list[Violation]:
    """A job must not exceed its retry budget without surfacing failure."""
    if attempts > max_attempts:
        return [_v(_RULE, WARNING, f"job {job} attempted {attempts} times exceeding max {max_attempts}")]
    return []


def verify_no_concurrent_singleton(running_instances: int, job: str = "") -> list[Violation]:
    """A singleton job must never run concurrently with itself (split-brain effects)."""
    if running_instances > 1:
        return [_v(_RULE, CRITICAL, f"singleton job {job} has {running_instances} concurrent instances")]
    return []


def verify_failure_rate(failures: int, total: int, max_rate: float) -> list[Violation]:
    """The job failure rate must stay below the alert threshold."""
    if total > 0:
        rate = failures / total
        if rate > max_rate:
            return [_v(_RULE, CRITICAL, f"job failure rate {round(rate, 3)} exceeds {max_rate}")]
    return []
