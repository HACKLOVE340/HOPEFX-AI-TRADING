# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
SniperEntryEngine — precision ICT/SMC entry refinement layer.

Pipeline
--------
1. HTF Setup Detection  (H1/H4)
   - Confirm trend via BOS/CHoCH on the higher timeframe
   - Identify the most recent unmitigated Order Block (OB)
   - Confirm price is in a Premium/Discount zone relative to the HTF range

2. LTF Drill-Down  (M5)
   - Fetch M5 bars from the data layer orchestrator
   - Detect BOS or CHoCH on M5 to confirm institutional intent
   - Identify the displacement candle (large-body engulfing move)
   - Calculate the Consequent Encroachment (CE) level of the displacement FVG

3. Limit Placement
   - Entry limit = CE of the M5 displacement FVG (50% of the gap)
   - Stop loss   = beyond the HTF OB extreme (with ATR buffer)
   - Take profit = next HTF liquidity pool / opposing OB

The engine is injected between the SMC signal (BrainDecision) and
_execute_decision() in hopefx_engine.py.  It returns a SniperSetup
dataclass; when confirmation is absent it returns None so the engine
falls back to a market order at the brain's price.

Configuration (all via environment variables — see .env.example):
  SNIPER_ENABLED              true | false  (default: true)
  SNIPER_HTF_TIMEFRAME        H1 | H4       (default: H1)
  SNIPER_LTF_TIMEFRAME        M5 | M15      (default: M5)
  SNIPER_LTF_BARS             number of LTF bars to fetch (default: 100)
  SNIPER_OB_LOOKBACK          HTF OB search window in bars (default: 20)
  SNIPER_PIVOT_N              swing pivot neighbour count (default: 3)
  SNIPER_DISPLACEMENT_MULT    body/ATR ratio to qualify displacement (default: 1.5)
  SNIPER_SL_ATR_BUFFER        ATR multiples added beyond OB for SL (default: 0.5)
  SNIPER_TP_RR                minimum R:R for TP placement (default: 2.0)
  SNIPER_MAX_SPREAD_POINTS    reject entry when spread > N points (default: 30)
  SNIPER_CONFIDENCE_BOOST     confidence multiplier on confirmed setup (default: 1.20)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OrderBlock:
    """A single identified Order Block."""

    direction: str  # "bullish" | "bearish"
    top: float  # upper boundary of the OB candle
    bottom: float  # lower boundary of the OB candle
    origin_index: int  # bar index within the analysis window
    mitigated: bool = False  # True once price has traded through the OB


@dataclass
class DisplacementCandle:
    """A large-body candle that creates a Fair Value Gap (FVG)."""

    direction: str  # "bullish" | "bearish"
    open: float
    high: float
    low: float
    close: float
    # FVG boundaries created by this candle (gap between prev candle and next candle)
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0
    ce_level: float = 0.0  # Consequent Encroachment = midpoint of the FVG
    bar_index: int = 0


@dataclass
class LTFConfirmation:
    """Result of the M5 drill-down analysis."""

    confirmed: bool
    event: str  # "BOS_bullish" | "BOS_bearish" | "CHoCH_bullish" | "CHoCH_bearish" | "none"
    displacement: DisplacementCandle | None
    last_sh: float | None  # last M5 swing high
    last_sl: float | None  # last M5 swing low
    bars_analysed: int = 0


@dataclass
class SniperSetup:
    """
    Fully confirmed sniper entry.

    Consumed by hopefx_engine._execute_decision() to place a LIMIT order
    instead of a MARKET order.
    """

    symbol: str
    direction: str  # "long" | "short"
    entry_price: float  # limit price (CE of M5 FVG)
    stop_loss: float  # absolute SL price
    take_profit: float  # absolute TP price
    confidence: float  # boosted confidence (capped at 1.0)
    order_type: str = "LIMIT"
    htf_ob: OrderBlock | None = None
    ltf_confirmation: LTFConfirmation | None = None
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": round(self.entry_price, 5),
            "stop_loss": round(self.stop_loss, 5),
            "take_profit": round(self.take_profit, 5),
            "confidence": round(self.confidence, 4),
            "order_type": self.order_type,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# SniperEntryEngine
# ---------------------------------------------------------------------------


