"""WebSocket endpoints."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from src.core.bus import event_bus
from src.core.events import TickEvent, SignalEvent

router = APIRouter()


@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """Stream real-time events."""
    await websocket.accept()
    
    # Subscribe to events
    queue: asyncio.Queue = asyncio.Queue()
    
    async def tick_handler(event: TickEvent):
        await queue.put({"type": "tick", "data": event.tick.model_dump()})
    
    async def signal_handler(event: SignalEvent):
        await queue.put({"type": "signal", "data": event.model_dump()})
    
    event_bus.subscribe(TickEvent, tick_handler)
    event_bus.subscribe(SignalEvent, signal_handler)
    
    try:
        while True:
            # Send queued messages
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                await websocket.send_json(msg)
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
            
            # Receive client messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                # Handle commands
                cmd = json.loads(data)
                if cmd.get("action") == "subscribe":
                    # Handle subscription changes
                    pass
            except asyncio.TimeoutError:
                pass
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
