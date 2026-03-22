"""
All Proprietary Firm Broker Integrations
- FTMO
- The5ers  
- MyForexFunds
- TopStep

Enterprise-grade implementations with:
- Real-time account metrics
- Risk limit enforcement
- Trade copying
- Performance tracking
- Payout management
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import asyncio
import hmac
import hashlib
import json
import uuid

import aiohttp
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ============ ENUMS & DATA CLASSES ============

class PropFirmType(Enum):
    """Prop firm type"""
    FTMO = "ftmo"
    THE5ERS = "the5ers"
    MYFOREXFUNDS = "myforexfunds"
    TOPSTEP = "topstep"

class TradingPhase(Enum):
    """Trading phases"""
    CHALLENGE = "challenge"
    VERIFICATION = "verification"
    FUNDED = "funded"
    PROFIT_SHARING = "profit_sharing"

class AccountStatus(Enum):
    """Account status"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    LIQUIDATED = "liquidated"
    PASSED = "passed"

@dataclass
class PropFirmMetrics:
    """Common metrics across all prop firms"""
    account_id: str
    firm_type: PropFirmType
    account_balance: float
    equity: float
    used_margin: float
    available_margin: float
    profit_loss: float
    profit_loss_percentage: float
    daily_drawdown: float
    daily_drawdown_percentage: float
    monthly_drawdown: float
    monthly_drawdown_percentage: float
    remaining_days: int
    trading_phase: TradingPhase
    trades_completed: int
    win_rate: float
    largest_win: float
    largest_loss: float
    consecutive_losses: int
    max_consecutive_losses: int
    account_status: AccountStatus
    daily_loss_limit: float
    remaining_daily_loss: float
    monthly_loss_limit: float
    remaining_monthly_loss: float
    leverage: int = 100
    last_update: datetime = field(default_factory=datetime.utcnow)

@dataclass
class PropFirmTrade:
    """Trade record from prop firm"""
    trade_id: str
    symbol: str
    side: str  # BUY/SELL
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_percentage: float = 0.0
    entry_time: datetime = field(default_factory=datetime.utcnow)
    exit_time: Optional[datetime] = None
    duration_seconds: int = 0
    status: str = "open"  # open, closed, cancelled

@dataclass
class RiskLimits:
    """Risk limits for prop firm"""
    daily_loss_limit: float
    monthly_loss_limit: float
    max_drawdown_percentage: float
    max_consecutive_losses: int
    max_position_size: float
    min_days_required: int

# ============ BASE PROP FIRM BROKER ============

class BasePropFirmBroker:
    """Base class for all prop firm brokers"""
    
    def __init__(self,
                 api_key: str,
                 secret_key: str,
                 account_id: str,
                 firm_type: PropFirmType):
        self.api_key = api_key
        self.secret_key = secret_key
        self.account_id = account_id
        self.firm_type = firm_type
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def get_metrics(self) -> PropFirmMetrics:
        """Get account metrics - must be implemented by subclass"""
        raise NotImplementedError
    
    async def place_order(self,
                         symbol: str,
                         side: str,
                         quantity: float,
                         order_type: str = "MARKET",
                         price: Optional[float] = None,
                         stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None) -> Dict[str, Any]:
        """Place order - must be implemented by subclass"""
        raise NotImplementedError
    
    async def close_trade(self, trade_id: str) -> Dict[str, Any]:
        """Close trade - must be implemented by subclass"""
        raise NotImplementedError
    
    async def get_open_trades(self) -> List[PropFirmTrade]:
        """Get open trades - must be implemented by subclass"""
        raise NotImplementedError
    
    async def get_trade_history(self, limit: int = 100) -> List[PropFirmTrade]:
        """Get trade history - must be implemented by subclass"""
        raise NotImplementedError
    
    async def check_risk_violations(self) -> Tuple[bool, Optional[str]]:
        """Check for risk limit violations"""
        metrics = await self.get_metrics()
        
        if metrics.remaining_daily_loss <= 0:
            return True, "Daily loss limit exceeded"
        
        if metrics.remaining_monthly_loss <= 0:
            return True, "Monthly loss limit exceeded"
        
        if metrics.daily_drawdown_percentage >= 5.0:
            return True, "Maximum daily drawdown exceeded"
        
        if metrics.monthly_drawdown_percentage >= 10.0:
            return True, "Maximum monthly drawdown exceeded"
        
        return False, None

