# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
src — Alternative entry-point package for the HOPEFX backtesting REST API.

Sub-packages
------------
    src.backtest         FastAPI router for backtesting endpoints.
    src.backtest.routes  Individual route modules (backtest.py).

The canonical backtesting engine lives in backtesting/.
This package provides a thin FastAPI router layer on top of it.
"""
