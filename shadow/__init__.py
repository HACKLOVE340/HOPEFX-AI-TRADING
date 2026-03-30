# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
shadow/
=======
Shadow systems: parallel validation feeds and paper-vs-live comparison.

Public API
----------
  from shadow import ShadowDataValidator, ShadowTradingEngine
"""
from shadow.data_validator import ShadowDataValidator
from shadow.trading_engine import ShadowTradingEngine

__all__ = ["ShadowDataValidator", "ShadowTradingEngine"]