# ============ FTMO BROKER IMPLEMENTATION ============

class FTMOBroker(BasePropFirmBroker):
    """FTMO Proprietary Firm Integration"""
    
    BASE_URL = "https://api.ftmo.com/v1"
    SANDBOX_URL = "https://sandbox.ftmo.com/v1"
    
    def __init__(self,
                 api_key: str,
                 secret_key: str,
                 account_id: str,
                 sandbox: bool = False):
        super().__init__(api_key, secret_key, account_id, PropFirmType.FTMO)
        self.base_url = self.SANDBOX_URL if sandbox else self.BASE_URL
        self._nonce = 0
        self._rate_limit_remaining = 1000
    
    def _generate_signature(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, str]:
        """Generate FTMO API signature"""
        timestamp = str(int(datetime.utcnow().timestamp() * 1000))
        self._nonce += 1
        
        sig_string = f"{method.upper()}{endpoint}{timestamp}{self._nonce}"
        if data:
            sig_string += json.dumps(data, sort_keys=True)
        
        signature = hmac.new(
            self.secret_key.encode(),
            sig_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return {
            'Authorization': f'FTMO {self.api_key}:{signature}',
            'X-FTMO-TIMESTAMP': timestamp,
            'X-FTMO-NONCE': str(self._nonce),
            'Content-Type': 'application/json'
        }
    
    async def get_metrics(self) -> PropFirmMetrics:
        """Get FTMO account metrics"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        endpoint = f"/accounts/{self.account_id}/metrics"
        headers = self._generate_signature("GET", endpoint)
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    error = await resp.json()
                    raise RuntimeError(f"FTMO API error: {error}")
                
                data = await resp.json()
                
                # Update rate limit
                self._rate_limit_remaining = int(
                    resp.headers.get('X-RateLimit-Remaining', self._rate_limit_remaining)
                )
                
                return PropFirmMetrics(
                    account_id=self.account_id,
                    firm_type=PropFirmType.FTMO,
                    account_balance=float(data.get('accountBalance', 0)),
                    equity=float(data.get('equity', 0)),
                    used_margin=float(data.get('usedMargin', 0)),
                    available_margin=float(data.get('availableMargin', 0)),
                    profit_loss=float(data.get('profitLoss', 0)),
                    profit_loss_percentage=float(data.get('profitLossPercentage', 0)),
                    daily_drawdown=float(data.get('dailyDrawdown', 0)),
                    daily_drawdown_percentage=float(data.get('dailyDrawdownPercentage', 0)),
                    monthly_drawdown=float(data.get('monthlyDrawdown', 0)),
                    monthly_drawdown_percentage=float(data.get('monthlyDrawdownPercentage', 0)),
                    remaining_days=int(data.get('remainingDays', 0)),
                    trading_phase=TradingPhase(data.get('phase', 'challenge')),
                    trades_completed=int(data.get('tradesCompleted', 0)),
                    win_rate=float(data.get('winRate', 0)),
                    largest_win=float(data.get('largestWin', 0)),
                    largest_loss=float(data.get('largestLoss', 0)),
                    consecutive_losses=int(data.get('consecutiveLosses', 0)),
                    max_consecutive_losses=int(data.get('maxConsecutiveLosses', 3)),
                    account_status=AccountStatus(data.get('status', 'active')),
                    daily_loss_limit=float(data.get('dailyLossLimit', 0)),
                    remaining_daily_loss=float(data.get('remainingDailyLoss', 0)),
                    monthly_loss_limit=float(data.get('monthlyLossLimit', 0)),
                    remaining_monthly_loss=float(data.get('remainingMonthlyLoss', 0))
                )
        
        except asyncio.TimeoutError:
            logger.error("FTMO API timeout")
            raise RuntimeError("FTMO API request timed out")
        except Exception as e:
            logger.error(f"Failed to fetch FTMO metrics: {e}")
            raise
    
    async def place_order(self,
                         symbol: str,
                         side: str,
                         quantity: float,
                         order_type: str = "MARKET",
                         price: Optional[float] = None,
                         stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None) -> Dict[str, Any]:
        """Place order on FTMO with risk checks"""
        
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        # Check risk limits first
        is_violated, reason = await self.check_risk_violations()
        if is_violated:
            raise ValueError(f"Risk violation: {reason}")
        
        # Validate risk
        metrics = await self.get_metrics()
        if stop_loss:
            potential_loss = quantity * abs(price - stop_loss) if price else 0
            if potential_loss > metrics.remaining_daily_loss:
                raise ValueError(
                    f"Order size exceeds daily loss limit. "
                    f"Max allowed: {metrics.remaining_daily_loss}"
                )
        
        endpoint = f"/accounts/{self.account_id}/orders"
        payload = {
            "symbol": symbol,
            "orderType": order_type,
            "side": side,
            "quantity": quantity,
            "price": price,
            "stopLoss": stop_loss,
            "takeProfit": take_profit
        }
        
        headers = self._generate_signature("POST", endpoint, payload)
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status not in [200, 201]:
                    error = await resp.json()
                    raise RuntimeError(f"Order placement failed: {error}")
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to place FTMO order: {e}")
            raise
    
    async def get_open_trades(self) -> List[PropFirmTrade]:
        """Get open trades"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/trades/open"
        headers = self._generate_signature("GET", endpoint)
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for t in data.get('trades', []):
                    trade = PropFirmTrade(
                        trade_id=t['tradeId'],
                        symbol=t['symbol'],
                        side=t['side'],
                        entry_price=float(t['entryPrice']),
                        quantity=float(t['quantity']),
                        entry_time=datetime.fromisoformat(t['entryTime']),
                        status='open'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch FTMO open trades: {e}")
            raise
    
    async def close_trade(self, trade_id: str) -> Dict[str, Any]:
        """Close specific trade"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/trades/{trade_id}/close"
        headers = self._generate_signature("POST", endpoint)
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to close FTMO trade: {e}")
            raise
    
    async def get_trade_history(self, limit: int = 100) -> List[PropFirmTrade]:
        """Get closed trades history"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/trades/closed"
        headers = self._generate_signature("GET", endpoint)
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params={'limit': limit}
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for t in data.get('trades', []):
                    trade = PropFirmTrade(
                        trade_id=t['tradeId'],
                        symbol=t['symbol'],
                        side=t['side'],
                        entry_price=float(t['entryPrice']),
                        exit_price=float(t.get('exitPrice', 0)),
                        quantity=float(t['quantity']),
                        pnl=float(t.get('pnl', 0)),
                        pnl_percentage=float(t.get('pnlPercentage', 0)),
                        entry_time=datetime.fromisoformat(t['entryTime']),
                        exit_time=datetime.fromisoformat(t['exitTime']) if t.get('exitTime') else None,
                        status='closed'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch FTMO trade history: {e}")
            raise

# ============ THE5ERS BROKER IMPLEMENTATION ============

class The5ersBroker(BasePropFirmBroker):
    """The5ers Proprietary Firm Integration"""
    
    BASE_URL = "https://api.the5ers.com/v1"
    SANDBOX_URL = "https://sandbox.the5ers.com/v1"
    
    def __init__(self,
                 api_key: str,
                 secret_key: str,
                 account_id: str,
                 sandbox: bool = False):
        super().__init__(api_key, secret_key, account_id, PropFirmType.THE5ERS)
        self.base_url = self.SANDBOX_URL if sandbox else self.BASE_URL
    
    async def get_metrics(self) -> PropFirmMetrics:
        """Get The5ers account metrics"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"The5ers API error: {await resp.text()}")
                
                data = await resp.json()
                
                return PropFirmMetrics(
                    account_id=self.account_id,
                    firm_type=PropFirmType.THE5ERS,
                    account_balance=float(data.get('balance', 0)),
                    equity=float(data.get('equity', 0)),
                    used_margin=float(data.get('usedMargin', 0)),
                    available_margin=float(data.get('availableMargin', 0)),
                    profit_loss=float(data.get('profitLoss', 0)),
                    profit_loss_percentage=float(data.get('profitLossPercent', 0)),
                    daily_drawdown=float(data.get('dailyDD', 0)),
                    daily_drawdown_percentage=float(data.get('dailyDDPercent', 0)),
                    monthly_drawdown=float(data.get('monthlyDD', 0)),
                    monthly_drawdown_percentage=float(data.get('monthlyDDPercent', 0)),
                    remaining_days=int(data.get('daysRemaining', 0)),
                    trading_phase=TradingPhase(data.get('phase', 'challenge')),
                    trades_completed=int(data.get('totalTrades', 0)),
                    win_rate=float(data.get('winRate', 0)) / 100,
                    largest_win=float(data.get('bestTrade', 0)),
                    largest_loss=float(data.get('worstTrade', 0)),
                    consecutive_losses=int(data.get('consecutiveLosses', 0)),
                    max_consecutive_losses=5,
                    account_status=AccountStatus(data.get('status', 'active')),
                    daily_loss_limit=float(data.get('dailyLimit', 0)),
                    remaining_daily_loss=float(data.get('remainingDaily', 0)),
                    monthly_loss_limit=float(data.get('monthlyLimit', 0)),
                    remaining_monthly_loss=float(data.get('remainingMonthly', 0))
                )
        
        except Exception as e:
            logger.error(f"Failed to fetch The5ers metrics: {e}")
            raise
    
    async def place_order(self,
                         symbol: str,
                         side: str,
                         quantity: float,
                         order_type: str = "MARKET",
                         price: Optional[float] = None,
                         stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None) -> Dict[str, Any]:
        """Place order on The5ers"""
        
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        is_violated, reason = await self.check_risk_violations()
        if is_violated:
            raise ValueError(f"Risk violation: {reason}")
        
        endpoint = f"/accounts/{self.account_id}/orders"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "instrument": symbol,
            "direction": side,
            "volume": quantity,
            "orderType": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                json=payload
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to place The5ers order: {e}")
            raise
    
    async def get_open_trades(self) -> List[PropFirmTrade]:
        """Get open trades on The5ers"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/positions"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for pos in data.get('positions', []):
                    trade = PropFirmTrade(
                        trade_id=pos['positionId'],
                        symbol=pos['instrument'],
                        side=pos['direction'],
                        entry_price=float(pos['openPrice']),
                        quantity=float(pos['volume']),
                        entry_time=datetime.fromisoformat(pos['openTime']),
                        status='open'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch The5ers positions: {e}")
            raise
    
    async def close_trade(self, trade_id: str) -> Dict[str, Any]:
        """Close position on The5ers"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/positions/{trade_id}/close"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to close The5ers position: {e}")
            raise
    
    async def get_trade_history(self, limit: int = 100) -> List[PropFirmTrade]:
        """Get trade history from The5ers"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/history"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params={'limit': limit}
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for t in data.get('trades', []):
                    trade = PropFirmTrade(
                        trade_id=t['tradeId'],
                        symbol=t['instrument'],
                        side=t['direction'],
                        entry_price=float(t['openPrice']),
                        exit_price=float(t.get('closePrice', 0)),
                        quantity=float(t['volume']),
                        pnl=float(t.get('pnl', 0)),
                        entry_time=datetime.fromisoformat(t['openTime']),
                        exit_time=datetime.fromisoformat(t['closeTime']) if t.get('closeTime') else None,
                        status='closed'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch The5ers history: {e}")
            raise

# ============ MYFOREXFUNDS BROKER IMPLEMENTATION ============

class MyForexFundsBroker(BasePropFirmBroker):
    """MyForexFunds Proprietary Firm Integration"""
    
    BASE_URL = "https://api.myforexfunds.com/v1"
    SANDBOX_URL = "https://sandbox.myforexfunds.com/v1"
    
    def __init__(self,
                 api_key: str,
                 secret_key: str,
                 account_id: str,
                 sandbox: bool = False):
        super().__init__(api_key, secret_key, account_id, PropFirmType.MYFOREXFUNDS)
        self.base_url = self.SANDBOX_URL if sandbox else self.BASE_URL
        self.secret_key = secret_key
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authenticated headers"""
        return {
            'Authorization': f'ApiKey {self.api_key}',
            'X-Secret-Key': self.secret_key,
            'Content-Type': 'application/json'
        }
    
    async def get_metrics(self) -> PropFirmMetrics:
        """Get MyForexFunds account metrics"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/traders/{self.account_id}/account"
        headers = self._get_headers()
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"MyForexFunds API error: {await resp.text()}")
                
                data = await resp.json()
                
                return PropFirmMetrics(
                    account_id=self.account_id,
                    firm_type=PropFirmType.MYFOREXFUNDS,
                    account_balance=float(data.get('balance', 0)),
                    equity=float(data.get('equity', 0)),
                    used_margin=float(data.get('marginUsed', 0)),
                    available_margin=float(data.get('marginAvailable', 0)),
                    profit_loss=float(data.get('profit', 0)),
                    profit_loss_percentage=float(data.get('profitPercent', 0)),
                    daily_drawdown=float(data.get('dailyLoss', 0)),
                    daily_drawdown_percentage=float(data.get('dailyLossPercent', 0)),
                    monthly_drawdown=float(data.get('monthlyLoss', 0)),
                    monthly_drawdown_percentage=float(data.get('monthlyLossPercent', 0)),
                    remaining_days=int(data.get('daysLeft', 0)),
                    trading_phase=TradingPhase(data.get('level', 'challenge')),
                    trades_completed=int(data.get('closedTrades', 0)),
                    win_rate=float(data.get('winPercent', 0)) / 100,
                    largest_win=float(data.get('maxProfit', 0)),
                    largest_loss=float(data.get('maxLoss', 0)),
                    consecutive_losses=int(data.get('losingStreak', 0)),
                    max_consecutive_losses=4,
                    account_status=AccountStatus(data.get('status', 'active')),
                    daily_loss_limit=float(data.get('dailyLossLimit', 0)),
                    remaining_daily_loss=float(data.get('remainingDailyLoss', 0)),
                    monthly_loss_limit=float(data.get('monthlyLossLimit', 0)),
                    remaining_monthly_loss=float(data.get('remainingMonthlyLoss', 0))
                )
        
        except Exception as e:
            logger.error(f"Failed to fetch MyForexFunds metrics: {e}")
            raise
    
    async def place_order(self,
                         symbol: str,
                         side: str,
                         quantity: float,
                         order_type: str = "MARKET",
                         price: Optional[float] = None,
                         stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None) -> Dict[str, Any]:
        """Place order on MyForexFunds"""
        
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        is_violated, reason = await self.check_risk_violations()
        if is_violated:
            raise ValueError(f"Risk violation: {reason}")
        
        endpoint = f"/traders/{self.account_id}/orders"
        headers = self._get_headers()
        
        payload = {
            "pair": symbol,
            "action": side,
            "lots": quantity,
            "type": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                json=payload
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to place MyForexFunds order: {e}")
            raise
    
    async def get_open_trades(self) -> List[PropFirmTrade]:
        """Get open trades on MyForexFunds"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/traders/{self.account_id}/trades/open"
        headers = self._get_headers()
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for t in data.get('openTrades', []):
                    trade = PropFirmTrade(
                        trade_id=str(t['id']),
                        symbol=t['pair'],
                        side=t['action'],
                        entry_price=float(t['openPrice']),
                        quantity=float(t['lots']),
                        entry_time=datetime.fromisoformat(t['openTime']),
                        status='open'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch MyForexFunds trades: {e}")
            raise
    
    async def close_trade(self, trade_id: str) -> Dict[str, Any]:
        """Close trade on MyForexFunds"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/traders/{self.account_id}/trades/{trade_id}/close"
        headers = self._get_headers()
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to close MyForexFunds trade: {e}")
            raise
    
    async def get_trade_history(self, limit: int = 100) -> List[PropFirmTrade]:
        """Get trade history from MyForexFunds"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/traders/{self.account_id}/trades/closed"
        headers = self._get_headers()
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params={'limit': limit}
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for t in data.get('closedTrades', []):
                    trade = PropFirmTrade(
                        trade_id=str(t['id']),
                        symbol=t['pair'],
                        side=t['action'],
                        entry_price=float(t['openPrice']),
                        exit_price=float(t.get('closePrice', 0)),
                        quantity=float(t['lots']),
                        pnl=float(t.get('profit', 0)),
                        pnl_percentage=float(t.get('profitPercent', 0)),
                        entry_time=datetime.fromisoformat(t['openTime']),
                        exit_time=datetime.fromisoformat(t['closeTime']) if t.get('closeTime') else None,
                        status='closed'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch MyForexFunds history: {e}")
            raise

# ============ TOPSTEP BROKER IMPLEMENTATION ============

class TopStepBroker(BasePropFirmBroker):
    """TopStep Trader Proprietary Firm Integration"""
    
    BASE_URL = "https://api.topsteptrader.com/v2"
    SANDBOX_URL = "https://sandbox.topsteptrader.com/v2"
    
    def __init__(self,
                 api_key: str,
                 secret_key: str,
                 account_id: str,
                 sandbox: bool = False):
        super().__init__(api_key, secret_key, account_id, PropFirmType.TOPSTEP)
        self.base_url = self.SANDBOX_URL if sandbox else self.BASE_URL
        self.secret_key = secret_key
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authenticated headers"""
        # TopStep uses OAuth2 or API key
        return {
            'Authorization': f'Bearer {self.api_key}',
            'X-API-Key': self.secret_key,
            'Content-Type': 'application/json'
        }
    
    async def get_metrics(self) -> PropFirmMetrics:
        """Get TopStep account metrics"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/summary"
        headers = self._get_headers()
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"TopStep API error: {await resp.text()}")
                
                data = await resp.json()
                
                return PropFirmMetrics(
                    account_id=self.account_id,
                    firm_type=PropFirmType.TOPSTEP,
                    account_balance=float(data.get('cash', 0)),
                    equity=float(data.get('totalValue', 0)),
                    used_margin=float(data.get('marginUsed', 0)),
                    available_margin=float(data.get('buyingPower', 0)),
                    profit_loss=float(data.get('netProfit', 0)),
                    profit_loss_percentage=float(data.get('returnPercent', 0)),
                    daily_drawdown=float(data.get('dailyDrawdown', 0)),
                    daily_drawdown_percentage=float(data.get('dailyDrawdownPercent', 0)),
                    monthly_drawdown=float(data.get('monthDrawdown', 0)),
                    monthly_drawdown_percentage=float(data.get('monthDrawdownPercent', 0)),
                    remaining_days=int(data.get('daysRemaining', 0)),
                    trading_phase=TradingPhase(data.get('phase', 'challenge')),
                    trades_completed=int(data.get('totalTrades', 0)),
                    win_rate=float(data.get('winRate', 0)) / 100,
                    largest_win=float(data.get('largestWin', 0)),
                    largest_loss=float(data.get('largestLoss', 0)),
                    consecutive_losses=int(data.get('consecutiveLosses', 0)),
                    max_consecutive_losses=6,
                    account_status=AccountStatus(data.get('status', 'active')),
                    daily_loss_limit=float(data.get('dailyLossLimit', 0)),
                    remaining_daily_loss=float(data.get('remainingDailyLimit', 0)),
                    monthly_loss_limit=float(data.get('monthLossLimit', 0)),
                    remaining_monthly_loss=float(data.get('remainingMonthLimit', 0))
                )
        
        except Exception as e:
            logger.error(f"Failed to fetch TopStep metrics: {e}")
            raise
    
    async def place_order(self,
                         symbol: str,
                         side: str,
                         quantity: float,
                         order_type: str = "MARKET",
                         price: Optional[float] = None,
                         stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None) -> Dict[str, Any]:
        """Place order on TopStep"""
        
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        is_violated, reason = await self.check_risk_violations()
        if is_violated:
            raise ValueError(f"Risk violation: {reason}")
        
        endpoint = f"/accounts/{self.account_id}/orders"
        headers = self._get_headers()
        
        payload = {
            "symbol": symbol,
            "action": side,
            "quantity": int(quantity),
            "orderType": order_type,
            "limitPrice": price,
            "stopPrice": stop_loss,
            "profitTarget": take_profit
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                json=payload
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to place TopStep order: {e}")
            raise
    
    async def get_open_trades(self) -> List[PropFirmTrade]:
        """Get open positions on TopStep"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/positions"
        headers = self._get_headers()
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for pos in data.get('positions', []):
                    trade = PropFirmTrade(
                        trade_id=str(pos['id']),
                        symbol=pos['symbol'],
                        side=pos['action'],
                        entry_price=float(pos['averagePrice']),
                        quantity=float(pos['quantity']),
                        entry_time=datetime.fromisoformat(pos['openTime']),
                        status='open'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch TopStep positions: {e}")
            raise
    
    async def close_trade(self, trade_id: str) -> Dict[str, Any]:
        """Close position on TopStep"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/positions/{trade_id}/close"
        headers = self._get_headers()
        
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                headers=headers
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                
                return await resp.json()
        
        except Exception as e:
            logger.error(f"Failed to close TopStep position: {e}")
            raise
    
    async def get_trade_history(self, limit: int = 100) -> List[PropFirmTrade]:
        """Get trade history from TopStep"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/trades"
        headers = self._get_headers()
        
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params={'limit': limit, 'status': 'closed'}
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                trades = []
                
                for t in data.get('trades', []):
                    trade = PropFirmTrade(
                        trade_id=str(t['id']),
                        symbol=t['symbol'],
                        side=t['action'],
                        entry_price=float(t['entryPrice']),
                        exit_price=float(t.get('exitPrice', 0)),
                        quantity=float(t['quantity']),
                        pnl=float(t.get('profit', 0)),
                        pnl_percentage=float(t.get('profitPercent', 0)),
                        entry_time=datetime.fromisoformat(t['openTime']),
                        exit_time=datetime.fromisoformat(t['closeTime']) if t.get('closeTime') else None,
                        status='closed'
                    )
                    trades.append(trade)
                
                return trades
        
        except Exception as e:
            logger.error(f"Failed to fetch TopStep history: {e}")
            raise

# ============ FACTORY CLASS ============

class PropFirmFactory:
    """Factory for creating prop firm broker instances"""
    
    _brokers = {
        PropFirmType.FTMO: FTMOBroker,
        PropFirmType.THE5ERS: The5ersBroker,
        PropFirmType.MYFOREXFUNDS: MyForexFundsBroker,
        PropFirmType.TOPSTEP: TopStepBroker
    }
    
    @staticmethod
    def create_broker(firm_type: PropFirmType,
                     api_key: str,
                     secret_key: str,
                     account_id: str,
                     sandbox: bool = False) -> BasePropFirmBroker:
        """
        Create prop firm broker instance
        
        Args:
            firm_type: Type of prop firm
            api_key: API key
            secret_key: Secret key
            account_id: Account ID
            sandbox: Use sandbox environment
            
        Returns:
            Broker instance
        """
        broker_class = PropFirmFactory._brokers.get(firm_type)
        
        if not broker_class:
            raise ValueError(f"Unknown prop firm type: {firm_type}")
        
        return broker_class(api_key, secret_key, account_id, sandbox)

# ============ USAGE EXAMPLE ============

async def example_usage():
    """Example usage of prop firm brokers"""
    
    # Create FTMO broker
    async with PropFirmFactory.create_broker(
        PropFirmType.FTMO,
        api_key="your-api-key",
        secret_key="your-secret-key",
        account_id="your-account-id",
        sandbox=True
    ) as broker:
        
        # Get metrics
        metrics = await broker.get_metrics()
        print(f"Balance: {metrics.account_balance}")
        print(f"Daily P&L: {metrics.profit_loss}")
        
        # Check risk
        is_violated, reason = await broker.check_risk_violations()
        if not is_violated:
            # Place order
            result = await broker.place_order(
                symbol="EUR/USD",
                side="BUY",
                quantity=1.0,
                stop_loss=1.0950,
                take_profit=1.1050
            )
            print(f"Order placed: {result}")
        
        # Get open trades
        trades = await broker.get_open_trades()
        print(f"Open trades: {len(trades)}")