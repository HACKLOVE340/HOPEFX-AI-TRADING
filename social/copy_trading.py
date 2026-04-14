# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Copy trading engine."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal


@dataclass
class CopyRelationship:
    follower_id: str
    leader_id: str
    copy_ratio: float = 1.0
    max_allocation: Decimal | None = None
    max_per_trade: Decimal | None = None
    is_active: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


import logging

_logger = logging.getLogger(__name__)


class CopyTradingEngine:
    """
    Manages copy-trading relationships between followers and leaders.

    broker must be injected via set_broker() (or the constructor) before
    broadcast_trade() can place real orders.  Without a broker every copy
    trade is logged as broker_offline — the same safe-fail behaviour as
    AdvancedCopyTradingEngine.
    """

    def __init__(self, broker=None, config=None):
        self.relationships: dict[str, CopyRelationship] = {}
        self.broker = broker
        self.config = config or {}

    def set_broker(self, broker) -> None:
        """Inject the live broker after construction (called by startup_factories)."""
        self.broker = broker
        _logger.info("CopyTradingEngine: broker injected (%s)", type(broker).__name__)

    def _key(self, follower_id: str, leader_id: str) -> str:
        return f"{follower_id}_{leader_id}"

    def start_copying(
        self,
        follower_id: str,
        leader_id: str,
        copy_ratio: float = 1.0,
        max_allocation: Decimal | None = None,
        max_per_trade: Decimal | None = None,
    ) -> CopyRelationship:
        rel = CopyRelationship(
            follower_id=follower_id,
            leader_id=leader_id,
            copy_ratio=copy_ratio,
            max_allocation=max_allocation,
            max_per_trade=max_per_trade,
        )
        self.relationships[self._key(follower_id, leader_id)] = rel
        return rel

    def stop_copying(self, follower_id: str, leader_id: str) -> bool:
        key = self._key(follower_id, leader_id)
        if key not in self.relationships:
            return False
        self.relationships[key].is_active = False
        return True

    def sync_trade(self, trade_id: str, leader_id: str) -> dict[str, str]:
        """Return {copy_id: follower_id} for all active followers of leader_id."""
        result = {}
        for rel in self.relationships.values():
            if rel.leader_id == leader_id and rel.is_active:
                copy_id = f"COPY_{trade_id}_{rel.follower_id}"
                result[copy_id] = rel.follower_id
        return result

    def broadcast_trade(
        self,
        leader_id: str,
        symbol: str,
        direction: str,
        quantity: float,
        fill_price: float,
        fill_id: str,
    ) -> dict[str, dict]:
        """
        Place proportional copy orders for every active follower of leader_id.

        Returns a dict of {follower_id: result} where result has keys:
          status  — "filled" | "broker_offline" | "error"
          reason  — human-readable detail
          order   — broker response (when status == "filled")
        """
        results: dict[str, dict] = {}

        active = [r for r in self.relationships.values() if r.leader_id == leader_id and r.is_active]
        if not active:
            return results

        if not self.broker:
            _logger.warning(
                "CopyTradingEngine.broadcast_trade: broker not injected — "
                "%d follower(s) will not receive copy of fill %s",
                len(active),
                fill_id,
            )
            for rel in active:
                results[rel.follower_id] = {"status": "broker_offline", "reason": "broker not injected"}
            return results

        for rel in active:
            copy_qty = round(quantity * rel.copy_ratio, 4)
            if rel.max_per_trade is not None:
                copy_qty = min(copy_qty, float(rel.max_per_trade))
            if copy_qty <= 0:
                results[rel.follower_id] = {"status": "skipped", "reason": "copy_qty <= 0"}
                continue
            try:
                order_result = self.broker.place_order(
                    symbol=symbol,
                    direction=direction,
                    quantity=copy_qty,
                    order_type="market",
                    metadata={
                        "copy_of_fill": fill_id,
                        "leader_id": leader_id,
                        "follower_id": rel.follower_id,
                    },
                )
                results[rel.follower_id] = {"status": "filled", "order": order_result}
                _logger.info(
                    "copy_trade: follower=%s leader=%s symbol=%s dir=%s qty=%.4f",
                    rel.follower_id,
                    leader_id,
                    symbol,
                    direction,
                    copy_qty,
                )
            except Exception as exc:
                _logger.error("copy_trade failed for follower=%s: %s", rel.follower_id, exc)
                results[rel.follower_id] = {"status": "error", "reason": str(exc)}

        return results

    def get_active_relationships(self, user_id: str, as_follower: bool = True) -> list[CopyRelationship]:
        out = []
        for rel in self.relationships.values():
            if not rel.is_active:
                continue
            if (as_follower and rel.follower_id == user_id) or (not as_follower and rel.leader_id == user_id):
                out.append(rel)
        return out


class RiskLimitExceededError(Exception):
    """Raised when a copy trade would exceed risk limits."""


async def _copy_trade(
    self,
    leader_trade: dict,
    follower_config: dict,
    follower_balance: float = 100_000.0,
    balance: float | None = None,
) -> dict:
    """Copy a leader trade proportionally, respecting follower risk limits."""
    if balance is not None:
        follower_balance = balance

    copy_ratio = follower_config.get("copy_ratio", 1.0)
    max_pos_size = follower_config.get("max_position_size", 1.0)  # fraction of balance
    leader_qty = leader_trade.get("quantity", 1.0)
    leader_balance = 100_000.0  # assumed leader balance

    # Proportional sizing
    balance_ratio = follower_balance / leader_balance
    raw_qty = leader_qty * copy_ratio * balance_ratio

    # max_position_size is a fraction of balance expressed as notional lots.
    # 1 lot ≈ $1 notional when no price given; use price if available.
    price = leader_trade.get("price")
    # No price: treat max_position_size as max fraction of leader qty
    max_qty_by_risk = (follower_balance * max_pos_size) / price if price and price > 0 else leader_qty * max_pos_size

    if raw_qty > max_qty_by_risk:
        raise RiskLimitExceededError(f"Copied quantity {raw_qty:.4f} exceeds max allowed {max_qty_by_risk:.4f}")

    return {
        "symbol": leader_trade["symbol"],
        "side": leader_trade.get("side", "buy"),
        "quantity": round(raw_qty, 4),
        "price": price or 0.0,
        "follower_id": follower_config.get("follower_id", ""),
    }


def _calculate_leaderboard(self, traders: list) -> list:
    """Rank traders by composite score: return × sharpe × log1p(followers)."""
    import math

    scored = []
    for t in traders:
        score = t.get("return", 0) * t.get("sharpe", 1) * math.log1p(t.get("followers", 0))
        scored.append({**t, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, t in enumerate(scored):
        t["rank"] = i + 1
    return scored


CopyTradingEngine.copy_trade = _copy_trade
CopyTradingEngine.calculate_leaderboard = _calculate_leaderboard
