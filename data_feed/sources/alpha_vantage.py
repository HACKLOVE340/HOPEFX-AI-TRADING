# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/sources/alpha_vantage.py
====================================
Alpha Vantage REST tick-source adapter.

Uses the CURRENCY_EXCHANGE_RATE function for both FX pairs and commodities
(XAU/USD is treated as a currency pair by Alpha Vantage).

Free tier: 25 requests/day, 5 requests/minute.
Docs: https://www.alphavantage.co/documentation/#currency-exchange

Environment variable: ALPHA_VANTAGE_KEY  (alias: ALPHA_VANTAGE_API_KEY)
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_AV_BASE_URL = "https://www.alphavantage.co/query"
_AV_FUNCTION = "CURRENCY_EXCHANGE_RATE"


class AlphaVantageSource:
    """
    Alpha Vantage CURRENCY_EXCHANGE_RATE adapter.

    Parameters
    ----------
    api_key:
        Alpha Vantage API key.  Resolved from env vars if not supplied.
    timeout:
        Per-request HTTP timeout in seconds.
    session:
        Optional shared aiohttp.ClientSession.  If None, a new session is
        created per fetch (suitable for low-frequency polling).
    """

    name: str = "alpha_vantage"

    def __init__(
        self,
        api_key: str = "",
        timeout: float = 5.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._owns_session = session is None
        # Track rate-limit hits so callers can back off.
        self._rate_limited: bool = False

    async def fetch(self, symbol: str, cfg: dict[str, Any]) -> float | None:
        """
        Return the latest exchange rate for *symbol* or None on failure.

        Parameters
        ----------
        symbol:
            Canonical symbol (e.g. ``"XAUUSD"``).
        cfg:
            Symbol config dict — must contain ``alpha_vantage_symbol`` and
            ``alpha_vantage_market``.
        """
        if not self._api_key:
            logger.debug("AlphaVantageSource: no API key — skipping %s", symbol)
            return None

        from_sym = cfg.get("alpha_vantage_symbol", "")
        to_sym = cfg.get("alpha_vantage_market", "USD")
        if not from_sym:
            logger.warning("AlphaVantageSource: no alpha_vantage_symbol for %s", symbol)
            return None

        params = {
            "function": _AV_FUNCTION,
            "from_currency": from_sym,
            "to_currency": to_sym,
            "apikey": self._api_key,
        }

        session = self._session or aiohttp.ClientSession(timeout=self._timeout)
        try:
            async with session.get(_AV_BASE_URL, params=params, timeout=self._timeout) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            # Alpha Vantage wraps the rate in a nested key.
            rate_block = data.get("Realtime Currency Exchange Rate", {})
            if not rate_block:
                # Check for rate-limit / error messages.
                note = data.get("Note", "") or data.get("Information", "")
                if note:
                    if not self._rate_limited:
                        logger.warning("AlphaVantageSource[%s]: API note: %s", symbol, note[:120])
                        self._rate_limited = True
                else:
                    logger.warning("AlphaVantageSource[%s]: unexpected response: %s", symbol, str(data)[:200])
                return None

            self._rate_limited = False
            raw_rate = rate_block.get("5. Exchange Rate", "")
            if not raw_rate:
                return None

            price = float(raw_rate)
            return price if price > 0 else None

        except aiohttp.ClientResponseError as exc:
            logger.warning("AlphaVantageSource[%s]: HTTP %s: %s", symbol, exc.status, exc.message)
            return None
        except aiohttp.ClientError as exc:
            logger.warning("AlphaVantageSource[%s]: connection error: %s", symbol, exc)
            return None
        except (ValueError, KeyError) as exc:
            logger.warning("AlphaVantageSource[%s]: parse error: %s", symbol, exc)
            return None
        except Exception as exc:
            logger.error("AlphaVantageSource[%s]: unexpected error: %s", symbol, exc)
            return None
        finally:
            if self._owns_session and not self._session:
                await session.close()

    async def close(self) -> None:
        """Close the shared session if this adapter owns it."""
        if self._session and self._owns_session:
            await self._session.close()
            self._session = None

    def status(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "api_key_set": bool(self._api_key),
            "rate_limited": self._rate_limited,
        }
