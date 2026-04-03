# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
charting/__init__.py
=====================
Advanced Charting Module — professional-grade charting + nuclear AI dashboard.

Standard charting:
  ChartEngine, IndicatorLibrary, DrawingToolkit, TimeframeManager, TemplateManager

Nuclear AI dashboard (new):
  NuclearAIChartEngine  — real-time backend orchestrator (nuclear_ai_chart_engine.py)
  get_chart_engine()    — module-level singleton accessor
  mount_nuclear_routes  — FastAPI route mounting helper (websocket_server.py)

Quick start:
    # Backend: mount nuclear routes on your FastAPI app
    from charting import mount_nuclear_routes, get_chart_engine
    mount_nuclear_routes(app)

    # Standalone WebSocket server (port 8001)
    python -m charting.websocket_server

    # Inject a news event for immediate scoring
    engine = get_chart_engine()
    result = engine.inject_news_event("nuclear strike reported", volatility=2.5, sentiment=-0.9)
    # result = { "severity": 10, "action": "nuclear_mode", "explanation": "...", ... }
"""

from .chart_engine import ChartEngine
from .drawing_tools import Drawing, DrawingToolkit, DrawingType
from .indicators import TechnicalIndicators as IndicatorLibrary
from .templates import TemplateManager
from .timeframes import TimeframeManager

# ── Nuclear AI chart engine ───────────────────────────────────────────────────
# Imported lazily so the module loads even when optional deps (FastAPI, SB3)
# are not installed.


def get_chart_engine():
    """Return the NuclearAIChartEngine module-level singleton."""
    from .nuclear_ai_chart_engine import get_chart_engine as _get

    return _get()


def mount_nuclear_routes(app, engine=None):
    """
    Mount nuclear dashboard WebSocket + REST routes onto a FastAPI app.

    Routes added:
      GET  /ws/nuclear              — live NuclearChartState stream
      GET  /api/nuclear/snapshot    — HTTP polling fallback
      POST /api/nuclear/event       — inject news event for scoring
      POST /api/nuclear/resume      — manual trading resume
      GET  /api/nuclear/history     — last N nuclear events
      GET  /api/nuclear/status      — supervisor status + WS count
    """
    from .websocket_server import mount_nuclear_routes as _mount

    _mount(app, engine)


# ── Standard singletons ───────────────────────────────────────────────────────

chart_engine = ChartEngine()
indicator_library = IndicatorLibrary()
drawing_toolkit = DrawingToolkit()
timeframe_manager = TimeframeManager()
template_manager = TemplateManager()

__all__ = [
    # Standard charting
    "ChartEngine",
    "Drawing",
    "DrawingToolkit",
    "DrawingType",
    "IndicatorLibrary",
    "TemplateManager",
    "TimeframeManager",
    "chart_engine",
    "drawing_toolkit",
    # Nuclear AI dashboard
    "get_chart_engine",
    "indicator_library",
    "mount_nuclear_routes",
    "template_manager",
    "timeframe_manager",
]

__version__ = "2.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Professional charting + nuclear-grade AI dashboard with RL + WORDMAP"
