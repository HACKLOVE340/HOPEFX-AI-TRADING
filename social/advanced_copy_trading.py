"""
Advanced Copy Trading Engine
- Multi-account signal mirroring
- Risk adjustment per follower
- Trade correlation analysis
- Performance tracking
- Commission splitting
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import uuid
import json
from enum import Enum

class TradeStatus(Enum):
    """Trade status enumeration"""
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    FAILED = "failed"

@dataclass
class TraderProfile:
    """Signal provider profile"""
    trader_id: str
    username: str
    email: str
    account_balance: float
    win_rate: float
    total_trades: int
    avg_win: float
    avg_loss: float
    sharpe_ratio: float
    verified: bool = False
    verification_date: Optional[datetime] = None
    followers_count: int = 0
    commission_rate: float = 0.2  # 20% commission on profits
    
    def calculate_trust_score(self) -> float:
        """Calculate trader trust score (0-100)"""
        score = 0.0
        
        # Win rate component (40%)
        score += min(self.win_rate * 100, 40)
        
        # Trade history component (20%)
        score += min((self.total_trades / 1000) * 20, 20)
        
        # Sharpe ratio component (20%)
        score += min(max(self.sharpe_ratio / 3, 0) * 20, 20)
        
        # Verification bonus (10%)
        if self.verified:
            score += 10
        
        # Followers trust (10%)
        score += min((self.followers_count / 1000) * 10, 10)
        
        return min(100, score)

@dataclass
class FollowerConfig:
    """Follower configuration"""
    follower_id: str
    trader_id: str
    account_balance: float
    risk_per_trade: float = 0.02  # 2% risk per trade
    max_concurrent_trades: int = 10
    max_account_drawdown: float = 0.20  # 20% max drawdown
    enabled: bool = True
    copy_ratio: float = 1.0  # 1.0 = copy exactly, 0.5 = copy half size
    created_at: datetime = field(default_factory=datetime.now)

@dataclass
class SignalMessage:
    """Trading signal from provider"""
    signal_id: str
    trader_id: str
    symbol: str
    side: str  # BUY/SELL
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    confidence: float  # 0-1
    timestamp: datetime
    expiration_time: Optional[datetime] = None
    notes: str = ""

@dataclass
class ExecutedTrade:
    """Record of executed trade"""
    trade_id: str
    signal_id: str
    trader_id: str
    follower_id: str
    symbol: str
    side: str
    entry_price: float
    entry_quantity: float
    stop_loss: float
    take_profit: float
    status: TradeStatus
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_percent: float = 0.0
    commission: float = 0.0

class CopyTradingEngine:
    """Enterprise copy trading system"""
    
    def __init__(self):
        self.traders: Dict[str, TraderProfile] = {}
        self.followers: Dict[str, FollowerConfig] = {}
        self.active_trades: Dict[str, List[ExecutedTrade]] = {}
        self.trade_history: List[ExecutedTrade] = []
        self.signals_queue: List[SignalMessage] = []
    
    def register_trader(self, 
                       username: str, 
                       email: str, 
                       initial_balance: float,
                       commission_rate: float = 0.2) -> TraderProfile:
        """Register new signal provider"""
        trader = TraderProfile(
            trader_id=str(uuid.uuid4()),
            username=username,
            email=email,
            account_balance=initial_balance,
            win_rate=0.0,
            total_trades=0,
            avg_win=0.0,
            avg_loss=0.0,
            sharpe_ratio=0.0,
            commission_rate=commission_rate
        )
        self.traders[trader.trader_id] = trader
        return trader
    
    def verify_trader(self, trader_id: str) -> bool:
        """Verify trader identity"""
        if trader_id in self.traders:
            self.traders[trader_id].verified = True
            self.traders[trader_id].verification_date = datetime.now()
            return True
        return False
    
    def subscribe_follower(self, 
                          follower_id: str, 
                          trader_id: str, 
                          account_balance: float,
                          risk_per_trade: float = 0.02,
                          copy_ratio: float = 1.0) -> FollowerConfig:
        """Subscribe follower to trader"""
        if trader_id not in self.traders:
            raise ValueError(f"Trader {trader_id} not found")
        
        config = FollowerConfig(
            follower_id=follower_id,
            trader_id=trader_id,
            account_balance=account_balance,
            risk_per_trade=risk_per_trade,
            copy_ratio=copy_ratio
        )
        
        self.followers[follower_id] = config
        self.traders[trader_id].followers_count += 1
        self.active_trades[follower_id] = []
        
        return config
    
    def publish_signal(self, signal: SignalMessage) -> bool:
        """Publish trading signal"""
        if signal.trader_id not in self.traders:
            return False
        
        self.signals_queue.append(signal)
        self._broadcast_signal(signal)
        return True
    
    def _broadcast_signal(self, signal: SignalMessage) -> Dict[str, Dict]:
        """Broadcast signal to all followers"""
        results = {}
        
        followers_of_trader = [
            f for f in self.followers.values() 
            if f.trader_id == signal.trader_id and f.enabled
        ]
        
        for follower in followers_of_trader:
            try:
                # Check follower constraints
                if not self._can_accept_trade(follower, signal):
                    results[follower.follower_id] = {
                        'status': 'skipped',
                        'reason': 'follower constraints violated'
                    }
                    continue
                
                # Calculate lot size based on follower's account
                lot_size = self._calculate_lot_size(signal, follower)
                
                # Execute trade
                trade = ExecutedTrade(
                    trade_id=str(uuid.uuid4()),
                    signal_id=signal.signal_id,
                    trader_id=signal.trader_id,
                    follower_id=follower.follower_id,
                    symbol=signal.symbol,
                    side=signal.side,
                    entry_price=signal.entry_price,
                    entry_quantity=lot_size,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    status=TradeStatus.OPEN,
                    entry_time=datetime.now()
                )
                
                self.active_trades[follower.follower_id].append(trade)
                
                results[follower.follower_id] = {
                    'status': 'success',
                    'trade_id': trade.trade_id,
                    'lot_size': lot_size,
                    'symbol': signal.symbol,
                    'side': signal.side
                }
            
            except Exception as e:
                results[follower.follower_id] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        return results
    
    def _can_accept_trade(self, follower: FollowerConfig, signal: SignalMessage) -> bool:
        """Check if follower can accept trade"""
        # Check concurrent trades limit
        open_trades = len([
            t for t in self.active_trades.get(follower.follower_id, [])
            if t.status == TradeStatus.OPEN
        ])
        
        if open_trades >= follower.max_concurrent_trades:
            return False
        
        # Check max drawdown
        current_drawdown = self._calculate_current_drawdown(follower.follower_id)
        if current_drawdown >= follower.max_account_drawdown:
            return False
        
        return True
    
    def _calculate_lot_size(self, signal: SignalMessage, follower: FollowerConfig) -> float:
        """Calculate appropriate lot size for follower"""
        max_risk = follower.account_balance * follower.risk_per_trade
        price_diff = abs(signal.entry_price - signal.stop_loss)
        
        if price_diff == 0:
            return 0.1 * follower.copy_ratio
        
        base_lot_size = max_risk / price_diff
        return base_lot_size * follower.copy_ratio
    
    def close_trade(self, 
                   follower_id: str, 
                   trade_id: str, 
                   exit_price: float) -> Optional[ExecutedTrade]:
        """Close an active trade"""
        if follower_id not in self.active_trades:
            return None
        
        for trade in self.active_trades[follower_id]:
            if trade.trade_id == trade_id and trade.status == TradeStatus.OPEN:
                # Calculate PnL
                pnl = trade.entry_quantity * (exit_price - trade.entry_price)
                pnl_percent = (exit_price - trade.entry_price) / trade.entry_price
                
                # Calculate commission
                commission = abs(pnl) * 0.001  # 0.1% commission
                
                # Update trade
                trade.exit_price = exit_price
                trade.pnl = pnl - commission
                trade.pnl_percent = pnl_percent
                trade.commission = commission
                trade.status = TradeStatus.CLOSED
                trade.exit_time = datetime.now()
                
                # Move to history
                self.trade_history.append(trade)
                self.active_trades[follower_id].remove(trade)
                
                # Update follower account
                self.followers[follower_id].account_balance += trade.pnl
                
                return trade
        
        return None
    
    def _calculate_current_drawdown(self, follower_id: str) -> float:
        """Calculate current drawdown for follower"""
        if follower_id not in self.followers:
            return 0.0
        
        follower = self.followers[follower_id]
        closed_trades = [t for t in self.trade_history if t.follower_id == follower_id]
        
        if not closed_trades:
            return 0.0
        
        cumulative_pnl = sum(t.pnl for t in closed_trades)
        current_equity = follower.account_balance
        peak_equity = follower.account_balance - cumulative_pnl
        
        if peak_equity <= 0:
            return 0.0
        
        return max(0, (peak_equity - current_equity) / peak_equity)
    
    def get_trader_performance(self, trader_id: str) -> Dict:
        """Get trader performance metrics"""
        trader = self.traders.get(trader_id)
        
        if not trader:
            return {}
        
        # Get trader's followers' trades
        followers = [f for f in self.followers.values() if f.trader_id == trader_id]
        all_trades = [t for t in self.trade_history 
                     if t.trader_id == trader_id]
        
        winning_trades = [t for t in all_trades if t.pnl > 0]
        losing_trades = [t for t in all_trades if t.pnl < 0]
        
        return {
            'trader_id': trader_id,
            'username': trader.username,
            'trust_score': trader.calculate_trust_score(),
            'verified': trader.verified,
            'followers': len(followers),
            'total_trades': len(all_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(all_trades) if all_trades else 0,
            'total_pnl': sum(t.pnl for t in all_trades),
            'avg_win': sum(t.pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0,
            'avg_loss': sum(t.pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0,
        }
    
    def get_follower_performance(self, follower_id: str) -> Dict:
        """Get follower performance metrics"""
        follower = self.followers.get(follower_id)
        
        if not follower:
            return {}
        
        trades = [t for t in self.trade_history if t.follower_id == follower_id]
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
        
        return {
            'follower_id': follower_id,
            'account_balance': follower.account_balance,
            'initial_balance': follower.account_balance - sum(t.pnl for t in trades),
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(trades) if trades else 0,
            'total_pnl': sum(t.pnl for t in trades),
            'roi': (sum(t.pnl for t in trades) / (follower.account_balance - sum(t.pnl for t in trades)) * 100) if trades else 0,
        }