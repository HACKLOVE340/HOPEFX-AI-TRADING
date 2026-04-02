# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
enhanced_backtest_engine.py — compatibility shim
=================================================
The institutional backtest engine has moved to backtesting/enhanced_engine.py.

This shim re-exports everything so existing imports continue to work.
New code should import from backtesting.enhanced_engine directly:

    from backtesting.enhanced_engine import EnhancedBacktestEngine
"""

from backtesting.enhanced_engine import *  # noqa: F401,F403  # pylint: disable=wildcard-import,unused-wildcard-import
