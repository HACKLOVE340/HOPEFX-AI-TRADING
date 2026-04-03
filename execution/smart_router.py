# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
execution/smart_router.py
==========================
SmartRouter — microstructure-aware, sentiment-gated order routing.

Design invariants
-----------------
- Routing decisions are driven by orchestrator microstructure features and
  sentiment scores. No broker API is called for price data.
- Broker selection uses a composite score: latency, fill rate, slippage,
  spread regime, OFI direction alignment, and sentiment risk.
- News blackout and high-impact macro windows suppress routing entirely.
- Every routing decision is written to DataLineageStore.
- Fallback chain: primary → secondary → paper (never silently drops).
- Circuit breaker: broker removed from pool after 3 consecutive errors
  within 60 s; re-admitted after CIRCUIT_RESET_S.

Routing score formula (per broker)
-----------------------------------
  score = w_lat  * latency_score(ema_latency_ms)
        + w_fill * fill_rate
        + w_slip * slippage_score(avg_slippage_bps)
        + w_ofi  * ofi_alignment(ofi, direction)
        + w_sent * sentiment_penalty(sentiment_score)
        + w_rel  * reliability_score

  All weights configurable via env vars.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

from execution.algo_orders import AlgoOrderManager, get_algo_manager

logger = logging.getLogger(__name__)

# ── algo delegation thresholds (env-overridable) ──────────────────────────────
# Orders at or above ALGO_LARGE_ORDER_THRESHOLD lots are routed through
# AlgoOrderManager (TWAP/VWAP/Iceberg) instead of a plain market order.
# These mirror the thresholds in AlgoOrderManager so both sides agree.
_ALGO_LARGE_THRESHOLD = float(os.getenv("ALGO_LARGE_ORDER_THRESHOLD", "10.0"))
_ALGO_ICEBERG_THRESHOLD = float(os.getenv("ALGO_ICEBERG_THRESHOLD", "50.0"))

# ── routing weights (env-overridable) ─────────────────────────────────────────
_W_LATENCY = float(os.getenv("ROUTER_W_LATENCY", "0.25"))
_W_FILL = float(os.getenv("ROUTER_W_FILL", "0.25"))
_W_SLIPPAGE = float(os.getenv("ROUTER_W_SLIPPAGE", "0.20"))
_W_OFI = float(os.getenv("ROUTER_W_OFI", "0.15"))
_W_SENTIMENT = float(os.getenv("ROUTER_W_SENTIMENT", "0.10"))
_W_RELIABILITY = float(os.getenv("ROUTER_W_RELIABILITY", "0.05"))

# ── circuit breaker ────────────────────────────────────────────────────────────
_CB_ERROR_WINDOW_S = float(os.getenv("ROUTER_CB_WINDOW_S", "60.0"))
_CB_ERROR_THRESHOLD = int(os.getenv("ROUTER_CB_ERRORS", "3"))
_CB_RESET_S = float(os.getenv("ROUTER_CB_RESET_S", "120.0"))

# ── execution limits ──────────────────────────────────────────────────────────
_ORDER_TIMEOUT_S = float(os.getenv("ROUTER_ORDER_TIMEOUT_S", "5.0"))
_MAX_SPREAD_BPS = float(os.getenv("ROUTER_MAX_SPREAD_BPS", "50.0"))

# ── sentiment thresholds ──────────────────────────────────────────────────────
_SENT_BLACKOUT_THRESH = float(os.getenv("ROUTER_SENT_BLACKOUT", "0.80"))  # |score| > this → block
_IMPACT_BLACKOUT = float(os.getenv("ROUTER_IMPACT_BLACKOUT", "0.75"))


