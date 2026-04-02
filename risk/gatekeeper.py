# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/gatekeeper.py
==================
Gatekeeper — pre-trade signal filter wired to the MarketDataOrchestrator.

All checks consume data exclusively from the orchestrator. No broker API
is called for market data anywhere in this file.

Check order (fail-fast, most critical first)
--------------------------------------------
1.  Kill switch active                — hard block, no recovery
2.  Post-breach pause window          — temporary block
3.  Daily drawdown limit              — block when daily DD >= limit
4.  Max drawdown limit                — block when total DD >= limit
5.  Data quality gate                 — block when orchestrator quality < threshold
6.  News blackout (orchestrator)      — block during high-impact news windows
7.  Macro impact blackout             — block when impact_score > threshold
8.  Extreme sentiment blackout        — block when |sentiment| > threshold
9.  Max daily trades cap              — block when daily count >= cap
10. Confidence floor                  — block when signal confidence < floor
11. Spread gate                       — block when spread > max_spread_usd

On any breach
-------------
- Publishes breach event to hopefx:breach channel.
- Sets pause flag for PAUSE_AFTER_BREACH_S seconds (except kill-switch).
- Logs at WARNING with structured fields.
- Writes rejection to DataLineageStore.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from core.event_bus import bus, CH_SIGNAL, CH_BREACH

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
_DAILY_DD_LIMIT: float = float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05"))
_MAX_DD_LIMIT: float = float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10"))
_MIN_CONFIDENCE: float = float(os.getenv("GATEKEEPER_MIN_CONF", "0.55"))
_MAX_DAILY_TRADES: int = int(os.getenv("GATEKEEPER_MAX_DAILY_TRADES", "20"))
_PAUSE_AFTER_BREACH_S: float = float(os.getenv("GATEKEEPER_PAUSE_S", "60"))
_MIN_DATA_QUALITY: float = float(os.getenv("GATEKEEPER_MIN_DATA_QUALITY", "0.40"))
_MAX_SPREAD_USD: float = float(os.getenv("GATEKEEPER_MAX_SPREAD_USD", "2.00"))
_SENT_BLACKOUT_THRESH: float = float(os.getenv("GATEKEEPER_SENT_BLACKOUT", "0.85"))
_IMPACT_BLACKOUT: float = float(os.getenv("GATEKEEPER_IMPACT_BLACKOUT", "0.75"))

# Public aliases used by tests and external callers
MAX_DAILY_TRADES: int = _MAX_DAILY_TRADES
DAILY_DD_LIMIT_PCT: float = _DAILY_DD_LIMIT


# ── Gate result ───────────────────────────────────────────────────────────────


@dataclass
class GateResult:
    passed: bool
    reason: str = ""
    failures: list[dict] = field(default_factory=list)


# ── News calendar ─────────────────────────────────────────────────────────────


class _NewsCalendar:
    """Lightweight news-event calendar for pre-trade blackout checks.

    Holds a list of high-impact event datetimes.  ``is_blackout()`` returns
    True when any event falls within ``window_minutes`` of *now*.

    The orchestrator's MacroCalendarEngine is the authoritative source in
    production; this class is used when no orchestrator is wired (tests,
    standalone mode).
    """

    _BLACKOUT_MINUTES: int = int(os.getenv("NEWS_BLACKOUT_MINUTES", "30"))

    def __init__(self) -> None:
        self._events: list[datetime] = []

    def add_event(self, dt: datetime) -> None:
        """Register a high-impact event datetime (timezone-aware)."""
        self._events.append(dt)

    def is_blackout(self, window_minutes: int = None) -> bool:
        """Return True if any registered event is within *window_minutes* of now."""
        window = window_minutes if window_minutes is not None else self._BLACKOUT_MINUTES
        now = datetime.now(UTC)
        cutoff = timedelta(minutes=window)
        for ev in self._events:
            # Normalise naive datetimes to UTC
            if ev.tzinfo is None:
                ev = ev.replace(tzinfo=UTC)  # noqa: PLW2901
            if abs(now - ev) <= cutoff:
                return True
        return False

    def clear(self) -> None:
        self._events.clear()


