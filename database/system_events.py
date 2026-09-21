# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
database/system_events.py — read/write helpers for the ``system_events`` table.

Four call sites (``ml/training_manager.py``, ``ml/ab_testing.py`` and two
fallbacks in ``api/superadmin/ml_ai.py``) each hand-rolled their own access to
this table, and every one of them was written against a ``SystemEvent`` that
does not exist. The model has::

    id BigInteger PK · timestamp · level · component · event_type
    message · details_json · traceback · trace_id · session_id

The callers used ``created_at``, ``status`` and ``metadata``, none of which are
columns, passed a string id into the BigInteger primary key, and omitted
``level`` and ``message``, which are ``nullable=False``. So:

* every write raised ``TypeError: 'status' is an invalid keyword argument``;
* every read raised ``AttributeError`` on ``SystemEvent.created_at`` while
  building the query;
* and ``r.metadata`` is not ``None`` for a row with no payload — on a
  declarative model it is the SQLAlchemy ``MetaData`` object, which is truthy,
  so ``meta = r.metadata or {}`` yielded a ``MetaData`` and ``meta.get(...)``
  raised in turn.

All of it was caught by surrounding ``except Exception`` blocks and logged at
``debug``. The visible result was a training-history page and an A/B test page
that were always empty, and an A/B manager that lost every running test on
restart — with nothing anywhere reporting a fault. The training page in
particular falls back to ``_static_model_status()``, so it showed a plausible
list of models read off disk while the actual run history was never stored.

This module is the single place that knows the mapping. The identifier is kept
in ``trace_id`` (String(50), indexed) rather than the primary key, because these
are UUID-shaped strings and ``id`` is a BigInteger; ``status`` and the free-form
payload live in ``details_json``, which is the column that exists for exactly
that purpose.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["SystemEventRecord", "read_events", "upsert_event"]

_MAX_REF_LEN = 50


class SystemEventRecord:
    """A decoded ``system_events`` row, in the shape the callers expected."""

    __slots__ = ("component", "event_type", "payload", "ref_id", "status", "timestamp")

    def __init__(
        self,
        *,
        ref_id: str,
        event_type: str,
        component: str,
        status: str,
        payload: dict[str, Any],
        timestamp: datetime | None,
    ) -> None:
        self.ref_id = ref_id
        self.event_type = event_type
        self.component = component
        self.status = status
        self.payload = payload
        self.timestamp = timestamp

    @property
    def started_at(self) -> str | None:
        return self.timestamp.isoformat() if self.timestamp else None


def _encode(status: str, payload: dict[str, Any]) -> str:
    return json.dumps({"status": status, "payload": payload}, default=str)


def _decode(raw: str | None) -> tuple[str, dict[str, Any]]:
    """Decode ``details_json``. Never raises — a row written by something else,
    or by an older version of this code, must not take down a whole listing."""
    if not raw:
        return "", {}
    try:
        blob = json.loads(raw)
    except (TypeError, ValueError):
        return "", {}
    if not isinstance(blob, dict):
        return "", {}
    payload = blob.get("payload")
    return str(blob.get("status") or ""), payload if isinstance(payload, dict) else {}


def upsert_event(
    db: Any,
    *,
    ref_id: str,
    event_type: str,
    component: str,
    status: str,
    payload: dict[str, Any],
    level: str = "INFO",
    message: str | None = None,
) -> None:
    """Insert or update the row identified by ``ref_id``.

    ``ref_id`` is matched on ``trace_id``, not the primary key — see the module
    docstring. Both ``level`` and ``message`` are NOT NULL on the table, and
    both were previously omitted, which is the second reason writes failed even
    once the invalid kwargs were removed.
    """
    from database.models import SystemEvent

    ref = str(ref_id)[:_MAX_REF_LEN]
    row = db.query(SystemEvent).filter(SystemEvent.trace_id == ref).one_or_none()
    if row is None:
        row = SystemEvent(trace_id=ref, event_type=event_type)
        db.add(row)

    row.level = level
    row.component = str(component)[:50]
    row.event_type = event_type
    row.message = message or f"{event_type} {ref} {status}"
    row.details_json = _encode(status, payload)


def read_events(db: Any, *, event_type: str, limit: int = 50) -> list[SystemEventRecord]:
    """Most-recent-first rows of one ``event_type``, decoded.

    Ordering is by ``timestamp``; the callers used ``created_at``, which is the
    column name on ``audit_log``, not on this table.
    """
    from database.models import SystemEvent

    rows = (
        db.query(SystemEvent)
        .filter(SystemEvent.event_type == event_type)
        .order_by(SystemEvent.timestamp.desc())
        .limit(limit)
        .all()
    )
    out: list[SystemEventRecord] = []
    for r in rows:
        status, payload = _decode(r.details_json)
        out.append(
            SystemEventRecord(
                ref_id=r.trace_id or str(r.id),
                event_type=r.event_type,
                component=r.component or "unknown",
                status=status,
                payload=payload,
                timestamp=r.timestamp,
            )
        )
    return out
