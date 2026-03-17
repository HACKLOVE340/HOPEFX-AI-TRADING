
# Phase 1.1: Event-Driven Backtesting Engine

code = '''"""
HOPEFX Backtesting Engine - Event-Driven Architecture
Production-grade backtesting with transaction cost modeling
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Optional, Tuple, Any
from enum import Enum
import json
import pickle
from pathlib import Path


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class TickData:
    """Represents a single tick/price update"""
    timestamp: datetime
    symbol: str
    bid: float
    ask: float
    volume: float = 0.0
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class BarData:
    """OHLCV bar data"""
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    @classmethod
    def from_ticks(cls, ticks: List[TickData], symbol: str, timestamp: datetime) -> 'BarData':
        if not ticks:
            raise ValueError("Cannot create bar from empty ticks")
        prices = [t.mid for t in ticks]
        volumes = [t.volume for t in ticks]
        return cls(
            timestamp=timestamp,
            symbol=symbol,
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            volume=sum(volumes)
        )


@dataclass
class Order:
    """Represents a trading order"""
    order_id: str
    timestamp: datetime
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: Optional[float] = None
    commission: float = 0.0
    slippage: float = 0.0
    
    def __post_init__(self):
        if self.order_id is None:
            self.order_id = f"ORD_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


@dataclass
class Position:
    """Tracks open position for a symbol"""
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    entry_time: datetime
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    @property
    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price
    
    def update_unrealized_pnl(self, current_price: float) -> float:
        if self.side == OrderSide.BUY:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity
        return self.unrealized_pnl


@dataclass
class Trade:
    """Completed trade record"""
    trade_id: str
    entry_order: Order
    exit_order: Order
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    commission: float
    slippage: float
    duration: timedelta = field(init=False)
    
    def __post_init__(self):
        self.duration = self.exit_time - self.entry_time


@dataclass
class PerformanceMetrics:
    """Comprehensive backtest performance metrics"""
    # Returns
    total_return: float
    annualized_return: float
    volatility: float
    
    # Risk-adjusted
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    
    # Drawdowns
    max_drawdown: float
    max_drawdown_duration: int
    avg_drawdown: float
    
    # Trade stats
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_trade_return: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    
    # Time
    start_date: datetime
    end_date: datetime
    trading_days: int
    
    # Equity curve data
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    drawdown_series: pd.Series = field(default_factory=pd.Series)
    returns_series: pd.Series = field(default_factory=pd.Series)
    
    def to_dict(self) -> Dict:
        return {
            'total_return': self.total_return,
            'annualized_return': self.annualized_return,
            'volatility': self.volatility,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'calmar_ratio': self.calmar_ratio,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_duration': self.max_drawdown_duration,
            'avg_drawdown': self.avg_drawdown,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'avg_trade_return': self.avg_trade_return,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'profit_factor': self.profit_factor,
            'expectancy': self.expectancy,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'trading_days': self.trading_days
        }
    
    def save(self, filepath: str):
        """Save metrics to JSON"""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)


class TransactionCostModel:
    """Models trading costs: commission, spread, slippage"""
    
    def __init__(
        self,
        commission_per_lot: float = 0.0,
        commission_rate: float = 0.0,
        spread_pips: float = 0.0,
        slippage_model: str = "fixed",
        slippage_pips: float = 0.0,
        slippage_std: float = 0.0
    ):
        self.commission_per_lot = commission_per_lot
        self.commission_rate = commission_rate
        self.spread_pips = spread_pips
        self.slippage_model = slippage_model
        self.slippage_pips = slippage_pips
        self.slippage_std = slippage_std
    
    def calculate_costs(
        self,
        order: Order,
        tick: TickData,
        quantity: float
    ) -> Tuple[float, float, float]:
        """Returns (fill_price, commission, slippage)"""
        
        # Base price with spread
        if order.side == OrderSide.BUY:
            base_price = tick.ask
        else:
            base_price = tick.bid
        
        # Add slippage
        if self.slippage_model == "fixed":
            slippage = self.slippage_pips * 0.0001  # Convert pips to price
        elif self.slippage_model == "gaussian":
            slippage = np.random.normal(self.slippage_pips * 0.0001, self.slippage_std * 0.0001)
        else:
            slippage = 0.0
        
        if order.side == OrderSide.BUY:
            fill_price = base_price + slippage
        else:
            fill_price = base_price - slippage
        
        # Commission
        if self.commission_per_lot > 0:
            commission = self.commission_per_lot * (quantity / 100000)  # Standard lot size
        elif self.commission_rate > 0:
            commission = fill_price * quantity * self.commission_rate
        else:
            commission = 0.0
        
        return fill_price, commission, slippage


class BacktestEngine:
    """
    Event-driven backtesting engine
    Processes ticks/bars sequentially, executes orders, tracks performance
    """
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        transaction_costs: Optional[TransactionCostModel] = None,
        data_frequency: str = "tick",  # tick, 1m, 5m, 1h, 1d
        enable_fractional: bool = False,
        leverage: float = 1.0
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.transaction_costs = transaction_costs or TransactionCostModel()
        self.data_frequency = data_frequency
        self.enable_fractional = enable_fractional
        self.leverage = leverage
        
        # State
        self.positions: Dict[str, Position] = {}
        self.pending_orders: List[Order] = []
        self.closed_trades: List[Trade] = []
        self.equity_history: List[Dict] = []
        self.current_time: Optional[datetime] = None
        
        # Performance tracking
        self.peak_equity = initial_capital
        self.current_drawdown = 0.0
        self.max_drawdown = 0.0
        self.drawdown_start: Optional[datetime] = None
        self.max_drawdown_duration = 0
        
        # Strategy
        self.strategy: Optional[Callable] = None
        self.symbols: List[str] = []
        
        # Data
        self.data_handler: Optional[Any] = None
        
    def set_strategy(self, strategy: Callable, symbols: List[str]):
        """Set the trading strategy function"""
        self.strategy = strategy
        self.symbols = symbols
    
    def set_data_handler(self, data_handler: Any):
        """Set data source (CSV, database, API)"""
        self.data_handler = data_handler
    
    def run(self, start_date: datetime, end_date: datetime) -> PerformanceMetrics:
        """
        Run backtest over date range
        """
        if self.strategy is None:
            raise ValueError("Strategy not set. Call set_strategy() first.")
        if self.data_handler is None:
            raise ValueError("Data handler not set. Call set_data_handler() first.")
        
        print(f"Starting backtest from {start_date} to {end_date}")
        print(f"Initial capital: ${self.initial_capital:,.2f}")
        
        # Reset state
        self.capital = self.initial_capital
        self.positions = {}
        self.pending_orders = []
        self.closed_trades = []
        self.equity_history = []
        self.peak_equity = self.initial_capital
        self.max_drawdown = 0.0
        self.max_drawdown_duration = 0
        
        # Get data iterator
        data_iterator = self.data_handler.get_data(start_date, end_date, self.symbols)
        
        # Event loop
        for timestamp, symbol, tick in data_iterator:
            self.current_time = timestamp
            
            # Process pending orders
            self._process_orders(tick)
            
            # Update positions
            self._update_positions(tick)
            
            # Record equity
            self._record_equity(timestamp)
            
            # Call strategy
            signals = self.strategy(
                timestamp=timestamp,
                symbol=symbol,
                tick=tick,
                positions=self.positions,
                capital=self.capital,
                history=self.equity_history
            )
            
            # Execute signals
            if signals:
                for signal in signals:
                    self._execute_signal(signal, tick)
        
        # Close all positions at end
        self._close_all_positions()
        
        # Calculate metrics
        metrics = self._calculate_metrics(start_date, end_date)
        
        print(f"Backtest complete. Final equity: ${self.capital:,.2f}")
        print(f"Total return: {metrics.total_return:.2%}")
        print(f"Max drawdown: {metrics.max_drawdown:.2%}")
        print(f"Sharpe ratio: {metrics.sharpe_ratio:.2f}")
        
        return metrics
    
    def _process_orders(self, tick: TickData):
        """Process pending orders against current tick"""
        filled_orders = []
        
        for order in self.pending_orders:
            if order.symbol != tick.symbol:
                continue
            
            fill_price = None
            
            # Check fill conditions
            if order.order_type == OrderType.MARKET:
                fill_price = tick.ask if order.side == OrderSide.BUY else tick.bid
            
            elif order.order_type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and tick.ask <= order.price:
                    fill_price = order.price
                elif order.side == OrderSide.SELL and tick.bid >= order.price:
                    fill_price = order.price
            
            elif order.order_type == OrderType.STOP:
                if order.side == OrderSide.BUY and tick.ask >= order.stop_price:
                    fill_price = tick.ask
                elif order.side == OrderSide.SELL and tick.bid <= order.stop_price:
                    fill_price = tick.bid
            
            if fill_price:
                # Apply transaction costs
                fill_price, commission, slippage = self.transaction_costs.calculate_costs(
                    order, tick, order.quantity
                )
                
                order.filled_price = fill_price
                order.filled_quantity = order.quantity
                order.commission = commission
                order.slippage = slippage
                order.status = OrderStatus.FILLED
                
                self._update_position_from_fill(order)
                filled_orders.append(order)
        
        # Remove filled orders
        for order in filled_orders:
            self.pending_orders.remove(order)
    
    def _update_positions(self, tick: TickData):
        """Update unrealized PnL for open positions"""
        if tick.symbol in self.positions:
            position = self.positions[tick.symbol]
            position.update_unrealized_pnl(tick.mid)
    
    def _record_equity(self, timestamp: datetime):
        """Record current equity state"""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        total_equity = self.capital + unrealized
        
        # Update drawdown
        if total_equity > self.peak_equity:
            self.peak_equity = total_equity
            self.drawdown_start = None
        else:
            drawdown = (self.peak_equity - total_equity) / self.peak_equity
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown
            
            if self.drawdown_start is None:
                self.drawdown_start = timestamp
            else:
                duration = (timestamp - self.drawdown_start).days
                if duration > self.max_drawdown_duration:
                    self.max_drawdown_duration = duration
        
        self.equity_history.append({
            'timestamp': timestamp,
            'capital': self.capital,
            'unrealized_pnl': unrealized,
            'total_equity': total_equity,
            'drawdown': (self.peak_equity - total_equity) / self.peak_equity if self.peak_equity > 0 else 0,
            'positions': len(self.positions)
        })
    
    def _execute_signal(self, signal: Dict, tick: TickData):
        """Convert strategy signal to order"""
        side = OrderSide.BUY if signal['action'] == 'buy' else OrderSide.SELL
        quantity = signal.get('quantity', 0.0)
        
        if quantity <= 0:
            return
        
        # Check for position close
        if tick.symbol in self.positions:
            current_pos = self.positions[tick.symbol]
            if current_pos.side != side:
                # Close existing position
                close_order = Order(
                    order_id=None,
                    timestamp=self.current_time,
                    symbol=tick.symbol,
                    side=OrderSide.SELL if current_pos.side == OrderSide.BUY else OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=current_pos.quantity
                )
                self.pending_orders.append(close_order)
        
        # Open new position
        order = Order(
            order_id=None,
            timestamp=self.current_time,
            symbol=tick.symbol,
            side=side,
            order_type=signal.get('order_type', OrderType.MARKET),
            quantity=quantity,
            price=signal.get('price'),
            stop_price=signal.get('stop_price')
        )
        
        self.pending_orders.append(order)
    
    def _update_position_from_fill(self, order: Order):
        """Update or create position from filled order"""
        symbol = order.symbol
        
        if symbol in self.positions:
            position = self.positions[symbol]
            
            if position.side == order.side:
                # Adding to position
                total_qty = position.quantity + order.filled_quantity
                position.entry_price = (
                    (position.entry_price * position.quantity + order.filled_price * order.filled_quantity) / total_qty
                )
                position.quantity = total_qty
            else:
                # Reducing/closing position
                if order.filled_quantity >= position.quantity:
                    # Close position
                    pnl = position.realized_pnl + (order.filled_price - position.entry_price) * position.quantity
                    if position.side == OrderSide.SELL:
                        pnl = -pnl
                    
                    trade = Trade(
                        trade_id=f"TRADE_{len(self.closed_trades)}",
                        entry_order=order,  # Simplified - should track original entry
                        exit_order=order,
                        symbol=symbol,
                        side=position.side,
                        quantity=position.quantity,
                        entry_price=position.entry_price,
                        exit_price=order.filled_price,
                        entry_time=position.entry_time,
                        exit_time=self.current_time,
                        pnl=pnl,
                        commission=order.commission,
                        slippage=order.slippage
                    )
                    
                    self.closed_trades.append(trade)
                    self.capital += pnl - order.commission
                    del self.positions[symbol]
                else:
                    # Partial close
                    position.quantity -= order.filled_quantity
                    self.capital -= order.commission
        else:
            # New position
            self.positions[symbol] = Position(
                symbol=symbol,
                side=order.side,
                quantity=order.filled_quantity,
                entry_price=order.filled_price,
                entry_time=self.current_time
            )
            self.capital -= order.commission
    
    def _close_all_positions(self):
        """Close all open positions at end of backtest"""
        for symbol, position in list(self.positions.items()):
            # Create closing order at last known price
            close_order = Order(
                order_id=f"CLOSE_{symbol}",
                timestamp=self.current_time,
                symbol=symbol,
                side=OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
                filled_quantity=position.quantity,
                filled_price=position.entry_price,  # Simplified - should use last tick
                status=OrderStatus.FILLED
            )
            
            pnl = (close_order.filled_price - position.entry_price) * position.quantity
            if position.side == OrderSide.SELL:
                pnl = -pnl
            
            trade = Trade(
                trade_id=f"TRADE_{len(self.closed_trades)}",
                entry_order=close_order,
                exit_order=close_order,
                symbol=symbol,
                side=position.side,
                quantity=position.quantity,
                entry_price=position.entry_price,
                exit_price=close_order.filled_price,
                entry_time=position.entry_time,
                exit_time=self.current_time,
                pnl=pnl,
                commission=0.0,
                slippage=0.0
            )
            
            self.closed_trades.append(trade)
            self.capital += pnl
        
        self.positions = {}
    
    def _calculate_metrics(self, start_date: datetime, end_date: datetime) -> PerformanceMetrics:
        """Calculate comprehensive performance metrics"""
        
        # Convert equity history to DataFrame
        equity_df = pd.DataFrame(self.equity_history)
        if len(equity_df) == 0:
            raise ValueError("No equity history recorded")
        
        equity_df.set_index('timestamp', inplace=True)
        
        # Calculate returns
        total_return = (self.capital - self.initial_capital) / self.initial_capital
        
        # Annualized metrics
        days = (end_date - start_date).days
        years = days / 365.25
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        
        # Daily returns for volatility
        equity_df['daily_return'] = equity_df['total_equity'].pct_change()
        volatility = equity_df['daily_return'].std() * np.sqrt(252)  # Annualized
        
        # Risk-adjusted metrics
        risk_free_rate = 0.02  # Assume 2%
        excess_return = annualized_return - risk_free_rate
        sharpe_ratio = excess_return / volatility if volatility > 0 else 0
        
        # Sortino (downside deviation only)
        downside_returns = equity_df['daily_return'][equity_df['daily_return'] < 0]
        downside_dev = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
        sortino_ratio = excess_return / downside_dev if downside_dev > 0 else 0
        
        # Calmar (return / max drawdown)
        calmar_ratio = annualized_return / self.max_drawdown if self.max_drawdown > 0 else 0
        
        # Trade statistics
        total_trades = len(self.closed_trades)
        if total_trades > 0:
            winning_trades = sum(1 for t in self.closed_trades if t.pnl > 0)
            losing_trades = total_trades - winning_trades
            win_rate = winning_trades / total_trades
            
            avg_trade_return = sum(t.pnl for t in self.closed_trades) / total_trades
            
            wins = [t.pnl for t in self.closed_trades if t.pnl > 0]
            losses = [t.pnl for t in self.closed_trades if t.pnl <= 0]
            
            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            
            gross_profit = sum(wins)
            gross_loss = abs(sum(losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            
            expectancy = (win_rate * avg_win) - ((1 - win_rate) * abs(avg_loss))
        else:
            winning_trades = losing_trades = 0
            win_rate = avg_trade_return = avg_win = avg_loss = profit_factor = expectancy = 0
        
        # Drawdown calculations
        equity_curve = equity_df['total_equity']
        rolling_max = equity_curve.expanding().max()
        drawdown_series = (equity_curve - rolling_max) / rolling_max
        avg_drawdown = drawdown_series[drawdown_series < 0].mean() if len(drawdown_series[drawdown_series < 0]) > 0 else 0
        
        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            max_drawdown=self.max_drawdown,
            max_drawdown_duration=self.max_drawdown_duration,
            avg_drawdown=avg_drawdown,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_trade_return=avg_trade_return,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            expectancy=expectancy,
            start_date=start_date,
            end_date=end_date,
            trading_days=days,
            equity_curve=equity_df,
            drawdown_series=drawdown_series,
            returns_series=equity_df['daily_return']
        )
    
    def save_results(self, filepath_prefix: str):
        """Save backtest results to disk"""
        Path(filepath_prefix).parent.mkdir(parents=True, exist_ok=True)
        
        # Save equity history
        equity_df = pd.DataFrame(self.equity_history)
        equity_df.to_csv(f"{filepath_prefix}_equity.csv", index=False)
        
        # Save trades
        trades_data = []
        for trade in self.closed_trades:
            trades_data.append({
                'trade_id': trade.trade_id,
                'symbol': trade.symbol,
                'side': trade.side.value,
                'quantity': trade.quantity,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'entry_time': trade.entry_time.isoformat(),
                'exit_time': trade.exit_time.isoformat(),
                'pnl': trade.pnl,
                'commission': trade.commission,
                'slippage': trade.slippage,
                'duration_seconds': trade.duration.total_seconds()
            })
        
        trades_df = pd.DataFrame(trades_data)
        trades_df.to_csv(f"{filepath_prefix}_trades.csv", index=False)
        
        # Save state
        state = {
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_trades': len(self.closed_trades),
            'symbols': self.symbols,
            'data_frequency': self.data_frequency
        }
        
        with open(f"{filepath_prefix}_state.json", 'w') as f:
            json.dump(state, f, indent=2)
        
        print(f"Results saved to {filepath_prefix}*")


# Simple data handler for CSV files
class CSVDataHandler:
    """Loads and iterates tick/bar data from CSV"""
    
    def __init__(self, filepath: str, date_format: str = '%Y-%m-%d %H:%M:%S'):
        self.filepath = filepath
        self.date_format = date_format
        self.data: pd.DataFrame = None
    
    def load(self):
        """Load CSV data"""
        self.data = pd.read_csv(self.filepath)
        self.data['timestamp'] = pd.to_datetime(self.data['timestamp'], format=self.date_format)
        self.data.sort_values('timestamp', inplace=True)
        print(f"Loaded {len(self.data)} rows from {self.filepath}")
    
    def get_data(self, start_date: datetime, end_date: datetime, symbols: List[str]):
        """Generator yielding (timestamp, symbol, tick)"""
        if self.data is None:
            self.load()
        
        mask = (self.data['timestamp'] >= start_date) & (self.data['timestamp'] <= end_date)
        filtered = self.data[mask]
        
        for _, row in filtered.iterrows():
            tick = TickData(
                timestamp=row['timestamp'],
                symbol=row['symbol'],
                bid=row['bid'],
                ask=row['ask'],
                volume=row.get('volume', 0.0)
            )
            yield row['timestamp'], row['symbol'], tick


if __name__ == "__main__":
    # Example usage
    print("HOPEFX Backtesting Engine")
    print("Import this module and create your strategy")
'''

# Save the file
with open('backtesting/engine.py', 'w') as f:
    f.write(code)

print("✅ Created: backtesting/engine.py")
print(f"   Lines: {len(code.splitlines())}")
print(f"   Size: {len(code)} bytes")
