# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
src/backtest — FastAPI router package for backtesting REST endpoints.

Routes are defined in src/backtest/routes/backtest.py and mounted at
/api/backtest. The canonical backtesting engine lives in backtesting/.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from src.backtest.routes.backtest import router  # noqa: F401
except Exception as _exc:
    logger.debug("src.backtest router unavailable: %s", _exc)
    router = None  # type: ignore[assignment]

__all__ = ["router"]