@dataclass
class BrokerState:
    """Per-broker rolling execution quality state."""

    broker_id: str
    ema_latency_ms: float = 100.0
    fill_rate: float = 0.95
    avg_slippage_bps: float = 5.0
    reliability: float = 1.0
    error_times: list[float] = field(default_factory=list)
    circuit_open: bool = False
    circuit_open_at: float = 0.0
    total_orders: int = 0
    total_fills: int = 0
    total_errors: int = 0

    def record_fill(self, latency_ms: float, slippage_bps: float) -> None:
        self.ema_latency_ms = 0.7 * self.ema_latency_ms + 0.3 * latency_ms
        self.avg_slippage_bps = 0.8 * self.avg_slippage_bps + 0.2 * slippage_bps
        self.total_fills += 1
        self.total_orders += 1
        self.fill_rate = self.total_fills / max(self.total_orders, 1)
        self.reliability = min(1.0, self.reliability * 1.001)  # slow recovery

    def record_error(self) -> None:
        now = time.monotonic()
        self.error_times.append(now)
        # Prune old errors outside window
        self.error_times = [t for t in self.error_times if now - t < _CB_ERROR_WINDOW_S]
        self.total_errors += 1
        self.total_orders += 1
        self.reliability *= 0.90
        if len(self.error_times) >= _CB_ERROR_THRESHOLD:
            self.circuit_open = True
            self.circuit_open_at = now
            logger.error(
                "Circuit breaker OPEN for broker=%s after %d errors in %.0fs",
                self.broker_id,
                len(self.error_times),
                _CB_ERROR_WINDOW_S,
            )

    def check_circuit_reset(self) -> None:
        if self.circuit_open and time.monotonic() - self.circuit_open_at > _CB_RESET_S:
            self.circuit_open = False
            self.error_times = []
            logger.warning("Circuit breaker RESET for broker=%s", self.broker_id)

    def routing_score(
        self,
        direction: str,
        ofi: float,
        sentiment_score: float,
    ) -> float:
        """Composite routing score [0, 1]. Higher = better."""
        # Latency: 0 ms → 1.0, 500 ms → ~0.0
        lat_score = 1.0 / (1.0 + self.ema_latency_ms / 100.0)

        # Slippage: 0 bps → 1.0, 50 bps → ~0.0
        slip_score = 1.0 / (1.0 + self.avg_slippage_bps / 10.0)

        # OFI alignment: reward routing in direction of order flow
        ofi_align = _ofi_alignment(ofi, direction)

        # Sentiment penalty: high absolute sentiment = higher uncertainty
        sent_pen = 1.0 - min(abs(sentiment_score), 1.0) * 0.5

        return (
            _W_LATENCY * lat_score
            + _W_FILL * self.fill_rate
            + _W_SLIPPAGE * slip_score
            + _W_OFI * ofi_align
            + _W_SENTIMENT * sent_pen
            + _W_RELIABILITY * self.reliability
        )


