# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Mobile API v2.0 — iOS/Android REST + WebSocket endpoints.

Security fixes applied:
- CORS: wildcard origins removed; explicit allowlist from MOBILE_CORS_ORIGINS env var.
  allow_credentials=False (wildcard + credentials is rejected by all browsers per spec).
- JWT: tokens use standard 'sub' claim, not 'user_id'. Token type ('access'/'refresh')
  is embedded so refresh tokens cannot be used as access tokens.
- Risk gate: order placement is BLOCKED (not allowed) when risk check raises an
  exception. Previous code silently allowed orders on broker.check_risk() failure.
- WebSocket /ws/trades: user_id is now extracted from a verified JWT token passed
  as a query parameter, not trusted from a plain query string.
- WebSocket /ws/quotes: broker quote errors are logged, not silently swallowed.
- All bare `except Exception: pass` replaced with explicit logging.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

import bcrypt
import jwt
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────────────


class MobileUserRegistration(BaseModel):
    email: str = Field(..., pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    password: str = Field(..., min_length=8)
    username: str = Field(..., min_length=3, max_length=30)
    device_id: str
    platform: str  # ios | android

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if v.lower() not in ("ios", "android"):
            raise ValueError("platform must be 'ios' or 'android'")
        return v.lower()


class AuthToken(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


class Account(BaseModel):
    account_id: str
    username: str
    balance: float
    equity: float
    margin_used: float
    margin_available: float
    open_trades: int
    daily_pnl: float
    monthly_pnl: float
    account_status: str = "active"


class QuoteData(BaseModel):
    symbol: str
    bid: float
    ask: float
    last_update: datetime
    spread: float
    bid_volume: float = 0.0
    ask_volume: float = 0.0


class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(..., pattern="^(MARKET|LIMIT|STOP)$")
    quantity: float = Field(..., gt=0)
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str = ""


class TradeData(BaseModel):
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    quantity: float
    current_price: float
    pnl: float
    pnl_percentage: float
    entry_time: datetime
    duration_seconds: int
    spread: float = 0.0


class PerformanceData(BaseModel):
    day: str
    pnl: float
    trades: int
    win_rate: float
    max_drawdown: float


class NewsItem(BaseModel):
    id: str
    title: str
    summary: str
    source: str
    timestamp: datetime
    importance: str = "medium"
    related_symbols: list[str] = []


class NotificationPreferences(BaseModel):
    email_alerts: bool = True
    push_notifications: bool = True
    sms_alerts: bool = False
    trade_updates: bool = True
    news_updates: bool = True
    performance_reports: bool = True


# ── Mobile API server ─────────────────────────────────────────────────────────


class MobileAPIServer:
    """Production mobile API server."""

    def __init__(
        self,
        host: str = "0.0.0.0",  # nosec B104 - host configurable via parameter
        port: int = 8001,
        jwt_secret: str | None = None,
        broker=None,
        db=None,
        notification_service=None,
        cache_service=None,
        rate_limiter=None,
    ) -> None:
        resolved_secret = jwt_secret or os.getenv("SECURITY_JWT_SECRET") or os.getenv("JWT_SECRET")
        if not resolved_secret or len(resolved_secret) < 32:
            raise ValueError(
                "jwt_secret must be >= 32 characters. "
                "Set SECURITY_JWT_SECRET env var or pass jwt_secret= explicitly. "
                'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
            )

        self.app = FastAPI(
            title="HopeFX Mobile API",
            version="2.0.0",
            description="Mobile trading API",
        )
        self.host = host
        self.port = port
        self.jwt_secret = resolved_secret
        self.broker = broker
        self.db = db
        self.notification_service = notification_service
        self.cache_service = cache_service
        self.rate_limiter = rate_limiter
        self.active_connections: dict[str, list[WebSocket]] = {}

        # CORS — explicit allowlist only; wildcard + credentials is rejected by
        # browsers per the CORS spec and is a security misconfiguration.
        _raw = os.getenv("MOBILE_CORS_ORIGINS", "")
        _allowed_origins: list[str] = [o.strip() for o in _raw.split(",") if o.strip()] if _raw else []
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=_allowed_origins,
            allow_credentials=False,  # never True with a dynamic/wildcard list
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

        self._setup_routes()

    # ── Token helpers ─────────────────────────────────────────────────────────

    def _generate_access_token(self, user_id: str) -> str:
        """Short-lived access token (24 h). Uses standard 'sub' claim."""
        payload = {
            "sub": user_id,
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def _generate_refresh_token(self, user_id: str) -> str:
        """Long-lived refresh token (7 d). Distinct 'type' prevents use as access."""
        payload = {
            "sub": user_id,
            "type": "refresh",
            "exp": datetime.now(UTC) + timedelta(days=7),
            "iat": datetime.now(UTC),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def _decode_token(self, token: str, expected_type: str) -> str:
        """Decode and validate a JWT; return user_id (sub). Raises HTTPException on failure."""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from None
        except jwt.DecodeError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None

        if payload.get("type") != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Expected {expected_type} token",
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing sub claim")
        return user_id

    async def _verify_token(self, authorization: str = Header(...)) -> str:
        """FastAPI dependency: extract and verify Bearer access token."""
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid auth scheme — expected 'Bearer <token>'",
            )
        return self._decode_token(parts[1], expected_type="access")

    async def _verify_ws_token(self, token: str) -> str:
        """Verify a JWT passed as a WebSocket query parameter."""
        return self._decode_token(token, expected_type="access")

    # ── Routes ────────────────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        """Register all route groups."""
        self._register_health_routes()
        self._register_auth_routes()
        self._register_account_routes()
        self._register_trading_routes()
        self._register_performance_routes()
        self._register_news_routes()
        self._register_notification_routes()
        self._register_websocket_routes()

    # ── Health ────────────────────────────────────────────────────────────────

    def _register_health_routes(self) -> None:
        @self.app.get("/health", tags=["Health"])
        async def health_check():
            return {
                "status": "healthy",
                "timestamp": datetime.now(UTC).isoformat(),
                "version": "2.0.0",
            }

    # ── Auth ─────────────────────────────────────────────────────────────────

    def _register_auth_routes(self) -> None:
        @self.app.post("/api/v2/auth/register", response_model=AuthToken, tags=["Auth"])
        async def register(user: MobileUserRegistration):
            try:
                if self.db and self.db.user_exists(user.email):
                    raise HTTPException(status_code=409, detail="User already exists")

                salt = bcrypt.gensalt()
                password_hash = bcrypt.hashpw(user.password.encode(), salt)
                user_id = str(uuid.uuid4())

                if self.db:
                    self.db.save_user(
                        {
                            "user_id": user_id,
                            "email": user.email,
                            "username": user.username,
                            "password_hash": password_hash.decode(),
                            "device_id": user.device_id,
                            "platform": user.platform,
                            "created_at": datetime.now(UTC),
                            "notification_preferences": NotificationPreferences().model_dump(),
                        }
                    )

                logger.info("Mobile user registered: user_id=%s", user_id)
                return AuthToken(
                    access_token=self._generate_access_token(user_id),
                    refresh_token=self._generate_refresh_token(user_id),
                    expires_in=86400,
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Registration failed: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Registration failed") from None

        @self.app.post("/api/v2/auth/login", response_model=AuthToken, tags=["Auth"])
        async def login(email: str, password: str):
            try:
                if not self.db:
                    raise HTTPException(status_code=503, detail="Database unavailable")

                user = self.db.get_user_by_email(email)
                if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
                    raise HTTPException(status_code=401, detail="Invalid credentials")

                logger.info("Mobile user logged in: user_id=%s", user["user_id"])
                return AuthToken(
                    access_token=self._generate_access_token(user["user_id"]),
                    refresh_token=self._generate_refresh_token(user["user_id"]),
                    expires_in=86400,
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Login failed: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Login failed") from None

        @self.app.post("/api/v2/auth/refresh", response_model=AuthToken, tags=["Auth"])
        async def refresh_token(refresh_token: str):
            user_id = self._decode_token(refresh_token, expected_type="refresh")
            return AuthToken(
                access_token=self._generate_access_token(user_id),
                refresh_token=self._generate_refresh_token(user_id),
                expires_in=86400,
            )

    # ── Account ──────────────────────────────────────────────────────────────

    def _register_account_routes(self) -> None:
        @self.app.get("/api/v2/account", response_model=Account, tags=["Account"])
        async def get_account(user_id: str = Depends(self._verify_token)):
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                cache_key = f"account:{user_id}"
                if self.cache_service:
                    cached = self.cache_service.get(cache_key)
                    if cached:
                        return Account(**cached)

                info = await self.broker.get_account_info(user_id)
                account = Account(
                    account_id=user_id,
                    username=info.get("username", ""),
                    balance=float(info.get("balance", 0)),
                    equity=float(info.get("equity", 0)),
                    margin_used=float(info.get("margin_used", 0)),
                    margin_available=float(info.get("margin_available", 0)),
                    open_trades=int(info.get("open_trades", 0)),
                    daily_pnl=float(info.get("daily_pnl", 0)),
                    monthly_pnl=float(info.get("monthly_pnl", 0)),
                )
                if self.cache_service:
                    self.cache_service.set(cache_key, account.model_dump(), ttl=30)
                return account
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Failed to fetch account for %s: %s", user_id, exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to fetch account") from None

    # ── Trading ──────────────────────────────────────────────────────────────

    def _register_trading_routes(self) -> None:
        @self.app.get("/api/v2/quotes/{symbol}", response_model=QuoteData, tags=["Trading"])
        async def get_quote(symbol: str, user_id: str = Depends(self._verify_token)):
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                quote = await self.broker.get_quote(symbol)
                return QuoteData(
                    symbol=symbol,
                    bid=float(quote["bid"]),
                    ask=float(quote["ask"]),
                    last_update=datetime.now(UTC),
                    spread=float(quote["ask"]) - float(quote["bid"]),
                    bid_volume=float(quote.get("bid_volume", 0)),
                    ask_volume=float(quote.get("ask_volume", 0)),
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Failed to fetch quote for %s: %s", symbol, exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to fetch quote") from None

        @self.app.post("/api/v2/orders", response_model=dict[str, Any], tags=["Trading"])
        async def place_order(
            order: PlaceOrderRequest,
            background_tasks: BackgroundTasks,
            user_id: str = Depends(self._verify_token),
        ):
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                if order.order_type in ("LIMIT", "STOP") and order.price is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"price required for {order.order_type} orders",
                    )

                # Risk gate — BLOCK on exception; never allow-on-error.
                if hasattr(self.broker, "check_risk"):
                    try:
                        is_ok, reason = await self.broker.check_risk(user_id, order)
                    except Exception as risk_exc:
                        logger.error(
                            "Risk check raised exception for %s/%s: %s",
                            user_id,
                            order.symbol,
                            risk_exc,
                            exc_info=True,
                        )
                        raise HTTPException(
                            status_code=503,
                            detail="Risk service unavailable — order blocked",
                        ) from risk_exc
                    if not is_ok:
                        raise HTTPException(status_code=400, detail=f"Risk check failed: {reason}")

                result = await self.broker.place_order(
                    user_id=user_id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    quantity=order.quantity,
                    price=order.price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    comment=order.comment,
                )

                if self.notification_service:
                    background_tasks.add_task(
                        self.notification_service.send,
                        user_id=user_id,
                        title="Order Placed",
                        body=f"{order.side} {order.quantity} {order.symbol}",
                    )

                logger.info("Order placed by %s: %s", user_id, order.symbol)
                return {
                    "order_id": result.get("order_id", str(uuid.uuid4())),
                    "status": result.get("status", "pending"),
                    "entry_price": order.price or result.get("entry_price", 0),
                    "quantity": order.quantity,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Order placement failed for %s: %s", user_id, exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Order placement failed") from None

        @self.app.get("/api/v2/trades", response_model=list[TradeData], tags=["Trading"])
        async def get_open_trades(user_id: str = Depends(self._verify_token)):
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                trades = await self.broker.get_open_trades(user_id)
                return [
                    TradeData(
                        trade_id=t["trade_id"],
                        symbol=t["symbol"],
                        side=t["side"],
                        entry_price=float(t["entry_price"]),
                        quantity=float(t["quantity"]),
                        current_price=float(t["current_price"]),
                        pnl=float(t["pnl"]),
                        pnl_percentage=float(t["pnl_percentage"]),
                        entry_time=datetime.fromisoformat(t["entry_time"]),
                        duration_seconds=int(
                            (datetime.now(UTC) - datetime.fromisoformat(t["entry_time"])).total_seconds()
                        ),
                        spread=float(t.get("spread", 0)),
                    )
                    for t in trades
                ]
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Failed to fetch trades for %s: %s", user_id, exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to fetch trades") from None

        @self.app.post("/api/v2/trades/{trade_id}/close", tags=["Trading"])
        async def close_trade(
            trade_id: str,
            background_tasks: BackgroundTasks,
            user_id: str = Depends(self._verify_token),
        ):
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                result = await self.broker.close_trade(trade_id)
                if self.notification_service:
                    background_tasks.add_task(
                        self.notification_service.send,
                        user_id=user_id,
                        title="Trade Closed",
                        body=f"Trade #{trade_id} closed with P&L: {result.get('pnl', 0)}",
                    )
                return {
                    "trade_id": trade_id,
                    "status": "closed",
                    "close_price": result.get("close_price", 0),
                    "pnl": result.get("pnl", 0),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Failed to close trade %s: %s", trade_id, exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to close trade") from None

    # ── Performance ──────────────────────────────────────────────────────────

    def _register_performance_routes(self) -> None:
        @self.app.get(
            "/api/v2/performance",
            response_model=list[PerformanceData],
            tags=["Performance"],
        )
        async def get_performance(
            days: int = Query(30, ge=1, le=365),
            user_id: str = Depends(self._verify_token),
        ):
            try:
                if not self.db:
                    return []
                records = self.db.get_performance_history(user_id, days=days)
                return [PerformanceData(**r) for r in records]
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(
                    "Failed to fetch performance for %s: %s",
                    user_id,
                    exc,
                    exc_info=True,
                )
                raise HTTPException(status_code=500, detail="Failed to fetch performance") from None

    # ── News ─────────────────────────────────────────────────────────────────

    def _register_news_routes(self) -> None:
        @self.app.get("/api/v2/news", response_model=list[NewsItem], tags=["News"])
        async def get_news(
            limit: int = Query(20, ge=1, le=100),
            user_id: str = Depends(self._verify_token),
        ):
            try:
                return []
            except Exception as exc:
                logger.error("Failed to fetch news: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to fetch news") from None

    # ── Notifications ────────────────────────────────────────────────────────

    def _register_notification_routes(self) -> None:
        @self.app.get("/api/v2/notifications/preferences", tags=["Notifications"])
        async def get_notification_preferences(
            user_id: str = Depends(self._verify_token),
        ):
            try:
                if not self.db:
                    return NotificationPreferences()
                prefs = self.db.get_notification_preferences(user_id)
                return NotificationPreferences(**prefs) if prefs else NotificationPreferences()
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Failed to fetch prefs for %s: %s", user_id, exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to fetch preferences") from None

        @self.app.post("/api/v2/notifications/preferences", tags=["Notifications"])
        async def update_notification_preferences(
            preferences: NotificationPreferences,
            user_id: str = Depends(self._verify_token),
        ):
            try:
                if self.db:
                    self.db.update_notification_preferences(user_id, preferences.model_dump())
                return {"status": "updated"}
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Failed to update prefs for %s: %s", user_id, exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to update preferences") from None

    # ── WebSocket ────────────────────────────────────────────────────────────

    def _register_websocket_routes(self) -> None:
        @self.app.websocket("/api/v2/ws/quotes")
        async def websocket_quotes(
            websocket: WebSocket,
            symbols: str = Query(...),
            token: str = Query(...),
        ):
            """Real-time quote stream. Requires a valid access JWT as ?token=."""
            from rate_limiting.websocket_limiter import get_ws_limiter, get_client_ip

            limiter = get_ws_limiter()
            client_ip = get_client_ip(websocket)
            allowed, reason = await limiter.check_and_register(websocket, client_ip)
            if not allowed:
                await websocket.close(code=1008, reason=reason)
                return

            try:
                await self._verify_ws_token(token)
            except HTTPException:
                await websocket.close(code=4001)
                await limiter.release(client_ip)
                return

            await websocket.accept()
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

            try:
                while True:
                    quotes: dict[str, Any] = {}
                    for sym in symbol_list:
                        if self.broker:
                            try:
                                quote = await self.broker.get_quote(sym)
                                quotes[sym] = {
                                    "bid": float(quote["bid"]),
                                    "ask": float(quote["ask"]),
                                    "timestamp": datetime.now(UTC).isoformat(),
                                }
                            except Exception as q_exc:
                                logger.warning("Quote fetch failed for %s: %s", sym, q_exc)
                    if quotes:
                        await websocket.send_json(quotes)
                    await asyncio.sleep(0.5)
            except WebSocketDisconnect:
                logger.debug("WebSocket quotes disconnected")
            except Exception as exc:
                logger.error("WebSocket quotes error: %s", exc, exc_info=True)
                await websocket.close()
            finally:
                await limiter.release(client_ip)

        @self.app.websocket("/api/v2/ws/trades")
        async def websocket_trades(
            websocket: WebSocket,
            token: str = Query(...),
        ):
            """Real-time trade update stream. Requires a valid access JWT as ?token=.
            user_id is extracted from the verified token — never trusted from query string.
            """
            from rate_limiting.websocket_limiter import get_ws_limiter, get_client_ip

            limiter = get_ws_limiter()
            client_ip = get_client_ip(websocket)
            allowed, reason = await limiter.check_and_register(websocket, client_ip)
            if not allowed:
                await websocket.close(code=1008, reason=reason)
                return

            try:
                user_id = await self._verify_ws_token(token)
            except HTTPException:
                await websocket.close(code=4001)
                await limiter.release(client_ip)
                return

            await websocket.accept()
            self.active_connections.setdefault(user_id, []).append(websocket)

            try:
                while True:
                    data = await websocket.receive_text()
                    if data == "ping":
                        await websocket.send_text("pong")
            except WebSocketDisconnect:
                logger.debug("WebSocket trades disconnected for %s", user_id)
            except Exception as exc:
                logger.error("WebSocket trades error for %s: %s", user_id, exc, exc_info=True)
            finally:
                conns = self.active_connections.get(user_id, [])
                if websocket in conns:
                    conns.remove(websocket)
                await limiter.release(client_ip)

    def run(self, reload: bool = False) -> None:
        import uvicorn

        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info", reload=reload)


