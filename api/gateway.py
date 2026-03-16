# api/gateway.py
"""
HOPEFX API Gateway
Secure external interface for clients and integrations
"""

import asyncio
from fastapi import FastAPI, WebSocket, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from typing import Dict, List, Optional
from datetime import datetime
import jwt
import hashlib


class APIGateway:
    """
    Secure API gateway with authentication, rate limiting, and request routing.
    """
    
    def __init__(self, mcc, orchestra, pms, auth_secret: str):
        self.mcc = mcc
        self.orchestra = orchestra
        self.pms = pms
        self.auth_secret = auth_secret
        self.app = FastAPI(title="HOPEFX Ultimate API", version="3.0")
        
        # Security
        self.security = HTTPBearer()
        self.rate_limits: Dict[str, Dict] = {}  # IP -> {count, reset_time}
        
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
            allow_headers=["*"]
        )
        
        # Compression
        self.app.add_middleware(GZipMiddleware, minimum_size=1000)
        
        # Rate limiting
        @self.app.middleware("http")
        async def rate_limit(request, call_next):
            client_ip = request.client.host
            
            # Check rate limit
            now = datetime.utcnow()
            limit = self.rate_limits.get(client_ip, {'count': 0, 'reset_time': now})
            
            if now > limit['reset_time'] + 60:  # Reset every minute
                limit = {'count': 0, 'reset_time': now}
            
            if limit['count'] > 1000:  # 1000 requests per minute
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            
            limit['count'] += 1
            self.rate_limits[client_ip] = limit
            
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(1000 - limit['count'])
            return response
    
    def _setup_routes(self):
        """Setup API routes"""
        
        # Health check
        @self.app.get("/health")
        async def health():
            return {
                'status': 'healthy',
                'timestamp': datetime.utcnow().isoformat(),
                'version': '3.0',
                'components': {
                    'mcc': self.mcc.health if hasattr(self.mcc, 'health') else 'unknown',
                    'orchestra': len(self.orchestra.active_strategies),
                    'portfolio': self.pms.get_portfolio_summary()
                }
            }
        
        # System status
        @self.app.get("/api/v1/status")
        async def status(credentials: HTTPAuthorizationCredentials = Depends(self.security)):
            self._verify_token(credentials.credentials)
            
            return {
                'system': self.mcc.get_status() if hasattr(self.mcc, 'get_status') else {},
                'orchestra': self.orchestra.get_heatmap_data(),
                'portfolio': self.pms.get_portfolio_summary(),
                'timestamp': datetime.utcnow().isoformat()
            }
        
        # Strategy control
        @self.app.post("/api/v1/strategies/{strategy_id}/activate")
        async def activate_strategy(
            strategy_id: str,
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            self._verify_token(credentials.credentials, required_role='admin')
            
            self.orchestra.activate_strategy(strategy_id)
            return {'success': True, 'strategy_id': strategy_id, 'action': 'activated'}
        
        @self.app.post("/api/v1/strategies/{strategy_id}/deactivate")
        async def deactivate_strategy(
            strategy_id: str,
            reason: str = "api_request",
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            self._verify_token(credentials.credentials, required_role='admin')
            
            self.orchestra.deactivate_strategy(strategy_id, reason)
            return {'success': True, 'strategy_id': strategy_id, 'action': 'deactivated'}
        
        # Emergency controls
        @self.app.post("/api/v1/emergency/kill-switch")
        async def trigger_kill_switch(
            reason: str,
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            self._verify_token(credentials.credentials, required_role='superadmin')
            
            if hasattr(self.mcc, '_trigger_kill_switch'):
                self.mcc._trigger_kill_switch(f"API: {reason}")
            
            return {'success': True, 'action': 'kill_switch_triggered', 'reason': reason}
        
        # Portfolio info
        @self.app.get("/api/v1/portfolio")
        async def get_portfolio(
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            self._verify_token(credentials.credentials)
            return self.pms.get_portfolio_summary()
        
        # Order management
        @self.app.post("/api/v1/orders")
        async def create_order(
            order: Dict,
            credentials: HTTPAuthorizationCredentials = Depends(self.security)
        ):
            self._verify_token(credentials.credentials, required_role='trader')
            
            # Validate order
            if order.get('quantity', 0) <= 0:
                raise HTTPException(status_code=400, detail="Invalid quantity")
            
            # Submit through OMS
            # oms_id = self.oms.create_order(**order)
            
            return {'success': True, 'order_id': 'placeholder', 'status': 'pending'}
        
        # WebSocket for real-time data
        @self.app.websocket("/ws/v1/stream")
        async def websocket_stream(websocket: WebSocket):
            await websocket.accept()
            
            # Authenticate
            token = websocket.query_params.get('token')
            if not token or not self._verify_token(token, raise_exception=False):
                await websocket.close(code=4001, reason="Unauthorized")
                return
            
            try:
                while True:
                    # Send portfolio updates
                    data = {
                        'timestamp': datetime.utcnow().isoformat(),
                        'portfolio': self.pms.get_portfolio_summary(),
                        'heatmap': self.orchestra.get_heatmap_data()
                    }
                    await websocket.send_json(data)
                    await asyncio.sleep(1)
                    
            except Exception as e:
                print(f"WebSocket error: {e}")
    
    def _verify_token(self, token: str, required_role: str = 'user', raise_exception: bool = True) -> bool:
        """Verify JWT token"""
        try:
            payload = jwt.decode(token, self.auth_secret, algorithms=['HS256'])
            
            # Check role
            user_role = payload.get('role', 'user')
            role_hierarchy = {'user': 0, 'trader': 1, 'admin': 2, 'superadmin': 3}
            
            if role_hierarchy.get(user_role, 0) < role_hierarchy.get(required_role, 0):
                if raise_exception:
                    raise HTTPException(status_code=403, detail="Insufficient permissions")
                return False
            
            return True
            
        except jwt.ExpiredSignatureError:
            if raise_exception:
                raise HTTPException(status_code=401, detail="Token expired")
            return False
        except jwt.InvalidTokenError:
            if raise_exception:
                raise HTTPException(status_code=401, detail="Invalid token")
            return False
    
    def generate_token(self, user_id: str, role: str, expires_hours: int = 24) -> str:
        """Generate JWT token for client"""
        from datetime import timedelta
        
        payload = {
            'user_id': user_id,
            'role': role,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(hours=expires_hours)
        }
        
        return jwt.encode(payload, self.auth_secret, algorithm='HS256')
    
    def run(self, host: str = "0.0.0.0", port: int = 8443):
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
            workers=4
        )
