# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/fixtures
==============
Shared pytest fixtures for the HOPEFX test suite.

Import in conftest.py via:

    pytest_plugins = ["tests.fixtures.db"]

Or import directly in test modules:

    from tests.fixtures.db import async_db_session, db_user, db_trade
"""

from tests.fixtures.db import (
    async_db_session,
    db_engine,
    db_signal,
    db_tables,
    db_trade,
    db_user,
    market_data_repo,
    position_repo,
    signal_repo,
    sync_db_engine,
    sync_db_session,
    trade_repo,
)

__all__ = [
    "async_db_session",
    "db_engine",
    "db_signal",
    "db_tables",
    "db_trade",
    "db_user",
    "market_data_repo",
    "position_repo",
    "signal_repo",
    "sync_db_engine",
    "sync_db_session",
    "trade_repo",
]
