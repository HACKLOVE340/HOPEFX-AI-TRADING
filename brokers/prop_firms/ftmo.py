"""
FTMO (Forex Trader Mom) Integration
- Real-time account metrics
- Challenge/Verification phases
- Profit distribution & payouts
- Risk limit enforcement
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import json
import hmac
import hashlib
from enum import Enum

import aiohttp
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class FTMOPhase(Enum):
    """FTMO Account Phases"""
    CHALLENGE = "challenge"
    VERIFICATION = "verification"
    FUNDED = "funded"
    PROFIT_SHARING = "profit_sharing"

@dataclass
class FTMOMetrics:
    """FTMO Account Metrics"""
    account_balance: float
    equity: float
    profit_loss: float
    drawdown: float
    daily_loss_limit: float
    remaining_daily_loss: float
    monthly_loss_limit: float
    remaining_monthly_loss: float
    phase: FTMOPhase
    days_remaining: int
    phase_progress: float  # 0-1
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data['phase'] = self.phase.value
        return data

class FTMOBroker:
    """Enterprise-grade FTMO Integration"""
    
    BASE_URL = "https://api.ftmo.com/v1"
    
    def __init__(self, 
                 api_key: str,
                 secret_key: str,
                 account_id: str,
                 sandbox: bool = False):
        """
        Initialize FTMO broker
        
        Args:
            api_key: FTMO API key
            secret_key: FTMO secret key
            account_id: FTMO account ID
            sandbox: Use sandbox environment
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.account_id = account_id
        self.sandbox = sandbox
        
        if sandbox:
            self.BASE_URL = "https://sandbox-api.ftmo.com/v1"
        
        self.session: Optional[aiohttp.ClientSession] = None
        self._request_nonce = 0
        self._rate_limit_remaining = 1000
        self._rate_limit_reset = 0
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    def _generate_signature(self, 
                           method: str,
                           endpoint: str,
                           params: Optional[Dict] = None) -> Dict[str, str]:
        """Generate FTMO API signature"""
        timestamp = str(int(datetime.utcnow().timestamp() * 1000))
        nonce = self._request_nonce
        self._request_nonce += 1
        
        # Build signature string
        sig_string = f"{method.upper()}{endpoint}{timestamp}{nonce}"
        
        if params:
            sig_string += json.dumps(params, sort_keys=True)
        
        # Create HMAC-SHA256 signature
        signature = hmac.new(
            self.secret_key.encode(),
            sig_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return {
            'Authorization': f'FTMO {self.api_key}:{signature}',
            'X-FTMO-TIMESTAMP': timestamp,
            'X-FTMO-NONCE': str(nonce),
            'Content-Type': 'application/json'
        }
    
    async def get_account_metrics(self) -> FTMOMetrics:
        """
        Retrieve real-time account metrics
        
        Returns:
            FTMOMetrics: Account performance data
            
        Raises:
            RuntimeError: If account fetch fails
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        endpoint = f"/accounts/{self.account_id}/metrics"
        headers = self._generate_signature("GET", endpoint)
        
        try:
            async with self.session.get(
                f"{self.BASE_URL}{endpoint}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    error_data = await resp.json()
                    raise RuntimeError(f"FTMO API Error: {error_data}")
                
                data = await resp.json()
                
                # Update rate limit info
                self._rate_limit_remaining = int(
                    resp.headers.get('X-RateLimit-Remaining', self._rate_limit_remaining)
                )
                self._rate_limit_reset = int(
                    resp.headers.get('X-RateLimit-Reset', self._rate_limit_reset)
                )
                
                return FTMOMetrics(
                    account_balance=float(data['accountBalance']),
                    equity=float(data['equity']),
                    profit_loss=float(data['profitLoss']),
                    drawdown=float(data['drawdown']),
                    daily_loss_limit=float(data['dailyLossLimit']),
                    remaining_daily_loss=float(data['remainingDailyLoss']),
                    monthly_loss_limit=float(data['monthlyLossLimit']),
                    remaining_monthly_loss=float(data['remainingMonthlyLoss']),
                    phase=FTMOPhase(data['phase']),
                    days_remaining=int(data['daysRemaining']),
                    phase_progress=float(data['phaseProgress'])
                )
                
        except asyncio.TimeoutError:
            logger.error("FTMO API timeout")
            raise RuntimeError("FTMO API request timed out")
        except Exception as e:
            logger.error(f"Failed to fetch FTMO metrics: {e}")
            raise
    
    async def place_order(self,
                         symbol: str,
                         order_type: str,
                         side: str,
                         quantity: float,
                         price: Optional[float] = None,
                         stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None,
                         comment: str = "") -> Dict[str, Any]:
        """
        Place order with FTMO risk limits applied
        
        Args:
            symbol: Trading pair (EUR/USD)
            order_type: MARKET, LIMIT, STOP
            side: BUY, SELL
            quantity: Lot size
            price: Limit/Stop price
            stop_loss: Stop loss price
            take_profit: Take profit price
            comment: Order comment
            
        Returns:
            Order placement response
        """
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        # Validate against FTMO risk limits
        metrics = await self.get_account_metrics()
        
        if metrics.remaining_daily_loss <= 0:
            raise ValueError("Daily loss limit exceeded")
        
        # Calculate potential loss
        potential_loss = quantity * abs(price - stop_loss) if stop_loss else 0
        
        if potential_loss > metrics.remaining_daily_loss:
            raise ValueError(
                f"Order size would exceed daily loss limit. "
                f"Max allowed loss: {metrics.remaining_daily_loss}"
            )
        
        endpoint = f"/accounts/{self.account_id}/orders"
        payload = {
            "symbol": symbol,
            "orderType": order_type,
            "side": side,
            "quantity": quantity,
            "price": price,
            "stopLoss": stop_loss,
            "takeProfit": take_profit,
            "comment": comment
        }
        
        headers = self._generate_signature("POST", endpoint, payload)
        
        try:
            async with self.session.post(
                f"{self.BASE_URL}{endpoint}",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status not in [200, 201]:
                    error_data = await resp.json()
                    raise RuntimeError(f"Order placement failed: {error_data}")
                
                return await resp.json()
                
        except Exception as e:
            logger.error(f"Failed to place FTMO order: {e}")
            raise
    
    async def get_trade_history(self,
                               limit: int = 100,
                               offset: int = 0) -> pd.DataFrame:
        """Get closed trades history"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/trades/closed"
        params = {"limit": limit, "offset": offset}
        headers = self._generate_signature("GET", endpoint, params)
        
        try:
            async with self.session.get(
                f"{self.BASE_URL}{endpoint}",
                headers=headers,
                params=params
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(await resp.json())
                
                data = await resp.json()
                df = pd.DataFrame(data['trades'])
                df['closeTime'] = pd.to_datetime(df['closeTime'])
                return df
                
        except Exception as e:
            logger.error(f"Failed to fetch trade history: {e}")
            raise
    
    async def check_violation(self) -> Tuple[bool, Optional[str]]:
        """
        Check if account has any rule violations
        
        Returns:
            (is_violated, violation_reason)
        """
        metrics = await self.get_account_metrics()
        
        if metrics.remaining_daily_loss <= 0:
            return True, "Daily loss limit exceeded"
        
        if metrics.remaining_monthly_loss <= 0:
            return True, "Monthly loss limit exceeded"
        
        if metrics.drawdown >= 0.05:  # 5% max drawdown
            return True, "Maximum drawdown exceeded"
        
        return False, None
    
    async def request_payout(self, amount: float) -> Dict[str, Any]:
        """Request profit withdrawal"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        endpoint = f"/accounts/{self.account_id}/payouts"
        payload = {"amount": amount}
        headers = self._generate_signature("POST", endpoint, payload)
        
        try:
            async with self.session.post(
                f"{self.BASE_URL}{endpoint}",
                headers=headers,
                json=payload
            ) as resp:
                if resp.status not in [200, 201]:
                    raise RuntimeError(await resp.json())
                return await resp.json()
        except Exception as e:
            logger.error(f"Payout request failed: {e}")
            raise



# ---------------------------------------------------------------------------
# MT5-based FTMOConnector (used by tests and BrokerFactory)
# ---------------------------------------------------------------------------

from typing import Dict as _Dict, Any as _Any  # noqa: E402

try:
    from brokers.mt5 import MT5Connector as _MT5Connector

    class FTMOConnector(_MT5Connector):
        """FTMO prop firm connector (MT5-based)."""

        FTMO_SERVERS = {
            "demo": ["FTMO-Demo", "FTMO-Demo2"],
            "live": ["FTMO-Live", "FTMO-Live2"],
        }

        def __init__(self, config: _Dict[str, _Any]):
            cfg = dict(config)
            self.challenge_type = cfg.get("challenge_type", "demo")
            if "server" not in cfg:
                servers = self.FTMO_SERVERS.get(self.challenge_type, self.FTMO_SERVERS["demo"])
                cfg["server"] = servers[0]
            super().__init__(cfg)
            logger.info(f"FTMOConnector initialized: {self.challenge_type} / {self.server}")

        def get_ftmo_rules(self) -> _Dict[str, _Any]:
            return {
                "max_daily_loss": "5%",
                "max_total_drawdown": "10%",
                "profit_target": "10%",
                "min_trading_days": 10,
                "profit_split": "70/30",
                "scaling": "up to $2M",
            }

        def check_ftmo_compliance(self) -> _Dict[str, _Any]:
            info = self.get_account_info()
            if info is None:
                return {"compliant": False, "reason": "not connected"}
            daily_loss_pct = (info.balance - info.equity) / info.balance * 100 if info.balance else 0
            compliant = daily_loss_pct < 5.0
            return {
                "compliant": compliant,
                "equity": info.equity,
                "balance": info.balance,
                "daily_loss_pct": daily_loss_pct,
            }

except ImportError:
    # Fallback alias if MT5 not available
    FTMOConnector = FTMOBroker  # type: ignore
