"""
forward_test.py
HOPEFX AI Trading – Forward Test Runner (Mock Data)

Simulates 1 session of forward trading using synthetic XAUUSD price data.
No real broker, no real money.  Safe to run anywhere.

Usage
-----
    python forward_test.py                   # default 500 ticks
    python forward_test.py --ticks 2000      # longer run
    python forward_test.py --seed 42         # reproducible prices

Exit codes
----------
0  – simulation completed without crashes
1  – simulation crashed (see logs)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("forward_test")


def _utcnow() -> datetime:
    """Return current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Lightweight mock components (no external deps required)
# ---------------------------------------------------------------------------

@dataclass
class MockTick:
    symbol: str
    bid: float
    ask: float
    timestamp: datetime = field(default_factory=_utcnow)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class MockPriceFeed:
    """Geometric Brownian Motion XAUUSD price feed."""

    def __init__(
        self,
        start_price: float = 2350.0,
        mu: float = 0.0,
        sigma: float = 0.0008,
        spread_pct: float = 0.0001,
        seed: Optional[int] = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._price = start_price
        self._mu = mu
        self._sigma = sigma
        self._half_spread = start_price * spread_pct / 2

    def next_tick(self) -> MockTick:
        # GBM step
        dt = 1.0 / 86400  # 1 second in fraction of day
        z = self._rng.gauss(0, 1)
        self._price *= 1 + self._mu * dt + self._sigma * z
        half = self._price * 0.00005  # 0.5 pip spread
        return MockTick(
            symbol="XAUUSD",
            bid=round(self._price - half, 3),
            ask=round(self._price + half, 3),
        )


class MockRiskManager:
    """Position-sizing and daily-loss guard."""

    MAX_DAILY_LOSS_USD = 500.0
    RISK_PER_TRADE_PCT = 0.01  # 1 % of account per trade
    MAX_POSITION_LOTS = 0.5

    def __init__(self, account_balance: float = 10_000.0) -> None:
        self.balance = account_balance
        self._daily_loss = 0.0
        self._trade_count = 0

    def check_trade_allowed(self) -> bool:
        if self._daily_loss >= self.MAX_DAILY_LOSS_USD:
            logger.warning(
                "RISK: daily loss limit hit (%.2f / %.2f)",
                self._daily_loss,
                self.MAX_DAILY_LOSS_USD,
            )
            return False
        return True

    def position_size(self, price: float, stop_distance_pips: float = 20.0) -> float:
        """Kelly-lite position sizing (capped)."""
        risk_usd = self.balance * self.RISK_PER_TRADE_PCT
        pip_value = 1.0  # USD per pip per 0.01 lot for XAUUSD (standard contract)
        raw_lots = risk_usd / (stop_distance_pips * pip_value * 100)
        return min(round(raw_lots, 2), self.MAX_POSITION_LOTS)

    def record_pnl(self, pnl: float) -> None:
        self.balance += pnl
        if pnl < 0:
            self._daily_loss += abs(pnl)
        self._trade_count += 1
        logger.info(
            "RISK PnL recorded: %.2f | balance=%.2f | daily_loss=%.2f",
            pnl,
            self.balance,
            self._daily_loss,
        )

    def validate_price(self, price: float) -> bool:
        """Data validation – reject stale/extreme ticks."""
        if price <= 0:
            logger.error("INVALID PRICE: %.4f (non-positive)", price)
            return False
        if price < 1000 or price > 4000:
            logger.warning("SUSPICIOUS PRICE: %.4f (out of XAU range)", price)
            return False
        return True


class MockEnsembleStrategy:
    """Simple EMA crossover strategy returning BUY/SELL/HOLD."""

    def __init__(self, fast: int = 9, slow: int = 21) -> None:
        self._fast = fast
        self._slow = slow
        self._prices: List[float] = []

    def _ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema

    def on_tick(self, price: float) -> str:
        self._prices.append(price)
        if len(self._prices) < self._slow + 1:
            return "HOLD"
        fast_ema = self._ema(self._prices, self._fast)
        slow_ema = self._ema(self._prices, self._slow)
        prev_fast = self._ema(self._prices[:-1], self._fast)
        prev_slow = self._ema(self._prices[:-1], self._slow)

        if prev_fast <= prev_slow and fast_ema > slow_ema:
            return "BUY"
        if prev_fast >= prev_slow and fast_ema < slow_ema:
            return "SELL"
        return "HOLD"


@dataclass
class MockPosition:
    side: str  # "BUY" or "SELL"
    entry_price: float
    lots: float
    stop_loss: float
    take_profit: float
    opened_at: datetime = field(default_factory=_utcnow)


class MockOrderGateway:
    """Simulated order gateway with fill, slippage and position tracking."""

    SLIPPAGE_PIPS = 0.5  # simulated slippage

    def __init__(self, risk_manager: MockRiskManager) -> None:
        self._risk = risk_manager
        self._position: Optional[MockPosition] = None
        self._trades: List[Dict] = []

    @property
    def position(self) -> Optional[MockPosition]:
        return self._position

    def open(self, tick: MockTick, signal: str) -> bool:
        if self._position is not None:
            return False  # already in trade
        if not self._risk.check_trade_allowed():
            return False

        lots = self._risk.position_size(tick.mid)
        if lots <= 0:
            return False

        slippage = self.SLIPPAGE_PIPS * 0.01
        if signal == "BUY":
            entry = tick.ask + slippage
            stop = entry - 20 * 0.01
            tp = entry + 40 * 0.01
        else:
            entry = tick.bid - slippage
            stop = entry + 20 * 0.01
            tp = entry - 40 * 0.01

        self._position = MockPosition(
            side=signal, entry_price=entry, lots=lots, stop_loss=stop, take_profit=tp
        )
        logger.info(
            "OPEN %s @ %.3f (lots=%.2f, SL=%.3f, TP=%.3f)",
            signal,
            entry,
            lots,
            stop,
            tp,
        )
        return True

    def update(self, tick: MockTick) -> Optional[float]:
        """Check SL/TP; return realised PnL if closed."""
        if self._position is None:
            return None

        pos = self._position
        price = tick.bid if pos.side == "BUY" else tick.ask

        hit_sl = (pos.side == "BUY" and price <= pos.stop_loss) or (
            pos.side == "SELL" and price >= pos.stop_loss
        )
        hit_tp = (pos.side == "BUY" and price >= pos.take_profit) or (
            pos.side == "SELL" and price <= pos.take_profit
        )

        if hit_sl or hit_tp:
            reason = "TP" if hit_tp else "SL"
            if pos.side == "BUY":
                pnl = (price - pos.entry_price) * pos.lots * 100  # rough USD
            else:
                pnl = (pos.entry_price - price) * pos.lots * 100

            self._trades.append(
                {
                    "side": pos.side,
                    "entry": pos.entry_price,
                    "exit": price,
                    "lots": pos.lots,
                    "pnl": round(pnl, 2),
                    "reason": reason,
                    "duration_s": (
                        _utcnow() - pos.opened_at
                    ).total_seconds(),
                }
            )
            logger.info(
                "CLOSE [%s] %s: entry=%.3f exit=%.3f pnl=%.2f",
                reason,
                pos.side,
                pos.entry_price,
                price,
                pnl,
            )
            self._risk.record_pnl(pnl)
            self._position = None
            return pnl

        return None

    @property
    def trade_log(self) -> List[Dict]:
        return list(self._trades)


# ---------------------------------------------------------------------------
# Forward test harness
# ---------------------------------------------------------------------------

class ForwardTestHarness:
    """
    Orchestrates the forward-test simulation loop.

    Components wired together:
    - KillSwitch + HeartbeatMonitor (from kill_switch / heartbeat_monitor modules)
    - MockPriceFeed
    - MockRiskManager
    - MockEnsembleStrategy
    - MockOrderGateway
    """

    def __init__(self, ticks: int = 500, seed: Optional[int] = None) -> None:
        self._max_ticks = ticks
        self._tick_num = 0

        self._feed = MockPriceFeed(seed=seed)
        self._risk = MockRiskManager()
        self._strategy = MockEnsembleStrategy()
        self._gateway = MockOrderGateway(self._risk)

        # Optional safety modules (imported softly so forward_test.py can run
        # standalone even if the main package isn't fully installed)
        self._kill_switch = None
        self._heartbeat = None
        self._metrics: Dict = {
            "ticks_processed": 0,
            "signals_generated": 0,
            "trades_opened": 0,
            "trades_closed": 0,
            "total_pnl": 0.0,
            "invalid_ticks": 0,
            "kill_switch_activations": 0,
        }

    async def _setup_safety(self) -> None:
        try:
            from kill_switch import KillSwitch
            from heartbeat_monitor import HeartbeatMonitor

            self._kill_switch = KillSwitch(poll_interval_sec=1.0)
            await self._kill_switch.start()

            self._heartbeat = HeartbeatMonitor(
                check_interval_sec=5.0, kill_switch=self._kill_switch
            )
            self._heartbeat.register("price_feed", timeout_sec=10, critical=True)
            self._heartbeat.register("strategy", timeout_sec=15, critical=False)
            await self._heartbeat.start()
            logger.info("Safety modules loaded (KillSwitch + HeartbeatMonitor)")
        except ImportError as exc:
            logger.warning("Safety modules not available: %s – continuing without", exc)

    async def _teardown_safety(self) -> None:
        try:
            if self._heartbeat:
                await self._heartbeat.stop()
            if self._kill_switch:
                await self._kill_switch.stop()
        except Exception as exc:
            logger.warning("Error stopping safety modules: %s", exc)

    def _is_halted(self) -> bool:
        if self._kill_switch and self._kill_switch.is_active():
            return True
        return False

    async def run(self) -> Dict:
        logger.info("=" * 60)
        logger.info("HOPEFX FORWARD TEST — %d ticks", self._max_ticks)
        logger.info("=" * 60)

        await self._setup_safety()

        try:
            for _ in range(self._max_ticks):
                if self._is_halted():
                    logger.warning("HALTED by kill switch after %d ticks", self._tick_num)
                    self._metrics["kill_switch_activations"] += 1
                    break

                tick = self._feed.next_tick()
                self._tick_num += 1

                # --- Data validation ---
                if not self._risk.validate_price(tick.mid):
                    self._metrics["invalid_ticks"] += 1
                    continue

                # --- Heartbeat ---
                if self._heartbeat:
                    self._heartbeat.beat("price_feed")

                # --- Check existing position for SL/TP ---
                pnl = self._gateway.update(tick)
                if pnl is not None:
                    self._metrics["trades_closed"] += 1
                    self._metrics["total_pnl"] += pnl

                # --- Strategy signal ---
                signal = self._strategy.on_tick(tick.mid)
                if self._heartbeat:
                    self._heartbeat.beat("strategy")

                if signal in ("BUY", "SELL"):
                    self._metrics["signals_generated"] += 1
                    opened = self._gateway.open(tick, signal)
                    if opened:
                        self._metrics["trades_opened"] += 1

                self._metrics["ticks_processed"] += 1

                # Simulate ~10ms per tick
                await asyncio.sleep(0)  # yield to event loop

        except Exception as exc:
            logger.exception("CRASH during simulation: %s", exc)
            raise
        finally:
            await self._teardown_safety()

        self._print_results()
        return self._metrics

    def _print_results(self) -> None:
        trades = self._gateway.trade_log
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(trades) * 100 if trades else 0

        logger.info("=" * 60)
        logger.info("FORWARD TEST RESULTS")
        logger.info("=" * 60)
        logger.info("Ticks processed     : %d", self._metrics["ticks_processed"])
        logger.info("Invalid ticks        : %d", self._metrics["invalid_ticks"])
        logger.info("Signals generated    : %d", self._metrics["signals_generated"])
        logger.info("Trades opened        : %d", self._metrics["trades_opened"])
        logger.info("Trades closed        : %d", self._metrics["trades_closed"])
        logger.info("Win rate             : %.1f %%", win_rate)
        logger.info("Total PnL (USD)      : %.2f", self._metrics["total_pnl"])
        logger.info("Final balance (USD)  : %.2f", self._risk.balance)
        logger.info("Kill switch fires    : %d", self._metrics["kill_switch_activations"])
        logger.info("=" * 60)

        if trades:
            avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
            avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
            total_wins = sum(t["pnl"] for t in wins)
            total_losses = abs(sum(t["pnl"] for t in losses))
            logger.info("Avg win (USD)        : %.2f", avg_win)
            logger.info("Avg loss (USD)       : %.2f", avg_loss)
            profit_factor = total_wins / total_losses if total_losses > 0 else float("inf")
            logger.info("Profit factor        : %.2f", profit_factor)

        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HOPEFX Forward Test (mock data)")
    parser.add_argument("--ticks", type=int, default=500, help="Number of ticks to simulate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--mode", type=str, default="forward-test", help="Run mode label")
    return parser.parse_args()


async def _async_main() -> int:
    args = _parse_args()
    logger.info("Starting HOPEFX forward test (mode=%s, ticks=%d, seed=%s)",
                args.mode, args.ticks, args.seed)
    harness = ForwardTestHarness(ticks=args.ticks, seed=args.seed)
    try:
        await harness.run()
        logger.info("Forward test completed successfully")
        return 0
    except Exception as exc:
        logger.critical("Forward test FAILED: %s", exc)
        return 1


def main() -> None:
    sys.exit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
