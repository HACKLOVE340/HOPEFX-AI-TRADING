# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/startup_helpers.py
=======================
Startup helper functions extracted from app.py to keep the top-level
module concise.  All functions are called from ``startup_event()`` in app.py.

Functions
---------
push_state_to_api_modules(state)
    Push app_state into API modules that hold a local reference.

prewarm_ml_predictor(state)
    Load EnhancedMLPredictor into memory before the first trade tick.

start_data_layer_orchestrator(state)
    Await the DataLayerOrchestrator startup with a configurable timeout.

init_kyc_gateway(state)
    Wire KYCGateway with ComplianceManager.

start_l2_feed(state)
    Start L2 order-book feed and depth bridge.

run_l2_depth_bridge(l2_feed, l2_symbols)
    Push L2 snapshots into MicrostructureEngine on each interval tick.

start_nuclear_price_bridge(state, nuclear_price_bridge_coro)
    Wrap the nuclear price bridge coroutine in an asyncio.Task.

mount_gateway(fastapi_app)
    Mount the APIGateway sub-application at /gateway when ENABLE_GATEWAY=true.
"""

from __future__ import annotations

import asyncio
import importlib as _il
import logging
import os
import pathlib

logger = logging.getLogger(__name__)


def push_state_to_api_modules(state) -> None:
    """Push *state* into every API module that holds a local ``app_state`` reference."""
    _state_modules = [
        ("api.trading", "set_state"),
        ("api.admin", "set_state"),
        ("api.watchlist", "set_state"),
        ("api.advanced_trading", "set_state"),
    ]
    for mod_name, fn_name in _state_modules:
        try:
            mod = _il.import_module(mod_name)
            fn = getattr(mod, fn_name, None)
            if fn is not None:
                fn(state)
                logger.info("State pushed → %s", mod_name)
        except ImportError as _imp_err:
            # Module may not be installed in all environments — benign, but log
            # at debug so a missing state push is visible when chasing it.
            logger.debug("State module %s unavailable: %s", mod_name, _imp_err)
        except Exception as exc:
            logger.warning("Failed to push state to %s: %s", mod_name, exc)


async def prewarm_ml_predictor(state) -> None:
    """Pre-warm EnhancedMLPredictor so the first trade is not cold.

    ``enhanced_ml_predictor.py`` is the active ML backend used by
    ``trader_full.py``.  Loading it here ensures the model is in memory
    before the first signal arrives rather than being lazily loaded on the
    first trade tick.
    """
    model_path = os.getenv("ML_MODEL_PATH", "ml/saved_models/hopefx")
    try:
        from enhanced_ml_predictor import EnhancedMLPredictor

        predictor = EnhancedMLPredictor()
        if pathlib.Path(model_path).exists():
            predictor.load(model_path)
            logger.info("EnhancedMLPredictor: model pre-warmed from %s", model_path)
        else:
            logger.info(
                "EnhancedMLPredictor: no saved model at %s — predictor ready for training",
                model_path,
            )
        state.ml_predictor = predictor
    except Exception as exc:
        logger.warning("EnhancedMLPredictor pre-warm failed (non-fatal): %s", exc)


async def start_data_layer_orchestrator(state) -> None:
    """Await the data layer orchestrator startup, retrying on failure.

    Uses ``asyncio.wait_for`` with a configurable timeout so a slow feed
    connection does not block other startup tasks indefinitely.

    **Why this retries now.** ``_started = True`` is the last line of
    ``orchestrator.start()``, so a failure in any of its ten feed-startup steps
    left the data layer down for the life of the process with no second attempt.
    That was survivable while the execution safety gate ignored ``_started``
    (F84) — the app simply traded blind. Now that the gate fails closed, the same
    single transient failure stops trading entirely and nothing ever tries again.
    The retry is part of that fix rather than an addition to it.

    Still non-fatal: exhausting the attempts logs and returns, so the rest of
    startup runs. Bounded and backing off, because an orchestrator that cannot
    start due to a wrong credential must not be reconnected to for ever at full
    speed.
    """
    orch_timeout = float(os.getenv("ORCHESTRATOR_STARTUP_TIMEOUT_S", "60.0"))
    attempts = max(1, int(os.getenv("ORCHESTRATOR_STARTUP_ATTEMPTS", "3")))
    base_delay = float(os.getenv("ORCHESTRATOR_RETRY_BASE_S", "5.0"))

    last_error: str = ""
    for attempt in range(1, attempts + 1):
        try:
            from data_layer.orchestrator import orchestrator

            await asyncio.wait_for(orchestrator.start(), timeout=orch_timeout)
            state.data_layer_orchestrator = orchestrator

            # Back-fill consumers built before this point.
            #
            # The component registry runs init_decision_engine — which builds
            # the Gatekeeper — before startup_event reaches this helper, so the
            # Gatekeeper is constructed while no orchestrator exists yet. It
            # then had no data source for the life of the process, and because
            # a missing orchestrator used to score data quality a perfect 1.0
            # rather than raising, nothing ever surfaced it. The reader now
            # fails closed, which turns the silent hole into a blocked signal —
            # correct, but still not a working gate. This connects it.
            for _holder in (state, getattr(state, "decision_engine", None)):
                _gk = getattr(_holder, "gatekeeper", None) or getattr(_holder, "_gate", None)
                if _gk is not None and getattr(_gk, "_orch", None) is None:
                    _gk._orch = orchestrator
                    logger.info(
                        "Data layer: attached orchestrator to %s built before it existed",
                        type(_gk).__name__,
                    )
            logger.info("Data layer orchestrator started (attempt %d/%d)", attempt, attempts)
            return
        except TimeoutError:
            last_error = f"timed out after {orch_timeout:.0f}s"
        except Exception as exc:
            last_error = str(exc)

        if attempt < attempts:
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Data layer orchestrator start failed (attempt %d/%d): %s — retrying in %.0fs",
                attempt,
                attempts,
                last_error,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)

    # Every attempt used. Say what this means, not just what happened: with the
    # execution gate failing closed, no data layer means no orders (F84).
    logger.error(
        "Data layer orchestrator FAILED to start after %d attempt(s): %s. "
        "Trading is BLOCKED — the execution safety gate refuses orders without a "
        "data layer, and data-layer endpoints will return degraded responses. "
        "Set ORCHESTRATOR_STARTUP_ATTEMPTS / ORCHESTRATOR_STARTUP_TIMEOUT_S to "
        "adjust, and check feed credentials and connectivity.",
        attempts,
        last_error,
    )


def init_kyc_gateway(state) -> None:
    """Wire KYCGateway with ComplianceManager (non-fatal)."""
    try:
        from compliance.kyc_provider import get_kyc_gateway, init_kyc_gateway as _init

        cm = getattr(state, "compliance_manager", None)
        if cm is not None:
            _init(cm)
            logger.info("KYCGateway initialised with ComplianceManager")
        else:
            get_kyc_gateway()  # initialise with no-DB fallback
            logger.warning("KYCGateway initialised without ComplianceManager (no DB)")
    except Exception as exc:
        logger.warning("KYCGateway init failed (non-fatal): %s", exc)


async def start_l2_feed(state) -> None:
    """Start L2 order book feed and depth bridge (non-fatal)."""
    try:
        from market_data.order_book import get_order_book_feed

        l2_symbols = os.getenv("L2_SYMBOLS", "XAU_USD,EUR_USD").split(",")
        l2_feed = get_order_book_feed()
        l2_task = asyncio.create_task(
            l2_feed.start([s.strip() for s in l2_symbols]),
            name="l2_order_book_feed",
        )
        if hasattr(state, "background_tasks"):
            state.background_tasks.append(l2_task)
        logger.info("L2 order book feed starting for symbols: %s", l2_symbols)

        l2_bridge_task = asyncio.create_task(
            run_l2_depth_bridge(l2_feed, l2_symbols),
            name="l2_depth_bridge",
        )
        if hasattr(state, "background_tasks"):
            state.background_tasks.append(l2_bridge_task)
    except Exception as exc:
        logger.warning("L2 order book feed failed to start (non-fatal): %s", exc)


async def run_l2_depth_bridge(l2_feed, l2_symbols: list) -> None:
    """Push L2 snapshots into MicrostructureEngine on each interval tick."""
    from data_layer.orchestrator import orchestrator as dl_orch

    interval = float(os.getenv("L2_SNAPSHOT_INTERVAL", "1.0"))
    while True:
        try:
            for sym in [s.strip() for s in l2_symbols]:
                snap = l2_feed.get_snapshot(sym)
                if snap is not None:
                    dl_orch._micro.inject_l2_depth(
                        symbol=sym,
                        bid_depth=snap.bid_depth,
                        ask_depth=snap.ask_depth,
                    )
        except Exception as exc:
            logger.debug("L2 depth bridge error: %s", exc)
        await asyncio.sleep(interval)


def start_nuclear_price_bridge(state, nuclear_price_bridge_coro) -> None:
    """Start NuclearStreamer price bridge background task (non-fatal).

    Parameters
    ----------
    state:
        The global ``AppState`` instance.
    nuclear_price_bridge_coro:
        The coroutine function imported from ``core.background_tasks``.
    """
    try:
        bridge_task = asyncio.create_task(nuclear_price_bridge_coro(state), name="nuclear_price_bridge")
        if hasattr(state, "background_tasks"):
            state.background_tasks.append(bridge_task)
        logger.info("nuclear_price_bridge task started")
    except Exception as exc:
        logger.warning("nuclear_price_bridge failed to start (non-fatal): %s", exc)


def mount_gateway(fastapi_app) -> None:
    """Mount the APIGateway sub-application at ``/gateway`` (non-fatal).

    Only mounts when ``ENABLE_GATEWAY=true`` — disabled by default to
    avoid exposing the extra surface area unless explicitly opted in.
    """
    if os.getenv("ENABLE_GATEWAY", "false").lower() != "true":
        return
    try:
        from api.gateway import build_gateway_app

        gw_app = build_gateway_app()
        if gw_app is not None:
            fastapi_app.mount("/gateway", gw_app)
            logger.info("APIGateway mounted at /gateway")
    except Exception as exc:
        logger.warning("APIGateway mount failed (non-fatal): %s", exc)
