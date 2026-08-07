# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/decision/HOPEFXDecisionEngine.py
======================================
Central decision engine — the single authoritative path from raw market
data to an approved, sized, and routed order.

Architecture
------------
Every incoming tick/bar passes through five sequential phases:

  Phase 1 — Signal Generation
      StrategyBrain.analyze_joint() produces a consensus signal from all
      active strategies (RSI, MACD, Bollinger, MA-crossover, regime router).

  Phase 2 — ML Enrichment
      The advanced ML predictor augments the raw signal with a directional
      probability.  Phase 1-4 stores (MTF fusion, anomaly weighting, online
      learner, deep ensemble) are applied in order when available.

  Phase 3 — Risk Gate
      Gatekeeper runs 11 internal pre-trade checks + FIA 2024 compliance.
      RiskManager validates position sizing against account equity, drawdown
      limits, and CVaR constraints.

  Phase 4 — Execution
      TradeExecutor routes the approved order through the smart broker
      router with mandatory pre-trade gate, drawdown circuit breaker, and
      loss-streak detection.

  Phase 5 — Post-Trade
      Fill is broadcast over EventBus, logged to the compliance audit trail,
      and fed back to the online learner for incremental model updates.

Wiring
------
The engine is instantiated once at startup by startup_factories.py and
injected into the FastAPI app_state.  All sub-systems are passed in at
construction time — no global singletons are imported inside methods.

Usage
-----
    engine = HOPEFXDecisionEngine(
        brain=strategy_brain,
        risk_manager=risk_manager,
        gatekeeper=gatekeeper,
        trade_executor=trade_executor,
        event_bus=event_bus,
    )
    result = await engine.process_tick(data, symbol="XAUUSD")
    if result.outcome == DecisionOutcome.EXECUTED:
        logger.info("Order placed: %s", result.order_id)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DecisionPhase(Enum):
    """Which phase the decision pipeline reached before stopping."""

    SIGNAL_GENERATION = "signal_generation"
    ML_ENRICHMENT = "ml_enrichment"
    RISK_GATE = "risk_gate"
    EXECUTION = "execution"
    POST_TRADE = "post_trade"


class DecisionOutcome(Enum):
    """Final outcome of a decision cycle."""

    NO_SIGNAL = "no_signal"
    ML_FILTERED = "ml_filtered"
    RISK_BLOCKED = "risk_blocked"
    SIZING_REJECTED = "sizing_rejected"
    EXECUTED = "executed"
    EXECUTION_ERROR = "execution_error"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DecisionContext:
    """Immutable snapshot of all inputs to a single decision cycle."""

    symbol: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])


