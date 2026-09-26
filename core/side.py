# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The one answer to "which side is this?" — BUY or SELL, or an error.

This repository has seven ``OrderSide`` enums (``database.models``, ``brokers``,
``brokers.base``, ``brokers.advanced_orders``, ``brokers.mt5_bridge`` and two
under ``backtesting/``), a ``core.types.Side`` StrEnum, and free-text
``'long'`` / ``'LONG'`` / ``'buy'`` strings. Before this module three places
independently answered "does this value mean long?" and did not agree
(MASTER_OUTSTANDING §A9), and every trade-persist path fed the database a
spelling the ``orderside`` ENUM('BUY', 'SELL') refuses — so no paper trade was
ever written.

The owner's decision: one side vocabulary, ``BUY`` / ``SELL``, enforced at the
persistence boundary. :func:`normalise_side` is that boundary. It never guesses:
anything it does not recognise raises :class:`UnknownSideError`. A default
direction on a money record is a silently inverted P&L.

This module imports nothing from ``brokers`` or ``database`` on purpose — both
depend on it, and ``brokers/__init__.py`` executes the whole broker package.
"""

from __future__ import annotations

import enum
from typing import Final

BUY: Final = "BUY"
SELL: Final = "SELL"

#: Lower-cased spellings that mean long / short. Every accepted string is
#: compared against these after ``strip().lower()``. The position reconciler,
#: ``brokers.base.Position`` and the position repository's SQL all read these
#: two sets rather than keeping copies.
LONG_SPELLINGS: Final[frozenset[str]] = frozenset({"buy", "long"})
SHORT_SPELLINGS: Final[frozenset[str]] = frozenset({"sell", "short"})

# ``str(SomeOrderSide.BUY)`` is ``"OrderSide.BUY"``; brokers/paper_trading.py
# compares against that spelling in several places, so it does reach here.
_ENUM_REPR_PREFIX: Final = "orderside."


class UnknownSideError(ValueError):
    """A value that is not a recognised spelling of BUY or SELL."""


def normalise_side(value: object) -> str:
    """Return exactly ``"BUY"`` or ``"SELL"`` for *value*, or raise.

    Accepted, case-insensitively and ignoring surrounding whitespace:

    * ``buy`` / ``long`` → ``"BUY"``; ``sell`` / ``short`` → ``"SELL"``
    * ``OrderSide.BUY`` / ``OrderSide.SELL`` — the ``str()`` of an enum member
    * any :class:`enum.Enum` member whose value, or failing that whose name,
      is one of the spellings above — every ``OrderSide`` in this repository
      and ``core.types.Side``

    Everything else — ``None``, empty, numbers, booleans, ``"unknown"`` —
    raises :class:`UnknownSideError`. The result is a plain ``str`` (not a
    ``str`` subclass), because DB-API drivers adapt by exact type.
    """
    if isinstance(value, enum.Enum):
        candidates = [value.value, value.name]
    elif isinstance(value, str):
        candidates = [value]
    else:
        raise UnknownSideError(f"side {value!r} is not a recognised spelling of BUY or SELL")

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        spelling = candidate.strip().lower()
        if spelling.startswith(_ENUM_REPR_PREFIX):
            spelling = spelling[len(_ENUM_REPR_PREFIX) :]
        if spelling in LONG_SPELLINGS:
            return BUY
        if spelling in SHORT_SPELLINGS:
            return SELL
    raise UnknownSideError(
        f"side {value!r} is not a recognised spelling of BUY or SELL "
        f"(accepted: {sorted(LONG_SPELLINGS | SHORT_SPELLINGS)}, case-insensitive)"
    )


def is_long(value: object) -> bool:
    """True for a BUY/long side, False for SELL/short; raises on anything else."""
    return normalise_side(value) == BUY
