"""
Advanced Copy Trading & Social Trading Engine
- Multi-account signal mirroring
- Risk adjustment per follower
- Trade correlation analysis
- Performance tracking
- Subscription management
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import uuid
import hashlib

import pandas as pd
import numpy as np
from sqlalchemy import Column, String, Float, Boolean, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base

logger = logging.getLogger(__name__)
Base = declarative_base()

class FollowStatus(Enum):
    """Follower account status"""
    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    EXPIRED = "expired"

class TradeAllocationStrategy(Enum):
    """Strategy for allocating trades to followers"""
    PROPORTIONAL = "proportional"  # Scale by account size
    FIXED_LOTS = "fixed_lots"       # Same lot size
    PERCENTAGE = "percentage"        # Percentage of follower balance
    RISK_BASED = "risk_based"        # Based on follower risk tolerance

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
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def calculate_trust_score(self) -> float:
        """Calculate trader trust score (0-100)"""
        score = 0.0
        
        # Win rate (40%)
        score += min(self.win_rate * 100, 40)
        
        # Monthly return (30%)
        score += min(self.monthly_return * 10, 30)
        
        # Trade history (20%)
        trade_score = min(self.total_trades / 1000 * 20, 20)
        score += trade_score
        
        # Verification bonus (10%)
        if self.verified:
            score += 10
        
        return min(100, score)

@dataclass
class FollowerConfig:
    """Configuration for follower's copy settings"""
    follower_id: str
    trader_id: str  # Followed trader
    allocation_strategy: TradeAllocationStrategy
    account_balance: float
    risk_per_trade: float = 0.02  # 2% risk per trade
    max_concurrent_trades: int = 10
    min_trade_duration_minutes: int = 1
    max_trade_duration_hours: int = 24
    auto_close_on_profit_target: bool = True
    auto_close_on_stop_loss: bool = True
    skip_correlation_above: float = 0.8  # Skip correlated trades
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)

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
    reason: str  # Trading reason/analysis
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
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
            'timestamp': self.timestamp.isoformat()
        }

class AdvancedCopyTradingEngine:
    """Enterprise-grade copy trading system"""
    
    def __init__(self, 
                 db_session=None,
                 risk_manager=None,
                 broker=None):
        """
        Initialize copy trading engine
        
        Args:
            db_session: Database session
            risk_manager: Risk management system
            broker: Broker connection
        """
        self.db_session = db_session
        self.risk_manager = risk_manager
        self.broker = broker
        
        # In-memory tracking
        self.active_signals: Dict[str, SignalMessage] = {}
        self.trade_correlations: Dict[str, List[str]] = {}
    
    def register_trader(self,
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
    
    def subscribe_to_trader(self,
                           follower_id: str,
                           trader_id: str,
                           account_balance: float,
                           allocation_strategy: TradeAllocationStrategy = TradeAllocationStrategy.PROPORTIONAL,
                           risk_per_trade: float = 0.02) -> FollowerConfig:
        """Subscribe follower to trader's signals"""
        
        config = FollowerConfig(
            follower_id=follower_id,
            trader_id=trader_id,
            allocation_strategy=allocation_strategy,
            account_balance=account_balance,
            risk_per_trade=risk_per_trade
        )
        
        logger.info(f"Follower {follower_id} subscribed to {trader_id}")
        return config
    
    def broadcast_signal(self,
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
            if not follower.enabled:
                results[follower.follower_id] = {'status': 'skipped', 'reason': 'disabled'}
                continue
            
            try:
                # Check trade correlation
                if self._check_trade_correlation(signal, follower):
                    results[follower.follower_id] = {
                        'status': 'skipped',
                        'reason': 'correlated_exposure'
                    }
                    continue
                
                # Calculate lot size based on strategy
                lot_size = self._calculate_lot_size(signal, follower)
                
                # Adjust risk
                adjusted_signal = self._adjust_signal_for_follower(signal, follower, lot_size)
                
                # Place order via broker
                if self.broker:
                    order_result = self.broker.place_order(
                        symbol=adjusted_signal.symbol,
                        side=adjusted_signal.side,
                        quantity=lot_size,
                        entry_price=adjusted_signal.entry_price,
                        stop_loss=adjusted_signal.stop_loss,
                        take_profit=adjusted_signal.take_profit
                    )
                    
                    results[follower.follower_id] = {
                        'status': 'success',
                        'order_id': order_result.get('order_id'),
                        'lot_size': lot_size,
                        'risk_amount': adjusted_signal.risk_amount
                    }
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
    
    def _calculate_lot_size(self,
                           signal: SignalMessage,
                           follower: FollowerConfig) -> float:
        """Calculate appropriate lot size for follower"""
        
        if follower.allocation_strategy == TradeAllocationStrategy.PROPORTIONAL:
            # Scale by account size ratio
            ratio = follower.account_balance / signal.lot_size  # Base trader lot
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
            reason=signal.reason
        )
        
        return adjusted
    
    def _check_trade_correlation(self,
                                signal: SignalMessage,
                                follower: FollowerConfig) -> bool:
        """Check if follower already has correlated trades"""
        
        # Calculate correlation with existing positions
        if follower.follower_id in self.trade_correlations:
            existing_symbols = self.trade_correlations[follower.follower_id]
            
            # Simple check: if same symbol already traded, skip
            if signal.symbol in existing_symbols:
                correlation = 1.0
            else:
                # In production, calculate true correlation
                correlation = 0.0
            
            if correlation > follower.skip_correlation_above:
                return True
        
        return False
    
    def close_copy_trade(self,
                        follower_id: str,
                        trader_id: str,
                        signal_id: str) -> bool:
        """Close copied trade"""
        
        if signal_id not in self.active_signals:
            logger.warning(f"Signal {signal_id} not found")
            return False
        
        signal = self.active_signals.pop(signal_id)
        
        logger.info(f"Closed copy trade for follower {follower_id}: {signal.symbol}")
        return True
    
    def get_follower_performance(self,
                                follower_id: str,
                                days: int = 30) -> Dict[str, Any]:
        """Get performance metrics for follower"""
        
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
    
    def calculate_payout(self,
                        trader_id: str,
                        subscription_revenue: float,
                        profit_share_percentage: float = 0.2) -> Tuple[float, float]:
        """
        Calculate trader payout
        
        Returns:
            (subscription_payout, profit_share_payout)
        """
        subscription_payout = subscription_revenue
        profit_share_payout = subscription_revenue * profit_share_percentage
        
        return subscription_payout, profit_share_payout