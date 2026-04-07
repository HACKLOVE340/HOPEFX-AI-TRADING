# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin logs sub-router."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import TokenPayload

from ._shared import SetLogLevelBody, _log_superadmin_action, _require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Logs ──────────────────────────────────────────────────────────────────────


@router.get("/logs")
async def get_logs(
    level: str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    search: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    entries = []
    try:
        from cache.redis_client import get_redis_client
        import json

        rc = get_redis_client()
        if rc:
            raw = rc.lrange("app:logs", 0, limit - 1)
            for item in raw:
                try:
                    entry = json.loads(item)
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

    if not entries:
        import os

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
                parts = stripped.split(" ", 3)
                entries.append(
                    {
                        "ts": parts[0] if len(parts) > 0 else "",
                        "level": parts[2] if len(parts) > 2 else "INFO",
                        "logger": parts[1] if len(parts) > 1 else "app",
                        "message": parts[3] if len(parts) > 3 else stripped,
                    }
                )
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)

    return {"logs": entries}


@router.get("/logs/levels")
async def get_log_levels(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import logging as _logging

    loggers = {}
    for name, lgr in _logging.Logger.manager.loggerDict.items():
        if isinstance(lgr, _logging.Logger):
            loggers[name] = _logging.getLevelName(lgr.effective_level)
    loggers["root"] = _logging.getLevelName(_logging.getLogger().level)
    return loggers


@router.patch("/logs/levels")
async def set_log_level(body: SetLogLevelBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import logging as _logging

    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if body.level.upper() not in valid:
        raise HTTPException(status_code=400, detail=f"level must be one of {valid}")
    lgr = _logging.getLogger(body.logger if body.logger != "root" else None)
    lgr.setLevel(body.level.upper())
    _log_superadmin_action(user, "set_log_level", f"{body.logger}={body.level}")
    return {"ok": True, "logger": body.logger, "level": body.level.upper()}


@router.get("/logs/export")
async def export_logs(
    level: str | None = Query(None),
    logger_name: str | None = Query(None, alias="logger"),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    from fastapi.responses import PlainTextResponse

    result = await get_logs(level=level, logger_name=logger_name, search=None, limit=1000, user=user)
    lines = [
        f"{e.get('ts', '')} {e.get('level', '')} {e.get('logger', '')} {e.get('message', '')}" for e in result["logs"]
    ]
    _log_superadmin_action(user, "export_logs")
    return PlainTextResponse("\n".join(lines), media_type="text/plain")  # type: ignore[return-value]
