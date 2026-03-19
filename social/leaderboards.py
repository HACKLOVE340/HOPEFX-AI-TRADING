"""
Performance Leaderboard System
- Rank traders by performance
- Calculate rankings with filters
- Historical leaderboard snapshots
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class LeaderboardEntry:
    """Single leaderboard entry"""
    rank: int
    trader_id: str
    username: str
    win_rate: float
    total_pnl: float
    sharpe_ratio: float
    followers: int
    trust_score: float
    verified: bool

class PerformanceLeaderboard:
    """Leaderboard rankings"""
    
    def __init__(self):
        self.leaderboard: List[LeaderboardEntry] = []
        self.historical_snapshots: Dict[datetime, List[LeaderboardEntry]] = {}
    
    def update_leaderboard(self, traders_data: List[Dict]) -> List[LeaderboardEntry]:
        """Update leaderboard with current trader data"""
        entries = []
        
        for idx, trader in enumerate(sorted(traders_data, 
                                           key=lambda x: x.get('win_rate', 0) * x.get('total_pnl', 0),
                                           reverse=True), 1):
            entry = LeaderboardEntry(
                rank=idx,
                trader_id=trader['trader_id'],
                username=trader['username'],
                win_rate=trader.get('win_rate', 0),
                total_pnl=trader.get('total_pnl', 0),
                sharpe_ratio=trader.get('sharpe_ratio', 0),
                followers=trader.get('followers', 0),
                trust_score=trader.get('trust_score', 0),
                verified=trader.get('verified', False)
            )
            entries.append(entry)
        
        self.leaderboard = entries
        logger.info(f"Leaderboard updated with {len(entries)} traders")
        return entries
    
    def get_top_traders(self, limit: int = 10) -> List[LeaderboardEntry]:
        """Get top N traders"""
        return self.leaderboard[:limit]
    
    def get_trader_rank(self, trader_id: str) -> Optional[LeaderboardEntry]:
        """Get single trader's rank"""
        for entry in self.leaderboard:
            if entry.trader_id == trader_id:
                return entry
        return None
    
    def snapshot_leaderboard(self) -> datetime:
        """Save leaderboard snapshot"""
        timestamp = datetime.now()
        self.historical_snapshots[timestamp] = list(self.leaderboard)
        logger.info(f"Leaderboard snapshot saved at {timestamp}")
        return timestamp