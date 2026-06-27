# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.market_structure — auctions, halts, circuit breakers, venues.

Pure predicates from the framework's market-structure section: auction-state
correctness, exchange/market-wide circuit breakers, limit-up/limit-down bands,
halt enforcement, dark-pool/OTC routing eligibility, and cross-venue price
sanity. Each returns list[Violation].
"""

from __future__ import annotations

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


def verify_not_halted(symbol_halted: bool, market_wide_halt: bool = False) -> list[Violation]:
    """No order may be sent into a halted symbol or a market-wide halt."""
    if market_wide_halt:
        return [_v("No Unauthorized Trade", CONSTITUTIONAL, "market-wide halt active — all trading blocked")]
    if symbol_halted:
        return [_v("No Unauthorized Trade", CRITICAL, "symbol halted — trading blocked")]
    return []


def verify_circuit_breaker(decline_pct: float, level1: float, level2: float, level3: float) -> list[Violation]:
    """Market-wide circuit-breaker levels: trading must pause/stop on breach."""
    if not _is_finite_number(decline_pct):
        return [_v("No Data Corruption", CRITICAL, "decline pct non-finite")]
    if decline_pct >= level3:
        return [
            _v("No Unbounded Failure", CONSTITUTIONAL, f"Level-3 circuit breaker: decline {decline_pct}% — HALT day")
        ]
    if decline_pct >= level2:
        return [_v("No Unbounded Failure", CRITICAL, f"Level-2 circuit breaker: decline {decline_pct}% — pause")]
    if decline_pct >= level1:
        return [_v("No Unbounded Failure", WARNING, f"Level-1 circuit breaker: decline {decline_pct}% — pause")]
    return []


def verify_luld_band(price: float, reference: float, band_pct: float) -> list[Violation]:
    """An order priced outside the limit-up/limit-down band must be rejected."""
    if not (_is_finite_number(price) and _is_finite_number(reference)) or reference <= 0:
        return [_v("No Data Corruption", CRITICAL, f"invalid LULD inputs price={price} ref={reference}")]
    dev = abs(price - reference) / reference * 100
    if dev > band_pct:
        return [
            _v(
                "No Unauthorized Trade",
                CRITICAL,
                f"price {price} outside LULD band ±{band_pct}% of {reference} ({dev:.2f}%)",
            )
        ]
    return []


def verify_auction_state(order_type: str, auction_phase: str) -> list[Violation]:
    """During an opening/closing auction only auction-eligible order types apply;
    a continuous-only order type submitted into an auction is an error."""
    continuous_only = {"market_on_continuous"}
    if auction_phase in ("opening_auction", "closing_auction") and order_type in continuous_only:
        return [_v("No Unauthorized Trade", WARNING, f"order type '{order_type}' not valid during {auction_phase}")]
    return []


def verify_venue_eligible(symbol: str, venue: str, allowed_venues: dict[str, set[str]]) -> list[Violation]:
    """Routing to a dark pool / OTC / exchange must respect per-symbol eligibility."""
    allowed = allowed_venues.get(symbol)
    if allowed is not None and venue not in allowed:
        return [_v("No Unauthorized Trade", CRITICAL, f"{symbol} not eligible for venue {venue}")]
    return []


def verify_cross_venue_price(prices: dict[str, float], max_dev_pct: float = 2.0) -> list[Violation]:
    """Prices for the same instrument across venues must not diverge excessively
    (cross-market arbitrage / stale-venue guard)."""
    vals = [p for p in prices.values() if _is_finite_number(p) and p > 0]
    if len(vals) < 2:  # noqa: PLR2004 — need ≥2 venues to compare
        return []
    lo, hi = min(vals), max(vals)
    dev = (hi - lo) / lo * 100
    if dev > max_dev_pct:
        return [_v("No Hidden Risk", CRITICAL, f"cross-venue price divergence {dev:.2f}% > {max_dev_pct}%")]
    return []
