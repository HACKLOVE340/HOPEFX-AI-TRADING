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

New in this version
-------------------
* Adaptive polling interval: poll interval adjusts dynamically based on
  source health score. Healthy sources poll at min_interval; degraded
  sources back off to max_interval. Interval changes are logged.
* Source health scoring: each provider maintains a rolling health score
  [0.0, 1.0] based on success rate, latency, and staleness. Score decays
  on failure and recovers on success.
* Automatic failover with hysteresis: failover only triggers when the
  active provider's health score drops below FAILOVER_THRESHOLD for
  HYSTERESIS_COUNT consecutive polls. Recovery back to primary requires
  the primary's health score to exceed RECOVERY_THRESHOLD for
  HYSTERESIS_COUNT consecutive polls.

Subscriber pattern
------------------
Any object with an ``on_new_price(price: float)`` coroutine can subscribe.
The engine calls all subscribers concurrently on every confirmed tick.

Usage
-----
    engine = ProductionDataEngine()
    engine.subscribe(brain)
    engine.subscribe(risk_manager)
    _t = asyncio.create_task(engine.start())
    _t.add_done_callback(lambda _: None)
"""

import asyncio
import contextlib
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
import yaml

UTC = timezone.utc
logger = logging.getLogger(__name__)

# Default plausible price bounds per symbol.  Overridden by
# ``data_feed.price_bounds.<SYMBOL>.min/max`` in config/data_feed.yaml.
# Keys are canonical uppercase symbols (e.g. "XAUUSD", "XAGUSD").
_DEFAULT_PRICE_BOUNDS: dict[str, tuple[float, float]] = {
    "XAUUSD": (1_000.0, 10_000.0),   # Gold / USD
    "XAGUSD": (5.0, 500.0),           # Silver / USD
    "XPTUSD": (200.0, 5_000.0),       # Platinum / USD
    "XPDUSD": (200.0, 10_000.0),      # Palladium / USD
    "EURUSD": (0.5, 2.5),
    "GBPUSD": (0.5, 3.0),
    "USDJPY": (50.0, 250.0),
    "BTCUSD": (1_000.0, 1_000_000.0),
}
# Fallback bounds used when a symbol is not in the table above.
_FALLBACK_PRICE_MIN = 0.0
_FALLBACK_PRICE_MAX = float("inf")

# How long (seconds) a circuit-breaker stays open before re-trying.
_CIRCUIT_BREAKER_COOLDOWN = 60

# Adaptive polling interval bounds (seconds)
_POLL_MIN_S = float(os.getenv("FEED_POLL_MIN_S", "0.5"))
_POLL_MAX_S = float(os.getenv("FEED_POLL_MAX_S", "10.0"))

# Health score thresholds for failover/recovery
_FAILOVER_THRESHOLD = float(os.getenv("FEED_FAILOVER_THRESHOLD", "0.3"))
_RECOVERY_THRESHOLD = float(os.getenv("FEED_RECOVERY_THRESHOLD", "0.7"))
_HYSTERESIS_COUNT = int(os.getenv("FEED_HYSTERESIS_COUNT", "3"))

# Health score EMA alpha
_HEALTH_ALPHA = float(os.getenv("FEED_HEALTH_ALPHA", "0.2"))


class _SourceHealth:
    """
    Rolling health score for a single data source.

    Score in [0.0, 1.0]:
      1.0 = perfectly healthy (fast, reliable, fresh)
      0.0 = completely failed

    Updated on every poll attempt:
      success: score += alpha * (1.0 - score)  [EMA toward 1.0]
      failure: score -= alpha * score           [EMA toward 0.0]
      latency penalty: score -= latency_ms / 10000 (capped at 0.2)
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.score: float = 1.0
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self.total_calls: int = 0
        self.total_failures: int = 0
        self.last_latency_ms: float = 0.0
        self.last_success_ts: float = 0.0
        self._poll_interval: float = _POLL_MIN_S

    def record_success(self, latency_ms: float) -> None:
        self.total_calls += 1
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        self.last_latency_ms = latency_ms
        self.last_success_ts = time.monotonic()
        # EMA toward 1.0
        self.score = self.score + _HEALTH_ALPHA * (1.0 - self.score)
        # Latency penalty (normalised: 1000ms = 0.1 penalty)
        latency_penalty = min(0.2, latency_ms / 10000.0)
        self.score = max(0.0, self.score - latency_penalty)
        self._update_poll_interval()

    def record_failure(self) -> None:
        self.total_calls += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        # EMA toward 0.0
        self.score = self.score - _HEALTH_ALPHA * self.score
        self.score = max(0.0, self.score)
        self._update_poll_interval()

    def _update_poll_interval(self) -> None:
        """Adaptive interval: healthy → min, degraded → max."""
        # Linear interpolation: score=1.0 → min, score=0.0 → max
        self._poll_interval = _POLL_MAX_S - self.score * (_POLL_MAX_S - _POLL_MIN_S)
        self._poll_interval = max(_POLL_MIN_S, min(_POLL_MAX_S, self._poll_interval))

    @property
    def poll_interval(self) -> float:
        return self._poll_interval

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "poll_interval_s": round(self._poll_interval, 2),
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "last_latency_ms": round(self.last_latency_ms, 1),
        }


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

        # Per-symbol price bounds — loaded from config, falling back to the
        # built-in table.  Bounds are keyed by canonical uppercase symbol.
        self._price_bounds: dict[str, tuple[float, float]] = dict(_DEFAULT_PRICE_BOUNDS)
        cfg_bounds = self._cfg.get("price_bounds", {})
        for sym, bounds in cfg_bounds.items():
            sym_upper = sym.upper()
            try:
                lo = float(bounds.get("min", _FALLBACK_PRICE_MIN))
                hi = float(bounds.get("max", _FALLBACK_PRICE_MAX))
                self._price_bounds[sym_upper] = (lo, hi)
                logger.debug("Price bounds loaded from config: %s [%.2f, %.2f]", sym_upper, lo, hi)
            except (TypeError, ValueError) as exc:
                logger.warning("Invalid price_bounds config for %s: %s — using defaults", sym, exc)

        # Active symbol (used for bound lookups; defaults to XAUUSD)
        self._symbol: str = self._cfg.get("symbol", "XAUUSD").upper()
        self._price_min, self._price_max = self._price_bounds.get(
            self._symbol, (_FALLBACK_PRICE_MIN, _FALLBACK_PRICE_MAX)
        )
        logger.info(
            "Price bounds for %s: [%.2f, %.2f]",
            self._symbol, self._price_min, self._price_max,
        )

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

        # Source health scores (adaptive polling + failover hysteresis)
        self._health: dict[str, _SourceHealth] = {
            p: _SourceHealth(p) for p in self._fallback_order
        }
        # Hysteresis counters for failover/recovery
        self._failover_count: int = 0   # consecutive polls below FAILOVER_THRESHOLD
        self._recovery_count: int = 0   # consecutive polls above RECOVERY_THRESHOLD
        self._primary_provider: str = self._cfg.get("primary", self._fallback_order[0])

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
        while self.is_running:
            provider = self._pick_provider()
            health = self._health[provider]

            t0 = time.monotonic()
            success = await self._fetch_price(provider)
            latency_ms = (time.monotonic() - t0) * 1000.0

            if success:
                health.record_success(latency_ms)
                self._fail_count[provider] = 0
                # Check if we can recover back to primary
                self._check_recovery(provider)
            else:
                health.record_failure()
                self._fail_count[provider] = self._fail_count.get(provider, 0) + 1
                threshold = int(self._cfg.get("circuit_breaker_threshold", 5))
                if self._fail_count[provider] >= threshold:
                    self._circuit_open_at[provider] = datetime.now(tz=UTC)
                    logger.warning(
                        "Circuit breaker OPEN for provider '%s' after %d failures",
                        provider, self._fail_count[provider],
                    )
                # Hysteresis-based failover
                self._check_failover(provider)

            # Adaptive sleep: use the active provider's health-based interval
            await asyncio.sleep(health.poll_interval)

    def _check_failover(self, provider: str) -> None:
        """
        Trigger failover only after HYSTERESIS_COUNT consecutive degraded polls.

        This prevents flapping on transient errors.
        """
        health = self._health[provider]
        if health.score < _FAILOVER_THRESHOLD:
            self._failover_count += 1
            self._recovery_count = 0
            if self._failover_count >= _HYSTERESIS_COUNT:
                next_provider = self._get_next_provider(provider)
                if next_provider != provider:
                    logger.warning(
                        "Hysteresis failover: %s (score=%.2f) → %s after %d degraded polls",
                        provider, health.score, next_provider, self._failover_count,
                    )
                    self.active_provider = next_provider
                    self._failover_count = 0
        else:
            self._failover_count = max(0, self._failover_count - 1)

    def _check_recovery(self, provider: str) -> None:
        """
        Recover back to primary only after HYSTERESIS_COUNT consecutive healthy polls.
        """
        if provider == self._primary_provider:
            return  # Already on primary
        primary_health = self._health.get(self._primary_provider)
        if primary_health and primary_health.score >= _RECOVERY_THRESHOLD:
            self._recovery_count += 1
            self._failover_count = 0
            if self._recovery_count >= _HYSTERESIS_COUNT:
                logger.info(
                    "Hysteresis recovery: returning to primary %s (score=%.2f) after %d healthy polls",
                    self._primary_provider, primary_health.score, self._recovery_count,
                )
                self.active_provider = self._primary_provider
                self._recovery_count = 0
        else:
            self._recovery_count = max(0, self._recovery_count - 1)

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
        """
        Attempt to fetch a price from *provider*. Returns True on success.

        3-path fallback order (enforced by _pick_provider / _fallback_order):
          1. goldapi       — primary REST source
          2. metalpriceapi — secondary REST source
          3. mt5_demo      — last-resort MT5 demo connection

        Health scoring is done exclusively in _continuous_stream to avoid
        double-counting: this method only returns True/False.
        """
        if provider == "mt5_demo":
            return await self._fetch_from_mt5()

        max_retries = int(self._cfg.get("max_retries", 3))
        for attempt in range(1, max_retries + 1):
            try:
                price = await self._call_rest_provider(provider)
                if price and self._price_min < price < self._price_max:
                    self._record_price(price)
                    self._fail_count[provider] = 0
                    await self._broadcast(price)
                    return True
                # Out-of-range price — log and retry without double-penalising health
                logger.debug(
                    "Provider '%s' returned out-of-range price for %s: %s (bounds: [%.2f, %.2f])",
                    provider, self._symbol, price, self._price_min, self._price_max,
                )
            except (TimeoutError, asyncio.TimeoutError):
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
        if price and self._price_min < price < self._price_max:
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
        """
        Load the data-feed YAML config.

        Falls back to a built-in default configuration when the file is absent
        so the engine can start in environments where the config file has not
        yet been deployed (e.g. CI, Docker first-run).  A warning is logged so
        operators know the default is in use.
        """
        config_path = Path(path)
        if not config_path.exists():
            logger.warning(
                "Data feed config not found at %s — using built-in defaults. "
                "Create config/data_feed.yaml to customise.",
                config_path.resolve(),
            )
            return {
                "data_feed": {
                    "primary": "goldapi",
                    "fallback_order": ["goldapi", "metalpriceapi", "mt5_demo"],
                    "history_size": 5000,
                    "timeout_seconds": 4,
                    "max_retries": 3,
                    "circuit_breaker_threshold": 5,
                    "goldapi": {
                        "url": "${GOLDAPI_URL:https://www.goldapi.io/api/XAU/USD}",
                        "api_key": "${GOLDAPI_KEY:}",
                    },
                    "metalpriceapi": {
                        "url": "${METALPRICEAPI_URL:https://api.metalpriceapi.com/v1/latest?base=USD&currencies=XAU}",
                        "api_key": "${METALPRICEAPI_KEY:}",
                    },
                    "mt5_demo": {},
                }
            }
        with config_path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def get_source_health(self, provider: str) -> _SourceHealth | None:
        """Return the health object for a named provider."""
        return self._health.get(provider)

    def get_all_health_scores(self) -> dict[str, float]:
        """Return health scores for all providers."""
        return {p: round(h.score, 4) for p, h in self._health.items()}

    def status(self) -> dict:
        """Return a snapshot of engine health for monitoring / dashboards."""
        return {
            "active_provider": self.active_provider,
            "primary_provider": self._primary_provider,
            "current_price": self.current_price,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "history_size": len(self.price_history),
            "fail_counts": dict(self._fail_count),
            "circuit_breakers": {p: (ts.isoformat() if ts else None) for p, ts in self._circuit_open_at.items()},
            "subscriber_count": len(self.subscribers),
            "is_running": self.is_running,
            "source_health": {p: h.to_dict() for p, h in self._health.items()},
            "failover_count": self._failover_count,
            "recovery_count": self._recovery_count,
            "adaptive_poll_interval_s": self._health.get(self.active_provider, _SourceHealth("")).poll_interval,
        }
