# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
charting/nuclear_ai_chart_engine.py
=====================================
Nuclear-grade AI chart engine — real-time backend orchestrator.

Pulls live data from:
  - data_layer.orchestrator  → OHLCV bars, ML features, tick data
  - news.nuclear_wordmap_scorer → geopolitical severity scoring
  - brain.nuclear_supervisor    → RL agent decisions + nuclear state
  - risk.orchestrator           → CVaR, exposure, kill-switch state

Produces a unified NuclearChartState broadcast over WebSocket every tick.

Architecture
------------
  NuclearAIChartEngine.start()
    └─ _tick_loop()          ← polls data_layer every TICK_INTERVAL_S
         ├─ _build_ohlcv()   ← aggregates bars per timeframe
         ├─ _score_news()    ← NuclearWordMapScorer on latest headlines
         ├─ _get_rl_state()  ← NuclearHopeFXSupervisor.get_status()
         ├─ _get_risk()      ← RiskOrchestrator snapshot
         ├─ _build_explain() ← human-readable explanation string
         └─ broadcast()      ← push NuclearChartState to all WS clients

NuclearChartState JSON schema (sent to frontend every tick):
  {
    "type": "nuclear_chart_update",
    "ts": <unix_ms>,
    "price": { "bid", "ask", "mid", "spread", "change_pct" },
    "bars": [ { "time", "open", "high", "low", "close", "volume" }, ... ],
    "nuclear": {
      "severity": 0-10,
      "action": "normal|pause_new_entries|hedge_mode|nuclear_mode",
      "nuclear_level": 0-3,
      "trading_paused": bool,
      "rl_action": 0-3,
      "rl_action_label": "NORMAL|PAUSE|HEDGE|NUCLEAR",
      "confidence": 0.0-1.0,
      "matched_terms": [...],
      "category_scores": {...},
      "vol_factor": float,
      "sentiment_factor": float,
      "explanation": "Human-readable reason string",
      "alert_active": bool,
      "historical_analog": "string|null"
    },
    "risk": {
      "cvar_95": float,
      "cvar_99": float,
      "var_95": float,
      "exposure": float,
      "max_risk": float,
      "kill_switch_active": bool,
      "kill_switch_reason": str|null,
      "daily_pnl": float,
      "drawdown_pct": float,
      "equity": float,
      "balance": float
    },
    "signals": [ { "direction", "confidence", "model", "entry", "sl", "tp", "reason" }, ... ],
    "equity_curve": [ { "time", "equity", "drawdown" }, ... ],
    "prediction_path": [ { "time", "price", "low", "high" }, ... ],
    "geopolitical_gauge": {
      "score": 0-100,
      "label": "NORMAL|ELEVATED|HIGH|CRITICAL",
      "color": "#hex",
      "flashing": bool
    }
  }
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from typing import ClassVar

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
TICK_INTERVAL_S: float = float(os.environ.get("CHART_TICK_INTERVAL", "1.0"))
MAX_BARS: int = 500
MAX_EQUITY_PTS: int = 500
MAX_SIGNALS: int = 50
NUCLEAR_ALERT_SEVERITY: int = 7

# RL action labels
RL_ACTION_LABELS = {0: "NORMAL", 1: "PAUSE", 2: "HEDGE", 3: "NUCLEAR"}

# Geopolitical gauge thresholds
_GAUGE_LEVELS = [
    (90, "CRITICAL", "#ff0033", True),
    (70, "HIGH", "#ff6600", True),
    (50, "ELEVATED", "#ffaa00", False),
    (0, "NORMAL", "#00ff88", False),
]

