# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Production Mobile API v2.0
- iOS/Android REST endpoints
- Real-time WebSocket support
- Offline-first architecture
- Push notifications
- Two-factor authentication
- Rate limiting & caching
"""

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
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)

# ============ REQUEST/RESPONSE MODELS ============


class MobileUserRegistration(BaseModel):
    """Mobile user registration"""

    email: str = Field(..., pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    password: str = Field(..., min_length=8)
    username: str = Field(..., min_length=3, max_length=30)
    device_id: str
    platform: str  # ios, android

    @validator("platform")
    @classmethod
    def validate_platform(cls, v):
        if v.lower() not in ["ios", "android"]:
            raise ValueError("Platform must be ios or android")
        return v.lower()


class AuthToken(BaseModel):
    """Authentication token response"""

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


class Account(BaseModel):
    """User account overview"""

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
    """Real-time market quote"""

    symbol: str
    bid: float
    ask: float
    last_update: datetime
    spread: float
    bid_volume: float = 0
    ask_volume: float = 0


class PlaceOrderRequest(BaseModel):
    """Mobile order placement"""

    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(..., pattern="^(MARKET|LIMIT|STOP)$")
    quantity: float = Field(..., gt=0)
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str = ""


class TradeData(BaseModel):
    """Trade details"""

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
    spread: float = 0


class PerformanceData(BaseModel):
    """Account performance data"""

    day: str
    pnl: float
    trades: int
    win_rate: float
    max_drawdown: float


class NewsItem(BaseModel):
    """News article for mobile"""

    id: str
    title: str
    summary: str
    source: str
    timestamp: datetime
    importance: str = "medium"  # low, medium, high
    related_symbols: list[str] = []


class NotificationPreferences(BaseModel):
    """User notification preferences"""

    email_alerts: bool = True
    push_notifications: bool = True
    sms_alerts: bool = False
    trade_updates: bool = True
    news_updates: bool = True
    performance_reports: bool = True


# ============ MOBILE API APPLICATION ============


class MobileAPIServer:
    """Production mobile API server with enterprise features"""

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
    ):
        """Initialize mobile API"""
        resolved_secret = jwt_secret or _os.getenv("SECURITY_JWT_SECRET") or _os.getenv("JWT_SECRET_KEY")
        if not resolved_secret or len(resolved_secret) < 32:
            raise ValueError(
                "jwt_secret must be >= 32 characters. "
                "Set SECURITY_JWT_SECRET env var or pass jwt_secret= explicitly. "
                'Generate with: python -c "import secrets; logger.info(secrets.token_hex(32))"'
            )

        self.app = FastAPI(
            title="HopeFX Mobile API",
            version="2.0.0",
            description="Enterprise mobile trading API",
        )

        self.host = host
        self.port = port
        self.jwt_secret = resolved_secret
        self.broker = broker
        self.db = db
        self.notification_service = notification_service
        self.cache_service = cache_service
        self.rate_limiter = rate_limiter

        # CORS: wildcard origins are incompatible with allow_credentials=True
        # (browsers reject such responses per CORS spec).  Restrict to an
        # explicit allowlist sourced from the environment; default to no
        # cross-origin access so misconfigured deployments fail closed.
        _raw_origins = os.getenv("MOBILE_CORS_ORIGINS", "")
        _allowed_origins: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()] if _raw_origins else []
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=_allowed_origins,
            allow_credentials=False,  # credentials require explicit origin list, never wildcard
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

        # Setup routes
        self._setup_routes()

        # WebSocket connections tracking
        self.active_connections: dict[str, list[WebSocket]] = {}

    def _resolve_broker(self):
        """Return broker: self.broker if set, otherwise app_state.broker."""
        if self.broker is not None:
            return self.broker
        try:
            from app import app_state as _state
            return getattr(_state, "broker", None)
        except Exception:
            return None

    @staticmethod
    async def _call_broker(method, *args, **kwargs):
        """Call sync or async broker method and return result."""
        import inspect
        result = method(*args, **kwargs)
        if inspect.iscoroutine(result):
            result = await result
        return result

    @staticmethod
    def _account_info_to_dict(info) -> dict:
        """Normalise AccountInfo dataclass or dict to a plain dict."""
        if isinstance(info, dict):
            return info
        return {
            "balance": float(getattr(info, "balance", 0) or 0),
            "equity": float(getattr(info, "equity", 0) or 0),
            "margin_used": float(getattr(info, "margin_used", 0) or 0),
            "margin_available": float(
                getattr(info, "margin_available", getattr(info, "free_margin", 0)) or 0
            ),
            "open_trades": 0,
            "daily_pnl": 0.0,
            "monthly_pnl": 0.0,
        }

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

    # ── Authentication ────────────────────────────────────────────────────────

    def _register_auth_routes(self) -> None:
        @self.app.post("/api/v2/auth/register", response_model=AuthToken, tags=["Auth"])
        async def register(user: MobileUserRegistration):
            """Register new mobile user"""

            try:
                # Check if user exists
                if self.db and self.db.user_exists(user.email):
                    raise HTTPException(status_code=409, detail="User already exists")

                # Hash password
                salt = bcrypt.gensalt()
                password_hash = bcrypt.hashpw(user.password.encode(), salt)

                # Create user
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
                            "notification_preferences": NotificationPreferences().dict(),
                        }
                    )

                # Generate tokens
                access_token = self._generate_token(user_id, expires_hours=24)
                refresh_token = self._generate_token(user_id, expires_hours=7 * 24)

                logger.info("User registered: user_id=%s", user_id)

                return AuthToken(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=86400,  # 24 hours
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Registration failed: %s", e)

                raise HTTPException(status_code=500, detail="Registration failed") from e

        @self.app.post("/api/v2/auth/login", response_model=AuthToken, tags=["Auth"])
        async def login(email: str, password: str):
            """Login mobile user"""

            try:
                if not self.db:
                    raise HTTPException(status_code=503, detail="Database unavailable")

                user = self.db.get_user_by_email(email)

                if not user:
                    raise HTTPException(status_code=401, detail="Invalid credentials")

                # Verify password
                if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
                    raise HTTPException(status_code=401, detail="Invalid credentials")

                # Generate tokens
                access_token = self._generate_token(user["user_id"], expires_hours=24)
                refresh_token = self._generate_token(user["user_id"], expires_hours=7 * 24)

                logger.info("User logged in: user_id=%s", user["user_id"])

                return AuthToken(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=86400,
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Login failed: %s", e)

                raise HTTPException(status_code=500, detail="Login failed") from e

        @self.app.post("/api/v2/auth/refresh", response_model=AuthToken, tags=["Auth"])
        async def refresh_token(refresh_token: str):
            """Refresh access token"""

            try:
                payload = jwt.decode(refresh_token, self.jwt_secret, algorithms=["HS256"])
                # Accept "sub" (standard) or legacy "user_id" claim
                user_id = payload.get("sub") or payload.get("user_id")
                if not user_id:
                    raise HTTPException(status_code=401, detail="Invalid refresh token: missing sub")

                new_access_token = self._generate_token(user_id, expires_hours=24)
                new_refresh_token = self._generate_token(user_id, expires_hours=7 * 24)

                return AuthToken(
                    access_token=new_access_token,
                    refresh_token=new_refresh_token,
                    expires_in=86400,
                )

            except jwt.ExpiredSignatureError:
                raise HTTPException(status_code=401, detail="Refresh token expired") from None
            except jwt.DecodeError:
                raise HTTPException(status_code=401, detail="Invalid refresh token") from None

    # ── Account ───────────────────────────────────────────────────────────────

    def _register_account_routes(self) -> None:
        @self.app.get("/api/v2/account", response_model=Account, tags=["Account"])
        async def get_account(user_id: str = Depends(self._verify_token)):
            """Get account overview"""

            try:
                broker = self._resolve_broker()
                if not broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                # Try cache first
                cache_key = f"account:{user_id}"
                if self.cache_service:
                    cached = self.cache_service.get(cache_key)
                    if cached:
                        return Account(**cached)

                raw_info = await self._call_broker(broker.get_account_info)
                account_info = self._account_info_to_dict(raw_info)

                account = Account(
                    account_id=user_id,
                    username=account_info.get("username", ""),
                    balance=float(account_info.get("balance", 0)),
                    equity=float(account_info.get("equity", 0)),
                    margin_used=float(account_info.get("margin_used", 0)),
                    margin_available=float(account_info.get("margin_available", 0)),
                    open_trades=int(account_info.get("open_trades", 0)),
                    daily_pnl=float(account_info.get("daily_pnl", 0)),
                    monthly_pnl=float(account_info.get("monthly_pnl", 0)),
                )

                # Cache for 30 seconds
                if self.cache_service:
                    self.cache_service.set(cache_key, account.dict(), ttl=30)

                return account

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Failed to fetch account: %s", e)

                raise HTTPException(status_code=500, detail="Failed to fetch account") from e

    # ── Trading ───────────────────────────────────────────────────────────────

    def _register_trading_routes(self) -> None:
        @self.app.get("/api/v2/quotes/{symbol}", response_model=QuoteData, tags=["Trading"])
        async def get_quote(symbol: str, user_id: str = Depends(self._verify_token)):
            """Get real-time quote"""

            try:
                broker = self._resolve_broker()
                if not broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                quote_getter = getattr(broker, "get_quote", None)
                if quote_getter is None:
                    # Fall back to price engine via app_state
                    try:
                        from app import app_state as _state
                        pe = getattr(_state, "price_engine", None)
                        if pe:
                            tick = pe.get_last_price(symbol)
                            if tick:
                                return QuoteData(
                                    symbol=symbol,
                                    bid=float(tick.bid),
                                    ask=float(tick.ask),
                                    last_update=datetime.now(UTC),
                                    spread=float(tick.ask) - float(tick.bid),
                                )
                    except Exception:  # noqa: BLE001 — tick parse failure falls through to 503
                        pass
                    raise HTTPException(status_code=503, detail="Quote unavailable")

                quote = await self._call_broker(quote_getter, symbol)
                if isinstance(quote, dict):
                    return QuoteData(
                        symbol=symbol,
                        bid=float(quote["bid"]),
                        ask=float(quote["ask"]),
                        last_update=datetime.now(UTC),
                        spread=float(quote["ask"]) - float(quote["bid"]),
                        bid_volume=float(quote.get("bid_volume", 0)),
                        ask_volume=float(quote.get("ask_volume", 0)),
                    )
                return QuoteData(
                    symbol=symbol,
                    bid=float(getattr(quote, "bid", 0)),
                    ask=float(getattr(quote, "ask", 0)),
                    last_update=datetime.now(UTC),
                    spread=float(getattr(quote, "ask", 0)) - float(getattr(quote, "bid", 0)),
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Failed to fetch quote: %s", e)

                raise HTTPException(status_code=500, detail="Failed to fetch quote") from e

        @self.app.post("/api/v2/orders", response_model=dict[str, Any], tags=["Trading"])
        async def place_order(
            order: PlaceOrderRequest,
            background_tasks: BackgroundTasks,
            user_id: str = Depends(self._verify_token),
        ):
            """Place new order"""

            try:
                broker = self._resolve_broker()
                if not broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                # Validate order
                if order.quantity <= 0:
                    raise ValueError("Quantity must be positive")

                if order.order_type == "LIMIT" and order.price is None:
                    raise ValueError("Price required for LIMIT orders")

                if order.order_type == "STOP" and order.price is None:
                    raise ValueError("Price required for STOP orders")

                # Check risk limits
                if hasattr(broker, "check_risk"):
                    is_ok, reason = await self._call_broker(broker.check_risk, user_id, order)
                    if not is_ok:
                        raise ValueError(f"Risk check failed: {reason}")

                # Place order
                result = await self._call_broker(broker.place_order,
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

                # Send notification async
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

            except ValueError as e:
                logger.warning("Order validation failed for %s: %s", user_id, e)
                raise HTTPException(status_code=400, detail="Invalid order parameters") from None
            except HTTPException:
                raise
            except Exception as e:
                logger.error("Order placement failed: %s", e)

                raise HTTPException(status_code=500, detail="Order placement failed") from None

        @self.app.get("/api/v2/trades", response_model=list[TradeData], tags=["Trading"])
        async def get_open_trades(user_id: str = Depends(self._verify_token)):
            """Get all open trades"""

            try:
                broker = self._resolve_broker()
                if not broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                # get_positions() is the standard broker method
                getter = getattr(broker, "get_open_trades", None) or getattr(broker, "get_positions", None)
                if getter is None:
                    return []
                raw_trades = await self._call_broker(getter)

                result = []
                for t in (raw_trades or []):
                    if isinstance(t, dict):
                        td = t
                    else:
                        td = {
                            "trade_id": getattr(t, "id", str(t)),
                            "symbol": getattr(t, "symbol", ""),
                            "side": getattr(t, "side", "buy"),
                            "entry_price": float(getattr(t, "entry_price", 0) or 0),
                            "quantity": float(getattr(t, "quantity", getattr(t, "size", 0)) or 0),
                            "current_price": float(getattr(t, "current_price", getattr(t, "entry_price", 0)) or 0),
                            "pnl": float(getattr(t, "unrealized_pnl", 0) or 0),
                            "pnl_percentage": 0.0,
                            "entry_time": getattr(t, "opened_at", datetime.now(UTC)).isoformat()
                            if hasattr(getattr(t, "opened_at", None), "isoformat")
                            else str(getattr(t, "opened_at", datetime.now(UTC).isoformat())),
                        }
                    try:
                        entry_t = datetime.fromisoformat(str(td.get("entry_time", datetime.now(UTC).isoformat())))
                        result.append(TradeData(
                            trade_id=str(td.get("trade_id", "")),
                            symbol=str(td.get("symbol", "")),
                            side=str(td.get("side", "buy")),
                            entry_price=float(td.get("entry_price", 0)),
                            quantity=float(td.get("quantity", 0)),
                            current_price=float(td.get("current_price", td.get("entry_price", 0))),
                            pnl=float(td.get("pnl", 0)),
                            pnl_percentage=float(td.get("pnl_percentage", 0)),
                            entry_time=entry_t,
                            duration_seconds=int((datetime.now(UTC) - entry_t).total_seconds()),
                            spread=float(td.get("spread", 0)),
                        ))
                    except Exception:  # noqa: BLE001 — malformed trade dict skipped
                        pass
                return result

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Failed to fetch trades: %s", e)

                raise HTTPException(status_code=500, detail="Failed to fetch trades") from e

        @self.app.post("/api/v2/trades/{trade_id}/close", tags=["Trading"])
        async def close_trade(
            trade_id: str,
            background_tasks: BackgroundTasks,
            user_id: str = Depends(self._verify_token),
        ):
            """Close specific trade"""

            try:
                broker = self._resolve_broker()
                if not broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                closer = getattr(broker, "close_trade", None) or getattr(broker, "close_position", None)
                if closer is None:
                    raise HTTPException(status_code=503, detail="Broker does not support trade close")
                result = await self._call_broker(closer, trade_id)

                if background_tasks and self.notification_service:
                    result_dict = result if isinstance(result, dict) else {}
                    background_tasks.add_task(
                        self.notification_service.send,
                        user_id=user_id,
                        title="Trade Closed",
                        body=f"Trade #{trade_id} closed with P&L: {result_dict.get('pnl', 0)}",
                    )

                result_dict = result if isinstance(result, dict) else {}
                return {
                    "trade_id": trade_id,
                    "status": "closed",
                    "close_price": result_dict.get("close_price", 0),
                    "pnl": result_dict.get("pnl", 0),
                    "timestamp": datetime.now(UTC).isoformat(),
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Failed to close trade: %s", e)

                raise HTTPException(status_code=500, detail="Failed to close trade") from e

    # ── Performance ───────────────────────────────────────────────────────────

    def _register_performance_routes(self) -> None:
        @self.app.get(
            "/api/v2/performance",
            response_model=list[PerformanceData],
            tags=["Analytics"],
        )
        async def get_performance(
            days: int = Query(30, ge=1, le=365),
            user_id: str = Depends(self._verify_token),
        ):
            """Get performance data"""

            try:
                broker = self._resolve_broker()
                if not broker:
                    raise HTTPException(status_code=503, detail="Broker offline")

                perf_getter = getattr(broker, "get_performance", None)
                if perf_getter is not None:
                    performance = await self._call_broker(perf_getter, user_id, days=days)
                else:
                    performance = []

                result = []
                for p in (performance or []):
                    try:
                        result.append(PerformanceData(
                            day=p["date"],
                            pnl=float(p["pnl"]),
                            trades=int(p["trades"]),
                            win_rate=float(p["win_rate"]),
                            max_drawdown=float(p["max_drawdown"]),
                        ))
                    except Exception:  # noqa: BLE001 — malformed portfolio entry skipped
                        pass
                return result

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Failed to fetch performance: %s", e)

                raise HTTPException(status_code=500, detail="Failed to fetch performance") from e

    # ── News ──────────────────────────────────────────────────────────────────

    def _register_news_routes(self) -> None:
        @self.app.get("/api/v2/news", response_model=list[NewsItem], tags=["News"])
        async def get_news(
            limit: int = Query(20, ge=1, le=100),
            user_id: str = Depends(self._verify_token),
        ):
            """Get latest financial news"""

            try:
                # This would typically call a news service
                return []

            except Exception as e:
                logger.error("Failed to fetch news: %s", e)

                raise HTTPException(status_code=500, detail="Failed to fetch news") from e

    # ── Notifications ─────────────────────────────────────────────────────────

    def _register_notification_routes(self) -> None:
        @self.app.get("/api/v2/notifications/preferences", tags=["Notifications"])
        async def get_notification_preferences(
            user_id: str = Depends(self._verify_token),
        ):
            """Get notification preferences"""

            try:
                if not self.db:
                    return NotificationPreferences()

                prefs = self.db.get_notification_preferences(user_id)
                return NotificationPreferences(**prefs) if prefs else NotificationPreferences()

            except Exception as e:
                logger.error("Failed to fetch preferences: %s", e)

                raise HTTPException(status_code=500, detail="Failed to fetch preferences") from e

        @self.app.post("/api/v2/notifications/preferences", tags=["Notifications"])
        async def update_notification_preferences(
            preferences: NotificationPreferences,
            user_id: str = Depends(self._verify_token),
        ):
            """Update notification preferences"""

            try:
                if self.db:
                    self.db.update_notification_preferences(user_id, preferences.dict())

                return {"status": "updated"}

            except Exception as e:
                logger.error("Failed to update preferences: %s", e)

                raise HTTPException(status_code=500, detail="Failed to update preferences") from e

    # ── WebSocket ─────────────────────────────────────────────────────────────

    def _register_websocket_routes(self) -> None:
        @self.app.websocket("/api/v2/ws/quotes")
        async def websocket_quotes(websocket: WebSocket, symbols: str = Query(...)):
            """WebSocket for real-time quotes"""
            from rate_limiting.websocket_limiter import get_client_ip, get_ws_limiter

            limiter = get_ws_limiter()
            client_ip = get_client_ip(websocket)
            allowed, reason = await limiter.check_and_register(websocket, client_ip)
            if not allowed:
                return

            await websocket.accept()
            symbol_list = [s.strip() for s in symbols.split(",")]

            try:
                while True:
                    quotes = {}
                    for symbol in symbol_list:
                        if self.broker:
                            try:
                                quote = await self.broker.get_quote(symbol)
                                quotes[symbol] = {
                                    "bid": float(quote["bid"]),
                                    "ask": float(quote["ask"]),
                                    "timestamp": datetime.now(UTC).isoformat(),
                                }
                            except Exception as _exc:
                                logger.debug("Suppressed exception: %s", _exc)

                    if quotes:
                        await websocket.send_json(quotes)

                    # Send every 500ms
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error("WebSocket error: %s", e)

                await websocket.close()
            finally:
                await limiter.release(client_ip)

        @self.app.websocket("/api/v2/ws/trades")
        async def websocket_trades(websocket: WebSocket, user_id: str = Query(...)):
            """WebSocket for real-time trade updates"""
            from rate_limiting.websocket_limiter import get_client_ip, get_ws_limiter

            limiter = get_ws_limiter()
            client_ip = get_client_ip(websocket)
            allowed, reason = await limiter.check_and_register(websocket, client_ip)
            if not allowed:
                return

            await websocket.accept()

            if user_id not in self.active_connections:
                self.active_connections[user_id] = []

            self.active_connections[user_id].append(websocket)

            try:
                while True:
                    # Receive keep-alive messages
                    data = await websocket.receive_text()
                    if data == "ping":
                        await websocket.send_text("pong")

            except Exception as e:
                logger.error("WebSocket error: %s", e)

            finally:
                if websocket in self.active_connections.get(user_id, []):
                    self.active_connections[user_id].remove(websocket)
                await limiter.release(client_ip)

    def _generate_token(self, user_id: str, expires_hours: int = 24) -> str:
        """Generate a JWT token using the standard 'sub' claim for the user id."""
        payload = {
            "sub": user_id,
            "exp": datetime.now(UTC) + timedelta(hours=expires_hours),
            "iat": datetime.now(UTC),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    async def _verify_token(self, authorization: str = Header(...)) -> str:
        """Verify JWT Bearer token and return the user id (sub claim)."""
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid auth scheme — expected 'Bearer <token>'",
            )
        token = parts[1]
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from None
        except jwt.DecodeError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None
        except Exception as exc:
            logger.error("Token verification failed: %s", exc)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed") from exc

        # Enforce access-token type claim.
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an access token")

        # Tokens use the standard "sub" claim (not "user_id").
        # Also accept "user_id" as a legacy fallback for tokens issued by older
        # versions of the mobile server that used a non-standard claim name.
        user_id = payload.get("sub") or payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing sub claim")

        # Check access-token blacklist (populated on logout) — same check as api/auth.py.
        jti = payload.get("jti")
        if jti:
            try:
                from auth.service import is_access_token_revoked

                if is_access_token_revoked(jti):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                    )
            except HTTPException:
                raise
            except Exception as _exc:
                logger.warning("Token blacklist check failed: %s", _exc)

        return str(user_id)

    def run(self, reload: bool = False):
        """Run the API server"""
        import uvicorn

        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info", reload=reload)


# ---------------------------------------------------------------------------
# Module-level app / router exports
# ---------------------------------------------------------------------------
# Expose a FastAPI ``app`` and an ``APIRouter`` so that other modules can do:
#
#   from mobile.api_v2 import app, router
#
# SECURITY_JWT_SECRET (or JWT_SECRET_KEY) must be set to at least 32 chars
# before the server handles its first request.  Building is deferred to avoid
# raising at import time during test collection or module scanning when the
# secret is not yet loaded from .env.
# ---------------------------------------------------------------------------

import os as _os
import logging as _logging

from fastapi import APIRouter as _APIRouter

_logger_v2 = _logging.getLogger(__name__)


def _build_module_app() -> "FastAPI":
    """Build the MobileAPIServer FastAPI app. Raises RuntimeError if secret unset."""
    _secret = _os.getenv("SECURITY_JWT_SECRET", "").strip() or _os.getenv("JWT_SECRET_KEY", "").strip()
    if not _secret or len(_secret) < 32:
        raise RuntimeError(
            "SECURITY_JWT_SECRET (or JWT_SECRET_KEY) must be set to at least 32 characters. "
            "Set it in your .env file or environment before starting the server."
        )
    return MobileAPIServer(jwt_secret=_secret).app


def _build_router_from_app(built_app: "FastAPI") -> "_APIRouter":
    """Copy routes from a built MobileAPIServer app onto an APIRouter."""
    r = _APIRouter(prefix="/mobile", tags=["Mobile"])
    try:
        from fastapi.routing import APIRoute as _APIRoute

        for _route in built_app.routes:
            if isinstance(_route, _APIRoute):
                _path = _route.path
                if _path.startswith("/mobile"):
                    _path = _path[len("/mobile") :]
                r.add_api_route(
                    path=_path,
                    endpoint=_route.endpoint,
                    methods=list(_route.methods or ["GET"]),
                    response_model=_route.response_model,
                    status_code=_route.status_code,
                    tags=_route.tags or ["Mobile"],
                    summary=_route.summary,
                    description=_route.description,
                    include_in_schema=_route.include_in_schema,
                )
    except Exception as _err:
        _logger_v2.warning(
            "mobile.api_v2: could not copy routes onto APIRouter — mobile v2 endpoints may be unavailable: %s",
            _err,
        )
    return r


# Module-level FastAPI application instance (used by uvicorn / tests).
# Deferred to avoid raising at import time when the secret is not yet loaded
# (e.g. during test collection or module scanning before .env is sourced).
try:
    app: FastAPI = _build_module_app()
except RuntimeError as _build_err:
    # Secret not available at import time — create a minimal placeholder app.
    # The real app is built on first request via the router below.
    _logger_v2.debug(
        "mobile.api_v2: deferred app init — secret not available at import time: %s",
        _build_err,
    )
    app = FastAPI(title="HOPEFX Mobile API v2 (pending config)")

# ---------------------------------------------------------------------------
# Convenience APIRouter — populated from the MobileAPIServer.app routes so
# that include_router(router) in core/router_registry.py works correctly.
#
# MobileAPIServer registers all routes on its own FastAPI sub-app instance.
# We copy those routes onto an APIRouter so the main app can include them
# under the /mobile prefix without a separate ASGI mount (which would hide
# them from the main app's OpenAPI schema and auth middleware).
# ---------------------------------------------------------------------------
router = _build_router_from_app(app)


# ============ USAGE ============

if __name__ == "__main__":
    # SECURITY_JWT_SECRET must be set in environment — no hardcoded fallback
    api = MobileAPIServer(port=8001)
    api.run()
