# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
websocket/manager.py
====================
Production WebSocket manager with JWT authentication.

This module provides a ``WebSocketManager`` compatible with the legacy
``websockets`` library interface used by standalone scripts and tests.
For the FastAPI application, the canonical implementation is
``api/ws_live.py`` (``LiveConnectionManager``).

Authentication flow
-------------------
1. Client connects.
2. Server sends ``{"type": "auth_required"}``.
3. Client must send ``{"type": "auth", "token": "Bearer <jwt>"}`` within
   ``AUTH_TIMEOUT_SECONDS`` (default 5 s).
4. Server validates the JWT via ``auth.jwt.decode_access_token``.
5. On success: server sends ``{"type": "auth_ok", "user_id": "..."}`` and
   the connection is admitted to the broadcast pool.
6. On failure or timeout: server sends ``{"type": "auth_failed"}`` and
   closes the connection with code 4001.

Environment variables
---------------------
    WS_AUTH_REQUIRED      — "true" (default) / "false" (dev/demo only)
    WS_AUTH_TIMEOUT       — seconds to wait for auth message (default 5)
    SECURITY_JWT_SECRET   — JWT signing secret (required in production)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_AUTH_REQUIRED: bool = os.getenv("WS_AUTH_REQUIRED", "true").lower() == "true"
# 5 s is sufficient for any legitimate client on a normal connection.
# 30 s was too long — it allowed unauthenticated connections to hold a slot
# for half a minute, enabling trivial resource exhaustion.
_AUTH_TIMEOUT: float = float(os.getenv("WS_AUTH_TIMEOUT", "5"))


def _validate_token(token: str) -> dict | None:
    """Validate a Bearer JWT. Returns the decoded payload or None on failure."""
    token = token.removeprefix("Bearer ").strip()
    try:
        from auth.jwt import decode_access_token  # type: ignore[import]

        return decode_access_token(token)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("WS token validation failed: %s", exc)
        return None


class WebSocketManager:
    """
    Manages authenticated WebSocket connections.

    Each connection must pass JWT authentication before it is admitted to
    the broadcast pool.  Unauthenticated connections are closed with
    code 4001 after ``AUTH_TIMEOUT_SECONDS``.
    """

    def __init__(self) -> None:
        # Maps websocket → user_id for authenticated connections only.
        self._authenticated: dict[Any, str] = {}

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def register(self, websocket: Any) -> bool:
        """
        Perform the auth handshake for a new connection.

        Returns True if the connection was authenticated and added to the
        broadcast pool, False if it was rejected.
        """
        try:
            await websocket.send(json.dumps({"type": "auth_required"}))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("WS send auth_required failed: %s", exc)
            return False

        if not _AUTH_REQUIRED:
            # Dev/demo mode — admit without auth, mark as anonymous.
            self._authenticated[websocket] = "anonymous"
            logger.debug("WS auth bypassed (WS_AUTH_REQUIRED=false)")
            return True

        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=_AUTH_TIMEOUT)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("WS auth timeout — closing connection")
            await self._reject(websocket, "auth_timeout")
            return False
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("WS recv error during auth: %s", exc)
            return False

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._reject(websocket, "invalid_json")
            return False

        if msg.get("type") != "auth" or not msg.get("token"):
            await self._reject(websocket, "auth_failed")
            return False

        payload = _validate_token(msg["token"])
        if payload is None:
            await self._reject(websocket, "auth_failed")
            return False

        user_id: str = str(payload.get("sub", "unknown"))
        self._authenticated[websocket] = user_id
        try:
            await websocket.send(json.dumps({"type": "auth_ok", "user_id": user_id}))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("WS send auth_ok failed: %s", exc)
        logger.info("WS authenticated: user=%s  pool_size=%d", user_id, len(self._authenticated))
        return True

    async def unregister(self, websocket: Any) -> None:
        """Remove a connection from the broadcast pool."""
        user_id = self._authenticated.pop(websocket, None)
        logger.info("WS disconnected: user=%s  pool_size=%d", user_id, len(self._authenticated))

    async def connection_handler(self, websocket: Any, path: str = "") -> None:
        """Full connection lifecycle: auth -> message loop -> cleanup."""
        admitted = await self.register(websocket)
        if not admitted:
            return
        try:
            async for message in websocket:
                await self.broadcast(message)
        finally:
            await self.unregister(websocket)

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast(self, message: Any) -> None:
        """Send a message to all authenticated connections."""
        if not self._authenticated:
            return
        encoded = json.dumps(message) if not isinstance(message, str) else message
        # asyncio.gather with return_exceptions=True ensures one slow/dead
        # connection cannot block or crash the broadcast to all others.
        await asyncio.gather(
            *[ws.send(encoded) for ws in list(self._authenticated)],
            return_exceptions=True,
        )

    async def broadcast_to_user(self, user_id: str, message: Any) -> None:
        """Send a message to all connections belonging to a specific user."""
        targets = [ws for ws, uid in self._authenticated.items() if uid == user_id]
        if not targets:
            return
        encoded = json.dumps(message) if not isinstance(message, str) else message
        await asyncio.gather(*[ws.send(encoded) for ws in targets], return_exceptions=True)

    # ── Server ────────────────────────────────────────────────────────────────

    def start_server(self, host: str = "localhost", port: int = 8765) -> None:
        """Start a standalone websockets server (non-FastAPI deployments)."""
        import websockets  # type: ignore[import]

        async def _serve() -> None:
            async with websockets.serve(self.connection_handler, host, port):
                logger.info("WS server listening on ws://%s:%d", host, port)
                await asyncio.Future()  # run forever

        asyncio.run(_serve())

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def connection_count(self) -> int:
        return len(self._authenticated)

    async def _reject(self, websocket: Any, reason: str) -> None:
        try:
            await websocket.send(json.dumps({"type": "auth_failed", "reason": reason}))
            await websocket.close(code=4001)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("WS reject cleanup error: %s", exc)


# Module-level singleton for use by app.py and other modules.
manager = WebSocketManager()


if __name__ == "__main__":
    manager.start_server()
