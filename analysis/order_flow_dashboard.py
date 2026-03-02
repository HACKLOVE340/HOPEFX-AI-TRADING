"""
Order Flow Dashboard

Unified dashboard combining all order flow components:
- Time & Sales
- Institutional Flow Detection
- Advanced Order Flow Metrics
- Depth of Market (from existing data module)
- Base Order Flow Analysis (from existing analysis module)

Provides a single get_complete_analysis() method for a full snapshot.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from analysis.order_flow import OrderFlowAnalyzer, get_order_flow_analyzer
from analysis.institutional_flow import (
    InstitutionalFlowDetector,
    get_institutional_detector,
)
from analysis.advanced_order_flow import (
    AdvancedOrderFlowAnalyzer,
    get_advanced_order_flow_analyzer,
)
from data.time_and_sales import TimeAndSalesService, get_time_and_sales_service
from data.depth_of_market import DepthOfMarketService, get_dom_service

logger = logging.getLogger(__name__)


class OrderFlowDashboard:
    """
    Unified Order Flow Dashboard.

    Aggregates signals and metrics from all order flow subsystems into a
    single, coherent analysis snapshot per symbol.

    Usage:
        dashboard = OrderFlowDashboard()

        # (All underlying services must have trade/tick data fed into them)
        analysis = dashboard.get_complete_analysis('XAUUSD')
    """

    def __init__(
        self,
        order_flow_analyzer: Optional[OrderFlowAnalyzer] = None,
        institutional_detector: Optional[InstitutionalFlowDetector] = None,
        advanced_analyzer: Optional[AdvancedOrderFlowAnalyzer] = None,
        time_and_sales: Optional[TimeAndSalesService] = None,
        dom_service: Optional[DepthOfMarketService] = None,
    ):
        """
        Initialize dashboard with optional pre-built service instances.

        If not provided, global singleton instances are used.
        """
        self._of = order_flow_analyzer or get_order_flow_analyzer()
        self._inst = institutional_detector or get_institutional_detector()
        self._adv = advanced_analyzer or get_advanced_order_flow_analyzer()
        self._ts = time_and_sales or get_time_and_sales_service()
        self._dom = dom_service or get_dom_service()

        logger.info("Order Flow Dashboard initialized")

    # ================================================================
    # MAIN ANALYSIS
    # ================================================================

    def get_complete_analysis(
        self,
        symbol: str,
        lookback_minutes: int = 60,
    ) -> Dict:
        """
        Get a complete order flow analysis snapshot for a symbol.

        Combines:
        - Base order flow analysis (volume profile, delta, key levels)
        - Institutional flow signals
        - Advanced metrics (aggression, clusters, divergence, oscillator)
        - Time & Sales statistics
        - DOM snapshot (if available)

        Args:
            symbol: Trading symbol
            lookback_minutes: Analysis window in minutes

        Returns:
            Dict with all analysis components
        """
        result: Dict = {
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "lookback_minutes": lookback_minutes,
            "order_flow": None,
            "institutional": None,
            "advanced": None,
            "time_and_sales": None,
            "dom": None,
        }

        # --- Base order flow ---
        try:
            of_analysis = self._of.analyze(symbol, lookback_minutes=lookback_minutes)
            result["order_flow"] = of_analysis.to_dict() if of_analysis else None
        except Exception as exc:
            logger.warning("Base order flow error for %s: %s", symbol, exc)

        # --- Institutional flow ---
        try:
            signals = self._inst.analyze_flow(symbol, lookback_minutes=lookback_minutes)
            smart = self._inst.get_smart_money_direction(
                symbol, lookback_minutes=lookback_minutes
            )
            result["institutional"] = {
                "signals": [s.to_dict() for s in signals],
                "smart_money_direction": smart.to_dict() if smart else None,
                "signal_count": len(signals),
            }
        except Exception as exc:
            logger.warning("Institutional flow error for %s: %s", symbol, exc)

        # --- Advanced metrics ---
        try:
            aggression = self._adv.get_aggression_metrics(
                symbol, lookback_minutes=lookback_minutes
            )
            clusters = self._adv.get_volume_clusters(
                symbol, lookback_minutes=lookback_minutes * 4
            )
            divergence = self._adv.detect_delta_divergence(
                symbol, lookback_minutes=lookback_minutes
            )
            oscillator = self._adv.get_order_flow_oscillator(symbol)
            stacked = self._adv.get_stacked_imbalances(
                symbol, lookback_minutes=lookback_minutes
            )
            pressure = self._adv.get_pressure_gauges(symbol)

            result["advanced"] = {
                "aggression_metrics": aggression.to_dict() if aggression else None,
                "volume_clusters": [c.to_dict() for c in clusters],
                "delta_divergence": divergence.to_dict() if divergence else None,
                "order_flow_oscillator": oscillator.to_dict() if oscillator else None,
                "stacked_imbalances": [s.to_dict() for s in stacked],
                "pressure_gauges": pressure,
            }
        except Exception as exc:
            logger.warning("Advanced order flow error for %s: %s", symbol, exc)

        # --- Time & Sales ---
        try:
            ts_stats = self._ts.get_trade_statistics(
                symbol, lookback_minutes=lookback_minutes
            )
            velocity = self._ts.get_trade_velocity(symbol)
            aggressor = self._ts.get_aggressor_stats(
                symbol, lookback_minutes=lookback_minutes
            )
            result["time_and_sales"] = {
                "statistics": ts_stats,
                "velocity": velocity.to_dict() if velocity else None,
                "aggressor_stats": aggressor.to_dict() if aggressor else None,
            }
        except Exception as exc:
            logger.warning("Time & Sales error for %s: %s", symbol, exc)

        # --- Depth of Market ---
        try:
            dom_analysis = self._dom.get_order_book_analysis(symbol)
            result["dom"] = dom_analysis.to_dict() if dom_analysis else None
        except Exception as exc:
            logger.warning("DOM error for %s: %s", symbol, exc)

        # Build a top-level summary
        result["summary"] = self._build_summary(result)

        return result

    def _build_summary(self, analysis: Dict) -> Dict:
        """Build a high-level summary from the full analysis."""
        signals: List[str] = []
        bias = "neutral"
        strength = "weak"

        # Order flow signal
        of = analysis.get("order_flow") or {}
        of_signal = of.get("order_flow_signal", "neutral")
        if of_signal in ("bullish", "bearish"):
            signals.append(f"order_flow:{of_signal}")

        # Institutional smart money
        inst = analysis.get("institutional") or {}
        smart = inst.get("smart_money_direction") or {}
        smart_dir = smart.get("direction", "neutral")
        if smart_dir in ("bullish", "bearish"):
            signals.append(f"smart_money:{smart_dir}")

        # Oscillator
        adv = analysis.get("advanced") or {}
        osc = adv.get("order_flow_oscillator") or {}
        osc_signal = osc.get("signal", "neutral")
        if osc_signal in ("bullish", "bearish"):
            signals.append(f"oscillator:{osc_signal}")

        # Tally
        bull = sum(1 for s in signals if "bullish" in s)
        bear = sum(1 for s in signals if "bearish" in s)

        if bull > bear:
            bias = "bullish"
            strength = "strong" if bull >= 2 else "moderate"
        elif bear > bull:
            bias = "bearish"
            strength = "strong" if bear >= 2 else "moderate"

        return {
            "bias": bias,
            "strength": strength,
            "supporting_signals": signals,
            "bullish_count": bull,
            "bearish_count": bear,
        }

    # ================================================================
    # CONVENIENCE METHODS
    # ================================================================

    def get_market_bias(self, symbol: str, lookback_minutes: int = 60) -> Dict:
        """
        Get high-level market bias for a symbol.

        Args:
            symbol: Trading symbol
            lookback_minutes: Lookback window

        Returns:
            Dict with bias and strength
        """
        analysis = self.get_complete_analysis(symbol, lookback_minutes)
        return analysis.get("summary", {"bias": "neutral", "strength": "weak"})

    def get_key_levels(self, symbol: str) -> Dict:
        """
        Get key support/resistance levels from order flow.

        Args:
            symbol: Trading symbol

        Returns:
            Dict with support and resistance levels
        """
        return self._of.get_key_levels(symbol)


# ================================================================
# FASTAPI INTEGRATION
# ================================================================


def create_dashboard_router(dashboard: OrderFlowDashboard):
    """
    Create FastAPI router for the order flow dashboard.

    Args:
        dashboard: OrderFlowDashboard instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/dashboard", tags=["Order Flow Dashboard"])

    @router.get("/{symbol}/complete")
    async def get_complete_analysis(symbol: str, lookback_minutes: int = 60):
        """Get complete order flow analysis for a symbol."""
        return dashboard.get_complete_analysis(symbol, lookback_minutes)

    @router.get("/{symbol}/bias")
    async def get_market_bias(symbol: str, lookback_minutes: int = 60):
        """Get market bias summary."""
        return dashboard.get_market_bias(symbol, lookback_minutes)

    @router.get("/{symbol}/levels")
    async def get_key_levels(symbol: str):
        """Get key S/R levels."""
        return dashboard.get_key_levels(symbol)

    return router


# Global instance
_dashboard: Optional[OrderFlowDashboard] = None


def get_order_flow_dashboard() -> OrderFlowDashboard:
    """Get the global Order Flow Dashboard instance."""
    global _dashboard
    if _dashboard is None:
        _dashboard = OrderFlowDashboard()
    return _dashboard
