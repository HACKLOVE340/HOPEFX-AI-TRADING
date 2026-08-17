# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/ai_quota.py
================
Per-user daily cap on endpoints that spend money at an LLM provider.

Why this exists
---------------
Every LLM-backed route already requires a JWT — api/chat.py's own docstring
notes that without auth "any bot that discovers the URL can run up OpenAI
charges indefinitely". Authentication answers *who* is calling but not *how
often*: a single registered account could hold /api/brain/complete open in a
loop and drain the provider budget overnight, and the per-IP limiter in
core/middleware.py does not stop that either — it meters request rate, not
cumulative spend, so a caller who stays just under the rate limit runs
unbounded over a day.

This module adds the missing dimension: a rolling 24-hour count per user, on
the routes that cost money per call.

Usage
-----
    from core.ai_quota import ai_quota

    @router.post("/chat")
    async def chat(body: ChatRequest, user: TokenPayload = Depends(ai_quota())):
        ...

The dependency resolves the caller itself (via get_current_user) and returns
the same TokenPayload, so it replaces the route's existing auth dependency
rather than being added alongside it.

Configuration
-------------
  AI_DAILY_LIMIT_PER_USER   requests per rolling 24 h (default 200)
  AI_QUOTA_ENABLED          set false to disable enforcement entirely
  AI_QUOTA_EXEMPT_ROLES     comma-separated roles that bypass the cap
                            (default "admin,superadmin" — operators run the
                            system and are not the abuse case this guards)

Storage
-------
Shares the Redis sliding window in rate_limiting/advanced.py, so the count is
consistent across replicas. When Redis is unreachable that module falls back to
an in-process counter: per-worker rather than global, which under-counts on a
multi-worker deployment but still bounds a single looping client.
"""

from __future__ import annotations

import logging
import os

from fastapi import Depends, HTTPException, status

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 86_400  # rolling 24 h


def _enabled() -> bool:
    return os.getenv("AI_QUOTA_ENABLED", "true").lower() not in ("false", "0", "no")


def _daily_limit() -> int:
    """Read the cap at call time so it is tunable without a restart in tests."""
    raw = os.getenv("AI_DAILY_LIMIT_PER_USER", "200")
    try:
        value = int(raw)
    except ValueError:
        logger.warning("AI_DAILY_LIMIT_PER_USER=%r is not an integer — using 200", raw)
        return 200
    # A limit of 0 would lock every user out of the feature. That is far more
    # likely to be a misconfigured env var than a deliberate shutdown, and the
    # deliberate version has its own switch (AI_QUOTA_ENABLED), so treat it as
    # invalid rather than silently disabling the AI features.
    if value <= 0:
        logger.warning("AI_DAILY_LIMIT_PER_USER=%d is not positive — using 200", value)
        return 200
    return value


def _exempt_roles() -> frozenset[str]:
    raw = os.getenv("AI_QUOTA_EXEMPT_ROLES", "admin,superadmin")
    return frozenset(r.strip() for r in raw.split(",") if r.strip())


def ai_quota(cost: int = 1, feature: str = "ai"):
    """Return a dependency enforcing the per-user daily AI cap.

    Args:
        cost: how many units this route consumes. A route that fans out into
            several provider calls should charge accordingly, so one expensive
            endpoint cannot cost 10x another while counting the same.
        feature: quota bucket name. Routes sharing a name share an allowance;
            the default puts every AI route in one budget, which is what
            "don't drain the account" actually means.

    Returns:
        A FastAPI dependency returning the authenticated :class:`TokenPayload`.
    """

    async def _check(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if not _enabled():
            return user
        if user.role in _exempt_roles():
            return user

        limit = _daily_limit()
        key = f"aiquota:{feature}:{user.sub}"

        try:
            from rate_limiting.advanced import _redis_is_allowed

            allowed = True
            # `cost` units are charged as `cost` entries in the same window, so a
            # route declaring cost=5 consumes five of the user's daily units.
            for _ in range(max(1, cost)):
                allowed = await _redis_is_allowed(key, limit, _WINDOW_SECONDS)
                if not allowed:
                    break
        except Exception as exc:
            # Fail open on limiter failure: a broken counter must not take away a
            # paying user's access to the product. The rate limiter in
            # core/middleware.py still bounds request rate, so the exposure is
            # a spend overrun, which is recoverable and logged — unlike a
            # total outage of every AI feature.
            logger.warning("AI quota check failed (%s) — allowing request", exc)
            return user

        if not allowed:
            logger.info("AI quota exhausted for user %s (feature=%s, limit=%d)", user.sub, feature, limit)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Daily AI usage limit reached ({limit} requests per 24 hours). "
                    "The limit resets on a rolling 24-hour window."
                ),
                headers={"Retry-After": str(_WINDOW_SECONDS)},
            )
        return user

    return _check
