# File 6: execution.py - Complete execution logic with safety checks

execution_content = '''#!/usr/bin/env python3
"""
HOPEFX Execution Module
Smart order execution with slippage modeling and safety checks.
"""

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, Callable

from validation import OrderValidator, Order, ValidationResult

logger = logging.getLogger('execution')


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


@dataclass
class ExecutionResult:
    """Result of order execution."""
    order_id: str
    status: OrderStatus
    filled_qty: float
    avg_price: float
    slippage: float
    commission: float
    pnl: Optional[float] = None
    message: Optional[str] = None
    timestamp: Optional[str] = None


class PaperExecutor:
    """Paper trading executor with realistic fill simulation."""
    
    def __init__(
        self,
        initial_balance: float = 10000.0,
        commission_per_lot: float = 3.5,  # Standard forex commission
        slippage_model: str = 'variable'
    ):
        self.balance = initial_balance
        self.equity = initial_balance
        self.commission_per_lot = commission_per_lot
        self.slippage_model = slippage_model
        self.positions: Dict[str, Dict] = {}
        self.order_history: list = []
        self.validator = OrderValidator()
        self.order_counter = 0
        
    def _generate_order_id(self) -> str:
        """Generate unique order ID."""
        self.order_counter += 1
        return f"ORD_{int(time.time())}_{self.order_counter}"
    
    def _calculate_slippage(
        self,
        symbol: str,
        side: str,
        qty: float,
        base_price: float,
        volatility: float = 0.0
    ) -> float:
        """
        Calculate realistic slippage based on market conditions.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            qty: Order quantity in lots
            base_price: Current market price
            volatility: Current volatility (0-1 scale)
        
        Returns:
            Slippage amount in price terms
        """
        if self.slippage_model == 'fixed':
            # Fixed $0.05 slippage for XAUUSD
            return 0.05 if symbol == 'XAUUSD' else base_price * 0.0001
        
        elif self.slippage_model == 'variable':
            # Variable slippage based on size and volatility
            base_slippage = 0.02  # $0.02 base for XAUUSD
            
            # Size penalty (larger orders = more slippage)
            size_factor = min(qty / 0.1, 5.0)  # Cap at 5x for 1.0 lots
            
            # Volatility penalty
            vol_factor = 1.0 + (volatility * 2.0)
            
            slippage = base_slippage * size_factor * vol_factor
            return min(slippage, 0.5)  # Cap at $0.50
        
        return 0.0
    
    def _calculate_commission(self, qty: float, symbol: str) -> float:
        """Calculate commission based on quantity."""
        # Standard: $3.50 per lot round turn
        return self.commission_per_lot * qty
    
    def submit_order(
        self,
        order: Order,
        current_price: float,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        volatility: float = 0.0,
        skip_validation: bool = False
    ) -> ExecutionResult:
        """
        Submit and execute an order with full validation.
        
        Args:
            order: Order to execute
            current_price: Current market price
            bid: Bid price (optional)
            ask: Ask price (optional)
            volatility: Current market volatility
            skip_validation: Skip validation (for testing only)
        
        Returns:
            ExecutionResult with fill details
        """
        order_id = self._generate_order_id()
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        
        # Validation
        if not skip_validation:
            validation = self.validator.validate_order(
                order=order,
                current_price=current_price,
                account_balance=self.equity,
                open_positions=list(self.positions.values())
            )
            
            if not validation.valid:
                logger.error(f"Order {order_id} rejected: {validation.reason}")
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    filled_qty=0.0,
                    avg_price=0.0,
                    slippage=0.0,
                    commission=0.0,
                    message=validation.reason,
                    timestamp=timestamp
                )
            
            self.validator.record_trade(validation.risk_pct)
        
        # Determine fill price
        if order.side == 'buy':
            base_price = ask if ask else current_price + 0.02
            slippage = self._calculate_slippage(
                order.symbol, order.side, order.qty, base_price, volatility
            )
            fill_price = base_price + slippage
        else:
            base_price = bid if bid else current_price - 0.02
            slippage = self._calculate_slippage(
                order.symbol, order.side, order.qty, base_price, volatility
            )
            fill_price = base_price - slippage
        
        # Calculate costs
        commission = self._calculate_commission(order.qty, order.symbol)
        
        # Execute based on order type
        if order.order_type == 'market':
            return self._execute_market_order(
                order_id, order, fill_price, slippage, commission, timestamp
            )
        elif order.order_type == 'limit':
            return self._execute_limit_order(
                order_id, order, current_price, fill_price, slippage, commission, timestamp
            )
        else:
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message=f"Unsupported order type: {order.order_type}",
                timestamp=timestamp
            )
    
    def _execute_market_order(
        self,
        order_id: str,
        order: Order,
        fill_price: float,
        slippage: float,
        commission: float,
        timestamp: str
    ) -> ExecutionResult:
        """Execute a market order."""
        notional = order.qty * fill_price
        total_cost = notional + commission
        
        # Check balance for buys
        if order.side == 'buy':
            if total_cost > self.balance:
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    filled_qty=0.0,
                    avg_price=0.0,
                    slippage=0.0,
                    commission=0.0,
                    message="Insufficient balance",
                    timestamp=timestamp
                )
            
            # Update balance and positions
            self.balance -= total_cost
            
            # Close existing short if any
            if order.symbol in self.positions and self.positions[order.symbol]['side'] == 'short':
                old_pos = self.positions[order.symbol]
                pnl = (old_pos['entry_price'] - fill_price) * old_pos['qty'] - commission
                self.equity += pnl
                del self.positions[order.symbol]
                logger.info(f"Closed short position P&L: ${pnl:.2f}")
            else:
                # Add to long position
                if order.symbol in self.positions:
                    # Average into existing position
                    old = self.positions[order.symbol]
                    total_qty = old['qty'] + order.qty
                    avg_entry = (old['entry_price'] * old['qty'] + fill_price * order.qty) / total_qty
                    old['qty'] = total_qty
                    old['entry_price'] = avg_entry
                else:
                    self.positions[order.symbol] = {
                        'symbol': order.symbol,
                        'side': 'long',
                        'qty': order.qty,
                        'entry_price': fill_price,
                        'entry_time': timestamp,
                        'stop_loss': order.stop_loss,
                        'take_profit': order.take_profit
                    }
        
        else:  # sell
            if order.symbol not in self.positions:
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    filled_qty=0.0,
                    avg_price=0.0,
                    slippage=0.0,
                    commission=0.0,
                    message="No position to sell",
                    timestamp=timestamp
                )
            
            pos = self.positions[order.symbol]
            if pos['side'] != 'long':
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    filled_qty=0.0,
                    avg_price=0.0,
                    slippage=0.0,
                    commission=0.0,
                    message=f"Cannot sell {pos['side']} position",
                    timestamp=timestamp
                )
            
            # Calculate P&L
            if order.qty >= pos['qty']:
                # Full close
                pnl = (fill_price - pos['entry_price']) * pos['qty'] - commission
                self.balance += fill_price * pos['qty'] - commission
                self.equity += pnl
                del self.positions[order.symbol]
            else:
                # Partial close
                pnl = (fill_price - pos['entry_price']) * order.qty - commission
                self.balance += fill_price * order.qty - commission
                self.equity += pnl
                pos['qty'] -= order.qty
        
        result = ExecutionResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            filled_qty=order.qty,
            avg_price=fill_price,
            slippage=slippage,
            commission=commission,
            timestamp=timestamp
        )
        
        self.order_history.append({
            'order': order,
            'result': result,
            'balance_after': self.balance,
            'equity_after': self.equity
        })
        
        logger.info(
            f"Executed {order.side} {order.qty} {order.symbol} @ {fill_price:.2f} "
            f"(slip: ${slippage:.2f}, comm: ${commission:.2f})"
        )
        
        return result
    
    def _execute_limit_order(
        self,
        order_id: str,
        order: Order,
        current_price: float,
        fill_price: float,
        slippage: float,
        commission: float,
        timestamp: str
    ) -> ExecutionResult:
        """Execute a limit order (simplified - immediate fill if price OK)."""
        if order.price is None:
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message="Limit order requires price",
                timestamp=timestamp
            )
        
        # Check if limit price is acceptable
        if order.side == 'buy' and current_price > order.price:
            # Price moved above limit, won't fill
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.PENDING,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message="Limit price not reached",
                timestamp=timestamp
            )
        
        if order.side == 'sell' and current_price < order.price:
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.PENDING,
                filled_qty=0.0,
                avg_price=0.0,
                slippage=0.0,
                commission=0.0,
                message="Limit price not reached",
                timestamp=timestamp
            )
        
        # Fill at limit price (or better)
        fill_price = order.price
        return self._execute_market_order(
            order_id, order, fill_price, 0.0, commission, timestamp
        )
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get current position for symbol."""
        return self.positions.get(symbol)
    
    def get_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """Calculate unrealized P&L for a position."""
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        
        if pos['side'] == 'long':
            return (current_price - pos['entry_price']) * pos['qty']
        else:
            return (pos['entry_price'] - current_price) * pos['qty']
    
    def close_all_positions(self, current_prices: Dict[str, float]) -> list:
        """Close all open positions."""
        results = []
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            order = Order(
                symbol=symbol,
                side='sell' if pos['side'] == 'long' else 'buy',
                qty=pos['qty']
            )
            result = self.submit_order(
                order, current_prices.get(symbol, pos['entry_price'])
            )
            results.append(result)
        return results


# Smart order router (stub for future multi-broker support)
class SmartOrderRouter:
    """Routes orders to best available broker/venue."""
    
    def __init__(self):
        self.brokers: Dict[str, Any] = {}
        self.default_broker = None
    
    def register_broker(self, name: str, broker_instance, is_default: bool = False):
        """Register a broker for routing."""
        self.brokers[name] = broker_instance
        if is_default or self.default_broker is None:
            self.default_broker = name
        logger.info(f"Registered broker: {name}")
    
    def route_order(self, order: Order, **kwargs) -> ExecutionResult:
        """Route order to appropriate broker."""
        if not self.brokers:
            raise RuntimeError("No brokers registered")
        
        broker = self.brokers.get(self.default_broker)
        if hasattr(broker, 'submit_order'):
            return broker.submit_order(order, **kwargs)
        else:
            raise RuntimeError(f"Broker {self.default_broker} has no submit_order method")


if __name__ == '__main__':
    # Demo
    print("=" * 60)
    print("Execution Module Demo")
    print("=" * 60)
    
    executor = PaperExecutor(initial_balance=10000.0)
    
    # Buy order
    buy_order = Order(symbol='XAUUSD', side='buy', qty=0.01, stop_loss=1950.0)
    result = executor.submit_order(buy_order, current_price=2000.0)
    print(f"\\nBuy order: {result.status.value} @ {result.avg_price:.2f}")
    print(f"  Slippage: ${result.slippage:.2f}, Commission: ${result.commission:.2f}")
    print(f"  Balance: ${executor.balance:.2f}, Equity: ${executor.equity:.2f}")
    
    # Sell order
    sell_order = Order(symbol='XAUUSD', side='sell', qty=0.01)
    result = executor.submit_order(sell_order, current_price=2010.0)
    print(f"\\nSell order: {result.status.value} @ {result.avg_price:.2f}")
    print(f"  Balance: ${executor.balance:.2f}, Equity: ${executor.equity:.2f}")
    
    # Invalid order (should reject)
    bad_order = Order(symbol='INVALID', side='buy', qty=0.01)
    result = executor.submit_order(bad_order, current_price=100.0)
    print(f"\\nInvalid order: {result.status.value} - {result.message}")
'''

with open('/mnt/kimi/output/hopefx_upgrade/execution.py', 'w') as f:
    f.write(execution_content)

print("✅ execution.py created - Order execution with slippage and safety")