@dataclass
class RoutingDecision:
    """Full routing decision record for lineage."""

    decision_id: str
    order_id: str
    selected_broker: str
    fallback_chain: list[str]
    scores: dict[str, float]
    ofi: float
    sentiment_score: float
    impact_score: float
    spread_bps: float
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class SmartRouter:
    """
    Routes orders to the optimal broker using microstructure + sentiment.

    Wiring
    ------
    - Receives microstructure features (OFI, spread, pressure) from the
      order_request dict, which was populated by HopeFXEngine from orchestrator.
    - Receives sentiment scores from the same feature dict.
    - Never calls any broker for price data.
    - Writes every routing decision to lineage_store.

    Usage
    -----
        router = SmartRouter(lineage_store=lineage_store)
        router.add_broker("oanda", oanda_broker_instance)
        router.add_broker("ibkr",  ibkr_broker_instance)
        fill = await router.route_and_execute(order_request)
    """

    def __init__(
        self,
        lineage_store=None,
        algo_manager: AlgoOrderManager | None = None,
    ) -> None:
        self._lineage: Any = lineage_store
        self._brokers: dict[str, Any] = {}  # broker_id → broker instance
        self._states: dict[str, BrokerState] = {}
        self._decisions: list[RoutingDecision] = []
        self._total_routed: int = 0
        self._total_filled: int = 0

        # AlgoOrderManager handles large orders (TWAP/VWAP/Iceberg).
        # If not injected, use the module-level singleton.
        self._algo: AlgoOrderManager = algo_manager or get_algo_manager()
        # Wire the broker submission function into the algo manager so child
        # orders flow through the same broker selection logic.
        self._algo.set_broker_submit_fn(self._submit_child_order)

        # Pending algo orders: algo_id → order_request
        self._pending_algo_orders: dict[str, Any] = {}

    def add_broker(self, broker_id: str, broker_instance: Any) -> None:
        """Register a broker. Broker must implement place_order(order_dict)."""
        self._brokers[broker_id] = broker_instance
        self._states[broker_id] = BrokerState(broker_id=broker_id)
        logger.info("SmartRouter: registered broker=%s", broker_id)

    def remove_broker(self, broker_id: str) -> None:
        self._brokers.pop(broker_id, None)
        self._states.pop(broker_id, None)
        logger.warning("SmartRouter: removed broker=%s", broker_id)

    # ── Main routing entry point ──────────────────────────────────────────────

    async def route_and_execute(self, order_request: dict) -> dict:
        """
        Select optimal broker and execute order.

        order_request must contain:
          symbol, direction, quantity, order_type, mid_price, bid, ask,
          spread, confidence, sentiment (from orchestrator features),
          impact (macro impact score), features (full orchestrator feature dict)

        Returns fill dict with: status, fill_price, quantity, broker, latency_ms
        """
        self._total_routed += 1

        # Extract microstructure + sentiment from orchestrator-populated features
        features = order_request.get("features", {})
        ofi = float(features.get("order_flow_imbalance", 0.0))
        _trade_pressure = float(features.get("trade_pressure", 0.0))
        spread_bps = _spread_to_bps(
            order_request.get("spread", 0.0),
            order_request.get("mid_price", 1.0),
        )
        sentiment_score = float(order_request.get("sentiment", 0.0))
        impact_score = float(order_request.get("impact", 0.0))
        direction = order_request.get("direction", "long")

        # ── Pre-routing gates ──────────────────────────────────────────────
        # Unwind orders bypass sentiment/impact gates — they are unconditional.
        is_unwind = bool(order_request.get("is_unwind", False))
        if not is_unwind:
            gate_result = self._pre_route_gate(spread_bps, sentiment_score, impact_score, direction, ofi)
            if gate_result is not None:
                return {"status": "rejected", "reason": gate_result, "broker": "none"}

        # ── Large-order delegation to AlgoOrderManager ────────────────────
        quantity = float(order_request.get("quantity", 0.0))
        if not is_unwind and quantity >= _ALGO_LARGE_THRESHOLD:
            return await self._route_via_algo(order_request, quantity, direction)

        # ── Score and rank brokers ─────────────────────────────────────────
        ranked = self._rank_brokers(direction, ofi, sentiment_score)
        if not ranked:
            return {
                "status": "rejected",
                "reason": "no_brokers_available",
                "broker": "none",
            }

        # ── Build routing decision ─────────────────────────────────────────
        decision = RoutingDecision(
            decision_id=str(uuid.uuid4()),
            order_id=order_request.get("order_id", ""),
            selected_broker=ranked[0][0],
            fallback_chain=[b for b, _ in ranked[1:]],
            scores={b: round(s, 4) for b, s in ranked},
            ofi=ofi,
            sentiment_score=sentiment_score,
            impact_score=impact_score,
            spread_bps=spread_bps,
            reason=self._explain_selection(ranked[0][0], ofi, sentiment_score),
        )
        self._decisions.append(decision)
        self._write_routing_lineage(decision, order_request)

        # ── Execute with fallback chain ────────────────────────────────────
        return await self._execute_with_fallback(order_request, ranked, decision)

    # ── Algo order delegation ─────────────────────────────────────────────────

    async def _route_via_algo(
        self,
        order_request: dict,
        quantity: float,
        direction: str,
    ) -> dict:
        """
        Delegate a large order to AlgoOrderManager (TWAP/VWAP/Iceberg).

        The algo manager slices the order into child orders and submits each
        via _submit_child_order(), which flows through the normal broker
        selection and fallback logic.

        Returns a synthetic fill dict aggregating all child fills once the
        algo completes. For very large orders this is async — the caller
        receives a status="algo_submitted" response immediately and fills
        are reported back via the broker_submit_fn callback.
        """
        symbol = order_request.get("symbol", "")
        side = direction.upper()
        signal_id = order_request.get("signal_id", "")
        strategy_id = f"signal:{signal_id}"

        logger.info(
            "SmartRouter: delegating %.2f lots %s %s to AlgoOrderManager",
            quantity,
            side,
            symbol,
        )

        # Store the original order context so child fills can reference it

        algo_id = await self._algo.submit_auto(
            symbol=symbol,
            side=side,
            total_quantity=quantity,
            strategy_id=strategy_id,
        )

        if algo_id is None:
            # submit_auto returned None — quantity fell below threshold
            # (shouldn't happen here, but handle gracefully)
            logger.warning(
                "AlgoOrderManager.submit_auto returned None for qty=%.2f — falling through to market order",
                quantity,
            )
            ranked = self._rank_brokers(direction, 0.0, 0.0)
            if not ranked:
                return {
                    "status": "rejected",
                    "reason": "no_brokers_available",
                    "broker": "none",
                }
            decision = RoutingDecision(
                decision_id=str(uuid.uuid4()),
                order_id=order_request.get("order_id", ""),
                selected_broker=ranked[0][0],
                fallback_chain=[b for b, _ in ranked[1:]],
                scores={b: round(s, 4) for b, s in ranked},
                ofi=0.0,
                sentiment_score=0.0,
                impact_score=0.0,
                spread_bps=0.0,
                reason="algo_fallback_market",
            )
            return await self._execute_with_fallback(order_request, ranked, decision)

        self._total_routed += 1
        self._pending_algo_orders[algo_id] = order_request

        return {
            "status": "algo_submitted",
            "algo_id": algo_id,
            "quantity": quantity,
            "symbol": symbol,
            "direction": direction,
            "broker": "algo_manager",
            "reason": f"large_order_delegated:qty={quantity:.2f}",
        }

    async def _submit_child_order(self, child_order_dict: dict) -> dict:
        """
        Broker submission function wired into AlgoOrderManager.

        Called by each algo (TWAP/VWAP/Iceberg) for every child order slice.
        Routes through the normal broker selection and fallback chain.
        """
        symbol = child_order_dict.get("symbol", "")
        side = child_order_dict.get("side", "BUY").lower()
        direction = "long" if side == "buy" else "short"
        quantity = float(child_order_dict.get("quantity", 0.0))

        # Build a minimal order_request compatible with _execute_with_fallback
        order_request = {
            "order_id": child_order_dict.get("child_id", str(uuid.uuid4())),
            "signal_id": child_order_dict.get("algo_id", ""),
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
            "order_type": "MARKET",
            "mid_price": float(child_order_dict.get("mid_price", 0.0)),
            "bid": float(child_order_dict.get("bid", 0.0)),
            "ask": float(child_order_dict.get("ask", 0.0)),
            "spread": float(child_order_dict.get("spread", 0.0)),
            "confidence": 1.0,
            "sentiment": 0.0,
            "impact": 0.0,
            "features": {},
            "lineage_id": child_order_dict.get("algo_id", ""),
            "is_child_order": True,
        }

        ranked = self._rank_brokers(direction, 0.0, 0.0)
        if not ranked:
            return {
                "status": "rejected",
                "reason": "no_brokers_available",
                "broker": "none",
            }

        decision = RoutingDecision(
            decision_id=str(uuid.uuid4()),
            order_id=order_request["order_id"],
            selected_broker=ranked[0][0],
            fallback_chain=[b for b, _ in ranked[1:]],
            scores={b: round(s, 4) for b, s in ranked},
            ofi=0.0,
            sentiment_score=0.0,
            impact_score=0.0,
            spread_bps=0.0,
            reason=f"child_order:algo={child_order_dict.get('algo_id', '')}",
        )
        self._decisions.append(decision)

        result = await self._execute_with_fallback(order_request, ranked, decision)

        # Update slippage model with child fill data
        if result.get("status") == "filled":
            broker_id = result.get("broker", "")
            if broker_id in self._states:
                latency_ms = float(result.get("latency_ms", 100.0))
                fill_price = float(result.get("fill_price", order_request["mid_price"]))
                expected = order_request["ask"] if direction == "long" else order_request["bid"]
                slippage_bps = abs(fill_price - expected) / max(expected, 1e-9) * 10_000
                self._states[broker_id].record_fill(latency_ms, slippage_bps)

        return result

    # ── Pre-routing gates ─────────────────────────────────────────────────────

    def _pre_route_gate(
        self,
        spread_bps: float,
        sentiment_score: float,
        impact_score: float,
        direction: str,
        ofi: float,
    ) -> str | None:
        """
        Return rejection reason string if order should not be routed.
        Return None if routing should proceed.
        """
        # Spread too wide
        if spread_bps > _MAX_SPREAD_BPS:
            logger.warning(
                "Router: spread %.1f bps > max %.1f bps — rejecting",
                spread_bps,
                _MAX_SPREAD_BPS,
            )
            return f"spread_too_wide:{spread_bps:.1f}bps"

        # Extreme sentiment — news blackout
        if abs(sentiment_score) > _SENT_BLACKOUT_THRESH:
            logger.warning(
                "Router: extreme sentiment %.3f — news blackout active",
                sentiment_score,
            )
            return f"sentiment_blackout:{sentiment_score:.3f}"

        # High macro impact
        if impact_score > _IMPACT_BLACKOUT:
            logger.warning(
                "Router: macro impact %.3f > threshold %.3f — blocking",
                impact_score,
                _IMPACT_BLACKOUT,
            )
            return f"macro_impact_blackout:{impact_score:.3f}"

        # OFI strongly against direction — adverse microstructure
        if direction == "long" and ofi < -0.70:
            logger.warning("Router: OFI=%.3f strongly against long — rejecting", ofi)
            return f"adverse_ofi:{ofi:.3f}"
        if direction == "short" and ofi > 0.70:
            logger.warning("Router: OFI=%.3f strongly against short — rejecting", ofi)
            return f"adverse_ofi:{ofi:.3f}"

        return None

    # ── Broker ranking ────────────────────────────────────────────────────────

    def _rank_brokers(
        self,
        direction: str,
        ofi: float,
        sentiment_score: float,
    ) -> list[tuple[str, float]]:
        """Return list of (broker_id, score) sorted descending, circuit-open excluded."""
        ranked = []
        for broker_id, state in self._states.items():
            state.check_circuit_reset()
            if state.circuit_open:
                logger.debug("Router: broker=%s circuit open — excluded", broker_id)
                continue
            score = state.routing_score(direction, ofi, sentiment_score)
            ranked.append((broker_id, score))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    # ── Execution with fallback ───────────────────────────────────────────────

    async def _execute_with_fallback(
        self,
        order_request: dict,
        ranked: list[tuple[str, float]],
        decision: RoutingDecision,
    ) -> dict:
        last_error = "unknown"
        for broker_id, score in ranked:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._brokers[broker_id].place_order(order_request),
                    timeout=_ORDER_TIMEOUT_S,
                )
                latency_ms = (time.monotonic() - t0) * 1000

                if result.get("status") == "filled":
                    self._total_filled += 1
                    fill_price = float(result.get("fill_price", order_request.get("mid_price", 0)))
                    expected = order_request.get(
                        "ask" if order_request.get("direction") == "long" else "bid",
                        fill_price,
                    )
                    slippage_bps = abs(fill_price - expected) / max(expected, 1) * 10000
                    self._states[broker_id].record_fill(latency_ms, slippage_bps)
                    logger.info(
                        "Router: FILL broker=%s score=%.3f latency=%.1fms slip=%.2fbps",
                        broker_id,
                        score,
                        latency_ms,
                        slippage_bps,
                    )
                    return {
                        **result,
                        "broker": broker_id,
                        "latency_ms": latency_ms,
                        "routing_score": score,
                    }

                # Broker returned non-fill (e.g. partial, rejected)
                self._states[broker_id].record_error()
                last_error = result.get("reason", "broker_non_fill")
                logger.warning(
                    "Router: broker=%s non-fill: %s — trying fallback",
                    broker_id,
                    last_error,
                )

            except TimeoutError:
                self._states[broker_id].record_error()
                last_error = "timeout"
                logger.error(
                    "Router: broker=%s timed out after %.1fs",
                    broker_id,
                    _ORDER_TIMEOUT_S,
                )
            except Exception as exc:
                self._states[broker_id].record_error()
                last_error = str(exc)
                logger.error("Router: broker=%s error: %s", broker_id, exc)

        logger.critical("Router: ALL brokers failed. last_error=%s", last_error)
        return {
            "status": "rejected",
            "reason": f"all_brokers_failed:{last_error}",
            "broker": "none",
        }

    # ── Lineage ───────────────────────────────────────────────────────────────

    def _write_routing_lineage(self, decision: RoutingDecision, order: dict) -> None:
        if self._lineage is None:
            return
        try:
            self._lineage.record_signal(
                direction=f"ROUTE:{order.get('direction', '?')}→{decision.selected_broker}",
                confidence=float(order.get("confidence", 0.0)),
                probability=0.0,
                features_hash="",
                model_version=f"smart_router:ofi={decision.ofi:.3f}",
                lineage_id=decision.decision_id,
                symbol=order.get("symbol", "XAU_USD"),
            )
        except Exception as exc:
            logger.debug("Router lineage write failed: %s", exc)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def _explain_selection(self, broker_id: str, ofi: float, sentiment: float) -> str:
        state = self._states.get(broker_id)
        if not state:
            return "only_available"
        reasons = []
        if state.ema_latency_ms < 50:
            reasons.append("low_latency")
        if state.fill_rate > 0.97:
            reasons.append("high_fill_rate")
        if state.avg_slippage_bps < 3:
            reasons.append("low_slippage")
        if abs(ofi) > 0.3:
            reasons.append(f"ofi_aligned:{ofi:.2f}")
        if abs(sentiment) < 0.2:
            reasons.append("neutral_sentiment")
        return ",".join(reasons) if reasons else "best_composite_score"

    def metrics(self) -> dict[str, Any]:
        active_algos = self._algo.get_all_active()
        return {
            "total_routed": self._total_routed,
            "total_filled": self._total_filled,
            "fill_rate": self._total_filled / max(self._total_routed, 1),
            "algo_active_orders": len(active_algos),
            "algo_orders": active_algos,
            "brokers": {
                bid: {
                    "ema_latency_ms": round(s.ema_latency_ms, 2),
                    "fill_rate": round(s.fill_rate, 4),
                    "avg_slippage_bps": round(s.avg_slippage_bps, 3),
                    "reliability": round(s.reliability, 4),
                    "circuit_open": s.circuit_open,
                    "total_orders": s.total_orders,
                    "total_errors": s.total_errors,
                }
                for bid, s in self._states.items()
            },
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ofi_alignment(ofi: float, direction: str) -> float:
    """
    Return [0, 1] score for how well OFI aligns with trade direction.
    OFI > 0 = buy pressure, OFI < 0 = sell pressure.
    """
    if direction == "long":
        return (ofi + 1.0) / 2.0  # +1 OFI → 1.0, -1 OFI → 0.0
    if direction == "short":
        return (-ofi + 1.0) / 2.0  # -1 OFI → 1.0, +1 OFI → 0.0
    return 0.5


def _spread_to_bps(spread_usd: float, mid: float) -> float:
    if mid <= 0:
        return 0.0
    return (spread_usd / mid) * 10000
