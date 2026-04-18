# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""src/backtest/routes — FastAPI route modules for the backtesting API."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from src.backtest.routes.backtest import router
except Exception as _exc:
    logger.debug("src.backtest.routes.backtest unavailable: %s", _exc)
    router = None  # type: ignore[assignment]

__all__ = ["router"]
