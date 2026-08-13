# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
analysis/chart_analysis.py
==========================
The engine behind ``POST /api/trading/ai-analysis`` — the AI Chart Bot.

What this replaces
------------------
The previous implementation was 230 lines inline in the router. It called
yfinance directly, computed EMA/RSI/ATR by hand, and returned a templated
sentence. It contained no machine learning of any kind, while the UI labelled
its output "ML FEATURE IMPORTANCE" and "Reading ML signals…". It also:

* raised ``ZeroDivisionError`` — an unhandled HTTP 500 — whenever the last 15
  closes were identical, because ``(gains if d > 0 else losses)`` routes a zero
  delta into ``losses`` and the ``if losses else 0.001`` guard only catches an
  *empty* list, not a list of zeros. Reachable every market close and on any
  quiet 1m chart;
* raised ``TypeError``/``AttributeError`` on ``{"price": null}`` and
  ``{"symbol": null}``, because the signature was an unvalidated ``dict``;
* computed its EMAs backwards — ``for c in reversed(closes[-20:])`` weights the
  *oldest* bar most — which changed the regime verdict on 19.1% of 3,000
  simulated price paths;
* carried a fourth independent yfinance ticker map mapping XAUUSD to ``GC=F``,
  the futures contract, in direct contradiction of
  ``config/multi_source_feed.yaml``, which blanks Yahoo for spot metals on
  purpose so nothing quotes a proxy as spot.

Design
------
Every numeric helper here is pure, total, and independently testable. They
return ``None`` for "undefined on this input" rather than raising or
substituting a magic number: a flat tape has no meaningful RSI, and saying so
is more useful than reporting 0.0 (maximally oversold) and recommending BUY,
which is what the old code did on the path that did not crash outright.

The machine learning is real. ``InferenceEngine.predict`` supplies direction,
*calibrated* confidence and a model version, and brings its own staleness and
drift gating. Indicators are demoted to what they are — supporting context that
explains the model's call, not a substitute for it.

Provenance is part of the answer, not a footnote. Every response states which
model spoke, how many bars it saw, where the bars came from, and whether any
gate was open. A degraded answer is labelled degraded, because an analysis that
cannot tell you it is guessing is worse than no analysis.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

# Regimes the frontend's MarketRegime union accepts.
REGIME_TRENDING_UP = "trending_up"
REGIME_TRENDING_DOWN = "trending_down"
REGIME_RANGING = "ranging"
REGIME_VOLATILE = "volatile"

_MIN_BARS_FOR_REGIME = 20
_MIN_BARS_FOR_ML = 100

# Analysis is cached per (symbol, timeframe) for this long. A chart click is a
# read, and the underlying H1 bar does not change between two clicks a second
# apart — but the old endpoint ran an uncached 25-second-timeout fetch on every
# one of them, with no rate limit, in the shared executor pool.
CACHE_TTL_SECONDS = 20


# ── Input ─────────────────────────────────────────────────────────────────────


class ChartClickContext(BaseModel):
    """Validated click payload.

    The endpoint previously took a bare ``dict``. ``{"price": null}`` reached
    ``float(None)`` and ``{"symbol": null}`` reached ``None.replace(...)``, each
    an unhandled 500 from a one-line client mistake. NaN and infinity passed
    straight through and poisoned every number downstream, including the stop
    loss shown to the user.
    """

    symbol: str = "XAUUSD"
    price: float = 0.0
    timeframe: str = "1h"
    timestamp: int | None = None
    # Echoed back to the client untouched; the frontend uses it to pair the
    # analysis with the bar the user clicked.
    bar: dict[str, Any] | None = None

    model_config = {"extra": "allow"}

    @field_validator("symbol", mode="before")
    @classmethod
    def _symbol_not_null(cls, v: Any) -> str:
        return "XAUUSD" if v is None or not str(v).strip() else str(v)

    @field_validator("price", mode="before")
    @classmethod
    def _price_is_finite(cls, v: Any) -> float:
        if v is None:
            return 0.0
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        # NaN/inf silently contaminate every arithmetic result derived from the
        # click price — including stop_loss and take_profit.
        return 0.0 if not math.isfinite(f) else f

    @field_validator("timeframe", mode="before")
    @classmethod
    def _timeframe_not_null(cls, v: Any) -> str:
        return "1h" if v is None or not str(v).strip() else str(v)

    def canonical_symbol(self) -> str:
        return self.symbol.replace("/", "").replace("%2F", "").replace("_", "").upper()


