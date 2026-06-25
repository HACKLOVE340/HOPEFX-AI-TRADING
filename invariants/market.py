# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.market — market-data, microstructure, time/clock & feed invariants.

Pure predicates from the framework's market/data sections: tick & spread
validity, order-book integrity, multi-feed agreement, staleness, clock drift,
event ordering, and corporate/calendar integrity. Each returns list[Violation].
"""

from __future__ import annotations

from invariants.constitution import (
    CRITICAL,
    WARNING,
    Violation,
    _EPS,
    _is_finite_number,
    _v,
)

_RULE = "No Data Corruption"
_MIN_FEEDS = 2  # need ≥2 feeds to compare for divergence


def verify_orderbook_integrity(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> list[Violation]:
    """Book must have depth on both sides and a non-crossed top-of-book."""
    out: list[Violation] = []
    if not bids or not asks:
        out.append(_v(_RULE, CRITICAL, "order book empty on one side"))
        return out
    if any(p <= 0 or q < 0 for p, q in bids + asks):
        out.append(_v(_RULE, CRITICAL, "order book has non-positive price or negative size"))
    if bids[0][0] > asks[0][0] + _EPS:
        out.append(_v(_RULE, CRITICAL, f"crossed book: best bid {bids[0][0]} > best ask {asks[0][0]}"))
    return out


def verify_feed_agreement(prices: dict[str, float], max_dev_pct: float = 1.0) -> list[Violation]:
    """Multiple price feeds for the same instrument must not diverge beyond a
    threshold (feed poisoning / stale-feed guard)."""
    vals = [p for p in prices.values() if _is_finite_number(p) and p > 0]
    if len(vals) < _MIN_FEEDS:
        return []
    lo, hi = min(vals), max(vals)
    dev = (hi - lo) / lo * 100 if lo > 0 else float("inf")
    if dev > max_dev_pct:
        return [_v("No Hidden Risk", CRITICAL, f"feed divergence {dev:.2f}% > {max_dev_pct}% across {list(prices)}",
                   spread_pct=round(dev, 4))]
    return []


def verify_data_freshness(age_seconds: float, max_age_seconds: float, name: str = "market_data") -> list[Violation]:
    """Market/portfolio/risk data must be fresh — stale data drives wrong trades."""
    if not _is_finite_number(age_seconds):
        return [_v(_RULE, CRITICAL, f"{name} age is non-finite")]
    if age_seconds > max_age_seconds:
        return [_v("No Hidden Risk", CRITICAL, f"{name} stale: {age_seconds:.1f}s > {max_age_seconds}s",
                   age=age_seconds, limit=max_age_seconds)]
    return []


def verify_clock_drift(drift_ms: float, max_drift_ms: float = 50.0) -> list[Violation]:
    """Service clocks must stay synced — drift causes duplicate/incorrect trades."""
    if not _is_finite_number(drift_ms):
        return [_v(_RULE, CRITICAL, "clock drift is non-finite")]
    if abs(drift_ms) > max_drift_ms:
        return [_v("No Data Corruption", CRITICAL, f"clock drift {drift_ms}ms > {max_drift_ms}ms", drift_ms=drift_ms)]
    return []


def verify_no_future_event(event_ts: float, now: float, tol_s: float = 1.0) -> list[Violation]:
    """No event may be timestamped in the future (causality / replay integrity)."""
    if _is_finite_number(event_ts) and _is_finite_number(now) and event_ts > now + tol_s:
        return [_v("No Data Corruption", CRITICAL, f"future-dated event ts={event_ts} > now={now}")]
    return []


def verify_event_sequence(prev_seq: int, seq: int) -> list[Violation]:
    """Event-sourced streams must be gapless and monotonic (exactly-once)."""
    if seq != prev_seq + 1:
        sev = CRITICAL if seq <= prev_seq else WARNING
        return [_v("No Data Corruption", sev, f"event sequence break: expected {prev_seq + 1}, got {seq}")]
    return []


def verify_causal_order(cause_ts: float, effect_ts: float) -> list[Violation]:
    """Cause must precede effect (signal before trade, etc.)."""
    if _is_finite_number(cause_ts) and _is_finite_number(effect_ts) and cause_ts > effect_ts + _EPS:
        return [_v("No State Corruption", CRITICAL, f"causality violated: cause {cause_ts} after effect {effect_ts}")]
    return []


def verify_market_open(is_open: bool, halted: bool = False) -> list[Violation]:
    """A halted or closed market must not accept trades."""
    out: list[Violation] = []
    if halted:
        out.append(_v("No Unauthorized Trade", CRITICAL, "market is halted — trading must be blocked"))
    if not is_open:
        out.append(_v("No Unauthorized Trade", WARNING, "market is closed"))
    return out


def verify_symbol_tradeable(symbol: str, delisted: set[str] | None = None,
                            tradeable: set[str] | None = None) -> list[Violation]:
    """Delisted/unknown instruments must be blocked."""
    if delisted and symbol in delisted:
        return [_v("No Unauthorized Trade", CRITICAL, f"symbol {symbol} is delisted")]
    if tradeable is not None and symbol not in tradeable:
        return [_v("No Unauthorized Trade", CRITICAL, f"symbol {symbol} not in tradeable universe")]
    return []
