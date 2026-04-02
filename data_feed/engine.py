# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ProductionDataEngine — real-time XAUUSD price ingestion.

Architecture
------------
* Primary source  : GoldAPI (REST, 1-second polling)
* Secondary source: MetalPriceAPI (REST, same interval)
* Last-resort     : MT5 demo account via MT5Backup

Failure handling
----------------
* Per-provider retry loop with configurable max_retries.
* Circuit breaker: provider is skipped after circuit_breaker_threshold
  consecutive failures and re-tried after a cool-down period.
* Health monitor: forces provider rotation when no update arrives for 30 s.
* Stale-data guard: rejects prices outside a plausible XAUUSD range.

Subscriber pattern
------------------
Any object with an ``on_new_price(price: float)`` coroutine can subscribe.
The engine calls all subscribers concurrently on every confirmed tick.

Usage
-----
    engine = ProductionDataEngine()
    engine.subscribe(brain)
    engine.subscribe(risk_manager)
    asyncio.create_task(engine.start())
"""

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import aiohttp
import yaml
import contextlib

logger = logging.getLogger(__name__)

# Plausible XAUUSD price range used to reject obviously bad ticks.
_PRICE_MIN = 1_000.0
_PRICE_MAX = 10_000.0

# How long (seconds) a circuit-breaker stays open before re-trying.
_CIRCUIT_BREAKER_COOLDOWN = 60


def _resolve_env(value: Any) -> str:
    """
    Expand ``${ENV_VAR:default}`` placeholders in YAML string values.

    If the environment variable is set its value is returned; otherwise the
    default after the colon is used.  Plain strings are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        if ":" in inner:
            var, default = inner.split(":", 1)
        else:
            var, default = inner, ""
        return os.environ.get(var, default)
    return value


