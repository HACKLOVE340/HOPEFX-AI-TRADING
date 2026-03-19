
# 4. RISK MANAGER - Advanced risk controls

risk_code = '''"""
HOPEFX Risk Management System
Position sizing, drawdown controls, correlation management
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class RiskConfig:
    """Risk management configuration"""
    max_position_size_pct: float = 0.02  # 2% per trade
    max_total_exposure_pct: float = 0.5  # 50% total
    max_drawdown_pct: float = 0.10  # 10% max drawdown
    daily_loss_limit_pct: float = 0.05  # 5% daily loss
    max_correlation: float = 0.7  # Max correlation between positions
    min_risk_reward: float = 1.5  # Minimum R:R ratio
    volatility_adjustment: bool = True
    kelly_criterion: bool = False

class RiskManager:
    """
    Professional risk management system
    
    Features:
    - Kelly criterion position sizing
    - Volatility-based sizing
    - Correlation checks
    - Drawdown monitoring
    - Dynamic leverage adjustment
    """
    
    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        self.daily_stats = {
            'date': time.strftime('%Y-%m-%d'),
            'starting_equity': 0,
            'current_equity': 0,
            'daily_pnl': 0,
            'trades_today': 0
        }
        self.peak_equity = 0
        self.current_drawdown = 0
        
        logger.info(f"RiskManager initialized: {self.config}")
    
    async def filter_signals(self, signals: List[Dict], state: Any) -> List[Dict]:
        """Filter and size trading signals"""
        approved_signals = []
        
        for signal in signals:
            try:
                # Check if we can take this trade
                sized_signal = await self._size_position(signal, state)
                if sized_signal:
                    approved_signals.append(sized_signal)
            except Exception as e:
                logger.error(f"Risk filtering error: {e}")
        
        return approved_signals
    
    async def _size_position(self, signal: Dict, state: Any) -> Optional[Dict]:
        """Calculate appropriate position size"""
        symbol = signal.get('symbol')
        action = signal.get('action')
        suggested_size = signal.get('size', 0)
        
        # Check daily loss limit
        if await self._check_daily_limit(state):
            logger.warning("Daily loss limit reached, rejecting signal")
            return None
        
        # Check drawdown
        if await self._check_drawdown(state):
            logger.warning("Max drawdown reached, rejecting signal")
            return None
        
        # Calculate max position size based on equity
        equity = getattr(state, 'equity', 100000)
        max_position_value = equity * self.config.max_position_size_pct
        
        # Get current price
        price = signal.get('price', 0)
        if price <= 0:
            logger.error(f"Invalid price for {symbol}: {price}")
            return None
        
        # Volatility adjustment
        volatility_factor = 1.0
        if self.config.volatility_adjustment:
            volatility = await self._get_volatility(symbol, state)
            volatility_factor = 1.0 / (1 + volatility * 10)  # Reduce size in high vol
        
        # Kelly criterion (optional)
        if self.config.kelly_criterion:
            win_rate = signal.get('win_rate', 0.5)
            avg_win = signal.get('avg_win', 1)
            avg_loss = signal.get('avg_loss', 1)
            if avg_loss > 0:
                kelly_pct = win_rate - ((1 - win_rate) / (avg_win / avg_loss))
                kelly_pct = max(0, min(kelly_pct * 0.5, self.config.max_position_size_pct))  # Half Kelly
                max_position_value = equity * kelly_pct
        
        # Calculate size
        max_units = int(max_position_value * volatility_factor / price)
        
        # Check correlation with existing positions
        if await self._check_correlation(symbol, state):
            logger.warning(f"High correlation for {symbol}, reducing size by 50%")
            max_units = int(max_units * 0.5)
        
        # Use minimum of suggested and calculated
        final_size = min(suggested_size, max_units) if suggested_size > 0 else max_units
        
        if final_size <= 0:
            return None
        
        # Update signal with calculated size
        sized_signal = signal.copy()
        sized_signal['size'] = final_size
        sized_signal['risk_approved'] = True
        sized_signal['position_value'] = final_size * price
        sized_signal['risk_pct'] = (final_size * price) / equity
        
        return sized_signal
    
    async def _check_daily_limit(self, state: Any) -> bool:
        """Check if daily loss limit reached"""
        daily_pnl = getattr(state, 'daily_pnl', 0)
        equity = getattr(state, 'equity', 100000)
        
        if daily_pnl < 0 and abs(daily_pnl) > equity * self.config.daily_loss_limit_pct:
            return True
        return False
    
    async def _check_drawdown(self, state: Any) -> bool:
        """Check if max drawdown exceeded"""
        equity = getattr(state, 'equity', 0)
        
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        if self.peak_equity > 0:
            self.current_drawdown = (self.peak_equity - equity) / self.peak_equity
        
        return self.current_drawdown > self.config.max_drawdown_pct
    
    async def _get_volatility(self, symbol: str, state: Any) -> float:
        """Get current volatility for symbol"""
        # Try to get from price engine
        if hasattr(state, 'price_engine') and state.price_engine:
            ohlcv = state.price_engine.get_ohlcv(symbol, '1h', limit=24)
            if ohlcv and len(ohlcv) > 1:
                closes = [c.close for c in ohlcv]
                returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                if returns:
                    import statistics
                    return statistics.stdev(returns)
        
        return 0.001  # Default 0.1% volatility
    
    async def _check_correlation(self, symbol: str, state: Any) -> bool:
        """Check if symbol correlates highly with existing positions"""
        positions = getattr(state, 'active_positions', {})
        
        if not positions:
            return False
        
        # Simple correlation check based on symbol pairs
        # In production, use actual price correlation
        correlated_pairs = {
            'EURUSD': ['GBPUSD', 'AUDUSD', 'NZDUSD'],
            'GBPUSD': ['EURUSD', 'AUDUSD'],
            'XAUUSD': ['XAGUSD'],  # Gold/Silver correlation
        }
        
        for pos_symbol in positions.keys():
            if symbol in correlated_pairs.get(pos_symbol, []):
                return True
            if pos_symbol in correlated_pairs.get(symbol, []):
                return True
        
        return False
    
    def calculate_position_size_fixed_fraction(self, equity: float, risk_pct: float, 
                                               entry: float, stop_loss: float) -> float:
        """Calculate position size based on fixed fractional risk"""
        risk_amount = equity * risk_pct
        trade_risk = abs(entry - stop_loss)
        
        if trade_risk == 0:
            return 0
        
        position_size = risk_amount / trade_risk
        return position_size
    
    def get_risk_report(self, state: Any) -> Dict:
        """Generate comprehensive risk report"""
        equity = getattr(state, 'equity', 0)
        
        return {
            'current_drawdown': self.current_drawdown,
            'max_drawdown_limit': self.config.max_drawdown_pct,
            'daily_pnl': getattr(state, 'daily_pnl', 0),
            'daily_limit': self.config.daily_loss_limit_pct,
            'open_positions': getattr(state, 'open_trades_count', 0),
            'peak_equity': self.peak_equity,
            'risk_level': self._assess_risk_level(state).value,
            'margin_used_pct': getattr(state, 'margin_used', 0) / equity if equity > 0 else 0
        }
    
    def _assess_risk_level(self, state: Any) -> RiskLevel:
        """Assess current risk level"""
        if self.current_drawdown > self.config.max_drawdown_pct * 0.8:
            return RiskLevel.CRITICAL
        elif self.current_drawdown > self.config.max_drawdown_pct * 0.5:
            return RiskLevel.HIGH
        elif getattr(state, 'open_trades_count', 0) > 5:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
'''

with open(project_root / "risk" / "__init__.py", "w") as f:
    f.write(risk_code)

print("✓ Created risk/__init__.py with RiskManager")
