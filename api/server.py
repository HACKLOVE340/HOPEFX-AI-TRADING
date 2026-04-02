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
from typing import Any

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
import contextlib

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


def create_api_app(trading_app=None) -> Any | None:
    """Create FastAPI application"""
    if not FASTAPI_AVAILABLE:
        return None

    import os

    from fastapi.security import HTTPBearer
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest

    # ── Config resolved before app construction ───────────────────────────────
    _raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
    _allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

    # Hard-fail in production if ALLOWED_ORIGINS is still localhost — the
    # frontend can never reach the API from a real domain in that state.
    if os.getenv("APP_ENV") == "production" and all("localhost" in o or "127." in o for o in _allowed_origins):
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
    health_checker = get_health_checker(trading_app) if trading_app else get_health_checker()

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
                            await bus.publish(CH_TICK, {"price": price, "symbol": "XAUUSD"})
                        except Exception as _exc:
                            logger.debug("NuclearStreamer EventBus forward error: %s", _exc)

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
                "APScheduler not installed — weekly report scheduling disabled. Install: pip install apscheduler"
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
            with contextlib.suppress((TimeoutError, asyncio.CancelledError)):
                await asyncio.wait_for(_nuclear_stream_task, timeout=3.0)
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
    _configure_middleware(app, _allowed_origins, BaseHTTPMiddleware, StarletteRequest)

    # ── Auth dependencies ─────────────────────────────────────────────────────
    _bearer = HTTPBearer(auto_error=True)
    _get_current_user, _require_trader, _require_admin = _build_auth_deps(_bearer)

    # Store reference to trading app
    app.state.trading_app = trading_app

    _register_probe_routes(app, trading_app, health_checker)
    _register_trading_routes(app, trading_app, _get_current_user, _require_trader, _ALLOWED_SYMBOLS, _MAX_QTY)
    _register_brain_routes(app, trading_app, _get_current_user, _require_admin)
    _register_system_routes(app, trading_app, _require_admin)

    return app


# ── Helpers extracted from create_api_app ─────────────────────────────────────


