# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/mcc — Master Control Core: strategy orchestration and lifecycle management.

Public API
----------
    MasterControlCore   Top-level coordinator: activate/deactivate strategies,
                        route price updates, enforce risk limits.
    MCCConfig           Dataclass for MCC configuration parameters.
"""

from core.mcc.master_control import MasterControlCore, MCCConfig

__all__ = [
    "MasterControlCore",
    "MCCConfig",
]
