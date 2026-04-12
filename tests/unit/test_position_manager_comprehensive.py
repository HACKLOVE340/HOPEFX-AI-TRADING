# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Comprehensive tests for execution/position_manager.py."""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import pytest
from execution.position_manager import (
    Position,
    PositionAlreadyOpenError,
    PositionCloseResult,
    PositionManager,
    PositionNotFoundError,
)

UTC = timezone.utc


def _pm():
    return PositionManager(redis_client=None)


def _pos(symbol="XAUUSD", side="BUY", qty=1.0, entry=2000.0, sl=None, tp=None):
    return Position(
        position_id=f"pos_{symbol}",
        symbol=symbol,
        side=side,
        quantity=qty,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
    )


# ── Position dataclass ─────────────────────────────────────────────────────────


class TestPositionDataclass:
    def test_to_dict_keys(self):
        p = _pos()
        d = p.to_dict()
        for k in ("position_id", "symbol", "side", "quantity", "entry_price", "opened_at"):
            assert k in d

    def test_to_dict_values(self):
        p = _pos(symbol="XAUUSD", side="BUY", qty=2.0, entry=1900.0)
        d = p.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert d["side"] == "BUY"
        assert d["quantity"] == pytest.approx(2.0)
        assert d["entry_price"] == pytest.approx(1900.0)

    def test_from_dict_roundtrip(self):
        p = _pos(symbol="XAUUSD", side="SELL", qty=0.5, entry=2050.0, sl=2100.0, tp=1950.0)
        d = p.to_dict()
        p2 = Position.from_dict(d)
        assert p2.symbol == p.symbol
        assert p2.side == p.side
        assert p2.quantity == pytest.approx(p.quantity)
        assert p2.entry_price == pytest.approx(p.entry_price)
        assert p2.stop_loss == pytest.approx(p.stop_loss)
        assert p2.take_profit == pytest.approx(p.take_profit)

    def test_from_dict_no_opened_at(self):
        d = {"position_id": "p1", "symbol": "XAUUSD", "side": "BUY", "quantity": 1.0, "entry_price": 2000.0}
        p = Position.from_dict(d)
        assert isinstance(p.opened_at, datetime)

    def test_from_dict_string_opened_at(self):
        d = {
            "position_id": "p1",
            "symbol": "XAUUSD",
            "side": "BUY",
            "quantity": 1.0,
            "entry_price": 2000.0,
            "opened_at": "2025-01-01T00:00:00+00:00",
        }
        p = Position.from_dict(d)
        assert p.opened_at.year == 2025

    def test_metadata_default_empty(self):
        assert _pos().metadata == {}

    def test_last_price_default_none(self):
        assert _pos().last_price is None

    def test_stop_loss_stored(self):
        p = _pos(sl=1950.0)
        assert p.stop_loss == pytest.approx(1950.0)

    def test_take_profit_stored(self):
        p = _pos(tp=2100.0)
        assert p.take_profit == pytest.approx(2100.0)


# ── PositionCloseResult ────────────────────────────────────────────────────────


class TestPositionCloseResult:
    def test_fields(self):
        r = PositionCloseResult(
            position_id="p1",
            symbol="XAUUSD",
            side="BUY",
            quantity=1.0,
            entry_price=2000.0,
            fill_price=2050.0,
            realized_pnl=50.0,
            duration_seconds=60.0,
            closed_at=datetime.now(UTC),
        )
        assert r.realized_pnl == pytest.approx(50.0)
        assert r.fill_price == pytest.approx(2050.0)


# ── PositionManager — open_position ───────────────────────────────────────────


