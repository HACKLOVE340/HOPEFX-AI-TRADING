"""
Advanced Copy Trading & Social Trading Engine
- Multi-account signal mirroring
- Risk adjustment per follower
- Trade correlation analysis
- Performance tracking
- Subscription management
- Advanced account synchronization
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import uuid
import asyncio
from collections import defaultdict

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class FollowStatus(Enum):
    """Follower account status"""
    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    PENDING_APPROVAL = "pending_approval"

class TradeAllocationStrategy(Enum):
    """Strategy for allocating trades to followers"""
    PROPORTIONAL = "proportional"      # Scale by account size
    FIXED_LOTS = "fixed_lots"          # Same lot size
    PERCENTAGE = "percentage"           # Percentage of follower balance
    RISK_BASED = "risk_based"           # Based on follower risk tolerance
    KELLY_CRITERION = "kelly_criterion" # Kelly formula sizing

class CopyTradeStatus(Enum):
    """Status of a copied trade"""
    PENDING = "pending"
    PLACED = "placed"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    FAILED = "failed"

@dataclass
class CopyTraderProfile:
    """Profile of a signal provider (expert trader)"""
    trader_id: str
    username: str
    email: str
    account_balance: float
    win_rate: float
    monthly_return: float
    total_trades: int
    verified: bool = False
    followers_count: int = 0
    subscription_price: float = 0.0
    bio: str = ""
    strategy_description: str = ""
    max_followers: int = 100
    total_payout: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def calculate_trust_score(self) -> float:
        """Calculate trader trust score (0-100)"""
        score = 0.0
        
        # Win rate (40%)
        score += min(self.win_rate * 100, 40)
        
        # Monthly return (30%)
        score += min(max(self.monthly_return * 100, 0), 30)
        
        # Trade history (20%)
        trade_score = min(self.total_trades / 1000 * 20, 20)
        score += trade_score
        
        # Verification bonus (10%)
        if self.verified:
            score += 10
        
        return min(100, max(0, score))

@dataclass
class FollowerConfig:
    """Configuration for follower's copy settings"""
    follower_id: str
    trader_id: str  # Followed trader
    allocation_strategy: TradeAllocationStrategy
    account_balance: float
    risk_per_trade: float = 0.02
    max_concurrent_trades: int = 10
    min_trade_duration_minutes: int = 1
    max_trade_duration_hours: int = 24
    auto_close_on_profit_target: bool = True
    auto_close_on_stop_loss: bool = True
    skip_correlation_above: float = 0.8
    min_win_rate_required: float = 0.40
    enabled: bool = True
    pause_on_drawdown_percentage: float = 10.0
    status: FollowStatus = FollowStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)
    subscription_expires: Optional[datetime] = None

@dataclass
class SignalMessage:
    """Trading signal from copy provider"""
    signal_id: str
    trader_id: str
    symbol: str
    side: str  # BUY/SELL
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    lot_size: float
    reason: str
    strength: float = 0.5  # 0-1
    timestamp: datetime = field(default_factory=datetime.utcnow)
    expiration_minutes: int = 60
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'signal_id': self.signal_id,
            'trader_id': self.trader_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'risk_amount': self.risk_amount,
            'lot_size': self.lot_size,
            'reason': self.reason,
            'strength': self.strength,
            'timestamp': self.timestamp.isoformat()
        }

@dataclass
class CopyTradeRecord:
    """Record of a copied trade"""
    copy_trade_id: str
    signal_id: str
    follower_id: str
    trader_id: str
    symbol: str
    side: str
    entry_price: float
    entry_quantity: float
    stop_loss: float
    take_profit: float
    status: CopyTradeStatus
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_percentage: float = 0.0
    filled_quantity: float = 0.0

