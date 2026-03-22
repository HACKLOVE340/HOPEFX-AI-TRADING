# portfolio/pms.py
"""
HOPEFX Portfolio Management System
Real-time P&L, exposure, and portfolio optimization
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class Position:
    """Portfolio position with real-time P&L"""
    symbol: str
    quantity: Decimal = Decimal("0")
    avg_entry_price: Decimal = Decimal("0")
    market_price: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    opened_at: datetime = field(default_factory=datetime.utcnow)
    trades: List[Dict] = field(default_factory=list)
    
    def update_market_price(self, price: Decimal):
        """Update with latest market price"""
        self.market_price = price
        if self.quantity != 0:
            self.unrealized_pnl = self.quantity * (price - self.avg_entry_price)
    
    def add_trade(self, trade_qty: Decimal, trade_price: Decimal, side: str):
        """Process new trade"""
        trade = {
            'timestamp': datetime.utcnow(),
            'quantity': trade_qty,
            'price': trade_price,
            'side': side
        }
        self.trades.append(trade)
        
        # Update position
        if side == "BUY":
            # Increase long or reduce short
            if self.quantity >= 0:
                # Adding to long
                total_cost = (self.quantity * self.avg_entry_price) + (trade_qty * trade_price)
                self.quantity += trade_qty
                self.avg_entry_price = total_cost / self.quantity if self.quantity != 0 else Decimal("0")
            else:
                # Reducing short
                self.realized_pnl += trade_qty * (self.avg_entry_price - trade_price)
                self.quantity += trade_qty
                if self.quantity == 0:
                    self.avg_entry_price = Decimal("0")
        else:  # SELL
            if self.quantity <= 0:
                # Adding to short
                total_cost = (abs(self.quantity) * self.avg_entry_price) + (trade_qty * trade_price)
                self.quantity -= trade_qty
                self.avg_entry_price = total_cost / abs(self.quantity) if self.quantity != 0 else Decimal("0")
            else:
                # Reducing long
                self.realized_pnl += trade_qty * (trade_price - self.avg_entry_price)
                self.quantity -= trade_qty
                if self.quantity == 0:
                    self.avg_entry_price = Decimal("0")
        
        self.update_market_price(trade_price)
    
    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.market_price
    
    @property
    def total_pnl(self) -> Decimal:
        return self.unrealized_pnl + self.realized_pnl


class PortfolioManager:
    """
    Real-time portfolio tracking with risk metrics.
    """
    
    def __init__(self, base_currency: str = "USD"):
        self.base_currency = base_currency
        self.positions: Dict[str, Position] = {}
        self.cash: Decimal = Decimal("0")
        self.margin_used: Decimal = Decimal("0")
        self.daily_pnl: Decimal = Decimal("0")
        self.total_pnl: Decimal = Decimal("0")
        self.peak_value: Decimal = Decimal("0")
        self.max_drawdown: Decimal = Decimal("0")
        self.trade_history: List[Dict] = []
        self.last_update: datetime = datetime.utcnow()
    
    def update_price(self, symbol: str, price: Decimal):
        """Update market price for symbol"""
        if symbol in self.positions:
            self.positions[symbol].update_market_price(price)
            self._recalculate_portfolio()
    
    def process_fill(self, order_id: str, symbol: str, side: str, 
                     quantity: Decimal, price: Decimal, commission: Decimal):
        """Process order fill"""
        # Update or create position
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        
        pos = self.positions[symbol]
        prev_unrealized = pos.unrealized_pnl
        
        pos.add_trade(quantity, price, side)
        
        # Update cash
        trade_value = quantity * price
        if side == "BUY":
            self.cash -= trade_value + commission
        else:
            self.cash += trade_value - commission
        
        # Record trade
        trade_record = {
            'order_id': order_id,
            'timestamp': datetime.utcnow(),
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': price,
            'commission': commission,
            'realized_pnl': pos.realized_pnl - sum(t.get('realized_pnl', 0) for t in self.trade_history[-10:]),
            'position_after': pos.quantity
        }
        self.trade_history.append(trade_record)
        
        self._recalculate_portfolio()
    
    def _recalculate_portfolio(self):
        """Recalculate all portfolio metrics"""
        total_value = self.cash + sum(pos.market_value for pos in self.positions.values())
        
        # Update peak and drawdown
        if total_value > self.peak_value:
            self.peak_value = total_value
        
        current_drawdown = (self.peak_value - total_value) / self.peak_value if self.peak_value > 0 else Decimal("0")
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
        
        # Update P&L
        self.total_pnl = sum(pos.total_pnl for pos in self.positions.values())
        
        self.last_update = datetime.utcnow()
    
    def get_portfolio_summary(self) -> Dict:
        """Get complete portfolio summary"""
        long_exposure = sum(
            pos.market_value for pos in self.positions.values() if pos.quantity > 0
        )
        short_exposure = sum(
            abs(pos.market_value) for pos in self.positions.values() if pos.quantity < 0
        )
        
        return {
            'timestamp': self.last_update.isoformat(),
            'cash': float(self.cash),
            'total_value': float(self.cash + sum(pos.market_value for pos in self.positions.values())),
            'long_exposure': float(long_exposure),
            'short_exposure': float(short_exposure),
            'net_exposure': float(long_exposure - short_exposure),
            'gross_exposure': float(long_exposure + short_exposure),
            'unrealized_pnl': float(sum(pos.unrealized_pnl for pos in self.positions.values())),
            'realized_pnl': float(sum(pos.realized_pnl for pos in self.positions.values())),
            'total_pnl': float(self.total_pnl),
            'max_drawdown': float(self.max_drawdown),
            'margin_used': float(self.margin_used),
            'positions': {
                sym: {
                    'quantity': float(pos.quantity),
                    'avg_entry': float(pos.avg_entry_price),
                    'market_price': float(pos.market_price),
                    'unrealized_pnl': float(pos.unrealized_pnl),
                    'market_value': float(pos.market_value)
                }
                for sym, pos in self.positions.items() if pos.quantity != 0
            }
        }


class PortfolioOptimizer:
    """
    Kelly Criterion and Mean-Variance optimization.
    """
    
    def __init__(self, pms: PortfolioManager):
        self.pms = pms
        self.returns_history: Dict[str, List[float]] = {}
        self.covariance_matrix: Optional[np.ndarray] = None
        self.target_volatility = 0.15  # 15% annualized
    
    def update_returns(self, symbol: str, daily_return: float):
        """Add daily return to history"""
        if symbol not in self.returns_history:
            self.returns_history[symbol] = []
        self.returns_history[symbol].append(daily_return)
        if len(self.returns_history[symbol]) > 252:  # 1 year
            self.returns_history[symbol].pop(0)
    
    def calculate_kelly_sizes(self) -> Dict[str, float]:
        """
        Kelly Criterion for optimal position sizing.
        f* = (p*b - q) / b
        """
        kelly_sizes = {}
        
        for symbol, returns in self.returns_history.items():
            if len(returns) < 30:
                continue
            
            returns_arr = np.array(returns)
            wins = returns_arr[returns_arr > 0]
            losses = returns_arr[returns_arr < 0]
            
            if len(wins) == 0 or len(losses) == 0:
                continue
            
            win_rate = len(wins) / len(returns_arr)
            loss_rate = 1 - win_rate
            
            avg_win = np.mean(wins)
            avg_loss = abs(np.mean(losses))
            
            # Kelly fraction
            win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            kelly = (win_rate * win_loss_ratio - loss_rate) / win_loss_ratio if win_loss_ratio > 0 else 0
            
            # Half-Kelly for safety
            kelly_sizes[symbol] = max(0, kelly * 0.5)
        
        return kelly_sizes
    
    def optimize_weights(self) -> Dict[str, float]:
        """
        Mean-variance optimization with target volatility.
        """
        symbols = list(self.returns_history.keys())
        if len(symbols) < 2:
            return {sym: 1.0 for sym in symbols}
        
        # Build returns matrix
        min_len = min(len(r) for r in self.returns_history.values())
        returns_matrix = np.array([
            self.returns_history[sym][-min_len:] for sym in symbols
        ])
        
        # Calculate expected returns and covariance
        expected_returns = np.mean(returns_matrix, axis=1)
        cov_matrix = np.cov(returns_matrix)
        
        # Optimization: maximize Sharpe with volatility constraint
        def negative_sharpe(weights):
            port_return = np.dot(weights, expected_returns)
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            
            if port_vol > self.target_volatility / np.sqrt(252):
                return 0  # Penalty
            
            return -(port_return / port_vol) if port_vol > 0 else 0
        
        # Constraints
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}  # Sum to 1
        ]
        bounds = [(0, 0.5) for _ in symbols]  # Max 50% in any position
        
        # Optimize
        from scipy.optimize import minimize
        result = minimize(
            negative_sharpe,
            [1/len(symbols)] * len(symbols),
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )
        
        if result.success:
            return {symbols[i]: max(0, result.x[i]) for i in range(len(symbols))}
        
        # Fallback: equal weight
        return {sym: 1/len(symbols) for sym in symbols}
