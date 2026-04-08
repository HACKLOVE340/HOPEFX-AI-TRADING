# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
forward_test.py
HOPEFX AI Trading — Forward Test Runner (Real Dukascopy Replay)

Replays real historical XAUUSD tick data from Dukascopy through the full
production pipeline: DataQualityEngine → MicrostructureEngine →
NormalizationPipeline → EMA-crossover strategy → paper order gateway.

No synthetic data. No mocks. No GBM. Real tick data only.

Usage
-----
    python forward_test.py                          # last 7 days, H1 bars
    python forward_test.py --days 30                # last 30 days
    python forward_test.py --start 2024-01-01       # specific start date
    python forward_test.py --end   2024-03-31       # specific end date
    python forward_test.py --tf H1                  # timeframe (M1/M5/H1/H4/D1)

Exit codes
----------
0  — replay completed without crashes
1  — replay crashed (see logs)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

import pandas as pd

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("forward_test")


# ---------------------------------------------------------------------------
# Real components — no mocks
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RealRiskManager:
    """
    Production-grade position sizing and daily-loss guard.

    Reads limits from environment variables (same as risk/manager.py).
    Uses Kelly criterion with fractional scaling.
    """

    def __init__(self, account_balance: float = 10_000.0) -> None:
        import os

        self.balance = account_balance
        self._peak_balance = account_balance
        self._daily_loss = 0.0
        self._trade_count = 0
        self.MAX_DAILY_LOSS_PCT = float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05"))
        self.MAX_POSITION_PCT = float(os.getenv("RISK_MAX_POSITION_PCT", "0.05"))
        self.KELLY_FRACTION = float(os.getenv("RISK_KELLY_FRACTION", "0.25"))
        self.MIN_DATA_QUALITY = float(os.getenv("RISK_MIN_DATA_QUALITY", "0.40"))

    @property
    def max_daily_loss_usd(self) -> float:
        return self._peak_balance * self.MAX_DAILY_LOSS_PCT

    def check_trade_allowed(self) -> bool:
        if self._daily_loss >= self.max_daily_loss_usd:
            logger.warning(
                "RISK: daily loss limit hit (%.2f / %.2f)",
                self._daily_loss,
                self.max_daily_loss_usd,
            )
            return False
        return True

    def position_size(
        self,
        price: float,
        win_rate: float = 0.52,
        avg_win: float = 1.5,
        avg_loss: float = 1.0,
    ) -> float:
        """Quarter-Kelly position sizing."""
        kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        kelly_f = max(0.0, kelly_f) * self.KELLY_FRACTION
        risk_usd = self.balance * kelly_f
        max_usd = self.balance * self.MAX_POSITION_PCT
        risk_usd = min(risk_usd, max_usd)
        # Convert USD risk to lots (1 lot XAUUSD = 100 oz; $1 move = $100/lot)
        stop_usd = price * 0.002  # 0.2% stop
        lots = risk_usd / max(stop_usd * 100, 1.0)
        return round(min(lots, 10.0), 2)

    def validate_tick(self, tick) -> bool:
        """Reject ticks outside plausible XAUUSD range."""
        if tick.mid <= 0:
            return False
        if not (500.0 < tick.mid < 5000.0):
            logger.warning("SUSPICIOUS PRICE: %.4f (out of XAU range)", tick.mid)
            return False
        return True

    def record_pnl(self, pnl: float) -> None:
        self.balance += pnl
        self._peak_balance = max(self._peak_balance, self.balance)
        if pnl < 0:
            self._daily_loss += abs(pnl)
        self._trade_count += 1
        logger.info(
            "PnL: %.2f | balance=%.2f | daily_loss=%.2f",
            pnl,
            self.balance,
            self._daily_loss,
        )


