# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/roadmap_event_wiring.py
==============================
Event bus wiring for roadmap components.

Connects the new modules (Dynamic Strategy Registry, Advanced Orders,
Continuous Learning, Tenant Isolation, Telemetry) to the existing
event bus channels so they react to real-time system events.

Called from startup_event() after all components are initialised.

Usage
-----
    from core.roadmap_event_wiring import wire_roadmap_events
    await wire_roadmap_events(app_state)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def wire_roadmap_events(app_state: Any) -> list[str]:
    """
    Wire roadmap components to the event bus.

    Returns a list of successfully wired component names.
    """
    wired: list[str] = []

    # ── Dynamic Strategy Registry: listen for strategy reload events ──────────
    try:
        from core.event_bus import bus, CH_SYSTEM

        registry = getattr(app_state, "dynamic_strategy_registry", None)
        if registry is not None:

            async def _on_strategy_reload(msg: dict) -> None:
                """Handle strategy reload requests from admin/superadmin."""
                if msg.get("type") == "strategy_reload":
                    strategy_name = msg.get("strategy_name")
                    if strategy_name:
                        await registry.reload_strategy(strategy_name)
                    else:
                        await registry.reload_all()

            bus.subscribe_handler(CH_SYSTEM, _on_strategy_reload)
            wired.append("dynamic_strategy_registry")
            logger.info("Wired: DynamicStrategyRegistry -> CH_SYSTEM (strategy_reload)")
    except Exception as exc:
        logger.warning("Failed to wire dynamic_strategy_registry events: %s", exc)

    # ── Advanced Orders: listen for price ticks to evaluate triggers ───────────
    try:
        from core.event_bus import bus, CH_TICK

        order_manager = getattr(app_state, "advanced_order_manager", None)
        if order_manager is not None:

            async def _on_tick_for_orders(msg: dict) -> None:
                """Evaluate advanced order triggers on each tick."""
                symbol = msg.get("symbol")
                bid = msg.get("bid")
                ask = msg.get("ask")
                if symbol and bid and ask:
                    await order_manager.evaluate_triggers(
                        symbol=symbol,
                        bid=float(bid),
                        ask=float(ask),
                    )

            bus.subscribe_handler(CH_TICK, _on_tick_for_orders)
            wired.append("advanced_order_manager")
            logger.info("Wired: AdvancedOrderManager -> CH_TICK (trigger evaluation)")
    except Exception as exc:
        logger.warning("Failed to wire advanced_order_manager events: %s", exc)

    # ── Continuous Learning: listen for trade fills to accumulate training data ─
    try:
        from core.event_bus import bus, CH_ORDER

        cl_pipeline = getattr(app_state, "continuous_learning", None)
        if cl_pipeline is not None:

            async def _on_order_for_learning(msg: dict) -> None:
                """Accumulate trade outcomes for continuous learning."""
                if msg.get("type") in ("fill", "closed"):
                    await cl_pipeline.record_trade_outcome(msg)

            bus.subscribe_handler(CH_ORDER, _on_order_for_learning)
            wired.append("continuous_learning")
            logger.info("Wired: ContinuousLearningPipeline -> CH_ORDER (trade outcomes)")
    except Exception as exc:
        logger.warning("Failed to wire continuous_learning events: %s", exc)

    # ── Telemetry: publish span events for key trading actions ─────────────────
    try:
        from core.event_bus import bus, CH_SIGNAL, CH_BREACH
        from tracing.opentelemetry_setup import get_tracer, TraceContextPropagator

        tracer = get_tracer("hopefx.event_wiring")

        async def _on_signal_for_telemetry(msg: dict) -> None:
            """Create a trace span for each generated signal."""
            with tracer.start_as_current_span("event.signal_generated") as span:
                span.set_attribute("signal.symbol", msg.get("symbol", "unknown"))
                span.set_attribute("signal.direction", msg.get("direction", "unknown"))
                span.set_attribute("signal.confidence", msg.get("confidence", 0))
                # Inject trace context into the message for downstream correlation
                TraceContextPropagator.inject_context(msg)

        async def _on_breach_for_telemetry(msg: dict) -> None:
            """Create a trace span for risk breaches."""
            with tracer.start_as_current_span("event.risk_breach") as span:
                span.set_attribute("breach.type", msg.get("breach_type", "unknown"))
                span.set_attribute("breach.severity", msg.get("severity", "unknown"))

        bus.subscribe_handler(CH_SIGNAL, _on_signal_for_telemetry)
        bus.subscribe_handler(CH_BREACH, _on_breach_for_telemetry)
        wired.append("telemetry")
        logger.info("Wired: Telemetry -> CH_SIGNAL, CH_BREACH (span creation)")
    except Exception as exc:
        logger.warning("Failed to wire telemetry events: %s", exc)

    # ── Tenant Isolation: listen for tenant lifecycle events ───────────────────
    try:
        from core.event_bus import bus, CH_SYSTEM

        tenant_mgr = getattr(app_state, "tenant_isolation", None)
        if tenant_mgr is not None:

            async def _on_tenant_event(msg: dict) -> None:
                """Handle tenant provisioning/deprovisioning events."""
                msg_type = msg.get("type")
                tenant_id = msg.get("tenant_id")
                if msg_type == "tenant_provisioned" and tenant_id:
                    await tenant_mgr.provision_tenant(tenant_id)
                elif msg_type == "tenant_deprovisioned" and tenant_id:
                    await tenant_mgr.deprovision_tenant(tenant_id)

            bus.subscribe_handler(CH_SYSTEM, _on_tenant_event)
            wired.append("tenant_isolation")
            logger.info("Wired: TenantIsolationManager -> CH_SYSTEM (tenant lifecycle)")
    except Exception as exc:
        logger.warning("Failed to wire tenant_isolation events: %s", exc)

    logger.info("Roadmap event wiring complete: %d components wired", len(wired))
    return wired
