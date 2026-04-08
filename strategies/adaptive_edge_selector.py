# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
AdaptiveEdgeSelector — HOPEFX Ultimate Adaptive Edge Selector.

Analyses live market indicators, detects the current regime, and selects
ONE edge that is optimal for this exact moment.  Returns a clean
EdgeDecision dataclass (JSON-serialisable) that the brain uses to override
its default strategy routing.

Four edges
----------
sniper       One-shot precision entry.  Requires trending regime, cone ≥ 0.7,
             ADX ≥ 25, confidence ≥ 80 %.  Uses tight SL/TP derived from ATR.
scalper      Fast mean-reversion.  Requires ranging/low-vol regime, RSI at
             extremes or MA cross, confidence ≥ 80 %.
grid         Hedge-layer recovery.  Only when volatile + cone ≥ 0.7.  Max 4
             layers, breakeven basket at +20 pips, cooldown when DD > 5 %.
skip         No trade — wait for a better setup.  Default when no edge
             qualifies or confidence < 80 %.

Regime detection (from raw indicators, no OHLCV required)
----------------------------------------------------------
trending_up / trending_down   ADX ≥ 25 + volume_delta positive/negative
ranging                       ADX < 20 + low ATR relative to price
volatile                      ADX ≥ 20 + high ATR or volume spike
choppy                        ADX < 15 + conflicting signals
low_vol                       ATR below quiet threshold

