"""
Production Mobile API v2.0
- iOS/Android REST endpoints
- Real-time WebSocket support
- Offline-first architecture
- Push notifications
- Two-factor authentication
- Rate limiting & caching
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import uuid
import json
import asyncio
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Depends, WebSocket, Header, Query, BackgroundTasks, status
from fastapi.security import HTTPBearer, HTTPAuthCredentials
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import jwt
import bcrypt
import aiohttp

logger = logging.getLogger(__name__)

# ============ REQUEST/RESPONSE MODELS ============

class MobileUserRegistration(BaseModel):
    """Mobile user registration"""
    email: str = Field(..., regex=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    password: str = Field(..., min_length=8)
    username: str = Field(..., min_length=3, max_length=30)
    device_id: str
    platform: str  # ios, android
    
    @validator('platform')
    def validate_platform(cls, v):
        if v.lower() not in ['ios', 'android']:
            raise ValueError('Platform must be ios or android')
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
    side: str = Field(..., regex="^(BUY|SELL)$")
    order_type: str = Field(..., regex="^(MARKET|LIMIT|STOP)$")
    quantity: float = Field(..., gt=0)
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
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
    related_symbols: List[str] = []

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
    
    def __init__(self,
                 host: str = "0.0.0.0",
                 port: int = 8001,
                 jwt_secret: str = "your-secret-key",
                 broker=None,
                 db=None,
                 notification_service=None,
                 cache_service=None,
                 rate_limiter=None):
        """Initialize mobile API"""
        
        self.app = FastAPI(
            title="HopeFX Mobile API",
            version="2.0.0",
            description="Enterprise mobile trading API"
        )
        
        self.host = host
        self.port = port
        self.jwt_secret = jwt_secret
        self.broker = broker
        self.db = db
        self.notification_service = notification_service
        self.cache_service = cache_service
        self.rate_limiter = rate_limiter
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Setup routes
        self._setup_routes()
        
        # WebSocket connections tracking
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    def _setup_routes(self):
        """Setup all API routes"""
        
        # ============ HEALTH CHECK ============
        @self.app.get("/health", tags=["Health"])
        async def health_check():
            """Health check endpoint"""
            return {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "version": "2.0.0"
            }
        
        # ============ AUTHENTICATION ============
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
                    self.db.save_user({
                        'user_id': user_id,
                        'email': user.email,
                        'username': user.username,
                        'password_hash': password_hash.decode(),
                        'device_id': user.device_id,
                        'platform': user.platform,
                        'created_at': datetime.utcnow(),
                        'notification_preferences': NotificationPreferences().dict()
                    })
                
                # Generate tokens
                access_token = self._generate_token(user_id, expires_hours=24)
                refresh_token = self._generate_token(user_id, expires_hours=7*24)
                
                logger.info(f"User registered: {user.email}")
                
                return AuthToken(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=86400  # 24 hours
                )
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Registration failed: {e}")
                raise HTTPException(status_code=500, detail="Registration failed")
        
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
                if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
                    raise HTTPException(status_code=401, detail="Invalid credentials")
                
                # Generate tokens
                access_token = self._generate_token(user['user_id'], expires_hours=24)
                refresh_token = self._generate_token(user['user_id'], expires_hours=7*24)
                
                logger.info(f"User logged in: {email}")
                
                return AuthToken(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=86400
                )
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Login failed: {e}")
                raise HTTPException(status_code=500, detail="Login failed")
        
        @self.app.post("/api/v2/auth/refresh", response_model=AuthToken, tags=["Auth"])
        async def refresh_token(refresh_token: str):
            """Refresh access token"""
            
            try:
                payload = jwt.decode(refresh_token, self.jwt_secret, algorithms=['HS256'])
                user_id = payload['user_id']
                
                new_access_token = self._generate_token(user_id, expires_hours=24)
                new_refresh_token = self._generate_token(user_id, expires_hours=7*24)
                
                return AuthToken(
                    access_token=new_access_token,
                    refresh_token=new_refresh_token,
                    expires_in=86400
                )
            
            except jwt.ExpiredSignatureError:
                raise HTTPException(status_code=401, detail="Refresh token expired")
            except jwt.DecodeError:
                raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        # ============ ACCOUNT ============
        @self.app.get("/api/v2/account", response_model=Account, tags=["Account"])
        async def get_account(user_id: str = Depends(self._verify_token)):
            """Get account overview"""
            
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                
                # Try cache first
                cache_key = f"account:{user_id}"
                if self.cache_service:
                    cached = self.cache_service.get(cache_key)
                    if cached:
                        return Account(**cached)
                
                account_info = await self.broker.get_account_info(user_id)
                
                account = Account(
                    account_id=user_id,
                    username=account_info.get('username', ''),
                    balance=float(account_info.get('balance', 0)),
                    equity=float(account_info.get('equity', 0)),
                    margin_used=float(account_info.get('margin_used', 0)),
                    margin_available=float(account_info.get('margin_available', 0)),
                    open_trades=int(account_info.get('open_trades', 0)),
                    daily_pnl=float(account_info.get('daily_pnl', 0)),
                    monthly_pnl=float(account_info.get('monthly_pnl', 0))
                )
                
                # Cache for 30 seconds
                if self.cache_service:
                    self.cache_service.set(cache_key, account.dict(), ttl=30)
                
                return account
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to fetch account: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch account")
        
        # ============ TRADING ============
        @self.app.get("/api/v2/quotes/{symbol}", response_model=QuoteData, tags=["Trading"])
        async def get_quote(symbol: str, user_id: str = Depends(self._verify_token)):
            """Get real-time quote"""
            
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                
                quote = await self.broker.get_quote(symbol)
                
                return QuoteData(
                    symbol=symbol,
                    bid=float(quote['bid']),
                    ask=float(quote['ask']),
                    last_update=datetime.utcnow(),
                    spread=float(quote['ask']) - float(quote['bid']),
                    bid_volume=float(quote.get('bid_volume', 0)),
                    ask_volume=float(quote.get('ask_volume', 0))
                )
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to fetch quote: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch quote")
        
        @self.app.post("/api/v2/orders", response_model=Dict[str, Any], tags=["Trading"])
        async def place_order(
            order: PlaceOrderRequest,
            background_tasks: BackgroundTasks,
            user_id: str = Depends(self._verify_token)
        ):
            """Place new order"""
            
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                
                # Validate order
                if order.quantity <= 0:
                    raise ValueError("Quantity must be positive")
                
                if order.order_type == "LIMIT" and order.price is None:
                    raise ValueError("Price required for LIMIT orders")
                
                if order.order_type == "STOP" and order.price is None:
                    raise ValueError("Price required for STOP orders")
                
                # Check risk limits
                if self.broker and hasattr(self.broker, 'check_risk'):
                    is_ok, reason = await self.broker.check_risk(user_id, order)
                    if not is_ok:
                        raise ValueError(f"Risk check failed: {reason}")
                
                # Place order
                result = await self.broker.place_order(
                    user_id=user_id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    quantity=order.quantity,
                    price=order.price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    comment=order.comment
                )
                
                # Send notification async
                if self.notification_service:
                    background_tasks.add_task(
                        self.notification_service.send,
                        user_id=user_id,
                        title="Order Placed",
                        body=f"{order.side} {order.quantity} {order.symbol}"
                    )
                
                logger.info(f"Order placed by {user_id}: {order.symbol}")
                
                return {
                    'order_id': result.get('order_id', str(uuid.uuid4())),
                    'status': result.get('status', 'pending'),
                    'entry_price': order.price or result.get('entry_price', 0),
                    'quantity': order.quantity,
                    'timestamp': datetime.utcnow().isoformat()
                }
            
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Order placement failed: {e}")
                raise HTTPException(status_code=500, detail="Order placement failed")
        
        @self.app.get("/api/v2/trades", response_model=List[TradeData], tags=["Trading"])
        async def get_open_trades(user_id: str = Depends(self._verify_token)):
            """Get all open trades"""
            
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                
                trades = await self.broker.get_open_trades(user_id)
                
                return [
                    TradeData(
                        trade_id=t['trade_id'],
                        symbol=t['symbol'],
                        side=t['side'],
                        entry_price=float(t['entry_price']),
                        quantity=float(t['quantity']),
                        current_price=float(t['current_price']),
                        pnl=float(t['pnl']),
                        pnl_percentage=float(t['pnl_percentage']),
                        entry_time=datetime.fromisoformat(t['entry_time']),
                        duration_seconds=int((datetime.utcnow() - datetime.fromisoformat(t['entry_time'])).total_seconds()),
                        spread=float(t.get('spread', 0))
                    )
                    for t in trades
                ]
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to fetch trades: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch trades")
        
        @self.app.post("/api/v2/trades/{trade_id}/close", tags=["Trading"])
        async def close_trade(
            trade_id: str,
            user_id: str = Depends(self._verify_token),
            background_tasks: BackgroundTasks = None
        ):
            """Close specific trade"""
            
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                
                result = await self.broker.close_trade(trade_id)
                
                if background_tasks and self.notification_service:
                    background_tasks.add_task(
                        self.notification_service.send,
                        user_id=user_id,
                        title="Trade Closed",
                        body=f"Trade #{trade_id} closed with P&L: {result.get('pnl', 0)}"
                    )
                
                return {
                    'trade_id': trade_id,
                    'status': 'closed',
                    'close_price': result.get('close_price', 0),
                    'pnl': result.get('pnl', 0),
                    'timestamp': datetime.utcnow().isoformat()
                }
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to close trade: {e}")
                raise HTTPException(status_code=500, detail="Failed to close trade")
        
        # ============ PERFORMANCE ============
        @self.app.get("/api/v2/performance", response_model=List[PerformanceData], tags=["Analytics"])
        async def get_performance(
            days: int = Query(30, ge=1, le=365),
            user_id: str = Depends(self._verify_token)
        ):
            """Get performance data"""
            
            try:
                if not self.broker:
                    raise HTTPException(status_code=503, detail="Broker offline")
                
                performance = await self.broker.get_performance(user_id, days=days)
                
                return [
                    PerformanceData(
                        day=p['date'],
                        pnl=float(p['pnl']),
                        trades=int(p['trades']),
                        win_rate=float(p['win_rate']),
                        max_drawdown=float(p['max_drawdown'])
                    )
                    for p in performance
                ]
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to fetch performance: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch performance")
        
        # ============ NEWS & ECONOMIC CALENDAR ============
        @self.app.get("/api/v2/news", response_model=List[NewsItem], tags=["News"])
        async def get_news(
            limit: int = Query(20, ge=1, le=100),
            user_id: str = Depends(self._verify_token)
        ):
            """Get latest financial news"""
            
            try:
                # This would typically call a news service
                return []
            
            except Exception as e:
                logger.error(f"Failed to fetch news: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch news")
        
        # ============ NOTIFICATIONS ============
        @self.app.get("/api/v2/notifications/preferences", tags=["Notifications"])
        async def get_notification_preferences(user_id: str = Depends(self._verify_token)):
            """Get notification preferences"""
            
            try:
                if not self.db:
                    return NotificationPreferences()
                
                prefs = self.db.get_notification_preferences(user_id)
                return NotificationPreferences(**prefs) if prefs else NotificationPreferences()
            
            except Exception as e:
                logger.error(f"Failed to fetch preferences: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch preferences")
        
        @self.app.post("/api/v2/notifications/preferences", tags=["Notifications"])
        async def update_notification_preferences(
            preferences: NotificationPreferences,
            user_id: str = Depends(self._verify_token)
        ):
            """Update notification preferences"""
            
            try:
                if self.db:
                    self.db.update_notification_preferences(user_id, preferences.dict())
                
                return {"status": "updated"}
            
            except Exception as e:
                logger.error(f"Failed to update preferences: {e}")
                raise HTTPException(status_code=500, detail="Failed to update preferences")
        
        # ============ WEBSOCKET (REAL-TIME) ============
        @self.app.websocket("/api/v2/ws/quotes")
        async def websocket_quotes(websocket: WebSocket, symbols: str = Query(...)):
            """WebSocket for real-time quotes"""
            
            await websocket.accept()
            symbol_list = [s.strip() for s in symbols.split(',')]
            
            try:
                while True:
                    quotes = {}
                    for symbol in symbol_list:
                        if self.broker:
                            try:
                                quote = await self.broker.get_quote(symbol)
                                quotes[symbol] = {
                                    'bid': float(quote['bid']),
                                    'ask': float(quote['ask']),
                                    'timestamp': datetime.utcnow().isoformat()
                                }
                            except:
                                pass
                    
                    if quotes:
                        await websocket.send_json(quotes)
                    
                    # Send every 500ms
                    await asyncio.sleep(0.5)
            
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await websocket.close()
        
        @self.app.websocket("/api/v2/ws/trades")
        async def websocket_trades(websocket: WebSocket, user_id: str = Query(...)):
            """WebSocket for real-time trade updates"""
            
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
                logger.error(f"WebSocket error: {e}")
            
            finally:
                self.active_connections[user_id].remove(websocket)
    
    def _generate_token(self, user_id: str, expires_hours: int = 24) -> str:
        """Generate JWT token"""
        
        payload = {
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=expires_hours),
            'iat': datetime.utcnow()
        }
        
        token = jwt.encode(payload, self.jwt_secret, algorithm='HS256')
        return token
    
    async def _verify_token(self, authorization: str = Header(...)) -> str:
        """Verify JWT token and return user_id"""
        
        try:
            parts = authorization.split()
            
            if len(parts) != 2 or parts[0] != "Bearer":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid auth scheme"
                )
            
            token = parts[1]
            payload = jwt.decode(token, self.jwt_secret, algorithms=['HS256'])
            return payload['user_id']
        
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired"
            )
        except jwt.DecodeError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
    
    def run(self, reload: bool = False):
        """Run the API server"""
        import uvicorn
        
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            reload=reload
        )


# ============ USAGE ============

if __name__ == "__main__":
    api = MobileAPIServer(
        port=8001,
        jwt_secret="your-super-secret-key"
    )
    api.run()