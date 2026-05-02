# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""replay/router.py — FastAPI router for chart replay endpoints."""

import logging

from replay.engine import ChartReplayEngine
from replay.models import ReplaySpeed

logger = logging.getLogger(__name__)


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

    @router.get("/sessions")
    async def list_sessions():
        """List all active replay sessions."""
        sessions = []
        for session in engine.sessions.values():
            sessions.append(
                {
                    "session_id": session.session_id,
                    "symbol": session.symbol,
                    "timeframe": session.timeframe,
                    "status": session.state.value,
                    "current_bar": getattr(session, "current_bar_index", 0),
                    "total_bars": len(engine.data_cache.get(f"{session.symbol}_{session.timeframe}", [])),
                    "current_price": getattr(session, "current_price", 0.0),
                    "equity": session.current_balance,
                    "pnl": session.current_balance - session.initial_balance,
                    "created_at": session.created_at.isoformat(),
                }
            )
        return sessions

    @router.post("/sessions")
    async def create_session(req: CreateSessionRequest):
        """Create a new replay session."""
        from datetime import datetime

        try:
            start = datetime.fromisoformat(req.start_date)
            end = datetime.fromisoformat(req.end_date)
        except ValueError as exc:
            logger.warning("Invalid date format in replay request: %s", exc)
            raise HTTPException(
                status_code=400, detail="Invalid date format — use ISO 8601 (e.g. 2024-01-15T00:00:00)"
            ) from None
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

    @router.post("/sessions/{session_id}/resume")
    async def resume(session_id: str):
        """Resume a paused replay session (or start it if not yet started).

        Delegates to engine.play() which handles both initial start and
        resume-from-pause transitions.
        """
        success = engine.play(session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return {"session_id": session_id, "status": "playing"}

    @router.post("/sessions/{session_id}/stop")
    async def stop(session_id: str):
        """Stop and reset a replay session."""
        success = engine.stop(session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return {"session_id": session_id, "status": "idle"}

    @router.put("/sessions/{session_id}/speed")
    @router.post("/sessions/{session_id}/speed")
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

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        """Return full session state including bars and trades."""
        session = engine.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        data_key = f"{session.symbol}_{session.timeframe}"
        bars_raw = engine.data_cache.get(data_key, [])
        bar_idx = getattr(session, "current_bar_index", 0)
        # Return bars up to current position so the frontend can render the chart
        visible_bars = bars_raw[: bar_idx + 1] if bars_raw else []
        return {
            "session_id": session.session_id,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "start_date": session.start_date.isoformat(),
            "end_date": session.end_date.isoformat(),
            "current_bar": bar_idx,
            "total_bars": len(bars_raw),
            "status": session.state.value,
            "current_price": visible_bars[-1].close if visible_bars else 0.0,
            "equity": session.current_balance,
            "pnl": session.current_balance - session.initial_balance,
            "trades": session.trades,
            "bars": [
                {
                    "time": int(b.timestamp.timestamp()),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in visible_bars
            ],
            "created_at": session.created_at.isoformat(),
        }

    @router.post("/sessions/{session_id}/step")
    async def step_session(session_id: str):
        """Advance the replay session by exactly one bar."""
        session = engine.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        data_key = f"{session.symbol}_{session.timeframe}"
        bars = engine.data_cache.get(data_key, [])
        bar_idx = getattr(session, "current_bar_index", 0)
        if bar_idx >= len(bars) - 1:
            from replay.models import ReplayState

            session.state = ReplayState.FINISHED
            return {"session_id": session_id, "status": "completed", "current_bar": bar_idx}
        bar_idx += 1
        session.current_bar_index = bar_idx  # type: ignore[attr-defined]
        current_bar = bars[bar_idx]
        return {
            "session_id": session_id,
            "current_bar": bar_idx,
            "total_bars": len(bars),
            "status": session.state.value,
            "bar": {
                "time": int(current_bar.timestamp.timestamp()),
                "open": current_bar.open,
                "high": current_bar.high,
                "low": current_bar.low,
                "close": current_bar.close,
                "volume": current_bar.volume,
            },
        }

    @router.post("/sessions/{session_id}/run")
    async def run_session(session_id: str, bars: int = 10):
        """Advance the replay session by N bars at once."""
        session = engine.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        data_key = f"{session.symbol}_{session.timeframe}"
        all_bars = engine.data_cache.get(data_key, [])
        bar_idx = getattr(session, "current_bar_index", 0)
        new_idx = min(bar_idx + max(1, bars), len(all_bars) - 1)
        session.current_bar_index = new_idx  # type: ignore[attr-defined]
        if new_idx >= len(all_bars) - 1:
            from replay.models import ReplayState

            session.state = ReplayState.FINISHED
        advanced = new_idx - bar_idx
        return {
            "session_id": session_id,
            "bars_advanced": advanced,
            "current_bar": new_idx,
            "total_bars": len(all_bars),
            "status": session.state.value,
        }

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        """Delete a replay session."""
        if session_id not in engine.sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        del engine.sessions[session_id]

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

# Module-level router — imported by core.router_registry
_replay_engine_instance = None


def _get_replay_engine():
    global _replay_engine_instance
    if _replay_engine_instance is None:
        _replay_engine_instance = ChartReplayEngine()
    return _replay_engine_instance


router = create_replay_router(_get_replay_engine())
