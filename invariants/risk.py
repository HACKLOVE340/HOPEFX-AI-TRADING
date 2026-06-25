# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.risk — risk, exposure, leverage, liquidity & concentration invariants.

Pure predicates from the framework's risk-engine sections: hard limits, VaR,
leverage, margin buffer, liquidation proximity, drawdown, daily loss, per-
dimension exposure, concentration, hidden/effective leverage, liquidity, and
catastrophic-loss kill-switch triggers. Each returns list[Violation].
"""

from __future__ import annotations

from typing import Mapping

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Hidden Risk"


def verify_daily_loss(daily_loss: float, limit: float) -> list[Violation]:
    if not _is_finite_number(daily_loss):
        return [_v(_RULE, CONSTITUTIONAL, "daily_loss is non-finite")]
    if daily_loss > limit:
        return [_v(_RULE, CRITICAL, f"daily loss {daily_loss} exceeds limit {limit}", value=daily_loss, limit=limit)]
    return []


def verify_drawdown(drawdown_pct: float, max_drawdown_pct: float) -> list[Violation]:
    if not _is_finite_number(drawdown_pct):
        return [_v(_RULE, CONSTITUTIONAL, "drawdown is non-finite")]
    if drawdown_pct > max_drawdown_pct:
        return [_v(_RULE, CRITICAL, f"drawdown {drawdown_pct}% exceeds max {max_drawdown_pct}%")]
    return []


def verify_var(portfolio_var: float, approved_var: float) -> list[Violation]:
    if not _is_finite_number(portfolio_var):
        return [_v(_RULE, CONSTITUTIONAL, "portfolio VaR is non-finite")]
    if portfolio_var > approved_var:
        return [_v(_RULE, CRITICAL, f"portfolio VaR {portfolio_var} exceeds approved {approved_var}")]
    return []


def verify_leverage(effective_leverage: float, max_leverage: float) -> list[Violation]:
    """Effective (not just nominal) leverage must stay within approval — hidden
    leverage from derivatives/synthetics is a top institutional failure."""
    if not _is_finite_number(effective_leverage):
        return [_v("No Hidden Exposure", CONSTITUTIONAL, "effective leverage is non-finite")]
    if effective_leverage > max_leverage:
        return [_v("No Hidden Exposure", CRITICAL,
                   f"effective leverage {effective_leverage}x exceeds max {max_leverage}x")]
    return []


def verify_margin_buffer(margin_buffer: float, minimum: float) -> list[Violation]:
    if not _is_finite_number(margin_buffer):
        return [_v(_RULE, CONSTITUTIONAL, "margin buffer is non-finite")]
    if margin_buffer < minimum:
        return [_v(_RULE, CRITICAL, f"margin buffer {margin_buffer} below minimum {minimum}")]
    return []


def verify_liquidation_distance(distance_pct: float, threshold_pct: float) -> list[Violation]:
    """Proximity to forced liquidation must stay above a safety threshold."""
    if not _is_finite_number(distance_pct):
        return [_v(_RULE, CONSTITUTIONAL, "liquidation distance is non-finite")]
    if distance_pct < threshold_pct:
        return [_v(_RULE, CRITICAL, f"liquidation distance {distance_pct}% below threshold {threshold_pct}%")]
    return []


def verify_order_liquidity(order_size: float, available_liquidity: float, max_fraction: float = 0.25) -> list[Violation]:
    """An order must not consume more than a safe fraction of available liquidity
    (liquidity-mirage / market-impact guard)."""
    if not (_is_finite_number(order_size) and _is_finite_number(available_liquidity)):
        return [_v(_RULE, CONSTITUTIONAL, "order size / liquidity non-finite")]
    if available_liquidity <= 0:
        return [_v(_RULE, CRITICAL, "no available liquidity")]
    if order_size > available_liquidity * max_fraction:
        return [_v(_RULE, CRITICAL,
                   f"order {order_size} > {max_fraction:.0%} of liquidity {available_liquidity}")]
    return []


def verify_exposure_limits(exposure: Mapping[str, float], limits: Mapping[str, float]) -> list[Violation]:
    """Per-dimension exposure (symbol/sector/asset-class/geo/strategy/counterparty
    /exchange/currency) must each stay within its limit. No hidden exposure."""
    out: list[Violation] = []
    for dim, val in exposure.items():
        if not _is_finite_number(val):
            out.append(_v("No Hidden Exposure", CONSTITUTIONAL, f"exposure[{dim}] is non-finite"))
            continue
        lim = limits.get(dim)
        if lim is not None and val > lim:
            out.append(_v("No Hidden Exposure", CRITICAL, f"exposure[{dim}] {val} exceeds limit {lim}"))
    return out


def verify_concentration(largest_position_pct: float, limit_pct: float) -> list[Violation]:
    """A 'diversified' portfolio must not be secretly concentrated."""
    if not _is_finite_number(largest_position_pct):
        return [_v("No Hidden Exposure", CONSTITUTIONAL, "concentration is non-finite")]
    if largest_position_pct > limit_pct:
        return [_v("No Hidden Exposure", WARNING,
                   f"largest position {largest_position_pct}% exceeds concentration limit {limit_pct}%")]
    return []


def verify_dependency_concentration(dependency_pct: float, max_pct: float, name: str) -> list[Violation]:
    """No single exchange/broker/market may be relied on beyond a max share."""
    if _is_finite_number(dependency_pct) and dependency_pct > max_pct:
        return [_v("No Critical Single Point Of Failure", WARNING,
                   f"{name} dependency {dependency_pct}% exceeds {max_pct}%")]
    return []


def catastrophic_loss_triggers(drawdown_pct: float, daily_loss: float, risk_violation: bool,
                               dd_kill: float, loss_kill: float) -> list[Violation]:
    """If any catastrophic threshold is breached, trading must halt (kill switch).
    Returns a CONSTITUTIONAL violation that the caller must act on by halting."""
    out: list[Violation] = []
    if _is_finite_number(drawdown_pct) and drawdown_pct > dd_kill:
        out.append(_v("No Unbounded Failure", CONSTITUTIONAL, f"drawdown {drawdown_pct}% > kill {dd_kill}% — HALT"))
    if _is_finite_number(daily_loss) and daily_loss > loss_kill:
        out.append(_v("No Unbounded Failure", CONSTITUTIONAL, f"daily loss {daily_loss} > kill {loss_kill} — HALT"))
    if risk_violation:
        out.append(_v("No Unbounded Failure", CONSTITUTIONAL, "hard risk violation — HALT"))
    return out
