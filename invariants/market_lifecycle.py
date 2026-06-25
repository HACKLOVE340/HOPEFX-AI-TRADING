# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.market_lifecycle — instrument lifecycle, exchange rules & settlement.

Pure predicates for the framework's market-microstructure lifecycle categories
distinct from ``invariants.market_structure`` (halts/LULD): exchange order rules
(tick size, lot size, min/max notional), corporate actions applied, stable
symbol mapping, instrument tradability over its lifecycle (listed→delisted),
settlement-calendar correctness, tax/withholding applied, and liquidity-mirage
detection (quoted size that vanishes on execution). Each returns ``list[Violation]``.
"""

from __future__ import annotations

from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _EPS,
    _is_finite_number,
    _v,
)

_RULE = "No Unauthorized Trade"


def verify_price_on_tick(price: float, tick_size: float) -> list[Violation]:
    """An order price must be a multiple of the instrument's tick size."""
    if not (_is_finite_number(price) and _is_finite_number(tick_size)) or tick_size <= 0:
        return [_v("No Data Corruption", CRITICAL, "price/tick non-finite or tick<=0")]
    remainder = abs(price / tick_size - round(price / tick_size))
    if remainder > _EPS:
        return [_v(_RULE, CRITICAL, f"price {price} not a multiple of tick size {tick_size}")]
    return []


def verify_quantity_on_lot(quantity: float, lot_size: float) -> list[Violation]:
    """An order quantity must be a multiple of the instrument's lot size."""
    if not (_is_finite_number(quantity) and _is_finite_number(lot_size)) or lot_size <= 0:
        return [_v("No Data Corruption", CRITICAL, "quantity/lot non-finite or lot<=0")]
    remainder = abs(quantity / lot_size - round(quantity / lot_size))
    if remainder > _EPS:
        return [_v(_RULE, CRITICAL, f"quantity {quantity} not a multiple of lot size {lot_size}")]
    return []


def verify_notional_within_bounds(notional: float, min_notional: float, max_notional: float) -> list[Violation]:
    """Order notional must respect the exchange's min/max notional limits."""
    if not _is_finite_number(notional):
        return [_v("No Data Corruption", CRITICAL, "notional non-finite")]
    if notional < min_notional:
        return [_v(_RULE, CRITICAL, f"notional {notional} below exchange minimum {min_notional}")]
    if notional > max_notional:
        return [_v(_RULE, CRITICAL, f"notional {notional} above exchange maximum {max_notional}")]
    return []


def verify_corporate_action_applied(applied: bool, action: str = "split") -> list[Violation]:
    """A corporate action (split/dividend) must be reflected in price/position."""
    if not applied:
        return [_v("No Data Corruption", CONSTITUTIONAL, f"corporate action not applied: {action}")]
    return []


def verify_symbol_mapping_stable(internal: Any, resolved: Any, symbol: str = "") -> list[Violation]:
    """Symbol resolution must be stable (mapping drift trades the wrong instrument)."""
    if internal != resolved:
        return [_v("No Data Corruption", CONSTITUTIONAL,
                   f"symbol mapping drift for {symbol}: {internal!r} != {resolved!r}")]
    return []


def verify_instrument_tradable(listed: bool, delisted: bool, symbol: str = "") -> list[Violation]:
    """An instrument must be listed and not delisted/expired before trading."""
    if delisted:
        return [_v(_RULE, CONSTITUTIONAL, f"trade on delisted/expired instrument {symbol}")]
    if not listed:
        return [_v(_RULE, CRITICAL, f"trade on not-yet-listed instrument {symbol}")]
    return []


def verify_settlement_date_valid(is_business_day: bool, settlement_date: str = "") -> list[Violation]:
    """Settlement must fall on a valid business/exchange day."""
    if not is_business_day:
        return [_v("No Data Corruption", CRITICAL, f"settlement date {settlement_date} is not a valid business day")]
    return []


def verify_tax_applied(expected_tax: float, applied_tax: float, tol: float = 0.01) -> list[Violation]:
    """Tax/withholding must be computed and applied correctly."""
    if not (_is_finite_number(expected_tax) and _is_finite_number(applied_tax)):
        return [_v("No Data Corruption", CRITICAL, "tax values non-finite")]
    if abs(expected_tax - applied_tax) > tol:
        return [_v("No Compliance Breach", CONSTITUTIONAL,
                   f"tax mismatch: expected {expected_tax} != applied {applied_tax}")]
    return []


def verify_no_liquidity_mirage(quoted_size: float, executable_size: float, max_shortfall: float) -> list[Violation]:
    """Quoted depth must roughly hold up on execution (phantom liquidity)."""
    if not (_is_finite_number(quoted_size) and _is_finite_number(executable_size)):
        return [_v("No Data Corruption", CRITICAL, "liquidity sizes non-finite")]
    if quoted_size > 0:
        shortfall = (quoted_size - executable_size) / quoted_size
        if shortfall > max_shortfall:
            return [_v("No Data Corruption", WARNING,
                       f"liquidity mirage: only {executable_size}/{quoted_size} executable (shortfall {round(shortfall, 3)})")]
    return []


def verify_position_within_exchange_limit(position: float, exchange_limit: float, symbol: str = "") -> list[Violation]:
    """A position must not breach exchange/regulatory position limits."""
    if _is_finite_number(position) and _is_finite_number(exchange_limit) and abs(position) > exchange_limit:
        return [_v("No Compliance Breach", CONSTITUTIONAL,
                   f"position {position} on {symbol} exceeds exchange limit {exchange_limit}")]
    return []
