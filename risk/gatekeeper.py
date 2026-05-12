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
12. FIA 2024 compliance               — FIAComplianceManager mandatory pre-trade
                                        controls (order size, intraday position,
                                        price tolerance, kill switch, market data
                                        validation, message throttle)

On any breach
-------------
- Publishes breach event to hopefx:breach channel.
- Sets pause flag for PAUSE_AFTER_BREACH_S seconds (except kill-switch).
- Logs at WARNING with structured fields.
- Writes rejection to DataLineageStore.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from core.event_bus import CH_BREACH, CH_SIGNAL, bus
from risk.fia_compliance import FIAComplianceManager, RiskControlStatus

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

    def is_blackout(self, window_minutes: int | None = None) -> bool:
        """Return True if any registered event is within *window_minutes* of now."""
        window = window_minutes if window_minutes is not None else self._BLACKOUT_MINUTES
        now = datetime.now(UTC)
        cutoff = timedelta(minutes=window)
        for ev in self._events:
            # Normalise naive datetimes to UTC
            ev_aware = ev.replace(tzinfo=UTC) if ev.tzinfo is None else ev
            if abs(now - ev_aware) <= cutoff:
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _safe_float(obj, names: tuple[str, ...], default: float = 0.0) -> float:
    """Return the first explicitly-set numeric attribute from *names*.

    Only accepts ``int`` or ``float`` values — skips auto-generated mock
    attributes and other non-numeric types.  Falls back to *default* when no
    name yields a real number.
    """
    for name in names:
        raw = getattr(obj, name, None)
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return float(raw)
    return default


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

    def __init__(
        self,
        orchestrator=None,
        lineage_store=None,
        fia_compliance: FIAComplianceManager | None = None,
    ) -> None:
        initial_balance = float(os.getenv("INITIAL_BALANCE", "100000"))
        self._orch = orchestrator
        self._lineage = lineage_store
        self._equity = _EquityTracker(initial_balance)
        self._calendar = _NewsCalendar()
        self._kill_active: bool = False
        self._paused_until: float = 0.0
        self._daily_trades: int = 0
        _now = datetime.now(UTC)
        self._trade_day: tuple = (_now.year, _now.month, _now.day)
        self._running: bool = False
        self._pass_count: int = 0
        self._block_count: int = 0
        self._fia_block_count: int = 0
        # Lock protects all mutable counters (_daily_trades, _pass_count,
        # _block_count, _trade_day, _paused_until) from concurrent asyncio tasks.
        # Without this lock, concurrent signals can race and undercount trades,
        # potentially bypassing MAX_DAILY_TRADES limits.
        self._lock = asyncio.Lock()

        # FIA 2024 compliance manager — runs mandatory pre-trade controls
        # (order size, intraday position, price tolerance, kill switch, market
        # data validation, message throttle) after the 11 internal gate checks.
        # Injected for tests; defaults to a new instance with env-driven config.
        self._fia: FIAComplianceManager = fia_compliance or FIAComplianceManager(
            config={
                "max_order_size": float(os.getenv("FIA_MAX_ORDER_SIZE", "100")),
                "max_intraday_position": float(os.getenv("FIA_MAX_INTRADAY_POSITION", "500")),
                "price_tolerance": float(os.getenv("FIA_PRICE_TOLERANCE", "0.02")),
                "daily_loss_limit": float(os.getenv("FIA_DAILY_LOSS_LIMIT", "0.03")),
                "max_messages_per_second": int(os.getenv("FIA_MAX_MSG_PER_SEC", "50")),
            }
        )

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
        _t = asyncio.create_task(self._breach_listener(), name="gatekeeper_breach_listener")
        _t.add_done_callback(lambda _: None)
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

        Runs the 11 internal gate checks first (fail-fast), then delegates to
        FIAComplianceManager for mandatory FIA 2024 pre-trade controls.

        Consumes orchestrator data for quality, sentiment, and blackout checks.
        Returns GateResult(passed=True) if all checks pass.

        Thread-safety: all mutable counter mutations are protected by
        self._lock to prevent race conditions when multiple signals are
        evaluated concurrently.
        """
        async with self._lock:
            self._reset_daily_counter_locked()
            failures = self._run_checks_on_signal(signal)

            if not failures:
                self._pass_count += 1
                self._daily_trades += 1

        if failures:
            async with self._lock:
                self._block_count += 1
            primary = failures[0]["reason"]
            logger.warning(
                "GATE BLOCK signal_id=%s reason=%s all_failures=%s",
                getattr(signal, "signal_id", "?"),
                primary,
                [f["reason"] for f in failures],
            )
            self._write_rejection_lineage(signal, primary, failures)
            async with self._lock:
                if primary != "kill_switch_active":
                    self._paused_until = time.monotonic() + _PAUSE_AFTER_BREACH_S
            return GateResult(passed=False, reason=primary, failures=failures)

        # ── FIA 2024 compliance checks ─────────────────────────────────────
        # Only reached when all 11 internal gates pass.  Build minimal order
        # and market-data dicts from the signal so FIAComplianceManager can
        # run its mandatory pre-trade controls.
        fia_result = await self._run_fia_checks(signal)
        if fia_result is not None:
            return fia_result

        return GateResult(passed=True)

    async def _run_fia_checks(self, signal) -> GateResult | None:
        """
        Run FIA 2024 mandatory pre-trade controls via FIAComplianceManager.

        Returns a blocking GateResult if any FIA rule fires, None if all pass.
        Errors in FIA checks are logged and treated as non-blocking so that a
        misconfigured compliance manager cannot halt all trading.
        """
        try:
            # ExecutionSignal uses tick_bid/tick_ask/tick_mid; dict signals use
            # bid/ask/mid.  Read both name variants so both paths work correctly.
            bid = _safe_float(signal, ("tick_bid", "bid"))
            ask = _safe_float(signal, ("tick_ask", "ask"))
            mid = _safe_float(signal, ("tick_mid", "mid_price", "mid"))

            order = {
                "symbol": getattr(signal, "symbol", "XAU_USD"),
                "size": float(getattr(signal, "quantity", getattr(signal, "size", 1.0))),
                "side": getattr(signal, "direction", "long"),
                "price": float(getattr(signal, "entry_price", mid)),
            }
            # FIA 3.1 market-data validation is only meaningful when the signal
            # carries live tick prices (bid > 0 and ask > bid).  Pure ML signals
            # without embedded prices rely on the orchestrator data-quality gate
            # (check 5) for staleness protection — skip FIA 3.1 for those.
            has_prices = bid > 0.0 and ask > bid
            market_data = {
                "mid": mid if mid > 0.0 else (bid + ask) / 2.0 if has_prices else 0.0,
                "bid": bid if has_prices else 0.0,
                "ask": ask if has_prices else 0.0,
                "timestamp": datetime.now(UTC),
            }
            portfolio_state = {
                "daily_pnl": float(getattr(signal, "daily_pnl", 0.0)),
                "capital": float(os.getenv("INITIAL_BALANCE", "100000")),
            }

            fia_results = await self._fia.validate_order(order, market_data, portfolio_state)

            # FIA 1.3 (price tolerance) and FIA 3.1 (market data validation)
            # require live tick prices.  When the signal carries no embedded
            # prices (pure ML signal — prices live in the orchestrator), these
            # checks are not applicable and must not block the signal.  The
            # orchestrator data-quality gate (check 5) is the authoritative
            # staleness guard for price-less signals.
            price_dependent_rules = frozenset(
                {
                    "FIA_1.3_PRICE_TOLERANCE",
                    "FIA_3.1_MARKET_DATA_VALIDATION",
                }
            )
            if not has_prices:
                fia_results = [
                    r
                    for r in fia_results
                    if r.rule not in price_dependent_rules
                    or r.status not in (RiskControlStatus.BLOCK, RiskControlStatus.KILL_SWITCH)
                ]

            for result in fia_results:
                if result.status in (RiskControlStatus.BLOCK, RiskControlStatus.KILL_SWITCH):
                    async with self._lock:
                        self._fia_block_count += 1
                        self._block_count += 1
                        # FIA kill switch mirrors the internal kill switch
                        if result.status == RiskControlStatus.KILL_SWITCH:
                            self._kill_active = True

                    reason = f"fia:{result.rule}"
                    logger.warning(
                        "FIA BLOCK signal_id=%s rule=%s message=%s",
                        getattr(signal, "signal_id", "?"),
                        result.rule,
                        result.message,
                    )
                    self._write_rejection_lineage(
                        signal,
                        reason,
                        [{"reason": reason, "detail": result.message}],
                    )
                    return GateResult(
                        passed=False,
                        reason=reason,
                        failures=[{"reason": reason, "detail": result.message, "rule": result.rule}],
                    )
        except Exception as exc:
            # FIA check errors must not silently pass orders — log at ERROR
            # and block the signal so the failure is visible in monitoring.
            logger.error(
                "FIA compliance check raised unexpectedly for signal_id=%s: %s — blocking signal",
                getattr(signal, "signal_id", "?"),
                exc,
            )
            async with self._lock:
                self._fia_block_count += 1
                self._block_count += 1
            return GateResult(
                passed=False,
                reason="fia_check_error",
                failures=[{"reason": "fia_check_error", "detail": str(exc)}],
            )

        return None

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
        async with self._lock:
            self._reset_daily_counter_locked()
            failures = self._run_checks_on_dict(signal)

            if not failures:
                self._pass_count += 1
                self._daily_trades += 1
                should_pass = True
            else:
                self._block_count += 1
                should_pass = False

        if should_pass:
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
            async with self._lock:
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
        """Orchestrator tick confidence is authoritative.

        When the orchestrator is wired, its value is always used (including 0.0
        on error — fail-closed). The signal's own data_quality is only used
        when no orchestrator is configured (standalone/test mode).
        """
        if getattr(self, "_orch", None) is not None:
            # Orchestrator present — use its value unconditionally (fail-closed on error).
            return self._get_data_quality_from_orch()
        # No orchestrator — fall back to signal attribute (standalone/test mode).
        return float(getattr(signal, "data_quality", 1.0))

    def _get_data_quality_from_orch(self) -> float:
        if getattr(self, "_orch", None) is None:
            return 1.0
        try:
            tick = getattr(self, "_orch", None) and self._orch.get_latest_tick()
            return float(tick.confidence) if tick else 0.0
        except Exception:
            # Fail-closed: unknown data quality blocks the trade via the
            # data_quality < _MIN_DATA_QUALITY check in gate step 5.
            logger.warning("_get_data_quality_from_orch: tick read failed — returning 0.0 (fail-closed)", exc_info=True)
            return 0.0

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
            with contextlib.suppress(Exception):
                return self._orch.is_blackout_window()
            # fall through to local calendar

        # Local calendar fallback (tests / standalone mode)
        cal = getattr(self, "_calendar", None)
        return bool(cal is not None and cal.is_blackout())

    def _get_impact_score(self, signal) -> float:
        """Orchestrator macro impact score is authoritative.

        When the orchestrator is wired, its value is always used (including 1.0
        on error — fail-closed). The signal's own impact_score is only used
        when no orchestrator is configured (standalone/test mode).
        """
        if getattr(self, "_orch", None) is not None:
            return self._get_impact_score_from_orch()
        return float(getattr(signal, "impact_score", 0.0))

    def _get_impact_score_from_orch(self) -> float:
        if getattr(self, "_orch", None) is None:
            return 0.0
        try:
            return float(self._orch.get_macro_impact_score())
        except Exception:
            # Fail-closed: unknown macro impact treated as maximum (1.0) so
            # the _IMPACT_BLACKOUT threshold check blocks the trade.
            logger.warning(
                "_get_impact_score_from_orch: orchestrator call failed — returning 1.0 (fail-closed)", exc_info=True
            )
            return 1.0

    def _get_sentiment(self, signal) -> float:
        score = self._get_sentiment_from_orch()
        if score != 0.0:
            return score
        return float(getattr(signal, "sentiment_score", 0.0))

    def _get_sentiment_from_orch(self) -> float:
        if getattr(self, "_orch", None) is None:
            return 0.0
        try:
            features = self._orch.get_ml_features()
            return float(features.get("news_sentiment_score", 0.0))
        except Exception:
            logger.debug("_get_sentiment_from_orch: orchestrator call failed", exc_info=True)
            return 0.0

    def _reset_daily_counter_locked(self) -> None:
        """Thread-safe daily counter reset.  Call only while holding self._lock."""
        now = datetime.now(UTC)
        today = (now.year, now.month, now.day)
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
            "fia_block_count": self._fia_block_count,
            "daily_trades": self._daily_trades,
            "daily_dd_pct": round(self._equity.daily_dd * 100, 4),
            "max_dd_pct": round(self._equity.max_dd * 100, 4),
            "kill_active": self._kill_active,
            "paused": time.monotonic() < self._paused_until,
            "fia_kill_switch": self._fia.kill_switch_active,
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
    except Exception:
        logger.warning("_make_gatekeeper: orchestrator import failed — using bare Gatekeeper", exc_info=True)
        return Gatekeeper()


# Module-level singleton used by tests and scripts
gatekeeper: Gatekeeper = _make_gatekeeper()
