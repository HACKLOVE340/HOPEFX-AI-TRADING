# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_sltp_staleness.py
=================================
Regression: SLTPMonitor._get_mid must not return a price from a STALE tick (feed
stall), so a stop is never triggered against a frozen price.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

from execution.sl_tp_monitor import SLTPMonitor


@dataclass
class _Tick:
    mid: float
    timestamp: float  # epoch seconds


def _monitor(tick_cache):
    return SLTPMonitor(position_manager=MagicMock(), broker=MagicMock(), tick_cache=tick_cache)


def test_fresh_tick_returns_mid():
    m = _monitor({"XAUUSD": _Tick(mid=2000.0, timestamp=time.time())})
    assert m._get_mid("XAUUSD") == 2000.0


def test_stale_tick_returns_none():
    # 60s old — well beyond the default 10s max age.
    m = _monitor({"XAUUSD": _Tick(mid=2000.0, timestamp=time.time() - 60.0)})
    assert m._get_mid("XAUUSD") is None


def test_missing_symbol_returns_none():
    m = _monitor({})
    assert m._get_mid("XAUUSD") is None