# ── Pure indicator helpers ────────────────────────────────────────────────────


def ema(values: list[float], period: int) -> float | None:
    """Exponential moving average over the most recent *period* values.

    Oldest to newest, seeded on the first value of the window — the definition.
    The previous implementation iterated ``reversed(...)``, which weights the
    oldest bar most heavily and makes the average lag *into* the past, and
    seeded on ``closes[-1]`` while also including that bar in the loop, so the
    newest bar was counted twice.
    """
    if period <= 0 or not values:
        return None
    window = values[-period:]
    if len(window) < 2:
        return float(window[0]) if window else None
    alpha = 2.0 / (period + 1.0)
    out = float(window[0])
    for v in window[1:]:
        out = out * (1.0 - alpha) + float(v) * alpha
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI, or ``None`` where RSI is undefined.

    Returns ``None`` — not a number — when the window has no price movement at
    all. RSI is a ratio of average gain to average loss; with both zero the
    ratio does not exist. The previous code sent zero deltas into ``losses``
    (``d > 0`` is false for ``d == 0``), so a flat window produced
    ``avg_gain=0`` and ``avg_loss=0.0`` and divided by it: an unhandled
    ZeroDivisionError, on every quiet chart and every market close.

    A zero delta is neither a gain nor a loss and is now counted as neither.
    """
    if period <= 0 or len(closes) < period + 1:
        return None

    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        d = float(closes[i]) - float(closes[i - 1])
        if d > 0:
            gains += d
        elif d < 0:
            losses += -d

    if gains == 0.0 and losses == 0.0:
        return None  # flat window — RSI undefined, and that is the honest answer
    if losses == 0.0:
        return 100.0
    if gains == 0.0:
        return 0.0

    rs = (gains / period) / (losses / period)
    return 100.0 - (100.0 / (1.0 + rs))


def atr(bars: list[dict[str, float]], period: int = 14) -> float | None:
    """Average true range over the most recent *period* bars."""
    if period <= 0 or len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(-period, 0):
        high = float(bars[i]["high"])
        low = float(bars[i]["low"])
        prev_close = float(bars[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(trs) / len(trs) if trs else None


def classify_volatility(atr_value: float | None, price: float) -> str:
    if not atr_value or price <= 0:
        return "unknown"
    pct = atr_value / price
    if pct > 0.015:
        return "high"
    if pct < 0.005:
        return "low"
    return "medium"


@dataclass(frozen=True)
class RegimeVerdict:
    regime: str
    confidence: float
    trend: str
    reasons: list[str] = field(default_factory=list)


def classify_regime(closes: list[float], atr_value: float | None, price: float) -> RegimeVerdict:
    """Technical regime from EMA alignment and volatility.

    Supporting context for the model's call, not a replacement for it. Kept
    conservative: a regime it cannot justify is reported as ranging at moderate
    confidence rather than dressed up.
    """
    if len(closes) < _MIN_BARS_FOR_REGIME:
        return RegimeVerdict(REGIME_RANGING, 0.35, "neutral", ["Insufficient history for a regime call"])

    ema_fast = ema(closes, 20)
    ema_slow = ema(closes, 50)
    if ema_fast is None or ema_slow is None or ema_slow == 0:
        return RegimeVerdict(REGIME_RANGING, 0.35, "neutral", ["EMA undefined on this window"])

    spread = (ema_fast - ema_slow) / ema_slow
    price_vs_fast = (closes[-1] - ema_fast) / ema_fast if ema_fast else 0.0
    vol = classify_volatility(atr_value, price)

    reasons: list[str] = []
    if vol == "high":
        reasons.append(f"ATR is {atr_value / price * 100:.2f}% of price — high volatility")

    if abs(spread) > 0.005 and abs(price_vs_fast) > 0.003:
        # Confidence grows with separation but is capped: EMA alignment alone
        # never justifies near-certainty.
        conf = min(0.85, 0.5 + abs(spread) * 20)
        if spread > 0:
            reasons.append(f"EMA20 is {spread * 100:+.2f}% above EMA50 — uptrend alignment")
            return RegimeVerdict(REGIME_TRENDING_UP, conf, "bullish", reasons)
        reasons.append(f"EMA20 is {spread * 100:+.2f}% below EMA50 — downtrend alignment")
        return RegimeVerdict(REGIME_TRENDING_DOWN, conf, "bearish", reasons)

    if vol == "high":
        return RegimeVerdict(REGIME_VOLATILE, 0.6, "neutral", reasons)

    reasons.append(f"EMA20/EMA50 spread is {spread * 100:+.2f}% — no directional alignment")
    return RegimeVerdict(REGIME_RANGING, 0.6, "neutral", reasons)


def is_degenerate(bars: list[dict[str, float]]) -> bool:
    """True when *bars* carry no price movement at all.

    A flat close series across every bar is the signature of a synthesised
    series, not a quiet market. Analysing it produces zero-range indicators the
    UI renders identically to real ones.
    """
    if len(bars) < 2:
        return True
    closes = [float(b["close"]) for b in bars]
    return max(closes) - min(closes) <= 0.0


# ── ML layer ──────────────────────────────────────────────────────────────────


@dataclass
class ModelVerdict:
    """What the model said, and how much of it should be believed."""

    direction: Literal["long", "short", "neutral"] = "neutral"
    confidence: float = 0.0
    probability: float = 0.5
    model_version: str = "unavailable"
    bars_used: int = 0
    fallback: bool = True
    available: bool = False
    features: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_MODEL_NAME_FOR_IMPORTANCE = "advanced_oos"


def feature_importance(model_version: str, direction: str, limit: int = 6) -> list[dict[str, Any]]:
    """Top feature importances from the model that produced the verdict.

    The UI has always had a "ML FEATURE IMPORTANCE" section. It read
    ``context.nearestSignal.features`` — part of the *request* the browser
    sends, hard-coded ``null`` at the only place a click context is built — so
    the section could never render. These come from
    ``ml/explainability.get_feature_importance``, which unwraps the calibrated
    pipeline to the fitted estimator and caches for an hour.

    Importance here is **global**, not per-prediction: it says which inputs the
    model relies on overall, not which ones drove this particular call. The
    response labels it that way rather than presenting it as attribution.
    """
    try:
        from ml.explainability import get_feature_importance as _gfi

        name = model_version if model_version and model_version not in ("unknown", "fallback") else None
        raw = _gfi(name or _MODEL_NAME_FOR_IMPORTANCE, top_n=limit)
        items = raw.get("features") or []
        if not items:
            return []
        peak = max((float(it.get("importance", 0.0)) for it in items), default=0.0) or 1.0
        bias = "bullish" if direction == "long" else "bearish" if direction == "short" else "neutral"
        return [
            {
                "name": str(it.get("feature", "?")),
                "importance": round(min(float(it.get("importance", 0.0)) / peak, 1.0), 4),
                "direction": bias,
            }
            for it in items[:limit]
        ]
    except Exception as exc:
        logger.debug("chart_analysis: feature importance unavailable: %s", exc)
        return []


def run_model(bars: list[dict[str, float]], symbol: str, engine: Any | None) -> ModelVerdict:
    """Ask the real inference engine, and report honestly when it cannot answer.

    Never raises: a chart click must not 500 because a model file is missing.
    Every reason for a missing or degraded verdict becomes a warning the user
    can see, rather than a silent downgrade to indicator-only output that looks
    identical.
    """
    verdict = ModelVerdict()

    if engine is None:
        verdict.warnings.append("ML engine unavailable — analysis is technical-indicator only")
        return verdict
    if len(bars) < _MIN_BARS_FOR_ML:
        verdict.warnings.append(
            f"Only {len(bars)} bars available; the model needs {_MIN_BARS_FOR_ML} — "
            "analysis is technical-indicator only"
        )
        return verdict

    try:
        import pandas as pd

        df = pd.DataFrame(bars)
        result = engine.predict(df, symbol=symbol)
    except Exception as exc:
        logger.warning("chart_analysis: inference failed for %s: %s", symbol, exc)
        verdict.warnings.append(f"ML inference failed ({type(exc).__name__}) — technical-indicator only")
        return verdict

    verdict.available = True
    verdict.direction = str(result.get("direction", "neutral"))
    verdict.confidence = float(result.get("confidence", 0.0) or 0.0)
    verdict.probability = float(result.get("probability", 0.5) or 0.5)
    verdict.model_version = str(result.get("model_version", "unknown"))
    verdict.bars_used = int(result.get("bars_used", 0) or 0)
    verdict.fallback = bool(result.get("fallback", False))

    if verdict.fallback:
        verdict.warnings.append("Model returned its deterministic fallback — no trained prediction for this window")

    # Safety gates. These already exist and already govern live trading; the
    # chart bot previously showed the user none of them.
    try:
        if not engine.is_safe_to_trade():
            verdict.warnings.append(
                "Data-quality gate is CLOSED (feed health, macro blackout, or consensus "
                "confidence) — the platform would not trade on this"
            )
    except Exception as exc:
        logger.debug("chart_analysis: is_safe_to_trade unavailable: %s", exc)
    try:
        if not engine.drift_guard_active():
            verdict.warnings.append("Feature-drift monitoring is not running — model drift would go undetected")
    except Exception as exc:
        logger.debug("chart_analysis: drift_guard_active unavailable: %s", exc)

    verdict.features = feature_importance(verdict.model_version, verdict.direction)
    return verdict


# ── Composition ───────────────────────────────────────────────────────────────

_DIR_TO_ACTION = {"long": "buy", "short": "sell", "neutral": "hold"}


def _build_summary(
    symbol: str,
    regime: RegimeVerdict,
    model: ModelVerdict,
    action: str,
    price: float,
    rsi_value: float | None,
) -> str:
    """Prose that reflects what actually happened, including what did not."""
    parts: list[str] = []

    if model.available and not model.fallback:
        parts.append(
            f"{symbol}: model {model.model_version} reads {model.direction} "
            f"at {model.confidence * 100:.0f}% calibrated confidence over {model.bars_used} bars."
        )
    elif model.available:
        parts.append(f"{symbol}: no trained prediction for this window — the model returned its fallback.")
    else:
        parts.append(f"{symbol}: no model verdict available; this is a technical read only.")

    parts.append(f"Technical regime is {regime.regime.replace('_', ' ')} at {regime.confidence * 100:.0f}% confidence.")
    if rsi_value is not None:
        parts.append(f"RSI(14) is {rsi_value:.1f}.")
    else:
        parts.append("RSI is undefined on this window — no price movement to measure.")

    if price > 0:
        parts.append(f"Recommended: {action.upper()} around {price:.4f}.")
    else:
        parts.append(f"Recommended: {action.upper()}.")

    return " ".join(parts)


def compose(
    ctx: ChartClickContext,
    bars: list[dict[str, float]],
    model: ModelVerdict,
    *,
    data_source: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Assemble the response the frontend renders. Pure — no I/O."""
    import uuid

    symbol = ctx.canonical_symbol()
    price = ctx.price
    if price <= 0 and bars:
        price = float(bars[-1]["close"])

    closes = [float(b["close"]) for b in bars]
    atr_value = atr(bars)
    rsi_value = rsi(closes)
    regime = classify_regime(closes, atr_value, price)
    volatility = classify_volatility(atr_value, price)

    warnings: list[str] = list(model.warnings)
    key_drivers: list[str] = []

    # The model leads. Indicators explain, and may temper, but do not override —
    # the old code let an RSI threshold set the recommendation outright.
    if model.available and not model.fallback and model.direction != "neutral":
        action = _DIR_TO_ACTION.get(model.direction, "hold")
        action_confidence = model.confidence
        key_drivers.append(
            f"Model {model.model_version}: {model.direction} "
            f"(p={model.probability:.3f}, calibrated {model.confidence * 100:.0f}%)"
        )
    elif regime.regime == REGIME_TRENDING_UP:
        action, action_confidence = "buy", min(regime.confidence, 0.6)
    elif regime.regime == REGIME_TRENDING_DOWN:
        action, action_confidence = "sell", min(regime.confidence, 0.6)
    else:
        action, action_confidence = "hold", 0.4

    key_drivers.extend(regime.reasons)
    if rsi_value is not None:
        if rsi_value < 30:
            key_drivers.append(f"RSI(14) {rsi_value:.1f} — oversold")
        elif rsi_value > 70:
            key_drivers.append(f"RSI(14) {rsi_value:.1f} — overbought")
        else:
            key_drivers.append(f"RSI(14) {rsi_value:.1f} — neutral")
        # A model call against a stretched oscillator is worth flagging rather
        # than quietly averaging away.
        if action == "buy" and rsi_value > 70:
            warnings.append(f"Model is long into overbought RSI ({rsi_value:.1f})")
        elif action == "sell" and rsi_value < 30:
            warnings.append(f"Model is short into oversold RSI ({rsi_value:.1f})")

    if atr_value:
        key_drivers.append(
            f"ATR(14) {atr_value:.4f} ({atr_value / price * 100:.2f}% of price)"
            if price > 0
            else f"ATR(14) {atr_value:.4f}"
        )
    key_drivers.append(f"Volatility: {volatility}")

    if volatility == "high":
        warnings.append("High volatility — position sizing and stop distance should widen")
    if not bars:
        warnings.append("No market data was available — this analysis is a placeholder, not a read of the market")
    elif len(bars) < _MIN_BARS_FOR_REGIME:
        warnings.append(f"Only {len(bars)} bars available — regime detection needs {_MIN_BARS_FOR_REGIME}")

    # Levels. Without an ATR there is no defensible distance, so none is
    # invented — the old code fell back to a flat 0.5% of price and presented it
    # with the same authority as a measured one.
    if atr_value and price > 0:
        direction_sign = -1.0 if action == "sell" else 1.0
        stop_loss = round(price - direction_sign * atr_value * 1.5, 5)
        take_profit = round(price + direction_sign * atr_value * 2.5, 5)
        entry_zone = [round(price - atr_value * 0.3, 5), round(price + atr_value * 0.3, 5)]
        targets = {
            "bull": round(price + atr_value * 2, 5),
            "bear": round(price - atr_value * 2, 5),
            "base": round(price + direction_sign * atr_value, 5),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
        key_levels = [
            round(price - atr_value * 2, 5),
            round(price - atr_value, 5),
            round(price + atr_value, 5),
            round(price + atr_value * 2, 5),
        ]
        risk_assessment = (
            f"ATR(14) {atr_value:.4f} over {len(bars)} bars. "
            f"Stop {stop_loss:.4f} (1.5×ATR), target {take_profit:.4f} (2.5×ATR), R:R 1.67."
        )
    else:
        stop_loss = take_profit = None
        entry_zone = []
        targets = {"bull": price, "bear": price, "base": price, "stop_loss": None, "take_profit": None}
        key_levels = []
        risk_assessment = (
            "No ATR could be computed from the available data, so no stop or target is offered. "
            "Sizing this position from the numbers on screen is not supported."
        )
        warnings.append("No ATR available — no stop-loss or take-profit is being suggested")

    degraded = (not model.available) or model.fallback or not bars or len(bars) < _MIN_BARS_FOR_REGIME
    summary = _build_summary(symbol, regime, model, action, price, rsi_value)

    return {
        "id": str(uuid.uuid4()),
        "timestamp": ctx.timestamp or int(now_ms if now_ms is not None else time.time() * 1000),
        "context": ctx.model_dump(),
        # AIResult contract
        "direction": {"buy": "long", "sell": "short"}.get(action, "neutral"),
        "confidence": round(min(action_confidence, 0.95), 3),
        "reasoning": summary,
        "regime": regime.regime,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "entry_zone": entry_zone,
        "key_levels": key_levels,
        # AIAnalysis contract
        "regimeConfidence": round(regime.confidence, 3),
        "volatility": volatility,
        "trend": regime.trend,
        "summary": summary,
        "keyDrivers": key_drivers,
        "riskAssessment": risk_assessment,
        "recommendedAction": action,
        "actionConfidence": round(min(action_confidence, 0.95), 3),
        "priceTargets": targets,
        "timeHorizon": "4H–1D",
        "warnings": warnings,
        "features": model.features,
        # Provenance — the UI can now tell a real analysis from a degraded one.
        "modelVersion": model.model_version,
        "modelAvailable": model.available and not model.fallback,
        "barsAnalyzed": len(bars),
        "dataSource": data_source,
        "degraded": degraded,
        "rsi": round(rsi_value, 2) if rsi_value is not None else None,
        "atr": round(atr_value, 5) if atr_value is not None else None,
        # Legacy snake_case aliases retained for existing consumers.
        "data_source": data_source,
        "bars_analyzed": len(bars),
    }


# ── Data loading ──────────────────────────────────────────────────────────────


async def load_bars(symbol: str, timeframe: str, app_state: Any, limit: int = 200) -> tuple[list[dict], str]:
    """OHLCV for *symbol* from the platform's own price engine.

    Returns ``(bars, data_source)``. Never raises.

    The previous implementation embedded a fourth independent yfinance ticker
    map and called Yahoo directly, mapping XAUUSD to ``GC=F`` — the futures
    contract. ``config/multi_source_feed.yaml`` blanks Yahoo for spot metals on
    purpose, recording that quoting GLD (~$390) against spot gold (~$4,070)
    "would be far worse than no quote at all"; the same reasoning applies to
    front-month futures. Going through ``price_engine.get_ohlcv`` means the
    chart bot sees exactly what ``/api/trading/ohlcv`` and the chart itself see,
    which is also the only way the numbers on the two panels can agree.
    """
    import asyncio

    engine = getattr(app_state, "price_engine", None) if app_state is not None else None
    if engine is None:
        return [], "unavailable"

    try:
        data = await asyncio.wait_for(engine.get_ohlcv(symbol, timeframe, limit), timeout=25.0)
    except TimeoutError:
        logger.warning("chart_analysis: OHLCV timed out for %s %s", symbol, timeframe)
        return [], "timeout"
    except Exception as exc:
        logger.warning("chart_analysis: OHLCV failed for %s %s: %s", symbol, timeframe, exc)
        return [], "error"

    bars = [
        {
            "open": float(d.open),
            "high": float(d.high),
            "low": float(d.low),
            "close": float(d.close),
            "volume": float(getattr(d, "volume", 0.0) or 0.0),
        }
        for d in (data or [])
    ]
    if not bars:
        return [], "empty"
    if is_degenerate(bars):
        # The price engine's last-resort tier repeats the paper broker's static
        # price with volume=0. Indicators over it are all zero and render
        # identically to real ones.
        logger.warning("chart_analysis: %d flat bars for %s — discarding synthetic series", len(bars), symbol)
        return [], "synthetic"
    return bars, "price_engine"


# ── Cache ─────────────────────────────────────────────────────────────────────

_CACHE_KEY = "ai_analysis:{symbol}"


def cache_read(symbol: str) -> dict[str, Any] | None:
    """Most recent analysis for *symbol*, or None."""
    try:
        import json

        from cache.redis_client import get_sync_redis_client

        client = get_sync_redis_client()
        if not client:
            return None
        raw = client.get(_CACHE_KEY.format(symbol=symbol))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("chart_analysis: cache read failed: %s", exc)
        return None


def cache_write(symbol: str, payload: dict[str, Any], ttl: int = CACHE_TTL_SECONDS) -> bool:
    """Publish the analysis under ``ai_analysis:{symbol}``.

    ``api/ws_live.py`` has always read this key for six symbols on every
    broadcast cycle, under a comment asserting "The /trading/ai-analysis REST
    endpoint caches its result in Redis". It never did — there was not a single
    Redis reference in the handler. So the broadcaster performed six GETs per
    cycle that always returned nothing, and chart-bot clients never received the
    ``ai_analysis`` push the code exists to send. Writing the key makes that
    path live for the first time.

    A degraded analysis is deliberately not published: pushing a placeholder to
    every connected client is worse than pushing nothing.
    """
    if payload.get("degraded"):
        return False
    try:
        import json

        from cache.redis_client import get_sync_redis_client

        client = get_sync_redis_client()
        if not client:
            return False
        client.setex(_CACHE_KEY.format(symbol=symbol), ttl, json.dumps(payload, default=str))
        return True
    except Exception as exc:
        logger.debug("chart_analysis: cache write failed: %s", exc)
        return False


# ── Entry point ───────────────────────────────────────────────────────────────


async def analyze(ctx: ChartClickContext, app_state: Any, *, engine: Any | None = None) -> dict[str, Any]:
    """Full pipeline: load bars → run the model → compose. Never raises."""
    symbol = ctx.canonical_symbol()
    bars, data_source = await load_bars(symbol, ctx.timeframe, app_state)

    if engine is None:
        try:
            from ml.inference_engine import get_inference_engine

            engine = get_inference_engine()
        except Exception as exc:
            logger.warning("chart_analysis: inference engine unavailable: %s", exc)
            engine = None

    model = run_model(bars, symbol, engine)
    payload = compose(ctx, bars, model, data_source=data_source)
    cache_write(symbol, payload)
    return payload
