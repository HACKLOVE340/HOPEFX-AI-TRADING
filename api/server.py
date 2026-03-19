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
    
    app = FastAPI(
        title="HOPEFX Trading API",
        description="Production trading system API",
        version="2.1.0"
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
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
    async def get_status():
        """Get trading system status"""
        if not trading_app:
            raise HTTPException(status_code=503, detail="Trading app not available")
        
        return trading_app.get_status()
    
    @app.get("/api/v1/account")
    async def get_account():
        """Get account information"""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        
        try:
            account = await trading_app.broker.get_account_info()
            return account
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/v1/positions")
    async def get_positions():
        """Get open positions"""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        
        try:
            positions = await trading_app.broker.get_positions()
            return {
                "positions": [p.to_dict() for p in positions],
                "count": len(positions)
            }
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/api/v1/orders")
    async def place_order(request: TradeRequest, background_tasks: BackgroundTasks):
        """Place a new order"""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        
        try:
            order = await trading_app.broker.place_market_order(
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity
            )
            
            # Record metrics in background
            background_tasks.add_task(
                get_metrics_registry().record_order_latency,
                0  # Would calculate actual latency
            )
            
            return {
                "order_id": order.id,
                "status": order.status.value,
                "filled_quantity": order.filled_quantity,
                "average_price": order.average_fill_price
            }
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.delete("/api/v1/positions/{position_id}")
    async def close_position(position_id: str):
        """Close a position"""
        if not trading_app or not trading_app.broker:
            raise HTTPException(status_code=503, detail="Broker not available")
        
        try:
            success = await trading_app.broker.close_position(position_id)
            if not success:
                raise HTTPException(status_code=400, detail="Failed to close position")
            
            return {"success": True, "position_id": position_id}
            
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # Brain control endpoints
    @app.post("/api/v1/brain/pause")
    async def pause_brain():
        """Pause trading"""
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        
        trading_app.brain.pause()
        return {"status": "paused"}
    
    @app.post("/api/v1/brain/resume")
    async def resume_brain():
        """Resume trading"""
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        
        trading_app.brain.resume()
        return {"status": "resumed"}
    
    @app.get("/api/v1/brain/state")
    async def get_brain_state():
        """Get brain state"""
        if not trading_app or not trading_app.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        
        return {
            "state": trading_app.brain.state.to_dict(),
            "health": trading_app.brain.get_health(),
            "decision_history_count": len(trading_app.brain.decision_history)
        }
    
    # Metrics and logs
    @app.get("/api/v1/metrics/json")
    async def get_metrics_json():
        """Get metrics as JSON"""
        registry = get_metrics_registry()
        return registry.get_all_metrics()
    
    @app.get("/api/v1/logs/recent")
    async def get_recent_logs(lines: int = 100):
        """Get recent log entries"""
        # This would integrate with your log aggregation
        return {"logs": [], "note": "Implement log retrieval from file or ELK"}
    
    # System control
    @app.post("/api/v1/system/shutdown")
    async def shutdown_system(background_tasks: BackgroundTasks):
        """Shutdown the trading system"""
        if not trading_app:
            raise HTTPException(status_code=503, detail="Trading app not available")
        
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
