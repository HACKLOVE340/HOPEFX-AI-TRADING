# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/regime_router.py
=====================
Shim that re-exports :class:`~strategies.regime_router.RegimeRouter` from the
``strategies`` package so that callers using ``from core.regime_router import …``
continue to work.

The canonical implementation lives in ``strategies/regime_router.py``.
"""

from strategies.regime_router import RegimeRouter

__all__ = ["RegimeRouter"]
