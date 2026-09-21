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
    # "active" | "paused". ``is_active`` is the gate broadcast_trade reads and
    # stays authoritative for order routing; ``status`` distinguishes a copy the
    # follower paused from one that was never started, which the API needs in
    # order to offer resume.
    status: str = "active"
    paused_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "copy_id": f"{self.follower_id}_{self.leader_id}",
            "follower_id": self.follower_id,
            "leader_id": self.leader_id,
            "copy_ratio": self.copy_ratio,
            "max_allocation": float(self.max_allocation) if self.max_allocation is not None else None,
            "max_per_trade": float(self.max_per_trade) if self.max_per_trade is not None else None,
            "status": self.status,
            "is_active": self.is_active,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
        }


import logging

_logger = logging.getLogger(__name__)

# Upper bound on ``copy_ratio``. A follower may deliberately size above the
# leader, but this multiplies real order quantity in ``broadcast_trade``, so an
# unbounded value is a fat-finger away from a position nobody intended.
_MAX_COPY_RATIO = 10.0


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

    # ── The interface api/copy_trading.py calls ───────────────────────────────
    #
    # ``api/copy_trading.py`` was written against seven methods that existed on
    # nothing. Production wires *this* class (``social/__init__`` constructs the
    # singleton and ``init_social`` assigns it to app_state), while the router's
    # fallback constructs ``AdvancedCopyTradingEngine`` — a third class, with a
    # third interface. Whichever object it got, every call raised AttributeError.
    #
    # ``get_my_copies`` caught that and returned ``{"copies": [], "total": 0}``,
    # so a feature that could not work at all presented as a feature the user
    # simply had not used. The rest returned HTTP 500.
    #
    # These are ``async`` because the router awaits them. The work is in-memory,
    # so nothing here blocks.

    def _require_own(self, copy_id: str, user_id: str | None) -> CopyRelationship:
        """Look up a copy and check the caller owns it.

        The router passes ``copy_id`` straight from the URL. Nothing tied it to
        the caller, so once these methods existed, any authenticated user on the
        professional plan could pause, re-risk or stop another user's copy by
        guessing an id — and the ids are ``follower_leader``, so they are
        guessable. Ownership is enforced here, at the one place that resolves an
        id, rather than in each of the five routes.

        Raises ``ValueError`` for both "no such copy" and "not yours", which the
        router maps to 404. They are deliberately indistinguishable: a
        different error for the second case would confirm that someone else's
        copy exists.
        """
        rel = self.relationships.get(copy_id)
        if rel is None or (user_id is not None and rel.follower_id != user_id):
            raise ValueError(f"copy {copy_id} not found")
        return rel

    async def get_user_copies(self, user_id: str) -> list[dict]:
        """Every copy this user follows, paused ones included.

        Not ``get_active_relationships``: a paused copy still belongs in the
        list, or the user has no way to resume it.
        """
        return [rel.to_dict() for rel in self.relationships.values() if rel.follower_id == user_id]

    async def pause_copy(self, copy_id: str, user_id: str | None = None) -> dict:
        rel = self._require_own(copy_id, user_id)
        rel.is_active = False
        rel.status = "paused"
        rel.paused_at = datetime.now(UTC)
        _logger.info("copy_trading: paused %s", copy_id)
        return rel.to_dict()

    async def resume_copy(self, copy_id: str, user_id: str | None = None) -> dict:
        rel = self._require_own(copy_id, user_id)
        rel.is_active = True
        rel.status = "active"
        rel.paused_at = None
        _logger.info("copy_trading: resumed %s", copy_id)
        return rel.to_dict()

    async def stop_copy(self, copy_id: str, user_id: str | None = None) -> dict:
        """Remove the relationship entirely.

        Distinct from ``stop_copying``, which deactivates but keeps the record.
        The route is documented as stopping "permanently", so it removes.
        """
        rel = self._require_own(copy_id, user_id)
        self.relationships.pop(copy_id, None)
        _logger.info("copy_trading: stopped %s", copy_id)
        return {**rel.to_dict(), "status": "stopped"}

    async def adjust_risk(self, copy_id: str, payload: dict, user_id: str | None = None) -> dict:
        """Change the sizing limits on a live copy.

        Validated rather than assigned: this scales real orders in
        ``broadcast_trade``, and a negative or absent ratio there would size
        every copied trade wrongly for as long as it went unnoticed.
        """
        rel = self._require_own(copy_id, user_id)
        payload = payload or {}

        if "copy_ratio" in payload and payload["copy_ratio"] is not None:
            try:
                ratio = float(payload["copy_ratio"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"copy_ratio must be a number, got {payload['copy_ratio']!r}") from exc
            if not 0 < ratio <= _MAX_COPY_RATIO:
                raise ValueError(f"copy_ratio must be in (0, {_MAX_COPY_RATIO}], got {ratio}")
            rel.copy_ratio = ratio

        for name in ("max_allocation", "max_per_trade"):
            if name not in payload:
                continue
            raw = payload[name]
            if raw is None:
                setattr(rel, name, None)
                continue
            try:
                value = Decimal(str(raw))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a number, got {raw!r}") from exc
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
            setattr(rel, name, value)

        _logger.info("copy_trading: risk adjusted on %s -> %s", copy_id, rel.to_dict())
        return rel.to_dict()

    async def get_copy_performance(self, copy_id: str, user_id: str | None = None) -> dict:
        """Configuration and settlement state for one copy.

        Per-copy P&L is **not** reported, because it is not tracked: copied
        orders are placed through ``broadcast_trade`` with the leader's fill id
        in the order metadata, and nothing reads that back to attribute a result
        to the relationship. Returning a plausible-looking number here would be
        worse than returning none, so the payload says so explicitly and the
        caller can render it as unavailable rather than as zero.
        """
        rel = self._require_own(copy_id, user_id)
        return {
            **rel.to_dict(),
            "pnl_available": False,
            "pnl_unavailable_reason": (
                "per-copy P&L attribution is not recorded; copied fills are not linked back to the relationship"
            ),
            "leader_performance": self._leader_performance(rel.leader_id),
        }

    @staticmethod
    def _leader_performance(leader_id: str) -> dict | None:
        """Whatever the profile manager holds for the leader, or None.

        Imported lazily: ``social/__init__`` imports this module, so a top-level
        import would be circular.
        """
        try:
            from social import profile_manager

            profile = profile_manager.get_profile(leader_id)
        except Exception:  # pragma: no cover - defensive
            return None
        if profile is None:
            return None
        return {
            "win_rate": profile.win_rate,
            "total_trades": profile.total_trades,
            "total_pnl": profile.total_pnl,
            "sharpe_ratio": profile.sharpe_ratio,
        }

    async def get_master_traders(self, sort_by: str = "followers", limit: int = 20) -> list[dict]:
        """Public trader profiles, ranked, with live follower counts.

        Follower counts come from this engine's own relationships rather than
        ``profile.total_followers``, which nothing updates when a copy starts or
        stops — that field would have drifted from the moment the feature was
        used.
        """
        try:
            from social import profile_manager

            profiles = profile_manager.list_profiles(public_only=True)
        except Exception:  # pragma: no cover - defensive
            profiles = []

        followers: dict[str, int] = {}
        for rel in self.relationships.values():
            if rel.is_active:
                followers[rel.leader_id] = followers.get(rel.leader_id, 0) + 1

        # Fields are listed explicitly rather than taken from
        # ``profile.to_dict()``, which includes ``email``. ``GET /masters`` has
        # no auth dependency, so dumping the profile would have published every
        # public trader's email address to anyone who asked — a leak introduced
        # by making this method work at all, which is why it is handled here
        # rather than left to the caller.
        rows = []
        for profile in profiles:
            data = profile.to_dict() if hasattr(profile, "to_dict") else dict(profile)
            trader_id = data.get("trader_id", "")
            rows.append(
                {
                    "trader_id": trader_id,
                    "username": data.get("username"),
                    "bio": data.get("bio", ""),
                    "avatar_url": data.get("avatar_url"),
                    "verified": data.get("verified", False),
                    "followers": followers.get(trader_id, 0),
                    "total_trades": data.get("total_trades", 0),
                    "win_rate": data.get("win_rate", 0.0),
                    "total_pnl": data.get("total_pnl", 0.0),
                    "sharpe_ratio": data.get("sharpe_ratio", 0.0),
                }
            )

        keys = {
            "followers": lambda r: r["followers"],
            "win_rate": lambda r: r["win_rate"],
            "profit": lambda r: r["total_pnl"],
            "sharpe": lambda r: r["sharpe_ratio"],
            "trades": lambda r: r["total_trades"],
        }
        rows.sort(key=keys.get(sort_by, keys["followers"]), reverse=True)
        for i, row in enumerate(rows[:limit], start=1):
            row["rank"] = i
        return rows[:limit]


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
