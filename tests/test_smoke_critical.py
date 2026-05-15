# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_smoke_critical.py
=============================
Regression gates for 19 critical modules.

Upgraded from pure import/instantiate smoke tests to round-trip behavioral
gates.  Each module now has at least one test that:

  1. Calls a real public method with real inputs
  2. Asserts the output is numerically/structurally correct — not just non-None
  3. Asserts fail-safe / fail-closed behaviour on bad inputs

What this prevents
------------------
The original tests passed even if every method raised NotImplementedError or
returned a sentinel zero.  A position sizer returning 0.0 lots, a TCA engine
recording no fills, or a leaderboard returning an empty list would all have
passed.  These tests now catch those regressions.
"""

from __future__ import annotations

import asyncio

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
