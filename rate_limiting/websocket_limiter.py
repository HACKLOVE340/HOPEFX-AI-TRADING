# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
rate_limiting/websocket_limiter.py
===================================
Per-IP WebSocket connection rate limiter and concurrent connection cap.

Problem
-------
FastAPI's `Depends()` mechanism does not apply to WebSocket upgrade requests
before `websocket.accept()` is called.  A single client can open unlimited
WebSocket connections, exhausting file descriptors and memory.

Solution
--------
WebSocketConnectionLimiter enforces two independent limits per client IP:

  1. Concurrent connection cap  — max open connections from one IP at a time.
     Default: WS_MAX_CONNECTIONS_PER_IP=10
     Exceeding this closes the new connection with code 1008 (policy violation).

  2. Connection rate cap  — max new connections per IP per minute.
     Default: WS_MAX_CONNECTIONS_PER_MINUTE=20
     Exceeding this closes the new connection with code 1008.

Both limits are enforced before websocket.accept() so the TCP connection is
rejected at the HTTP upgrade stage, not after a full WebSocket handshake.

Storage
-------
- Primary: Redis (shared across replicas, TTL-based sliding window).
- Fallback: asyncio-safe in-process counters (single-pod only).

Usage
-----
    from rate_limiting.websocket_limiter import get_ws_limiter

    limiter = get_ws_limiter()

    @app.websocket("/ws/live")
    async def live_ws(ws: WebSocket):
        client_ip = get_client_ip(ws)
        allowed, reason = await limiter.check_and_register(ws, client_ip)
        if not allowed:
            return  # socket already closed by check_and_register()

        await ws.accept()
        try:
            ...
        finally:
            await limiter.release(client_ip)

Configuration (env vars)
------------------------
WS_MAX_CONNECTIONS_PER_IP      — max concurrent connections per IP (default: 10)
WS_MAX_CONNECTIONS_PER_MINUTE  — max new connections per IP per minute (default: 20)
WS_RATE_WINDOW_SECONDS         — sliding window for rate cap (default: 60)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
# Default raised from 10 → 50: a single browser session can legitimately open
# multiple sockets (main /ws/live + chart-bot orchestrator + nuclear dashboard).
# The old limit of 10 was hit immediately in multi-tab or multi-panel layouts.
_MAX_CONNS_PER_IP = int(os.getenv("WS_MAX_CONNECTIONS_PER_IP", "50"))
_MAX_CONNS_PER_MINUTE = int(os.getenv("WS_MAX_CONNECTIONS_PER_MINUTE", "60"))
_RATE_WINDOW_S = int(os.getenv("WS_RATE_WINDOW_SECONDS", "60"))

# Redis key prefixes
_KEY_CONNS = "hopefx:ws:conns:"  # INCR/DECR — current open connections
_KEY_RATE = "hopefx:ws:rate:"  # sorted set — timestamps of recent connects