@dataclass
class DecisionResult:
    """Full audit record for one decision cycle."""

    decision_id: str
    symbol: str
    timestamp: datetime
    phase_reached: DecisionPhase
    outcome: DecisionOutcome

    direction: str | None = None
    base_confidence: float = 0.0
    ml_probability: float = 0.0
    signal_strength: float = 0.0

    approved_size: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    order_id: str | None = None
    filled_quantity: float = 0.0
    average_price: float = 0.0
    commission: float = 0.0

    latency_ms: float = 0.0
    gate_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "phase_reached": self.phase_reached.value,
            "outcome": self.outcome.value,
            "direction": self.direction,
            "base_confidence": self.base_confidence,
            "ml_probability": self.ml_probability,
            "signal_strength": self.signal_strength,
            "approved_size": self.approved_size,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "order_id": self.order_id,
            "filled_quantity": self.filled_quantity,
            "average_price": self.average_price,
            "commission": self.commission,
            "latency_ms": self.latency_ms,
            "gate_reason": self.gate_reason,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class HOPEFXDecisionEngine:
    """
    Central decision engine — single authoritative path from tick to order.

    All sub-systems are injected at construction time.  Optional components
    (feature_engineer, compliance_manager, ml_predictor) degrade gracefully
    when absent — the engine never raises on missing optional dependencies.

    Thread safety
    -------------
    A per-instance asyncio.Lock serialises concurrent process_tick calls so
    risk state is never read mid-update.  Set allow_concurrent=True to
    disable the lock (e.g. in backtests where calls are sequential).
    """

    import os as _os

    ML_THRESHOLD: float = float(_os.getenv("HOPEFX_ML_THRESHOLD", "0.52"))

    def __init__(
        self,
        brain: Any,
        risk_manager: Any,
        gatekeeper: Any,
        trade_executor: Any,
        event_bus: Any,
        feature_engineer: Any | None = None,
        compliance_manager: Any | None = None,
        ml_predictor: Any | None = None,
        allow_concurrent: bool = False,
    ) -> None:
        self._brain = brain
        self._risk = risk_manager
        self._gate = gatekeeper
        self._executor = trade_executor
        self._bus = event_bus
        self._fe = feature_engineer
        self._compliance = compliance_manager
        self._ml = ml_predictor
        self._lock: asyncio.Lock | None = None if allow_concurrent else asyncio.Lock()
        self._cycles: int = 0
        self._executed: int = 0
        self._blocked: int = 0
        self._errors: int = 0
        logger.info(
            "HOPEFXDecisionEngine initialised — ml_threshold=%.2f concurrent=%s",
            self.ML_THRESHOLD,
            allow_concurrent,
        )

    # ── Public entry point ────────────────────────────────────────────────────

    async def process_tick(
        self,
        data: dict[str, Any],
        symbol: str = "XAUUSD",
    ) -> DecisionResult:
        """
        Run the full five-phase decision pipeline for one tick/bar.

        Args:
            data: Market data dict with keys: close, open, high, low,
                  volume, prices (list), highs, lows, volumes.
            symbol: Trading instrument identifier.

        Returns:
            DecisionResult with full audit trail regardless of outcome.
        """
        ctx = DecisionContext(symbol=symbol, data=data)
        t0 = time.monotonic()

        if self._lock is not None:
            async with self._lock:
                result = await self._pipeline(ctx)
        else:
            result = await self._pipeline(ctx)

        result.latency_ms = (time.monotonic() - t0) * 1000
        self._cycles += 1
        if result.outcome == DecisionOutcome.EXECUTED:
            self._executed += 1
        elif result.outcome == DecisionOutcome.EXECUTION_ERROR:
            self._errors += 1
        else:
            self._blocked += 1

        logger.debug(
            "Decision %s: symbol=%s outcome=%s phase=%s latency=%.1fms",
            ctx.decision_id,
            symbol,
            result.outcome.value,
            result.phase_reached.value,
            result.latency_ms,
        )
        return result

    # ── Pipeline ──────────────────────────────────────────────────────────────

    async def _pipeline(self, ctx: DecisionContext) -> DecisionResult:
        result = DecisionResult(
            decision_id=ctx.decision_id,
            symbol=ctx.symbol,
            timestamp=ctx.timestamp,
            phase_reached=DecisionPhase.SIGNAL_GENERATION,
            outcome=DecisionOutcome.NO_SIGNAL,
        )

        signal_info = self._phase1_signal(ctx, result)
        if signal_info is None:
            return result

        result.phase_reached = DecisionPhase.ML_ENRICHMENT
        ml_prob = await self._phase2_ml(ctx, signal_info, result)
        if ml_prob is None:
            result.outcome = DecisionOutcome.ML_FILTERED
            return result

        result.phase_reached = DecisionPhase.RISK_GATE
        approved_size = await self._phase3_risk(ctx, signal_info, result)
        if approved_size is None or approved_size <= 0:
            return result

        result.phase_reached = DecisionPhase.EXECUTION
        executed = await self._phase4_execute(ctx, signal_info, approved_size, result)
        if not executed:
            return result

        result.phase_reached = DecisionPhase.POST_TRADE
        result.outcome = DecisionOutcome.EXECUTED
        await self._phase5_post_trade(ctx, result)
        return result

    # ── Phase 1: Signal generation ────────────────────────────────────────────

    def _phase1_signal(
        self,
        ctx: DecisionContext,
        result: DecisionResult,
    ) -> dict[str, Any] | None:
        """Run StrategyBrain and return signal info dict, or None."""
        try:
            brain_result: dict[str, Any] = self._brain.analyze_joint(ctx.data)
        except Exception as exc:
            logger.warning("Phase1 brain.analyze_joint failed: %s", exc)
            result.error = f"brain error: {exc}"
            return None

        if not brain_result.get("consensus_reached"):
            logger.debug("Phase1 no consensus for %s: %s", ctx.symbol, brain_result.get("reason", ""))
            return None

        signal = brain_result.get("consensus_signal")
        if signal is None:
            return None

        direction: str = signal.signal_type.value if hasattr(signal.signal_type, "value") else str(signal.signal_type)
        confidence: float = float(getattr(signal, "confidence", 0.0))
        result.direction = direction
        result.base_confidence = confidence
        result.entry_price = float(ctx.data.get("close", 0.0))
        return {
            "direction": direction,
            "confidence": confidence,
            "signal": signal,
            "brain_result": brain_result,
        }

    # ── Phase 2: ML enrichment ────────────────────────────────────────────────

    async def _phase2_ml(
        self,
        ctx: DecisionContext,
        signal_info: dict[str, Any],
        result: DecisionResult,
    ) -> float | None:
        """Enrich signal with ML probability. Returns probability or None to filter."""
        prob: float = signal_info["confidence"]

        if self._ml is not None:
            raw: Any = None
            try:
                ohlcv_df = self._build_ohlcv_df(ctx.data)
                raw = self._ml.predict(ohlcv_df)
            except RuntimeError as exc:
                # The inference engine raises RuntimeError to BLOCK inference on a
                # known-bad state (stale model / drift) when STALE_MODEL_BLOCK is
                # enabled — the production default. This is a hard stop: filter
                # the signal rather than swallowing the error and trading on base
                # confidence, which would silently bypass the staleness gate.
                logger.warning(
                    "Phase2 ML blocked (stale/drift) — filtering signal for %s: %s",
                    ctx.symbol,
                    exc,
                )
                return None
            except Exception as exc:
                logger.warning("Phase2 ML predict failed (using base confidence) for %s: %s", ctx.symbol, exc)
                raw = None

            # InferenceEngine.predict() returns a dict (calibrated confidence in
            # [0,1]); legacy predictors may return a scalar or array. The previous
            # code only handled scalar/array, so on the dict path it hit
            # float(raw[-1]) -> KeyError and silently discarded every ML output.
            if isinstance(raw, dict):
                # Only override base confidence with a REAL prediction; on the
                # deterministic fallback (no model / too few bars) keep the base
                # confidence instead of forcing the signal to a 0.0 confidence.
                if not raw.get("fallback", False):
                    prob = float(raw.get("confidence", raw.get("probability", prob)))
            elif isinstance(raw, int | float):
                prob = float(raw)
            elif raw is not None and hasattr(raw, "__len__") and len(raw) > 0:
                prob = float(raw[-1])

        prob = self._apply_phase_stores(prob, ctx)
        result.ml_probability = prob
        result.signal_strength = prob

        if prob < self.ML_THRESHOLD:
            logger.debug(
                "Phase2 ML filtered: prob=%.3f < threshold=%.3f symbol=%s",
                prob,
                self.ML_THRESHOLD,
                ctx.symbol,
            )
            return None
        return prob

    def _apply_phase_stores(self, prob: float, ctx: DecisionContext) -> float:
        """Apply anomaly weighting, online blend, and deep ensemble blend."""
        for fn_name in ("_apply_anomaly_weighting", "_apply_online_blend", "_apply_deep_ensemble_blend"):
            try:
                import importlib

                mod = importlib.import_module("core.signal_engine")
                fn = getattr(mod, fn_name)
                ohlcv_df = self._build_ohlcv_df(ctx.data)
                prob = float(fn(prob, ohlcv_df, ctx.symbol))
            except Exception:  # nosec B110 — signal engine plugin is optional; keep prior prob on failure  # noqa: S110
                pass
        return prob

    # ── Phase 3: Risk gate ────────────────────────────────────────────────────

    async def _phase3_risk(
        self,
        ctx: DecisionContext,
        signal_info: dict[str, Any],
        result: DecisionResult,
    ) -> float | None:
        """Run Gatekeeper + RiskManager. Returns approved size or None."""
        direction = signal_info["direction"]
        signal = signal_info["signal"]

        # Gatekeeper evaluation
        try:
            gate_result = await self._gate.evaluate(signal)
            if not gate_result.passed:
                reason = getattr(gate_result, "reason", "gate blocked")
                logger.info("Phase3 gate blocked: symbol=%s reason=%s", ctx.symbol, reason)
                result.outcome = DecisionOutcome.RISK_BLOCKED
                result.gate_reason = str(reason)
                return None
        except Exception as exc:
            logger.warning("Phase3 gatekeeper.evaluate failed: %s", exc)
            result.outcome = DecisionOutcome.RISK_BLOCKED
            result.gate_reason = f"gate error: {exc}"
            return None

        # RiskManager: account info + position sizing
        try:
            broker = getattr(self._executor, "broker", None)
            if broker is None:
                # No broker → no real account info. Do NOT fabricate a $100k
                # account and size against it; block the trade instead.
                logger.warning(
                    "Phase3: no broker/account info available — blocking trade "
                    "(refusing to size against a fabricated account)."
                )
                result.outcome = DecisionOutcome.RISK_BLOCKED
                result.gate_reason = "account_info_unavailable: no broker connected"
                return None

            account_info: Any = await broker.get_account_info()
            if account_info is None:
                # Brokers return None when disconnected or when the account
                # query fails. Same rule as "no broker": never size against an
                # account we could not read.
                logger.warning(
                    "Phase3: broker returned no account info — blocking trade "
                    "(refusing to size against a fabricated account)."
                )
                result.outcome = DecisionOutcome.RISK_BLOCKED
                result.gate_reason = "account_info_unavailable: broker returned None"
                return None

            raw_positions = await broker.get_positions()
            positions: list[dict] = [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "current_price": getattr(p, "current_price", 0),
                }
                for p in raw_positions
            ]

            assessment = self._risk.assess_risk(account_info, positions)
            if not assessment.can_trade:
                logger.info("Phase3 risk blocked: %s", getattr(assessment, "messages", "risk limit"))
                result.outcome = DecisionOutcome.RISK_BLOCKED
                result.gate_reason = str(getattr(assessment, "messages", "risk limit"))
                return None

            # No default. `AccountInfo.get` is getattr-based, so a default here
            # is returned for a *missing field* as readily as a missing key —
            # which is how a broker whose account object lacks `equity` would
            # silently be sized against a fabricated six-figure balance. Block
            # instead; this is the same rule as the no-broker branch above.
            # Read defensively across dict / AccountInfo / plain object so a
            # broker returning a non-conforming type is reported as an account
            # problem rather than surfacing as an opaque "risk error" from the
            # broad handler below — that misattribution is what made S1-01 look
            # like a risk limit for the whole of the live-OANDA path.
            _raw_equity = (
                account_info.get("equity") if hasattr(account_info, "get") else getattr(account_info, "equity", None)
            )
            equity: float = float(_raw_equity or 0.0)
            if equity <= 0:
                logger.warning(
                    "Phase3: account equity unavailable or non-positive (%r) — blocking trade "
                    "(refusing to size against a fabricated account).",
                    equity,
                )
                result.outcome = DecisionOutcome.RISK_BLOCKED
                result.gate_reason = f"account_info_unavailable: equity={equity}"
                return None

            entry: float = result.entry_price or float(ctx.data.get("close", 0.0))
            sl_price, tp_price = self._resolve_sl_tp(ctx.data, direction, entry)
            result.stop_loss = sl_price
            result.take_profit = tp_price

            # `probability` and `direction` were previously omitted, so sizing
            # ran on the hardcoded defaults (probability=0.55, direction="long")
            # for every trade — Kelly could not see the model's actual edge, and
            # short trades were sized and labelled as longs.
            # See docs/HARDENING_BACKLOG.md S1-06 and S1-09.
            sizing = self._risk.calculate_position_size(
                symbol=ctx.symbol,
                signal_strength=result.signal_strength,
                probability=result.ml_probability,
                direction="long" if self._is_long(direction) else "short",
                entry_price=entry,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                account_equity=equity,
                volatility=self._estimate_volatility(ctx.data, entry),
                existing_positions=positions,
                # Age of the market data behind this decision, so the pre-trade
                # staleness invariant has something to measure (S5-01).
                tick_ts=self._tick_timestamp(ctx),
            )

            if not sizing.approved or sizing.recommended_size <= 0:
                logger.info(
                    "Phase3 sizing rejected: symbol=%s reason=%s",
                    ctx.symbol,
                    getattr(sizing, "reason", "size=0"),
                )
                result.outcome = DecisionOutcome.SIZING_REJECTED
                result.gate_reason = str(getattr(sizing, "reason", "size=0"))
                return None

            result.approved_size = float(sizing.recommended_size)
            # Carry the risk-approval token issued by size_order() through to
            # execution. It is the proof this order passed the risk gate; when
            # it was dropped here, TradeExecutor manufactured a constant in its
            # place and the No Unauthorized Trade invariant became
            # unfalsifiable. See docs/HARDENING_BACKLOG.md S1-05.
            self._risk_approval_token = str(getattr(sizing, "risk_approval_token", "") or "")
            if not self._risk_approval_token:
                logger.warning(
                    "Phase3: sizing returned no risk_approval_token for %s — "
                    "blocking, since execution cannot verify this order passed risk.",
                    ctx.symbol,
                )
                result.outcome = DecisionOutcome.SIZING_REJECTED
                result.gate_reason = "missing_risk_approval_token"
                return None
            return result.approved_size

        except Exception as exc:
            logger.exception("Phase3 risk assessment failed: %s", exc)
            result.outcome = DecisionOutcome.RISK_BLOCKED
            result.gate_reason = f"risk error: {exc}"
            return None

    # ── Phase 4: Execution ────────────────────────────────────────────────────

    async def _phase4_execute(
        self,
        ctx: DecisionContext,
        signal_info: dict[str, Any],
        approved_size: float,
        result: DecisionResult,
    ) -> bool:
        """Submit order via TradeExecutor. Returns True on success."""
        direction = signal_info["direction"]
        action = "buy" if self._is_long(direction) else "sell"

        exec_signal = {
            "symbol": ctx.symbol,
            "action": action,
            "size": approved_size,
            "entry_price": result.entry_price,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            "confidence": result.ml_probability,
            "decision_id": ctx.decision_id,
            # Proof this order passed the risk gate — stamped by size_order()
            # and verified by TradeExecutor / the OMS (S1-05).
            "risk_approval_token": getattr(self, "_risk_approval_token", ""),
        }

        try:
            exec_result = await self._executor.execute_signal(exec_signal)
        except Exception as exc:
            logger.exception("Phase4 execute_signal raised: %s", exc)
            result.outcome = DecisionOutcome.EXECUTION_ERROR
            result.error = str(exc)
            return False

        if not exec_result.success:
            logger.warning(
                "Phase4 execution failed: symbol=%s status=%s msg=%s",
                ctx.symbol,
                exec_result.status.value,
                exec_result.message,
            )
            result.outcome = DecisionOutcome.EXECUTION_ERROR
            result.error = exec_result.message
            return False

        result.order_id = exec_result.order_id
        result.filled_quantity = exec_result.filled_quantity
        result.average_price = exec_result.average_price
        result.commission = exec_result.commission
        return True

    # ── Phase 5: Post-trade ───────────────────────────────────────────────────

    async def _phase5_post_trade(self, ctx: DecisionContext, result: DecisionResult) -> None:
        """Broadcast fill, log compliance, and feed online learner. All best-effort."""
        payload = result.to_dict()

        # EventBus broadcast
        try:
            await self._bus.publish_signal(payload)
        except Exception as exc:
            logger.debug("Phase5 event_bus publish failed: %s", exc)

        # Compliance audit
        if self._compliance is not None:
            try:
                self._compliance.log_trade(
                    symbol=ctx.symbol,
                    direction=result.direction or "",
                    quantity=result.filled_quantity,
                    price=result.average_price,
                    order_id=result.order_id or "",
                    metadata=payload,
                )
            except Exception as exc:
                logger.debug("Phase5 compliance log failed: %s", exc)

        # Online learner feedback
        try:
            from core.signal_engine import _notify_online_learner

            _notify_online_learner(
                ctx.symbol,
                result.direction or "",
                result.filled_quantity,
                type("_Order", (), {"id": result.order_id})(),
                payload,
            )
        except Exception as exc:
            logger.debug("Phase5 online learner notify failed: %s", exc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _tick_timestamp(ctx: DecisionContext) -> float | None:
        """POSIX timestamp of the market data behind this decision.

        Prefers an explicit tick timestamp carried on the incoming data; falls
        back to the decision's own timestamp, which at least bounds staleness
        at the age of this cycle. Returns None when neither is usable, in which
        case the staleness check is skipped exactly as before.
        """
        raw = ctx.data.get("tick_ts") or ctx.data.get("timestamp") or ctx.data.get("ts")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
        if isinstance(raw, datetime):
            ts = raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
            return ts.timestamp()
        try:
            return ctx.timestamp.timestamp()
        except Exception:
            return None

    @staticmethod
    def _is_long(direction: str) -> bool:
        """Single definition of "is this a long?".

        This predicate previously existed in three copies (execution action,
        SL/TP orientation, and — omitted entirely — sizing direction). Copies
        of a predicate drift; keeping one is the same discipline the rest of
        Round 3 applies to duplicated types and instances.
        """
        d = (direction or "").upper()
        return "BUY" in d or d in ("LONG", "ENTRY_LONG")

    def _build_ohlcv_df(self, data: dict[str, Any]) -> Any:
        """Build a rolling OHLCV DataFrame from the broker data dict."""
        try:
            from core.signal_engine import _build_ohlcv_df

            return _build_ohlcv_df(data)
        except Exception:
            import pandas as pd

            return pd.DataFrame(
                {
                    "open": [data.get("open", data.get("close", 0))],
                    "high": [data.get("high", data.get("close", 0))],
                    "low": [data.get("low", data.get("close", 0))],
                    "close": [data.get("close", 0)],
                    "volume": [data.get("volume", 0)],
                }
            )

    def _resolve_sl_tp(
        self,
        data: dict[str, Any],
        direction: str,
        entry: float,
    ) -> tuple[float, float]:
        """ATR-based SL/TP; falls back to 1%/2% of entry when ATR unavailable."""
        try:
            from core.signal_engine import _compute_atr

            atr = _compute_atr(
                data.get("highs", []),
                data.get("lows", []),
                data.get("prices", [entry]),
                entry,
            )
        except Exception:
            atr = entry * 0.01

        is_long = self._is_long(direction)
        if is_long:
            return float(entry - 2.0 * atr), float(entry + 3.0 * atr)
        return float(entry + 2.0 * atr), float(entry - 3.0 * atr)

    def _estimate_volatility(self, data: dict[str, Any], entry: float) -> float:
        """Estimate annualised volatility from recent price history."""
        try:
            from core.signal_engine import _estimate_annualised_volatility

            return _estimate_annualised_volatility(data, entry)
        except Exception:
            import numpy as np

            prices = data.get("prices", [entry])
            if len(prices) < 2:
                return 0.15
            p_arr = np.nan_to_num(np.array(prices, dtype=float), nan=0.0)
            denom = np.where(p_arr[:-1] != 0, p_arr[:-1], 1.0)
            returns = np.diff(p_arr) / denom
            return float(np.std(returns) * np.sqrt(252))

    # ── Status and metrics ────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return a health-check dict for monitoring and /status endpoints."""
        exec_rate = (self._executed / self._cycles) if self._cycles > 0 else 0.0
        return {
            "engine": "HOPEFXDecisionEngine",
            "ml_threshold": self.ML_THRESHOLD,
            "cycles_total": self._cycles,
            "executed": self._executed,
            "blocked": self._blocked,
            "errors": self._errors,
            "execution_rate": round(exec_rate, 4),
            "sub_systems": {
                "brain": type(self._brain).__name__,
                "risk_manager": type(self._risk).__name__,
                "gatekeeper": type(self._gate).__name__,
                "trade_executor": type(self._executor).__name__,
                "event_bus": type(self._bus).__name__,
                "feature_engineer": type(self._fe).__name__ if self._fe else None,
                "ml_predictor": type(self._ml).__name__ if self._ml else None,
                "compliance_manager": type(self._compliance).__name__ if self._compliance else None,
            },
        }

    def reset_metrics(self) -> None:
        """Reset cycle counters (useful between backtest runs)."""
        self._cycles = 0
        self._executed = 0
        self._blocked = 0
        self._errors = 0


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


def create_decision_router(engine: HOPEFXDecisionEngine):
    """
    FastAPI router exposing decision engine status and manual tick injection.

    Mount with::

        from core.decision.HOPEFXDecisionEngine import create_decision_router
        app.include_router(create_decision_router(engine))
    """
    from fastapi import APIRouter, Depends
    from pydantic import BaseModel
    from api.auth import require_role

    router = APIRouter(prefix="/api/decision", tags=["Decision Engine"], dependencies=[Depends(require_role("admin"))])

    class TickRequest(BaseModel):
        symbol: str = "XAUUSD"
        close: float
        open: float
        high: float
        low: float
        volume: float = 0.0

    @router.get("/status", summary="Decision engine health and metrics")
    async def get_status():
        return engine.status()

    @router.post("/tick", summary="Inject a single tick through the decision pipeline")
    async def inject_tick(req: TickRequest):
        data = {
            "close": req.close,
            "open": req.open,
            "high": req.high,
            "low": req.low,
            "volume": req.volume,
            "prices": [req.close],
            "highs": [req.high],
            "lows": [req.low],
            "volumes": [req.volume],
        }
        result = await engine.process_tick(data, symbol=req.symbol)
        return result.to_dict()

    @router.post("/reset", summary="Reset engine cycle metrics")
    async def reset_metrics():
        engine.reset_metrics()
        return {"reset": True}

    return router