class TestPositionManagerOpen:
    @pytest.mark.asyncio
    async def test_open_buy_position(self):
        pm = _pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        assert pos.symbol == "XAUUSD"
        assert pos.side == "BUY"
        assert pos.quantity == pytest.approx(1.0)
        assert pos.entry_price == pytest.approx(2000.0)

    @pytest.mark.asyncio
    async def test_open_sell_position(self):
        pm = _pm()
        pos = await pm.open_position("XAUUSD", "SELL", 0.5, 2050.0)
        assert pos.side == "SELL"

    @pytest.mark.asyncio
    async def test_open_stores_position(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        assert pm.get_position("XAUUSD") is not None

    @pytest.mark.asyncio
    async def test_open_with_sl_tp(self):
        pm = _pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0, stop_loss=1950.0, take_profit=2100.0)
        assert pos.stop_loss == pytest.approx(1950.0)
        assert pos.take_profit == pytest.approx(2100.0)

    @pytest.mark.asyncio
    async def test_open_with_custom_position_id(self):
        pm = _pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0, position_id="custom_id")
        assert pos.position_id == "custom_id"

    @pytest.mark.asyncio
    async def test_open_with_metadata(self):
        pm = _pm()
        pos = await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0, metadata={"source": "signal"})
        assert pos.metadata.get("source") == "signal"

    @pytest.mark.asyncio
    async def test_open_duplicate_raises(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        with pytest.raises(PositionAlreadyOpenError):
            await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)

    @pytest.mark.asyncio
    async def test_open_invalid_side_raises(self):
        pm = _pm()
        with pytest.raises(ValueError, match="side"):
            await pm.open_position("XAUUSD", "LONG", 1.0, 2000.0)

    @pytest.mark.asyncio
    async def test_open_zero_quantity_raises(self):
        pm = _pm()
        with pytest.raises(ValueError, match="quantity"):
            await pm.open_position("XAUUSD", "BUY", 0.0, 2000.0)

    @pytest.mark.asyncio
    async def test_open_negative_quantity_raises(self):
        pm = _pm()
        with pytest.raises(ValueError, match="quantity"):
            await pm.open_position("XAUUSD", "BUY", -1.0, 2000.0)

    @pytest.mark.asyncio
    async def test_open_zero_price_raises(self):
        pm = _pm()
        with pytest.raises(ValueError, match="entry_price"):
            await pm.open_position("XAUUSD", "BUY", 1.0, 0.0)

    @pytest.mark.asyncio
    async def test_open_negative_price_raises(self):
        pm = _pm()
        with pytest.raises(ValueError, match="entry_price"):
            await pm.open_position("XAUUSD", "BUY", 1.0, -100.0)

    @pytest.mark.asyncio
    async def test_open_multiple_symbols(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        await pm.open_position("EURUSD", "SELL", 0.5, 1.08)
        assert pm.get_position("XAUUSD") is not None
        assert pm.get_position("EURUSD") is not None


# ── PositionManager — close_position ──────────────────────────────────────────


class TestPositionManagerClose:
    @pytest.mark.asyncio
    async def test_close_buy_profit(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        result = await pm.close_position("XAUUSD", fill_price=2050.0)
        assert result.realized_pnl == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_close_buy_loss(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        result = await pm.close_position("XAUUSD", fill_price=1950.0)
        assert result.realized_pnl == pytest.approx(-50.0)

    @pytest.mark.asyncio
    async def test_close_sell_profit(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "SELL", 1.0, 2000.0)
        result = await pm.close_position("XAUUSD", fill_price=1950.0)
        assert result.realized_pnl == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_close_sell_loss(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "SELL", 1.0, 2000.0)
        result = await pm.close_position("XAUUSD", fill_price=2050.0)
        assert result.realized_pnl == pytest.approx(-50.0)

    @pytest.mark.asyncio
    async def test_close_removes_position(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        await pm.close_position("XAUUSD", fill_price=2050.0)
        assert pm.get_position("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_close_adds_to_history(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        await pm.close_position("XAUUSD", fill_price=2050.0)
        history = pm.get_history()
        assert len(history) == 1
        assert history[0].symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_close_nonexistent_raises(self):
        pm = _pm()
        with pytest.raises(PositionNotFoundError):
            await pm.close_position("GHOST", fill_price=2000.0)

    @pytest.mark.asyncio
    async def test_close_zero_price_raises(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        with pytest.raises(ValueError, match="fill_price"):
            await pm.close_position("XAUUSD", fill_price=0.0)

    @pytest.mark.asyncio
    async def test_close_result_has_duration(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        result = await pm.close_position("XAUUSD", fill_price=2050.0)
        assert result.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_close_result_fill_price(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        result = await pm.close_position("XAUUSD", fill_price=2075.0)
        assert result.fill_price == pytest.approx(2075.0)


# ── PositionManager — update_position ─────────────────────────────────────────


class TestPositionManagerUpdate:
    @pytest.mark.asyncio
    async def test_update_last_price(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        pos = await pm.update_position("XAUUSD", last_price=2025.0)
        assert pos.last_price == pytest.approx(2025.0)

    @pytest.mark.asyncio
    async def test_update_stop_loss(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        pos = await pm.update_position("XAUUSD", stop_loss=1980.0)
        assert pos.stop_loss == pytest.approx(1980.0)

    @pytest.mark.asyncio
    async def test_update_take_profit(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        pos = await pm.update_position("XAUUSD", take_profit=2080.0)
        assert pos.take_profit == pytest.approx(2080.0)

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self):
        pm = _pm()
        with pytest.raises(PositionNotFoundError):
            await pm.update_position("GHOST", last_price=2000.0)

    @pytest.mark.asyncio
    async def test_update_none_values_unchanged(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0, stop_loss=1950.0)
        pos = await pm.update_position("XAUUSD", last_price=2010.0)
        assert pos.stop_loss == pytest.approx(1950.0)  # unchanged


# ── PositionManager — queries ──────────────────────────────────────────────────


class TestPositionManagerQueries:
    @pytest.mark.asyncio
    async def test_get_position_returns_none_when_empty(self):
        assert _pm().get_position("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_get_all_positions_empty(self):
        assert _pm().get_all_positions() == {}

    @pytest.mark.asyncio
    async def test_get_all_positions_returns_all(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        await pm.open_position("EURUSD", "SELL", 0.5, 1.08)
        all_pos = pm.get_all_positions()
        assert "XAUUSD" in all_pos
        assert "EURUSD" in all_pos

    @pytest.mark.asyncio
    async def test_get_total_exposure_zero_when_empty(self):
        assert _pm().get_total_exposure() == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_get_total_exposure_with_positions(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 2.0, 2000.0)
        exposure = pm.get_total_exposure()
        assert exposure == pytest.approx(4000.0)

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl_empty(self):
        assert _pm().get_unrealized_pnl() == {}

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl_with_last_price(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)
        await pm.update_position("XAUUSD", last_price=2050.0)
        pnl = pm.get_unrealized_pnl()
        assert "XAUUSD" in pnl
        assert pnl["XAUUSD"] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl_sell_position(self):
        pm = _pm()
        await pm.open_position("XAUUSD", "SELL", 1.0, 2000.0)
        await pm.update_position("XAUUSD", last_price=1950.0)
        pnl = pm.get_unrealized_pnl()
        assert pnl["XAUUSD"] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_get_history_empty(self):
        assert _pm().get_history() == []

    @pytest.mark.asyncio
    async def test_get_history_limit(self):
        pm = _pm()
        for i in range(5):
            sym = f"SYM{i}"
            await pm.open_position(sym, "BUY", 1.0, 2000.0)
            await pm.close_position(sym, fill_price=2010.0)
        history = pm.get_history(limit=3)
        assert len(history) == 3


# ── PositionAlreadyOpenError / PositionNotFoundError ──────────────────────────


class TestCustomExceptions:
    def test_already_open_error_message(self):
        err = PositionAlreadyOpenError("XAUUSD")
        assert "XAUUSD" in str(err)

    def test_not_found_error_message(self):
        err = PositionNotFoundError("XAUUSD")
        assert "XAUUSD" in str(err)

    def test_already_open_is_exception(self):
        assert isinstance(PositionAlreadyOpenError("X"), Exception)

    def test_not_found_is_exception(self):
        assert isinstance(PositionNotFoundError("X"), Exception)


# ── PositionManager — concurrent safety ───────────────────────────────────────


class TestPositionManagerConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_opens_different_symbols(self):
        pm = _pm()
        await asyncio.gather(
            pm.open_position("XAUUSD", "BUY", 1.0, 2000.0),
            pm.open_position("EURUSD", "SELL", 0.5, 1.08),
            pm.open_position("GBPUSD", "BUY", 0.3, 1.26),
        )
        assert len(pm.get_all_positions()) == 3

    @pytest.mark.asyncio
    async def test_concurrent_open_same_symbol_one_wins(self):
        pm = _pm()
        results = await asyncio.gather(
            pm.open_position("XAUUSD", "BUY", 1.0, 2000.0),
            pm.open_position("XAUUSD", "SELL", 1.0, 2000.0),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, PositionAlreadyOpenError)]
        successes = [r for r in results if isinstance(r, Position)]
        assert len(successes) == 1
        assert len(errors) == 1
