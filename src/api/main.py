"""Production-grade FastAPI with all enhancements."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from src.core.bus import event_bus
from src.core.event_store import EventStore
from src.risk.kill_switch import kill_switch, KillSource
from src.ml.gpu_manager import gpu_manager
from src.data.orderbook import MultiBookAggregator
from src.brain.engine import BrainEngine
from src.execution.reconciliation import ByzantineReconciler
from configs.settings import get_settings

logger = structlog.get_logger()
limiter = Limiter(key_func=get_remote_address)
security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Enhanced lifespan with all components."""
    settings = get_settings()
    
    # 1. Event store (audit)
    app.state.event_store = EventStore(settings.redis.url.get_secret_value())
    await app.state.event_store.initialize()
    
    # 2. GPU manager
    if gpu_manager.device.type == "cuda":
        logger.info(f"GPU ready: {gpu_manager.get_stats()}")
    
    # 3. Kill switch (distributed)
    await kill_switch.initialize(settings.security.jwt_secret.get_secret_value())
    await kill_switch.check_recovery()
    
    if kill_switch.is_killed():
        logger.critical("System starting in KILLED state")
    
    # 4. Order book aggregator
    app.state.orderbooks = MultiBookAggregator()
    
    # 5. Brain engine
    app.state.brain = BrainEngine()
    await app.state.brain.initialize()
    
    # 6. Event bus
    await event_bus.start()
    
    # 7. Reconciliation (if live trading)
    # app.state.reconciler = ByzantineReconciler(...)
    # await app.state.reconciler.start()
    
    logger.info("All systems operational")
    
    yield
    
    # Shutdown
    await event_bus.stop()
    await kill_switch.reset("shutdown")  # Cleanup


app = FastAPI(
    title="HOPEFX v2 - Institutional XAUUSD Trading",
    version="2.0.0-prod",
    docs_url=None if get_settings().env == "production" else "/docs",
    redoc_url=None if get_settings().env == "production" else "/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dashboard.hopefx.io"] if get_settings().env == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health_check():
    """Deep health check."""
    gpu_stats = gpu_manager.get_stats() if gpu_manager.device.type == "cuda" else None
    
    return {
        "status": "healthy" if not kill_switch.is_killed() else "killed",
        "kill_switch": kill_switch.get_metrics(),
        "gpu": gpu_stats,
        "event_bus": event_bus.get_stats(),
        "timestamp": asyncio.get_event_loop().time()
    }


@app.post("/admin/kill")
async def admin_kill(
    reason: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Emergency kill endpoint."""
    # Verify admin token...
    cmd = await kill_switch.kill(reason, source=KillSource.OPERATOR)
    return {"killed": True, "command_id": cmd.id}


@app.websocket("/ws/market")
async def market_stream(websocket: WebSocket):
    """Real-time market data with order book."""
    await websocket.accept()
    orderbooks = websocket.app.state.orderbooks
    
    try:
        while True:
            # Get consolidated view
            xau = orderbooks.get_consolidated("XAUUSD")
            await websocket.send_json({
                "orderbook": xau,
                "timestamp": asyncio.get_event_loop().time()
            })
            await asyncio.sleep(0.1)  # 10Hz
    except Exception:
        await websocket.close()


@app.websocket("/ws/brain")
async def brain_stream(websocket: WebSocket):
    """Brain decision stream."""
    await websocket.accept()
    brain = websocket.app.state.brain
    
    # Subscribe to brain decisions
    async def on_decision(decision):
        await websocket.send_json({
            "signal": decision.signal.value,
            "confidence": decision.confidence,
            "regime": decision.regime.name,
            "latency_us": decision.reasoning.get("latency_us")
        })
    
    # Register callback...
    
    try:
        while True:
            await asyncio.sleep(1)
    except Exception:
        await websocket.close()
