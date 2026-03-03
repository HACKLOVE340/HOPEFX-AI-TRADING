"""
Feature Flags Module

Provides a centralised registry of every application feature with its
maturity status and runtime on/off control via environment variables.

Each flag maps a symbolic name to an env-var.  When the env-var is absent
the flag falls back to its hard-coded default (True for stable features,
False for experimental/disabled ones).

Usage::

    from config.feature_flags import flags

    if flags.ORDER_FLOW_DASHBOARD:
        result = dashboard.get_complete_analysis("XAUUSD")

    # Inspect the full registry at startup
    for name, info in flags.registry().items():
        print(f"{name}: enabled={info['enabled']}, status={info['status']}")

Status levels
-------------
STABLE       Feature is production-ready and on by default.
BETA         Feature is functional but still under active development; on by default.
EXPERIMENTAL Feature exists but is not yet reliable; off by default.
DISABLED     Feature has been intentionally turned off or removed from the active product.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class FeatureStatus(str, Enum):
    """Maturity level of a feature."""

    STABLE = "stable"
    BETA = "beta"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Registry descriptor
# ---------------------------------------------------------------------------


class _FeatureDef:
    """Descriptor for a single feature flag.

    Reads its value from *env_var* at runtime so the flag can be overridden
    without redeploying code.
    """

    def __init__(
        self,
        env_var: str,
        default: bool,
        status: FeatureStatus,
        description: str,
    ) -> None:
        self._env_var = env_var
        self._default = default
        self._status = status
        self._description = description
        self._attr_name: str = ""

    # Called by Python when the descriptor is assigned to a class attribute
    def __set_name__(self, owner: type, name: str) -> None:
        self._attr_name = name

    # Instance access returns the resolved bool
    def __get__(self, obj: object, objtype: type | None = None) -> bool:
        raw = os.environ.get(self._env_var)
        if raw is None:
            return self._default
        return raw.strip().lower() not in ("0", "false", "no", "off")

    def _is_enabled(self) -> bool:
        """Read the current enabled state from env (shared by __get__ and meta)."""
        raw = os.environ.get(self._env_var)
        if raw is None:
            return self._default
        return raw.strip().lower() not in ("0", "false", "no", "off")

    # Allow the owning class to expose metadata
    def meta(self) -> Dict[str, Any]:
        return {
            "name": self._attr_name,
            "env_var": self._env_var,
            "enabled": self._is_enabled(),
            "default": self._default,
            "status": self._status.value,
            "description": self._description,
        }


# ---------------------------------------------------------------------------
# Feature flags class
# ---------------------------------------------------------------------------


class FeatureFlags:
    """
    Centralised feature flag registry for the HOPEFX AI Trading platform.

    All features are declared here as class-level descriptors.  Access them as
    ordinary boolean attributes::

        flags = FeatureFlags()
        if flags.SOCIAL_TRADING:
            ...
    """

    # ── Core Trading ──────────────────────────────────────────────────────

    STRATEGY_MANAGER = _FeatureDef(
        "FEATURE_STRATEGY_MANAGER",
        default=True,
        status=FeatureStatus.STABLE,
        description="Multi-strategy orchestration and lifecycle management.",
    )
    PAPER_TRADING = _FeatureDef(
        "FEATURE_PAPER_TRADING",
        default=True,
        status=FeatureStatus.STABLE,
        description="Paper-trading broker simulator for risk-free testing.",
    )
    LIVE_TRADING = _FeatureDef(
        "FEATURE_LIVE_TRADING",
        default=False,
        status=FeatureStatus.STABLE,
        description="Live order execution via connected broker APIs.  "
                    "Off by default for safety; requires explicit opt-in.",
    )
    RISK_MANAGER = _FeatureDef(
        "FEATURE_RISK_MANAGER",
        default=True,
        status=FeatureStatus.STABLE,
        description="Real-time position sizing, drawdown limits, and exposure control.",
    )

    # ── Strategies ────────────────────────────────────────────────────────

    STRATEGY_MA_CROSSOVER = _FeatureDef(
        "FEATURE_STRATEGY_MA_CROSSOVER",
        default=True,
        status=FeatureStatus.STABLE,
        description="Moving-average crossover strategy.",
    )
    STRATEGY_EMA_CROSSOVER = _FeatureDef(
        "FEATURE_STRATEGY_EMA_CROSSOVER",
        default=True,
        status=FeatureStatus.STABLE,
        description="Exponential moving-average crossover strategy.",
    )
    STRATEGY_BOLLINGER = _FeatureDef(
        "FEATURE_STRATEGY_BOLLINGER",
        default=True,
        status=FeatureStatus.STABLE,
        description="Bollinger Bands mean-reversion strategy.",
    )
    STRATEGY_BREAKOUT = _FeatureDef(
        "FEATURE_STRATEGY_BREAKOUT",
        default=True,
        status=FeatureStatus.STABLE,
        description="Price-breakout momentum strategy.",
    )
    STRATEGY_MACD = _FeatureDef(
        "FEATURE_STRATEGY_MACD",
        default=True,
        status=FeatureStatus.STABLE,
        description="MACD divergence / histogram strategy.",
    )
    STRATEGY_RSI = _FeatureDef(
        "FEATURE_STRATEGY_RSI",
        default=True,
        status=FeatureStatus.STABLE,
        description="RSI overbought/oversold strategy.",
    )
    STRATEGY_SMC_ICT = _FeatureDef(
        "FEATURE_STRATEGY_SMC_ICT",
        default=True,
        status=FeatureStatus.STABLE,
        description="Smart Money Concepts / ICT methodology strategy.",
    )
    STRATEGY_MEAN_REVERSION = _FeatureDef(
        "FEATURE_STRATEGY_MEAN_REVERSION",
        default=True,
        status=FeatureStatus.STABLE,
        description="Statistical mean-reversion strategy.",
    )
    STRATEGY_STOCHASTIC = _FeatureDef(
        "FEATURE_STRATEGY_STOCHASTIC",
        default=True,
        status=FeatureStatus.STABLE,
        description="Stochastic oscillator strategy.",
    )
    STRATEGY_BRAIN = _FeatureDef(
        "FEATURE_STRATEGY_BRAIN",
        default=True,
        status=FeatureStatus.BETA,
        description="AI meta-strategy that selects and weights sub-strategies dynamically.",
    )

    # ── Analysis & Order Flow ─────────────────────────────────────────────

    ORDER_FLOW_ANALYSIS = _FeatureDef(
        "FEATURE_ORDER_FLOW_ANALYSIS",
        default=True,
        status=FeatureStatus.STABLE,
        description="Base order flow: volume profile, delta, key levels.",
    )
    ORDER_FLOW_ADVANCED = _FeatureDef(
        "FEATURE_ORDER_FLOW_ADVANCED",
        default=True,
        status=FeatureStatus.STABLE,
        description="Advanced order flow: aggression metrics, stacked imbalances, oscillator.",
    )
    INSTITUTIONAL_FLOW = _FeatureDef(
        "FEATURE_INSTITUTIONAL_FLOW",
        default=True,
        status=FeatureStatus.STABLE,
        description="Institutional / smart-money flow detection.",
    )
    ORDER_FLOW_DASHBOARD = _FeatureDef(
        "FEATURE_ORDER_FLOW_DASHBOARD",
        default=True,
        status=FeatureStatus.STABLE,
        description="Unified order-flow dashboard aggregating all sub-systems.",
    )
    MARKET_ANALYSIS = _FeatureDef(
        "FEATURE_MARKET_ANALYSIS",
        default=True,
        status=FeatureStatus.STABLE,
        description="Market regime detection, multi-timeframe analysis, session analysis.",
    )
    MARKET_SCANNER = _FeatureDef(
        "FEATURE_MARKET_SCANNER",
        default=True,
        status=FeatureStatus.STABLE,
        description="Multi-symbol market scanner with pattern alerts.",
    )
    CANDLESTICK_PATTERNS = _FeatureDef(
        "FEATURE_CANDLESTICK_PATTERNS",
        default=True,
        status=FeatureStatus.STABLE,
        description="Japanese candlestick pattern recognition (17 patterns).",
    )
    DARK_POOL_DETECTION = _FeatureDef(
        "FEATURE_DARK_POOL_DETECTION",
        default=True,
        status=FeatureStatus.BETA,
        description="Heuristic detection of dark-pool / off-exchange block trades.",
    )

    # ── Data feeds ────────────────────────────────────────────────────────

    TIME_AND_SALES = _FeatureDef(
        "FEATURE_TIME_AND_SALES",
        default=True,
        status=FeatureStatus.STABLE,
        description="Tick-by-tick time-and-sales trade feed.",
    )
    DEPTH_OF_MARKET = _FeatureDef(
        "FEATURE_DEPTH_OF_MARKET",
        default=True,
        status=FeatureStatus.STABLE,
        description="Level-2 depth-of-market order book.",
    )
    MARKET_DATA_STREAMING = _FeatureDef(
        "FEATURE_MARKET_DATA_STREAMING",
        default=True,
        status=FeatureStatus.STABLE,
        description="WebSocket-based real-time market data streaming.",
    )

    # ── News & Sentiment ──────────────────────────────────────────────────

    NEWS_SENTIMENT = _FeatureDef(
        "FEATURE_NEWS_SENTIMENT",
        default=True,
        status=FeatureStatus.STABLE,
        description="NLP-based news sentiment analysis.",
    )
    ECONOMIC_CALENDAR = _FeatureDef(
        "FEATURE_ECONOMIC_CALENDAR",
        default=True,
        status=FeatureStatus.STABLE,
        description="High-impact economic event calendar with trade-pause logic.",
    )
    GEOPOLITICAL_RISK = _FeatureDef(
        "FEATURE_GEOPOLITICAL_RISK",
        default=True,
        status=FeatureStatus.BETA,
        description="Geopolitical risk scoring via World Monitor integration (XAU/USD bias).",
    )

    # ── Machine Learning ──────────────────────────────────────────────────

    ML_PREDICTIONS = _FeatureDef(
        "FEATURE_ML_PREDICTIONS",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description="LSTM/Transformer price-direction predictions.  Model training pipeline pending.",
    )
    ML_FEATURE_ENGINEERING = _FeatureDef(
        "FEATURE_ML_FEATURE_ENGINEERING",
        default=True,
        status=FeatureStatus.STABLE,
        description="Technical-indicator feature engineering for ML pipelines.",
    )

    # ── Charting ──────────────────────────────────────────────────────────

    CHART_ENGINE = _FeatureDef(
        "FEATURE_CHART_ENGINE",
        default=True,
        status=FeatureStatus.STABLE,
        description="Interactive chart rendering engine.",
    )
    DRAWING_TOOLS = _FeatureDef(
        "FEATURE_DRAWING_TOOLS",
        default=True,
        status=FeatureStatus.STABLE,
        description="Professional chart drawing toolkit (trendlines, Fibonacci, pitchfork, Elliott Wave, etc.).",
    )

    # ── Backtesting ───────────────────────────────────────────────────────

    BACKTESTING = _FeatureDef(
        "FEATURE_BACKTESTING",
        default=True,
        status=FeatureStatus.STABLE,
        description="Event-driven backtesting engine with full portfolio simulation.",
    )
    WALK_FORWARD = _FeatureDef(
        "FEATURE_WALK_FORWARD",
        default=True,
        status=FeatureStatus.STABLE,
        description="Walk-forward optimisation for strategy robustness testing.",
    )

    # ── Brokers ───────────────────────────────────────────────────────────

    BROKER_OANDA = _FeatureDef(
        "FEATURE_BROKER_OANDA",
        default=True,
        status=FeatureStatus.STABLE,
        description="OANDA REST/streaming broker connector.",
    )
    BROKER_ALPACA = _FeatureDef(
        "FEATURE_BROKER_ALPACA",
        default=True,
        status=FeatureStatus.STABLE,
        description="Alpaca broker connector.",
    )
    BROKER_BINANCE = _FeatureDef(
        "FEATURE_BROKER_BINANCE",
        default=True,
        status=FeatureStatus.STABLE,
        description="Binance spot/futures broker connector.",
    )
    BROKER_MT5 = _FeatureDef(
        "FEATURE_BROKER_MT5",
        default=True,
        status=FeatureStatus.STABLE,
        description="MetaTrader 5 broker connector.",
    )
    BROKER_INTERACTIVE_BROKERS = _FeatureDef(
        "FEATURE_BROKER_INTERACTIVE_BROKERS",
        default=True,
        status=FeatureStatus.STABLE,
        description="Interactive Brokers TWS/Gateway connector.",
    )

    # ── Social & Copy Trading ─────────────────────────────────────────────

    SOCIAL_TRADING = _FeatureDef(
        "FEATURE_SOCIAL_TRADING",
        default=True,
        status=FeatureStatus.BETA,
        description="Social trading profiles, leaderboards, and marketplace.",
    )
    COPY_TRADING = _FeatureDef(
        "FEATURE_COPY_TRADING",
        default=True,
        status=FeatureStatus.BETA,
        description="Automated trade copying from signal providers.",
    )

    # ── Monetisation ──────────────────────────────────────────────────────

    SUBSCRIPTIONS = _FeatureDef(
        "FEATURE_SUBSCRIPTIONS",
        default=True,
        status=FeatureStatus.STABLE,
        description="SaaS subscription management and billing.",
    )
    WHITE_LABEL = _FeatureDef(
        "FEATURE_WHITE_LABEL",
        default=True,
        status=FeatureStatus.BETA,
        description="White-label / reseller platform with tenant management and branding.",
    )
    ENTERPRISE = _FeatureDef(
        "FEATURE_ENTERPRISE",
        default=True,
        status=FeatureStatus.BETA,
        description="Enterprise licensing, audit logging, and SLA features.",
    )
    PAYMENTS = _FeatureDef(
        "FEATURE_PAYMENTS",
        default=True,
        status=FeatureStatus.STABLE,
        description="Integrated payment gateway, wallets, and transaction management.",
    )

    # ── Mobile ────────────────────────────────────────────────────────────

    MOBILE_API = _FeatureDef(
        "FEATURE_MOBILE_API",
        default=True,
        status=FeatureStatus.BETA,
        description="Mobile-optimised REST API endpoints.",
    )
    PUSH_NOTIFICATIONS = _FeatureDef(
        "FEATURE_PUSH_NOTIFICATIONS",
        default=True,
        status=FeatureStatus.BETA,
        description="Push notifications for iOS/Android.",
    )

    # ── Admin & Monitoring ────────────────────────────────────────────────

    ADMIN_DASHBOARD = _FeatureDef(
        "FEATURE_ADMIN_DASHBOARD",
        default=True,
        status=FeatureStatus.STABLE,
        description="Web-based admin dashboard (positions, risk, system health).",
    )
    ANALYTICS_MODULE = _FeatureDef(
        "FEATURE_ANALYTICS",
        default=True,
        status=FeatureStatus.STABLE,
        description="Portfolio analytics, performance reports, and risk analytics.",
    )

    # ── Experimental / Unreleased ─────────────────────────────────────────

    RESEARCH_MODULE = _FeatureDef(
        "FEATURE_RESEARCH",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description="Quantitative research tooling (alpha discovery, factor models).  WIP.",
    )
    EXPLAINABILITY = _FeatureDef(
        "FEATURE_EXPLAINABILITY",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description="SHAP/LIME explainability for ML model decisions.  WIP.",
    )
    TRANSPARENCY_REPORTS = _FeatureDef(
        "FEATURE_TRANSPARENCY",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description="Automated transparency / audit reports for regulators.  WIP.",
    )
    TEAMS_MODULE = _FeatureDef(
        "FEATURE_TEAMS",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description="Multi-user team workspaces with role-based access.  WIP.",
    )
    NOCODE_BUILDER = _FeatureDef(
        "FEATURE_NOCODE",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description="No-code strategy builder for non-technical users.  WIP.",
    )
    REPLAY_ENGINE = _FeatureDef(
        "FEATURE_REPLAY",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description="Tick-by-tick market replay for strategy analysis.  WIP.",
    )

    # ── Internal helpers ──────────────────────────────────────────────────

    def registry(self) -> Dict[str, Dict[str, Any]]:
        """
        Return metadata for every registered feature flag.

        Returns:
            Dict keyed by flag name.  Each value is a dict with keys:
            ``name``, ``env_var``, ``enabled``, ``default``, ``status``,
            ``description``.
        """
        result: Dict[str, Dict[str, Any]] = {}
        # Use vars() on the class so we get the raw descriptor objects
        # (getattr would invoke __get__ and return bools)
        for attr_name, descriptor in vars(type(self)).items():
            if isinstance(descriptor, _FeatureDef):
                result[attr_name] = descriptor.meta()
        return result

    def enabled_features(self) -> list[str]:
        """Return names of all currently enabled features."""
        return [name for name, info in self.registry().items() if info["enabled"]]

    def disabled_features(self) -> list[str]:
        """Return names of all currently disabled features."""
        return [name for name, info in self.registry().items() if not info["enabled"]]

    def log_summary(self) -> None:
        """Log a startup summary of enabled / disabled features."""
        reg = self.registry()
        enabled = [n for n, i in reg.items() if i["enabled"]]
        disabled = [n for n, i in reg.items() if not i["enabled"]]
        logger.info(
            "Feature flags: %d enabled, %d disabled",
            len(enabled),
            len(disabled),
        )
        for name in disabled:
            logger.info(
                "  DISABLED  %-40s  (env_var: %s)",
                name,
                reg[name]["env_var"],
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Global feature-flags instance — import and use directly::
#:
#:     from config.feature_flags import flags
#:     if flags.SOCIAL_TRADING: ...
flags = FeatureFlags()

__all__ = ["FeatureFlags", "FeatureStatus", "flags"]