# ── Equity tracker ────────────────────────────────────────────────────────────


class _EquityTracker:
    def __init__(self, initial: float) -> None:
        self._initial = initial
        self._peak = initial
        self._current = initial
        self._day_open = initial
        self._day = datetime.now(UTC).day

    def update(self, equity: float) -> None:
        today = datetime.now(UTC).day
        if today != self._day:
            self._day_open = equity
            self._day = today
        self._current = equity
        self._peak = max(self._peak, equity)

    @property
    def daily_dd(self) -> float:
        if self._day_open <= 0:
            return 0.0
        return max(0.0, (self._day_open - self._current) / self._day_open)

    @property
    def max_dd(self) -> float:
        if self._peak <= 0:
            return 0.0
        return max(0.0, (self._peak - self._current) / self._peak)


# ── Gatekeeper ────────────────────────────────────────────────────────────────


class Gatekeeper:
    """
    Pre-trade signal filter.

    Two usage modes:
    1. Event-bus mode: await gk.start() — subscribes to hopefx:signal,
       routes passing signals to hopefx:order.
    2. Direct mode: result = await gk.evaluate(signal) — called directly
       by HopeFXEngine for synchronous gate evaluation.

    Both modes consume orchestrator data for all market-data checks.
    """

    def __init__(self, orchestrator=None, lineage_store=None) -> None:
        initial_balance = float(os.getenv("INITIAL_BALANCE", "100000"))
        self._orch = orchestrator
        self._lineage = lineage_store
        self._equity = _EquityTracker(initial_balance)
        self._calendar = _NewsCalendar()
        self._kill_active: bool = False
        self._paused_until: float = 0.0
        self._daily_trades: int = 0
        self._trade_day: int = datetime.now(UTC).day
        self._running: bool = False
        self._pass_count: int = 0
        self._block_count: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Event-bus mode: subscribe to signals and route to orders."""
        self._running = True
        logger.info(
            "Gatekeeper starting — daily_dd=%.1f%% max_dd=%.1f%% min_conf=%.2f",
            _DAILY_DD_LIMIT * 100,
            _MAX_DD_LIMIT * 100,
            _MIN_CONFIDENCE,
        )
        asyncio.create_task(self._breach_listener(), name="gatekeeper_breach_listener")
        await self._signal_consumer()

    async def stop(self) -> None:
        self._running = False
        logger.info(
            "Gatekeeper stopped — passed=%d blocked=%d",
            self._pass_count,
            self._block_count,
        )

    # ── Direct evaluation (called by HopeFXEngine) ────────────────────────────

    async def evaluate(self, signal) -> GateResult:
        """
        Evaluate a signal against all pre-trade checks.

        Consumes orchestrator data for quality, sentiment, and blackout checks.
        Returns GateResult(passed=True) if all checks pass.
        """
        self._reset_daily_counter()
        failures = self._run_checks_on_signal(signal)

        if not failures:
            self._pass_count += 1
            self._daily_trades += 1
            return GateResult(passed=True)

        self._block_count += 1
        primary = failures[0]["reason"]
        logger.warning(
            "GATE BLOCK signal_id=%s reason=%s all_failures=%s",
            getattr(signal, "signal_id", "?"),
            primary,
            [f["reason"] for f in failures],
        )
        self._write_rejection_lineage(signal, primary, failures)

        if primary != "kill_switch_active":
            self._paused_until = time.monotonic() + _PAUSE_AFTER_BREACH_S

        return GateResult(passed=False, reason=primary, failures=failures)

    # ── Event-bus signal consumer ─────────────────────────────────────────────

    async def _signal_consumer(self) -> None:
        async for msg in bus.subscribe(CH_SIGNAL):
            if not self._running:
                break
            if msg.get("type") == "heartbeat":
                continue
            try:
                await self._on_bus_signal(msg)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Gatekeeper signal error: %s", exc)

    async def _breach_listener(self) -> None:
        async for msg in bus.subscribe(CH_BREACH):
            if not self._running:
                break
            reason = msg.get("reason", "")
            if reason == "equity_update":
                equity = float(msg.get("equity", 0))
                if equity > 0:
                    self._equity.update(equity)
            elif reason in ("kill_switch", "kill_event"):
                self._kill_active = True
                logger.critical("Gatekeeper: kill event received — all trading halted.")

    async def _on_bus_signal(self, signal: dict) -> None:
        self._reset_daily_counter()
        failures = self._run_checks_on_dict(signal)

        if not failures:
            self._pass_count += 1
            self._daily_trades += 1
            order_request = {
                "type": "order_request",
                "symbol": signal.get("symbol"),
                "direction": signal.get("direction"),
                "confidence": signal.get("confidence"),
                "mid": signal.get("mid"),
                "timestamp": datetime.now(UTC).isoformat(),
                "signal_ref": signal.get("tick_seq"),
            }
            logger.info(
                "GATE PASS  %s %s  conf=%.4f",
                signal.get("direction"),
                signal.get("symbol"),
                signal.get("confidence", 0),
            )
            await bus.publish_order(order_request)
        else:
            self._block_count += 1
            primary = failures[0]["reason"]
            breach = {
                "type": "breach",
                "reason": primary,
                "checks_failed": failures,
                "signal": signal,
                "daily_dd": round(self._equity.daily_dd * 100, 4),
                "max_dd": round(self._equity.max_dd * 100, 4),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await bus.publish_breach(breach)
            if primary != "kill_switch_active":
                self._paused_until = time.monotonic() + _PAUSE_AFTER_BREACH_S

    # ── Core checks ───────────────────────────────────────────────────────────

    def _run_checks_on_signal(self, signal) -> list[dict]:
        """Run checks against an ExecutionSignal object (direct mode)."""
        equity = getattr(self, "_equity", _EquityTracker(0))
        return self._run_checks_params(
            kill_active=getattr(self, "_kill_active", False),
            paused_until=getattr(self, "_paused_until", 0.0),
            daily_dd=equity.daily_dd,
            max_dd=equity.max_dd,
            data_quality=self._get_data_quality(signal),
            is_blackout=self._get_blackout(),
            impact_score=self._get_impact_score(signal),
            sentiment_score=self._get_sentiment(signal),
            daily_trades=getattr(self, "_daily_trades", 0),
            confidence=getattr(signal, "confidence", 0.0),
            spread=getattr(signal, "tick_spread", 0.0),
        )

    def _run_checks_on_dict(self, signal: dict) -> list[dict]:
        """Run checks against a signal dict (event-bus mode)."""
        equity = getattr(self, "_equity", _EquityTracker(0))
        return self._run_checks_params(
            kill_active=getattr(self, "_kill_active", False),
            paused_until=getattr(self, "_paused_until", 0.0),
            daily_dd=equity.daily_dd,
            max_dd=equity.max_dd,
            data_quality=self._get_data_quality_from_orch(),
            is_blackout=self._get_blackout(),
            impact_score=self._get_impact_score_from_orch(),
            sentiment_score=self._get_sentiment_from_orch(),
            daily_trades=getattr(self, "_daily_trades", 0),
            confidence=float(signal.get("confidence", 0.0)),
            spread=float(signal.get("spread", 0.0)),
        )

    def _run_checks(self, signal) -> list[dict]:
        """Unified entry-point: accepts a signal dict or ExecutionSignal object.

        This is the method called by tests and external code that has a
        pre-constructed Gatekeeper instance and wants to evaluate a signal
        without going through the async event-bus path.
        """
        if isinstance(signal, dict):
            return self._run_checks_on_dict(signal)
        return self._run_checks_on_signal(signal)

    @staticmethod
    def _run_checks_params(
        kill_active: bool,
        paused_until: float,
        daily_dd: float,
        max_dd: float,
        data_quality: float,
        is_blackout: bool,
        impact_score: float,
        sentiment_score: float,
        daily_trades: int,
        confidence: float,
        spread: float,
    ) -> list[dict]:
        failures: list[dict] = []

        # 1. Kill switch
        if kill_active:
            return [{"reason": "kill_switch_active", "detail": "Kill switch active."}]

        # 2. Pause window
        _paused = paused_until if paused_until is not None else 0.0
        if time.monotonic() < _paused:
            remaining = _paused - time.monotonic()
            return [{"reason": "post_breach_pause", "detail": f"{remaining:.0f}s remaining"}]

        # 3. Daily drawdown
        if daily_dd >= _DAILY_DD_LIMIT:
            failures.append(
                {
                    "reason": "daily_dd_limit",
                    "detail": f"Daily DD {daily_dd * 100:.2f}% >= {_DAILY_DD_LIMIT * 100:.1f}%",
                }
            )

        # 4. Max drawdown
        if max_dd >= _MAX_DD_LIMIT:
            failures.append(
                {
                    "reason": "max_dd_limit",
                    "detail": f"Max DD {max_dd * 100:.2f}% >= {_MAX_DD_LIMIT * 100:.1f}%",
                }
            )

        # 5. Data quality (orchestrator authoritative)
        if data_quality < _MIN_DATA_QUALITY:
            failures.append(
                {
                    "reason": "data_quality_low",
                    "detail": f"Quality {data_quality:.3f} < {_MIN_DATA_QUALITY}",
                }
            )

        # 6. News blackout (orchestrator MacroCalendarEngine)
        if is_blackout:
            failures.append(
                {
                    "reason": "news_blackout",
                    "detail": "High-impact news event within blackout window.",
                }
            )

        # 7. Macro impact blackout
        if impact_score > _IMPACT_BLACKOUT:
            failures.append(
                {
                    "reason": "macro_impact_blackout",
                    "detail": f"Impact {impact_score:.3f} > {_IMPACT_BLACKOUT}",
                }
            )

        # 8. Extreme sentiment blackout
        if abs(sentiment_score) > _SENT_BLACKOUT_THRESH:
            failures.append(
                {
                    "reason": "sentiment_blackout",
                    "detail": f"Sentiment {sentiment_score:.3f} exceeds ±{_SENT_BLACKOUT_THRESH}",
                }
            )

        # 9. Daily trade cap
        if daily_trades >= _MAX_DAILY_TRADES:
            failures.append(
                {
                    "reason": "daily_trade_cap",
                    "detail": f"Trades {daily_trades} >= cap {_MAX_DAILY_TRADES}",
                }
            )

        # 10. Confidence floor
        if confidence < _MIN_CONFIDENCE:
            failures.append(
                {
                    "reason": "low_confidence",
                    "detail": f"Confidence {confidence:.4f} < floor {_MIN_CONFIDENCE}",
                }
            )

        # 11. Spread gate
        if spread > _MAX_SPREAD_USD:
            failures.append(
                {
                    "reason": "spread_too_wide",
                    "detail": f"Spread ${spread:.4f} > max ${_MAX_SPREAD_USD}",
                }
            )

        return failures

    # ── Orchestrator data access ──────────────────────────────────────────────

    def _get_data_quality(self, signal) -> float:
        """Orchestrator tick confidence is authoritative."""
        q = self._get_data_quality_from_orch()
        if q > 0:
            return q
        return getattr(signal, "data_quality", 1.0)

    def _get_data_quality_from_orch(self) -> float:
        if getattr(self, "_orch", None) is None:
            return 1.0
        try:
            tick = getattr(self, "_orch", None) and self._orch.get_latest_tick()
            return tick.confidence if tick else 1.0
        except Exception as _dq_exc:
            logger.debug("Data quality check failed (%s) — defaulting to 1.0", _dq_exc)
            return 1.0

    def _get_blackout(self) -> bool:
        """Return True when a news/macro blackout is active.

        Priority
        --------
        1. Orchestrator MacroCalendarEngine (authoritative in production).
           Calls orchestrator.is_blackout_window() which delegates to
           MacroCalendarEngine.is_blackout_window().  The window is
           controlled by NEWS_BLACKOUT_BEFORE_MIN / NEWS_BLACKOUT_AFTER_MIN
           env vars (default 5 min each side of a HIGH-impact event).

           NOTE: We call is_blackout_window() directly — NOT is_safe_to_trade().
           is_safe_to_trade() bundles feed-liveness and tick-quality checks
           that are already handled by separate gates (check 5 above).
           Mixing them here would cause a blackout block when a feed is
           temporarily down, masking the real reason in logs.

        2. Local _NewsCalendar (used in tests / standalone mode when no
           orchestrator is wired).  Controlled by NEWS_BLACKOUT_MINUTES
           env var (default 30 min).
        """
        # Orchestrator is authoritative — check first when available.
        if getattr(self, "_orch", None) is not None:
            try:
                return self._orch.is_blackout_window()
            except Exception as _bo_exc:
                logger.debug("Orchestrator blackout check failed (%s) — falling back to local calendar", _bo_exc)

        # Local calendar fallback (tests / standalone mode)
        cal = getattr(self, "_calendar", None)
        return bool(cal is not None and cal.is_blackout())

    def _get_impact_score(self, signal) -> float:
        score = self._get_impact_score_from_orch()
        if score > 0:
            return score
        return getattr(signal, "impact_score", 0.0)

    def _get_impact_score_from_orch(self) -> float:
        if getattr(self, "_orch", None) is None:
            return 0.0
        try:
            return self._orch.get_macro_impact_score()
        except Exception as _imp_exc:
            logger.debug("Impact score fetch failed (%s) — defaulting to 0.0", _imp_exc)
            return 0.0

    def _get_sentiment(self, signal) -> float:
        score = self._get_sentiment_from_orch()
        if score != 0.0:
            return score
        return getattr(signal, "sentiment_score", 0.0)

    def _get_sentiment_from_orch(self) -> float:
        if getattr(self, "_orch", None) is None:
            return 0.0
        try:
            features = self._orch.get_ml_features()
            return float(features.get("news_sentiment_score", 0.0))
        except Exception as _sent_exc:
            logger.debug("Sentiment score fetch failed (%s) — defaulting to 0.0", _sent_exc)
            return 0.0

    def _reset_daily_counter(self) -> None:
        today = datetime.now(UTC).day
        if today != self._trade_day:
            self._daily_trades = 0
            self._trade_day = today

    def _write_rejection_lineage(self, signal, reason: str, failures: list[dict]) -> None:
        if self._lineage is None:
            return
        try:
            self._lineage.record_signal(
                direction=f"GATE_BLOCK:{getattr(signal, 'direction', '?')}",
                confidence=getattr(signal, "confidence", 0.0),
                probability=0.0,
                features_hash="",
                model_version=f"gatekeeper:{reason}",
                lineage_id=getattr(signal, "signal_id", str(uuid.uuid4())),
                symbol=getattr(signal, "symbol", "XAU_USD"),
            )
        except Exception as exc:
            logger.debug("Gatekeeper lineage write failed: %s", exc)

    # ── Equity update (called by engine on fills) ─────────────────────────────

    def update_equity(self, equity: float) -> None:
        self._equity.update(equity)

    def activate_kill_switch(self) -> None:
        self._kill_active = True
        logger.critical("Gatekeeper: kill switch ACTIVATED")

    def deactivate_kill_switch(self) -> None:
        self._kill_active = False
        logger.warning("Gatekeeper: kill switch DEACTIVATED by operator")

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        return {
            "pass_count": self._pass_count,
            "block_count": self._block_count,
            "daily_trades": self._daily_trades,
            "daily_dd_pct": round(self._equity.daily_dd * 100, 4),
            "max_dd_pct": round(self._equity.max_dd * 100, 4),
            "kill_active": self._kill_active,
            "paused": time.monotonic() < self._paused_until,
        }


# ── Module-level singleton ────────────────────────────────────────────────────
# Wired to the orchestrator singleton so all market-data checks use the
# authoritative data layer rather than stale signal attributes.
def _make_gatekeeper() -> Gatekeeper:
    # Access lineage store via orchestrator — single entry point rule.
    # Never import data_layer.lineage.store directly from outside data_layer/.
    try:
        from data_layer.orchestrator import orchestrator

        return Gatekeeper(
            orchestrator=orchestrator,
            lineage_store=orchestrator._lineage,
        )
    except Exception as _gk_exc:
        logger.warning("Gatekeeper wiring via orchestrator failed (%s) — starting ungated", _gk_exc)
        return Gatekeeper()


gatekeeper = _make_gatekeeper()
