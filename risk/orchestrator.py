# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/orchestrator.py
=====================
RiskOrchestrator — central risk control surface for the nuclear supervisor
and any other component that needs to dynamically adjust risk limits.

Responsibilities
----------------
1. set_max_risk(fraction)   — clamp the global max-risk budget [0, 1].
   0.0 = no new risk (nuclear mode), 1.0 = full budget restored.
2. activate_hedge_mode()    — open inverse/hedge positions on a symbol.
3. deactivate_hedge_mode()  — close hedge positions and restore normal mode.
4. get_current_exposure()   — return current portfolio risk exposure [0, 1].
5. get_status()             — snapshot of all risk parameters.

The orchestrator is a thin coordination layer.  It delegates actual order
placement to the broker adapter and actual position sizing to RiskManager.
Both are injected lazily to avoid circular imports.

Thread / async safety
---------------------
All public methods are async-safe.  Internal state is protected by an
asyncio.Lock so concurrent callers (supervisor + engine) do not race.

Usage
-----
    from risk.orchestrator import risk_orchestrator

    await risk_orchestrator.set_max_risk(0.0)          # nuclear
    await risk_orchestrator.set_max_risk(0.15)         # hedge
    await risk_orchestrator.activate_hedge_mode("XAU_USD")
    exposure = await risk_orchestrator.get_current_exposure()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class HedgePosition:
    """Tracks an open hedge position."""
    symbol: str
    units: float
    direction: str          # "short" or "long"
    opened_at: float = field(default_factory=time.time)
    order_id: Optional[str] = None


@dataclass
class RiskSnapshot:
    """Point-in-time risk state."""
    max_risk_fraction: float
    current_exposure: float
    hedge_active: bool
    hedge_positions: List[HedgePosition]
    trading_allowed: bool
    timestamp: float = field(default_factory=time.time)


# ── Orchestrator ──────────────────────────────────────────────────────────────


