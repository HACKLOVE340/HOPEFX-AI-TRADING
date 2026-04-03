# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# api/gateway.py
"""
HOPEFX API Gateway
Secure external interface for clients and integrations.

Usage
-----
Standalone (SSL on port 8443)::

    from api.gateway import APIGateway
    gw = APIGateway(mcc, orchestra, pms, auth_secret=os.environ["SECURITY_JWT_SECRET"])
    gw.run()

Mounted inside the main FastAPI app (app.py)::

    from api.gateway import build_gateway_app
    gateway_app = build_gateway_app()
    if gateway_app is not None:
        app.mount("/gateway", gateway_app)

The gateway adds Redis-backed rate limiting, GZip compression, and routes all
order requests through the main app's TradeExecutor so pre-trade risk checks
(PreTradeGate, drawdown limits, position sizing) are always enforced.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
UTC = timezone.utc

import jwt
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

try:
    import redis as _redis_lib

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class APIGateway:
    """
    Secure API gateway with authentication, rate limiting, and request routing.
    """

    def __init__(self, mcc, orchestra, pms, auth_secret: str):
        self.mcc = mcc
        self.orchestra = orchestra
        self.pms = pms
        self.auth_secret = auth_secret
        self.app = FastAPI(
            title="HOPEFX Ultimate API",
            version="3.0",
            docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
            redoc_url=None if os.getenv("APP_ENV") == "production" else "/redoc",
        )

        # Security
        self.security = HTTPBearer()
        self.rate_limits: dict[str, dict] = {}  # in-process fallback only

        # Redis client for distributed rate limiting (optional)
        self._redis_client = None
        if _REDIS_AVAILABLE:
            try:
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                self._redis_client = _redis_lib.from_url(
                    redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                self._redis_client.ping()
            except Exception as exc:
                logger.warning(
                    "Gateway Redis unavailable, degrading to in-process rate limiter: %s",
                    exc,
                )
                self._redis_client = None  # degrade to in-process fallback

        # Middleware
        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self):
        """Add middleware layers"""
        # CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://hopefx.com", "https://app.hopefx.com"],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

        # Compression
        self.app.add_middleware(GZipMiddleware, minimum_size=1000)

        # Rate limiting — Redis-backed sliding window (falls back to in-process counter)
        _RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "1000"))
        _WINDOW = 60  # seconds

        @self.app.middleware("http")
        async def rate_limit(request, call_next):
            client_ip = request.client.host if request.client else "unknown"
            key = f"rl:{client_ip}"

            remaining = _RATE_LIMIT - 1  # default if Redis unavailable

            # Try Redis sliding window (INCR + EXPIRE is atomic enough for rate limiting)
            if self._redis_client is not None:
                try:
                    pipe = self._redis_client.pipeline()
                    pipe.incr(key)
                    pipe.expire(key, _WINDOW)
                    count, _ = pipe.execute()
                    remaining = max(0, _RATE_LIMIT - count)
                    if count > _RATE_LIMIT:
                        from fastapi.responses import JSONResponse

                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Rate limit exceeded"},
                            headers={
                                "X-RateLimit-Limit": str(_RATE_LIMIT),
                                "X-RateLimit-Remaining": "0",
                                "Retry-After": str(_WINDOW),
                            },
                        )
                except Exception as exc:
                    logger.debug(
                        "Gateway Redis rate-limit check failed, degrading gracefully: %s",
                        exc,
                    )
            else:
                # In-process fallback (single-worker only)
                now = datetime.now(UTC)
                limit = self.rate_limits.get(client_ip, {"count": 0, "reset_time": now})
                if (now - limit["reset_time"]).total_seconds() > _WINDOW:
                    limit = {"count": 0, "reset_time": now}
                limit["count"] += 1
                self.rate_limits[client_ip] = limit
                remaining = max(0, _RATE_LIMIT - limit["count"])
                if limit["count"] > _RATE_LIMIT:
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded"},
                        headers={"Retry-After": str(_WINDOW)},
                    )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response

    def _setup_info_routes(self) -> None:
        """Register health, status, and portfolio read routes."""

        @self.app.get("/health")
        async def health():
            return {
                "status": "healthy",
                "timestamp": datetime.now(UTC).isoformat(),
                "version": "3.0",
                "components": {
                    "mcc": self.mcc.health if hasattr(self.mcc, "health") else "unknown",
                    "orchestra": len(self.orchestra.active_strategies),
                    "portfolio": self.pms.get_portfolio_summary(),
                },
            }

        # System status
        @self.app.get("/api/v1/status")
        async def status(credentials: HTTPAuthorizationCredentials = Depends(self.security)):
            self._verify_token(credentials.credentials)
            return {
                "system": self.mcc.get_status() if hasattr(self.mcc, "get_status") else {},
                "orchestra": self.orchestra.get_heatmap_data(),
                "portfolio": self.pms.get_portfolio_summary(),
                "timestamp": datetime.now(UTC).isoformat(),
            }

            return {
                "system": self.mcc.get_status() if hasattr(self.mcc, "get_status") else {},
                "orchestra": self.orchestra.get_heatmap_data(),
                "portfolio": self.pms.get_portfolio_summary(),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def _setup_strategy_routes(self) -> None:
        """Register strategy control routes."""

        @self.app.post("/api/v1/strategies/{strategy_id}/activate")
        async def activate_strategy(
            strategy_id: str, credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            self._verify_token(credentials.credentials, required_role="admin")
            self.orchestra.activate_strategy(strategy_id)
            return {"success": True, "strategy_id": strategy_id, "action": "activated"}

        @self.app.post("/api/v1/strategies/{strategy_id}/deactivate")
        async def deactivate_strategy(
            strategy_id: str,
            reason: str = "api_request",
            credentials: HTTPAuthorizationCredentials = Depends(self.security),
        ):
            self._verify_token(credentials.credentials, required_role="admin")
            self.orchestra.deactivate_strategy(strategy_id, reason)
            return {"success": True, "strategy_id": strategy_id, "action": "deactivated"}

        @self.app.post("/api/v1/emergency/kill-switch")
        async def trigger_kill_switch(reason: str, credentials: HTTPAuthorizationCredentials = Depends(self.security)):
            self._verify_token(credentials.credentials, required_role="superadmin")
            if hasattr(self.mcc, "_trigger_kill_switch"):
                self.mcc._trigger_kill_switch(f"API: {reason}")
            return {"success": True, "action": "kill_switch_triggered", "reason": reason}

    def _setup_order_routes(self) -> None:
        """Register order management routes."""

        @self.app.post("/api/v1/orders")
        async def create_order(order: dict, credentials: HTTPAuthorizationCredentials = Depends(self.security)):
            self._verify_token(credentials.credentials, required_role="trader")
            symbol = order.get("symbol", "").strip().upper()
            action = order.get("action", order.get("side", "")).strip().lower()
            quantity = float(order.get("quantity", order.get("size", 0)))
            if not symbol:
                raise HTTPException(status_code=400, detail="symbol is required")
            if action not in ("buy", "sell", "close"):
                raise HTTPException(status_code=400, detail=f"action must be buy | sell | close, got {action!r}")
            if quantity <= 0:
                raise HTTPException(status_code=400, detail=f"quantity must be > 0, got {quantity}")
            try:
                from app import app_state

                trade_executor = getattr(app_state, "trade_executor", None)
                if trade_executor is None:
                    raise HTTPException(
                        status_code=503, detail="TradeExecutor not initialised — server is still starting up"
                    )
                signal = {
                    "symbol": symbol,
                    "action": action,
                    "size": quantity,
                    "price": order.get("price"),
                    "stop_loss": order.get("stop_loss"),
                    "take_profit": order.get("take_profit"),
                    "strategy_id": order.get("strategy_id", "gateway_api"),
                    "position_id": order.get("position_id"),
                }
                result = await trade_executor.execute_signal(signal)
                return {
                    "success": result.success,
                    "order_id": result.order_id,
                    "status": result.status.value,
                    "filled_quantity": result.filled_quantity,
                    "average_price": result.average_price,
                    "commission": result.commission,
                    "latency_ms": result.latency_ms,
                    "message": result.message,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            except HTTPException:
                raise
            except Exception:
                logger.exception("Gateway order execution error: %s")
                raise HTTPException(
                    status_code=500,
                    detail="Order execution failed — check server logs",
                ) from None

    def _setup_ws_routes(self) -> None:
        """Register WebSocket streaming route."""

        @self.app.websocket("/ws/v1/stream")
        async def websocket_stream(websocket: WebSocket):
            from rate_limiting.websocket_limiter import get_client_ip, get_ws_limiter

            limiter = get_ws_limiter()
            client_ip = get_client_ip(websocket)
            allowed, reason = await limiter.check_and_register(websocket, client_ip)
            if not allowed:
                await websocket.close(code=1008, reason=reason)
                return
            token = websocket.query_params.get("token")
            if not token or not self._verify_token(token, raise_exception=False):
                await websocket.close(code=4001, reason="Unauthorized")
                await limiter.release(client_ip)
                return
            await websocket.accept()
            try:
                while True:
                    data = {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "portfolio": self.pms.get_portfolio_summary(),
                        "heatmap": self.orchestra.get_heatmap_data(),
                    }
                    await websocket.send_json(data)
                    await asyncio.sleep(1)
            except Exception as e:
                logger.debug("WebSocket stream error: %s", e)
            finally:
                await limiter.release(client_ip)

    def _setup_routes(self):
        """Setup API routes."""
        self._setup_info_routes()
        self._setup_strategy_routes()
        self._setup_order_routes()
        self._setup_ws_routes()

    def _verify_token(
        self,
        token: str,
        required_role: str = "user",
        raise_exception: bool = True,
    ) -> bool:
        """Verify JWT token"""
        try:
            payload = jwt.decode(token, self.auth_secret, algorithms=["HS256"])

            # Check role
            user_role = payload.get("role", "user")
            role_hierarchy = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}

            if role_hierarchy.get(user_role, 0) < role_hierarchy.get(required_role, 0):
                if raise_exception:
                    raise HTTPException(
                        status_code=403,
                        detail="Insufficient permissions",
                    )
                return False

            return True

        except jwt.ExpiredSignatureError:
            if raise_exception:
                raise HTTPException(status_code=401, detail="Token expired") from None
            return False
        except jwt.InvalidTokenError:
            if raise_exception:
                raise HTTPException(status_code=401, detail="Invalid token") from None
            return False

    def generate_token(self, user_id: str, role: str, expires_hours: int = 24) -> str:
        """Generate JWT token for client"""
        from datetime import timedelta

        payload = {
            "user_id": user_id,
            "role": role,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=expires_hours),
        }

        return jwt.encode(payload, self.auth_secret, algorithm="HS256")

    def run(self, host: str = "0.0.0.0", port: int = 8443):  # nosec B104 - host configurable via parameter
        """Run with SSL/TLS"""
        import uvicorn

        # SSL configuration
        ssl_keyfile = "certs/server.key"
        ssl_certfile = "certs/server.crt"

        uvicorn.run(
            self.app,
            host=host,
            port=port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            workers=4,
        )


def build_gateway_app():
    """
    Build and return the gateway FastAPI sub-application for mounting.

    Returns None when required dependencies (mcc, orchestra, pms) are not
    available in app_state, so callers can skip mounting gracefully.

    Example — mount in app.py::

        from api.gateway import build_gateway_app
        _gw = build_gateway_app()
        if _gw is not None:
            app.mount("/gateway", _gw)
    """
    try:
        from app import app_state

        mcc = getattr(app_state, "mcc", None)
        orchestra = getattr(app_state, "orchestra", None)
        pms = getattr(app_state, "portfolio_manager", None)
        auth_secret = os.getenv("SECURITY_JWT_SECRET") or os.getenv("JWT_SECRET_KEY", "")

        if not auth_secret or len(auth_secret) < 32:
            logger.warning(
                "build_gateway_app: SECURITY_JWT_SECRET not set or too short — "
                "gateway not mounted. Set SECURITY_JWT_SECRET (>=32 chars)."
            )
            return None

        if mcc is None or orchestra is None or pms is None:
            logger.info(
                "build_gateway_app: mcc/orchestra/pms not yet in app_state — "
                "gateway not mounted (call after startup_event completes)."
            )
            return None

        gw = APIGateway(mcc=mcc, orchestra=orchestra, pms=pms, auth_secret=auth_secret)
        logger.info("APIGateway built — mount at /gateway to activate")
        return gw.app

    except Exception as exc:
        logger.warning("build_gateway_app failed (non-fatal): %s", exc)
        return None
