# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/multi_source_feed.py
================================
MultiSourceTickFeed — yFinance → Alpha Vantage → Twelve Data fallback chain.

Architecture
------------
* One asyncio polling task per symbol runs concurrently.
* Each task walks the fallback_order, skipping sources whose circuit breaker
  is open, and retries up to max_retries before recording a failure.
* Validated ticks are written to Redis via RedisTickWriter and broadcast to
  all registered subscribers with both symbol and price.
* A health-monitor task rotates stale symbols to the next healthy source.

Prometheus metrics (all labelled by symbol and/or source)
----------------------------------------------------------
  msf_last_price            — latest validated price
  msf_fetch_latency_ms      — end-to-end fetch latency
  msf_active_source         — index of the currently active source (0/1/2)
  msf_source_errors_total   — cumulative fetch failures per source
  msf_circuit_breaker_open  — 1 when circuit breaker is open, 0 when closed

Public API
----------
  MultiSourceTickFeed   — main class
  get_multi_source_feed — module-level singleton factory
  get_feed_status       — returns status dict for the singleton (diagnostics)
"""

from __future__ import annotations

import asyncio
import inspect
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

# ── Prometheus metrics ────────────────────────────────────────────────────────

try:
    from prometheus_client import Counter as _Counter
    from prometheus_client import Gauge as _Gauge

    _PROM = True
    _PG = _Gauge("msf_last_price", "MSF last validated price", ["symbol", "source"])
    _LG = _Gauge("msf_fetch_latency_ms", "MSF fetch round-trip latency ms", ["symbol", "source"])
    _SG = _Gauge("msf_active_source", "MSF active source index (0=yfinance 1=av 2=td)", ["symbol"])
    _EG = _Counter("msf_source_errors_total", "MSF cumulative fetch failures", ["symbol", "source"])
    _CBG = _Gauge("msf_circuit_breaker_open", "MSF circuit breaker open=1 closed=0", ["symbol", "source"])
except Exception:
    _PROM = False
    _PG = _LG = _SG = _EG = _CBG = None  # type: ignore

# ── Constants ─────────────────────────────────────────────────────────────────

_CONFIG_PATH = Path("config/multi_source_feed.yaml")
_FALLBACK_ORDER = ["yfinance", "alpha_vantage", "twelve_data"]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_env(v: Any, _depth: int = 0) -> str:
    """Expand ``${VAR:default}`` placeholders in YAML string values.

    The default may itself be a placeholder — the feed config uses
    ``"${ALPHA_VANTAGE_KEY:${ALPHA_VANTAGE_API_KEY:}}"`` to accept either
    variable name. This used to `partition(":")` once and return the default
    verbatim, so with neither variable set it produced the *literal string*
    ``"${ALPHA_VANTAGE_API_KEY:}"``.

    That string is truthy, which had three consequences: the `or os.getenv(...)`
    fallbacks after it were never reached, an unset key looked configured, and
    AlphaVantageSource sent ``apikey=${ALPHA_VANTAGE_API_KEY:}`` upstream on
    every fetch — a request guaranteed to fail, once per symbol per cycle.

    Resolving recursively returns "" when nothing is set, which is what the
    callers already treat as "not configured".
    """
    if not isinstance(v, str):
        return v
    if not (v.startswith("${") and v.endswith("}")):
        return v
    if _depth > 8:  # pathological nesting — do not spin
        logger.warning("_resolve_env: placeholder nested too deeply, giving up: %r", v)
        return ""

    inner = v[2:-1]
    var, sep, default = inner.partition(":")
    resolved = os.environ.get(var.strip())
    if resolved:
        return resolved
    if not sep:
        return ""
    return _resolve_env(default, _depth + 1)


def _load_config(path: Path = _CONFIG_PATH) -> dict:
    if not path.exists():
        logger.warning("multi_source_feed.yaml not found at %s", path)
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _required_param_count(handler: Any) -> int:
    """Return the number of required positional parameters for *handler*."""
    try:
        sig = inspect.signature(handler)
        return sum(
            1
            for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        )
    except (ValueError, TypeError):
        return 1


# ── Per-symbol state ──────────────────────────────────────────────────────────


class _SymbolState:
    __slots__ = (
        "symbol",
        "current_price",
        "last_update",
        "active_source",
        "fail_counts",
        "circuit_open_at",
        "history",
        "price_min",
        "price_max",
        "last_price_for_anomaly",
        "stale_warned",
    )

    def __init__(self, symbol: str, price_min: float, price_max: float, history_size: int) -> None:
        self.symbol = symbol
        self.current_price: float | None = None
        self.last_update: datetime | None = None
        self.active_source: str = _FALLBACK_ORDER[0]
        self.fail_counts: dict[str, int] = dict.fromkeys(_FALLBACK_ORDER, 0)
        self.circuit_open_at: dict[str, float | None] = dict.fromkeys(_FALLBACK_ORDER, None)
        self.history: deque = deque(maxlen=history_size)
        self.price_min = price_min
        self.price_max = price_max
        self.last_price_for_anomaly: float | None = None
        # Suppress repeated stale-rotation warnings: WARNING on the first stale
        # detection, DEBUG while it stays stale (e.g. a market-closed weekend or a
        # source with no coverage). Reset on the next successful update.
        self.stale_warned: bool = False

    def is_circuit_open(self, source: str, cooldown: float) -> bool:
        open_at = self.circuit_open_at.get(source)
        if open_at is None:
            return False
        if time.monotonic() - open_at >= cooldown:
            self.circuit_open_at[source] = None
            self.fail_counts[source] = 0
            if _PROM and _CBG:
                _CBG.labels(symbol=self.symbol, source=source).set(0)
            logger.info("MultiSourceFeed[%s]: circuit CLOSED for '%s'", self.symbol, source)
            return False
        return True

    def record_failure(self, source: str, threshold: int) -> None:
        self.fail_counts[source] = self.fail_counts.get(source, 0) + 1
        if _PROM and _EG:
            _EG.labels(symbol=self.symbol, source=source).inc()
        if self.fail_counts[source] >= threshold:
            self.circuit_open_at[source] = time.monotonic()
            if _PROM and _CBG:
                _CBG.labels(symbol=self.symbol, source=source).set(1)
            logger.warning(
                "MultiSourceFeed[%s]: circuit OPEN for '%s' after %d failures",
                self.symbol,
                source,
                self.fail_counts[source],
            )

    def record_success(self, source: str, price: float) -> None:
        self.fail_counts[source] = 0
        self.circuit_open_at[source] = None
        if _PROM and _CBG:
            _CBG.labels(symbol=self.symbol, source=source).set(0)
        self.current_price = price
        self.last_update = datetime.now(tz=UTC)
        self.history.append((price, self.last_update))
        self.last_price_for_anomaly = price
        self.stale_warned = False  # fresh data — re-arm the stale warning

    def pick_source(self, fallback_order: list[str], cooldown: float) -> str:
        for src in fallback_order:
            if not self.is_circuit_open(src, cooldown):
                return src
        return fallback_order[0]

    def is_price_valid(self, price: float) -> bool:
        return self.price_min < price < self.price_max

    def is_anomalous(self, price: float, jump_pct: float) -> bool:
        if self.last_price_for_anomaly is None:
            return False
        return abs((price - self.last_price_for_anomaly) / self.last_price_for_anomaly) * 100.0 > jump_pct

    def status(self) -> dict:
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "active_source": self.active_source,
            "fail_counts": dict(self.fail_counts),
            "circuit_open": {s: (v is not None) for s, v in self.circuit_open_at.items()},
            "history_size": len(self.history),
        }


# ── Main feed class ───────────────────────────────────────────────────────────


class MultiSourceTickFeed:
    """
    Multi-symbol, multi-source tick ingestion engine.

    Fallback chain: yFinance → Alpha Vantage → Twelve Data.

    Each source can be disabled via the ``enabled`` flag in
    config/multi_source_feed.yaml.  Sources with an empty provider-specific
    symbol string (e.g. ``alpha_vantage_symbol: ""``) are skipped per-symbol
    without tripping the circuit breaker.

    Subscribers receive ``on_new_price(symbol, price)`` calls on every
    validated tick.  Legacy subscribers that accept only ``(price)`` are also
    supported — the feed detects the signature at subscribe time.
    """

    def __init__(
        self,
        config_path: Path | str = _CONFIG_PATH,
        symbols: list[str] | None = None,
    ) -> None:
        raw = _load_config(Path(config_path))
        self._cfg = raw.get("multi_source_feed", {})

        self._refresh_s = float(self._cfg.get("refresh_seconds", 2))
        self._timeout_s = float(self._cfg.get("timeout_seconds", 5))
        self._max_retries = int(self._cfg.get("max_retries", 3))
        self._cb_threshold = int(self._cfg.get("circuit_breaker_threshold", 5))
        self._cb_cooldown = float(self._cfg.get("circuit_breaker_cooldown", 60))
        self._history_size = int(self._cfg.get("history_size", 5000))
        self._max_stale_s = float(self._cfg.get("max_stale_seconds", 30))
        self._anomaly_pct = float(self._cfg.get("anomaly_jump_pct", 5.0))
        self._fallback_order: list[str] = self._cfg.get("fallback_order", _FALLBACK_ORDER)

        redis_cfg = self._cfg.get("redis", {})
        self._tick_key_ttl = int(redis_cfg.get("tick_key_ttl", 30))

        # Determine which sources are enabled in config.
        self._source_enabled: dict[str, bool] = {
            "yfinance": bool(self._cfg.get("yfinance", {}).get("enabled", True)),
            "alpha_vantage": bool(self._cfg.get("alpha_vantage", {}).get("enabled", True)),
            "twelve_data": bool(self._cfg.get("twelve_data", {}).get("enabled", True)),
        }
        # Effective fallback order — only enabled sources.
        self._active_order: list[str] = [s for s in self._fallback_order if self._source_enabled.get(s, True)] or list(
            self._fallback_order
        )

        symbols_cfg = self._cfg.get("symbols", {})
        active = symbols or list(symbols_cfg.keys()) or ["XAUUSD"]
        self._symbol_cfgs: dict[str, dict] = {s: symbols_cfg.get(s, {}) for s in active}
        self._states: dict[str, _SymbolState] = {
            sym: _SymbolState(
                sym,
                float(scfg.get("price_min", 0.0)),
                float(scfg.get("price_max", 1_000_000.0)),
                self._history_size,
            )
            for sym, scfg in self._symbol_cfgs.items()
        }

        self._sources: dict[str, Any] = {}
        self._session: aiohttp.ClientSession | None = None
        self._tick_writer: Any | None = None
        self._redis_errors: int = 0
        # Subscribers stored as (component, param_count) tuples.
        self._subscribers: list[tuple[Any, int]] = []
        self._running: bool = False
        self._tasks: list[asyncio.Task] = []

        logger.info(
            "MultiSourceTickFeed init | symbols=%s | chain=%s | enabled=%s",
            list(self._states.keys()),
            self._active_order,
            self._source_enabled,
        )

    # ── Source construction ───────────────────────────────────────────────────

    def _build_sources(self) -> dict[str, Any]:
        from .sources.alpha_vantage import AlphaVantageSource
        from .sources.twelve_data import TwelveDataSource
        from .sources.yfinance_source import YFinanceSource

        yf_cfg = self._cfg.get("yfinance", {})
        av_cfg = self._cfg.get("alpha_vantage", {})
        td_cfg = self._cfg.get("twelve_data", {})

        av_key = (
            _resolve_env(av_cfg.get("api_key", ""))
            or os.getenv("ALPHA_VANTAGE_KEY", "")
            or os.getenv("ALPHA_VANTAGE_API_KEY", "")
        )
        td_key = _resolve_env(td_cfg.get("api_key", "")) or os.getenv("TWELVE_API_KEY", "")

        sources: dict[str, Any] = {}
        if self._source_enabled.get("yfinance", True):
            sources["yfinance"] = YFinanceSource(
                period=yf_cfg.get("period", "1d"),
                interval=yf_cfg.get("interval", "1m"),
            )
        if self._source_enabled.get("alpha_vantage", True):
            sources["alpha_vantage"] = AlphaVantageSource(
                api_key=av_key,
                timeout=self._timeout_s,
                session=self._session,
            )
        if self._source_enabled.get("twelve_data", True):
            sources["twelve_data"] = TwelveDataSource(
                api_key=td_key,
                timeout=self._timeout_s,
                session=self._session,
            )

        self._warn_unusable_sources(av_key=av_key, td_key=td_key)
        return sources

    def _warn_unusable_sources(self, *, av_key: str, td_key: str) -> None:
        """Log, once at startup, any source that is enabled but cannot be used.

        A keyed source with no key skips every fetch and returns None, at DEBUG
        level — so at normal log levels an unset key is indistinguishable from
        an upstream outage, and both look like "no data" in the UI.

        This matters most for the metals. XAUUSD, XAGUSD and XPTUSD have no
        yfinance ticker on purpose (Yahoo delisted spot, and quoting GLD against
        spot gold would be far worse than quoting nothing), so they can ONLY be
        priced by alpha_vantage or twelve_data. Without a key there is no spot
        gold price on a platform whose primary instrument is gold.
        """
        keyed = {"alpha_vantage": av_key, "twelve_data": td_key}
        unusable = [name for name, key in keyed.items() if self._source_enabled.get(name, True) and not key]
        if not unusable:
            return

        # Symbols that depend entirely on the keyed sources.
        keyless_only = sorted(sym for sym, cfg in self._symbol_cfgs.items() if not (cfg or {}).get("yfinance_ticker"))
        logger.warning(
            "Data feed: %s enabled but no API key configured — every fetch from "
            "%s will be skipped. Set %s. Affected symbols (no yfinance fallback): %s",
            ", ".join(unusable),
            "them" if len(unusable) > 1 else "it",
            " / ".join({"alpha_vantage": "ALPHA_VANTAGE_KEY", "twelve_data": "TWELVE_API_KEY"}[n] for n in unusable),
            ", ".join(keyless_only) or "none",
        )

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, component: Any) -> None:
        """
        Register a subscriber.

        The subscriber must implement ``on_new_price`` as a coroutine.
        Two-argument form ``on_new_price(symbol, price)`` is preferred.
        Legacy one-argument form ``on_new_price(price)`` is also accepted.
        """
        handler = getattr(component, "on_new_price", None)
        if handler is None:
            logger.warning(
                "MultiSourceTickFeed.subscribe: %s has no on_new_price — ignored",
                type(component).__name__,
            )
            return
        n = _required_param_count(handler)
        self._subscribers.append((component, n))
        logger.info(
            "MultiSourceTickFeed: %s subscribed (on_new_price params=%d)",
            type(component).__name__,
            n,
        )

    def unsubscribe(self, component: Any) -> None:
        self._subscribers = [(c, n) for c, n in self._subscribers if c is not component]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout_s))
        self._sources = self._build_sources()

        # Share the session with HTTP-based sources.
        for name in ("alpha_vantage", "twelve_data"):
            src = self._sources.get(name)
            if src and hasattr(src, "_session"):
                src._session = self._session
                src._owns_session = False

        # Connect Redis tick writer (non-fatal if Redis is unavailable).
        # Bound before the try so no path can reach the banner with it unset.
        tick_writer_started = False
        try:
            from .redis_tick_writer import RedisTickWriter

            self._tick_writer = RedisTickWriter(tick_key_ttl=self._tick_key_ttl)
            # start(), NOT connect(). connect() only acquires the Redis client;
            # start() also launches the background worker that drains the write
            # queue into Redis.
            #
            # With only connect(), RedisTickWriter.write() enqueued every tick
            # and returned True — self._redis was set, so it reported success —
            # while no worker existed to consume the queue. The queue filled to
            # its maxsize and from then on each new tick evicted the oldest.
            # Every tick the feed fetched was silently discarded, nothing was
            # ever published to hopefx:tick, and the startup banner still logged
            # "redis=connected" because self._tick_writer was truthy.
            #
            # Downstream that is: frozen prices in the UI (ws_live had nothing to
            # broadcast), charts stuck on "Loading market data…", and
            # "No OHLCV data available" on the indicator builder — one silent
            # failure presenting as a dozen broken pages.
            # The banner below reports this flag, not the truthiness of
            # self._tick_writer. The object exists whether or not Redis answered,
            # so the old check logged "redis=connected" on the very same startup
            # that warned ticks would NOT be persisted — two adjacent lines
            # contradicting each other, with the reassuring one last.
            tick_writer_started = await self._tick_writer.start()
            if not tick_writer_started:
                logger.warning(
                    "MultiSourceTickFeed: RedisTickWriter did not start — ticks will NOT be "
                    "persisted or broadcast. Check Redis connectivity (REDIS_URL/REDIS_PASSWORD)."
                )
        except Exception as exc:
            logger.warning("MultiSourceTickFeed: RedisTickWriter init failed (non-fatal): %s", exc)
            self._tick_writer = None
            tick_writer_started = False

        # Launch one polling task per symbol plus the health monitor.
        for sym in self._states:
            self._tasks.append(asyncio.create_task(self._poll_symbol(sym), name=f"msf_poll_{sym}"))
        self._tasks.append(asyncio.create_task(self._health_monitor(), name="msf_health"))

        logger.info(
            "MultiSourceTickFeed started | %d symbol(s) | refresh=%.1fs | redis=%s",
            len(self._states),
            self._refresh_s,
            "connected" if tick_writer_started else "UNAVAILABLE — ticks not persisted",
        )

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._session and not self._session.closed:
            await self._session.close()
        if self._tick_writer:
            await self._tick_writer.close()
        logger.info("MultiSourceTickFeed stopped")

    # ── Public accessors ──────────────────────────────────────────────────────

    def get_price(self, symbol: str) -> float | None:
        st = self._states.get(symbol)
        return st.current_price if st else None

    def get_last_update(self, symbol: str) -> datetime | None:
        st = self._states.get(symbol)
        return st.last_update if st else None

    def status(self) -> dict:
        symbols = {sym: st.status() for sym, st in self._states.items()}
        redis = self._tick_writer.status() if self._tick_writer else {"redis_connected": False}
        healthy, message = self._health_summary(symbols, redis)
        return {
            "running": self._running,
            # `healthy` and `message` are part of this contract, not decoration.
            # security/diagnostics.py has always read them:
            #     return status.get("healthy", False), status.get("message", "")
            # and this dict has never contained either key, so the check could
            # only ever return False. The deployed superadmin page reported
            # "data_feeds_module: Data feed module unhealthy" continuously,
            # whether the feed was streaming perfectly or not running at all —
            # a check with exactly one possible answer tells you nothing, and
            # having it on screen in red trains you to ignore the panel.
            "healthy": healthy,
            "message": message,
            "symbols": symbols,
            "sources": {n: s.status() if hasattr(s, "status") else {} for n, s in self._sources.items()},
            "source_enabled": self._source_enabled,
            "active_fallback_order": self._active_order,
            "redis": redis,
            "subscriber_count": len(self._subscribers),
            "redis_errors": self._redis_errors,
            "max_stale_seconds": self._max_stale_s,
        }

    def _health_summary(self, symbols: dict, redis: dict) -> tuple[bool, str]:
        """Reduce the status snapshot to one boolean and one sentence.

        Healthy means the feed is running *and* at least one symbol has ticked
        recently. "Running" alone is not health: the poll loop stays alive with
        every source circuit-open, which is precisely the state worth alerting
        on.
        """
        if not self._running:
            return False, "Data feed is not running"
        if not symbols:
            return False, "Data feed is running but no symbols are configured"

        # Twice max_stale_seconds: max_stale is the per-tick validity window,
        # and a symbol one refresh past it is not yet a fault.
        cutoff = max(self._max_stale_s * 2, 10.0)
        now = datetime.now(UTC)
        fresh: list[str] = []
        stale: list[str] = []
        for sym, st in symbols.items():
            last = st.get("last_update")
            if not last:
                stale.append(sym)
                continue
            try:
                age = (now - datetime.fromisoformat(last)).total_seconds()
            except (TypeError, ValueError):
                stale.append(sym)
                continue
            (fresh if age <= cutoff else stale).append(sym)

        redis_note = "" if redis.get("redis_connected") else "; Redis not connected — ticks are not persisted"
        if not fresh:
            return False, (
                f"Data feed is running but all {len(stale)} symbol(s) are stale (>{cutoff:.0f}s){redis_note}"
            )
        return True, (f"Data feed healthy — {len(fresh)}/{len(symbols)} symbol(s) fresh{redis_note}")

    # ── Internal polling ──────────────────────────────────────────────────────

    def _serviceable_order(self, symbol: str, sym_cfg: dict) -> list[str]:
        """The subset of the fallback chain that *could* price *symbol*.

        A source with no ticker mapping for this symbol — or, for the keyed
        sources, no API key — cannot answer, and that is knowable from config
        without a single request. Asking it anyway and then calling
        ``record_failure`` on the None it returns conflates "not configured"
        with "upstream is down".

        That conflation is what filled the production log: XAUUSD, XAGUSD,
        XPTUSD and USOIL carry a blank ``yfinance_ticker`` on purpose, so every
        2-second poll spent three retries on yfinance, tripped the breaker at 5
        failures, waited out the 60 s cooldown, closed the breaker, and tripped
        it again — for as long as the process ran. The visible cost was noise;
        the real cost was that ``circuit OPEN for 'yfinance'`` and the
        ``msf_source_errors`` counter, the two signals that would tell an
        operator Yahoo had *actually* gone down, were saturated by design.

        Sources that do not implement ``can_serve`` are assumed capable, so a
        custom or stubbed adapter keeps its current behaviour.
        """
        out: list[str] = []
        for name in self._active_order:
            adapter = self._sources.get(name)
            if adapter is None:
                continue
            check = getattr(adapter, "can_serve", None)
            if check is None or check(symbol, sym_cfg):
                out.append(name)
        return out

    async def _poll_symbol(self, symbol: str) -> None:
        state = self._states[symbol]
        sym_cfg = self._symbol_cfgs.get(symbol, {})

        # Serviceability is fixed once start() has built the sources: it depends
        # only on the symbol config and the API keys, both read at build time.
        # So decide once here rather than re-deciding every poll.
        order = self._serviceable_order(symbol, sym_cfg)
        if not order:
            logger.warning(
                "MultiSourceFeed[%s]: no configured source can price this symbol "
                "(checked %s) — not polling. It will have no live price until a "
                "source is configured for it: set ALPHA_VANTAGE_KEY or "
                "TWELVE_API_KEY, or give it a ticker in config/multi_source_feed.yaml.",
                symbol,
                ", ".join(self._active_order) or "none",
            )
            return
        if len(order) < len(self._active_order):
            logger.info(
                "MultiSourceFeed[%s]: chain=%s (skipping %s — not configured for this symbol)",
                symbol,
                order,
                ", ".join(s for s in self._active_order if s not in order),
            )
        # _SymbolState defaults active_source to the head of the global chain,
        # which status() would report as "yfinance" for a symbol yfinance can
        # never serve. Start it on a source that could actually answer.
        if state.active_source not in order:
            state.active_source = order[0]

        while self._running:
            t0 = time.monotonic()
            source = state.pick_source(order, self._cb_cooldown)
            price = await self._fetch_with_retry(symbol, source, sym_cfg)

            if price is not None:
                if state.is_anomalous(price, self._anomaly_pct):
                    logger.warning(
                        "MultiSourceFeed[%s]: anomaly from '%s': %.4f→%.4f — discarded",
                        symbol,
                        source,
                        state.last_price_for_anomaly,
                        price,
                    )
                    state.record_failure(source, self._cb_threshold)
                elif not state.is_price_valid(price):
                    logger.warning(
                        "MultiSourceFeed[%s]: out-of-range from '%s': %.4f — discarded",
                        symbol,
                        source,
                        price,
                    )
                    state.record_failure(source, self._cb_threshold)
                else:
                    latency_ms = (time.monotonic() - t0) * 1000.0
                    state.record_success(source, price)
                    state.active_source = source

                    if _PROM:
                        if _PG:
                            _PG.labels(symbol=symbol, source=source).set(price)
                        if _LG:
                            _LG.labels(symbol=symbol, source=source).set(latency_ms)
                        if _SG:
                            _SG.labels(symbol=symbol).set(
                                self._active_order.index(source) if source in self._active_order else -1
                            )

                    logger.debug(
                        "MultiSourceFeed[%s]: %.4f via '%s' (%.0f ms)",
                        symbol,
                        price,
                        source,
                        latency_ms,
                    )
                    await self._publish(symbol, price, source)
                    await self._broadcast(symbol, price)
            else:
                state.record_failure(source, self._cb_threshold)
                nxt = state.pick_source(order, self._cb_cooldown)
                if nxt != source:
                    state.active_source = nxt
                    logger.warning(
                        "MultiSourceFeed[%s]: '%s' failed — switching to '%s'",
                        symbol,
                        source,
                        nxt,
                    )

            await asyncio.sleep(self._refresh_s)

    async def _fetch_with_retry(self, symbol: str, source: str, sym_cfg: dict) -> float | None:
        adapter = self._sources.get(source)
        if adapter is None:
            return None

        for attempt in range(1, self._max_retries + 1):
            try:
                price = await adapter.fetch(symbol, sym_cfg)
                if price is not None:
                    return price
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "MultiSourceFeed[%s/%s]: attempt %d/%d: %s",
                    symbol,
                    source,
                    attempt,
                    self._max_retries,
                    exc,
                )
            if attempt < self._max_retries:
                await asyncio.sleep(0.5 * attempt)

        return None

    async def _publish(self, symbol: str, price: float, source: str) -> None:
        """Write tick to Redis (tick:SYMBOL keys + pub/sub channels)."""
        if self._tick_writer is None:
            return
        ok = await self._tick_writer.write(symbol=symbol, price=price, source=source)
        if not ok:
            self._redis_errors += 1

    async def _broadcast(self, symbol: str, price: float) -> None:
        """
        Notify all subscribers of a validated tick.

        Calls ``on_new_price(symbol, price)`` for two-param subscribers or
        ``on_new_price(price)`` for legacy one-param subscribers.
        """
        if not self._subscribers:
            return

        tasks: list[asyncio.Task] = []
        for component, n_params in self._subscribers:
            handler = getattr(component, "on_new_price", None)
            if handler is None:
                continue
            try:
                coro = handler(symbol, price) if n_params >= 2 else handler(price)
                if asyncio.iscoroutine(coro):
                    tasks.append(asyncio.create_task(coro))
            except Exception as exc:
                logger.error(
                    "MultiSourceFeed[%s]: subscriber %s call error: %s",
                    symbol,
                    type(component).__name__,
                    exc,
                )

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        sub_iter = (c for c, _ in self._subscribers if hasattr(c, "on_new_price"))
        for component, result in zip(sub_iter, results, strict=False):
            if isinstance(result, Exception):
                logger.error(
                    "MultiSourceFeed[%s]: subscriber %s raised: %s",
                    symbol,
                    type(component).__name__,
                    result,
                )

    async def _health_monitor(self) -> None:
        """Rotate stale symbols to the next healthy source every 15 s."""
        while self._running:
            await asyncio.sleep(15)
            now = datetime.now(tz=UTC)
            for sym, state in self._states.items():
                if state.last_update is None:
                    continue
                age_s = (now - state.last_update).total_seconds()
                if age_s > self._max_stale_s:
                    # First stale detection logs at WARNING; while it stays stale
                    # (market closed / no source coverage) drop to DEBUG to avoid
                    # flooding the logs every 15 s.
                    if not state.stale_warned:
                        logger.warning("MultiSourceFeed[%s]: stale (%.0f s) — rotating source", sym, age_s)
                        state.stale_warned = True
                    else:
                        logger.debug(
                            "MultiSourceFeed[%s]: still stale (%.0f s) — rotating source (suppressed)", sym, age_s
                        )
                    state.record_failure(state.active_source, self._cb_threshold)
                    # Rotate only among sources that could actually price this
                    # symbol — rotating onto one with no ticker mapping just
                    # guarantees the next poll fails too.
                    order = self._serviceable_order(sym, self._symbol_cfgs.get(sym, {}))
                    if order:
                        state.active_source = state.pick_source(order, self._cb_cooldown)


# ── Module-level singleton ────────────────────────────────────────────────────

_feed_instance: MultiSourceTickFeed | None = None


def get_multi_source_feed(
    config_path: Path | str = _CONFIG_PATH,
    symbols: list[str] | None = None,
) -> MultiSourceTickFeed:
    """Return the module-level MultiSourceTickFeed singleton."""
    global _feed_instance
    if _feed_instance is None:
        _feed_instance = MultiSourceTickFeed(config_path=config_path, symbols=symbols)
    return _feed_instance


def get_feed_status() -> dict:
    """
    Return a status snapshot of the module-level feed singleton.

    Returns a minimal dict with ``running=False`` when the singleton has not
    been initialised yet.  Used by security/diagnostics.py and health checks.
    """
    if _feed_instance is None:
        return {
            "running": False,
            "healthy": False,
            "message": "Data feed singleton has not been initialised",
            "symbols": {},
            "redis": {"redis_connected": False},
        }
    return _feed_instance.status()
