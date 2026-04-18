# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
visualization — Chart generation and dashboard visualization utilities.

Public API
----------
    ChartGenerator      Generates Plotly/Matplotlib charts for equity curves,
                        drawdown, trade distribution, and regime heatmaps.
    DashboardRenderer   Renders HTML dashboard components from trade data.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from visualization.charts import ChartGenerator
except Exception as _exc:
    logger.debug("visualization.charts unavailable: %s", _exc)
    ChartGenerator = None  # type: ignore[assignment,misc]

try:
    from visualization.dashboard import DashboardServer
except Exception as _exc:
    logger.debug("visualization.dashboard unavailable: %s", _exc)
    DashboardServer = None  # type: ignore[assignment,misc]

__all__ = ["ChartGenerator", "DashboardServer"]
