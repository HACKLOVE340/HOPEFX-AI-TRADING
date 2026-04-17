# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/analytics — Real-time analytics and heatmap generation.

Public API
----------
    RealtimeHeatmapEngine   Correlation matrix, regime detection, and
                            heatmap data generation for the dashboard.
"""

from core.analytics.realtime_heatmap import RealtimeHeatmapEngine

__all__ = [
    "RealtimeHeatmapEngine",
]
