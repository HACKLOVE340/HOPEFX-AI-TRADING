# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/sources/twelve_data.py
==================================
Twelve Data REST tick-source adapter.

Uses the /price endpoint for the latest price and /quote for bid/ask.
Free tier: 800 API credits/day, 8 credits/minute.
Docs: https://twelvedata.com/docs#price

Environment variable: TWELVE_API_KEY
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_TD_BASE_URL = "https://api.twelvedata.com"
_TD_PRICE_EP = "/price"
_TD_QUOTE_EP = "/quote"


class TwelveDataSource:
    """
    Twelve Data /price REST adapter.

    Parameters
    ----------
    api_key:
        Twelve Data API key.
    timeout:
        Per-request HTTP timeout in seconds.
    session:
        Optional shared aiohttp.ClientSession.
    use_quote:
        When True, use /quote to get bid/ask and compute mid.
        When False (default), use /price for the last traded price.
    """

    name: str = "twelve_data"

    def __init__(
        self,
        api_key: str = "",
        timeout: float = 5.0,
        session: aiohttp.ClientSession | None = None,
        use_quote: bool = False,
    ) -> None:
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._owns_session = session is None
        self._use_quote = use_quote
        self._credits_exhausted: bool = False

    async def fetch(self, symbol: str, cfg: dict[str, Any]) -> float | None:
        """
        Return the latest price for *symbol* or None on failure.

        Parameters
        ----------
        symbol:
            Canonical symbol (e.g. ``"XAUUSD"``).
        cfg:
            Symbol config dict — must contain ``twelve_data_symbol``.
        """
        if not self._api_key:
            logger.debug("TwelveDataSource: no API key — skipping %s", symbol)
            return None

        td_symbol = cfg.get("twelve_data_symbol", "")
        if not td_symbol:
            logger.warning("TwelveDataSource: no twelve_data_symbol for %s", symbol)
            return None

        endpoint = _TD_QUOTE_EP if self._use_quote else _TD_PRICE_EP
        params = {
            "symbol": td_symbol,
            "apikey": self._api_key,
        }

        session = self._session or aiohttp.ClientSession(timeout=self._timeout)
        try:
            url = f"{_TD_BASE_URL}{endpoint}"
            async with session.get(url, params=params, timeout=self._timeout) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            # Check for API-level errors.
            status = data.get("status", "")
            if status == "error":
                code = data.get("code", 0)
                msg = data.get("message", "")
                if code in (429, 400) or "credits" in msg.lower() or "limit" in msg.lower():
                    if not self._credits_exhausted:
                        logger.warning("TwelveDataSource[%s]: credits/rate-limit: %s", symbol, msg)
                        self._credits_exhausted = True
                else:
                    logger.warning("TwelveDataSource[%s]: API error %s: %s", symbol, code, msg)
                return None

            self._credits_exhausted = False

            if self._use_quote:
                # /quote returns bid/ask — compute mid.
                bid_str = data.get("bid", "")
                ask_str = data.get("ask", "")
                if bid_str and ask_str:
                    bid = float(bid_str)
                    ask = float(ask_str)
                    if bid > 0 and ask > 0 and ask >= bid:
                        return (bid + ask) / 2.0
                # Fall back to close price if bid/ask unavailable.
                close_str = data.get("close", "")
                if close_str:
                    price = float(close_str)
                    return price if price > 0 else None
                return None
            else:
                # /price returns {"price": "1234.56"}
                price_str = data.get("price", "")
                if not price_str:
                    return None
                price = float(price_str)
                return price if price > 0 else None

        except aiohttp.ClientResponseError as exc:
            logger.warning("TwelveDataSource[%s]: HTTP %s: %s", symbol, exc.status, exc.message)
            return None
        except aiohttp.ClientError as exc:
            logger.warning("TwelveDataSource[%s]: connection error: %s", symbol, exc)
            return None
        except (ValueError, KeyError) as exc:
            logger.warning("TwelveDataSource[%s]: parse error: %s", symbol, exc)
            return None
        except Exception as exc:
            logger.error("TwelveDataSource[%s]: unexpected error: %s", symbol, exc)
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
            "credits_exhausted": self._credits_exhausted,
            "use_quote": self._use_quote,
        }
