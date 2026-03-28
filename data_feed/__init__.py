# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed — real-time price ingestion layer.

Public API
----------
ProductionDataEngine  : primary async engine (REST + MT5 fallback)
MT5Backup             : MT5 price source used as last-resort fallback
"""

from .engine import ProductionDataEngine
from .mt5_backup import MT5Backup

__all__ = ["ProductionDataEngine", "MT5Backup"]
