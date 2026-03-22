"""
Prop Firm Challenge Compliance Engine
Supports: FTMO, MyForexFunds, The5ers, TopStep, True Forex Funds
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
import json
from pathlib import Path

class PropFirm(Enum):
    FTMO = "ftmo"
    MY_FOREX_FUNDS = "my_forex_funds"
    THE5ERS = "the5ers"
    TOPSTEP = "topstep"
    TRUE_FOREX_FUNDS = "true_forex_funds"

@dataclass
class ChallengeConfig:
    """Configuration for prop firm challenge."""
    firm: PropFirm
    account_size: float
    max_daily_loss: float  # Percentage
    max_total_loss: float  # Percentage
    profit_target: float   # Percentage
    min_trading_days: int
    max_trading_days: int
    allowed_instruments: List[str]
    max_lot_size: Optional[float] = None
    weekend_holding: bool = True
    news_trading: bool = True

@dataclass
class ComplianceStatus:
    """Current compliance status."""
    compliant: bool
    violations: List[str]
    daily_loss_used: float
    total_loss_used: float
    profit_progress: float
    days_traded: int
    days_remaining: int

class PropFirmComplianceEngine:
    """
    Real-time compliance monitoring for prop firm challenges.
    Prevents violations that would disqualify the trader.
    """
    
    RULES = {
        PropFirm.FTMO: {
            'daily_loss_limit': 0.05,      # 5%
            'total_loss_limit': 0.10,      # 10%
            'profit_target': 0.10,         # 10%
            'min_days': 4,
            'max_days': 30,
            'max_lot_per_10k': 1.0,        # 1 lot per $10k
        },
        PropFirm.MY_FOREX_FUNDS: {
            'daily_loss_limit': 0.05,
            'total_loss_limit': 0.12,      # 12%
            'profit_target': 0.08,         # 8%
            'min_days': 3,
            'max_days': 30,
            'max_lot_per_10k': 2.0,
        },
        PropFirm.THE5ERS: {
            'daily_loss_limit': 0.04,      # 4%
            'total_loss_limit': 0.08,      # 8%
            'profit_target': 0.06,         # 6%
            'min_days': 3,
            'max_days': 60,
        }
    }
    
    def __init__(self, config: ChallengeConfig):
        self.config = config
        self.rules = self.RULES.get(config.firm, {})
        self.daily_pnl: Dict[str, float] = {}
        self.trades: List[Dict] = []
        self.start_date = datetime.now()
        self.violation_handlers: List[Callable] = []
        
        # Load state if exists
        self._load_state()
    
    def _load_state(self):
        """Load challenge state from disk."""
        state_file = Path(f"prop_firms/{self.config.firm.value}_{self.config.account_size}.json")
        if state_file.exists():
            with open(state_file) as f:
                state = json.load(f)
                self.daily_pnl = state.get('daily_pnl', {})
                self.trades = state.get('trades', [])
                self.start_date = datetime.fromisoformat(state['start_date'])
    
    def _save_state(self):
        """Persist challenge state."""
        state_file = Path(f"prop_firms/{self.config.firm.value}_{self.config.account_size}.json")
        state_file.parent.mkdir(exist_ok=True)
        
        with open(state_file, 'w') as f:
            json.dump({
                'firm': self.config.firm.value,
                'account_size': self.config.account_size,
                'start_date': self.start_date.isoformat(),
                'daily_pnl': self.daily_pnl,
                'trades': self.trades[-1000:],  # Keep last 1000
                'current_equity': self._get_current_equity()
            }, f, indent=2)
    
    def check_trade_allowed(self, trade: Dict) -> ComplianceStatus:
        """
        Check if a proposed trade violates any rules.
        Must be called BEFORE executing the trade.
        """
        violations = []
        current_equity = self._get_current_equity()
        
        # Check lot size limit
        if self.rules.get('max_lot_per_10k'):
            max_lots = (self.config.account_size / 10000) * self.rules['max_lot_per_10k']
            if trade['size'] > max_lots:
                violations.append(f"Lot size {trade['size']} exceeds max {max_lots}")
        
        # Check instrument allowed
        if trade['symbol'] not in self.config.allowed_instruments:
            violations.append(f"Instrument {trade['symbol']} not allowed")
        
        # Simulate worst-case scenario
        worst_case_pnl = -trade['size'] * 100 * 10  # 100 pips against
        
        # Check daily loss limit
        today = datetime.now().strftime('%Y-%m-%d')
        current_daily_loss = abs(min(0, self.daily_pnl.get(today, 0)))
        potential_daily_loss = current_daily_loss + abs(worst_case_pnl)
        
        if potential_daily_loss > self.config.account_size * self.config.max_daily_loss:
            violations.append(f"Daily loss limit would be exceeded: ${potential_daily_loss:.2f}")
        
        # Check total loss limit
        total_loss = sum(min(0, pnl) for pnl in self.daily_pnl.values())
        potential_total = abs(total_loss) + abs(worst_case_pnl)
        
        if potential_total > self.config.account_size * self.config.max_total_loss:
            violations.append("Total loss limit would be exceeded")
        
        return ComplianceStatus(
            compliant=len(violations) == 0,
            violations=violations,
            daily_loss_used=current_daily_loss / self.config.account_size,
            total_loss_used=abs(total_loss) / self.config.account_size,
            profit_progress=self._calculate_profit_progress(),
            days_traded=len(self.daily_pnl),
            days_remaining=self.config.max_trading_days - (datetime.now() - self.start_date).days
        )
    
    def record_trade(self, trade: Dict, result: Dict):
        """Record completed trade and update compliance metrics."""
        self.trades.append({
            **trade,
            'exit_price': result['exit_price'],
            'pnl': result['pnl'],
            'timestamp': datetime.now().isoformat()
        })
        
        # Update daily P&L
        today = datetime.now().strftime('%Y-%m-%d')
        self.daily_pnl[today] = self.daily_pnl.get(today, 0) + result['pnl']
        
        self._save_state()
        self._check_violations()
    
    def _check_violations(self):
        """Check for rule violations and trigger alerts."""
        status = self.check_compliance()
        
        if not status.compliant:
            for handler in self.violation_handlers:
                handler(status)
    
    def check_compliance(self) -> ComplianceStatus:
        """Full compliance check."""
        violations = []
        current_equity = self._get_current_equity()
        
        # Calculate metrics
        total_pnl = sum(self.daily_pnl.values())
        profit_target = self.config.account_size * self.config.profit_target
        
        # Check profit target reached
        if total_pnl >= profit_target:
            # Check minimum days
            if len(self.daily_pnl) >= self.config.min_trading_days:
                violations.append("PROFIT TARGET REACHED - Challenge Complete!")
            else:
                violations.append(f"Profit target reached but only {len(self.daily_pnl)} trading days (min {self.config.min_trading_days})")
        
        # Check time limit
        days_elapsed = (datetime.now() - self.start_date).days
        if days_elapsed > self.config.max_trading_days:
            violations.append("Maximum trading days exceeded - Challenge Failed")
        
        return ComplianceStatus(
            compliant=len([v for v in violations if 'Complete' not in v and 'Failed' not in v]) == 0,
            violations=violations,
            daily_loss_used=abs(min(0, self.daily_pnl.get(datetime.now().strftime('%Y-%m-%d'), 0))) / self.config.account_size,
            total_loss_used=abs(sum(min(0, pnl) for pnl in self.daily_pnl.values())) / self.config.account_size,
            profit_progress=total_pnl / profit_target,
            days_traded=len(self.daily_pnl),
            days_remaining=self.config.max_trading_days - days_elapsed
        )
    
    def on_violation(self, handler: Callable):
        """Register violation handler."""
        self.violation_handlers.append(handler)
    
    def _get_current_equity(self) -> float:
        """Calculate current equity."""
        return self.config.account_size + sum(self.daily_pnl.values())
    
    def _calculate_profit_progress(self) -> float:
        """Calculate progress toward profit target."""
        total_pnl = sum(self.daily_pnl.values())
        target = self.config.account_size * self.config.profit_target
        return min(total_pnl / target, 1.0) if target > 0 else 0
    
    def get_dashboard(self) -> Dict:
        """Get compliance dashboard data."""
        status = self.check_compliance()
        
        return {
            'firm': self.config.firm.value,
            'account_size': self.config.account_size,
            'current_equity': self._get_current_equity(),
            'total_return_pct': (self._get_current_equity() / self.config.account_size - 1) * 100,
            'profit_target_pct': self.config.profit_target * 100,
            'progress_pct': status.profit_progress * 100,
            'daily_loss_limit_pct': self.config.max_daily_loss * 100,
            'daily_loss_used_pct': status.daily_loss_used * 100,
            'total_loss_limit_pct': self.config.max_total_loss * 100,
            'total_loss_used_pct': status.total_loss_used * 100,
            'days_traded': status.days_traded,
            'min_days_required': self.config.min_trading_days,
            'days_remaining': status.days_remaining,
            'status': 'passing' if status.compliant else 'violation',
            'violations': status.violations,
            'recent_trades': self.trades[-5:]
        }

# Usage example
if __name__ == '__main__':
    # Setup FTMO $100k challenge
    config = ChallengeConfig(
        firm=PropFirm.FTMO,
        account_size=100000,
        max_daily_loss=0.05,
        max_total_loss=0.10,
        profit_target=0.10,
        min_trading_days=4,
        max_trading_days=30,
        allowed_instruments=['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY']
    )
    
    engine = PropFirmComplianceEngine(config)
    
    # Check before trading
    proposed_trade = {'symbol': 'XAUUSD', 'size': 10.0, 'side': 'buy'}
    status = engine.check_trade_allowed(proposed_trade)
    
    if not status.compliant:
        print("Trade blocked:", status.violations)
    else:
        print("Trade approved")
