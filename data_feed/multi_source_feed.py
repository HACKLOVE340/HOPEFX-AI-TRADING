# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/multi_source_feed.py
MultiSourceTickFeed — yFinance -> Alpha Vantage -> Twelve Data fallback chain.
"""
from __future__ import annotations
import asyncio, contextlib, logging, os, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import aiohttp, yaml

UTC = timezone.utc
logger = logging.getLogger(__name__)

try:
    from prometheus_client import Gauge as _Gauge
    _PROM = True
    _PG = _Gauge("msf_last_price","MSF last price",["symbol","source"])
    _LG = _Gauge("msf_fetch_latency_ms","MSF fetch latency ms",["symbol","source"])
    _SG = _Gauge("msf_active_source","MSF active source index",["symbol"])
except Exception:
    _PROM = False; _PG = _LG = _SG = None  # type: ignore

_CONFIG_PATH = Path("config/multi_source_feed.yaml")
_FALLBACK_ORDER = ["yfinance","alpha_vantage","twelve_data"]

def _resolve_env(v: Any) -> str:
    if not isinstance(v, str): return v
    if v.startswith("${") and v.endswith("}"):
        inner = v[2:-1]; var, _, default = inner.partition(":")
        return os.environ.get(var.strip(), default)
    return v

def _load_config(path: Path = _CONFIG_PATH) -> dict:
    if not path.exists():
        logger.warning("multi_source_feed.yaml not found at %s", path); return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class _SymbolState:
    __slots__ = ("symbol","current_price","last_update","active_source",
                 "fail_counts","circuit_open_at","history","price_min","price_max","last_price_for_anomaly")
    def __init__(self, symbol, price_min, price_max, history_size):
        self.symbol = symbol; self.current_price = None; self.last_update = None
        self.active_source = _FALLBACK_ORDER[0]
        self.fail_counts = dict.fromkeys(_FALLBACK_ORDER, 0)
        self.circuit_open_at = dict.fromkeys(_FALLBACK_ORDER, None)
        self.history = deque(maxlen=history_size)
        self.price_min = price_min; self.price_max = price_max
        self.last_price_for_anomaly = None

    def is_circuit_open(self, source, cooldown):
        open_at = self.circuit_open_at.get(source)
        if open_at is None: return False
        if time.monotonic() - open_at >= cooldown:
            self.circuit_open_at[source] = None; self.fail_counts[source] = 0
            logger.info("MultiSourceFeed[%s]: circuit CLOSED for '%s'", self.symbol, source)
            return False
        return True

    def record_failure(self, source, threshold):
        self.fail_counts[source] = self.fail_counts.get(source, 0) + 1
        if self.fail_counts[source] >= threshold:
            self.circuit_open_at[source] = time.monotonic()
            logger.warning("MultiSourceFeed[%s]: circuit OPEN for '%s' after %d failures",
                           self.symbol, source, self.fail_counts[source])

    def record_success(self, source, price):
        self.fail_counts[source] = 0; self.circuit_open_at[source] = None
        self.current_price = price; self.last_update = datetime.now(tz=UTC)
        self.history.append((price, self.last_update)); self.last_price_for_anomaly = price

    def pick_source(self, fallback_order, cooldown):
        for src in fallback_order:
            if not self.is_circuit_open(src, cooldown): return src
        return fallback_order[0]

    def is_price_valid(self, price): return self.price_min < price < self.price_max

    def is_anomalous(self, price, jump_pct):
        if self.last_price_for_anomaly is None: return False
        return abs((price - self.last_price_for_anomaly) / self.last_price_for_anomaly) * 100.0 > jump_pct

    def status(self):
        return {"symbol": self.symbol, "current_price": self.current_price,
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "active_source": self.active_source, "fail_counts": dict(self.fail_counts),
                "circuit_open": {s: (v is not None) for s, v in self.circuit_open_at.items()},
                "history_size": len(self.history)}


class MultiSourceTickFeed:
    """Multi-symbol, multi-source tick ingestion engine (yFinance->AlphaVantage->TwelveData)."""

    def __init__(self, config_path=_CONFIG_PATH, symbols=None):
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
        self._fallback_order = self._cfg.get("fallback_order", _FALLBACK_ORDER)
        redis_cfg = self._cfg.get("redis", {})
        self._tick_key_ttl = int(redis_cfg.get("tick_key_ttl", 30))
        symbols_cfg = self._cfg.get("symbols", {})
        active = symbols or list(symbols_cfg.keys()) or ["XAUUSD"]
        self._symbol_cfgs = {s: symbols_cfg.get(s, {}) for s in active}
        self._states = {
            sym: _SymbolState(sym, float(scfg.get("price_min",0.0)),
                              float(scfg.get("price_max",1_000_000.0)), self._history_size)
            for sym, scfg in self._symbol_cfgs.items()
        }
        self._sources: dict[str, Any] = {}
        self._session = None
        self._tick_writer = None
        self._redis_errors = 0
        self._subscribers: list[Any] = []
        self._running = False
        self._tasks: list[asyncio.Task] = []
        logger.info("MultiSourceTickFeed init | symbols=%s | chain=%s",
                    list(self._states.keys()), self._fallback_order)

    def _build_sources(self):
        from .sources.alpha_vantage import AlphaVantageSource
        from .sources.twelve_data import TwelveDataSource
        from .sources.yfinance_source import YFinanceSource
        yf = self._cfg.get("yfinance", {}); av = self._cfg.get("alpha_vantage", {}); td = self._cfg.get("twelve_data", {})
        av_key = _resolve_env(av.get("api_key","")) or os.getenv("ALPHA_VANTAGE_KEY","") or os.getenv("ALPHA_VANTAGE_API_KEY","")
        td_key = _resolve_env(td.get("api_key","")) or os.getenv("TWELVE_API_KEY","")
        return {
            "yfinance": YFinanceSource(period=yf.get("period","1d"), interval=yf.get("interval","1m")),
            "alpha_vantage": AlphaVantageSource(api_key=av_key, timeout=self._timeout_s, session=self._session),
            "twelve_data": TwelveDataSource(api_key=td_key, timeout=self._timeout_s, session=self._session),
        }

    def subscribe(self, component):
        self._subscribers.append(component)
        logger.info("MultiSourceTickFeed: %s subscribed", type(component).__name__)

    def unsubscribe(self, component):
        with contextlib.suppress(ValueError): self._subscribers.remove(component)

    async def start(self):
        if self._running: return
        self._running = True
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout_s))
        self._sources = self._build_sources()
        for name in ("alpha_vantage","twelve_data"):
            src = self._sources.get(name)
            if src and hasattr(src,"_session"):
                src._session = self._session; src._owns_session = False
        try:
            from .redis_tick_writer import RedisTickWriter
            self._tick_writer = RedisTickWriter(tick_key_ttl=self._tick_key_ttl)
            await self._tick_writer.connect()
        except Exception as exc:
            logger.warning("MultiSourceTickFeed: RedisTickWriter init failed (non-fatal): %s", exc)
            self._tick_writer = None
        for sym in self._states:
            self._tasks.append(asyncio.create_task(self._poll_symbol(sym), name=f"msf_poll_{sym}"))
        self._tasks.append(asyncio.create_task(self._health_monitor(), name="msf_health"))
        logger.info("MultiSourceTickFeed started | %d symbol(s) | refresh=%.1fs | redis=%s",
                    len(self._states), self._refresh_s,
                    "connected" if self._tick_writer else "unavailable")

    async def stop(self):
        self._running = False
        for t in self._tasks: t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._session and not self._session.closed: await self._session.close()
        if self._tick_writer: await self._tick_writer.close()
        logger.info("MultiSourceTickFeed stopped")

    def get_price(self, symbol):
        st = self._states.get(symbol); return st.current_price if st else None

    def get_last_update(self, symbol):
        st = self._states.get(symbol); return st.last_update if st else None

    def status(self):
        return {
            "running": self._running,
            "symbols": {sym: st.status() for sym, st in self._states.items()},
            "sources": {n: s.status() if hasattr(s,"status") else {} for n,s in self._sources.items()},
            "redis": self._tick_writer.status() if self._tick_writer else {"redis_connected": False},
            "subscriber_count": len(self._subscribers),
        }

    async def _poll_symbol(self, symbol):
        state = self._states[symbol]; sym_cfg = self._symbol_cfgs.get(symbol, {})
        while self._running:
            t0 = time.monotonic()
            source = state.pick_source(self._fallback_order, self._cb_cooldown)
            price = await self._fetch_with_retry(symbol, source, sym_cfg)
            if price is not None:
                if state.is_anomalous(price, self._anomaly_pct):
                    logger.warning("MultiSourceFeed[%s]: anomaly from '%s': %.4f->%.4f — discarded",
                                   symbol, source, state.last_price_for_anomaly, price)
                    state.record_failure(source, self._cb_threshold)
                elif not state.is_price_valid(price):
                    logger.warning("MultiSourceFeed[%s]: out-of-range from '%s': %.4f — discarded",
                                   symbol, source, price)
                    state.record_failure(source, self._cb_threshold)
                else:
                    latency_ms = (time.monotonic() - t0) * 1000.0
                    state.record_success(source, price); state.active_source = source
                    if _PROM and _PG:
                        _PG.labels(symbol=symbol,source=source).set(price)
                        _LG.labels(symbol=symbol,source=source).set(latency_ms)
                        _SG.labels(symbol=symbol).set(
                            self._fallback_order.index(source) if source in self._fallback_order else -1)
                    logger.debug("MultiSourceFeed[%s]: %.4f via '%s' (%.0f ms)",
                                 symbol, price, source, latency_ms)
                    await self._publish(symbol, price, source)
                    await self._broadcast(symbol, price)
            else:
                state.record_failure(source, self._cb_threshold)
                nxt = state.pick_source(self._fallback_order, self._cb_cooldown)
                if nxt != source:
                    state.active_source = nxt
                    logger.warning("MultiSourceFeed[%s]: '%s' failed — switching to '%s'",
                                   symbol, source, nxt)
            await asyncio.sleep(self._refresh_s)

    async def _fetch_with_retry(self, symbol, source, sym_cfg):
        adapter = self._sources.get(source)
        if adapter is None: return None
        for attempt in range(1, self._max_retries + 1):
            try:
                price = await adapter.fetch(symbol, sym_cfg)
                if price is not None: return price
            except asyncio.CancelledError: raise
            except Exception as exc:
                logger.warning("MultiSourceFeed[%s/%s]: attempt %d/%d: %s",
                               symbol, source, attempt, self._max_retries, exc)
            if attempt < self._max_retries: await asyncio.sleep(0.5 * attempt)
        return None

    async def _publish(self, symbol, price, source):
        if self._tick_writer is None: return
        ok = await self._tick_writer.write(symbol=symbol, price=price, source=source)
        if not ok: self._redis_errors += 1

    async def _broadcast(self, symbol, price):
        if not self._subscribers: return
        tasks = [asyncio.create_task(sub.on_new_price(price))
                 for sub in self._subscribers if hasattr(sub,"on_new_price")]
        if not tasks: return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sub, result in zip(self._subscribers, results, strict=False):
            if isinstance(result, Exception):
                logger.error("MultiSourceFeed[%s]: subscriber %s raised: %s",
                             symbol, type(sub).__name__, result)

    async def _health_monitor(self):
        while self._running:
            await asyncio.sleep(15)
            now = datetime.now(tz=UTC)
            for sym, state in self._states.items():
                if state.last_update is None: continue
                age_s = (now - state.last_update).total_seconds()
                if age_s > self._max_stale_s:
                    logger.warning("MultiSourceFeed[%s]: stale (%.0f s) — rotating source", sym, age_s)
                    state.record_failure(state.active_source, self._cb_threshold)
                    state.active_source = state.pick_source(self._fallback_order, self._cb_cooldown)


_feed_instance: MultiSourceTickFeed | None = None

def get_multi_source_feed(config_path=_CONFIG_PATH, symbols=None):
    """Return the module-level MultiSourceTickFeed singleton."""
    global _feed_instance
    if _feed_instance is None:
        _feed_instance = MultiSourceTickFeed(config_path=config_path, symbols=symbols)
    return _feed_instance