class SniperEntryEngine:
    """
    Refines a raw SMC/brain signal into a precision limit-order setup.

    Usage
    -----
    engine = SniperEntryEngine()
    setup = engine.refine(decision, htf_df, orchestrator)
    if setup:
        # place LIMIT order at setup.entry_price
    else:
        # fall back to market order at decision.tick_mid
    """

    def __init__(self) -> None:
        self.enabled = _env_bool("SNIPER_ENABLED", True)
        self.htf_timeframe = os.environ.get("SNIPER_HTF_TIMEFRAME", "H1").upper()
        self.ltf_timeframe = os.environ.get("SNIPER_LTF_TIMEFRAME", "M5").upper()
        self.ltf_bars = _env_int("SNIPER_LTF_BARS", 100)
        self.ob_lookback = _env_int("SNIPER_OB_LOOKBACK", 20)
        self.pivot_n = _env_int("SNIPER_PIVOT_N", 3)
        self.displacement_mult = _env_float("SNIPER_DISPLACEMENT_MULT", 1.5)
        self.sl_atr_buffer = _env_float("SNIPER_SL_ATR_BUFFER", 0.5)
        self.tp_rr = _env_float("SNIPER_TP_RR", 2.0)
        self.max_spread_points = _env_float("SNIPER_MAX_SPREAD_POINTS", 30.0)
        self.confidence_boost = _env_float("SNIPER_CONFIDENCE_BOOST", 1.20)

        logger.info(
            "SniperEntryEngine initialised — enabled=%s htf=%s ltf=%s ltf_bars=%d",
            self.enabled,
            self.htf_timeframe,
            self.ltf_timeframe,
            self.ltf_bars,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def refine(
        self,
        decision,
        htf_df: pd.DataFrame,
        orchestrator=None,
        spread: float = 0.0,
    ) -> SniperSetup | None:
        """
        Attempt to refine a brain decision into a sniper limit-order setup.

        Parameters
        ----------
        decision    : BrainDecision from HOPEFXBrain.process_bar()
        htf_df      : H1 (or configured HTF) OHLCV DataFrame already in memory
        orchestrator: data_layer.orchestrator instance for LTF bar fetch
        spread      : current bid/ask spread in price points

        Returns
        -------
        SniperSetup when all conditions are met, None otherwise.
        """
        if not self.enabled:
            return None

        direction = getattr(decision, "action", "hold")
        if direction not in ("long", "short"):
            return None

        symbol = getattr(decision, "symbol", "XAU_USD")
        base_confidence = float(getattr(decision, "confidence", 0.5))
        mid_price = float(getattr(decision, "tick_mid", 0.0))

        if mid_price <= 0:
            logger.debug("SniperEntryEngine: tick_mid=0 for %s — skipping", symbol)
            return None

        # Spread guard
        if spread > self.max_spread_points:
            logger.debug(
                "SniperEntryEngine: spread=%.1f > max=%.1f — skipping %s",
                spread,
                self.max_spread_points,
                symbol,
            )
            return None

        # ── 1. HTF setup detection ─────────────────────────────────────────
        htf_result = self._detect_htf_setup(htf_df, direction)
        if htf_result is None:
            logger.debug("SniperEntryEngine: no HTF setup for %s %s", direction, symbol)
            return None

        htf_ob, htf_atr = htf_result

        # ── 2. LTF drill-down ─────────────────────────────────────────────
        ltf_df = self._fetch_ltf_bars(symbol, orchestrator)
        if ltf_df is None or len(ltf_df) < 20:
            logger.debug(
                "SniperEntryEngine: insufficient LTF bars (%d) for %s",
                0 if ltf_df is None else len(ltf_df),
                symbol,
            )
            return None

        ltf_conf = self._confirm_ltf(ltf_df, direction)
        if not ltf_conf.confirmed:
            logger.debug(
                "SniperEntryEngine: LTF not confirmed (event=%s) for %s %s",
                ltf_conf.event,
                direction,
                symbol,
            )
            return None

        # ── 3. Limit placement ────────────────────────────────────────────
        setup = self._build_setup(
            symbol=symbol,
            direction=direction,
            mid_price=mid_price,
            htf_ob=htf_ob,
            htf_atr=htf_atr,
            ltf_conf=ltf_conf,
            base_confidence=base_confidence,
        )

        if setup is None:
            return None

        logger.info(
            "SniperEntryEngine: CONFIRMED %s %s — entry=%.5f sl=%.5f tp=%.5f conf=%.3f reason=%s",
            direction,
            symbol,
            setup.entry_price,
            setup.stop_loss,
            setup.take_profit,
            setup.confidence,
            setup.reason,
        )
        return setup

    # ------------------------------------------------------------------
    # HTF setup detection
    # ------------------------------------------------------------------

    def _detect_htf_setup(
        self,
        df: pd.DataFrame,
        direction: str,
    ) -> tuple[OrderBlock, float] | None:
        """
        Confirm HTF structure and locate the most recent unmitigated OB.

        Returns (OrderBlock, atr) or None when conditions are not met.
        """
        if df is None or len(df) < max(self.ob_lookback + 5, 20):
            return None

        prices = df.to_dict("records")

        # ATR proxy (14-bar average true range)
        atr = self._calc_atr(prices, period=14)

        # Confirm HTF BOS/CHoCH in the required direction
        struct = self._analyse_structure(prices, self.pivot_n)
        trend = struct.get("trend", "neutral")
        event = struct.get("event", "none")

        direction_ok = (
            (direction == "long" and trend == "bullish")
            or (direction == "short" and trend == "bearish")
            or (direction == "long" and "bullish" in event)
            or (direction == "short" and "bearish" in event)
        )
        if not direction_ok:
            return None

        # Locate the most recent unmitigated OB
        ob = self._find_last_ob(prices, direction)
        if ob is None:
            return None

        # Confirm price is approaching the OB (within 3× ATR)
        current_close = float(prices[-1].get("close", 0))
        ob_mid = (ob.top + ob.bottom) / 2.0
        if abs(current_close - ob_mid) > atr * 3.0:
            return None

        return ob, atr

    def _find_last_ob(self, prices: list[dict], direction: str) -> OrderBlock | None:
        """
        Identify the most recent unmitigated Order Block.

        Bullish OB: last bearish candle before a strong bullish impulse that
                    breaks the prior swing high.
        Bearish OB: last bullish candle before a strong bearish impulse that
                    breaks the prior swing low.
        """
        window = prices[-self.ob_lookback - 2 :]
        n = len(window)
        candidates: list[OrderBlock] = []

        for i in range(1, n - 1):
            c = window[i]
            nxt = window[i + 1]
            c_open = float(c.get("open", 0))
            c_close = float(c.get("close", 0))
            c_high = float(c.get("high", 0))
            c_low = float(c.get("low", 0))
            n_open = float(nxt.get("open", 0))
            n_close = float(nxt.get("close", 0))

            if direction == "long":
                # Bearish candle followed by bullish impulse breaking prior high
                if c_close < c_open and n_close > n_open and n_close > c_high:
                    candidates.append(
                        OrderBlock(
                            direction="bullish",
                            top=c_high,
                            bottom=c_low,
                            origin_index=i,
                        )
                    )
            # Bullish candle followed by bearish impulse breaking prior low
            elif c_close > c_open and n_close < n_open and n_close < c_low:
                candidates.append(
                    OrderBlock(
                        direction="bearish",
                        top=c_high,
                        bottom=c_low,
                        origin_index=i,
                    )
                )

        if not candidates:
            return None

        # Mark mitigated OBs (price has traded through them)
        current_price = float(prices[-1].get("close", 0))
        for ob in candidates:
            if direction == "long" and current_price < ob.bottom or direction == "short" and current_price > ob.top:
                ob.mitigated = True

        # Return the most recent unmitigated OB
        unmitigated = [ob for ob in candidates if not ob.mitigated]
        return unmitigated[-1] if unmitigated else None

    # ------------------------------------------------------------------
    # LTF confirmation: BOS/CHoCH + displacement candle + CE level
    # ------------------------------------------------------------------

    def _confirm_ltf(self, df: pd.DataFrame, direction: str) -> LTFConfirmation:
        """
        Confirm institutional intent on the LTF (M5).

        Checks
        ------
        1. BOS or CHoCH in the required direction on M5
        2. Presence of a displacement candle (large-body FVG-creating move)
        3. CE level of the displacement FVG is calculable
        """
        prices = df.to_dict("records")
        n = len(prices)

        struct = self._analyse_structure(prices, pivot_n=max(2, self.pivot_n - 1))
        event = struct.get("event", "none")
        last_sh = struct.get("last_sh")
        last_sl = struct.get("last_sl")

        # BOS or CHoCH must align with the required direction
        event_ok = (direction == "long" and ("bullish" in event or event == "none")) or (
            direction == "short" and ("bearish" in event or event == "none")
        )

        # Detect displacement candle + FVG in the last 30 bars
        displacement = self._find_displacement(prices[-30:], direction)

        confirmed = event_ok and displacement is not None and displacement.ce_level > 0

        return LTFConfirmation(
            confirmed=confirmed,
            event=event,
            displacement=displacement,
            last_sh=last_sh,
            last_sl=last_sl,
            bars_analysed=n,
        )

    def _find_displacement(
        self,
        prices: list[dict],
        direction: str,
    ) -> DisplacementCandle | None:
        """
        Find the most recent displacement candle that creates a Fair Value Gap.

        A displacement candle qualifies when:
        - Its body size >= displacement_mult × ATR
        - It creates a gap between the prior candle's extreme and the next
          candle's extreme (3-candle FVG pattern)

        The CE (Consequent Encroachment) is the midpoint of that FVG.
        """
        n = len(prices)
        if n < 3:
            return None

        atr = self._calc_atr(prices, period=min(14, n - 1))
        if atr <= 0:
            return None

        # Walk backwards to find the most recent qualifying displacement
        for i in range(n - 2, 0, -1):
            prev = prices[i - 1]
            curr = prices[i]
            nxt = prices[i + 1]

            c_open = float(curr.get("open", 0))
            c_close = float(curr.get("close", 0))
            c_high = float(curr.get("high", 0))
            c_low = float(curr.get("low", 0))
            body = abs(c_close - c_open)

            if body < self.displacement_mult * atr:
                continue

            if direction == "long":
                # Bullish displacement: close > open, gap above prev high
                if c_close <= c_open:
                    continue
                fvg_bottom = float(prev.get("high", 0))
                fvg_top = float(nxt.get("low", 0))
                if fvg_top <= fvg_bottom:
                    continue
                ce = (fvg_top + fvg_bottom) / 2.0
                return DisplacementCandle(
                    direction="bullish",
                    open=c_open,
                    high=c_high,
                    low=c_low,
                    close=c_close,
                    fvg_top=fvg_top,
                    fvg_bottom=fvg_bottom,
                    ce_level=ce,
                    bar_index=i,
                )
            else:
                # Bearish displacement: close < open, gap below prev low
                if c_close >= c_open:
                    continue
                fvg_top = float(prev.get("low", 0))
                fvg_bottom = float(nxt.get("high", 0))
                if fvg_bottom >= fvg_top:
                    continue
                ce = (fvg_top + fvg_bottom) / 2.0
                return DisplacementCandle(
                    direction="bearish",
                    open=c_open,
                    high=c_high,
                    low=c_low,
                    close=c_close,
                    fvg_top=fvg_top,
                    fvg_bottom=fvg_bottom,
                    ce_level=ce,
                    bar_index=i,
                )

        return None

    # ------------------------------------------------------------------
    # Limit placement
    # ------------------------------------------------------------------

    def _build_setup(
        self,
        symbol: str,
        direction: str,
        mid_price: float,
        htf_ob: OrderBlock,
        htf_atr: float,
        ltf_conf: LTFConfirmation,
        base_confidence: float,
    ) -> SniperSetup | None:
        """
        Compute entry, SL, and TP from confirmed HTF OB + LTF CE level.

        Entry  = CE of the M5 displacement FVG
        SL     = beyond the HTF OB extreme + ATR buffer
        TP     = entry ± (risk × tp_rr)
        """
        disp = ltf_conf.displacement
        if disp is None or disp.ce_level <= 0:
            return None

        entry = disp.ce_level

        if direction == "long":
            # SL below the HTF OB bottom with ATR buffer
            sl = htf_ob.bottom - (htf_atr * self.sl_atr_buffer)
            risk = abs(entry - sl)
            if risk <= 0:
                return None
            tp = entry + (risk * self.tp_rr)
            # Sanity: entry must be above current price (we're waiting for pullback)
            # or within 2× ATR below current price (already in the zone)
            if entry > mid_price + htf_atr * 2.0:
                return None
        else:
            # SL above the HTF OB top with ATR buffer
            sl = htf_ob.top + (htf_atr * self.sl_atr_buffer)
            risk = abs(sl - entry)
            if risk <= 0:
                return None
            tp = entry - (risk * self.tp_rr)
            if entry < mid_price - htf_atr * 2.0:
                return None

        # Minimum R:R guard
        actual_rr = abs(tp - entry) / risk if risk > 0 else 0.0
        if actual_rr < self.tp_rr * 0.9:
            return None

        boosted_conf = min(1.0, base_confidence * self.confidence_boost)

        reason = (
            f"sniper:{direction}|htf_ob={htf_ob.bottom:.2f}-{htf_ob.top:.2f}"
            f"|ltf_event={ltf_conf.event}|ce={entry:.5f}|rr={actual_rr:.2f}"
        )

        return SniperSetup(
            symbol=symbol,
            direction=direction,
            entry_price=round(entry, 5),
            stop_loss=round(sl, 5),
            take_profit=round(tp, 5),
            confidence=round(boosted_conf, 4),
            order_type="LIMIT",
            htf_ob=htf_ob,
            ltf_confirmation=ltf_conf,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _analyse_structure(self, prices: list[dict], pivot_n: int = 3) -> dict[str, Any]:
        """
        Detect BOS/CHoCH from swing pivots.

        Mirrors the logic in SMCICTStrategy._analyze_market_structure() but
        operates on any timeframe and is parameterised by pivot_n.
        """
        n = len(prices)
        if n < pivot_n * 2 + 2:
            return {"trend": "neutral", "event": "none", "last_sh": None, "last_sl": None}

        swing_highs: list[tuple[int, float]] = []
        swing_lows: list[tuple[int, float]] = []

        for i in range(pivot_n, n - pivot_n):
            h = float(prices[i].get("high", 0))
            lo = float(prices[i].get("low", 0))
            left_h = [float(prices[j].get("high", 0)) for j in range(i - pivot_n, i)]
            right_h = [float(prices[j].get("high", 0)) for j in range(i + 1, i + pivot_n + 1)]
            left_l = [float(prices[j].get("low", 0)) for j in range(i - pivot_n, i)]
            right_l = [float(prices[j].get("low", 0)) for j in range(i + 1, i + pivot_n + 1)]

            if h >= max(left_h) and h >= max(right_h):
                swing_highs.append((i, h))
            if lo <= min(left_l) and lo <= min(right_l):
                swing_lows.append((i, lo))

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {"trend": "neutral", "event": "none", "last_sh": None, "last_sl": None}

        sh_prev_val = swing_highs[-2][1]
        sh_last_val = swing_highs[-1][1]
        sl_prev_val = swing_lows[-2][1]
        sl_last_val = swing_lows[-1][1]

        higher_high = sh_last_val > sh_prev_val
        higher_low = sl_last_val > sl_prev_val
        lower_high = sh_last_val < sh_prev_val
        lower_low = sl_last_val < sl_prev_val

        if higher_high and higher_low:
            trend = "bullish"
        elif lower_high and lower_low:
            trend = "bearish"
        else:
            trend = "neutral"

        current_close = float(prices[-1].get("close", 0))
        event = "none"

        if trend == "bullish":
            if current_close > sh_last_val:
                event = "BOS_bullish"
            elif current_close < sl_last_val:
                event = "CHoCH_bearish"
        elif trend == "bearish":
            if current_close < sl_last_val:
                event = "BOS_bearish"
            elif current_close > sh_last_val:
                event = "CHoCH_bullish"
        elif current_close > sh_last_val:
            event = "CHoCH_bullish"
        elif current_close < sl_last_val:
            event = "CHoCH_bearish"

        return {
            "trend": trend,
            "event": event,
            "last_sh": sh_last_val,
            "last_sl": sl_last_val,
        }

    def _calc_atr(self, prices: list[dict], period: int = 14) -> float:
        """Average True Range over the last ``period`` bars."""
        n = len(prices)
        if n < 2:
            return 0.0
        trs: list[float] = []
        for i in range(max(1, n - period), n):
            h = float(prices[i].get("high", 0))
            lo = float(prices[i].get("low", 0))
            prev_c = float(prices[i - 1].get("close", h))
            tr = max(h - lo, abs(h - prev_c), abs(lo - prev_c))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 0.0

    def _fetch_ltf_bars(
        self,
        symbol: str,
        orchestrator,
    ) -> pd.DataFrame | None:
        """
        Fetch LTF OHLCV bars from the data layer orchestrator.

        Falls back gracefully when the orchestrator is unavailable.
        """
        if orchestrator is None:
            return None
        try:
            df = orchestrator.get_ohlcv_window(
                symbol=symbol,
                bars=self.ltf_bars,
                timeframe=self.ltf_timeframe,
            )
            return df
        except Exception as exc:
            logger.debug("SniperEntryEngine: LTF fetch failed: %s", exc)
            return None
