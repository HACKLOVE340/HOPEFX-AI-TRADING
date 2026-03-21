""" 
HOPEFX Risk Manager
Comprehensive risk management with position sizing, exposure limits, and drawdown control
"""

import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskConfig:
    """Risk management configuration"""
    max_position_size_pct: float = 0.02  # 2% per position
    max_portfolio_exposure_pct: float = 0.5  # 50% total exposure
    max_drawdown_pct: float = 0.10  # 10% max drawdown
    daily_loss_limit_pct: float = 0.05  # 5% daily loss
    max_leverage: float = 1.0
    min_risk_reward: float = 1.5
    max_correlation: float = 0.7
    volatility_lookback: int = 20
    kelly_fraction: float = 0.5  # Half Kelly for safety


@dataclass
class PositionSizingResult:
    """Position sizing calculation result"""
    recommended_size: float
    max_allowed_size: float
    risk_amount: float
    risk_pct: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
    approved: bool
    reason: str


@dataclass
class RiskAssessment:
    """Overall risk assessment"""
    level: RiskLevel
    can_trade: bool
    daily_pnl: float
    daily_pnl_pct: float
    current_drawdown: float
    margin_used_pct: float
    total_exposure_pct: float
    largest_position_pct: float
    messages: List[str] = field(default_factory=list)


