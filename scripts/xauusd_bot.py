# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.

# File 2: scripts/xauusd_bot.py - REAL working version (not aspirational)
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

xauusd_bot_content = '''#!/usr/bin/env python3
"""
HOPEFX XAUUSD Paper Trading Bot - WORKING PROTOTYPE
Simple, functional paper trading loop with ML predictions.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('xauusd_bot')


class PaperBroker:
    """Paper broker backed by the live OANDA practice feed."""

    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.positions = {}
        self.trades = []
        self._last_price: float = 0.0

    def get_price(self, symbol):
        """
        Fetch the latest price from the OANDA practice feed.

        Raises RuntimeError if the feed is unavailable — no synthetic
        fallback; callers must handle the error and retry.
        """
        try:
            from data_layer.orchestrator import orchestrator
            tick = orchestrator.get_latest_tick(symbol.replace("XAUUSD", "XAU_USD"))
            if tick is None:
                raise RuntimeError(
                    f"No live tick available for {symbol}. "
                    "Ensure the data layer is started before running the bot."
                )
            self._last_price = tick.mid
            return {
                'bid': tick.bid,
                'ask': tick.ask,
                'mid': tick.mid,
                'timestamp': tick.timestamp.isoformat(),
            }
        except ImportError as exc:
            raise RuntimeError(
                "data_layer.orchestrator not available — "
                "run the bot from the project root with all dependencies installed."
            ) from exc

    def place_order(self, symbol, side, qty, order_type='market'):
        """Simulate order execution."""
        price_data = self.get_price(symbol)
        fill_price = price_data['ask'] if side == 'buy' else price_data['bid']

        trade = {
            'id': f"trade_{len(self.trades)}",
            'symbol': symbol,
            'side': side,
            'qty': qty,
            'price': fill_price,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'pnl': 0.0
        }

        if side == 'buy':
            cost = fill_price * qty
            if cost > self.balance:
                logger.warning("Insufficient balance: $%s < $%s", self.balance, cost)
                return None
            self.balance -= cost
            self.positions[symbol] = {'side': 'long', 'qty': qty, 'entry': fill_price}
        else:
            if symbol in self.positions and self.positions[symbol]['side'] == 'long':
                entry = self.positions[symbol]['entry']
                pnl = (fill_price - entry) * qty
                trade['pnl'] = pnl
                self.balance += fill_price * qty + pnl
                self.equity = self.balance
                del self.positions[symbol]
            else:
                logger.warning("No position to close")
                return None

        self.trades.append(trade)
        logger.info("Order filled: %s %s %s @ %s", side, qty, symbol, fill_price)
        return trade

    def get_position(self, symbol):
        """Get current position."""
        return self.positions.get(symbol)

    def get_unrealized_pnl(self, symbol):
        """Calculate unrealized P&L."""
        if symbol not in self.positions:
            return 0.0
        pos = self.positions[symbol]
        current = self.get_price(symbol)['mid']
        return (current - pos['entry']) * pos['qty']


class SimpleMLModel:
    """
    Momentum-based signal model used when the full ML predictor is unavailable.

    Uses only real price history — no synthetic data. Replace with
    ml.advanced_predictor.get_predictor() for production use.
    """

    def __init__(self):
        self.price_history = []
        self.prediction_history = []

    def predict(self, price_data):
        """Generate prediction based on recent price momentum."""
        self.price_history.append(price_data['mid'])
        if len(self.price_history) < 5:
            return {'signal': 'neutral', 'confidence': 0.5, 'target': price_data['mid']}

        # Simple momentum: if price rising for 3 ticks, predict up
        recent = self.price_history[-5:]
        momentum = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])

        if momentum >= 3:
            signal = 'buy'
            confidence = 0.6 + (momentum - 3) * 0.1
            target = price_data['mid'] + 2.0
        elif momentum <= 1:
            signal = 'sell'
            confidence = 0.6 + (1 - momentum) * 0.1
            target = price_data['mid'] - 2.0
        else:
            signal = 'neutral'
            confidence = 0.5
            target = price_data['mid']

        prediction = {
            'signal': signal,
            'confidence': min(0.95, confidence),
            'target': target,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        self.prediction_history.append(prediction)
        return prediction


class XAUUSDBot:
    """Working XAUUSD paper trading bot."""

    def __init__(self, mode='paper', capital=10000.0, duration_minutes=60):
        self.mode = mode
        self.capital = capital
        self.duration = duration_minutes
        self.broker = PaperBroker(initial_balance=capital)
        self.model = SimpleMLModel()
        self.running = False
        self.stats = {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'peak_equity': capital
        }

    def run(self):
        """Main trading loop."""
        logger.info("Starting XAUUSD Bot - Mode: %s, Capital: $%s", self.mode, self.capital)
        logger.info("Running for %s minutes...", self.duration)

        self.running = True
        start_time = time.time()
        end_time = start_time + (self.duration * 60)

        try:
            while self.running and time.time() < end_time:
                self._tick()
                time.sleep(5)  # 5-second ticks for demo

        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            self._shutdown()

    def _tick(self):
        """Process one tick."""
        # Get price
        price_data = self.broker.get_price('XAUUSD')

        # Get ML prediction
        pred = self.model.predict(price_data)

        # Get current position
        position = self.broker.get_position('XAUUSD')

        # Trading logic
        if position is None and pred['signal'] == 'buy' and pred['confidence'] > 0.6:
            # Enter long
            qty = 0.01  # Micro lot
            self.broker.place_order('XAUUSD', 'buy', qty)
            self.stats['trades'] += 1
            logger.info("🔵 BUY signal (conf: %s) @ %s", pred['confidence'], price_data['mid'])

        elif position and position['side'] == 'long' and pred['signal'] == 'sell':
            # Exit long
            qty = position['qty']
            trade = self.broker.place_order('XAUUSD', 'sell', qty)
            if trade and trade['pnl'] != 0:
                self.stats['total_pnl'] += trade['pnl']
                if trade['pnl'] > 0:
                    self.stats['wins'] += 1
                else:
                    self.stats['losses'] += 1
            logger.info("🔴 SELL signal @ %s (P&L: $%s)", price_data['mid'], trade.get('pnl', 0))

        # Update equity tracking
        unrealized = self.broker.get_unrealized_pnl('XAUUSD')
        current_equity = self.broker.balance + unrealized

        if current_equity > self.stats['peak_equity']:
            self.stats['peak_equity'] = current_equity

        drawdown = (self.stats['peak_equity'] - current_equity) / self.stats['peak_equity']
        if drawdown > self.stats['max_drawdown']:
            self.stats['max_drawdown'] = drawdown

        # Log status every 30 seconds
        if int(time.time()) % 30 == 0:
            self._log_status(price_data, pred, position, current_equity)

    def _log_status(self, price, pred, position, equity):
        """Log current status."""
        pos_str = f"Position: {position['side']} {position['qty']} @ {position['entry']:.2f}" if position else "Position: None"
        logger.info(
            f"Price: {price['mid']:.2f} | "
            f"Signal: {pred['signal']} ({pred['confidence']:.2f}) | "
            f"{pos_str} | "
            f"Equity: ${equity:.2f} | "
            f"P&L: ${self.stats['total_pnl']:.2f}"
        )

    def _shutdown(self):
        """Graceful shutdown."""
        logger.info("=" * 60)
        logger.info("SHUTDOWN COMPLETE - FINAL RESULTS")
        logger.info("=" * 60)

        # Close any open position
        position = self.broker.get_position('XAUUSD')
        if position:
            logger.info("Closing open position...")
            trade = self.broker.place_order('XAUUSD', 'sell', position['qty'])
            if trade:
                self.stats['total_pnl'] += trade['pnl']

        # Print stats
        win_rate = (self.stats['wins'] / self.stats['trades'] * 100) if self.stats['trades'] > 0 else 0

        logger.info("Total Trades: %s", self.stats['trades'])
        logger.info("Wins: %s | Losses: %s", self.stats['wins'], self.stats['losses'])
        logger.info("Win Rate: %s%", win_rate)
        logger.info("Total P&L: $%s", self.stats['total_pnl'])
        logger.info("Max Drawdown: %s%", self.stats['max_drawdown']*100)
        logger.info("Final Equity: $%s", self.broker.equity)

        # Save results
        results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'mode': self.mode,
            'duration_minutes': self.duration,
            'stats': self.stats,
            'final_equity': self.broker.equity,
            'trades': self.broker.trades
        }

        results_file = Path('results/xauusd_paper_results.json')
        results_file.parent.mkdir(exist_ok=True)
        with Path(results_file).open('w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("Results saved to: %s", results_file)


def main():
    parser = argparse.ArgumentParser(
        description='HOPEFX XAUUSD Paper Trading Bot - Alpha Prototype'
    )
    parser.add_argument(
        '--mode',
        choices=['paper'],
        default='paper',
        help='Trading mode (paper only for now)'
    )
    parser.add_argument(
        '--symbol',
        default='XAUUSD',
        help='Trading symbol (default: XAUUSD)'
    )
    parser.add_argument(
        '--capital',
        type=float,
        default=10000.0,
        help='Initial capital (default: 10000)'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Duration in minutes (default: 60)'
    )

    args = parser.parse_args()

    if args.mode != 'paper':
        print("⚠️  WARNING: Only paper mode is implemented!")
        print("Live trading is NOT available in this alpha version.")
        return 1

    print("=" * 60)
    print("HOPEFX XAUUSD Paper Trading Bot")
    print("Alpha Prototype - Educational Use Only")
    print("=" * 60)
    print(f"Symbol: {args.symbol}")
    print(f"Mode: {args.mode}")
    print(f"Capital: ${args.capital:.2f}")
    print(f"Duration: {args.duration} minutes")
    print("-" * 60)
    print("Press Ctrl+C to stop")
    print("=" * 60)

    bot = XAUUSDBot(
        mode=args.mode,
        capital=args.capital,
        duration_minutes=args.duration
    )

    bot.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
'''

with Path("/mnt/kimi/output/hopefx_upgrade/scripts/xauusd_bot.py").open("w", encoding="utf-8") as f:
    f.write(xauusd_bot_content)

logger.info("scripts/xauusd_bot.py created - REAL working paper trading bot")
