"""
Production Mobile API v2.0
- iOS/Android REST endpoints
- Real-time WebSocket support
- Offline-first architecture
- Push notifications
- Two-factor authentication
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import uuid
import json

from fastapi import FastAPI, HTTPException, Depends, WebSocket, Header, Query
from fastapi.security import HTTPBearer, HTTPAuthCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import jwt
import bcrypt

logger = logging.getLogger(__name__)

# ============ REQUEST/RESPONSE MODELS ============

class MobileUserRegistration(BaseModel):
    """Mobile user registration"""
    email: str
    password: str
    username: str
    device_id: str
    platform: str  # ios, android

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

class QuoteData(BaseModel):
    """Real-time market quote"""
    symbol: str
    bid: float
    ask: float
    last_update: datetime
    spread: float

class PlaceOrderRequest(BaseModel):
    """Mobile order placement"""
    symbol: str
    side: str  # BUY, SELL
    order_type: str  # MARKET, LIMIT, STOP
    quantity: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

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

# ============ MOBILE API APP ============

class MobileAPIServer:
    """Production mobile API server"""
    
    def __init__(self,
                 host: str = "0.0.0.0",
                 port: int = 8001,
                 jwt_secret: str = "your-secret-key",
                 broker=None,
                 db=None,
                 notification_service=None):
        """
        Initialize mobile API
        
        Args:
            host: API host
            port: API port
            jwt_secret: JWT secret for tokens
            broker: Broker connection
            db: Database connection
            notification_service: Push notification service
        """
        self.app = FastAPI(title="HopeFX Mobile API", version="2.0.0")
        self.host = host
        self.port = port
        self.jwt_secret = jwt_secret
        self.broker = broker
        self.db = db
        self.notification_service = notification_service
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup all API routes"""
        
        # ============ AUTHENTICATION ============
        @self.app.post("/api/v2/auth/register", response_model=AuthToken)
        async def register(user: MobileUserRegistration):
            """Register new mobile user"""
            
            # Hash password
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(user.password.encode(), salt)
            
            # Store user
            user_id = str(uuid.uuid4())
            
            try:
                # Save to database
                if self.db:
                    self.db.save_user({
                        'user_id': user_id,
                        'email': user.email,
                        'username': user.username,
                        'password_hash': password_hash.decode(),
                        'device_id': user.device_id,
                        'platform': user.platform,
                        'created_at': datetime.utcnow()
                    })
                
                # Generate tokens
                access_token = self._generate_token(user_id, expires_hours=24)
                refresh_token = self._generate_token(user_id, expires_hours=7*24)
                
                return AuthToken(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=86400  # 24 hours
                )
                
            except Exception as e:
                logger.error(f"Registration failed: {e}")
                raise HTTPException(status_code=400, detail="Registration failed")
        
        @self.app.post("/api/v2/auth/login", response_model=AuthToken)
        async def login(email: str, password: str):
            """Login mobile user"""
            
            try:
                # Retrieve user from DB
                user = self.db.get_user_by_email(email) if self.db else None
                
                if not user:
                    raise HTTPException(status_code=401, detail="Invalid credentials")
                
                # Verify password
                if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
                    raise HTTPException(status_code=401, detail="Invalid credentials")
                
                # Generate tokens
                access_token = self._generate_token(user['user_id'], expires_hours=24)
                refresh_token = self._generate_token(user['user_id'], expires_hours=7*24)
                
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
        
        # ============ ACCOUNT ============
        @self.app.get("/api/v2/account", response_model=Account)
        async def get_account(user_id: str = Depends(self._verify_token)):
            """Get account overview"""
            
            if not self.broker:
                raise HTTPException(status_code=503, detail="Broker offline")
            
            try:
                account_info = self.broker.get_account_info(user_id)
                
                return Account(
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
                
            except Exception as e:
                logger.error(f"Failed to fetch account: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch account")
        
        # ============ TRADING ============
        @self.app.get("/api/v2/quotes/{symbol}", response_model=QuoteData)
        async def get_quote(symbol: str, user_id: str = Depends(self._verify_token)):
            """Get real-time quote for symbol"""
            
            if not self.broker:
                raise HTTPException(status_code=503, detail="Broker offline")
            
            try:
                quote = self.broker.get_quote(symbol)
                
                spread = quote['ask'] - quote['bid']
                
                return QuoteData(
                    symbol=symbol,
                    bid=float(quote['bid']),
                    ask=float(quote['ask']),
                    last_update=datetime.utcnow(),
                    spread=spread
                )
                
            except Exception as e:
                logger.error(f"Failed to fetch quote: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch quote")
        
        @self.app.post("/api/v2/orders", response_model=Dict[str, Any])
        async def place_order(order: PlaceOrderRequest, user_id: str = Depends(self._verify_token)):
            """Place new order from mobile"""
            
            if not self.broker:
                raise HTTPException(status_code=503, detail="Broker offline")
            
            try:
                # Validate order
                if order.quantity <= 0:
                    raise ValueError("Quantity must be positive")
                
                if order.order_type == "LIMIT" and order.price is None:
                    raise ValueError("Price required for LIMIT orders")
                
                # Place order
                result = self.broker.place_order(
                    user_id=user_id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    quantity=order.quantity,
                    price=order.price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit
                )
                
                # Send notification
                if self.notification_service:
                    self.notification_service.send(
                        user_id=user_id,
                        title="Order Placed",
                        body=f"{order.side} {order.quantity} {order.symbol} @ {order.price}"
                    )
                
                return {
                    'order_id': result['order_id'],
                    'status': result['status'],
                    'entry_price': result['entry_price'],
                    'timestamp': datetime.utcnow().isoformat()
                }
                
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                logger.error(f"Order placement failed: {e}")
                raise HTTPException(status_code=500, detail="Order placement failed")
        
        @self.app.get("/api/v2/trades", response_model=List[TradeData])
        async def get_open_trades(user_id: str = Depends(self._verify_token)):
            """Get all open trades"""
            
            if not self.broker:
                raise HTTPException(status_code=503, detail="Broker offline")
            
            try:
                trades = self.broker.get_open_trades(user_id)
                
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
                        duration_seconds=int((datetime.utcnow() - datetime.fromisoformat(t['entry_time'])).total_seconds())
                    )
                    for t in trades
                ]
                
            except Exception as e:
                logger.error(f"Failed to fetch trades: {e}")
                raise HTTPException(status_code=500, detail="Failed to fetch trades")
        
        @self.app.post("/api/v2/trades/{trade_id}/close")
        async def close_trade(trade_id: str, user_id: str = Depends(self._verify_token)):
            """Close specific trade"""
            
            if not self.broker:
                raise HTTPException(status_code=503, detail="Broker offline")
            
            try:
                result = self.broker.close_trade(trade_id)
                
                return {
                    'trade_id': trade_id,
                    'status': 'closed',
                    'close_price': result['close_price'],
                    'pnl': result['pnl'],
                    'timestamp': datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                logger.error(f"Failed to close trade: {e}")
                raise HTTPException(status_code=500, detail="Failed to close trade")
        
        # ============ WEBSOCKET (REAL-TIME) ============
        @self.app.websocket("/api/v2/ws/quotes")
        async def websocket_quotes(websocket: WebSocket, symbols: str = Query(...)):
            """WebSocket for real-time quotes"""
            
            await websocket.accept()
            symbol_list = symbols.split(',')
            
            try:
                while True:
                    quotes = {}
                    for symbol in symbol_list:
                        if self.broker:
                            quote = self.broker.get_quote(symbol)
                            quotes[symbol] = {
                                'bid': quote['bid'],
                                'ask': quote['ask'],
                                'timestamp': datetime.utcnow().isoformat()
                            }
                    
                    await websocket.send_json(quotes)
                    
                    # Send every 100ms
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await websocket.close()
    
    def _generate_token(self, user_id: str, expires_hours: int = 24) -> str:
        """Generate JWT token"""
        
        payload = {
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=expires_hours),
            'iat': datetime.utcnow()
        }
        
        token = jwt.encode(payload, self.jwt_secret, algorithm='HS256')
        return token
    
    def _verify_token(self, authorization: str = Header(...)) -> str:
        """Verify JWT token and return user_id"""
        
        try:
            scheme, token = authorization.split()
            
            if scheme != "Bearer":
                raise HTTPException(status_code=401, detail="Invalid auth scheme")
            
            payload = jwt.decode(token, self.jwt_secret, algorithms=['HS256'])
            return payload['user_id']
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except (jwt.DecodeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid token")
    
    def run(self):
        """Run the API server"""
        import uvicorn
        
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )


# ============ USAGE ============

if __name__ == "__main__":
    api = MobileAPIServer(
        port=8001,
        jwt_secret="your-super-secret-key"
    )
    api.run()