class MobileAPI:
    """
    Lightweight mobile API client.

    For production portfolio data, pass an *app_state* object that exposes
    a ``broker`` attribute with ``get_account_info()`` and ``get_positions()``
    methods.  Without app_state the portfolio endpoint returns an empty
    skeleton — callers should use the full MobileAPIServer HTTP endpoints
    instead of this client when live data is required.
    """

    def __init__(
        self,
        compression_enabled: bool = True,
        app_state: Any = None,
        **kwargs: Any,
    ) -> None:
        self.compression_enabled = compression_enabled
        self._app_state = app_state

    def get_portfolio_mobile(
        self,
        user_id: str,
        include_charts: bool = False,
        compression: bool = True,
    ) -> dict:
        """
        Return portfolio summary for *user_id*.

        Attempts to read live data from self._app_state.broker when available.
        Falls back to an empty skeleton when no broker is wired — callers
        must check ``data_source`` in the response to detect this case.
        """
        total_value = 0.0
        positions: list = []
        balance = 0.0
        data_source = "none"

        broker = getattr(self._app_state, "broker", None) if self._app_state else None
        if broker is not None:
            try:
                if hasattr(broker, "get_account_info"):
                    info = broker.get_account_info()
                    if hasattr(info, "__dict__"):
                        info = info.__dict__
                    if isinstance(info, dict):
                        balance = float(info.get("balance") or info.get("equity") or 0.0)
                        total_value = float(info.get("equity") or balance)
                    data_source = "broker"
                elif hasattr(broker, "balance"):
                    balance = float(broker.balance)
                    total_value = float(getattr(broker, "equity", balance))
                    data_source = "broker"
            except Exception as exc:
                logging.getLogger(__name__).warning("MobileAPI.get_portfolio_mobile: broker data error: %s", exc)

            try:
                if hasattr(broker, "get_positions"):
                    raw = broker.get_positions()
                    if raw:
                        positions = [p.__dict__ if hasattr(p, "__dict__") else p for p in raw]
            except Exception as exc:
                logging.getLogger(__name__).warning("MobileAPI.get_portfolio_mobile: positions error: %s", exc)

        return {
            "user_id": user_id,
            "total_value": total_value,
            "balance": balance,
            "positions": positions,
            "compression": compression,
            "charts": include_charts,
            "data_source": data_source,
        }

    def place_order_mobile(
        self,
        user_id: str,
        symbol: str,
        order_type: str,
        side: str,
        quantity: float,
        confirm_required: bool = True,
        **kwargs: Any,
    ) -> dict:
        order_id = f"{user_id}_{symbol}_{uuid.uuid4().hex[:8]}"
        return {
            "order_id": order_id,
            "user_id": user_id,
            "symbol": symbol,
            "order_type": order_type,
            "side": side,
            "quantity": quantity,
            "status": "pending" if confirm_required else "submitted",
        }


if __name__ == "__main__":
    # SECURITY_JWT_SECRET must be set in environment — no hardcoded fallback.
    api = MobileAPIServer(port=8001)
    api.run()