class RiskOrchestrator:
    """
    Central risk control surface.

    Parameters
    ----------
    default_max_risk : float
        Starting max-risk fraction (default 1.0 = full budget).
    hedge_units : float
        Default units for hedge positions (default 1000 = 0.01 lot on XAU).
    broker : optional
        Broker adapter with async place_order(symbol, units, side) method.
        Injected lazily if not provided at construction.
    """

    def __init__(
        self,
        default_max_risk: float = 1.0,
        hedge_units: float = 1_000.0,
        broker: Optional[Any] = None,
    ) -> None:
        self._max_risk: float = float(default_max_risk)
        self._hedge_units = hedge_units
        self._broker = broker
        self._hedge_active: bool = False
        self._hedge_positions: List[HedgePosition] = []
        self._trading_allowed: bool = True
        self._lock = asyncio.Lock()
        self._history: List[Dict[str, Any]] = []   # last 200 risk events

        logger.info(
            "RiskOrchestrator initialised | max_risk=%.2f hedge_units=%.0f",
            self._max_risk, self._hedge_units,
        )

    # ── Broker injection ──────────────────────────────────────────────────────

    def inject_broker(self, broker: Any) -> None:
        """Inject broker adapter after construction."""
        self._broker = broker
        logger.info("RiskOrchestrator: broker injected (%s)", type(broker).__name__)

    def _get_broker(self) -> Optional[Any]:
        """Lazy-load broker from hopefx_engine if not injected."""
        if self._broker is not None:
            return self._broker
        try:
            from hopefx_engine import HopeFXEngine
            # Access the module-level engine instance if available
            import hopefx_engine as _eng
            engine = getattr(_eng, "_engine_instance", None)
            if engine is not None:
                broker = getattr(engine, "_broker", None)
                if broker is not None:
                    self._broker = broker
                    return broker
        except Exception:
            pass
        return None

    # ── Core risk controls ────────────────────────────────────────────────────

    async def set_max_risk(self, fraction: float) -> None:
        """
        Set the global max-risk budget.

        Parameters
        ----------
        fraction : float
            Risk fraction [0.0, 1.0].
            0.0 = no new positions (nuclear mode).
            1.0 = full budget restored.
        """
        fraction = float(max(0.0, min(1.0, fraction)))
        async with self._lock:
            old = self._max_risk
            self._max_risk = fraction
            self._trading_allowed = fraction > 0.0

            self._record_event("set_max_risk", {
                "old_fraction": old,
                "new_fraction": fraction,
                "trading_allowed": self._trading_allowed,
            })

            logger.warning(
                "RiskOrchestrator: max_risk %.2f → %.2f | trading_allowed=%s",
                old, fraction, self._trading_allowed,
            )

            # Propagate to RiskManager if available
            await self._propagate_to_risk_manager(fraction)

    async def _propagate_to_risk_manager(self, fraction: float) -> None:
        """Push the new max-risk fraction into RiskManager."""
        try:
            from risk.manager import risk_manager
            if hasattr(risk_manager, "config"):
                # RiskConfig.max_risk_per_trade is the primary lever
                risk_manager.config.max_risk_per_trade = fraction * 0.02  # 2% base × fraction
                risk_manager.config.max_portfolio_risk = fraction * 0.06  # 6% base × fraction
                logger.debug(
                    "RiskManager updated: max_risk_per_trade=%.4f max_portfolio_risk=%.4f",
                    risk_manager.config.max_risk_per_trade,
                    risk_manager.config.max_portfolio_risk,
                )
        except Exception as exc:
            logger.warning("Could not propagate risk to RiskManager: %s", exc)

    # ── Hedge mode ────────────────────────────────────────────────────────────

    async def activate_hedge_mode(self, symbol: str = "XAU_USD") -> None:
        """
        Open an inverse hedge position on the given symbol.

        In nuclear/hedge mode we open a short on XAU_USD to offset long
        exposure.  The hedge size is self._hedge_units.
        """
        async with self._lock:
            if self._hedge_active:
                logger.info("Hedge already active — skipping duplicate activation")
                return

            self._hedge_active = True
            logger.warning("RiskOrchestrator: activating hedge mode on %s", symbol)

            broker = self._get_broker()
            order_id: Optional[str] = None

            if broker is not None:
                try:
                    result = await broker.place_order(
                        symbol=symbol,
                        units=-self._hedge_units,   # negative = short
                        order_type="MARKET",
                        label="NUCLEAR_HEDGE",
                    )
                    order_id = str(result.get("id", "")) if isinstance(result, dict) else str(result)
                    logger.info("Hedge order placed: %s", order_id)
                except Exception as exc:
                    logger.error("Hedge order failed: %s", exc)
            else:
                logger.warning(
                    "No broker available — hedge position NOT placed. "
                    "Manual hedge required on %s (%.0f units short)",
                    symbol, self._hedge_units,
                )

            pos = HedgePosition(
                symbol=symbol,
                units=self._hedge_units,
                direction="short",
                order_id=order_id,
            )
            self._hedge_positions.append(pos)
            self._record_event("activate_hedge", {
                "symbol": symbol,
                "units": self._hedge_units,
                "order_id": order_id,
            })

    async def deactivate_hedge_mode(self) -> None:
        """Close all open hedge positions and restore normal mode."""
        async with self._lock:
            if not self._hedge_active:
                return

            broker = self._get_broker()
            closed: List[str] = []

            for pos in self._hedge_positions:
                if broker is not None:
                    try:
                        # Close by placing opposite order
                        result = await broker.place_order(
                            symbol=pos.symbol,
                            units=pos.units,   # positive = buy back short
                            order_type="MARKET",
                            label="NUCLEAR_HEDGE_CLOSE",
                        )
                        closed.append(pos.symbol)
                        logger.info("Hedge closed on %s", pos.symbol)
                    except Exception as exc:
                        logger.error("Failed to close hedge on %s: %s", pos.symbol, exc)
                else:
                    logger.warning(
                        "No broker — hedge on %s NOT closed. Manual close required.",
                        pos.symbol,
                    )

            self._hedge_positions.clear()
            self._hedge_active = False
            self._record_event("deactivate_hedge", {"closed_symbols": closed})
            logger.info("RiskOrchestrator: hedge mode deactivated")

    # ── Exposure query ────────────────────────────────────────────────────────

    async def get_current_exposure(self) -> float:
        """
        Return current portfolio risk exposure as a fraction [0, 1].

        Tries to read from the engine's trade logger or risk manager.
        Falls back to 0.5 (conservative estimate) if unavailable.
        """
        try:
            from risk.manager import risk_manager
            if hasattr(risk_manager, "get_current_exposure"):
                return float(risk_manager.get_current_exposure())
        except Exception:
            pass

        try:
            from data_layer.orchestrator import orchestrator
            tick = orchestrator.get_latest_tick()
            if tick and hasattr(tick, "exposure"):
                return float(tick.exposure)
        except Exception:
            pass

        # Derive from max_risk as a proxy
        return min(1.0, 1.0 - self._max_risk + 0.1)

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of current risk orchestrator state."""
        return {
            "max_risk_fraction": self._max_risk,
            "trading_allowed": self._trading_allowed,
            "hedge_active": self._hedge_active,
            "hedge_positions": [
                {
                    "symbol": p.symbol,
                    "units": p.units,
                    "direction": p.direction,
                    "order_id": p.order_id,
                    "age_seconds": round(time.time() - p.opened_at, 1),
                }
                for p in self._hedge_positions
            ],
            "event_count": len(self._history),
            "last_event": self._history[-1] if self._history else None,
        }

    def is_trading_allowed(self) -> bool:
        """Quick check — False when max_risk == 0 (nuclear mode)."""
        return self._trading_allowed

    def get_max_risk(self) -> float:
        """Return current max-risk fraction."""
        return self._max_risk

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _record_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Append to internal audit history (capped at 200 entries)."""
        self._history.append({
            "ts": time.time(),
            "type": event_type,
            **data,
        })
        if len(self._history) > 200:
            self._history.pop(0)


