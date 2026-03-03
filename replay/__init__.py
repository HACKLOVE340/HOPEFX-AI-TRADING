"""
Phase 18: Chart Replay Mode Module

Provides historical market data replay functionality for practice trading
and strategy testing without risking real capital.
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
import time
import threading

logger = logging.getLogger(__name__)


class ReplaySpeed(Enum):
    """Replay speed options"""
    PAUSED = 0
    SPEED_1X = 1
    SPEED_2X = 2
    SPEED_5X = 5
    SPEED_10X = 10
    SPEED_50X = 50
    SPEED_100X = 100


class ReplayState(Enum):
    """Replay state"""
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass
class ReplaySession:
    """Replay session configuration"""
    session_id: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    current_date: datetime
    speed: ReplaySpeed = ReplaySpeed.SPEED_1X
    state: ReplayState = ReplayState.IDLE
    initial_balance: float = 100000.0
    current_balance: float = 100000.0
    trades: List[Dict[str, Any]] = field(default_factory=list)
    positions: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ReplayBar:
    """Single bar of replay data"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class ChartReplayEngine:
    """
    Chart Replay Engine
    
    Replays historical market data for practice trading and strategy testing.
    
    Features:
    - Variable speed playback (1x to 100x)
    - Pause/resume functionality
    - Practice trading with virtual balance
    - Session recording and review
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize replay engine."""
        self.config = config or {}
        self.sessions: Dict[str, ReplaySession] = {}
        self.active_session_id: Optional[str] = None
        self.data_cache: Dict[str, List[ReplayBar]] = {}
        self.callbacks: Dict[str, List[Callable]] = {
            'on_bar': [],
            'on_trade': [],
            'on_state_change': [],
        }
        self._replay_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        
        logger.info("Chart Replay Engine initialized")
    
    def create_session(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float = 100000.0
    ) -> ReplaySession:
        """
        Create a new replay session.
        
        Args:
            symbol: Trading symbol
            timeframe: Chart timeframe
            start_date: Replay start date
            end_date: Replay end date
            initial_balance: Starting virtual balance
            
        Returns:
            New replay session
        """
        session_id = f"replay_{len(self.sessions) + 1}_{int(datetime.now().timestamp())}"
        
        session = ReplaySession(
            session_id=session_id,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            current_date=start_date,
            initial_balance=initial_balance,
            current_balance=initial_balance
        )
        
        self.sessions[session_id] = session
        self.active_session_id = session_id
        
        # Load historical data
        self._load_data(session)
        
        logger.info(f"Created replay session: {session_id} for {symbol}")
        return session
    
    def _load_data(self, session: ReplaySession):
        """Load historical data for replay session."""
        # In production, this would load from database or data provider
        # For now, generate sample data
        data_key = f"{session.symbol}_{session.timeframe}"
        
        if data_key not in self.data_cache:
            bars = self._generate_sample_data(session)
            self.data_cache[data_key] = bars
        
        logger.info(f"Loaded {len(self.data_cache.get(data_key, []))} bars for {data_key}")
    
    def _generate_sample_data(self, session: ReplaySession) -> List[ReplayBar]:
        """Generate sample data for testing."""
        import random
        
        bars = []
        current_time = session.start_date
        price = 1950.0  # Starting price for XAUUSD
        
        # Map timeframe to timedelta
        tf_map = {
            '1M': timedelta(minutes=1),
            '5M': timedelta(minutes=5),
            '15M': timedelta(minutes=15),
            '30M': timedelta(minutes=30),
            '1H': timedelta(hours=1),
            '4H': timedelta(hours=4),
            '1D': timedelta(days=1),
        }
        delta = tf_map.get(session.timeframe, timedelta(hours=1))
        
        while current_time <= session.end_date:
            # Generate OHLCV data
            change = random.uniform(-0.5, 0.5)
            open_price = price
            close_price = price + change
            high_price = max(open_price, close_price) + random.uniform(0, 0.3)
            low_price = min(open_price, close_price) - random.uniform(0, 0.3)
            volume = random.uniform(1000, 10000)
            
            bars.append(ReplayBar(
                timestamp=current_time,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume
            ))
            
            price = close_price
            current_time += delta
        
        return bars
    
    def play(self, session_id: Optional[str] = None) -> bool:
        """Start or resume replay."""
        session = self._get_session(session_id)
        if not session:
            return False
        
        if session.state == ReplayState.FINISHED:
            logger.warning("Session already finished")
            return False
        
        session.state = ReplayState.PLAYING
        self._stop_flag.clear()
        
        # Start replay thread
        self._replay_thread = threading.Thread(
            target=self._replay_loop,
            args=(session,),
            daemon=True
        )
        self._replay_thread.start()
        
        self._trigger_callback('on_state_change', session, ReplayState.PLAYING)
        logger.info(f"Started replay: {session.session_id}")
        return True
    
    def pause(self, session_id: Optional[str] = None) -> bool:
        """Pause replay."""
        session = self._get_session(session_id)
        if not session:
            return False
        
        session.state = ReplayState.PAUSED
        self._stop_flag.set()
        
        self._trigger_callback('on_state_change', session, ReplayState.PAUSED)
        logger.info(f"Paused replay: {session.session_id}")
        return True
    
    def stop(self, session_id: Optional[str] = None) -> bool:
        """Stop replay."""
        session = self._get_session(session_id)
        if not session:
            return False
        
        session.state = ReplayState.FINISHED
        self._stop_flag.set()
        
        self._trigger_callback('on_state_change', session, ReplayState.FINISHED)
        logger.info(f"Stopped replay: {session.session_id}")
        return True
    
    def set_speed(self, speed: ReplaySpeed, session_id: Optional[str] = None) -> bool:
        """Set replay speed."""
        session = self._get_session(session_id)
        if not session:
            return False
        
        session.speed = speed
        logger.info(f"Set replay speed to {speed.name}")
        return True
    
    def seek(self, target_date: datetime, session_id: Optional[str] = None) -> bool:
        """Seek to a specific date in the replay."""
        session = self._get_session(session_id)
        if not session:
            return False
        
        if target_date < session.start_date or target_date > session.end_date:
            logger.warning("Target date out of range")
            return False
        
        session.current_date = target_date
        logger.info(f"Seeked to {target_date}")
        return True
    
    def place_practice_order(
        self,
        side: str,
        size: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        session_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Place a practice order in the replay session.
        
        Args:
            side: 'BUY' or 'SELL'
            size: Position size
            order_type: 'MARKET' or 'LIMIT'
            price: Limit price (optional)
            session_id: Session ID
            
        Returns:
            Trade details or None
        """
        session = self._get_session(session_id)
        if not session:
            return None
        
        # Get current price from replay
        current_bar = self._get_current_bar(session)
        if not current_bar:
            return None
        
        execution_price = price if order_type == "LIMIT" and price else current_bar.close
        
        trade = {
            'trade_id': f"trade_{len(session.trades) + 1}",
            'timestamp': session.current_date,
            'symbol': session.symbol,
            'side': side,
            'size': size,
            'price': execution_price,
            'order_type': order_type,
            'pnl': 0.0,
            'status': 'FILLED'
        }
        
        session.trades.append(trade)
        
        # Update position
        self._update_position(session, trade)
        
        self._trigger_callback('on_trade', session, trade)
        logger.info(f"Practice trade executed: {side} {size} @ {execution_price}")
        return trade
    
    def _get_session(self, session_id: Optional[str]) -> Optional[ReplaySession]:
        """Get session by ID or active session."""
        if session_id:
            return self.sessions.get(session_id)
        elif self.active_session_id:
            return self.sessions.get(self.active_session_id)
        return None
    
    def _get_current_bar(self, session: ReplaySession) -> Optional[ReplayBar]:
        """Get the current bar in replay."""
        data_key = f"{session.symbol}_{session.timeframe}"
        bars = self.data_cache.get(data_key, [])
        
        for bar in bars:
            if bar.timestamp >= session.current_date:
                return bar
        return bars[-1] if bars else None
    
    def _update_position(self, session: ReplaySession, trade: Dict[str, Any]):
        """Update session positions based on trade."""
        # Find existing position
        existing_pos = None
        for pos in session.positions:
            if pos['symbol'] == trade['symbol'] and pos['status'] == 'OPEN':
                existing_pos = pos
                break
        
        if existing_pos:
            # Update or close existing position
            if existing_pos['side'] == trade['side']:
                # Add to position
                existing_pos['size'] += trade['size']
            else:
                # Reduce or close position
                existing_pos['size'] -= trade['size']
                if existing_pos['size'] <= 0:
                    existing_pos['status'] = 'CLOSED'
                    pnl = (trade['price'] - existing_pos['entry_price']) * abs(existing_pos['size'])
                    if existing_pos['side'] == 'SELL':
                        pnl = -pnl
                    existing_pos['pnl'] = pnl
                    session.current_balance += pnl
        else:
            # Create new position
            session.positions.append({
                'position_id': f"pos_{len(session.positions) + 1}",
                'symbol': trade['symbol'],
                'side': trade['side'],
                'size': trade['size'],
                'entry_price': trade['price'],
                'current_price': trade['price'],
                'pnl': 0.0,
                'status': 'OPEN'
            })
    
    def _replay_loop(self, session: ReplaySession):
        """Main replay loop running in background thread."""
        data_key = f"{session.symbol}_{session.timeframe}"
        bars = self.data_cache.get(data_key, [])
        
        for bar in bars:
            if self._stop_flag.is_set():
                break
            
            if bar.timestamp < session.current_date:
                continue
            
            session.current_date = bar.timestamp
            
            # Update positions with current price
            for pos in session.positions:
                if pos['status'] == 'OPEN':
                    pos['current_price'] = bar.close
                    pos['pnl'] = (bar.close - pos['entry_price']) * pos['size']
                    if pos['side'] == 'SELL':
                        pos['pnl'] = -pos['pnl']
            
            self._trigger_callback('on_bar', session, bar)
            
            # Sleep based on speed
            if session.speed != ReplaySpeed.PAUSED:
                sleep_time = 1.0 / session.speed.value
                time.sleep(sleep_time)
        
        session.state = ReplayState.FINISHED
        self._trigger_callback('on_state_change', session, ReplayState.FINISHED)
    
    def register_callback(self, event: str, callback: Callable):
        """Register a callback for replay events."""
        if event in self.callbacks:
            self.callbacks[event].append(callback)
    
    def _trigger_callback(self, event: str, *args):
        """Trigger registered callbacks."""
        for callback in self.callbacks.get(event, []):
            try:
                callback(*args)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def get_session_summary(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get summary of replay session."""
        session = self._get_session(session_id)
        if not session:
            return {}
        
        return {
            'session_id': session.session_id,
            'symbol': session.symbol,
            'timeframe': session.timeframe,
            'state': session.state.value,
            'speed': session.speed.name,
            'start_date': session.start_date.isoformat(),
            'end_date': session.end_date.isoformat(),
            'current_date': session.current_date.isoformat(),
            'initial_balance': session.initial_balance,
            'current_balance': session.current_balance,
            'pnl': session.current_balance - session.initial_balance,
            'pnl_percent': ((session.current_balance / session.initial_balance) - 1) * 100,
            'total_trades': len(session.trades),
            'open_positions': len([p for p in session.positions if p['status'] == 'OPEN']),
        }


def create_replay_router(engine: 'ChartReplayEngine'):
    """
    Create a FastAPI router for the Chart Replay Engine module.

    Args:
        engine: ChartReplayEngine instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import Optional

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
        price: Optional[float] = None
        stop_loss: Optional[float] = None
        take_profit: Optional[float] = None

    @router.post("/sessions")
    async def create_session(req: CreateSessionRequest):
        """Create a new replay session."""
        from datetime import datetime
        try:
            start = datetime.fromisoformat(req.start_date)
            end = datetime.fromisoformat(req.end_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {exc}")
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


# Module exports
__all__ = [
    'ChartReplayEngine',
    'ReplaySession',
    'ReplayBar',
    'ReplaySpeed',
    'ReplayState',
    'create_replay_router',
]