class ProductionDataEngine:
    """
    Async, multi-provider real-time price engine for XAUUSD.

    Parameters
    ----------
    config_path:
        Path to ``config/data_feed.yaml`` (relative to CWD or absolute).
    """

    def __init__(self, config_path: str = "config/data_feed.yaml") -> None:
        self._raw_config = self._load_config(config_path)
        self._cfg = self._raw_config["data_feed"]

        # State
        self.current_price: float | None = None
        self.last_update: datetime | None = None
        self.price_history: deque = deque(maxlen=int(self._cfg.get("history_size", 5000)))
        self.subscribers: list[Any] = []
        self.is_running: bool = True

        # Provider management
        self._fallback_order: list[str] = self._cfg.get("fallback_order", ["goldapi", "metalpriceapi", "mt5_demo"])
        self.active_provider: str = self._cfg.get("primary", self._fallback_order[0])

        # Per-provider failure counters and circuit-breaker open timestamps.
        self._fail_count: dict[str, int] = dict.fromkeys(self._fallback_order, 0)
        self._circuit_open_at: dict[str, datetime | None] = dict.fromkeys(self._fallback_order)

        # HTTP session (created in start())
        self._session: aiohttp.ClientSession | None = None

        # MT5 backup (lazy-initialised)
        self._mt5_backup = None

        logger.info(
            "ProductionDataEngine initialised | primary=%s | fallback=%s",
            self.active_provider,
            self._fallback_order,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Open the HTTP session and start the polling + health-monitor loops."""
        timeout = aiohttp.ClientTimeout(total=float(self._cfg.get("timeout_seconds", 4)))
        self._session = aiohttp.ClientSession(timeout=timeout)
        logger.info("ProductionDataEngine started — primary provider: %s", self.active_provider)
        try:
            await asyncio.gather(
                self._continuous_stream(),
                self._health_monitor(),
            )
        finally:
            await self._session.close()

    async def stop(self) -> None:
        """Gracefully stop the engine."""
        self.is_running = False
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("ProductionDataEngine stopped")

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, component: Any) -> None:
        """Register a subscriber that will receive every confirmed price tick."""
        self.subscribers.append(component)
        logger.info("%s subscribed to live data feed", type(component).__name__)

    def unsubscribe(self, component: Any) -> None:
        """Remove a previously registered subscriber."""
        with contextlib.suppress(ValueError):
            self.subscribers.remove(component)

    # ── Internal polling loop ─────────────────────────────────────────────────

    async def _continuous_stream(self) -> None:
        refresh = float(self._cfg.get("refresh_seconds", 1))
        while self.is_running:
            provider = self._pick_provider()
            success = await self._fetch_price(provider)
            if not success:
                self._fail_count[provider] = self._fail_count.get(provider, 0) + 1
                threshold = int(self._cfg.get("circuit_breaker_threshold", 5))
                if self._fail_count[provider] >= threshold:
                    self._circuit_open_at[provider] = datetime.now(tz=UTC)
                    logger.warning(
                        "Circuit breaker OPEN for provider '%s' after %d failures",
                        provider,
                        self._fail_count[provider],
                    )
                next_provider = self._get_next_provider(provider)
                if next_provider != provider:
                    self.active_provider = next_provider
                    logger.warning("Switched to fallback provider: %s", next_provider)
            await asyncio.sleep(refresh)

    def _pick_provider(self) -> str:
        """Return the active provider, skipping any with an open circuit breaker."""
        now = datetime.now(tz=UTC)
        for candidate in self._fallback_order:
            open_at = self._circuit_open_at.get(candidate)
            if open_at is None:
                return candidate
            elapsed = (now - open_at).total_seconds()
            if elapsed >= _CIRCUIT_BREAKER_COOLDOWN:
                # Cool-down expired — reset and retry.
                self._circuit_open_at[candidate] = None
                self._fail_count[candidate] = 0
                logger.info("Circuit breaker CLOSED for provider '%s'", candidate)
                return candidate
        # All providers tripped — fall back to the primary and hope for the best.
        return self._fallback_order[0]

    def _get_next_provider(self, current: str) -> str:
        """Return the next provider in the fallback order after *current*."""
        now = datetime.now(tz=UTC)
        try:
            idx = self._fallback_order.index(current)
        except ValueError:
            idx = -1
        for candidate in self._fallback_order[idx + 1 :] + self._fallback_order[:idx]:
            open_at = self._circuit_open_at.get(candidate)
            if open_at is None or (now - open_at).total_seconds() >= _CIRCUIT_BREAKER_COOLDOWN:
                return candidate
        return current  # No healthy alternative found.

    # ── Price fetching ────────────────────────────────────────────────────────

    async def _fetch_price(self, provider: str) -> bool:
        """Attempt to fetch a price from *provider*. Returns True on success."""
        if provider == "mt5_demo":
            return await self._fetch_from_mt5()

        max_retries = int(self._cfg.get("max_retries", 3))
        for attempt in range(1, max_retries + 1):
            try:
                price = await self._call_rest_provider(provider)
                if price and _PRICE_MIN < price < _PRICE_MAX:
                    self._record_price(price)
                    self._fail_count[provider] = 0
                    await self._broadcast(price)
                    return True
                logger.debug("Provider '%s' returned out-of-range price: %s", provider, price)
            except TimeoutError:
                logger.warning(
                    "Provider '%s' timed out (attempt %d/%d)",
                    provider,
                    attempt,
                    max_retries,
                )
            except aiohttp.ClientError as exc:
                logger.warning(
                    "Provider '%s' HTTP error (attempt %d/%d): %s",
                    provider,
                    attempt,
                    max_retries,
                    exc,
                )
            except Exception as exc:
                logger.error(
                    "Provider '%s' unexpected error (attempt %d/%d): %s",
                    provider,
                    attempt,
                    max_retries,
                    exc,
                )
            if attempt < max_retries:
                await asyncio.sleep(0.5 * attempt)  # Back-off between retries.
        return False

    async def _call_rest_provider(self, provider: str) -> float | None:
        """Call a REST provider and return the raw price float."""
        cfg = self._cfg.get(provider, {})
        url = _resolve_env(cfg.get("url", ""))
        api_key = _resolve_env(cfg.get("api_key", ""))

        if provider == "goldapi":
            headers = {"x-access-token": api_key, "Content-Type": "application/json"}
        elif provider == "metalpriceapi":
            headers = {"apikey": api_key}
        else:
            headers = {}

        async with self._session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if provider == "goldapi":
            return float(data.get("price", 0))
        if provider == "metalpriceapi":
            # Response: {"rates": {"XAU": 0.000xxx}} — XAU is in troy-oz per USD.
            xau_per_usd = data.get("rates", {}).get("XAU", 0)
            if xau_per_usd and float(xau_per_usd) > 0:
                return round(1.0 / float(xau_per_usd), 4)
        return None

    async def _fetch_from_mt5(self) -> bool:
        """Fetch price from the MT5 demo backup connection."""
        if self._mt5_backup is None:
            from .mt5_backup import MT5Backup  # lazy import — MT5 SDK optional

            self._mt5_backup = MT5Backup(self._cfg.get("mt5_demo", {}))
            connected = await self._mt5_backup.connect()
            if not connected:
                return False

        price = await self._mt5_backup.get_price()
        if price and _PRICE_MIN < price < _PRICE_MAX:
            self._record_price(price)
            await self._broadcast(price)
            return True
        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _record_price(self, price: float) -> None:
        self.current_price = price
        self.last_update = datetime.now(tz=UTC)
        self.price_history.append((price, self.last_update))

    async def _broadcast(self, price: float) -> None:
        """Notify all subscribers concurrently."""
        tasks = []
        for sub in self.subscribers:
            if hasattr(sub, "on_new_price"):
                tasks.append(asyncio.create_task(sub.on_new_price(price)))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for sub, result in zip(self.subscribers, results, strict=False):
                if isinstance(result, Exception):
                    logger.error(
                        "Subscriber %s raised during on_new_price: %s",
                        type(sub).__name__,
                        result,
                    )

    async def _health_monitor(self) -> None:
        """Rotate provider when no update has arrived for 30 seconds."""
        while self.is_running:
            await asyncio.sleep(15)
            if self.last_update is not None:
                age = (datetime.now(tz=UTC) - self.last_update).total_seconds()
                if age > 30:
                    logger.warning("Data feed stale (%.0f s) — forcing provider rotation", age)
                    self.active_provider = self._get_next_provider(self.active_provider)

    # ── Config loading ────────────────────────────────────────────────────────

    @staticmethod
    def _load_config(path: str) -> dict:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Data feed config not found: {config_path.resolve()}")
        with config_path.open("r") as fh:
            return yaml.safe_load(fh)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return a snapshot of engine health for monitoring / dashboards."""
        return {
            "active_provider": self.active_provider,
            "current_price": self.current_price,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "history_size": len(self.price_history),
            "fail_counts": dict(self._fail_count),
            "circuit_breakers": {p: (ts.isoformat() if ts else None) for p, ts in self._circuit_open_at.items()},
            "subscriber_count": len(self.subscribers),
            "is_running": self.is_running,
        }
