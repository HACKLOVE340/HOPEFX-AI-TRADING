# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
payments/crypto/rate_feed.py
============================
Live crypto rate feed with TTL cache.

Fetches USD prices from CoinGecko (primary) with Binance as fallback.
Rates are cached for RATE_TTL_SECONDS (default 60 s) to avoid hammering
the external API on every payment request.

Usage
-----
    from payments.crypto.rate_feed import get_rates, coin_per_usd

    rates = await get_rates()          # {"BTC": 67500.0, "ETH": 3200.0, ...}
    btc_amount = coin_per_usd("BTC", 100.0)  # 0.001481...
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

# Supported coins → CoinGecko IDs
_COIN_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
}

# Binance symbols for fallback
_BINANCE_SYMBOLS: dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
}

RATE_TTL_SECONDS: int = int(os.getenv("CRYPTO_RATE_TTL_SECONDS", "60"))

# ── In-process TTL cache ──────────────────────────────────────────────────────
_cache_lock = asyncio.Lock()
_cached_rates: dict[str, float] = {}
_cache_ts: float = 0.0

# USDT peg — always 1.0 by definition; not a hardcoded price estimate
_STABLECOIN_RATES: dict[str, float] = {
    "USDT": 1.0,
    "USDC": 1.0,
}

# Conservative fallback rates used ONLY in non-production when all live feeds
# fail and the cache is empty.  These are intentionally stale estimates — never
# used for actual payment calculations in production (APP_ENV=production raises
# instead).  Values are updated periodically via git; not relied on for pricing.
_FALLBACK_RATES: dict[str, float] = {
    "BTC": 60_000.0,
    "ETH": 3_000.0,
    "USDT": 1.0,
    "USDC": 1.0,
}


async def _fetch_coingecko() -> dict[str, float]:
    """Fetch USD prices from CoinGecko /simple/price."""
    import aiohttp

    ids = ",".join(_COIN_IDS.values())
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session, session.get(url) as resp:
        resp.raise_for_status()
        data = await resp.json()

    rates: dict[str, float] = {}
    for coin, cg_id in _COIN_IDS.items():
        price = data.get(cg_id, {}).get("usd")
        if price and float(price) > 0:
            rates[coin] = float(price)
    return rates


async def _fetch_binance_fallback() -> dict[str, float]:
    """Fetch USD prices from Binance /api/v3/ticker/price as fallback."""
    import aiohttp

    rates: dict[str, float] = {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
        for coin, symbol in _BINANCE_SYMBOLS.items():
            try:
                url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    price = float(data.get("price", 0))
                    if price > 0:
                        rates[coin] = price
            except Exception as exc:
                logger.debug("Binance fallback failed for %s: %s", coin, exc)
    # USDT is always 1.0
    rates["USDT"] = 1.0
    return rates


async def get_rates(force_refresh: bool = False) -> dict[str, float]:
    """
    Return current USD prices for supported coins.

    Uses a TTL cache (RATE_TTL_SECONDS). On cache miss, tries CoinGecko
    first, then Binance, then falls back to the last known good rates.
    USDT is always 1.0.

    Returns
    -------
    Dict mapping coin symbol → USD price per coin (e.g. {"BTC": 67500.0}).
    """
    global _cached_rates, _cache_ts

    async with _cache_lock:
        now = time.monotonic()
        if not force_refresh and _cached_rates and (now - _cache_ts) < RATE_TTL_SECONDS:
            return dict(_cached_rates)

        # Try CoinGecko
        try:
            rates = await _fetch_coingecko()
            if len(rates) >= 2:  # at least BTC + ETH  # noqa: PLR2004
                _cached_rates = rates
                _cache_ts = now
                logger.debug("Crypto rates refreshed from CoinGecko: %s", rates)
                return dict(rates)
        except Exception as exc:
            logger.warning("CoinGecko rate fetch failed: %s — trying Binance", exc)

        # Try Binance
        try:
            rates = await _fetch_binance_fallback()
            if rates:
                _cached_rates = rates
                _cache_ts = now
                logger.warning("Crypto rates from Binance fallback: %s", rates)
                return dict(rates)
        except Exception as exc:
            logger.warning("Binance rate fetch failed: %s — using last known rates", exc)

        # Use last known good cache (stale but real)
        if _cached_rates:
            logger.warning("Using stale cached crypto rates (age=%.0fs)", now - _cache_ts)
            return dict(_cached_rates)

        # No live data and no cache — stablecoins are safe to return at peg,
        # but volatile coins (BTC, ETH) must not use hardcoded prices for
        # payment calculations. Raise so callers fail explicitly.
        _is_production = os.getenv("APP_ENV", "production").lower() == "production"
        if _is_production:
            raise RuntimeError(
                "All crypto rate feeds failed (CoinGecko + Binance) and no cached "
                "rates are available. Cannot safely price volatile coins for payment. "
                "Check network connectivity and CRYPTO_RATE_TTL_SECONDS configuration."
            )
        # Non-production: return conservative fallback rates so tests can proceed.
        # These are stale estimates — never used for payment pricing in production.
        logger.error(
            "All rate feeds failed and cache is empty — returning fallback rates "
            "(non-production). Do not use for payment calculations."
        )
        return dict(_FALLBACK_RATES)


def coin_per_usd_sync(coin: str, usd_amount: float) -> float | None:
    """
    Synchronous helper: convert USD to coin amount using cached rates.

    Returns None if no cached rate is available for the coin.
    Stablecoins (USDT, USDC) always return at peg (1.0).
    Volatile coins return None when the cache is empty — callers must
    handle None and not fall back to hardcoded prices.
    """
    coin = coin.upper()
    rate = _cached_rates.get(coin) or _STABLECOIN_RATES.get(coin)
    if not rate:
        return None
    return usd_amount / rate


async def coin_per_usd(coin: str, usd_amount: float) -> float:
    """
    Async helper: convert USD to coin amount using live rates.

    Raises ValueError if the coin is unsupported.
    """
    coin = coin.upper()
    if coin not in _COIN_IDS:
        raise ValueError(f"Unsupported coin: {coin}")
    rates = await get_rates()
    price = rates.get(coin)
    if not price:
        raise ValueError(f"No rate available for {coin}")
    return usd_amount / price
