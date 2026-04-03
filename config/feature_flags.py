# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
from datetime import timezone
UTC = timezone.utc
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class FeatureStatus(StrEnum):
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

    The ``_is_feature_def = True`` sentinel lets ``registry()`` identify
    descriptors by attribute name rather than class identity, so it survives
    ``importlib.reload()`` (which creates a new class object).
    """

    _is_feature_def: bool = True

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
    def meta(self) -> dict[str, Any]:
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
        description="Live order execution via connected broker APIs. "
        "Intentionally off by default — set FEATURE_LIVE_TRADING=true "
        "only after verifying broker credentials and risk limits.",
    )
    RISK_MANAGER = _FeatureDef(
        "FEATURE_RISK_MANAGER",
        default=True,
        status=FeatureStatus.STABLE,
        description="Real-time position sizing, drawdown limits, and exposure control.",
    )
    ADVANCED_TRADING = _FeatureDef(
        "FEATURE_ADVANCED_TRADING",
        default=True,
        status=FeatureStatus.EXPERIMENTAL,
        description="Advanced order types and execution features (OCO, trailing stops, "
        "iceberg orders). Mounts api/advanced_trading.py router. "
        "Disable with FEATURE_ADVANCED_TRADING=false if broker does not support "
        "these order types.",
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

    WATCHLIST = _FeatureDef(
        "FEATURE_WATCHLIST",
        default=True,
        status=FeatureStatus.EXPERIMENTAL,
        description="Per-user symbol watchlists with price-change tracking. "
        "Mounts api/watchlist.py router. DB-backed with in-memory fallback.",
    )
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
        description="Intraday volume anomaly detection — flags bars where volume "
        "deviates significantly from the rolling baseline (z-score threshold). "
        "Labelled 'dark pool detection' historically; on retail feeds (OANDA, "
        "yfinance) there is no off-exchange tape, so this is a volume-spike "
        "heuristic only. True dark-pool flow requires FINRA ATS data.",
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
        default=True,
        status=FeatureStatus.STABLE,
        description="ML ensemble price-direction predictions (XGBoost/LightGBM/RF). "
        "Requires ml/saved_models/advanced_oos.pkl (68% OOS accuracy, p=0.0000, "
        "122 stationary features). Falls back to rule-based signal when model file "
        "is absent.",
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

    TRADE_JOURNAL = _FeatureDef(
        "FEATURE_TRADE_JOURNAL",
        default=True,
        status=FeatureStatus.EXPERIMENTAL,
        description="Per-user trade journal with notes, tags, and P&L annotations. "
        "Mounts api/journal.py router. DB-backed via db_store with in-memory fallback.",
    )
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

    BILLING_SUBSCRIPTION = _FeatureDef(
        "FEATURE_BILLING_SUBSCRIPTION",
        default=True,
        status=FeatureStatus.EXPERIMENTAL,
        description="GET /api/billing/subscription endpoint returning the authenticated "
        "user's tier, status, renewal date, and feature list. "
        "Falls back to FREE tier defaults when subscription_manager is unavailable.",
    )
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

    # ── Auth ──────────────────────────────────────────────────────────────

    TWO_FACTOR_AUTH = _FeatureDef(
        "FEATURE_TWO_FACTOR_AUTH",
        default=True,
        status=FeatureStatus.EXPERIMENTAL,
        description="TOTP-based two-factor authentication (RFC 6238). "
        "Mounts api/two_factor.py router (setup, verify, disable, backup-codes). "
        "Secrets persisted via db_store with in-memory fallback.",
    )

    # ── Admin & Monitoring ────────────────────────────────────────────────

    PRICE_ALERTS = _FeatureDef(
        "FEATURE_PRICE_ALERTS",
        default=True,
        status=FeatureStatus.EXPERIMENTAL,
        description="User-defined price alerts with Discord/Telegram delivery. "
        "Mounts api/alerts.py router. AlertEngine lazy-initialised if not started "
        "by the startup factory. Requires DISCORD_WEBHOOK_URL or TELEGRAM_BOT_TOKEN "
        "for delivery; alerts are stored regardless.",
    )
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

    # ── Research integration path (Phases 1–4) ───────────────────────────

    MTF_FUSION = _FeatureDef(
        "FEATURE_MTF_FUSION",
        default=True,
        status=FeatureStatus.BETA,
        description=(
            "Phase 1: Multi-timeframe fusion. Loads H4 and D1 OHLCV at startup "
            "and appends d_*/h_* regime features to the ML feature matrix at "
            "inference time. Gate: OOS accuracy must remain ≥ 65% after adding "
            "MTF features. Disable with FEATURE_MTF_FUSION=false."
        ),
    )
    ANOMALY_WEIGHTING = _FeatureDef(
        "FEATURE_ANOMALY_WEIGHTING",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description=(
            "Phase 2: Anomaly weighting (IF+LOF ensemble). Signals on anomalous "
            "bars are blended toward neutral by down_weight_factor (default 0.5). "
            "Gate: 30-day OANDA paper run must complete and paper Sharpe must not "
            "drop by more than 0.2 after enabling. "
            "Set OANDA_PAPER_RUN_START_UTC to the ISO-8601 start timestamp. "
            "Enable with FEATURE_ANOMALY_WEIGHTING=true after gate passes."
        ),
    )
    ONLINE_LEARNING = _FeatureDef(
        "FEATURE_ONLINE_LEARNING",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description=(
            "Phase 3: Online learning with ADWIN+Page-Hinkley drift detection. "
            "Blends primary model (default 0.7) with IncrementalXGBoost that "
            "updates on each confirmed fill (default 0.3). Adaptive weights shift "
            "toward the better-performing model. "
            "Gate: 90-day OANDA paper run with >= 500 fills. "
            "Set OANDA_PAPER_RUN_START_UTC and OANDA_PAPER_FILL_COUNT. "
            "Enable with FEATURE_ONLINE_LEARNING=true after gate passes."
        ),
    )
    DEEP_ENSEMBLE = _FeatureDef(
        "FEATURE_DEEP_ENSEMBLE",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description=(
            "Phase 4: Deep learning ensemble (LSTM/Transformer/TCN/Hybrid). "
            "Blends deep model probability (default weight 0.2) with the Phase 3 "
            "output. Gate: OOS accuracy >= 70% AND p-value < 0.001 (enforced in "
            "DeepEnsembleStore.load()). GPU training required. "
            "Set DEEP_ENSEMBLE_MODEL_PATH and DEEP_ENSEMBLE_META_PATH. "
            "Enable with FEATURE_DEEP_ENSEMBLE=true after training and OOS eval."
        ),
    )

    LSTM_SIGNAL_ENABLED = _FeatureDef(
        "FEATURE_LSTM_SIGNAL_ENABLED",
        default=False,
        status=FeatureStatus.EXPERIMENTAL,
        description=(
            "P3 research: wire the research/pipeline LSTM (DeepPredictor, "
            "architecture='lstm') as an optional secondary signal layer in "
            "HOPEFXBrain.process_bar(). "
            "When enabled, the LSTM probability is blended with the XGBoost "
            "probability: blended = (1 - w) * xgb_prob + w * lstm_prob, "
            "where w = LSTM_SIGNAL_WEIGHT (default 0.0 — set to e.g. 0.3). "
            "Prerequisites: "
            "(1) Train a DeepPredictor model using research/pipeline/models_deep.py "
            "and save to ml/saved_models/lstm_signal.pt. "
            "(2) Evaluate OOS accuracy — only enable if LSTM improves Sharpe. "
            "(3) Set LSTM_SIGNAL_WEIGHT=0.3 (or desired blend weight). "
            "Enable with LSTM_SIGNAL_ENABLED=true in .env. "
            "Fails silently if model file is absent — XGBoost signal is unaffected."
        ),
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
    GRAPHQL_API = _FeatureDef(
        "FEATURE_GRAPHQL_API",
        default=True,
        status=FeatureStatus.EXPERIMENTAL,
        description="GraphQL endpoint at /graphql (Strawberry schema). "
        "Requires strawberry-graphql to be installed; silently skipped if absent. "
        "GraphiQL playground available at GET /graphql when enabled.",
    )

    # ── Internal helpers ──────────────────────────────────────────────────

    def registry(self) -> dict[str, dict[str, Any]]:
        """
        Return metadata for every registered feature flag.

        Returns:
            Dict keyed by flag name.  Each value is a dict with keys:
            ``name``, ``env_var``, ``enabled``, ``default``, ``status``,
            ``description``.
        """
        result: dict[str, dict[str, Any]] = {}
        # Use vars() on the class so we get the raw descriptor objects
        # (getattr would invoke __get__ and return bools).
        # Check by sentinel attribute rather than isinstance() so the registry
        # survives importlib.reload() — reload creates a new _FeatureDef class
        # object, breaking isinstance checks on descriptors from the old class.
        for attr_name, descriptor in vars(type(self)).items():
            if getattr(descriptor, "_is_feature_def", False):
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
# Phase gate enforcement helpers
# ---------------------------------------------------------------------------


def check_phase2_gate() -> tuple[bool, str]:
    """
    Verify the Phase 2 (anomaly weighting) paper-trading gate.

    Reads OANDA_PAPER_RUN_START_UTC from the environment and checks that
    at least 30 calendar days have elapsed since the paper run started.

    Returns
    -------
    (passed, reason) : bool and human-readable explanation.
    """
    from datetime import datetime, timedelta

    start_str = os.getenv("OANDA_PAPER_RUN_START_UTC", "")
    if not start_str:
        return False, ("OANDA_PAPER_RUN_START_UTC not set. Set to ISO-8601 UTC timestamp when the paper run started.")
    try:
        start = datetime.fromisoformat(start_str)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        elapsed = datetime.now(UTC) - start
        required = timedelta(days=30)
        if elapsed < required:
            remaining = required - elapsed
            return False, (f"Phase 2 gate: {elapsed.days} days elapsed, {remaining.days} days remaining (need 30).")
        return True, f"Phase 2 gate passed: {elapsed.days} days elapsed."
    except ValueError as exc:
        return False, f"OANDA_PAPER_RUN_START_UTC parse error: {exc}"


def check_phase3_gate() -> tuple[bool, str]:
    """
    Verify the Phase 3 (online learning) paper-trading gate.

    Checks that:
    1. At least 90 calendar days have elapsed since OANDA_PAPER_RUN_START_UTC.
    2. OANDA_PAPER_FILL_COUNT >= 500.

    Returns
    -------
    (passed, reason) : bool and human-readable explanation.
    """
    from datetime import datetime, timedelta

    # Check fill count
    fill_count_str = os.getenv("OANDA_PAPER_FILL_COUNT", "0")
    try:
        fill_count = int(fill_count_str)
    except ValueError:
        return False, f"OANDA_PAPER_FILL_COUNT is not an integer: {fill_count_str!r}"

    if fill_count < 500:
        return False, (
            f"Phase 3 gate: {fill_count} fills recorded, need >= 500. "
            "Set OANDA_PAPER_FILL_COUNT after the paper run completes."
        )

    # Check elapsed days
    start_str = os.getenv("OANDA_PAPER_RUN_START_UTC", "")
    if not start_str:
        return False, ("OANDA_PAPER_RUN_START_UTC not set. Set to ISO-8601 UTC timestamp when the paper run started.")
    try:
        start = datetime.fromisoformat(start_str)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        elapsed = datetime.now(UTC) - start
        required = timedelta(days=90)
        if elapsed < required:
            remaining = required - elapsed
            return False, (f"Phase 3 gate: {elapsed.days} days elapsed, {remaining.days} days remaining (need 90).")
        return True, (f"Phase 3 gate passed: {elapsed.days} days elapsed, {fill_count} fills.")
    except ValueError as exc:
        return False, f"OANDA_PAPER_RUN_START_UTC parse error: {exc}"


def check_phase4_gate(
    oos_accuracy: float,
    p_value: float,
    oos_accuracy_gate: float = 0.70,
    p_value_gate: float = 0.001,
) -> tuple[bool, str]:
    """
    Verify the Phase 4 (deep ensemble) OOS gate.

    Both conditions must pass atomically.  This mirrors the check in
    DeepEnsembleStore._check_oos_gate() but is callable independently
    for pre-flight validation before enabling the flag.

    Parameters
    ----------
    oos_accuracy      : OOS accuracy from the trained model's meta JSON.
    p_value           : p-value from the trained model's meta JSON.
    oos_accuracy_gate : Minimum required OOS accuracy (default 0.70).
    p_value_gate      : Maximum allowed p-value (default 0.001).

    Returns
    -------
    (passed, reason) : bool and human-readable explanation.
    """
    reasons = []
    if oos_accuracy < oos_accuracy_gate:
        reasons.append(
            f"OOS accuracy {oos_accuracy:.1%} < gate {oos_accuracy_gate:.1%}",
        )
    if p_value >= p_value_gate:
        reasons.append(
            f"p-value {p_value:.4f} >= gate {p_value_gate:.4f}",
        )
    if reasons:
        return False, "Phase 4 gate failed: " + "; ".join(reasons)
    return True, (f"Phase 4 gate passed: OOS={oos_accuracy:.1%} p={p_value:.4f}")


def check_sharpe_gate(
    sharpe_before: float,
    sharpe_after: float,
    max_drop: float = 0.2,
) -> tuple[bool, str]:
    """
    Verify the Phase 2 Sharpe gate.

    The paper trading Sharpe must not decrease by more than `max_drop`
    over a 30-day window after enabling anomaly weighting.

    Parameters
    ----------
    sharpe_before : Sharpe ratio before enabling anomaly weighting.
    sharpe_after  : Sharpe ratio after enabling anomaly weighting.
    max_drop      : Maximum allowed Sharpe drop (default 0.2).

    Returns
    -------
    (passed, reason) : bool and human-readable explanation.
    """
    drop = sharpe_before - sharpe_after
    if drop > max_drop:
        return False, (
            f"Sharpe gate failed: dropped {drop:.3f} "
            f"({sharpe_before:.3f} → {sharpe_after:.3f}), "
            f"max allowed drop = {max_drop:.3f}."
        )
    return True, (f"Sharpe gate passed: drop={drop:.3f} ({sharpe_before:.3f} → {sharpe_after:.3f}).")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Global feature-flags instance — import and use directly::
#:
#:     from config.feature_flags import flags
#:     if flags.SOCIAL_TRADING: ...
flags = FeatureFlags()

__all__ = [
    "FeatureFlags",
    "FeatureStatus",
    "check_phase2_gate",
    "check_phase3_gate",
    "check_phase4_gate",
    "check_sharpe_gate",
    "flags",
]