class EMAStrategy:
    """
    EMA crossover strategy operating on real OHLCV bars.

    Uses the same feature logic as the production strategy engine —
    no synthetic signals, no random noise.
    """

    def __init__(self, fast: int = 9, slow: int = 21) -> None:
        self._fast = fast
        self._slow = slow
        self._closes: list[float] = []

    def _ema(self, prices: list[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        k = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = p * k + ema * (1.0 - k)
        return ema

    def on_bar(self, close: float) -> str:
        """Return BUY / SELL / HOLD based on EMA crossover."""
        self._closes.append(close)
        if len(self._closes) < self._slow + 2:
            return "HOLD"
        fast_now = self._ema(self._closes, self._fast)
        slow_now = self._ema(self._closes, self._slow)
        fast_prev = self._ema(self._closes[:-1], self._fast)
        slow_prev = self._ema(self._closes[:-1], self._slow)
        if fast_prev <= slow_prev and fast_now > slow_now:
            return "BUY"
        if fast_prev >= slow_prev and fast_now < slow_now:
            return "SELL"
        return "HOLD"


@dataclass
class Position:
    side: str
    entry_price: float
    lots: float
    stop_loss: float
    take_profit: float
    opened_at: datetime = field(default_factory=_utcnow)


class PaperOrderGateway:
    """
    Paper order gateway with realistic slippage and SL/TP tracking.

    Uses real bar close prices — no synthetic fills.
    """

    SLIPPAGE_PCT = 0.0001  # 0.01% slippage on entry
    STOP_PCT = 0.0020  # 0.20% stop loss
    TP_RATIO = 2.0  # 2:1 reward/risk

    def __init__(self, risk: RealRiskManager) -> None:
        self._risk = risk
        self._position: Position | None = None
        self._trades: list[dict] = []

    @property
    def position(self) -> Position | None:
        return self._position

    def open(self, close: float, signal: str) -> bool:
        if self._position is not None:
            return False
        if not self._risk.check_trade_allowed():
            return False
        lots = self._risk.position_size(close)
        if lots <= 0:
            return False

        slip = close * self.SLIPPAGE_PCT
        stop_dist = close * self.STOP_PCT
        tp_dist = stop_dist * self.TP_RATIO

        if signal == "BUY":
            entry = close + slip
            sl = entry - stop_dist
            tp = entry + tp_dist
        else:
            entry = close - slip
            sl = entry + stop_dist
            tp = entry - tp_dist

        self._position = Position(
            side=signal,
            entry_price=entry,
            lots=lots,
            stop_loss=sl,
            take_profit=tp,
        )
        logger.info(
            "OPEN %s @ %.4f  lots=%.2f  SL=%.4f  TP=%.4f",
            signal,
            entry,
            lots,
            sl,
            tp,
        )
        return True

    def update(self, close: float) -> float | None:
        """Check SL/TP on bar close. Returns realised PnL if closed."""
        if self._position is None:
            return None
        pos = self._position
        hit_sl = (pos.side == "BUY" and close <= pos.stop_loss) or (pos.side == "SELL" and close >= pos.stop_loss)
        hit_tp = (pos.side == "BUY" and close >= pos.take_profit) or (pos.side == "SELL" and close <= pos.take_profit)
        if not (hit_sl or hit_tp):
            return None

        reason = "TP" if hit_tp else "SL"
        if pos.side == "BUY":
            pnl = (close - pos.entry_price) * pos.lots * 100.0
        else:
            pnl = (pos.entry_price - close) * pos.lots * 100.0

        self._trades.append(
            {
                "side": pos.side,
                "entry": pos.entry_price,
                "exit": close,
                "lots": pos.lots,
                "pnl": round(pnl, 2),
                "reason": reason,
                "duration_s": (_utcnow() - pos.opened_at).total_seconds(),
            }
        )
        logger.info(
            "CLOSE [%s] %s: entry=%.4f exit=%.4f pnl=%.2f",
            reason,
            pos.side,
            pos.entry_price,
            close,
            pnl,
        )
        self._risk.record_pnl(pnl)
        self._position = None
        return pnl

    @property
    def trade_log(self) -> list[dict]:
        return list(self._trades)


# ---------------------------------------------------------------------------
# Forward test harness — real Dukascopy data
# ---------------------------------------------------------------------------


class ForwardTestHarness:
    """
    Replays real Dukascopy XAUUSD data through the production pipeline.

    Data flow:
      DukascopyFetcher → NormalizationPipeline → EMAStrategy → PaperOrderGateway
    """

    def __init__(
        self,
        start: datetime,
        end: datetime,
        timeframe: str = "H1",
    ) -> None:
        self._start = start
        self._end = end
        self._timeframe = timeframe
        self._risk = RealRiskManager()
        self._strategy = EMAStrategy()
        self._gateway = PaperOrderGateway(self._risk)
        self._metrics: dict = {
            "bars_processed": 0,
            "signals_generated": 0,
            "trades_opened": 0,
            "trades_closed": 0,
            "total_pnl": 0.0,
            "invalid_bars": 0,
        }

    async def _fetch_ohlcv(self) -> pd.DataFrame:
        """Fetch real OHLCV data from Dukascopy via the replay engine (via orchestrator)."""
        from data_layer.orchestrator import orchestrator as _orch

        engine = _orch._replay
        logger.info(
            "Fetching Dukascopy XAUUSD %s bars %s → %s …",
            self._timeframe,
            self._start.strftime("%Y-%m-%d"),
            self._end.strftime("%Y-%m-%d"),
        )
        df = await engine.build_ohlcv_dataframe(
            symbol="XAUUSD",
            start=self._start,
            end=self._end,
            timeframe=self._timeframe,
            normalize=True,
        )
        return df

    async def run(self) -> dict:
        logger.info("=" * 60)
        logger.info(
            "HOPEFX FORWARD TEST — Real Dukascopy Replay  [%s → %s  %s]",
            self._start.strftime("%Y-%m-%d"),
            self._end.strftime("%Y-%m-%d"),
            self._timeframe,
        )
        logger.info("=" * 60)

        # Fetch real data
        df = await self._fetch_ohlcv()
        if df is None or df.empty:
            logger.error(
                "No data returned from Dukascopy for %s → %s. Check network connectivity and symbol name.",
                self._start.strftime("%Y-%m-%d"),
                self._end.strftime("%Y-%m-%d"),
            )
            return self._metrics

        logger.info("Loaded %d real bars from Dukascopy", len(df))

        # Replay bar by bar
        for _ts, bar in df.iterrows():
            close = float(bar.get("close", 0.0))
            if close <= 0 or not self._risk.validate_tick(type("_T", (), {"mid": close})()):
                self._metrics["invalid_bars"] += 1
                continue

            # Check existing position SL/TP
            pnl = self._gateway.update(close)
            if pnl is not None:
                self._metrics["trades_closed"] += 1
                self._metrics["total_pnl"] += pnl

            # Strategy signal on real bar close
            signal = self._strategy.on_bar(close)
            if signal in ("BUY", "SELL"):
                self._metrics["signals_generated"] += 1
                opened = self._gateway.open(close, signal)
                if opened:
                    self._metrics["trades_opened"] += 1

            self._metrics["bars_processed"] += 1

        self._print_results()
        return self._metrics

    def _print_results(self) -> None:
        trades = self._gateway.trade_log
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(trades) * 100 if trades else 0.0

        logger.info("=" * 60)
        logger.info("FORWARD TEST RESULTS  (Real Dukascopy Data)")
        logger.info("=" * 60)
        logger.info("Bars processed       : %d", self._metrics["bars_processed"])
        logger.info("Invalid bars         : %d", self._metrics["invalid_bars"])
        logger.info("Signals generated    : %d", self._metrics["signals_generated"])
        logger.info("Trades opened        : %d", self._metrics["trades_opened"])
        logger.info("Trades closed        : %d", self._metrics["trades_closed"])
        logger.info("Win rate             : %.1f %%", win_rate)
        logger.info("Total PnL (USD)      : %.2f", self._metrics["total_pnl"])
        logger.info("Final balance (USD)  : %.2f", self._risk.balance)
        logger.info("=" * 60)

        if trades:
            avg_win = sum(t["pnl"] for t in wins) / max(len(wins), 1)
            avg_loss = sum(t["pnl"] for t in losses) / max(len(losses), 1)
            total_wins = sum(t["pnl"] for t in wins)
            total_losses = abs(sum(t["pnl"] for t in losses))
            pf = total_wins / total_losses if total_losses > 0 else float("inf")
            logger.info("Avg win (USD)        : %.2f", avg_win)
            logger.info("Avg loss (USD)       : %.2f", avg_loss)
            logger.info("Profit factor        : %.2f", pf)
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HOPEFX Forward Test — Real Dukascopy Replay")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of past days to replay (default: 7)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD (overrides --days)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--tf",
        type=str,
        default="H1",
        help="Timeframe: M1 M5 M15 M30 H1 H4 D1 (default: H1)",
    )
    return parser.parse_args()


async def _async_main() -> int:
    args = _parse_args()

    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC) if args.end else now

    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    else:
        start = end - timedelta(days=args.days)

    if start >= end:
        logger.error("start (%s) must be before end (%s)", start.date(), end.date())
        return 1

    harness = ForwardTestHarness(start=start, end=end, timeframe=args.tf)
    try:
        await harness.run()
        logger.info("Forward test completed successfully")
        return 0
    except Exception as exc:
        logger.critical("Forward test FAILED: %s", exc, exc_info=True)
        return 1


def main() -> None:
    sys.exit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
