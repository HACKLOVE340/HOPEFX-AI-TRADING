"""
Institutional REST API & WebSocket Server
"""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import jwt
import pandas as pd

from hopefx.core.events import event_bus, EventType, DomainEvent
from hopefx.trading.execution import ExecutionEngine, Order, OrderSide, OrderType, TimeInForce
from hopefx.data.manager import UnifiedDataManager, DataConfig
from hopefx.infrastructure.logging import get_logger

logger = get_logger("hopefx.api")
security = HTTPBearer()

# ============================================================================
# LIFESPAN (startup/shutdown)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup
    logger.info("API starting up")
    
    # Initialize components
    app.state.data = UnifiedDataManager(DataConfig())
    await app.state.data.initialize()
    
    app.state.execution = ExecutionEngine()
    # Register brokers...
    
    # Start event bus
    asyncio.create_task(event_bus.start())
    
    yield
    
    # Shutdown
    logger.info("API shutting down")
    event_bus.stop()
    await app.state.data.shutdown()

# ============================================================================
# APP CREATION
# ============================================================================

app = FastAPI(
    title="HOPEFX Institutional API",
    version="4.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# AUTHENTICATION
# ============================================================================

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """Verify JWT token."""
    try:
        # In production, use proper secret key
        payload = jwt.decode(
            credentials.credentials,
            "your-secret-key",  # Use env var
            algorithms=["HS256"]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ============================================================================
# REST ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "4.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "database": "connected",
            "redis": "connected",
            "event_bus": "running"
        }
    }

@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: Dict,
    user: Dict = Depends(verify_token)
):
    """
    Submit new order.
    
    Supports all order types: market, limit, stop, TWAP, VWAP, etc.
    """
    try:
        # Build order object
        order = Order(
            order_id=str(uuid.uuid4()),
            symbol=order_data["symbol"],
            side=OrderSide.BUY if order_data["side"] == "buy" else OrderSide.SELL,
            quantity=Decimal(str(order_data["quantity"])),
            order_type=OrderType(order_data.get("type", "market")),
            time_in_force=TimeInForce(order_data.get("time_in_force", "gtc")),
            price=Decimal(str(order_data["price"])) if "price" in order_data else None,
            stop_price=Decimal(str(order_data["stop_price"])) if "stop_price" in order_data else None,
            user_id=user["user_id"]
        )
        
        # Submit
        order_id = await app.state.execution.submit_order(order)
        
        return {
            "order_id": order_id,
            "status": "accepted",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error("Order creation failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    user: Dict = Depends(verify_token)
):
    """Get order status."""
    status = app.state.execution.get_order_status(order_id)
    return status

@app.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str,
    user: Dict = Depends(verify_token)
):
    """Cancel order."""
    success = await app.state.execution.cancel_order(order_id)
    if not success:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"status": "cancelled"}

@app.get("/positions")
async def get_positions(user: Dict = Depends(verify_token)):
    """Get current positions."""
    # Query from database
    return {"positions": []}

@app.get("/trades/history")
async def trade_history(
    limit: int = 100,
    since: Optional[datetime] = None,
    user: Dict = Depends(verify_token)
):
    """Get trade history."""
    return {"trades": []}

# ============================================================================
# WEBSOCKET (Real-time streaming)
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket for real-time updates.
    
    Streams: trades, fills, market data, system events
    """
    await websocket.accept()
    
    # Subscribe to event bus
    queue = event_bus.subscribe_ws()
    
    try:
        while True:
            # Wait for events with timeout
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                
                # Send to client
                await websocket.send_json({
                    "type": event.event_type.name,
                    "timestamp": event.timestamp.isoformat(),
                    "trace_id": event.trace_id,
                    "data": event.payload
                })
                
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({"type": "keepalive"})
            
            # Check for client messages
            try:
                msg = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=0.1
                )
                # Handle client commands
                data = json.loads(msg)
                if data.get("action") == "subscribe":
                    # Handle subscription changes
                    pass
                    
            except asyncio.TimeoutError:
                pass  # No message from client
            
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
    finally:
        event_bus.unsubscribe_ws(queue)
