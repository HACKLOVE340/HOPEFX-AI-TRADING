"""
Backtesting Engine

Core event-driven backtesting engine for strategy evaluation.
"""

import logging
from queue import Queue
from typing import List, Dict, Optional
from backtesting.data_handler import DataHandler
from backtesting.execution import SimulatedExecutionHandler
from backtesting.portfolio import Portfolio
from backtesting.metrics import PerformanceMetrics
from backtesting.events import MarketEvent, SignalEvent, OrderEvent, FillEvent, EventType

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Event-driven backtesting engine.
    
    Coordinates data, strategy, execution, and portfolio components
    to simulate trading.
    """
    
    def __init__(self, data_handler: DataHandler, strategy, 
                 initial_capital: float = 100000.0,
                 commission_pct: float = 0.001,
                 slippage_pct: float = 0.0005):
        """
        Initialize backtesting engine.
        
        Args:
            data_handler: DataHandler instance
            strategy: Trading strategy instance
            initial_capital: Starting capital
            commission_pct: Commission percentage
            slippage_pct: Slippage percentage
        """
        self.data_handler = data_handler
        self.strategy = strategy
        
        self.events = Queue()
        self.portfolio = Portfolio(initial_capital)
        self.execution_handler = SimulatedExecutionHandler(
            data_handler, commission_pct, slippage_pct
        )
        
        self.signals_generated = 0
        self.orders_placed = 0
        self.fills_executed = 0
        
        logger.info(f"Initialized backtesting engine with ${initial_capital:,.2f}")
        
    def run(self):
        """Run the backtest."""
        logger.info("Starting backtest...")
        
        # Load data
        self.data_handler.load_data()
        
        # Main backtest loop
        while self.data_handler.continue_backtest:
            # Update market data
            self.data_handler.update_bars()
            
            if not self.data_handler.continue_backtest:
                break
                
            # Generate market event
            self.events.put(MarketEvent())
            
            # Process event queue
            while not self.events.empty():
                event = self.events.get()
                
                if event.type == EventType.MARKET:
                    self._handle_market_event()
                elif event.type == EventType.SIGNAL:
                    self._handle_signal_event(event)
                elif event.type == EventType.ORDER:
                    self._handle_order_event(event)
                elif event.type == EventType.FILL:
                    self._handle_fill_event(event)
                    
            # Update portfolio equity
            current_datetime = self.data_handler.get_current_datetime()
            current_prices = self._get_current_prices()
            
            if current_datetime:
                self.portfolio.update_timeindex(current_datetime, current_prices)
                
        logger.info(f"Backtest complete!")
        logger.info(f"Signals: {self.signals_generated}, Orders: {self.orders_placed}, Fills: {self.fills_executed}")
        
        return self.get_results()
        
    def _handle_market_event(self):
        """Handle market data update."""
        # Generate signals from strategy
        signals = self.strategy.calculate_signals(self.data_handler)
        
        if signals:
            for signal in signals:
                self.events.put(signal)
                self.signals_generated += 1
                
    def _handle_signal_event(self, signal: SignalEvent):
        """
        Handle trading signal by generating orders.
        
        Args:
            signal: SignalEvent from strategy
        """
        # In a real implementation, this would consult risk management
        # For now, simple conversion to market order
        
        # Determine order size (simplified - could use position sizing)
        quantity = self._calculate_position_size(signal)
        
        if quantity > 0:
            order = OrderEvent(
                symbol=signal.symbol,
                order_type='MARKET',
                quantity=quantity,
                direction=signal.signal_type
            )
            
            self.events.put(order)
            self.orders_placed += 1
            
    def _handle_order_event(self, order: OrderEvent):
        """
        Handle order by simulating execution.
        
        Args:
            order: OrderEvent to execute
        """
        fill = self.execution_handler.execute_order(order)
        
        if fill:
            self.events.put(fill)
            self.fills_executed += 1
            
    def _handle_fill_event(self, fill: FillEvent):
        """
        Handle fill by updating portfolio.
        
        Args:
            fill: FillEvent with execution details
        """
        current_prices = self._get_current_prices()
        self.portfolio.update_fill(fill, current_prices)
        
    def _get_current_prices(self) -> Dict[str, float]:
        """Get current prices for all symbols."""
        prices = {}
        
        for symbol in self.data_handler.symbols:
            bar = self.data_handler.get_latest_bar(symbol)
            if bar is not None:
                prices[symbol] = bar['close']
                
        return prices
        
    def _calculate_position_size(self, signal: SignalEvent) -> float:
        """
        Calculate position size for signal.
        
        Args:
            signal: Trading signal
            
        Returns:
            Position size
        """
        # Simplified position sizing
        # In reality, would use risk management module
        
        # Fixed position size for now
        return 100  # Placeholder
        
    def get_results(self) -> Dict:
        """
        Get backtest results.
        
        Returns:
            Dict with results and metrics
        """
        equity_curve = self.portfolio.get_equity_curve()
        trade_history = self.portfolio.get_trade_history()
        
        # Calculate metrics
        metrics_calc = PerformanceMetrics(
            equity_curve,
            trade_history,
            self.portfolio.initial_capital
        )
        
        metrics = metrics_calc.calculate_all_metrics()
        
        results = {
            'metrics': metrics,
            'equity_curve': equity_curve,
            'trade_history': trade_history,
            'holdings': self.portfolio.get_holdings(),
            'signals_generated': self.signals_generated,
            'orders_placed': self.orders_placed,
            'fills_executed': self.fills_executed,
        }
        
        return results
        
    def print_results(self):
        """Print backtest results to console."""
        results = self.get_results()
        metrics = results['metrics']
        
        print("\n" + "="*60)
        print("BACKTEST RESULTS")
        print("="*60)
        
        print(f"\nPerformance:")
        print(f"  Total Return: {metrics['total_return']:.2f}%")
        print(f"  Annual Return: {metrics['annual_return']:.2f}%")
        print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown: {metrics['max_drawdown']:.2f}%")
        
        print(f"\nTrade Statistics:")
        print(f"  Total Trades: {metrics['total_trades']}")
        print(f"  Win Rate: {metrics['win_rate']:.2f}%")
        print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"  Avg Win: ${metrics['avg_win']:.2f}")
        print(f"  Avg Loss: ${metrics['avg_loss']:.2f}")
        
        print(f"\nPortfolio:")
        print(f"  Final Equity: ${metrics['final_equity']:,.2f}")
        print(f"  Peak Equity: ${metrics['peak_equity']:,.2f}")
        
        print("="*60 + "\n")
