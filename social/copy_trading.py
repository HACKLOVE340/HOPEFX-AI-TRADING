"""
Copy Trading Engine

Enables users to automatically copy trades from successful traders.
"""

from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime


class CopyRelationship:
    """Represents a copy trading relationship"""
    def __init__(self, follower_id: str, leader_id: str, copy_ratio: float = 1.0):
        self.follower_id = follower_id
        self.leader_id = leader_id
        self.copy_ratio = copy_ratio
        self.max_allocation = None
        self.max_per_trade = None
        self.is_active = True
        self.started_at = datetime.utcnow()


class CopyTradingEngine:
    """Manages copy trading relationships and trade synchronization"""
    
    def __init__(self):
        self.relationships: Dict[str, CopyRelationship] = {}
    
    def start_copying(
        self, 
        follower_id: str, 
        leader_id: str,
        copy_ratio: float = 1.0,
        max_allocation: Optional[Decimal] = None,
        max_per_trade: Optional[Decimal] = None
    ) -> CopyRelationship:
        """Start copying a leader's trades"""
        relationship = CopyRelationship(follower_id, leader_id, copy_ratio)
        relationship.max_allocation = max_allocation
        relationship.max_per_trade = max_per_trade
        
        relationship_id = f"{follower_id}_{leader_id}"
        self.relationships[relationship_id] = relationship
        
        return relationship
    
    def stop_copying(self, follower_id: str, leader_id: str) -> bool:
        """Stop copying a leader's trades"""
        relationship_id = f"{follower_id}_{leader_id}"
        if relationship_id in self.relationships:
            self.relationships[relationship_id].is_active = False
            return True
        return False
    
    def sync_trade(self, leader_trade_id: str, leader_id: str) -> List[str]:
        """Synchronize a leader's trade to all followers"""
        copied_trades = []
        
        for rel_id, relationship in self.relationships.items():
            if relationship.leader_id == leader_id and relationship.is_active:
                # Create follower trade (simplified)
                follower_trade_id = f"COPY_{leader_trade_id}_{relationship.follower_id}"
                copied_trades.append(follower_trade_id)
        
        return copied_trades
    
    def get_active_relationships(self, user_id: str, as_follower: bool = True) -> List[CopyRelationship]:
        """Get active copy relationships for a user"""
        relationships = []
        for relationship in self.relationships.values():
            if as_follower and relationship.follower_id == user_id and relationship.is_active:
                relationships.append(relationship)
            elif not as_follower and relationship.leader_id == user_id and relationship.is_active:
                relationships.append(relationship)
        return relationships
