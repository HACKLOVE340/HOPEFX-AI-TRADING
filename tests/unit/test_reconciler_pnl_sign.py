# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A winning long must not be reconciled as a losing short.

`PositionReconciler._calc_pnl` decided direction with

    if pos.side == "buy":
        return (current_price - entry) * qty
    return (entry - current_price) * qty

`database.models.Position.side` is a free-text `String(10)`, and the column
holds more than one spelling. The proof is in this repository, in SQL:
`database/repositories/position_repository.py:147` nets open quantity with

    (Position.side == "long", Position.quantity),
    (Position.side == "buy",  Position.quantity),
    else_=-Position.quantity,

Two cases for the long side, because both are written. `_calc_pnl` covered one.
So a long stored as "long" fell to the `else` and was priced as a short.

Measured before the fix — a long of 2 units at 1900, marked at 1950, worth
+$100:

    side='buy'    ->  +100.00
    side='long'   ->  -100.00
    side='BUY'    ->  -100.00
    side='LONG'   ->  -100.00
    side='sell'   ->  -100.00
    side='short'  ->  -100.00

That number is not merely displayed. `_reconcile_once` writes it back
(`db_pos.unrealized_pnl = pnl`), and the reconciler is constructed in
production at `core/startup_factories.py:2829`.
"""

from __future__ import annotations

import logging

import pytest

from core.position_reconciler import PositionReconciler

pytestmark = pytest.mark.unit

ENTRY = 1900.0
MARK_UP = 1950.0
QTY = 2.0
#: A long of QTY bought at ENTRY and marked at MARK_UP.
WINNING_LONG_PNL = (MARK_UP - ENTRY) * QTY


class _Row:
    """The attributes `_calc_pnl` reads off a DB position row."""

    def __init__(self, side, quantity=QTY, entry_price=ENTRY):
        self.side = side
        self.quantity = quantity
        self.entry_price = entry_price


class TestEverySpellingOfLong:
    @pytest.mark.parametrize("side", ["buy", "long", "BUY", "LONG", "Buy", "Long"])
    def test_a_long_that_moved_up_is_a_profit(self, side: str) -> None:
        assert PositionReconciler._calc_pnl(_Row(side), MARK_UP) == pytest.approx(WINNING_LONG_PNL, abs=0.01)

    @pytest.mark.parametrize("side", ["buy", "long", "BUY", "LONG"])
    def test_a_long_that_moved_down_is_a_loss(self, side: str) -> None:
        assert PositionReconciler._calc_pnl(_Row(side), 1850.0) == pytest.approx(-100.0, abs=0.01)


class TestEverySpellingOfShort:
    @pytest.mark.parametrize("side", ["sell", "short", "SELL", "SHORT"])
    def test_a_short_that_moved_up_is_a_loss(self, side: str) -> None:
        assert PositionReconciler._calc_pnl(_Row(side), MARK_UP) == pytest.approx(-100.0, abs=0.01)

    @pytest.mark.parametrize("side", ["sell", "short", "SELL", "SHORT"])
    def test_a_short_that_moved_down_is_a_profit(self, side: str) -> None:
        assert PositionReconciler._calc_pnl(_Row(side), 1850.0) == pytest.approx(100.0, abs=0.01)


class TestTheTwoSidesAreOpposites:
    @pytest.mark.parametrize(("long_side", "short_side"), [("long", "short"), ("buy", "sell")])
    def test_the_same_move_pays_one_and_costs_the_other(self, long_side: str, short_side: str) -> None:
        long_pnl = PositionReconciler._calc_pnl(_Row(long_side), MARK_UP)
        short_pnl = PositionReconciler._calc_pnl(_Row(short_side), MARK_UP)
        assert long_pnl == pytest.approx(-short_pnl, abs=0.01)


class TestAnUnrecognisedSide:
    def test_it_is_reported_rather_than_silently_priced(self, caplog: pytest.LogCaptureFixture) -> None:
        """A side this function does not recognise still has to produce a
        number, because the caller writes one to the database either way. What
        it must not do is pick a direction in silence — that is how "long"
        stayed inverted without anyone noticing."""
        with caplog.at_level(logging.ERROR):
            PositionReconciler._calc_pnl(_Row("sideways"), MARK_UP)
        assert [r for r in caplog.records if r.levelname == "ERROR"], (
            "an unrecognised side produced a P&L with no error logged"
        )

    def test_a_missing_side_does_not_raise(self) -> None:
        """The loop that calls this catches per-cycle, so a raise here costs
        the whole reconciliation pass, not one row."""
        assert PositionReconciler._calc_pnl(_Row(None), MARK_UP) is not None


class TestTheArithmetic:
    def test_a_zero_quantity_position_has_no_pnl(self) -> None:
        assert PositionReconciler._calc_pnl(_Row("long", quantity=0.0), MARK_UP) == 0.0

    def test_a_missing_quantity_is_treated_as_zero(self) -> None:
        assert PositionReconciler._calc_pnl(_Row("long", quantity=None), MARK_UP) == 0.0

    def test_a_missing_entry_price_does_not_raise(self) -> None:
        assert PositionReconciler._calc_pnl(_Row("long", entry_price=None), MARK_UP) is not None

    def test_no_price_move_is_no_pnl(self) -> None:
        assert PositionReconciler._calc_pnl(_Row("long"), ENTRY) == pytest.approx(0.0, abs=0.01)
