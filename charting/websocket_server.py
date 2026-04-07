# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
charting/websocket_server.py
==============================
Nuclear dashboard WebSocket server — bridges NuclearAIChartEngine to
the React frontend over a persistent WebSocket connection.

Endpoints
---------
  GET  /ws/nuclear          — main nuclear chart stream (NuclearChartState)
  GET  /ws/live             — existing live feed (price ticks, positions)
  POST /api/nuclear/event   — inject a news event for immediate scoring
  GET  /api/nuclear/snapshot — HTTP snapshot of current chart state
  POST /api/nuclear/resume  — manually resume trading after nuclear halt
  GET  /api/nuclear/history — last N nuclear events

Message types sent to clients
------------------------------
  nuclear_chart_update   — full NuclearChartState (every TICK_INTERVAL_S)
  nuclear_alert          — immediate alert on severity ≥ 7
  nuclear_resume         — trading resumed notification
  heartbeat              — keepalive every 30s

Message types received from clients
-------------------------------------
  subscribe              — { "type": "subscribe", "channels": ["nuclear", "price"] }
  ping                   — keepalive ping
  inject_event           — { "type": "inject_event", "text": "...", "vol": 1.0, "sentiment": 0.0 }

Integration with existing /ws/live
-----------------------------------
The existing useWebSocket hook connects to /ws/live. The nuclear dashboard
uses a separate /ws/nuclear endpoint so it does not interfere with the
existing connection. Both can be active simultaneously.

Usage (standalone)
------------------
    python -m charting.websocket_server          # port 8001
    NUCLEAR_WS_PORT=8002 python -m charting.websocket_server

Usage (embedded in FastAPI app)
--------------------------------
    from charting.websocket_server import mount_nuclear_routes
    mount_nuclear_routes(app)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

# ── Optional FastAPI / WebSockets ─────────────────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    logger.warning("FastAPI not installed — nuclear WebSocket server disabled")

# ── Internal imports ──────────────────────────────────────────────────────────
from charting.nuclear_ai_chart_engine import NuclearAIChartEngine, get_chart_engine

NUCLEAR_WS_PORT: int = int(os.environ.get("NUCLEAR_WS_PORT", "8001"))
HEARTBEAT_INTERVAL_S: int = 30
NUCLEAR_ALERT_SEVERITY: int = 7


# ─────────────────────────────────────────────────────────────────────────────
# Connection manager
# ─────────────────────────────────────────────────────────────────────────────


class NuclearConnectionManager:
    """Manages all active WebSocket connections to the nuclear dashboard."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("Nuclear WS client connected. Total: %d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("Nuclear WS client disconnected. Total: %d", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients."""
        if not self._connections:
            return
        payload = json.dumps(message, default=str)
        dead: ClassVar[set[WebSocket]] = set()
        async with self._lock:
            connections = set(self._connections)
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:  # nosec B110
                dead.add(ws)
        if dead:
            async with self._lock:
                self._connections -= dead

    async def send_to(self, ws: WebSocket, message: dict) -> None:
        """Send a message to a single client."""
        try:
            await ws.send_text(json.dumps(message, default=str))
        except Exception as exc:
            logger.debug("Send error: %s", exc)

    @property
    def count(self) -> int:
        return len(self._connections)


# Module-level manager
_manager = NuclearConnectionManager()


# ─────────────────────────────────────────────────────────────────────────────
# Broadcast bridge — connects chart engine to WebSocket manager
# ─────────────────────────────────────────────────────────────────────────────


def _sync_broadcast_callback(state: dict) -> None:
    """
    Synchronous callback registered with NuclearAIChartEngine.
    Schedules the async broadcast on the running event loop.
    """
    try:
        loop = asyncio.get_running_loop()
        _t = loop.create_task(_async_broadcast(state))
        _t.add_done_callback(lambda _: None)
    except RuntimeError:
        ...  # nosec B110