class WebSocketConnectionLimiter:
    """
    Enforces per-IP concurrent connection cap and connection rate cap.

    Thread-safe for asyncio. Uses Redis when available, falls back to
    in-process counters (not shared across pods).
    """

    def __init__(self) -> None:
        self._redis = None
        self._redis_connect_failed: bool = False  # True after first failed attempt
        # In-process fallback state
        self._open_conns: dict[str, int] = defaultdict(int)
        self._rate_window: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()
        # Per-IP stack of backends used by open connections.
        # A stack (list) is required because multiple connections from the same
        # IP can be open simultaneously — each push on check_and_register() is
        # matched by a pop on release(), preserving LIFO symmetry regardless of
        # how many concurrent connections exist from one IP.
        self._conn_backend: dict[str, list] = defaultdict(list)  # ip → ["redis"|"local", ...]

    # ── Redis connection ──────────────────────────────────────────────────────

    def _try_connect_redis(self) -> None:
        """
        Create the Redis client if not already done.

        Called on every check_and_register() so that if Redis was unavailable
        at startup but comes up later, the limiter will start using it.
        Once a client object is successfully created (even if the broker is
        temporarily unreachable) we do not recreate it — the redis.asyncio
        client handles reconnection internally.
        """
        if self._redis is not None:
            return  # Already have a live client object
        if self._redis_connect_failed:
            return  # Import failed — redis package not installed; don't retry
        try:
            import redis.asyncio as aioredis  # pylint: disable=no-name-in-module

            # Build a default URL from the same env vars used by the rest of
            # the app (REDIS_HOST / REDIS_PORT / REDIS_PASSWORD) so that the
            # limiter connects to the same broker as nuclear_streamer and the
            # MacroStoreBridge.  REDIS_URL takes precedence when set explicitly.
            _host = os.getenv("REDIS_HOST", "localhost")
            _port = os.getenv("REDIS_PORT", "6379")
            _pw = os.getenv("REDIS_PASSWORD", "")
            _auth = f":{_pw}@" if _pw else ""
            _default_url = f"redis://{_auth}{_host}:{_port}/0"
            redis_url = os.getenv("REDIS_URL", _default_url)

            self._redis = aioredis.from_url(
                redis_url,
                socket_connect_timeout=0.5,
                socket_timeout=1.0,
                decode_responses=True,
            )
            logger.debug("WebSocketConnectionLimiter: Redis client created (%s:%s)", _host, _port)
        except ImportError:
            # redis package not installed — stay on in-process forever
            self._redis_connect_failed = True
            logger.warning(
                "WebSocketConnectionLimiter: redis package not installed — "
                "using in-process fallback (not shared across pods)"
            )
        except Exception as exc:
            # Unexpected error building the client object; log and retry next call
            logger.warning(
                "WebSocketConnectionLimiter: could not create Redis client (%s) — "
                "will retry on next connection; using in-process fallback for now",
                exc,
            )
            self._redis = None

    # ── Redis-backed checks ───────────────────────────────────────────────────

    async def _redis_check_and_register(self, ip: str) -> tuple[bool, str]:
        """Check limits and register connection in Redis. Returns (allowed, reason)."""
        try:
            now = time.time()
            conn_key = f"{_KEY_CONNS}{ip}"
            rate_key = f"{_KEY_RATE}{ip}"

            pipe = self._redis.pipeline()
            # Current open connections
            pipe.get(conn_key)
            # Rate window: count entries in last _RATE_WINDOW_S seconds
            pipe.zcount(rate_key, now - _RATE_WINDOW_S, "+inf")
            results = await pipe.execute()

            current_conns = int(results[0] or 0)
            recent_rate = int(results[1] or 0)

            if current_conns >= _MAX_CONNS_PER_IP:
                return False, (f"Too many concurrent connections from this IP (max {_MAX_CONNS_PER_IP})")
            if recent_rate >= _MAX_CONNS_PER_MINUTE:
                return False, (f"Connection rate limit exceeded (max {_MAX_CONNS_PER_MINUTE} per {_RATE_WINDOW_S}s)")

            # Register: increment open count + add timestamp to rate window
            pipe2 = self._redis.pipeline()
            pipe2.incr(conn_key)
            pipe2.expire(conn_key, _RATE_WINDOW_S * 10)  # TTL safety net
            pipe2.zadd(rate_key, {str(now): now})
            pipe2.zremrangebyscore(rate_key, "-inf", now - _RATE_WINDOW_S)
            pipe2.expire(rate_key, _RATE_WINDOW_S * 2)
            await pipe2.execute()

            return True, ""
        except Exception as exc:
            logger.debug("Redis WS limiter error: %s — falling back", exc)
            return None, ""  # type: ignore[return-value]  # None signals fallback

    async def _redis_release(self, ip: str) -> None:
        """Decrement open connection count in Redis."""
        try:
            conn_key = f"{_KEY_CONNS}{ip}"
            val = await self._redis.decr(conn_key)
            if val < 0:
                await self._redis.set(conn_key, 0)
        except Exception as exc:
            logger.debug("Redis WS release error: %s", exc)

    # ── In-process fallback ───────────────────────────────────────────────────

    async def _local_check_and_register(self, ip: str) -> tuple[bool, str]:
        async with self._lock:
            now = time.time()
            # Prune old rate window entries
            window = self._rate_window[ip]
            while window and window[0] < now - _RATE_WINDOW_S:
                window.popleft()

            current_conns = self._open_conns[ip]
            recent_rate = len(window)

            if current_conns >= _MAX_CONNS_PER_IP:
                return False, (f"Too many concurrent connections from this IP (max {_MAX_CONNS_PER_IP})")
            if recent_rate >= _MAX_CONNS_PER_MINUTE:
                return False, (f"Connection rate limit exceeded (max {_MAX_CONNS_PER_MINUTE} per {_RATE_WINDOW_S}s)")

            self._open_conns[ip] += 1
            window.append(now)
            return True, ""

    async def _local_release(self, ip: str) -> None:
        async with self._lock:
            self._open_conns[ip] = max(0, self._open_conns[ip] - 1)

    # ── Public API ────────────────────────────────────────────────────────────

    async def check_and_register(
        self,
        websocket,
        client_ip: str,
    ) -> tuple[bool, str]:
        """
        Check both limits and register the connection if allowed.

        Must be called BEFORE websocket.accept().

        When the connection is rejected (allowed=False) this method closes the
        WebSocket with code 1008 before returning, suppressing any exception
        that arises if the client already disconnected.  Callers only need to
        check the return value and return early — they must NOT call
        websocket.close() themselves on rejection.

        Parameters
        ----------
        websocket  : FastAPI WebSocket object.
        client_ip  : Client IP address string.

        Returns
        -------
        (allowed, reason) — if allowed=False the socket is already closed.
        """
        self._try_connect_redis()

        if self._redis is not None:
            allowed, reason = await self._redis_check_and_register(client_ip)
            if allowed is not None:  # None = Redis error, fall through to local
                if not allowed:
                    logger.warning("WS connection rejected for %s: %s", client_ip, reason)
                    with contextlib.suppress(Exception):
                        await websocket.close(code=1008, reason=reason)
                else:
                    # Push "redis" onto this IP's backend stack so release()
                    # always decrements the same backend that was incremented,
                    # even when multiple connections from the same IP are open.
                    self._conn_backend[client_ip].append("redis")
                return allowed, reason

        # In-process fallback (Redis unavailable or returned error)
        allowed, reason = await self._local_check_and_register(client_ip)
        if not allowed:
            logger.warning(
                "WS connection rejected for %s (local limiter): %s",
                client_ip,
                reason,
            )
            with contextlib.suppress(Exception):
                await websocket.close(code=1008, reason=reason)
        else:
            self._conn_backend[client_ip].append("local")
        return allowed, reason

    async def release(self, client_ip: str) -> None:
        """
        Decrement the open connection count for this IP.

        Must be called in the finally block of every WebSocket handler.

        Pops the most-recently-pushed backend for this IP and releases against
        it, guaranteeing symmetry with check_and_register() regardless of:
          - multiple concurrent connections from the same IP
          - Redis availability changes between registration and release
        """
        stack = self._conn_backend.get(client_ip)
        backend = stack.pop() if stack else None

        if backend == "redis":
            if self._redis is not None:
                with contextlib.suppress(Exception):
                    await self._redis_release(client_ip)
            else:
                # Redis died after this connection was registered there.
                # The local counter was never incremented for this connection
                # so decrementing it would corrupt the count.  The Redis key
                # expires via its TTL safety net (_RATE_WINDOW_S * 10).
                logger.debug(
                    "WS release: Redis gone after registration for %s — "
                    "skipping local decrement (counter was never incremented locally)",
                    client_ip,
                )
            return

        # "local" backend or unknown (safety net for unmatched release calls)
        await self._local_release(client_ip)

    def stats(self) -> dict:
        """Return current limiter state (for /health and /ws/stats endpoints)."""
        return {
            "max_connections_per_ip": _MAX_CONNS_PER_IP,
            "max_connections_per_minute": _MAX_CONNS_PER_MINUTE,
            "rate_window_seconds": _RATE_WINDOW_S,
            "backend": "redis" if self._redis is not None else "in_process",
            "open_connections_by_ip": dict(self._open_conns),
        }


# ── IP extraction helper ──────────────────────────────────────────────────────


def get_client_ip(websocket) -> str:
    """
    Extract the real client IP from a FastAPI WebSocket object.

    Respects X-Forwarded-For only when the connection comes from a trusted
    proxy (TRUSTED_PROXY_IPS env var, default 127.0.0.1,::1).
    """
    trusted_raw = os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1")
    trusted = {ip.strip() for ip in trusted_raw.split(",") if ip.strip()}

    direct_ip = ""
    with contextlib.suppress(Exception):
        if websocket.client:
            direct_ip = websocket.client.host or ""

    if direct_ip in trusted:
        # Connection is from a trusted proxy — honour X-Forwarded-For
        forwarded = ""
        with contextlib.suppress(Exception):
            forwarded = websocket.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return direct_ip or "unknown"


# ── Module-level singleton ────────────────────────────────────────────────────

_limiter: WebSocketConnectionLimiter | None = None


def get_ws_limiter() -> WebSocketConnectionLimiter:
    """Return the module-level WebSocketConnectionLimiter singleton."""
    global _limiter
    if _limiter is None:
        _limiter = WebSocketConnectionLimiter()
    return _limiter
