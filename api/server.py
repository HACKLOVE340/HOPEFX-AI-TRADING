# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX API Server
FastAPI application with logging, health checks, and metrics
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

try:
    from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, PlainTextResponse
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logging.warning("FastAPI not available, API server disabled")

from infrastructure.health import HealthStatus, get_health_checker
from infrastructure.logging import get_logger
from infrastructure.metrics import get_metrics_registry

logger = logging.getLogger(__name__)

logger = get_logger(__name__)


# Pydantic models
class TradeRequest(BaseModel):
    symbol: str
    side: str  # buy or sell
    quantity: float
    order_type: str = "market"


class ConfigUpdate(BaseModel):
    key: str
    value: Any


def create_api_app(trading_app=None) -> Optional[Any]:
    """Create FastAPI application"""
    if not FASTAPI_AVAILABLE:
        return None

    import os

    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest

    # ── Config resolved before app construction ───────────────────────────────
    _raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
    _allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

    # Hard-fail in production if ALLOWED_ORIGINS is still localhost — the
    # frontend can never reach the API from a real domain in that state.
    if os.getenv("APP_ENV") == "production" and all(
        "localhost" in o or "127." in o for o in _allowed_origins
    ):
        import sys as _sys

        logger.critical(
            "STARTUP BLOCKED: ALLOWED_ORIGINS is localhost-only in production. "
            "Set ALLOWED_ORIGINS=https://app.yourdomain.com before deploying."
        )
        _sys.exit(1)
    _ALLOWED_SYMBOLS = frozenset(
        os.getenv(
            "ALLOWED_SYMBOLS",
            "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,AUDUSD,USDCHF",
        ).split(","),
    )
    _MAX_QTY = float(os.getenv("MAX_ORDER_QUANTITY", "100.0"))

    # ── Health checker resolved before lifespan ───────────────────────────────
    if trading_app:
        health_checker = get_health_checker(trading_app)
    else:
        health_checker = get_health_checker()

    # ── Lifespan defined before FastAPI() so it can be passed at construction ─
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info("API server starting...")
        if trading_app:
            asyncio.create_task(health_checker.start_monitoring())

        # ── NuclearStreamer — live tick stream → EventBus → WebSocket clients ──
        # Streams XAUUSD from Finnhub / Twelve Data / Polygon concurrently.
        # OANDA is NOT used for streaming; it is execution-only.
        # At least one of FINNHUB_API_KEY / TWELVE_API_KEY / POLYGON_API_KEY
        # must be set for live ticks.  If none are set the stream is skipped
        # gracefully and the WebSocket falls back to no_live_feed.
        _nuclear_stream_task = None
        _has_any_stream_key = any(
            [
                os.getenv("FINNHUB_API_KEY"),
                os.getenv("TWELVE_API_KEY"),
                os.getenv("POLYGON_API_KEY"),
            ]
        )

        if _has_any_stream_key:
            try:
                from data_feed import NuclearStreamer
                from core.event_bus import bus, CH_TICK

                class _EventBusSubscriber:
                    """Bridge: forwards NuclearStreamer ticks onto the EventBus."""

                    async def on_new_price(self, price: float) -> None:
                        try:
                            await bus.publish(
                                CH_TICK, {"price": price, "symbol": "XAUUSD"}
                            )
                        except Exception as _exc:
                            logger.debug(
                                "NuclearStreamer EventBus forward error: %s", _exc
                            )

                _streamer = NuclearStreamer()
                _streamer.subscribe(_EventBusSubscriber())
                _nuclear_stream_task = asyncio.create_task(_streamer.run())
                logger.info(
                    "NuclearStreamer started — sources: finnhub=%s twelvedata=%s polygon=%s",
                    bool(os.getenv("FINNHUB_API_KEY")),
                    bool(os.getenv("TWELVE_API_KEY")),
                    bool(os.getenv("POLYGON_API_KEY")),
                )
            except Exception as _exc:
                logger.warning("NuclearStreamer init failed (non-fatal): %s", _exc)
        else:
            logger.info(
                "No streaming API keys set (FINNHUB_API_KEY / TWELVE_API_KEY / "
                "POLYGON_API_KEY) — live tick stream disabled."
            )

        # ── Weekly performance report scheduler ───────────────────────────────
        _scheduler = None
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
            from reports.weekly_report import schedule_weekly_report

            _scheduler = AsyncIOScheduler()
            schedule_weekly_report(_scheduler)
            _scheduler.start()
        except ImportError:
            logger.info(
                "APScheduler not installed — weekly report scheduling disabled. "
                "Install: pip install apscheduler"
            )
        except Exception as _exc:
            logger.warning("Scheduler init failed (non-fatal): %s", _exc)

        yield

        # ── Shutdown ──────────────────────────────────────────────────────────
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        if _nuclear_stream_task and not _nuclear_stream_task.done():
            _nuclear_stream_task.cancel()
            try:
                await asyncio.wait_for(_nuclear_stream_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        logger.info("API server shutting down...")
        health_checker.stop_monitoring()

    # ── Single app construction ───────────────────────────────────────────────
    app = FastAPI(
        title="HOPEFX Trading API",
        description="Production trading system API",
        version="2.1.0",
        docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
        redoc_url=None if os.getenv("APP_ENV") == "production" else "/redoc",
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "PUT"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
            response.headers["Permissions-Policy"] = (
                "geolocation=(), microphone=(), camera=()"
            )
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # ── Auth dependencies ─────────────────────────────────────────────────────
    _bearer = HTTPBearer(auto_error=True)

    def _get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
        try:
            from api.auth import _decode_token

            return _decode_token(credentials.credentials)
        except Exception as exc:
            logger.warning("Token decode failed: %s", exc)
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def _require_trader(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
        user = _get_current_user(credentials)
        _ROLE_RANK = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}
        if _ROLE_RANK.get(user.role, -1) < _ROLE_RANK["trader"]:
            raise HTTPException(status_code=403, detail="Role 'trader' required")
        return user

    def _require_admin(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
        user = _get_current_user(credentials)
        _ROLE_RANK = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}
        if _ROLE_RANK.get(user.role, -1) < _ROLE_RANK["admin"]:
            raise HTTPException(status_code=403, detail="Role 'admin' required")
        return user

    # Store reference to trading app
    app.state.trading_app = trading_app

    # Health endpoints
    @app.get("/health")
    async def health():
        """Comprehensive health check"""
        health_data = await health_checker.run_all_checks()

        status_code = 200
        if health_data.status == HealthStatus.UNHEALTHY:
            status_code = 503
        elif health_data.status == HealthStatus.DEGRADED:
            status_code = 503  # or 200 depending on your LB config

        return JSONResponse(content=health_data.to_dict(), status_code=status_code)

    @app.get("/ready")
    async def ready():
        """Readiness probe"""
        if not trading_app:
            return {"ready": False}

        ready = trading_app._components_initialized and trading_app.running
        return JSONResponse(content={"ready": ready}, status_code=200 if ready else 503)

    @app.get("/live")
    async def live():
        """Liveness probe"""
        return {"alive": True}

    # Metrics endpoint (Prometheus format)
    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics"""
        registry = get_metrics_registry()
        return PlainTextResponse(
            content=registry.export_prometheus(),
            media_type="text/plain",
        )

    # Trading endpoints
    @app.get("/api/v1/status")
    async def get_status(user=Depends(_get_current_user)):
        """Get trading system status. Requires: authenticated user."""
        if not trading_app:
            raise HTTPException(status_code=503, detail="Trading app not available")
        return trading_app.get_status()

    @app.get("/api/v1/account")
    async def get_account(user=Depends(_get_current_user)):
        """Get account information. Requires: authenticated user."""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        try:
            return await trading_app.broker.get_account_info()
        except Exception as e:
            logger.error("Error getting account info: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/positions")
    async def get_positions(user=Depends(_get_current_user)):
        """Get open positions. Requires: authenticated user."""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        try:
            positions = await trading_app.broker.get_positions()
            return {
                "positions": [p.to_dict() for p in positions],
                "count": len(positions),
            }
        except Exception as e:
            logger.error("Error getting positions: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/orders", status_code=201)
    async def place_order(
        request: TradeRequest,
        background_tasks: BackgroundTasks,
        user=Depends(_require_trader),
    ):
        """Place a new order. Requires: role >= 'trader'. Symbol and quantity validated."""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")

        # Server-side symbol validation
        symbol = request.symbol.upper().strip()
        if symbol not in _ALLOWED_SYMBOLS:
            raise HTTPException(
                status_code=400,
                detail=f"Symbol '{symbol}' not permitted. Allowed: {sorted(_ALLOWED_SYMBOLS)}",
            )

        # Server-side quantity validation
        if request.quantity <= 0 or request.quantity > _MAX_QTY:
            raise HTTPException(
                status_code=400,
                detail=f"Quantity must be > 0 and <= {_MAX_QTY}",
            )

        # Side validation
        if request.side.lower() not in ("buy", "sell"):
            raise HTTPException(status_code=400, detail="side must be 'buy' or 'sell'")

        try:
            order = await trading_app.broker.place_market_order(
                symbol=symbol,
                side=request.side.lower(),
                quantity=request.quantity,
            )
            logger.info(
                "Order placed: user=%s symbol=%s side=%s qty=%s id=%s",
                user.sub,
                symbol,
                request.side,
                request.quantity,
                order.id,
            )
            background_tasks.add_task(get_metrics_registry().record_order_latency, 0)
            return {
                "order_id": order.id,
                "status": order.status.value,
                "filled_quantity": order.filled_quantity,
                "average_price": order.average_fill_price,
            }
        except Exception as e:
            logger.error("Order error for user=%s: %s", user.sub, e)
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/v1/positions/{position_id}")
    async def close_position(position_id: str, user=Depends(_require_trader)):
        """Close a position. Requires: role >= 'trader'."""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        try:
            success = await trading_app.broker.close_position(position_id)
            if not success:
                raise HTTPException(status_code=404, detail="Position not found")
            logger.info("Position closed: user=%s id=%s", user.sub, position_id)
            return {"success": True, "position_id": position_id}
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error closing position: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    # Brain control endpoints
    @app.post("/api/v1/brain/pause")
    async def pause_brain(user=Depends(_require_admin)):
        """Pause trading. Requires: role >= 'admin'."""
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        trading_app.brain.pause()
        logger.info("Brain paused by user=%s", user.sub)
        return {"status": "paused"}

    @app.post("/api/v1/brain/resume")
    async def resume_brain(user=Depends(_require_admin)):
        """Resume trading. Requires: role >= 'admin'."""
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        trading_app.brain.resume()
        logger.info("Brain resumed by user=%s", user.sub)
        return {"status": "resumed"}

    @app.get("/api/v1/brain/state")
    async def get_brain_state(user=Depends(_get_current_user)):
        """Get brain state. Requires: authenticated user."""
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        return {
            "state": trading_app.brain.state.to_dict(),
            "health": trading_app.brain.get_health(),
            "decision_history_count": len(trading_app.brain.decision_history),
        }

    # Metrics and logs
    @app.get("/api/v1/metrics/json")
    async def get_metrics_json(user=Depends(_require_admin)):
        """Get metrics as JSON. Requires: role >= 'admin'."""
        registry = get_metrics_registry()
        return registry.get_all_metrics()

    @app.get("/api/v1/logs/recent")
    async def get_recent_logs(lines: int = 100, user=Depends(_require_admin)):
        """
        Return the last *lines* entries from the application log file.

        Reads from the rotating log file written by infrastructure/logging.py.
        Log directory and app name are resolved from environment variables:
            LOG_DIR   — default "logs"
            APP_NAME  — default "hopefx"

        Returns raw text lines when the file is plain-text, or parsed JSON
        objects when the file uses structured (JSON) format.  Falls back to
        an empty list with an error message when the log file is absent.
        """
        import os as _os
        import json as _json
        from pathlib import Path as _Path

        log_dir = _os.getenv("LOG_DIR", "logs")
        app_name = _os.getenv("APP_NAME", "hopefx")
        log_path = _Path(log_dir) / f"{app_name}.log"

        if not log_path.exists():
            return {
                "logs": [],
                "source": str(log_path),
                "error": f"Log file not found: {log_path}. "
                "Ensure LOG_DIR and APP_NAME env vars match the logging setup.",
            }

        try:
            # Efficient tail: read last chunk and split lines
            max_bytes = 512 * 1024  # read at most 512 KB from the end
            with open(log_path, "rb") as fh:
                fh.seek(0, 2)
                file_size = fh.tell()
                seek_pos = max(0, file_size - max_bytes)
                fh.seek(seek_pos)
                raw = fh.read().decode("utf-8", errors="replace")

            all_lines = [line for line in raw.splitlines() if line.strip()]
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines

            # Attempt JSON parse (structured logging format)
            parsed = []
            for line in tail:
                try:
                    parsed.append(_json.loads(line))
                except _json.JSONDecodeError:
                    parsed.append({"message": line})

            return {
                "logs": parsed,
                "source": str(log_path),
                "total_returned": len(parsed),
            }
        except OSError as exc:
            logger.warning("get_recent_logs: could not read %s: %s", log_path, exc)
            return {"logs": [], "source": str(log_path), "error": str(exc)}

    # System control
    @app.post("/api/v1/system/shutdown")
    async def shutdown_system(
        background_tasks: BackgroundTasks,
        user=Depends(_require_admin),
    ):
        """Shutdown the trading system. Requires: role >= 'admin'."""
        if not trading_app:
            raise HTTPException(status_code=503, detail="Trading app not available")
        logger.critical("System shutdown initiated by user=%s", user.sub)
        background_tasks.add_task(trading_app.shutdown)
        return {"status": "shutdown_initiated"}

    return app


# Standalone server starter
async def start_api_server(host: str = "0.0.0.0", port: int = 8000, trading_app=None):
    """Start API server"""
    if not FASTAPI_AVAILABLE:
        logger.error(
            "FastAPI required for API server. Install: pip install fastapi uvicorn",
        )
        return

    import uvicorn

    app = create_api_app(trading_app)
    if not app:
        return

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )

    server = uvicorn.Server(config)

    logger.info(f"API server starting on http://{host}:{port}")
    logger.info(f"  - API docs: http://{host}:{port}/docs")
    logger.info(f"  - Health:   http://{host}:{port}/health")
    logger.info(f"  - Metrics:  http://{host}:{port}/metrics")

    await server.serve()