async def _async_broadcast(state: dict) -> None:
    await _manager.broadcast(state)

    # Also send an immediate nuclear_alert if severity is high
    nuclear = state.get("nuclear", {})
    if nuclear.get("alert_active") and nuclear.get("severity", 0) >= NUCLEAR_ALERT_SEVERITY:
        alert = {
            "type": "nuclear_alert",
            "ts": state.get("ts"),
            "severity": nuclear.get("severity"),
            "action": nuclear.get("action"),
            "rl_action_label": nuclear.get("rl_action_label"),
            "explanation": nuclear.get("explanation"),
            "historical_analog": nuclear.get("historical_analog"),
            "gauge": state.get("geopolitical_gauge"),
        }
        await _manager.broadcast(alert)


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI route mounting
# ─────────────────────────────────────────────────────────────────────────────


def mount_nuclear_routes(app: Any, engine: NuclearAIChartEngine | None = None) -> None:
    """
    Mount nuclear dashboard routes onto an existing FastAPI app.

    Call this from app.py or the main FastAPI application:
        from charting.websocket_server import mount_nuclear_routes
        mount_nuclear_routes(app)
    """
    if not _FASTAPI_AVAILABLE:
        logger.warning("FastAPI not available — cannot mount nuclear routes")
        return

    chart_engine = engine or get_chart_engine()
    chart_engine.add_broadcast_callback(_sync_broadcast_callback)

    # ── WebSocket endpoint ────────────────────────────────────────────────────

    @app.websocket("/ws/nuclear")
    async def nuclear_ws_endpoint(ws: WebSocket):
        from rate_limiting.websocket_limiter import get_client_ip, get_ws_limiter

        limiter = get_ws_limiter()
        client_ip = get_client_ip(ws)

        allowed, reason = await limiter.check_and_register(ws, client_ip)
        if not allowed:
            await ws.close(code=1008, reason=reason)
            return

        await _manager.connect(ws)
        # Send immediate snapshot on connect
        snapshot = chart_engine.get_snapshot()
        await _manager.send_to(ws, snapshot)

        heartbeat_task = asyncio.create_task(_heartbeat_loop(ws))
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                    msg = json.loads(raw)
                    await _handle_client_message(ws, msg, chart_engine)
                except TimeoutError:
                    # Client silent for 60s — send ping
                    await _manager.send_to(ws, {"type": "ping", "ts": int(time.time() * 1000)})
                except WebSocketDisconnect:
                    break
                except json.JSONDecodeError:
                    await _manager.send_to(ws, {"type": "error", "message": "Invalid JSON"})
        finally:
            heartbeat_task.cancel()
            await _manager.disconnect(ws)
            await limiter.release(client_ip)

    # ── HTTP endpoints ────────────────────────────────────────────────────────

    @app.get("/api/nuclear/snapshot")
    async def nuclear_snapshot():
        """Return current NuclearChartState as JSON (for HTTP polling fallback)."""
        return JSONResponse(chart_engine.get_snapshot())

    @app.post("/api/nuclear/event")
    async def inject_nuclear_event(body: dict):
        """
        Inject a news event for immediate nuclear scoring.
        Body: { "text": "...", "volatility": 1.0, "sentiment": 0.0 }
        """
        text = body.get("text", "")
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        vol = float(body.get("volatility", 1.0))
        sentiment = float(body.get("sentiment", 0.0))
        result = chart_engine.inject_news_event(text, vol, sentiment)
        return JSONResponse(result)

    @app.post("/api/nuclear/resume")
    async def nuclear_resume():
        """Manually resume trading after a nuclear halt."""
        try:
            from brain.nuclear_supervisor import get_nuclear_supervisor

            sup = get_nuclear_supervisor()
            await sup.manual_resume()
            await _manager.broadcast(
                {
                    "type": "nuclear_resume",
                    "ts": int(time.time() * 1000),
                    "message": "Trading manually resumed by operator.",
                }
            )
            return JSONResponse({"status": "resumed"})
        except Exception as exc:
            logger.error("nuclear resume failed: %s", exc)
            raise HTTPException(status_code=500, detail="Operation failed — check server logs") from None

    @app.get("/api/nuclear/history")
    async def nuclear_history(n: int = 20):
        """Return last N nuclear events."""
        try:
            from brain.nuclear_supervisor import get_nuclear_supervisor

            sup = get_nuclear_supervisor()
            history = sup.get_event_history(n)
            return JSONResponse({"events": history})
        except Exception as exc:
            logger.warning("nuclear_history failed: %s", exc)
            return JSONResponse({"events": [], "error": "History unavailable — check server logs"})

    @app.get("/api/nuclear/status")
    async def nuclear_status():
        """Return nuclear supervisor status + connection count."""
        try:
            from brain.nuclear_supervisor import get_nuclear_supervisor

            sup = get_nuclear_supervisor()
            status = sup.get_status()
        except ImportError:
            status = {}
        return JSONResponse(
            {
                "ws_connections": _manager.count,
                "supervisor": status,
                "engine_ticks": chart_engine._tick_count,
            }
        )

    logger.info("Nuclear dashboard routes mounted: /ws/nuclear, /api/nuclear/*")


