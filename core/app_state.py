# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/app_state.py
=================
Application state container.

Extracted from app.py to keep the application entry point under 300 lines.
Import the singleton via:

    from core.app_state import app_state
"""

from __future__ import annotations

from typing import Any, Callable


class AppState:
    """Shared application state — populated during startup by ComponentRegistry."""

    def __init__(self) -> None:
        self.config: Any | None = None
        self.db_engine: Any | None = None
        self.db_session_factory: Callable[..., Any] | None = None
        self.cache = None
        self.initialized = False
        # Core trading components
        self.auth_service = None
        self.broker = None
        self.risk_manager = None
        self.compliance_manager = None
        self.strategy_brain = None
        self.ws_manager = None
        self.alert_engine = None
        self.wallet_manager = None
        # Social
        self.copy_trading_engine = None
        self.marketplace = None
        self.leaderboard_manager = None
        # Experimental modules (populated at startup when feature flags are on)
        self.research_engine = None
        self.explainer = None
        self.transparency_engine = None
        self.teams_manager = None
        self.nocode_builder = None
        self.replay_engine = None
        self.ml_feature_engineer = None
        # Price engine — used by /api/trading/ohlcv and /prices
        self.price_engine = None
        # ML inference engine — full pipeline (MacroStore + MTF + 200 features)
        self.inference_engine = None
        # MacroStore — daily macro series (DXY, VIX, yields, etc.)
        self.macro_store = None
        # Core trading components
        self.event_store = None
        self.brain = None
        self.position_tracker = None
        self.trade_executor = None
        self.order_book = None
        # Regime-aware strategy router
        self.regime_router = None
        # Central decision engine — five-phase tick-to-order pipeline
        # Populated by init_decision_engine() in startup_factories.py
        self.decision_engine = None
        # Feature engineer — sklearn-compatible OHLCV feature pipeline
        # Populated by init_feature_engineer() in startup_factories.py
        self.feature_engineer = None
        # Signal engine — asyncio task handle returned by init_signal_engine()
        self.signal_engine = None
        # Master Control Centre — strategy orchestration and lifecycle management
        self.mcc = None
        # Background asyncio tasks — populated at startup, cancelled at shutdown
        self.background_tasks: list = []


# Module-level singleton — imported by app.py and all API modules
app_state = AppState()
