# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§5: maintain conversation context across active tasks.

"Is the backtest done?" is unanswerable if the conversation has no idea a
backtest was started. `ai/jobs/runner.py` already runs several at once and knows
each one's state perfectly — what it does not do is tell the part of the system
that talks to people. This is that channel.

## Finished is not gone

A job leaves the *active* list when it ends and stays referable for a while,
because "how did it go?" arrives after the work finishes, not during it. An
implementation that dropped finished tasks would answer every follow-up question
with silence about the thing just asked about.

## Per operator, always

One operator's work is not context for another's conversation. Same rule as the
job runner, the notification inbox and the AI budget — and the same reason: this
platform has already shipped one cross-operator leak, in `snapshot()` and
`cancel()` on the job runner, and every store added since is keyed by operator
first so the next one has to be deliberate.

## Bounded

A session running for a week must not put a thousand finished jobs into every
answer. Recent finished work is kept; the rest ages out. The alternative is a
context block that grows until it crowds out the question.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Finished tasks kept per operator. Enough to answer "how did that go?" about
#: the last few things, not enough to bury the current question.
MAX_FINISHED = 8

#: Active tasks named individually before the description switches to a count.
MAX_NAMED_ACTIVE = 6


@dataclass
class _Task:
    task_id: str
    summary: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    outcome: str = ""


@dataclass
class _Conversation:
    active: dict[str, _Task] = field(default_factory=dict)
    finished: list[_Task] = field(default_factory=list)


_LOCK = threading.Lock()
_BY_OPERATOR: dict[str, _Conversation] = {}


def _conversation(operator: str) -> _Conversation:
    return _BY_OPERATOR.setdefault(operator, _Conversation())


def note_task(operator: str, *, task_id: str, summary: str) -> None:
    """Something started. The conversation should know about it."""
    if not summary.strip():
        raise ValueError("a task needs a summary the AI can say out loud")
    with _LOCK:
        _conversation(operator).active[task_id] = _Task(task_id=task_id, summary=summary.strip())


def finish_task(operator: str, *, task_id: str, outcome: str = "") -> bool:
    """Something ended. Returns False if the conversation never knew about it."""
    with _LOCK:
        conversation = _conversation(operator)
        task = conversation.active.pop(task_id, None)
        if task is None:
            return False
        task.outcome = outcome.strip()
        conversation.finished.append(task)
        del conversation.finished[:-MAX_FINISHED]
        return True


def active(operator: str) -> list[dict[str, Any]]:
    with _LOCK:
        return [
            {"task_id": t.task_id, "summary": t.summary, "started_at": t.started_at}
            for t in _conversation(operator).active.values()
        ]


def describe(operator: str) -> str:
    """What is going on, in a sentence the AI can put in front of an answer.

    Never empty. "Nothing is running" is a fact worth saying; an empty string
    reads as a missing feature rather than as a quiet system, and the caller
    would have to invent wording for the difference.
    """
    with _LOCK:
        conversation = _conversation(operator)
        running = list(conversation.active.values())
        done = list(conversation.finished)

    lines: list[str] = []
    if not running:
        lines.append("Nothing running for you right now.")
    elif len(running) <= MAX_NAMED_ACTIVE:
        lines.append(f"Still running: {'; '.join(t.summary for t in running)}.")
    else:
        named = running[:MAX_NAMED_ACTIVE]
        lines.append(
            f"Still running: {'; '.join(t.summary for t in named)}, and {len(running) - MAX_NAMED_ACTIVE} more."
        )

    if done:
        recent = done[-3:]
        lines.append(
            "Recently finished: "
            + "; ".join(f"{t.summary}{f' — {t.outcome}' if t.outcome else ''}" for t in recent)
            + "."
        )
    return " ".join(lines)


def reset_for_testing() -> None:
    with _LOCK:
        _BY_OPERATOR.clear()


__all__ = [
    "MAX_FINISHED",
    "MAX_NAMED_ACTIVE",
    "active",
    "describe",
    "finish_task",
    "note_task",
    "reset_for_testing",
]
