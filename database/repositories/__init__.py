# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/repositories
=====================
Typed async repository pattern for all HOPEFX database entities.

Repositories
------------
  TradeRepository       — Trade records (CRUD, open trades, PnL summary)
  PositionRepository    — Position records (open positions, mark-to-market)
  SignalRepository      — Signal records (pending, by strategy/source)
  MarketDataRepository  — OHLCV bar records (upsert, bulk insert, range query)
  TickDataRepository    — Sub-millisecond tick records (bulk insert, range query)

All repositories inherit from ``AsyncRepository[ModelT]`` which provides
standard CRUD via SQLAlchemy 2.x async sessions.

Usage::

    from database.repositories import TradeRepository, TickDataRepository
    from database.async_connection import AsyncConnectionPool

    pool = AsyncConnectionPool()
    await pool.connect()

    trade_repo = TradeRepository()
    tick_repo = TickDataRepository()

    async with pool.session() as session:
        trade = await trade_repo.create(session, symbol="XAUUSD", ...)
        ticks = await tick_repo.get_latest_ticks(session, "XAUUSD", n=50)
"""

from .base import AsyncRepository
from .market_data_repository import MarketDataRepository
from .position_repository import PositionRepository
from .signal_repository import SignalRepository
from .tick_data_repository import TickDataRepository
from .trade_repository import TradeRepository

__all__ = [
    "AsyncRepository",
    "TradeRepository",
    "PositionRepository",
    "SignalRepository",
    "MarketDataRepository",
    "TickDataRepository",
]
