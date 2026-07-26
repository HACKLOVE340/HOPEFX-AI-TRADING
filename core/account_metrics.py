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
