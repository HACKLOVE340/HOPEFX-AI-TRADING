# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""replay/router.py — FastAPI router for chart replay endpoints."""

from replay.engine import ChartReplayEngine
from replay.models import ReplaySpeed


def create_replay_router(engine: "ChartReplayEngine"):
    """
    Create a FastAPI router for the Chart Replay Engine module.

    Args:
        engine: ChartReplayEngine instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/replay", tags=["Replay"])

    class CreateSessionRequest(BaseModel):
        symbol: str = "XAUUSD"
        timeframe: str = "1h"
        start_date: str
        end_date: str
        initial_balance: float = 100000.0

    class SetSpeedRequest(BaseModel):
        speed: int = 1

    class PlaceOrderRequest(BaseModel):
        side: str
        size: float
        price: float | None = None
        stop_loss: float | None = None
        take_profit: float | None = None

    @router.post("/sessions")
    async def create_session(req: CreateSessionRequest):
        """Create a new replay session."""
        from datetime import datetime

        try:
            start = datetime.fromisoformat(req.start_date)
            end = datetime.fromisoformat(req.end_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {exc}") from exc
        session = engine.create_session(
            symbol=req.symbol,
            timeframe=req.timeframe,
            start_date=start,
            end_date=end,
            initial_balance=req.initial_balance,
        )
        return {
            "session_id": session.session_id,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "state": session.state.value,
            "start_date": session.start_date.isoformat(),
            "end_date": session.end_date.isoformat(),
        }

    @router.post("/sessions/{session_id}/play")
    async def play(session_id: str):
        """Start or resume a replay session."""
        success = engine.play(session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return {"session_id": session_id, "status": "playing"}

    @router.post("/sessions/{session_id}/pause")
    async def pause(session_id: str):
        """Pause a replay session."""
        success = engine.pause(session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return {"session_id": session_id, "status": "paused"}

    @router.post("/sessions/{session_id}/stop")
    async def stop(session_id: str):
        """Stop and reset a replay session."""
        success = engine.stop(session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return {"session_id": session_id, "status": "idle"}

    @router.put("/sessions/{session_id}/speed")
    async def set_speed(session_id: str, req: SetSpeedRequest):
        """Set replay speed (1x, 2x, 5x, 10x, 50x, 100x)."""
        valid_speeds = {s.value: s for s in ReplaySpeed if s != ReplaySpeed.PAUSED}
        if req.speed not in valid_speeds:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid speed. Choose from {sorted(valid_speeds.keys())}",
            )
        success = engine.set_speed(valid_speeds[req.speed], session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return {"session_id": session_id, "speed": req.speed}

    @router.get("/sessions/{session_id}/summary")
    async def get_summary(session_id: str):
        """Get current session summary (P&L, state, positions)."""
        summary = engine.get_session_summary(session_id)
        if not summary:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return summary

    @router.post("/sessions/{session_id}/orders")
    async def place_order(session_id: str, req: PlaceOrderRequest):
        """Place a practice order in the replay session."""
        result = engine.place_practice_order(
            side=req.side,
            size=req.size,
            price=req.price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            session_id=session_id,
        )
        if result is None:
            raise HTTPException(status_code=400, detail="Could not place order")
        return result

    return router


# Canonical alias used by app.py and WORDMAP
ReplayEngine = ChartReplayEngine

# Module exports