# Historical analog database (severity → analog description)
_HISTORICAL_ANALOGS: dict[int, str] = {
    10: "Similar to 2022 Russia-Ukraine invasion: Gold +12% in 48h, then -8% reversal. Expected drawdown: -28% if long.",
    9: "Similar to 2003 Iraq War start: Gold +6% spike, high volatility for 72h. CVaR elevated 3x.",
    8: "Similar to 2019 Iran-US escalation: Gold +4%, USD safe-haven bid. Pause recommended.",
    7: "Similar to 2022 Taiwan Strait tensions: Gold +2.5%, vol spike. Hedge positions advised.",
    6: "Similar to 2023 Middle East flare-up: Gold +1.5%, short-term uncertainty. Reduce size.",
    5: "Elevated geopolitical noise. Historical average: Gold +0.8% over 24h. Monitor closely.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Lazy imports — avoid circular deps at module load
# ─────────────────────────────────────────────────────────────────────────────


def _get_data_orchestrator():
    try:
        from data_layer.orchestrator import orchestrator

        return orchestrator
    except Exception as exc:
        logger.debug("data_layer.orchestrator unavailable: %s", exc)
        return None


def _get_nuclear_supervisor():
    try:
        from brain.nuclear_supervisor import get_nuclear_supervisor

        return get_nuclear_supervisor()
    except Exception as exc:
        logger.debug("nuclear_supervisor unavailable: %s", exc)
        return None


def _get_risk_orchestrator():
    try:
        from risk.orchestrator import risk_orchestrator

        return risk_orchestrator
    except Exception as exc:
        logger.debug("risk_orchestrator unavailable: %s", exc)
        return None


def _get_wordmap_scorer():
    try:
        from news.nuclear_wordmap_scorer import NuclearWordMapScorer

        return NuclearWordMapScorer()
    except Exception as exc:
        logger.debug("NuclearWordMapScorer unavailable: %s", exc)
        return None


def _get_explainer():
    try:
        from charting.nuclear_explainability import get_explainer

        return get_explainer()
    except Exception as exc:
        logger.debug("NuclearExplainabilityEngine unavailable: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# NuclearChartState builder
# ─────────────────────────────────────────────────────────────────────────────


class NuclearAIChartEngine:
    """
    Real-time chart data orchestrator for the nuclear dashboard.

    Usage:
        engine = NuclearAIChartEngine()
        engine.add_broadcast_callback(my_ws_broadcast_fn)
        await engine.start()
    """

    def __init__(self) -> None:
        self._running = False
        self._broadcast_callbacks: list[Callable[[dict], None]] = []

        # Ring buffers
        self._bars_1m: deque[dict] = deque(maxlen=MAX_BARS)
        self._bars_5m: deque[dict] = deque(maxlen=MAX_BARS)
        self._bars_1h: deque[dict] = deque(maxlen=MAX_BARS)
        self._equity_curve: deque[dict] = deque(maxlen=MAX_EQUITY_PTS)
        self._signals: deque[dict] = deque(maxlen=MAX_SIGNALS)
        self._nuclear_events: deque[dict] = deque(maxlen=100)

        # Cached state
        self._last_price: float = 0.0
        self._last_nuclear: dict = {}
        self._last_risk: dict = {}
        self._wordmap_scorer = None
        self._tick_count: int = 0

        # Lazy-init heavy components
        self._data_orch = None
        self._nuclear_sup = None
        self._risk_orch = None
        self._explainer = None

    # ── Public API ────────────────────────────────────────────────────────────

    def add_broadcast_callback(self, fn: Callable[[dict], None]) -> None:
        """Register a callback that receives the full NuclearChartState dict."""
        self._broadcast_callbacks.append(fn)

    def remove_broadcast_callback(self, fn: Callable[[dict], None]) -> None:
        self._broadcast_callbacks = [c for c in self._broadcast_callbacks if c is not fn]

    async def start(self) -> None:
        """Start the tick loop. Runs until stop() is called."""
        self._running = True
        self._wordmap_scorer = _get_wordmap_scorer()
        self._data_orch = _get_data_orchestrator()
        self._nuclear_sup = _get_nuclear_supervisor()
        self._risk_orch = _get_risk_orchestrator()
        self._explainer = _get_explainer()
        logger.info(
            "NuclearAIChartEngine started | data=%s nuclear=%s risk=%s wordmap=%s",
            self._data_orch is not None,
            self._nuclear_sup is not None,
            self._risk_orch is not None,
            self._wordmap_scorer is not None,
        )
        await self._tick_loop()

    async def stop(self) -> None:
        self._running = False
        logger.info("NuclearAIChartEngine stopped.")

    def get_snapshot(self) -> dict:
        """Return the latest chart state synchronously (for HTTP polling)."""
        return self._build_state()

    def inject_news_event(self, text: str, volatility: float = 1.0, sentiment: float = 0.0) -> dict:
        """
        Score a news event immediately and return the nuclear assessment.
        Called by connect_to_life.py when a news item arrives.
        """
        if self._wordmap_scorer is None:
            self._wordmap_scorer = _get_wordmap_scorer()
        if self._wordmap_scorer is None:
            return {
                "severity": 0,
                "action": "normal",
                "explanation": "Scorer unavailable",
            }

        severity, action, raw_score, meta = self._wordmap_scorer.score_event(text, volatility, sentiment)
        nuclear_state = self._build_nuclear_state(severity, action, raw_score, meta)
        self._last_nuclear = nuclear_state

        # Record event in history
        self._nuclear_events.append(
            {
                "ts": int(time.time() * 1000),
                "text": text[:200],
                "severity": severity,
                "action": action,
                "explanation": nuclear_state.get("explanation", ""),
            }
        )

        # Broadcast immediately on high-severity events
        if severity >= NUCLEAR_ALERT_SEVERITY:
            state = self._build_state()
            self._broadcast(state)

        return nuclear_state

    # ── Tick loop ─────────────────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                state = await asyncio.get_event_loop().run_in_executor(None, self._build_state)
                self._broadcast(state)
                self._tick_count += 1
            except Exception as exc:
                logger.warning("Chart engine tick error: %s", exc)
            await asyncio.sleep(TICK_INTERVAL_S)

    def _broadcast(self, state: dict) -> None:
        for cb in self._broadcast_callbacks:
            try:
                cb(state)
            except Exception as exc:
                logger.warning("Broadcast callback error: %s", exc)

    # ── State builder ─────────────────────────────────────────────────────────

    def _build_state(self) -> dict:
        """Assemble the full NuclearChartState from all data sources."""
        ts = int(time.time() * 1000)

        price_data = self._get_price_data()
        risk_data = self._get_risk_data()
        nuclear_data = self._get_nuclear_data(risk_data)
        bars = self._get_bars()
        signals = self._get_signals()
        equity_curve = list(self._equity_curve)
        prediction_path = self._build_prediction_path(price_data, nuclear_data)
        gauge = self._build_geopolitical_gauge(nuclear_data)

        return {
            "type": "nuclear_chart_update",
            "ts": ts,
            "price": price_data,
            "bars": bars,
            "nuclear": nuclear_data,
            "risk": risk_data,
            "signals": signals,
            "equity_curve": equity_curve,
            "prediction_path": prediction_path,
            "geopolitical_gauge": gauge,
            "nuclear_events": list(self._nuclear_events)[-20:],
        }

    # ── Price data ────────────────────────────────────────────────────────────

    def _get_price_data(self) -> dict:
        if self._data_orch is None:
            self._data_orch = _get_data_orchestrator()

        try:
            if self._data_orch:
                tick = self._data_orch.get_latest_tick()
                if tick:
                    mid = getattr(tick, "mid", None) or ((getattr(tick, "bid", 0) + getattr(tick, "ask", 0)) / 2)
                    bid = getattr(tick, "bid", mid)
                    ask = getattr(tick, "ask", mid)
                    spread = ask - bid
                    change_pct = getattr(tick, "change_pct", 0.0)
                    self._last_price = mid
                    return {
                        "bid": round(bid, 3),
                        "ask": round(ask, 3),
                        "mid": round(mid, 3),
                        "spread": round(spread, 3),
                        "change_pct": round(change_pct, 4),
                        "source": getattr(tick, "source", "live"),
                    }
        except Exception as exc:
            logger.debug("Price data error: %s", exc)

        # Fallback: return last known price
        p = self._last_price or 2650.0
        return {
            "bid": p - 0.15,
            "ask": p + 0.15,
            "mid": p,
            "spread": 0.30,
            "change_pct": 0.0,
            "source": "cached",
        }

    # ── OHLCV bars ────────────────────────────────────────────────────────────

    def _get_bars(self) -> dict[str, list[dict]]:
        """Return bars for 1m, 5m, 1h timeframes."""
        if self._data_orch is None:
            self._data_orch = _get_data_orchestrator()

        result: dict[str, list[dict]] = {"1m": [], "5m": [], "1h": []}
        try:
            if self._data_orch and hasattr(self._data_orch, "get_ohlcv"):
                for tf in ("1m", "5m", "1h"):
                    bars = self._data_orch.get_ohlcv(timeframe=tf, bars=300)
                    if bars:
                        result[tf] = [
                            {
                                "time": int(b.get("time", b.get("timestamp", 0))),
                                "open": round(b["open"], 3),
                                "high": round(b["high"], 3),
                                "low": round(b["low"], 3),
                                "close": round(b["close"], 3),
                                "volume": round(b.get("volume", 0), 2),
                            }
                            for b in bars
                        ]
        except Exception as exc:
            logger.debug("OHLCV bars error: %s", exc)

        # Fallback: return cached bars
        if not result["1m"] and self._bars_1m:
            result["1m"] = list(self._bars_1m)
        return result

    # ── Nuclear state ─────────────────────────────────────────────────────────

    def _get_nuclear_data(self, risk_data: dict) -> dict:
        """Get nuclear state from supervisor + wordmap scorer."""
        if self._nuclear_sup is None:
            self._nuclear_sup = _get_nuclear_supervisor()

        # Get supervisor state
        sup_status: ClassVar[dict] = {}
        if self._nuclear_sup:
            try:
                sup_status = self._nuclear_sup.get_status()
            except Exception as exc:
                logger.debug("Nuclear supervisor status error: %s", exc)

        nuclear_level = sup_status.get("nuclear_level", 0)
        trading_paused = sup_status.get("trading_paused", False)
        rl_loaded = sup_status.get("rl_agent_loaded", False)

        # Get last event from supervisor history
        last_event = sup_status.get("last_event") or {}
        severity = last_event.get("severity", 0)
        action = last_event.get("action", "normal")
        raw_score = last_event.get("raw_score", 0.0)
        meta = last_event.get("meta", {})

        # If we have a cached nuclear state from inject_news_event, use it
        if self._last_nuclear and self._last_nuclear.get("severity", 0) > severity:
            return self._last_nuclear

        return self._build_nuclear_state(
            severity,
            action,
            raw_score,
            meta,
            nuclear_level,
            trading_paused,
            rl_loaded,
            sup_status,
        )

    def _build_nuclear_state(
        self,
        severity: int,
        action: str,
        raw_score: float,
        meta: dict,
        nuclear_level: int = 0,
        trading_paused: bool = False,
        rl_loaded: bool = False,
        sup_status: dict | None = None,
    ) -> dict:
        """Build the nuclear sub-object for the chart state."""
        matched_terms = meta.get("matched_terms", [])
        category_scores = meta.get("category_scores", {})
        confidence = meta.get("confidence", 0.0)
        vol_factor = meta.get("vol_factor", 1.0)
        sentiment_factor = meta.get("sentiment_factor", 0.0)

        # Determine RL action — prefer action string over nuclear_level
        # so inject_news_event() produces the correct label even without a live supervisor
        _action_to_rl = {
            "normal": 0,
            "pause_new_entries": 1,
            "hedge_mode": 2,
            "nuclear_mode": 3,
        }
        rl_action = _action_to_rl.get(action, min(nuclear_level, 3))
        rl_action_label = RL_ACTION_LABELS.get(rl_action, "NORMAL")

        # Build human-readable explanation — use explainability engine if available
        explanation = self._build_explanation(
            severity,
            action,
            rl_action_label,
            matched_terms,
            category_scores,
            confidence,
            vol_factor,
            sentiment_factor,
            trading_paused,
            rl_loaded,
        )

        # Enrich with structured explainability engine output
        explain_detail: ClassVar[dict] = {}
        if self._explainer is None:
            self._explainer = _get_explainer()
        if self._explainer is not None:
            try:
                explain_detail = self._explainer.explain_to_dict(
                    severity=severity,
                    action=action,
                    rl_action=rl_action,
                    rl_loaded=rl_loaded,
                    meta=meta,
                    risk_data=self._last_risk,
                    price=self._last_price,
                )
                # Use the richer summary as the explanation
                if explain_detail.get("summary"):
                    explanation = explain_detail["summary"]
            except Exception as exc:
                logger.debug("Explainability engine error: %s", exc)

        # Historical analog
        analog = explain_detail.get("historical_analog")
        if analog is None:
            for thresh in sorted(_HISTORICAL_ANALOGS.keys(), reverse=True):
                if severity >= thresh:
                    analog = _HISTORICAL_ANALOGS[thresh]
                    break

        alert_active = severity >= NUCLEAR_ALERT_SEVERITY or trading_paused

        return {
            "severity": severity,
            "action": action,
            "nuclear_level": nuclear_level,
            "trading_paused": trading_paused,
            "rl_action": rl_action,
            "rl_action_label": rl_action_label,
            "rl_agent_loaded": rl_loaded,
            "confidence": round(confidence, 4),
            "raw_score": round(raw_score, 4),
            "matched_terms": matched_terms[:10],  # top 10 for UI
            "category_scores": category_scores,
            "vol_factor": round(vol_factor, 4),
            "sentiment_factor": round(sentiment_factor, 4),
            "explanation": explanation,
            "alert_active": alert_active,
            "historical_analog": analog,
            "cooldown_remaining": (sup_status or {}).get("cooldown_remaining", 0.0),
            "event_count": (sup_status or {}).get("event_history_count", 0),
            # Structured explainability (SHAP-style) — populated when engine available
            "feature_scores": explain_detail.get("feature_scores", []),
            "decision_trace": explain_detail.get("decision_trace", []),
            "risk_narrative": explain_detail.get("risk_narrative", ""),
            "action_advice": explain_detail.get("action_advice", ""),
            "confidence_breakdown": explain_detail.get("confidence_breakdown", {}),
        }

    def _build_explanation(
        self,
        severity: int,
        action: str,
        rl_label: str,
        matched_terms: list[dict],
        category_scores: dict,
        confidence: float,
        vol_factor: float,
        sentiment_factor: float,
        trading_paused: bool,
        rl_loaded: bool,
    ) -> str:
        """Generate a human-readable co-pilot explanation."""
        if severity == 0 and not trading_paused:
            return "All clear. No geopolitical risk detected. Normal trading conditions."

        parts: ClassVar[list[str]] = []

        # RL decision
        agent_type = "RL agent (PPO)" if rl_loaded else "Rule-based fallback"
        parts.append(f"{agent_type} triggered {rl_label} (severity={severity}/10).")

        # Top matched terms
        if matched_terms:
            top = sorted(matched_terms, key=lambda x: x.get("contribution", 0), reverse=True)[:3]
            terms_str = ", ".join(f'"{t["term"]}" ({t["category"]}, w={t["weight"]:.1f})' for t in top)
            parts.append(f"WORDMAP matched: {terms_str}.")

        # Category breakdown
        if category_scores:
            cats = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)[:2]
            cats_str = ", ".join(f"{k}={v:.1f}" for k, v in cats)
            parts.append(f"Risk categories: {cats_str}.")

        # Amplifiers
        amplifiers = []
        if vol_factor > 1.1:
            amplifiers.append(f"volatility spike (×{vol_factor:.2f})")
        if sentiment_factor > 0.2:
            amplifiers.append(f"negative sentiment (+{sentiment_factor:.2f})")
        if amplifiers:
            parts.append(f"Amplified by: {', '.join(amplifiers)}.")

        # Confidence
        parts.append(f"Confidence: {confidence * 100:.0f}%.")

        # Action description
        action_desc = {
            "normal": "Continuing normal trading.",
            "pause_new_entries": "New entries paused. Existing positions held.",
            "hedge_mode": "Hedge mode active. Max risk reduced to 15%. Inverse hedges opened.",
            "nuclear_mode": "FULL LIQUIDATION. All positions closed. Trading halted.",
        }.get(action, action)
        parts.append(action_desc)

        return " ".join(parts)

    # ── Risk data ─────────────────────────────────────────────────────────────

    def _get_risk_data(self) -> dict:
        if self._risk_orch is None:
            self._risk_orch = _get_risk_orchestrator()

        defaults = {
            "cvar_95": 0.0,
            "cvar_99": 0.0,
            "var_95": 0.0,
            "exposure": 0.0,
            "max_risk": 1.0,
            "kill_switch_active": False,
            "kill_switch_reason": None,
            "daily_pnl": 0.0,
            "drawdown_pct": 0.0,
            "equity": 0.0,
            "balance": 0.0,
        }

        try:
            if self._risk_orch:
                status = self._risk_orch.get_status() if hasattr(self._risk_orch, "get_status") else {}
                defaults.update(
                    {
                        "exposure": round(status.get("current_exposure", 0.0), 4),
                        "max_risk": round(status.get("max_risk_fraction", 1.0), 4),
                        "kill_switch_active": status.get("kill_switch_active", False),
                        "kill_switch_reason": status.get("kill_switch_reason"),
                    }
                )
        except Exception as exc:
            logger.debug("Risk data error: %s", exc)

        # Merge engine status if available
        try:
            from data_layer.orchestrator import orchestrator as dl

            if dl and hasattr(dl, "get_ml_features"):
                feats = dl.get_ml_features()
                if feats:
                    defaults["cvar_95"] = round(feats.get("cvar_95", 0.0), 4)
                    defaults["cvar_99"] = round(feats.get("cvar_99", 0.0), 4)
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        self._last_risk = defaults
        return defaults

    # ── Signals ───────────────────────────────────────────────────────────────

    def _get_signals(self) -> list[dict]:
        try:
            if self._data_orch and hasattr(self._data_orch, "get_ml_features"):
                feats = self._data_orch.get_ml_features()
                if feats:
                    direction = (
                        "long"
                        if feats.get("signal_direction", 0) > 0
                        else ("short" if feats.get("signal_direction", 0) < 0 else "neutral")
                    )
                    confidence = feats.get("signal_confidence", 0.5)
                    price = self._last_price or 2650.0
                    signal = {
                        "id": f"sig_{int(time.time())}",
                        "direction": direction,
                        "confidence": round(confidence, 4),
                        "model": "XGBoost+RL",
                        "entry": round(price, 3),
                        "sl": round(price * (0.998 if direction == "long" else 1.002), 3),
                        "tp": round(price * (1.004 if direction == "long" else 0.996), 3),
                        "reason": feats.get("signal_reason", "ML ensemble signal"),
                        "ts": int(time.time() * 1000),
                    }
                    self._signals.appendleft(signal)
        except Exception as exc:
            logger.debug("Signals error: %s", exc)

        return list(self._signals)[:20]

    # ── Prediction path ───────────────────────────────────────────────────────

    def _build_prediction_path(self, price_data: dict, nuclear_data: dict) -> list[dict]:
        """
        Build a forward price prediction path with confidence cones.
        Under nuclear conditions, shows expected drawdown scenarios.
        """
        mid = price_data.get("mid", self._last_price or 2650.0)
        severity = nuclear_data.get("severity", 0)
        now_s = int(time.time())
        path: ClassVar[list[dict]] = []

        # Base drift per minute (annualised vol ~15% for gold)
        base_vol_per_min = mid * 0.0001  # ~0.01% per minute

        # Under nuclear conditions, widen cones dramatically
        vol_multiplier = 1.0
        if severity >= 9:
            vol_multiplier = 8.0
        elif severity >= 7:
            vol_multiplier = 4.0
        elif severity >= 5:
            vol_multiplier = 2.0

        vol = base_vol_per_min * vol_multiplier

        # Generate 30-bar forward path (1 bar = 1 minute)
        for i in range(1, 31):
            t = now_s + i * 60
            # Base path: flat (no directional bias in nuclear mode)
            base = mid
            cone_width = vol * (i**0.5)  # sqrt-time scaling
            path.append(
                {
                    "time": t,
                    "price": round(base, 3),
                    "low": round(base - cone_width, 3),
                    "high": round(base + cone_width, 3),
                    "scenario": "nuclear" if severity >= 7 else "normal",
                }
            )

        return path

    # ── Geopolitical gauge ────────────────────────────────────────────────────

    def _build_geopolitical_gauge(self, nuclear_data: dict) -> dict:
        severity = nuclear_data.get("severity", 0)
        score = min(100, int(severity * 10))

        label, color, flashing = "NORMAL", "#00ff88", False
        for thresh, lbl, clr, flash in _GAUGE_LEVELS:
            if score >= thresh:
                label, color, flashing = lbl, clr, flash
                break

        return {
            "score": score,
            "label": label,
            "color": color,
            "flashing": flashing,
            "severity": severity,
        }

    # ── Equity curve update ───────────────────────────────────────────────────

    def record_equity_point(self, equity: float, balance: float, annotation: str | None = None) -> None:
        """Called by connect_to_life.py on each status poll to record equity."""
        drawdown = 0.0
        if balance > 0:
            drawdown = round((equity - balance) / balance * 100, 4)
        self._equity_curve.append(
            {
                "time": int(time.time()),
                "equity": round(equity, 2),
                "drawdown": drawdown,
                "annotation": annotation,
            }
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_engine_instance: NuclearAIChartEngine | None = None


def get_chart_engine() -> NuclearAIChartEngine:
    """Return the module-level singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = NuclearAIChartEngine()
    return _engine_instance
