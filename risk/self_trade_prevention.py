# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# risk/self_trade_prevention.py
"""
Self-Trade Prevention - FIA 3.5 Compliant
Prevents inadvertent self-matching and wash trades
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

UTC = timezone.utc

# Default lifetime for a resting order before it is treated as stale and pruned.
# Live callers (execution/engine.py) add every submitted order to the resting
# book but do not currently call remove_resting_order() on fill/cancel. Without
# a TTL the book grows unbounded and long-since-filled "phantom" orders keep
# matching against new orders forever, producing worsening false-positive
# self-trade blocks. One hour comfortably covers any genuinely resting order in
# this system (execution requests fill or are cancelled in seconds) while
# guaranteeing the book cannot accumulate stale entries.
_DEFAULT_RESTING_TTL_SECONDS = 3600.0


class SelfTradeAction(Enum):
    CANCEL_RESTING = "cancel_resting"  # Cancel the resting order
    CANCEL_NEW = "cancel_new"  # Cancel the new order
    CANCEL_BOTH = "cancel_both"  # Cancel both orders
    DECREMENT_SIZE = "decrement_size"  # Reduce both sizes


@dataclass
class Order:
    id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    size: float
    price: float
    timestamp: datetime
    account_id: str
    strategy_id: str | None = None


class SelfTradePrevention:
    """
    FIA 3.5: Self-Match Prevention
    Configurable at firm, group, trader, account, or strategy level
    """

    def __init__(
        self,
        prevention_level: str = "account",  # firm, group, account, strategy
        action: SelfTradeAction = SelfTradeAction.CANCEL_RESTING,
        allow_intentional: bool = False,
        resting_ttl_seconds: float | None = _DEFAULT_RESTING_TTL_SECONDS,
        max_resting_per_symbol: int = 10_000,
    ):
        self.level = prevention_level
        self.action = action
        self.allow_intentional = allow_intentional

        # Resting orders older than this (seconds) are considered filled/cancelled
        # and are pruned so they can neither grow the book unbounded nor match
        # against new orders. Set to None to disable TTL pruning entirely (not
        # recommended in live paths that never call remove_resting_order()).
        self.resting_ttl_seconds = resting_ttl_seconds
        # Hard upper bound per symbol as a defence-in-depth cap even inside the
        # TTL window; the oldest entries are dropped first.
        self.max_resting_per_symbol = max_resting_per_symbol

        # Track resting orders
        self.resting_orders: dict[str, list[Order]] = {}  # symbol -> orders

    def check_self_trade(self, new_order: Order) -> dict | None:
        """
        Check if new order would self-match with resting orders
        Returns action to take if self-trade detected
        """
        symbol = new_order.symbol

        if symbol not in self.resting_orders:
            return None

        # Drop filled/cancelled "phantom" orders before matching so stale entries
        # can never produce a false-positive self-trade block.
        self._prune_stale(symbol)

        opposing_side = "sell" if new_order.side == "buy" else "buy"

        for resting in self.resting_orders[symbol]:
            # Check if opposing side
            if resting.side != opposing_side:
                continue

            # Check if same entity (based on prevention level)
            if not self._same_entity(new_order, resting):
                continue

            # Check if prices cross
            if (new_order.side == "buy" and new_order.price >= resting.price) or (
                new_order.side == "sell" and new_order.price <= resting.price
            ):
                return self._handle_cross(new_order, resting)

        return None

    def _same_entity(self, order1: Order, order2: Order) -> bool:
        """Check if orders are from same entity based on prevention level"""
        if self.level == "firm":
            return True  # All orders in firm

        if self.level == "group":
            # Would need group ID
            return order1.strategy_id == order2.strategy_id

        if self.level == "account":
            return order1.account_id == order2.account_id

        if self.level == "strategy":
            return order1.strategy_id == order2.strategy_id

        return False

    def _handle_cross(self, new_order: Order, resting_order: Order) -> dict:
        """Determine action when self-trade detected"""
        logger.warning("Self-trade detected: %s vs %s on %s", new_order.id, resting_order.id, new_order.symbol)

        if self.action == SelfTradeAction.CANCEL_RESTING:
            return {
                "action": "cancel",
                "order_to_cancel": resting_order.id,
                "reason": "self_trade_prevention",
                "allow_new": True,
            }

        if self.action == SelfTradeAction.CANCEL_NEW:
            return {
                "action": "reject",
                "reason": "self_trade_prevention",
                "message": "Order would self-match with resting order",
            }

        if self.action == SelfTradeAction.CANCEL_BOTH:
            return {
                "action": "cancel_both",
                "orders_to_cancel": [resting_order.id],
                "reject_new": True,
                "reason": "self_trade_prevention",
            }

        if self.action == SelfTradeAction.DECREMENT_SIZE:
            min_size = min(new_order.size, resting_order.size)
            return {
                "action": "decrement",
                "new_order_size": new_order.size - min_size,
                "resting_order_size": resting_order.size - min_size,
                "reason": "self_trade_prevention",
            }

        return None

    def add_resting_order(self, order: Order) -> None:
        """Add order to resting book"""
        book = self.resting_orders.setdefault(order.symbol, [])
        book.append(order)
        # Prune on insert so the book self-limits even when callers never call
        # remove_resting_order() on fill/cancel.
        self._prune_stale(order.symbol)

    def remove_resting_order(self, order_id: str, symbol: str) -> None:
        """Remove filled or cancelled order"""
        if symbol in self.resting_orders:
            self.resting_orders[symbol] = [o for o in self.resting_orders[symbol] if o.id != order_id]

    @staticmethod
    def _order_age_seconds(order: Order, now: datetime) -> float:
        """Age of an order in seconds, tolerant of naive/aware timestamps."""
        ts = order.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return (now - ts).total_seconds()

    def _prune_stale(self, symbol: str) -> None:
        """
        Drop resting orders that are past their TTL, then enforce the per-symbol
        hard cap (oldest first). Keeps the book bounded and prevents already
        filled/cancelled phantom orders from matching against new orders.
        """
        book = self.resting_orders.get(symbol)
        if not book:
            return

        now = datetime.now(UTC)

        if self.resting_ttl_seconds is not None:
            ttl = self.resting_ttl_seconds
            kept = [o for o in book if self._order_age_seconds(o, now) <= ttl]
            dropped = len(book) - len(kept)
            if dropped:
                logger.debug("STP: pruned %d stale resting order(s) for %s (ttl=%ss)", dropped, symbol, ttl)
                book = kept
                self.resting_orders[symbol] = book

        # Defence-in-depth hard cap: keep the newest max_resting_per_symbol.
        if self.max_resting_per_symbol and len(book) > self.max_resting_per_symbol:
            overflow = len(book) - self.max_resting_per_symbol
            book.sort(key=lambda o: self._order_age_seconds(o, now))  # newest first
            del book[self.max_resting_per_symbol :]
            logger.warning(
                "STP: resting book for %s exceeded cap %d; dropped %d oldest order(s)",
                symbol,
                self.max_resting_per_symbol,
                overflow,
            )
