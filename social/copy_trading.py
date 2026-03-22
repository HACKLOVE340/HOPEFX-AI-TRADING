"""Copy trading engine."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class CopyRelationship:
    follower_id: str
    leader_id: str
    copy_ratio: float = 1.0
    max_allocation: Optional[Decimal] = None
    max_per_trade: Optional[Decimal] = None
    is_active: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CopyTradingEngine:
    """Manages copy-trading relationships between followers and leaders."""

    def __init__(self):
        self.relationships: Dict[str, CopyRelationship] = {}

    def _key(self, follower_id: str, leader_id: str) -> str:
        return f"{follower_id}_{leader_id}"

    def start_copying(self, follower_id: str, leader_id: str,
                      copy_ratio: float = 1.0,
                      max_allocation: Optional[Decimal] = None,
                      max_per_trade: Optional[Decimal] = None) -> CopyRelationship:
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

    def sync_trade(self, trade_id: str, leader_id: str) -> Dict[str, str]:
        """Propagate a leader trade to all active followers. Returns {copy_id: follower_id}."""
        result = {}
        for key, rel in self.relationships.items():
            if rel.leader_id == leader_id and rel.is_active:
                copy_id = f"COPY_{trade_id}_{rel.follower_id}"
                result[copy_id] = rel.follower_id
        return result

    def get_active_relationships(self, user_id: str, as_follower: bool = True) -> List[CopyRelationship]:
        out = []
        for rel in self.relationships.values():
            if not rel.is_active:
                continue
            if as_follower and rel.follower_id == user_id:
                out.append(rel)
            elif not as_follower and rel.leader_id == user_id:
                out.append(rel)
        return out
