# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Closing a long position must sell it.

Four broker adapters decided which way to trade out of a position with

    close_side = OrderSide.SELL if pos.side == "LONG" else OrderSide.BUY

and `Position.__post_init__` normalises `side` to an `OrderSide` on
construction — a documented, deliberate conversion, with `side_str` provided
for callers that still want the old spelling. So `pos.side == "LONG"` compares
an enum member to a string and is False for every position ever built. The
branch was dead, and its `else` ran every time.

Closing a SHORT therefore worked, because BUY is the right answer for a short.
Closing a LONG placed a BUY for the same quantity — **doubling the position
instead of flattening it**. One direction correct and one direction inverted is
the hardest possible shape to notice.

`brokers/ibkr_connector.py::close_position` is exercised end to end below.
The same dead predicate stood in `brokers/interactive_brokers.py:313`,
`brokers/alpaca.py:356` and `brokers/ccxt_connector.py:239`; all four now route
through `brokers.base.closing_side`, whose own test is the first class here.
Those three have no SDK stand-in yet and are exercised at the helper, not at
the adapter — stated rather than implied.
"""

from __future__ import annotations

import pytest

from brokers.base import OrderSide, Position, closing_side

pytestmark = pytest.mark.unit


def _position(side: str, quantity: float = 3.0) -> Position:
    return Position(
        symbol="XAUUSD",
        side=side,
        quantity=quantity,
        entry_price=1900.0,
        current_price=1950.0,
        unrealized_pnl=150.0,
    )


class TestClosingSide:
    def test_a_long_is_closed_by_selling(self) -> None:
        assert closing_side(_position("LONG")) is OrderSide.SELL

    def test_a_short_is_closed_by_buying(self) -> None:
        assert closing_side(_position("SHORT")) is OrderSide.BUY

    def test_it_reads_the_normalised_enum_not_the_string_it_was_given(self) -> None:
        """The predicate this replaces compared against the constructor's
        argument rather than the value the constructor stored."""
        long_position = _position("LONG")
        assert long_position.side is OrderSide.BUY
        assert (long_position.side == "LONG") is False
        assert closing_side(long_position) is OrderSide.SELL

    @pytest.mark.parametrize("spelling", ["LONG", "long", "BUY", "buy"])
    def test_every_accepted_spelling_of_long_closes_the_same_way(self, spelling: str) -> None:
        assert closing_side(_position(spelling)) is OrderSide.SELL

    @pytest.mark.parametrize("spelling", ["SHORT", "short", "SELL", "sell"])
    def test_every_accepted_spelling_of_short_closes_the_same_way(self, spelling: str) -> None:
        assert closing_side(_position(spelling)) is OrderSide.BUY

    def test_closing_twice_never_reopens(self) -> None:
        """Whatever the position, the closing side is the opposite of it."""
        for side in ("LONG", "SHORT"):
            position = _position(side)
            assert closing_side(position) is not position.side