class AdvancedCopyTradingEngine:
    """Enterprise-grade copy trading system"""
    
    def __init__(self, 
                 db_session=None,
                 risk_manager=None,
                 broker=None,
                 notification_service=None):
        """
        Initialize copy trading engine
        
        Args:
            db_session: Database session
            risk_manager: Risk management system
            broker: Broker connection
            notification_service: Push notification service
        """
        self.db_session = db_session
        self.risk_manager = risk_manager
        self.broker = broker
        self.notification_service = notification_service
        
        # In-memory tracking
        self.active_signals: Dict[str, SignalMessage] = {}
        self.copy_trades: Dict[str, CopyTradeRecord] = {}
        self.trade_correlations: Dict[str, List[str]] = defaultdict(list)
        self.follower_performances: Dict[str, Dict[str, Any]] = {}
    
    async def register_trader(self,
                             username: str,
                             email: str,
                             initial_balance: float,
                             subscription_price: float = 0.0) -> CopyTraderProfile:
        """Register new signal provider"""
        
        trader = CopyTraderProfile(
            trader_id=str(uuid.uuid4()),
            username=username,
            email=email,
            account_balance=initial_balance,
            win_rate=0.0,
            monthly_return=0.0,
            total_trades=0,
            subscription_price=subscription_price
        )
        
        logger.info(f"Registered trader: {username} (ID: {trader.trader_id})")
        return trader
    
    async def subscribe_to_trader(self,
                                 follower_id: str,
                                 trader_id: str,
                                 account_balance: float,
                                 allocation_strategy: TradeAllocationStrategy = TradeAllocationStrategy.PROPORTIONAL,
                                 risk_per_trade: float = 0.02,
                                 subscription_days: int = 30) -> FollowerConfig:
        """Subscribe follower to trader's signals"""
        
        config = FollowerConfig(
            follower_id=follower_id,
            trader_id=trader_id,
            allocation_strategy=allocation_strategy,
            account_balance=account_balance,
            risk_per_trade=risk_per_trade,
            subscription_expires=datetime.utcnow() + timedelta(days=subscription_days)
        )
        
        logger.info(f"Follower {follower_id} subscribed to {trader_id} for {subscription_days} days")
        return config
    
    async def broadcast_signal(self,
                              signal: SignalMessage,
                              followers: List[FollowerConfig]) -> Dict[str, Dict[str, Any]]:
        """
        Broadcast trading signal to all followers
        
        Args:
            signal: Trading signal
            followers: List of follower configurations
            
        Returns:
            Results for each follower
        """
        results = {}
        
        # Store signal
        self.active_signals[signal.signal_id] = signal
        
        for follower in followers:
            # Check subscription validity
            if not self._is_subscription_valid(follower):
                results[follower.follower_id] = {
                    'status': 'skipped',
                    'reason': 'subscription_expired'
                }
                continue
            
            if follower.status != FollowStatus.ACTIVE:
                results[follower.follower_id] = {
                    'status': 'skipped',
                    'reason': f'account_{follower.status.value}'
                }
                continue
            
            try:
                # Check trader's win rate
                if not self._check_trader_quality(signal.trader_id, follower.min_win_rate_required):
                    results[follower.follower_id] = {
                        'status': 'skipped',
                        'reason': 'trader_quality_below_threshold'
                    }
                    continue
                
                # Check trade correlation
                if self._check_trade_correlation(signal, follower):
                    results[follower.follower_id] = {
                        'status': 'skipped',
                        'reason': 'correlated_exposure'
                    }
                    continue
                
                # Calculate lot size
                lot_size = self._calculate_lot_size(signal, follower)
                
                # Adjust signal for follower
                adjusted_signal = self._adjust_signal_for_follower(signal, follower, lot_size)
                
                # Place order
                if self.broker:
                    order_result = await self.broker.place_order(
                        user_id=follower.follower_id,
                        symbol=adjusted_signal.symbol,
                        side=adjusted_signal.side,
                        order_type="MARKET",
                        quantity=lot_size,
                        entry_price=adjusted_signal.entry_price,
                        stop_loss=adjusted_signal.stop_loss,
                        take_profit=adjusted_signal.take_profit
                    )
                    
                    # Record copy trade
                    copy_trade = CopyTradeRecord(
                        copy_trade_id=str(uuid.uuid4()),
                        signal_id=signal.signal_id,
                        follower_id=follower.follower_id,
                        trader_id=signal.trader_id,
                        symbol=signal.symbol,
                        side=signal.side,
                        entry_price=adjusted_signal.entry_price,
                        entry_quantity=lot_size,
                        stop_loss=adjusted_signal.stop_loss,
                        take_profit=adjusted_signal.take_profit,
                        status=CopyTradeStatus.PLACED,
                        entry_time=datetime.utcnow()
                    )
                    
                    self.copy_trades[copy_trade.copy_trade_id] = copy_trade
                    
                    results[follower.follower_id] = {
                        'status': 'success',
                        'copy_trade_id': copy_trade.copy_trade_id,
                        'order_id': order_result.get('order_id'),
                        'lot_size': lot_size,
                        'risk_amount': adjusted_signal.risk_amount
                    }
                    
                    # Send notification
                    if self.notification_service:
                        await self.notification_service.send(
                            user_id=follower.follower_id,
                            title=f"Copy Trade Executed",
                            body=f"{signal.side} {lot_size} {signal.symbol} @ {adjusted_signal.entry_price}"
                        )
                else:
                    results[follower.follower_id] = {
                        'status': 'pending',
                        'reason': 'broker_offline'
                    }
            
            except Exception as e:
                logger.error(f"Failed to process signal for {follower.follower_id}: {e}")
                results[follower.follower_id] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        return results
    
    def _is_subscription_valid(self, follower: FollowerConfig) -> bool:
        """Check if subscription is still valid"""
        if follower.subscription_expires is None:
            return True
        
        return datetime.utcnow() < follower.subscription_expires
    
    def _check_trader_quality(self, trader_id: str, min_win_rate: float) -> bool:
        """Check if trader meets quality threshold"""
        # In production, fetch from database
        # For now, return True
        return True
    
    def _calculate_lot_size(self,
                           signal: SignalMessage,
                           follower: FollowerConfig) -> float:
        """Calculate appropriate lot size for follower"""
        
        if follower.allocation_strategy == TradeAllocationStrategy.PROPORTIONAL:
            # Scale by account size ratio
            ratio = follower.account_balance / signal.lot_size
            return signal.lot_size * ratio
        
        elif follower.allocation_strategy == TradeAllocationStrategy.FIXED_LOTS:
            return signal.lot_size
        
        elif follower.allocation_strategy == TradeAllocationStrategy.PERCENTAGE:
            # Risk fixed percentage of follower account
            max_risk = follower.account_balance * follower.risk_per_trade
            price_diff = abs(signal.entry_price - signal.stop_loss)
            return max_risk / price_diff if price_diff > 0 else 0.1
        
        elif follower.allocation_strategy == TradeAllocationStrategy.RISK_BASED:
            # Calculate based on risk tolerance
            max_risk = follower.account_balance * follower.risk_per_trade
            price_diff = abs(signal.entry_price - signal.stop_loss)
            
            if price_diff == 0:
                return 0.1
            
            lot_size = max_risk / price_diff
            
            # Cap at max concurrent trades
            max_concurrent_risk = follower.account_balance * 0.05
            return min(lot_size, max_concurrent_risk / price_diff)
        
        elif follower.allocation_strategy == TradeAllocationStrategy.KELLY_CRITERION:
            # Kelly formula: f = (bp - q) / b
            # where b = odds, p = win probability, q = loss probability
            
            # Estimate from trader stats (simplified)
            win_prob = 0.55  # Average ~55% win rate
            loss_prob = 0.45
            odds = 1.0
            
            kelly_fraction = (odds * win_prob - loss_prob) / odds
            kelly_fraction = max(0, min(kelly_fraction, 0.25))  # Cap at 25%
            
            max_risk = follower.account_balance * kelly_fraction
            price_diff = abs(signal.entry_price - signal.stop_loss)
            
            return max_risk / price_diff if price_diff > 0 else 0.1
        
        else:
            return signal.lot_size
    
    def _adjust_signal_for_follower(self,
                                   signal: SignalMessage,
                                   follower: FollowerConfig,
                                   lot_size: float) -> SignalMessage:
        """Adjust signal parameters for specific follower"""
        
        adjusted = SignalMessage(
            signal_id=signal.signal_id,
            trader_id=signal.trader_id,
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            risk_amount=abs(signal.entry_price - signal.stop_loss) * lot_size,
            lot_size=lot_size,
            reason=signal.reason,
            strength=signal.strength
        )
        
        return adjusted
    
    def _check_trade_correlation(self,
                                signal: SignalMessage,
                                follower: FollowerConfig) -> bool:
        """Check if follower already has correlated trades"""
        
        if follower.follower_id in self.trade_correlations:
            existing_symbols = self.trade_correlations[follower.follower_id]
            
            # Simple check: if same symbol already traded, skip
            if signal.symbol in existing_symbols:
                return True
            
            # Check for highly correlated pairs
            correlated_pairs = {
                'EUR/USD': ['GBP/USD', 'EUR/GBP'],
                'GBP/USD': ['EUR/USD', 'EUR/GBP'],
                'USD/JPY': ['EUR/JPY', 'GBP/JPY'],
            }
            
            if signal.symbol in correlated_pairs:
                for corr_symbol in correlated_pairs[signal.symbol]:
                    if corr_symbol in existing_symbols:
                        return True
        
        return False
    
    async def close_copy_trade(self,
                              copy_trade_id: str,
                              exit_price: float) -> bool:
        """Close copied trade"""
        
        if copy_trade_id not in self.copy_trades:
            logger.warning(f"Copy trade {copy_trade_id} not found")
            return False
        
        trade = self.copy_trades[copy_trade_id]
        trade.status = CopyTradeStatus.CLOSED
        trade.exit_time = datetime.utcnow()
        trade.exit_price = exit_price
        
        # Calculate P&L
        if trade.side == "BUY":
            trade.pnl = (exit_price - trade.entry_price) * trade.entry_quantity
        else:
            trade.pnl = (trade.entry_price - exit_price) * trade.entry_quantity
        
        trade.pnl_percentage = (trade.pnl / (trade.entry_price * trade.entry_quantity)) * 100
        
        logger.info(f"Closed copy trade {copy_trade_id}: P&L = {trade.pnl:.2f}")
        
        return True
    
    async def get_follower_performance(self,
                                      follower_id: str,
                                      days: int = 30) -> Dict[str, Any]:
        """Get performance metrics for follower"""
        
        # Filter copy trades by follower and date
        follower_trades = [
            t for t in self.copy_trades.values()
            if t.follower_id == follower_id and
            (datetime.utcnow() - t.entry_time).days <= days
        ]
        
        if not follower_trades:
            return {
                'follower_id': follower_id,
                'period_days': days,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_profit': 0.0,
                'avg_trade_duration': timedelta(),
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'profit_factor': 0.0
            }
        
        closed_trades = [t for t in follower_trades if t.status == CopyTradeStatus.CLOSED]
        
        if not closed_trades:
            return {
                'follower_id': follower_id,
                'period_days': days,
                'total_trades': len(follower_trades),
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_profit': 0.0,
                'avg_trade_duration': timedelta(),
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'profit_factor': 0.0
            }
        
        winning_trades = [t for t in closed_trades if t.pnl > 0]
        losing_trades = [t for t in closed_trades if t.pnl <= 0]
        
        total_profit = sum(t.pnl for t in closed_trades)
        total_loss = abs(sum(t.pnl for t in losing_trades))
        
        durations = [
            (t.exit_time - t.entry_time).total_seconds()
            for t in closed_trades
            if t.exit_time
        ]
        
        avg_duration = timedelta(seconds=np.mean(durations)) if durations else timedelta()
        
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        return {
            'follower_id': follower_id,
            'period_days': days,
            'total_trades': len(closed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(closed_trades) if closed_trades else 0,
            'total_profit': total_profit,
            'avg_trade_duration': avg_duration,
            'best_trade': max((t.pnl for t in closed_trades), default=0),
            'worst_trade': min((t.pnl for t in closed_trades), default=0),
            'profit_factor': profit_factor
        }
    
    async def calculate_payout(self,
                              trader_id: str,
                              subscription_revenue: float,
                              profit_share_percentage: float = 0.2) -> Tuple[float, float]:
        """
        Calculate trader payout
        
        Returns:
            (subscription_payout, profit_share_payout)
        """
        subscription_payout = subscription_revenue * (1 - profit_share_percentage)
        profit_share_payout = subscription_revenue * profit_share_percentage
        
        return subscription_payout, profit_share_payout
    
    async def get_top_traders(self, limit: int = 10) -> List[CopyTraderProfile]:
        """Get top-performing traders by trust score"""
        # In production, fetch from database
        return []
    
    async def pause_follower(self, follower_id: str, reason: str = ""):
        """Pause follower account"""
        # Find and update follower
        logger.info(f"Paused follower {follower_id}: {reason}")
    
    async def resume_follower(self, follower_id: str):
        """Resume paused follower account"""
        logger.info(f"Resumed follower {follower_id}")