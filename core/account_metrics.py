# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/account_metrics.py
=======================
Shared conventions for derived account metrics, so every transport reports the
same number for the same account state.

Why this module exists
----------------------
``margin_level = equity / margin_used * 100`` is undefined when no margin is in
use, and the two paths that compute it had diverged:

* ``api/ws_live.py`` returned ``9999.0``, deliberately — see the comment there.
  ``0.0`` was making the frontend render a margin-call warning for an account
  that simply had no open positions.
* ``api/trading.py`` returned ``0.0`` at three separate call sites.

So the same flat account showed "no risk" over the WebSocket and "margin call"
over REST, purely depending on which one the page happened to read. This module
holds the single definition both now use.
"""

from __future__ import annotations

import time

__all__ = ["NO_MARGIN_LEVEL", "margin_level"]


# Sentinel for "no margin in use, therefore no margin risk".
#
# Not 0.0: consumers colour low margin levels as danger, and 0.0 is the most
# dangerous value there is — the exact opposite of what an unlevered account
# means. Not None: the GraphQL schema types margin_level as a non-null Float
# (api/graphql_schema.py), so a null would be a breaking change.
#
# The frontend renders anything at or above lib/utils.ts MARGIN_LEVEL_SAFE
# (1000) as ">999%", which covers both this sentinel and the genuinely-huge
# ratios produced by a negligible amount of margin — e.g. $0.81 used against
# $10,000 equity is a true but useless 1234568%.
NO_MARGIN_LEVEL: float = 9999.0


def tick_age_seconds(ts_value: object, *, now: float | None = None) -> float | None:
    """Age in seconds of a tick timestamp, whatever unit it was written in.

    Returns ``None`` when the timestamp is absent or unusable — which is a
    different fact from "zero seconds old" and must not be confused with it.

    Two probes computed this inline as ``time.time() - float(ts)``, in
    ``infrastructure/health_engine.py`` and ``api/superadmin/reliability.py``.
    Tick writers store epoch **milliseconds**, so the subtraction mixed units
    and the deployed Reliability page showed:

        data_feed   ok   last tick age=-1784477523827.0s

    an age of minus fifty-six thousand years, graded ``ok`` — because the
    freshness test is ``age < 120`` and every negative number passes it. The
    check was therefore guaranteed to report a healthy feed exactly when it
    could not read the timestamp, which is the worst possible direction for it
    to fail in.

    ``api/superadmin/reliability.py`` also defaulted a missing timestamp to
    ``time.time()``, producing an age of exactly 0.0 — a fresh-looking tick
    conjured from no tick at all.

    Units are inferred from magnitude: seconds since 1970 are ~1.7e9, so a
    value past 1e11 is milliseconds and past 1e14 is microseconds. Both are far
    beyond any plausible second-denominated timestamp.
    """
    if ts_value is None:
        return None
    try:
        raw = float(ts_value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None

    if raw >= 1e14:  # microseconds
        seconds = raw / 1_000_000.0
    elif raw >= 1e11:  # milliseconds
        seconds = raw / 1_000.0
    else:
        seconds = raw

    age = (time.time() if now is None else now) - seconds
    # A tick from the future is a clock or unit problem, not a fresh tick.
    # Clamp to 0 rather than returning a negative that sails through "< 120".
    return max(age, 0.0)


def margin_level(equity: float, margin_used: float) -> float:
    """Return the margin level percentage, or NO_MARGIN_LEVEL if none is used.

    >>> margin_level(10_000.0, 2_000.0)
    500.0
    >>> margin_level(10_000.0, 0.0) == NO_MARGIN_LEVEL
    True
    >>> margin_level(10_000.0, -1.0) == NO_MARGIN_LEVEL
    True
    """
    if margin_used <= 0:
        return NO_MARGIN_LEVEL
    return round(equity / margin_used * 100, 2)