# ── FastAPI router (optional) ─────────────────────────────────────────────────

def create_orchestrator_router(orchestrator_instance: RiskOrchestrator):
    """
    Create a FastAPI router exposing risk orchestrator controls via HTTP.

    Mount with:
        app.include_router(create_orchestrator_router(risk_orchestrator),
                           prefix="/risk/orchestrator", tags=["risk"])
    """
    try:
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel, Field
    except ImportError:
        return None

    router = APIRouter()

    class SetMaxRiskRequest(BaseModel):
        fraction: float = Field(..., ge=0.0, le=1.0, description="Risk fraction [0, 1]")

    class HedgeRequest(BaseModel):
        symbol: str = Field(default="XAU_USD", description="Symbol to hedge")

    @router.get("/status")
    async def get_status():
        return orchestrator_instance.get_status()

    @router.post("/set_max_risk")
    async def set_max_risk(req: SetMaxRiskRequest):
        await orchestrator_instance.set_max_risk(req.fraction)
        return {"status": "ok", "max_risk": orchestrator_instance.get_max_risk()}

    @router.post("/hedge/activate")
    async def activate_hedge(req: HedgeRequest):
        await orchestrator_instance.activate_hedge_mode(req.symbol)
        return {"status": "ok", "hedge_active": orchestrator_instance._hedge_active}

    @router.post("/hedge/deactivate")
    async def deactivate_hedge():
        await orchestrator_instance.deactivate_hedge_mode()
        return {"status": "ok", "hedge_active": orchestrator_instance._hedge_active}

    @router.get("/exposure")
    async def get_exposure():
        exposure = await orchestrator_instance.get_current_exposure()
        return {"current_exposure": exposure}

    return router


# ── Module-level singleton ────────────────────────────────────────────────────

risk_orchestrator = RiskOrchestrator()