def _configure_middleware(app, allowed_origins, BaseHTTPMiddleware, StarletteRequest):
    """Add CORS and security-headers middleware."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "PUT"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    class _SecurityHeaders(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
            return response

    app.add_middleware(_SecurityHeaders)


def _build_auth_deps(bearer):
    """Return (get_current_user, require_trader, require_admin) dependency callables."""
    _role_rank = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}

    def _get_current_user(credentials=Depends(bearer)):
        try:
            from api.auth import _decode_token

            return _decode_token(credentials.credentials)
        except Exception as exc:
            logger.warning("Token decode failed: %s", exc)
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    def _require_trader(credentials=Depends(bearer)):
        user = _get_current_user(credentials)
        if _role_rank.get(user.role, -1) < _role_rank["trader"]:
            raise HTTPException(status_code=403, detail="Role 'trader' required")
        return user

    def _require_admin(credentials=Depends(bearer)):
        user = _get_current_user(credentials)
        if _role_rank.get(user.role, -1) < _role_rank["admin"]:
            raise HTTPException(status_code=403, detail="Role 'admin' required")
        return user

    return _get_current_user, _require_trader, _require_admin


def _register_probe_routes(app, trading_app, health_checker):
    """Register /health, /ready, /live, /metrics probes."""

    @app.get("/health")
    async def health():
        health_data = await health_checker.run_all_checks()
        status_code = 503 if health_data.status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED) else 200
        return JSONResponse(content=health_data.to_dict(), status_code=status_code)

    @app.get("/ready")
    async def ready():
        if not trading_app:
            return JSONResponse(content={"ready": False}, status_code=503)
        is_ready = trading_app._components_initialized and trading_app.running
        return JSONResponse(content={"ready": is_ready}, status_code=200 if is_ready else 503)

    @app.get("/live")
    async def live():
        return {"alive": True}

    @app.get("/metrics")
    async def metrics():
        registry = get_metrics_registry()
        return PlainTextResponse(content=registry.export_prometheus(), media_type="text/plain")


def _register_trading_routes(app, trading_app, get_current_user, require_trader, allowed_symbols, max_qty):
    """Register account, position, and order endpoints."""

    @app.get("/api/v1/status")
    async def get_status(user=Depends(get_current_user)):
        if not trading_app:
            raise HTTPException(status_code=503, detail="Trading app not available")
        return trading_app.get_status()

    @app.get("/api/v1/account")
    async def get_account(user=Depends(get_current_user)):
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        try:
            return await trading_app.broker.get_account_info()
        except Exception as exc:
            logger.error("Error getting account info: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to retrieve account info — check server logs") from exc

    @app.get("/api/v1/positions")
    async def get_positions(user=Depends(get_current_user)):
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        try:
            positions = await trading_app.broker.get_positions()
            return {"positions": [p.to_dict() for p in positions], "count": len(positions)}
        except Exception as exc:
            logger.error("Error getting positions: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/v1/orders", status_code=201)
    async def place_order(
        request: TradeRequest,
        background_tasks: BackgroundTasks,
        user=Depends(require_trader),
    ):
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        symbol = request.symbol.upper().strip()
        if symbol not in allowed_symbols:
            raise HTTPException(
                status_code=400, detail=f"Symbol '{symbol}' not permitted. Allowed: {sorted(allowed_symbols)}"
            )
        if request.quantity <= 0 or request.quantity > max_qty:
            raise HTTPException(status_code=400, detail=f"Quantity must be > 0 and <= {max_qty}")
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
        except Exception as exc:
            logger.error("Order error for user=%s: %s", user.sub, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/v1/positions/{position_id}")
    async def close_position(position_id: str, user=Depends(require_trader)):
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
        except Exception as exc:
            logger.error("Error closing position: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


def _register_brain_routes(app, trading_app, get_current_user, require_admin):
    """Register brain control and state endpoints."""

    @app.post("/api/v1/brain/pause")
    async def pause_brain(user=Depends(require_admin)):
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        trading_app.brain.pause()
        logger.info("Brain paused by user=%s", user.sub)
        return {"status": "paused"}

    @app.post("/api/v1/brain/resume")
    async def resume_brain(user=Depends(require_admin)):
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        trading_app.brain.resume()
        logger.info("Brain resumed by user=%s", user.sub)
        return {"status": "resumed"}

    @app.get("/api/v1/brain/state")
    async def get_brain_state(user=Depends(get_current_user)):
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        return {
            "state": trading_app.brain.state.to_dict(),
            "health": trading_app.brain.get_health(),
            "decision_history_count": len(trading_app.brain.decision_history),
        }

    @app.get("/api/v1/metrics/json")
    async def get_metrics_json(user=Depends(require_admin)):
        return get_metrics_registry().get_all_metrics()


def _register_system_routes(app, trading_app, require_admin):
    """Register logs and system-control endpoints."""

    @app.get("/api/v1/logs/recent")
    async def get_recent_logs(lines: int = 100, user=Depends(require_admin)):
        import os as _os
        import json as _json
        from pathlib import Path as _Path

        log_dir = _os.getenv("LOG_DIR", "logs")
        app_name = _os.getenv("APP_NAME", "hopefx")
        log_path = _Path(log_dir) / f"{app_name}.log"

        if not log_path.exists():
            return {"logs": [], "source": str(log_path), "error": f"Log file not found: {log_path}"}

        try:
            max_bytes = 512 * 1024
            with open(log_path, "rb") as fh:
                fh.seek(0, 2)
                file_size = fh.tell()
                fh.seek(max(0, file_size - max_bytes))
                raw = fh.read().decode("utf-8", errors="replace")
            all_lines = [line for line in raw.splitlines() if line.strip()]
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            parsed = []
            for line in tail:
                try:
                    parsed.append(_json.loads(line))
                except _json.JSONDecodeError:
                    parsed.append({"message": line})
            return {"logs": parsed, "source": str(log_path), "total_returned": len(parsed)}
        except OSError as exc:
            logger.warning("get_recent_logs: could not read %s: %s", log_path, exc)
            return {"logs": [], "source": str(log_path), "error": str(exc)}

    @app.post("/api/v1/system/shutdown")
    async def shutdown_system(background_tasks: BackgroundTasks, user=Depends(require_admin)):
        if not trading_app:
            raise HTTPException(status_code=503, detail="Trading app not available")
        logger.critical("System shutdown initiated by user=%s", user.sub)
        background_tasks.add_task(trading_app.shutdown)
        return {"status": "shutdown_initiated"}


# Standalone server starter
async def start_api_server(host: str = "0.0.0.0", port: int = 8000, trading_app=None):  # nosec B104 - host configurable via parameter
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