Configuration (env vars — see .env.example)
-------------------------------------------
EDGE_SELECTOR_ENABLED           true | false          (default: true)
EDGE_SELECTOR_MIN_CONFIDENCE    minimum confidence %  (default: 80)
EDGE_SELECTOR_CONE_THRESHOLD    cone score floor      (default: 0.70)
EDGE_SELECTOR_ADX_TREND         ADX floor for trend   (default: 25.0)
EDGE_SELECTOR_ADX_CHOPPY        ADX ceiling for choppy (default: 15.0)
EDGE_SELECTOR_RSI_OB            RSI overbought level  (default: 70)
EDGE_SELECTOR_RSI_OS            RSI oversold level    (default: 30)
EDGE_SELECTOR_ATR_SL_MULT       ATR multiplier for SL (default: 2.0)
EDGE_SELECTOR_ATR_TP_MULT       ATR multiplier for TP (default: 4.0)
EDGE_SELECTOR_MAX_LOT           maximum lot size      (default: 0.01)
EDGE_SELECTOR_GRID_MAX_LAYERS   max grid layers       (default: 4)
EDGE_SELECTOR_GRID_BE_PIPS      grid breakeven pips   (default: 20)
EDGE_SELECTOR_GRID_DD_COOLDOWN  drawdown % for cooldown (default: 5.0)
"""

from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Edge names
# ---------------------------------------------------------------------------

EDGE_SNIPER = "sniper"
EDGE_SCALPER = "scalper"
EDGE_GRID = "grid"
EDGE_SKIP = "skip"

# Regime labels
REGIME_TRENDING_UP = "trending_up"
REGIME_TRENDING_DOWN = "trending_down"
REGIME_RANGING = "ranging"
REGIME_VOLATILE = "volatile"
REGIME_CHOPPY = "choppy"
REGIME_LOW_VOL = "low_vol"
REGIME_UNKNOWN = "unknown"

# News proximity window that triggers a hard skip (minutes)
_NEWS_SKIP_WINDOW_MINUTES = 60


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
class MarketSnapshot:
    """
    Live market indicators passed to the edge selector.

    All fields have safe defaults so callers can supply only what they have.
    """

    symbol: str = "XAUUSD"
    price: float = 0.0
    atr: float = 0.0  # ATR(14) in price units
    adx: float = 0.0  # ADX(14)
    rsi: float = 50.0  # RSI(14)
    volume_delta: float = 0.0  # % change vs average, e.g. +15.0 = +15 %
    cone_strength: float = 0.0  # ITOS cone score 0.0–1.0
    last_candles: str = ""  # free-text description, e.g. "bullish engulfing"
    news_spike: bool = False  # True if a news event is active
    liquidity: str = "normal"  # "high" | "normal" | "low"
    drawdown_pct: float = 0.0  # current open drawdown %

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "atr": self.atr,
            "adx": self.adx,
            "rsi": self.rsi,
            "volume_delta": self.volume_delta,
            "cone_strength": self.cone_strength,
            "last_candles": self.last_candles,
            "news_spike": self.news_spike,
            "liquidity": self.liquidity,
            "drawdown_pct": self.drawdown_pct,
        }


@dataclass
class EdgeDecision:
    """
    Output of AdaptiveEdgeSelector.select().

    JSON-serialisable via to_dict().  Consumed by HOPEFXBrain._route_strategy()
    when an edge selector is injected.
    """

    regime: str
    edge: str
    confidence: int  # 0–100
    reason: str
    action: str  # human-readable trade instruction
    symbol: str = "XAUUSD"
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    lot_size: float = 0.01
    strategy_name: str = ""  # maps to brain strategy routing table
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "edge": self.edge,
            "confidence": self.confidence,
            "reason": self.reason,
            "action": self.action,
            "symbol": self.symbol,
            "entry_price": round(self.entry_price, 5),
            "sl_price": round(self.sl_price, 5),
            "tp_price": round(self.tp_price, 5),
            "lot_size": self.lot_size,
            "strategy_name": self.strategy_name,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# News event
# ---------------------------------------------------------------------------


@dataclass
class NewsEvent:
    """
    A scheduled or detected news event that may affect trading.

    minutes_away : float
        Minutes until (positive) or since (negative) the event.
        e.g. 30.0 = event in 30 min, -5.0 = event happened 5 min ago.
    description : str
        Human-readable label, e.g. "FOMC minutes", "crypto hack rumor".
    symbols_affected : list[str]
        Symbols directly impacted.  Empty list = all symbols.
    severity : str
        "high" | "medium" | "low"
    """

    minutes_away: float
    description: str = ""
    symbols_affected: list[str] = field(default_factory=list)
    severity: str = "high"

    def affects(self, symbol: str) -> bool:
        """True when this event affects the given symbol."""
        if not self.symbols_affected:
            return True
        return symbol.upper() in [s.upper() for s in self.symbols_affected]

    def is_within_window(self, window_minutes: float = _NEWS_SKIP_WINDOW_MINUTES) -> bool:
        """True when the event is within ±window_minutes of now."""
        return abs(self.minutes_away) <= window_minutes


# ---------------------------------------------------------------------------
# Decision memory
# ---------------------------------------------------------------------------


@dataclass
class DecisionRecord:
    """One historical edge decision and its outcome."""

    symbol: str
    edge: str  # EDGE_SNIPER | EDGE_SCALPER | EDGE_GRID | EDGE_SKIP
    outcome: str  # "won" | "lost" | "skipped" | "pending"
    confidence: int
    regime: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class DecisionMemory:
    """
    Per-symbol rolling history of edge decisions and outcomes.

    Used by AdaptiveEdgeSelector to:
    - Penalise edges that recently lost on a symbol
    - Boost edges that recently won on a symbol
    - Avoid repeating a losing pattern in the same regime

    Configuration
    -------------
    EDGE_MEMORY_WINDOW : int   number of decisions to remember per symbol (default 10)
    """

    def __init__(self, window: int | None = None) -> None:
        _w = window or _env_int("EDGE_MEMORY_WINDOW", 10)
        self._history: dict[str, deque[DecisionRecord]] = {}
        self._window = _w

    def record(self, decision: DecisionRecord) -> None:
        """Store a decision in the rolling window for its symbol."""
        sym = decision.symbol.upper()
        if sym not in self._history:
            self._history[sym] = deque(maxlen=self._window)
        self._history[sym].append(decision)

    def recent(self, symbol: str, n: int = 3) -> list[DecisionRecord]:
        """Return the n most recent records for a symbol (newest last)."""
        sym = symbol.upper()
        hist = list(self._history.get(sym, []))
        return hist[-n:]

    def last_outcome(self, symbol: str, edge: str) -> str | None:
        """Return the most recent outcome for a specific edge on a symbol."""
        for rec in reversed(self.recent(symbol, n=self._window)):
            if rec.edge == edge:
                return rec.outcome
        return None

    def win_rate(self, symbol: str, edge: str, n: int = 5) -> float:
        """Win rate (0.0–1.0) for an edge on a symbol over the last n decisions."""
        records = [r for r in self.recent(symbol, n=n) if r.edge == edge and r.outcome != "pending"]
        if not records:
            return 0.5  # neutral prior
        wins = sum(1 for r in records if r.outcome == "won")
        return wins / len(records)

    def memory_adjustment(self, symbol: str, edge: str) -> int:
        """
        Confidence adjustment (-15 to +10) based on recent history.

        Won last time  → +10
        Lost last time → -15
        Mixed          → proportional to win_rate
        """
        last = self.last_outcome(symbol, edge)
        if last == "won":
            return 10
        if last == "lost":
            return -15
        wr = self.win_rate(symbol, edge)
        if wr >= 0.6:
            return 5
        if wr <= 0.4:
            return -8
        return 0

    def clear(self, symbol: str | None = None) -> None:
        """Clear history for one symbol or all symbols."""
        if symbol is None:
            self._history.clear()
        else:
            self._history.pop(symbol.upper(), None)


# ---------------------------------------------------------------------------
# News filter
# ---------------------------------------------------------------------------


class NewsFilter:
    """
    Evaluates a list of NewsEvent objects and decides whether trading is safe.

    Rules
    -----
    - Any HIGH severity event within ±60 min → hard skip all symbols
    - Any MEDIUM severity event within ±30 min → skip affected symbols
    - Any event within ±15 min regardless of severity → skip affected symbols
    - Crypto-specific events (hack, exploit, SEC) → skip BTC/ETH/crypto symbols
    """

    # Keywords that flag crypto-specific risk
    _CRYPTO_KEYWORDS = ("hack", "exploit", "sec", "cftc", "ban", "crash", "rug")
    _CRYPTO_SYMBOLS = ("BTC", "ETH", "XRP", "SOL", "BNB", "DOGE")

    def __init__(self, events: list[NewsEvent] | None = None) -> None:
        self._events: list[NewsEvent] = events or []

    def add(self, event: NewsEvent) -> None:
        self._events.append(event)

    def clear(self) -> None:
        self._events.clear()

    def is_safe(self, symbol: str) -> tuple[bool, str]:
        """
        Return (safe, reason).

        safe=False means the symbol should be skipped due to news risk.

        Evaluation order
        ----------------
        1. Crypto keyword scan (symbol-specific — checked first so BTC/ETH
           events don't bleed into non-crypto symbols via the generic rules)
        2. Any event within 15 min (imminent — all symbols)
        3. High severity within 60 min (all affected symbols)
        4. Medium severity within 30 min (all affected symbols)
        """
        sym_upper = symbol.upper()

        # 1. Crypto-specific keyword scan (runs before generic severity rules)
        for ev in self._events:
            desc_lower = ev.description.lower()
            if any(kw in desc_lower for kw in self._CRYPTO_KEYWORDS):
                base = sym_upper.replace("USD", "").replace("USDT", "")
                if base in self._CRYPTO_SYMBOLS and abs(ev.minutes_away) <= 120:
                    return False, f"crypto_risk:{ev.description}"

        for ev in self._events:
            if not ev.affects(sym_upper):
                continue

            mins = abs(ev.minutes_away)
            sev = ev.severity.lower()

            # 2. Any event within 15 min — imminent, skip regardless of severity
            if mins <= 15:
                return False, f"news_imminent:{ev.description}_{mins:.0f}min_away"

            # 3. Hard block: high severity within 60 min
            if sev == "high" and mins <= 60:
                return False, f"news_high_sev:{ev.description}_{mins:.0f}min_away"

            # 4. Medium severity within 30 min
            if sev == "medium" and mins <= 30:
                return False, f"news_medium_sev:{ev.description}_{mins:.0f}min_away"

        return True, ""


# ---------------------------------------------------------------------------
# AdaptiveEdgeSelector
# ---------------------------------------------------------------------------


class AdaptiveEdgeSelector:
    """
    HOPEFX Beast Adaptive Edge Selector.

    Analyses live market indicators per symbol, detects regime, applies news
    filtering, factors decision memory, runs a one-step lookahead, and picks
    ONE edge that dominates right now — no bias, no primary.

    Single-symbol usage
    -------------------
    selector = AdaptiveEdgeSelector()
    snap = MarketSnapshot(symbol="XAUUSD", price=2345.67, atr=1.25, ...)
    decision = selector.select(snap)

    Multi-symbol usage
    ------------------
    snaps = [MarketSnapshot(...), MarketSnapshot(...), ...]
    decisions = selector.select_all(snaps)   # list[EdgeDecision]
    logger.info([d.to_dict() for d in decisions])

    Memory + news
    -------------
    selector = AdaptiveEdgeSelector(
        memory=DecisionMemory(),
        news_filter=NewsFilter([
            NewsEvent(minutes_away=30, description="FOMC minutes", severity="high"),
        ]),
    )
    """

    def __init__(
        self,
        memory: DecisionMemory | None = None,
        news_filter: NewsFilter | None = None,
    ) -> None:
        self.enabled = _env_bool("EDGE_SELECTOR_ENABLED", True)
        self.min_confidence = _env_int("EDGE_SELECTOR_MIN_CONFIDENCE", 80)
        self.cone_threshold = _env_float("EDGE_SELECTOR_CONE_THRESHOLD", 0.70)
        self.adx_trend = _env_float("EDGE_SELECTOR_ADX_TREND", 25.0)
        self.adx_choppy = _env_float("EDGE_SELECTOR_ADX_CHOPPY", 15.0)
        self.rsi_ob = _env_float("EDGE_SELECTOR_RSI_OB", 70.0)
        self.rsi_os = _env_float("EDGE_SELECTOR_RSI_OS", 30.0)
        self.atr_sl_mult = _env_float("EDGE_SELECTOR_ATR_SL_MULT", 2.0)
        self.atr_tp_mult = _env_float("EDGE_SELECTOR_ATR_TP_MULT", 4.0)
        self.max_lot = _env_float("EDGE_SELECTOR_MAX_LOT", 0.01)
        self.grid_max_layers = _env_int("EDGE_SELECTOR_GRID_MAX_LAYERS", 4)
        self.grid_be_pips = _env_float("EDGE_SELECTOR_GRID_BE_PIPS", 20.0)
        self.grid_dd_cooldown = _env_float("EDGE_SELECTOR_GRID_DD_COOLDOWN", 5.0)

        self.memory: DecisionMemory = memory or DecisionMemory()
        self.news_filter: NewsFilter = news_filter or NewsFilter()

        logger.info(
            "AdaptiveEdgeSelector initialised — enabled=%s min_conf=%d cone_thr=%.2f adx_trend=%.1f",
            self.enabled,
            self.min_confidence,
            self.cone_threshold,
            self.adx_trend,
        )

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def select(self, snap: MarketSnapshot) -> EdgeDecision:
        """
        Analyse the snapshot and return the single best EdgeDecision.

        Always returns a valid EdgeDecision — defaults to EDGE_SKIP when
        no edge qualifies or the selector is disabled.
        """
        if not self.enabled:
            return self._skip(snap, "edge_selector_disabled")

        # Hard safety guards — legacy field
        if snap.news_spike:
            return self._skip(snap, "news_spike_active")

        # News filter (structured events)
        safe, news_reason = self.news_filter.is_safe(snap.symbol)
        if not safe:
            return self._skip(snap, news_reason)

        if snap.cone_strength < self.cone_threshold and snap.adx < self.adx_trend:
            return self._skip(snap, f"cone_low={snap.cone_strength:.2f}_adx_weak={snap.adx:.1f}")
        if snap.liquidity == "low":
            return self._skip(snap, "liquidity_low")

        regime = self._detect_regime(snap)

        # Grid cooldown: if drawdown exceeds threshold, skip all edges
        if snap.drawdown_pct > self.grid_dd_cooldown:
            return self._skip(snap, f"dd_cooldown={snap.drawdown_pct:.1f}%")

        # Regime-driven edge selection
        if regime in (REGIME_TRENDING_UP, REGIME_TRENDING_DOWN):
            decision = self._try_sniper(snap, regime)
        elif regime == REGIME_RANGING:
            decision = self._try_scalper(snap, regime)
        elif regime == REGIME_VOLATILE:
            if snap.cone_strength >= self.cone_threshold:
                decision = self._try_grid(snap, regime)
            else:
                decision = self._skip(snap, f"volatile_cone_low={snap.cone_strength:.2f}")
        elif regime == REGIME_CHOPPY:
            decision = self._skip(snap, "choppy_regime")
        elif regime == REGIME_LOW_VOL:
            if snap.rsi >= self.rsi_ob or snap.rsi <= self.rsi_os:
                decision = self._try_scalper(snap, regime)
            else:
                decision = self._skip(snap, "low_vol_rsi_neutral")
        else:
            decision = self._skip(snap, f"unknown_regime={regime}")

        # Apply memory adjustment to non-skip decisions
        if decision.edge != EDGE_SKIP:
            adj = self.memory.memory_adjustment(snap.symbol, decision.edge)
            if adj != 0:
                new_conf = max(0, min(100, decision.confidence + adj))
                decision.confidence = new_conf
                decision.reason += f", mem_adj={adj:+d}"
                # Re-check minimum confidence after memory adjustment
                if decision.confidence < self.min_confidence:
                    return self._skip(snap, f"post_memory_conf_low={decision.confidence}")

        # Lookahead: downgrade if next-candle flip risk is high
        decision = self._apply_lookahead(snap, decision)

        return decision

    def select_all(
        self,
        snapshots: list[MarketSnapshot],
    ) -> list[EdgeDecision]:
        """
        Run select() for every snapshot and return one EdgeDecision per symbol.

        The order of the output matches the order of the input snapshots.
        """
        return [self.select(snap) for snap in snapshots]

    def record_outcome(
        self,
        symbol: str,
        edge: str,
        outcome: str,
        confidence: int = 0,
        regime: str = REGIME_UNKNOWN,
    ) -> None:
        """
        Record the outcome of a previous decision into memory.

        outcome : "won" | "lost" | "skipped" | "pending"
        """
        self.memory.record(
            DecisionRecord(
                symbol=symbol,
                edge=edge,
                outcome=outcome,
                confidence=confidence,
                regime=regime,
            )
        )

    # ------------------------------------------------------------------
    # Lookahead
    # ------------------------------------------------------------------

    def _apply_lookahead(self, snap: MarketSnapshot, decision: EdgeDecision) -> EdgeDecision:
        """
        One-step lookahead: assess whether the next candle or an imminent
        news event could flip the setup.  Downgrades confidence or converts
        to skip when the risk of reversal is high.

        Flip risk factors
        -----------------
        - RSI near 50 (no clear momentum) → moderate flip risk
        - Volume delta near zero → no conviction, easy reversal
        - Cone strength dropping toward threshold → signal weakening
        - ATR expanding rapidly (2× normal) → volatility spike incoming
        - News within 30 min (already caught by news filter for hard blocks,
          but medium-severity events within 30–60 min still reduce confidence)
        """
        if decision.edge == EDGE_SKIP:
            return decision

        flip_risk = 0  # 0 = none, 1 = low, 2 = medium, 3 = high

        # RSI near neutral
        rsi_dist = abs(snap.rsi - 50.0)
        if rsi_dist < 5:
            flip_risk += 2
        elif rsi_dist < 10:
            flip_risk += 1

        # Volume conviction
        if abs(snap.volume_delta) < 5.0:
            flip_risk += 1

        # Cone weakening
        if snap.cone_strength < self.cone_threshold + 0.05:
            flip_risk += 1

        # ATR spike (relative to a "normal" ATR proxy — use price/1000 as baseline)
        normal_atr_proxy = snap.price / 1000.0 if snap.price > 0 else 1.0
        if snap.atr > normal_atr_proxy * 2.0:
            flip_risk += 2

        # Soft news proximity (medium events 30–60 min away)
        for ev in self.news_filter._events:
            if ev.affects(snap.symbol) and 30 <= abs(ev.minutes_away) <= 60 and ev.severity in ("high", "medium"):
                flip_risk += 2
                break

        if flip_risk >= 4:
            # High flip risk — convert to skip
            return self._skip(snap, f"lookahead_flip_risk={flip_risk}")
        elif flip_risk >= 2:
            # Medium flip risk — reduce confidence
            penalty = flip_risk * 4
            new_conf = max(0, decision.confidence - penalty)
            decision.confidence = new_conf
            decision.reason += f", lookahead_risk={flip_risk}(−{penalty})"
            if decision.confidence < self.min_confidence:
                return self._skip(snap, f"post_lookahead_conf_low={decision.confidence}")

        return decision

    # ------------------------------------------------------------------
    # Regime detection from raw indicators
    # ------------------------------------------------------------------

    def _detect_regime(self, snap: MarketSnapshot) -> str:
        """
        Classify regime from ADX, ATR, RSI, volume_delta, and cone_strength.

        Priority order:
        1. Choppy  — ADX very weak
        2. Volatile — high ADX + high volume spike or news-adjacent
        3. Trending — ADX strong + volume confirms direction
        4. Ranging  — ADX moderate + low ATR relative to price
        5. Low-vol  — ATR very small
        6. Unknown
        """
        adx = snap.adx
        rsi = snap.rsi
        vol_delta = snap.volume_delta
        atr = snap.atr
        price = snap.price if snap.price > 0 else 1.0
        rel_atr = atr / price  # relative ATR as fraction of price

        # 1. Choppy: ADX very weak — no directional conviction
        if adx < self.adx_choppy:
            return REGIME_CHOPPY

        # 2. Volatile: strong ADX + large volume spike (> 30 %) or very high ATR
        if adx >= self.adx_trend and (abs(vol_delta) > 30.0 or rel_atr > 0.008):
            return REGIME_VOLATILE

        # 3. Trending: ADX strong + volume confirms direction
        if adx >= self.adx_trend:
            # RSI and volume delta together confirm direction
            if rsi > 50 and vol_delta > 0:
                return REGIME_TRENDING_UP
            if rsi < 50 and vol_delta < 0:
                return REGIME_TRENDING_DOWN
            # ADX strong but mixed signals — still trending, use RSI to pick side
            return REGIME_TRENDING_UP if rsi >= 50 else REGIME_TRENDING_DOWN

        # 4. Ranging: moderate ADX + tight ATR
        if adx < self.adx_trend and rel_atr < 0.004:
            return REGIME_RANGING

        # 5. Low-vol: very tight ATR
        if rel_atr < 0.002:
            return REGIME_LOW_VOL

        return REGIME_UNKNOWN

    # ------------------------------------------------------------------
    # Edge builders
    # ------------------------------------------------------------------

    def _try_sniper(self, snap: MarketSnapshot, regime: str) -> EdgeDecision:
        """
        Attempt to build a sniper (precision limit-order) edge.

        Requires:
        - cone_strength ≥ cone_threshold
        - ADX ≥ adx_trend
        - Confidence ≥ min_confidence
        """
        if snap.cone_strength < self.cone_threshold:
            return self._skip(snap, f"sniper_cone_low={snap.cone_strength:.2f}")

        if snap.adx < self.adx_trend:
            return self._skip(snap, f"sniper_adx_weak={snap.adx:.1f}")

        direction = "buy" if regime == REGIME_TRENDING_UP else "sell"
        confidence = self._score_sniper(snap, regime)

        if confidence < self.min_confidence:
            return self._skip(snap, f"sniper_conf_low={confidence}")

        sl, tp = self._calc_sl_tp(snap, direction)
        sl_pips = round(abs(snap.price - sl) / (snap.atr / 14), 1) if snap.atr > 0 else 20.0
        tp_pips = round(abs(tp - snap.price) / (snap.atr / 14), 1) if snap.atr > 0 else 40.0

        # Beast reason voice
        voice_parts = []
        if snap.cone_strength >= 0.90:
            voice_parts.append("Cone's screaming—signal locked")
        elif snap.cone_strength >= 0.80:
            voice_parts.append("Cone's lit—sharp entry")
        else:
            voice_parts.append(f"Cone solid at {snap.cone_strength:.2f}")

        if snap.adx >= 40:
            voice_parts.append("ADX roaring—trend unstoppable")
        elif snap.adx >= 30:
            voice_parts.append(f"ADX={snap.adx:.1f} strong—momentum confirmed")
        else:
            voice_parts.append(f"ADX={snap.adx:.1f} trending")

        candles_lower = snap.last_candles.lower()
        if "engulfing" in candles_lower:
            voice_parts.append("engulfing seals it—no mercy")
        elif "hammer" in candles_lower or "pin bar" in candles_lower:
            voice_parts.append("hammer/pin bar—reversal rejected")
        elif snap.last_candles:
            voice_parts.append(f"pattern: {snap.last_candles}")

        if abs(snap.volume_delta) >= 20:
            voice_parts.append(f"volume exploding {snap.volume_delta:+.0f}%—institutions in")
        elif abs(snap.volume_delta) >= 10:
            voice_parts.append(f"volume confirming {snap.volume_delta:+.0f}%")

        mem_last = self.memory.last_outcome(snap.symbol, EDGE_SNIPER)
        if mem_last == "won":
            voice_parts.append("last sniper won—lean in hard")
        elif mem_last == "lost":
            voice_parts.append("last sniper lost—SL tight, size small")

        voice_parts.append(f"SL {sl_pips:.0f}pips, TP {tp_pips:.0f}pips—{self.atr_tp_mult / self.atr_sl_mult:.0f}:1 RR")
        reason = ". ".join(voice_parts)

        action = (
            f"{direction} {self.max_lot:.2f} lot at market {snap.price:.2f}, "
            f"SL {sl:.2f} ({sl_pips:.0f} pips), TP {tp:.2f} ({tp_pips:.0f} pips)"
        )

        return EdgeDecision(
            regime=regime,
            edge=EDGE_SNIPER,
            confidence=confidence,
            reason=reason,
            action=action,
            symbol=snap.symbol,
            entry_price=snap.price,
            sl_price=sl,
            tp_price=tp,
            lot_size=self.max_lot,
            strategy_name="smc_ict",
        )

    def _try_scalper(self, snap: MarketSnapshot, regime: str) -> EdgeDecision:
        """
        Attempt to build a scalper (fast mean-reversion) edge.

        Requires:
        - RSI at extremes (≥ rsi_ob or ≤ rsi_os) OR volume_delta moderate
        - Confidence ≥ min_confidence
        """
        at_extreme = snap.rsi >= self.rsi_ob or snap.rsi <= self.rsi_os
        if not at_extreme and abs(snap.volume_delta) < 10.0:
            return self._skip(snap, "scalper_no_rsi_extreme_no_vol_signal")

        direction = "sell" if snap.rsi >= self.rsi_ob else "buy"
        confidence = self._score_scalper(snap, regime)

        if confidence < self.min_confidence:
            return self._skip(snap, f"scalper_conf_low={confidence}")

        # Scalper uses tighter SL/TP (half the sniper multipliers)
        sl_dist = snap.atr * (self.atr_sl_mult / 2.0)
        tp_dist = snap.atr * (self.atr_tp_mult / 2.0)
        sl = snap.price - sl_dist if direction == "buy" else snap.price + sl_dist
        tp = snap.price + tp_dist if direction == "buy" else snap.price - tp_dist

        # Beast reason voice
        voice_parts = []
        if snap.rsi >= self.rsi_ob:
            voice_parts.append(f"RSI={snap.rsi:.1f} overbought—fade the crowd")
        elif snap.rsi <= self.rsi_os:
            voice_parts.append(f"RSI={snap.rsi:.1f} oversold—snap back incoming")
        else:
            voice_parts.append(f"RSI={snap.rsi:.1f} at extreme")

        if snap.cone_strength >= 0.80:
            voice_parts.append(f"cone={snap.cone_strength:.2f} sharp—reversion confirmed")
        else:
            voice_parts.append(f"cone={snap.cone_strength:.2f}")

        if 5.0 <= abs(snap.volume_delta) <= 20.0:
            voice_parts.append(f"volume moderate {snap.volume_delta:+.0f}%—reversion fuel")

        mem_last = self.memory.last_outcome(snap.symbol, EDGE_SCALPER)
        if mem_last == "won":
            voice_parts.append("scalper won last—repeat the play")
        elif mem_last == "lost":
            voice_parts.append("scalper lost last—tighter TP this time")

        voice_parts.append(f"quick in/out, regime={regime}")
        reason = ". ".join(voice_parts)

        action = f"{direction} {self.max_lot:.2f} lot at market {snap.price:.2f}, SL {sl:.2f}, TP {tp:.2f} (scalp)"

        return EdgeDecision(
            regime=regime,
            edge=EDGE_SCALPER,
            confidence=confidence,
            reason=reason,
            action=action,
            symbol=snap.symbol,
            entry_price=snap.price,
            sl_price=sl,
            tp_price=tp,
            lot_size=self.max_lot,
            strategy_name="mean_reversion",
        )

    def _try_grid(self, snap: MarketSnapshot, regime: str) -> EdgeDecision:
        """
        Attempt to build a grid-recovery edge.

        Only valid in volatile regime with cone ≥ threshold.
        Max layers, breakeven basket, and DD cooldown are enforced.
        """
        confidence = self._score_grid(snap, regime)

        if confidence < self.min_confidence:
            return self._skip(snap, f"grid_conf_low={confidence}")

        action = (
            f"open grid {self.max_lot:.2f} lot/layer, "
            f"max {self.grid_max_layers} layers, "
            f"breakeven basket at +{self.grid_be_pips:.0f} pips, "
            f"cooldown if DD>{self.grid_dd_cooldown:.0f}%"
        )

        # Beast reason voice
        voice_parts = [
            "Volatile chaos—grid absorbs it",
            f"cone={snap.cone_strength:.2f} holds the structure",
            f"ADX={snap.adx:.1f} wild—layers catch every bounce",
            f"max {self.grid_max_layers} layers, basket closes at +{self.grid_be_pips:.0f}pips",
            "no martingale—capital protected",
        ]
        if snap.volume_delta != 0:
            voice_parts.append(f"vol_delta={snap.volume_delta:+.0f}%")
        reason = ". ".join(voice_parts)

        return EdgeDecision(
            regime=regime,
            edge=EDGE_GRID,
            confidence=confidence,
            reason=reason,
            action=action,
            symbol=snap.symbol,
            entry_price=snap.price,
            sl_price=0.0,  # grid manages its own SL via basket breakeven
            tp_price=0.0,
            lot_size=self.max_lot,
            strategy_name="breakout",
        )

    def _skip(self, snap: MarketSnapshot, reason: str) -> EdgeDecision:
        """Return a SKIP decision — no trade."""
        logger.debug("AdaptiveEdgeSelector: SKIP [%s] reason=%s", snap.symbol, reason)
        return EdgeDecision(
            regime=self._detect_regime(snap) if snap.price > 0 else REGIME_UNKNOWN,
            edge=EDGE_SKIP,
            confidence=0,
            reason=reason,
            action="no_trade — wait for better setup",
            symbol=snap.symbol,
            strategy_name="none",
        )

    # ------------------------------------------------------------------
    # Confidence scoring
    # ------------------------------------------------------------------

    def _score_sniper(self, snap: MarketSnapshot, regime: str) -> int:
        """
        Score sniper confidence 0–100.

        Base 60, then add points for each confirming factor.
        """
        score = 60

        # ADX strength (up to +15)
        if snap.adx >= 40:
            score += 15
        elif snap.adx >= 30:
            score += 10
        elif snap.adx >= self.adx_trend:
            score += 5

        # Cone sharpness (up to +10)
        if snap.cone_strength >= 0.90:
            score += 10
        elif snap.cone_strength >= 0.80:
            score += 7
        elif snap.cone_strength >= self.cone_threshold:
            score += 4

        # Volume confirmation (up to +8)
        if abs(snap.volume_delta) >= 20:
            score += 8
        elif abs(snap.volume_delta) >= 10:
            score += 5

        # Candle pattern (up to +5)
        candles_lower = snap.last_candles.lower()
        if "engulfing" in candles_lower:
            score += 5
        elif "pin bar" in candles_lower or "hammer" in candles_lower:
            score += 3

        # RSI alignment with direction (up to +5)
        if regime == REGIME_TRENDING_UP and snap.rsi > 55 or regime == REGIME_TRENDING_DOWN and snap.rsi < 45:
            score += 5

        # Liquidity bonus (+2)
        if snap.liquidity == "high":
            score += 2

        return min(score, 100)

    def _score_scalper(self, snap: MarketSnapshot, regime: str) -> int:
        """Score scalper confidence 0–100."""
        score = 55

        # RSI extreme (up to +20)
        rsi_dist_ob = abs(snap.rsi - self.rsi_ob)
        rsi_dist_os = abs(snap.rsi - self.rsi_os)
        rsi_extreme = min(rsi_dist_ob, rsi_dist_os)
        if rsi_extreme <= 5:
            score += 20
        elif rsi_extreme <= 10:
            score += 12
        elif rsi_extreme <= 15:
            score += 6

        # Cone sharpness (up to +8)
        if snap.cone_strength >= 0.80:
            score += 8
        elif snap.cone_strength >= self.cone_threshold:
            score += 4

        # Volume moderate (not too extreme — scalper wants reversion, not breakout)
        if 5.0 <= abs(snap.volume_delta) <= 20.0:
            score += 5

        # Regime fit
        if regime in (REGIME_RANGING, REGIME_LOW_VOL):
            score += 5

        return min(score, 100)

    def _score_grid(self, snap: MarketSnapshot, regime: str) -> int:
        """Score grid confidence 0–100."""
        score = 55

        # Cone sharpness (up to +15)
        if snap.cone_strength >= 0.90:
            score += 15
        elif snap.cone_strength >= 0.80:
            score += 10
        elif snap.cone_strength >= self.cone_threshold:
            score += 5

        # ADX moderate (grid works best in moderate volatility)
        if 20 <= snap.adx < 35:
            score += 10
        elif snap.adx >= 35:
            score += 5  # too strong — grid is riskier

        # Volume spike (grid needs movement)
        if abs(snap.volume_delta) >= 20:
            score += 8
        elif abs(snap.volume_delta) >= 10:
            score += 4

        # Drawdown penalty
        if snap.drawdown_pct > 2.0:
            score -= int(snap.drawdown_pct * 3)

        return max(0, min(score, 100))

    # ------------------------------------------------------------------
    # SL / TP calculation
    # ------------------------------------------------------------------

    def _calc_sl_tp(self, snap: MarketSnapshot, direction: str) -> tuple[float, float]:
        """
        Compute absolute SL and TP prices from ATR multipliers.

        Returns (sl_price, tp_price).
        """
        sl_dist = snap.atr * self.atr_sl_mult
        tp_dist = snap.atr * self.atr_tp_mult

        if direction == "buy":
            sl = snap.price - sl_dist
            tp = snap.price + tp_dist
        else:
            sl = snap.price + sl_dist
            tp = snap.price - tp_dist

        return round(sl, 5), round(tp, 5)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_selector: AdaptiveEdgeSelector | None = None


def get_edge_selector() -> AdaptiveEdgeSelector:
    """Return the module-level AdaptiveEdgeSelector singleton."""
    global _selector
    if _selector is None:
        _selector = AdaptiveEdgeSelector()
    return _selector