# ─────────────────────────────────────────────────────────────────────────────
# Client message handler
# ─────────────────────────────────────────────────────────────────────────────


async def _handle_client_message(ws: WebSocket, msg: dict, engine: NuclearAIChartEngine) -> None:
    msg_type = msg.get("type", "")

    if msg_type == "ping":
        await _manager.send_to(ws, {"type": "pong", "ts": int(time.time() * 1000)})

    elif msg_type == "subscribe":
        # Acknowledge subscription — actual data flows via broadcast
        channels = msg.get("channels", [])
        await _manager.send_to(
            ws,
            {
                "type": "subscribed",
                "channels": channels,
                "ts": int(time.time() * 1000),
            },
        )

    elif msg_type == "inject_event":
        text = msg.get("text", "")
        vol = float(msg.get("vol", 1.0))
        sentiment = float(msg.get("sentiment", 0.0))
        if text:
            result = engine.inject_news_event(text, vol, sentiment)
            await _manager.send_to(
                ws,
                {
                    "type": "event_scored",
                    "result": result,
                    "ts": int(time.time() * 1000),
                },
            )

    elif msg_type == "get_snapshot":
        snapshot = engine.get_snapshot()
        await _manager.send_to(ws, snapshot)

    elif msg_type == "get_history":
        n = int(msg.get("n", 20))
        try:
            from brain.nuclear_supervisor import get_nuclear_supervisor

            history = get_nuclear_supervisor().get_event_history(n)
        except ImportError:
            history = []
        await _manager.send_to(
            ws,
            {
                "type": "nuclear_history",
                "events": history,
                "ts": int(time.time() * 1000),
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Heartbeat loop
# ─────────────────────────────────────────────────────────────────────────────


async def _heartbeat_loop(ws: WebSocket) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "type": "heartbeat",
                        "ts": int(time.time() * 1000),
                    }
                )
            )
        except Exception:  # nosec B110
            break


# ─────────────────────────────────────────────────────────────────────────────
# Standalone server entry point
# ─────────────────────────────────────────────────────────────────────────────


def create_standalone_app() -> Any:
    """Create a standalone FastAPI app for the nuclear WebSocket server."""
    if not _FASTAPI_AVAILABLE:
        raise RuntimeError("FastAPI is required for standalone mode")

    app = FastAPI(title="HOPEFX Nuclear Dashboard WS", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    engine = get_chart_engine()
    mount_nuclear_routes(app, engine)

    @app.on_event("startup")
    async def _startup():
        _t = asyncio.create_task(engine.start())
        _t.add_done_callback(lambda _: None)
        logger.info("Nuclear chart engine started on app startup.")

    @app.on_event("shutdown")
    async def _shutdown():
        await engine.stop()

    return app


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    standalone_app = create_standalone_app()
    uvicorn.run(standalone_app, host="0.0.0.0", port=NUCLEAR_WS_PORT, log_level="info")  # nosec B104 - container/K8s deployment requires 0.0.0.0