class RiskManager:
    """
    Production risk manager with:
    - Kelly criterion position sizing
    - Dynamic exposure limits
    - Correlation-based risk reduction
    - Drawdown circuit breakers
    - Volatility-adjusted sizing
    """
    
    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        
        # State tracking
        self.peak_equity = 0.0
        self.current_drawdown = 0.0
        self.daily_starting_equity = 0.0
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now().date()
        
        # Position tracking
        self.position_history: List[Dict] = []
        self.trade_history: List[Dict] = []
        self.correlation_matrix: Dict[Tuple[str, str], float] = {}
        
        # Circuit breakers
        self._trading_halted = False
        self._halt_reason: Optional[str] = None
        self._halt_until: Optional[datetime] = None
    
    def update_equity(self, equity: float):
        """Update equity and calculate drawdown"""
        # Check for new day
        today = datetime.now().date()
        if today != self.last_reset_date:
            self.daily_starting_equity = equity
            self.daily_pnl = 0.0
            self.last_reset_date = today
        
        # Update daily P&L
        self.daily_pnl = equity - self.daily_starting_equity
        
        # Update peak and drawdown
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        if self.peak_equity > 0:
            self.current_drawdown = (self.peak_equity - equity) / self.peak_equity
        
        # Check circuit breakers
        self._check_circuit_breakers(equity)
    
    def _check_circuit_breakers(self, equity: float):
        """Check and trigger circuit breakers"""
        # Max drawdown
        if self.current_drawdown > self.config.max_drawdown_pct:
            self._halt_trading(
                f"Max drawdown reached: {self.current_drawdown:.2%} > {self.config.max_drawdown_pct:.2%}",
                duration_hours=24
            )
            return
        
        # Daily loss limit
        if self.daily_starting_equity > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_equity
            if daily_loss_pct > self.config.daily_loss_limit_pct:
                self._halt_trading(
                    f"Daily loss limit reached: {daily_loss_pct:.2%}",
                    duration_hours=1
                )
                return
        
        # Check if halt should be lifted
        if self._trading_halted and self._halt_until:
            if datetime.now() >= self._halt_until:
                self._resume_trading()
    
    def _halt_trading(self, reason: str, duration_hours: float = 1.0):
        """Halt trading"""
        self._trading_halted = True
        self._halt_reason = reason
        self._halt_until = datetime.now() + timedelta(hours=duration_hours)
        
        logger.critical(f"🚫 TRADING HALTED: {reason} (until {self._halt_until})")
    
    def _resume_trading(self):
        """Resume trading"""
        self._trading_halted = False
        self._halt_reason = None
        self._halt_until = None
        
        logger.info("✅ Trading resumed")
    
    def assess_risk(self, account_info: Dict, positions: List[Any]) -> RiskAssessment:
        """
        Comprehensive risk assessment
        """
        messages = []
        
        # Check if trading halted
        if self._trading_halted:
            return RiskAssessment(
                level=RiskLevel.CRITICAL,
                can_trade=False,
                daily_pnl=self.daily_pnl,
                daily_pnl_pct=self.daily_pnl / self.daily_starting_equity if self.daily_starting_equity > 0 else 0,
                current_drawdown=self.current_drawdown,
                margin_used_pct=0.0,
                total_exposure_pct=0.0,
                largest_position_pct=0.0,
                messages=[f"Trading halted: {self._halt_reason}"]
            )
        
        equity = account_info.get('equity', 0)
        margin_used = account_info.get('margin_used', 0)
        
        # Calculate metrics
        margin_used_pct = (margin_used / equity) if equity > 0 else 0
        
        total_exposure = sum(
            p.get('quantity', 0) * p.get('current_price', 0)
            for p in positions
        )
        total_exposure_pct = (total_exposure / equity) if equity > 0 else 0
        
        largest_position = max(
            (p.get('quantity', 0) * p.get('current_price', 0) for p in positions),
            default=0
        )
        largest_position_pct = (largest_position / equity) if equity > 0 else 0
        
        daily_pnl_pct = (self.daily_pnl / self.daily_starting_equity) if self.daily_starting_equity > 0 else 0
        
        # Determine risk level
        risk_level = RiskLevel.LOW
        can_trade = True
        
        if self.current_drawdown > self.config.max_drawdown_pct * 0.8:
            risk_level = RiskLevel.CRITICAL
            can_trade = False
            messages.append(f"Near max drawdown: {self.current_drawdown:.2%}")
        elif margin_used_pct > 0.8:
            risk_level = RiskLevel.HIGH
            messages.append(f"High margin usage: {margin_used_pct:.2%}")
        elif total_exposure_pct > self.config.max_portfolio_exposure_pct * 0.9:
            risk_level = RiskLevel.HIGH
            messages.append(f"High exposure: {total_exposure_pct:.2%}")
        elif largest_position_pct > self.config.max_position_size_pct * 1.5:
            risk_level = RiskLevel.MEDIUM
            messages.append(f"Large position: {largest_position_pct:.2%}")
        elif daily_pnl_pct < -self.config.daily_loss_limit_pct * 0.5:
            risk_level = RiskLevel.MEDIUM
            messages.append(f"Approaching daily loss limit: {daily_pnl_pct:.2%}")
        
        if not messages:
            messages.append("Risk within normal parameters")
        
        return RiskAssessment(
            level=risk_level,
            can_trade=can_trade,
            daily_pnl=self.daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            current_drawdown=self.current_drawdown,
            margin_used_pct=margin_used_pct,
            total_exposure_pct=total_exposure_pct,
            largest_position_pct=largest_position_pct,
            messages=messages
        )
    
    def calculate_position_size(
        self,
        symbol: str,
        signal_strength: float,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        account_equity: float,
        volatility: float,
        existing_positions: List[Dict] = None
    ) -> PositionSizingResult:
        """
        Calculate optimal position size using Kelly criterion with safety factors
        
        Args:
            signal_strength: 0.0 to 1.0
            entry_price: Planned entry price
            stop_loss_price: Stop loss level
            take_profit_price: Take profit level
            account_equity: Current account equity
            volatility: Annualized volatility (0.0 to 1.0)
            existing_positions: Current positions for correlation check
        """
        
        if existing_positions is None:
            existing_positions = []
        
        # Validate inputs
        if entry_price <= 0 or account_equity <= 0:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Invalid price or equity"
            )
        
        # Check if trading halted
        if self._trading_halted:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason=f"Trading halted: {self._halt_reason}"
            )
        
        # Calculate risk/reward
        risk_per_share = abs(entry_price - stop_loss_price)
        reward_per_share = abs(take_profit_price - entry_price)
        
        if risk_per_share <= 0:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Invalid stop loss (must be different from entry)"
            )
        
        risk_reward = reward_per_share / risk_per_share
        
        if risk_reward < self.config.min_risk_reward:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason=f"Risk/reward too low: {risk_reward:.2f} < {self.config.min_risk_reward}"
            )
        
        # Calculate win probability based on signal strength and historical performance
        # Simplified: use signal strength as proxy
        win_probability = 0.5 + (signal_strength * 0.3)  # 0.5 to 0.8
        
        # Kelly criterion: f* = (p*b - q) / b
        # where p = win prob, q = loss prob, b = win/loss ratio
        b = risk_reward
        p = win_probability
        q = 1 - p
        
        kelly_pct = (p * b - q) / b if b > 0 else 0
        
        # Apply Kelly fraction and safety caps
        position_risk_pct = kelly_pct * self.config.kelly_fraction
        
        # Cap at max position size
        position_risk_pct = min(position_risk_pct, self.config.max_position_size_pct)
        
        # Reduce for high volatility
        volatility_factor = max(0.3, 1.0 - (volatility * 2))  # 0.3 to 1.0
        position_risk_pct *= volatility_factor
        
        # Reduce for high drawdown
        drawdown_factor = max(0.5, 1.0 - (self.current_drawdown * 5))  # 0.5 to 1.0
        position_risk_pct *= drawdown_factor
        
        # Check correlation with existing positions
        correlation_penalty = self._calculate_correlation_penalty(symbol, existing_positions)
        position_risk_pct *= (1 - correlation_penalty)
        
        # Calculate position size
        risk_amount = account_equity * position_risk_pct
        position_size = risk_amount / risk_per_share if risk_per_share > 0 else 0
        
        # Round to standard lot sizes (1000 units for forex)
        position_size = int(position_size / 1000) * 1000
        
        # Ensure minimum size
        if position_size < 1000:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Position size too small after rounding"
            )
        
        # Calculate max allowed based on exposure limits
        current_exposure = sum(
            p.get('quantity', 0) * p.get('current_price', 0)
            for p in existing_positions
        )
        max_additional_exposure = (account_equity * self.config.max_portfolio_exposure_pct) - current_exposure
        max_size_from_exposure = max_additional_exposure / entry_price if entry_price > 0 else 0
        
        # Final position size is minimum of risk-based and exposure-based
        final_size = min(position_size, max_size_from_exposure)
        
        # Ensure we don't exceed max position size
        max_position_value = account_equity * self.config.max_position_size_pct
        max_size_from_position_limit = max_position_value / entry_price if entry_price > 0 else 0
        final_size = min(final_size, max_size_from_position_limit)
        
        # Round again
        final_size = int(final_size / 1000) * 1000
        
        if final_size < 1000:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Position size too small after applying limits"
            )
        
        actual_risk_amount = final_size * risk_per_share
        actual_risk_pct = actual_risk_amount / account_equity
        
        return PositionSizingResult(
            recommended_size=final_size,
            max_allowed_size=max_size_from_exposure,
            risk_amount=actual_risk_amount,
            risk_pct=actual_risk_pct,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            approved=True,
            reason=f"Kelly: {kelly_pct:.2%}, Risk/Reward: {risk_reward:.2f}, "
                   f"VolFactor: {volatility_factor:.2f}, DD_Factor: {drawdown_factor:.2f}"
        )
    
    def _calculate_correlation_penalty(self, symbol: str, positions: List[Dict]) -> float:
        """Calculate position size reduction due to correlation"""
        if not positions:
            return 0.0
        
        # Simplified: check if same symbol or related pairs
        correlated_exposure = 0.0
        
        for pos in positions:
            pos_symbol = pos.get('symbol', '')
            
            # Same symbol = full correlation
            if pos_symbol == symbol:
                correlated_exposure += pos.get('quantity', 0) * pos.get('current_price', 0)
                continue
            
            # Check for related pairs (e.g., EURUSD and GBPUSD both have USD)
            if self._symbols_related(symbol, pos_symbol):
                correlated_exposure += pos.get('quantity', 0) * pos.get('current_price', 0) * 0.5
        
        # Penalty increases with correlated exposure
        if correlated_exposure > 0:
            return min(0.5, correlated_exposure / 100000)  # Cap at 50% reduction
        
        return 0.0
    
    def _symbols_related(self, sym1: str, sym2: str) -> bool:
        """Check if two symbols are related (share a currency)"""
        # Extract currencies (simplified)
        currencies1 = set([sym1[:3], sym1[3:]]) if len(sym1) == 6 else set([sym1])
        currencies2 = set([sym2[:3], sym2[3:]]) if len(sym2) == 6 else set([sym2])
        
        return len(currencies1 & currencies2) > 0
    
    def filter_signals(
        self,
        signals: List[Dict],
        account_state: Any
    ) -> List[Dict]:
        """
        Filter and size trading signals through risk management
        """
        if not signals:
            return []
        
        # Update equity from account state
        if hasattr(account_state, 'equity'):
            self.update_equity(account_state.equity)
        
        filtered_signals = []
        
        for signal in signals:
            # Basic validation
            if not all(k in signal for k in ['symbol', 'action', 'entry_price', 'stop_loss']):
                logger.warning(f"Invalid signal format: {signal}")
                continue
            
            # Skip if action is close (handled separately)
            if signal['action'] == 'close':
                filtered_signals.append(signal)
                continue
            
            # Calculate position size
            sizing = self.calculate_position_size(
                symbol=signal['symbol'],
                signal_strength=signal.get('strength', 0.5),
                entry_price=signal['entry_price'],
                stop_loss_price=signal['stop_loss'],
                take_profit_price=signal.get('take_profit', signal['entry_price'] * 1.02),
                account_equity=getattr(account_state, 'equity', 100000),
                volatility=signal.get('volatility', 0.1),
                existing_positions=getattr(account_state, 'active_positions', {}).values()
            )
            
            if not sizing.approved:
                logger.info(f"Signal rejected for {signal['symbol']}: {sizing.reason}")
                continue
            
            # Add sizing to signal
            signal['size'] = sizing.recommended_size
            signal['risk_amount'] = sizing.risk_amount
            signal['risk_pct'] = sizing.risk_pct
            signal['stop_loss'] = sizing.stop_loss_price
            signal['take_profit'] = sizing.take_profit_price
            
            filtered_signals.append(signal)
            
            logger.info(
                f"Signal approved: {signal['symbol']} | "
                f"Size: {sizing.recommended_size} | "
                f"Risk: {sizing.risk_pct:.2%} | "
                f"R/R: {abs(sizing.take_profit_price - signal['entry_price']) / abs(sizing.stop_loss_price - signal['entry_price']):.2f}"
            )
        
        return filtered_signals
    
    def get_status(self) -> Dict[str, Any]:
        """Get risk manager status"""
        return {
            'trading_halted': self._trading_halted,
            'halt_reason': self._halt_reason,
            'halt_until': self._halt_until.isoformat() if self._halt_until else None,
            'current_drawdown': self.current_drawdown,
            'peak_equity': self.peak_equity,
            'daily_pnl': self.daily_pnl,
            'daily_pnl_pct': self.daily_pnl / self.daily_starting_equity if self.daily_starting_equity > 0 else 0,
            'config': {
                'max_position_size_pct': self.config.max_position_size_pct,
                'max_drawdown_pct': self.config.max_drawdown_pct,
                'daily_loss_limit_pct': self.config.daily_loss_limit_pct
            }
        }


# ── Aliases expected by tests ─────────────────────────────────────────────────
from dataclasses import dataclass as _dc, field as _field
from typing import Optional as _Opt


@_dc
class RiskCheckResult:
    """Result of a single risk check — used by tests."""
    passed: bool
    risk_level: "RiskLevel" = None
    message: str = ""
    details: dict = _field(default_factory=dict)

    def __post_init__(self):
        if self.risk_level is None:
            self.risk_level = RiskLevel.LOW if self.passed else RiskLevel.HIGH
