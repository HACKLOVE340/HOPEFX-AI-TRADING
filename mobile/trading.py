# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
mobile/trading.py
=================
MobileTradingEngine — delegates all order and position operations to the
real broker when wired via app_state, matching the MobileAPI pattern.

Wire by passing app_state (with .broker attribute) or broker directly:

    engine = MobileTradingEngine(app_state=app_state)
    engine = MobileTradingEngine(broker=broker_instance)

All methods return structured dicts. Async broker methods are awaited when
called from an async context; use execute_sync() for sync callers.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)


class MobileTradingEngine:
    """
    Mobile-optimised trading operations.

    Delegates to broker.place_order / broker.close_position /
    broker.cancel_order / broker.get_open_trades / broker.get_positions.
    Falls back to a structured error dict when broker is not wired.
    """

    def __init__(
        self,
        app_state: Any = None,
        broker: Any = None,
    ) -> None:
        self._app_state = app_state
        self._broker = broker
        # In-memory preset store (persisted externally by caller if needed)
        self._presets: dict[str, dict[str, Any]] = {}

    # ── Broker access ─────────────────────────────────────────────────────────

    def _get_broker(self) -> Any:
        if self._broker is not None:
            return self._broker
        if self._app_state is not None:
            return getattr(self._app_state, "broker", None)
        return None

    def _run(self, coro: Any) -> Any:
        """Run a coroutine from a sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already inside an event loop — caller must await directly
                raise RuntimeError("Cannot call _run() inside a running event loop. Use the async variant instead.")
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    # ── Order placement ───────────────────────────────────────────────────────

    async def place_order_async(
        self,
        user_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "mobile",
    ) -> dict[str, Any]:
        """Place an order via the real broker (async)."""
        broker = self._get_broker()
        if broker is None:
            logger.warning("MobileTradingEngine: broker not wired — order rejected")
            return {
                "order_id": None,
                "status": "rejected",
                "error": "Broker not available",
                "user_id": user_id,
                "symbol": symbol,
            }

        if order_type in ("LIMIT", "STOP") and price is None:
            return {
                "order_id": None,
                "status": "rejected",
                "error": f"price required for {order_type} orders",
            }

        try:
            result = await broker.place_order(
                user_id=user_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                comment=comment,
            )
            order_id = result.get("order_id") or str(uuid.uuid4())
            logger.info(
                "MobileTradingEngine: order placed user=%s symbol=%s side=%s qty=%s id=%s",
                user_id,
                symbol,
                side,
                quantity,
                order_id,
            )
            return {
                "order_id": order_id,
                "status": result.get("status", "submitted"),
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price or result.get("entry_price"),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            logger.error("MobileTradingEngine.place_order_async: %s", exc, exc_info=True)
            return {
                "order_id": None,
                "status": "error",
                "error": "Operation failed — check server logs",
                "user_id": user_id,
                "symbol": symbol,
            }

    def quick_order(
        self,
        user_id: str,
        preset_id: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """
        Execute a quick order from a saved preset.
        Preset must be registered via save_preset() first.
        """
        preset = self._presets.get(preset_id)
        if preset is None:
            return {
                "order_id": None,
                "status": "rejected",
                "error": f"Preset '{preset_id}' not found",
                "preset_id": preset_id,
            }

        if confirm:
            # Caller confirmed — execute via broker
            try:
                result = self._run(
                    self.place_order_async(
                        user_id=user_id,
                        symbol=preset["symbol"],
                        side=preset["side"],
                        quantity=preset["quantity"],
                        order_type=preset.get("order_type", "MARKET"),
                        price=preset.get("price"),
                        stop_loss=preset.get("stop_loss"),
                        take_profit=preset.get("take_profit"),
                        comment=f"quick_order:{preset_id}",
                    )
                )
                result["preset_id"] = preset_id
                return result
            except Exception as exc:
                logger.error("MobileTradingEngine.quick_order: %s", exc, exc_info=True)
                return {
                    "order_id": None,
                    "status": "error",
                    "error": "Operation failed — check server logs",
                    "preset_id": preset_id,
                }
        else:
            # Return preview for confirmation UI
            return {
                "order_id": None,
                "status": "pending_confirmation",
                "preset_id": preset_id,
                "preview": preset,
            }

    def save_preset(self, preset_id: str, preset: dict[str, Any]) -> None:
        """Save a quick-order preset."""
        required = {"symbol", "side", "quantity"}
        missing = required - set(preset.keys())
        if missing:
            raise ValueError(f"Preset missing required fields: {missing}")
        self._presets[preset_id] = preset
        logger.info("MobileTradingEngine: preset saved id=%s", preset_id)

    def delete_preset(self, preset_id: str) -> bool:
        if preset_id in self._presets:
            del self._presets[preset_id]
            return True
        return False

    def list_presets(self) -> list[dict[str, Any]]:
        return [{"preset_id": k, **v} for k, v in self._presets.items()]

    # ── Position management ───────────────────────────────────────────────────

    async def close_position_async(
        self,
        user_id: str,
        position_id: str,
        quantity: float | None = None,
    ) -> dict[str, Any]:
        """Close a specific position via the real broker (async)."""
        broker = self._get_broker()
        if broker is None:
            return {
                "status": "rejected",
                "error": "Broker not available",
                "position_id": position_id,
            }

        try:
            fn = getattr(broker, "close_position", None)
            if fn is None:
                return {
                    "status": "rejected",
                    "error": "Broker does not support close_position",
                    "position_id": position_id,
                }

            result = await fn(user_id=user_id, position_id=position_id, quantity=quantity)
            logger.info(
                "MobileTradingEngine: position closed user=%s id=%s",
                user_id,
                position_id,
            )
            return {
                "status": "closed",
                "position_id": position_id,
                "close_price": result.get("close_price") if isinstance(result, dict) else None,
                "pnl": result.get("pnl") if isinstance(result, dict) else None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            logger.error("MobileTradingEngine.close_position_async: %s", exc, exc_info=True)
            return {"status": "error", "error": "Operation failed — check server logs", "position_id": position_id}

    async def close_all_positions_async(
        self,
        user_id: str,
    ) -> dict[str, Any]:
        """Close all open positions via the real broker (async)."""
        broker = self._get_broker()
        if broker is None:
            return {
                "status": "rejected",
                "error": "Broker not available",
                "positions_closed": 0,
            }

        # Fetch open positions first
        positions: list[dict[str, Any]] = []
        try:
            fn = getattr(broker, "get_positions", None) or getattr(broker, "get_open_trades", None)
            if fn:
                raw = await fn(user_id)
                positions = raw if isinstance(raw, list) else []
        except Exception as exc:
            logger.warning("MobileTradingEngine.close_all: get_positions failed: %s", exc)

        closed = 0
        errors: list[str] = []
        for pos in positions:
            pos_id = pos.get("id") or pos.get("position_id") or pos.get("trade_id")
            if not pos_id:
                continue
            result = await self.close_position_async(user_id, str(pos_id))
            if result.get("status") == "closed":
                closed += 1
            else:
                errors.append(f"{pos_id}: {result.get('error', 'unknown')}")

        logger.info(
            "MobileTradingEngine.close_all: user=%s closed=%d errors=%d",
            user_id,
            closed,
            len(errors),
        )
        return {
            "action": "close_all",
            "user_id": user_id,
            "status": "completed" if not errors else "partial",
            "positions_closed": closed,
            "errors": errors,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def close_all_positions(
        self,
        user_id: str,
        confirm_required: bool = True,
    ) -> dict[str, Any]:
        """Sync wrapper for close_all_positions_async."""
        if confirm_required:
            return {
                "action": "close_all",
                "user_id": user_id,
                "status": "pending_confirmation",
                "positions_closed": 0,
            }
        try:
            return self._run(self.close_all_positions_async(user_id))
        except Exception as exc:
            logger.error("MobileTradingEngine.close_all_positions: %s", exc, exc_info=True)
            return {
                "action": "close_all",
                "user_id": user_id,
                "status": "error",
                "error": "Operation failed — check server logs",
                "positions_closed": 0,
            }

    # ── Order cancellation ────────────────────────────────────────────────────

    async def cancel_order_async(self, user_id: str, order_id: str) -> dict[str, Any]:
        """Cancel a pending order via the real broker (async)."""
        broker = self._get_broker()
        if broker is None:
            return {
                "status": "rejected",
                "error": "Broker not available",
                "order_id": order_id,
            }

        try:
            fn = getattr(broker, "cancel_order", None)
            if fn is None:
                return {
                    "status": "rejected",
                    "error": "Broker does not support cancel_order",
                    "order_id": order_id,
                }
            _result = await fn(user_id=user_id, order_id=order_id)
            logger.info("MobileTradingEngine: order cancelled user=%s id=%s", user_id, order_id)
            return {
                "status": "cancelled",
                "order_id": order_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            logger.error("MobileTradingEngine.cancel_order_async: %s", exc, exc_info=True)
            return {"status": "error", "error": "Operation failed — check server logs", "order_id": order_id}

    # ── Position / order queries ──────────────────────────────────────────────

    async def get_positions_async(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch open positions from the real broker (async)."""
        broker = self._get_broker()
        if broker is None:
            return []
        try:
            fn = getattr(broker, "get_positions", None) or getattr(broker, "get_open_trades", None)
            if fn is None:
                return []
            raw = await fn(user_id)
            return raw if isinstance(raw, list) else []
        except Exception as exc:
            logger.warning("MobileTradingEngine.get_positions_async: %s", exc)
            return []

    async def get_orders_async(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch open orders from the real broker (async)."""
        broker = self._get_broker()
        if broker is None:
            return []
        try:
            fn = getattr(broker, "get_orders", None) or getattr(broker, "get_pending_orders", None)
            if fn is None:
                return []
            raw = await fn(user_id)
            return raw if isinstance(raw, list) else []
        except Exception as exc:
            logger.warning("MobileTradingEngine.get_orders_async: %s", exc)
            return []
