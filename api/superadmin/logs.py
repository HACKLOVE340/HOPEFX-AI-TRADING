# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin logs sub-router."""

import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from api.auth import TokenPayload

from ._shared import SetLogLevelBody, _log_superadmin_action, _require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()

# Matches standard Python log lines:
#   2026-04-25 10:00:00,123 LEVEL logger.name Message text
_LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"
    r"\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
    r"\s+(?P<logger>\S+)"
    r"\s+(?P<message>.+)$"
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _normalise_entry(entry: dict) -> dict:
    """Normalise a Redis log entry to the shape the frontend expects.

    The JSON formatter in infrastructure/logging.py writes:
      - "timestamp" (ISO string) — frontend reads "ts"
      - "trace_id" nested inside "context" — frontend reads top-level "trace_id"

    This function fixes both without touching any other fields.
    """
    # Normalise timestamp key
    if "ts" not in entry and "timestamp" in entry:
        entry["ts"] = entry.pop("timestamp")

    # Surface trace_id from the nested context dict
    if "trace_id" not in entry:
        ctx = entry.get("context") or {}
        if isinstance(ctx, dict) and ctx.get("trace_id"):
            entry["trace_id"] = ctx["trace_id"]

    return entry


# ── Logs ──────────────────────────────────────────────────────────────────────


@router.get("/logs")
async def get_logs(
    level: str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    search: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    entries: list[dict] = []

    # ── Primary source: Redis ring-buffer written by the logging handler ──────
    try:
        import json as _json

        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.lrange("app:logs", 0, limit - 1)
            for item in raw:
                try:
                    entry = _normalise_entry(_json.loads(item))
                    if level and entry.get("level") != level:
                        continue
                    if logger_name and logger_name.lower() not in entry.get("logger", "").lower():
                        continue
                    if search and search.lower() not in entry.get("message", "").lower():
                        continue
                    entries.append(entry)
                except Exception:
                    logger.debug("Suppressed exception (no detail) in %s", __name__)
    except Exception as exc:
        logger.debug("get_logs redis: %s", exc)

    # ── Fallback: parse the log file when Redis has no entries ────────────────
    if not entries:
        log_file = os.getenv("LOG_FILE", "logs/app.log")
        try:
            with open(log_file) as f:
                lines = f.readlines()[-limit:]
            for line in reversed(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                if level and level not in stripped:
                    continue
                if search and search.lower() not in stripped.lower():
                    continue

                m = _LOG_LINE_RE.match(stripped)
                if m:
                    entry = {
                        "ts": m.group("ts"),
                        "level": m.group("level"),
                        "logger": m.group("logger"),
                        "message": m.group("message"),
                    }
                else:
                    # Unrecognised format — surface the raw line as the message
                    entry = {"ts": "", "level": "INFO", "logger": "app", "message": stripped}

                if logger_name and logger_name.lower() not in entry["logger"].lower():
                    continue
                entries.append(entry)
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)

    return {"logs": entries}


@router.get("/logs/levels")
async def get_log_levels(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import logging as _logging

    loggers: dict[str, str] = {}
    try:
        for name, lgr in list(_logging.Logger.manager.loggerDict.items()):
            try:
                if isinstance(lgr, _logging.Logger):
                    level_name = _logging.getLevelName(lgr.effective_level)
                    loggers[str(name)] = str(level_name)
            except Exception:
                pass
        root_level = _logging.getLogger().level
        loggers["root"] = _logging.getLevelName(root_level if root_level else _logging.WARNING)
    except Exception as exc:
        logger.debug("get_log_levels: %s", exc)
        loggers["root"] = "INFO"
    # Return flat dict — frontend iterates Object.entries(data) directly
    return loggers


@router.patch("/logs/levels")
async def set_log_level(
    body: SetLogLevelBody, user: TokenPayload = Depends(_require_superadmin)
) -> dict:
    import logging as _logging

    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if body.level.upper() not in valid:
        raise HTTPException(status_code=400, detail=f"level must be one of {valid}")
    lgr = _logging.getLogger(body.logger if body.logger != "root" else None)
    lgr.setLevel(body.level.upper())
    _log_superadmin_action(user, "set_log_level", f"{body.logger}={body.level}")
    return {"ok": True, "logger": body.logger, "level": body.level.upper()}


@router.get("/logs/export", response_class=PlainTextResponse)
async def export_logs(
    level: str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    user: TokenPayload = Depends(_require_superadmin),
) -> Response:
    """Export filtered log entries as plain text (one line per entry)."""
    result = await get_logs(
        level=level, logger_name=logger_name, search=None, limit=1000, user=user
    )
    lines = [
        f"{e.get('ts', '')} {e.get('level', '')} {e.get('logger', '')} {e.get('message', '')}"
        for e in result["logs"]
    ]
    _log_superadmin_action(user, "export_logs")
    return PlainTextResponse("\n".join(lines), media_type="text/plain")
