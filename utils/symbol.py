# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
utils/symbol.py — canonical symbol normalisation (M-6)

Two canonical forms exist in this codebase:

  XAUUSD   — MT5, internal engine, database, price-bounds keys
  XAU_USD  — OANDA REST/stream, Finnhub, nuclear engine, CSV filenames

All external input (user API requests, broker callbacks, config values)
must be normalised to one of these forms before use.  Use:

    to_mt5(symbol)   → "XAUUSD"   (no separator)
    to_oanda(symbol) → "XAU_USD"  (underscore separator)
    canonical(symbol) → "XAUUSD"  (default internal form)

The functions accept any reasonable variant:
    "XAU/USD", "xau_usd", "XAUUSD", "XAU_USD", "XAU USD", "GOLD"
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Alias table: maps known non-standard names to their canonical XAUUSD form.
# Add entries here when new instruments or broker-specific aliases appear.
# ---------------------------------------------------------------------------
_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSD",
    "GC": "XAUUSD",
    "GC=F": "XAUUSD",
    "SILVER": "XAGUSD",
    "SI=F": "XAGUSD",
    "PLATINUM": "XPTUSD",
    "PL=F": "XPTUSD",
    "PALLADIUM": "XPDUSD",
    "PA=F": "XPDUSD",
    "BITCOIN": "BTCUSD",
    "BTC": "BTCUSD",
}


def _strip(symbol: str) -> str:
    """Remove separators and whitespace, uppercase."""
    return symbol.upper().replace("/", "").replace("_", "").replace(" ", "").replace("-", "")


def to_mt5(symbol: str) -> str:
    """
    Normalise *symbol* to MT5 / internal form: no separator, uppercase.

    Examples
    --------
    >>> to_mt5("XAU_USD")
    'XAUUSD'
    >>> to_mt5("xau/usd")
    'XAUUSD'
    >>> to_mt5("GOLD")
    'XAUUSD'
    """
    stripped = _strip(symbol)
    return _ALIASES.get(stripped, stripped)


def to_oanda(symbol: str) -> str:
    """
    Normalise *symbol* to OANDA / Finnhub form: BASE_QUOTE, uppercase.

    For 6-character symbols the split point is at position 3.
    For longer symbols (e.g. "BTCUSD") the split is still at 3.

    Examples
    --------
    >>> to_oanda("XAUUSD")
    'XAU_USD'
    >>> to_oanda("xau/usd")
    'XAU_USD'
    >>> to_oanda("GOLD")
    'XAU_USD'
    """
    mt5 = to_mt5(symbol)
    if "_" in mt5:
        # Already has separator (shouldn't happen after to_mt5, but be safe)
        return mt5
    if len(mt5) >= 6:
        return mt5[:3] + "_" + mt5[3:]
    # Short symbol — return as-is (e.g. "BTC" alone)
    return mt5


def canonical(symbol: str) -> str:
    """
    Return the canonical internal form (MT5 / no-separator).

    This is the preferred form for:
    - Database storage
    - Price-bounds config keys
    - Redis tick keys (hopefx:tick:XAUUSD)
    - ML model filenames

    Use ``to_oanda()`` only when calling OANDA REST/stream APIs or
    Finnhub WebSocket subscriptions.
    """
    return to_mt5(symbol)


def are_equivalent(a: str, b: str) -> bool:
    """Return True when *a* and *b* refer to the same instrument."""
    return to_mt5(a) == to_mt5(b)
