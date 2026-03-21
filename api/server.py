"""
HOPEFX API Server
FastAPI application with logging, health checks, and metrics
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, PlainTextResponse
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logging.warning("FastAPI not available, API server disabled")

from infrastructure.health import HealthChecker, HealthStatus, get_health_checker
from infrastructure.metrics import get_metrics_registry
from infrastructure.logging import get_logger

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
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    app = FastAPI(
        title="HOPEFX Trading API",
        description="Production trading system API",
        version="2.1.0",
        # Disable docs in production
        docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
        redoc_url=None if os.getenv("APP_ENV") == "production" else "/redoc",
    )

    # CORS — restrict to configured origins, never wildcard in production
    _raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
    _allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "PUT"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # Security headers middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # Auth dependency
    _bearer = HTTPBearer(auto_error=True)

    def _get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
        try:
            from api.auth import _decode_token
            return _decode_token(credentials.credentials)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token",
                                headers={"WWW-Authenticate": "Bearer"})

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

    # Input validation helpers
    _ALLOWED_SYMBOLS = frozenset(
        os.getenv("ALLOWED_SYMBOLS", "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,AUDUSD,USDCHF").split(",")
    )
    _MAX_QTY = float(os.getenv("MAX_ORDER_QUANTITY", "100.0"))
    
    # Store reference to trading app
    app.state.trading_app = trading_app
    
    # Initialize health checker
    if trading_app:
        health_checker = get_health_checker(trading_app)
    else:
        health_checker = get_health_checker()
    
    @app.on_event("startup")
    async def startup():
        logger.info("API server starting...")
        # Start background health monitoring
        if trading_app:
            asyncio.create_task(health_checker.start_monitoring())
    
    @app.on_event("shutdown")
    async def shutdown():
        logger.info("API server shutting down...")
        health_checker.stop_monitoring()
    
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
        
        return JSONResponse(
            content=health_data.to_dict(),
            status_code=status_code
        )
    
    @app.get("/ready")
    async def ready():
        """Readiness probe"""
        if not trading_app:
            return {"ready": False}
        
        ready = (
            trading_app._components_initialized and
            trading_app.running
        )
        return JSONResponse(
            content={"ready": ready},
            status_code=200 if ready else 503
        )
    
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
            media_type="text/plain"
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
            return {"positions": [p.to_dict() for p in positions], "count": len(positions)}
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
            raise HTTPException(status_code=400,
                                detail=f"Symbol '{symbol}' not permitted. Allowed: {sorted(_ALLOWED_SYMBOLS)}")

        # Server-side quantity validation
        if request.quantity <= 0 or request.quantity > _MAX_QTY:
            raise HTTPException(status_code=400,
                                detail=f"Quantity must be > 0 and <= {_MAX_QTY}")

        # Side validation
        if request.side.lower() not in ("buy", "sell"):
            raise HTTPException(status_code=400, detail="side must be 'buy' or 'sell'")

        try:
            order = await trading_app.broker.place_market_order(
                symbol=symbol,
                side=request.side.lower(),
                quantity=request.quantity,
            )
            logger.info("Order placed: user=%s symbol=%s side=%s qty=%s id=%s",
                        user.sub, symbol, request.side, request.quantity, order.id)
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
        """Get recent log entries. Requires: role >= 'admin'."""
        return {"logs": [], "note": "Implement log retrieval from file or ELK"}

    # System control
    @app.post("/api/v1/system/shutdown")
    async def shutdown_system(background_tasks: BackgroundTasks, user=Depends(_require_admin)):
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
        logger.error("FastAPI required for API server. Install: pip install fastapi uvicorn")
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
        access_log=True
    )
    
    server = uvicorn.Server(config)
    
    logger.info(f"API server starting on http://{host}:{port}")
    logger.info(f"  - API docs: http://{host}:{port}/docs")
    logger.info(f"  - Health:   http://{host}:{port}/health")
    logger.info(f"  - Metrics:  http://{host}:{port}/metrics")
    
    await server.serve()
