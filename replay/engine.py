# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""replay/engine.py — ChartReplayEngine: step through historical bars."""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
UTC = timezone.utc
from typing import Any, ClassVar

from replay.models import ReplayBar, ReplaySession, ReplaySpeed, ReplayState

logger = logging.getLogger(__name__)


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

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize replay engine."""
        self.config = config or {}
        self.sessions: dict[str, ReplaySession] = {}
        self.active_session_id: str | None = None
        self.data_cache: dict[str, list[ReplayBar]] = {}
        self.callbacks: dict[str, list[Callable]] = {
            "on_bar": [],
            "on_trade": [],
            "on_state_change": [],
        }
        self._replay_thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

        logger.info("Chart Replay Engine initialized")

    def create_session(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float = 100000.0,
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
        session_id = f"replay_{len(self.sessions) + 1}_{int(datetime.now(UTC).timestamp())}"

        session = ReplaySession(
            session_id=session_id,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            current_date=start_date,
            initial_balance=initial_balance,
            current_balance=initial_balance,
        )

        self.sessions[session_id] = session
        self.active_session_id = session_id

        # Load historical data
        self._load_data(session)

        logger.info("Created replay session: %s for %s", session_id, symbol)

        return session

    def _load_data(self, session: ReplaySession):
        """Load historical data for replay session."""
        # In production, this would load from database or data provider
        # For now, generate sample data
        data_key = f"{session.symbol}_{session.timeframe}"

        if data_key not in self.data_cache:
            bars = self._generate_sample_data(session)
            self.data_cache[data_key] = bars

        logger.info("Loaded %s bars for %s", len(self.data_cache.get(data_key, [])), data_key)

    def _generate_sample_data(self, session: ReplaySession) -> list[ReplayBar]:
        """
        Generate bar data for replay.

        Attempts to fetch real historical data via yfinance; falls back to a
        simple random-walk simulation when yfinance is unavailable.
        """
        # ------------------------------------------------------------------
        # Try yfinance first
        # ------------------------------------------------------------------
        bars = self._fetch_yfinance_data(session)
        if bars:
            return bars

        # ------------------------------------------------------------------
        # Fallback: random-walk simulation
        # ------------------------------------------------------------------
        import random

        bars = []
        current_time = session.start_date
        price = 1950.0  # Starting price for XAUUSD

        # Map timeframe to timedelta
        tf_map = {
            "1M": timedelta(minutes=1),
            "5M": timedelta(minutes=5),
            "15M": timedelta(minutes=15),
            "30M": timedelta(minutes=30),
            "1H": timedelta(hours=1),
            "4H": timedelta(hours=4),
            "1D": timedelta(days=1),
        }
        delta = tf_map.get(session.timeframe, timedelta(hours=1))

        while current_time <= session.end_date:
            change = random.uniform(-0.5, 0.5)  # nosec B311 - replay bar generation, not cryptographic
            open_price = price
            close_price = price + change
            high_price = max(open_price, close_price) + random.uniform(0, 0.3)  # nosec B311 - replay bar generation, not cryptographic
            low_price = min(open_price, close_price) - random.uniform(0, 0.3)  # nosec B311 - replay bar generation, not cryptographic
            volume = random.uniform(1000, 10000)  # nosec B311 - replay bar generation, not cryptographic

            bars.append(
                ReplayBar(
                    timestamp=current_time,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                )
            )

            price = close_price
            current_time += delta

        return bars

    def _fetch_yfinance_data(self, session: ReplaySession) -> list[ReplayBar]:
        """
        Fetch real OHLCV data from yfinance for the replay session.

        Returns an empty list if yfinance is not installed or the download fails.
        """
        try:
            import yfinance as yf

            # Map internal symbol to yfinance ticker (e.g. XAUUSD → GC=F)
            _SYMBOL_MAP: dict[str, str] = {
                "XAUUSD": "GC=F",
                "XAGUSD": "SI=F",
                "EURUSD": "EURUSD=X",
                "GBPUSD": "GBPUSD=X",
                "USDJPY": "JPY=X",
            }
            ticker = _SYMBOL_MAP.get(session.symbol.upper(), session.symbol)

            # Map replay timeframe to yfinance interval
            _TF_MAP: dict[str, str] = {
                "1M": "1m",
                "5M": "5m",
                "15M": "15m",
                "30M": "30m",
                "1H": "1h",
                "4H": "1h",  # yfinance has no 4H; use 1H and downsample if needed
                "1D": "1d",
            }
            interval = _TF_MAP.get(session.timeframe, "1d")

            logger.info(
                "Fetching %s [%s] %s → %s via yfinance",
                ticker,
                interval,
                session.start_date.date(),
                session.end_date.date(),
            )
            df = yf.download(
                ticker,
                start=session.start_date,
                end=session.end_date,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )

            if df is None or df.empty:
                logger.warning("yfinance returned no data for %s", ticker)

                return []

            bars: ClassVar[list[ReplayBar]] = []
            for ts, row in df.iterrows():
                bars.append(
                    ReplayBar(
                        timestamp=ts.to_pydatetime(),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume", 0)),
                    )
                )

            logger.info("Loaded %s bars from yfinance for %s", len(bars), ticker)

            return bars

        except ImportError:
            logger.warning("yfinance not installed — using simulated replay data.")
            return []
        except Exception as exc:
            logger.warning("yfinance fetch failed (%s) — using simulated replay data.", exc)

            return []

    def play(self, session_id: str | None = None) -> bool:
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
        self._replay_thread = threading.Thread(target=self._replay_loop, args=(session,), daemon=True)
        self._replay_thread.start()

        self._trigger_callback("on_state_change", session, ReplayState.PLAYING)
        logger.info("Started replay: %s", session.session_id)

        return True

    def pause(self, session_id: str | None = None) -> bool:
        """Pause replay."""
        session = self._get_session(session_id)
        if not session:
            return False

        session.state = ReplayState.PAUSED
        self._stop_flag.set()

        self._trigger_callback("on_state_change", session, ReplayState.PAUSED)
        logger.info("Paused replay: %s", session.session_id)

        return True

    def stop(self, session_id: str | None = None) -> bool:
        """Stop replay."""
        session = self._get_session(session_id)
        if not session:
            return False

        session.state = ReplayState.FINISHED
        self._stop_flag.set()

        self._trigger_callback("on_state_change", session, ReplayState.FINISHED)
        logger.info("Stopped replay: %s", session.session_id)

        return True

    def set_speed(self, speed: ReplaySpeed, session_id: str | None = None) -> bool:
        """Set replay speed."""
        session = self._get_session(session_id)
        if not session:
            return False

        session.speed = speed
        logger.info("Set replay speed to %s", speed.name)

        return True

    def seek(self, target_date: datetime, session_id: str | None = None) -> bool:
        """Seek to a specific date in the replay."""
        session = self._get_session(session_id)
        if not session:
            return False

        if target_date < session.start_date or target_date > session.end_date:
            logger.warning("Target date out of range")
            return False

        session.current_date = target_date
        logger.info("Seeked to %s", target_date)

        return True

    def place_practice_order(
        self,
        side: str,
        size: float,
        order_type: str = "MARKET",
        price: float | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
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
            "trade_id": f"trade_{len(session.trades) + 1}",
            "timestamp": session.current_date,
            "symbol": session.symbol,
            "side": side,
            "size": size,
            "price": execution_price,
            "order_type": order_type,
            "pnl": 0.0,
            "status": "FILLED",
        }

        session.trades.append(trade)

        # Update position
        self._update_position(session, trade)

        self._trigger_callback("on_trade", session, trade)
        logger.info("Practice trade executed: %s %s @ %s", side, size, execution_price)

        return trade

    def _get_session(self, session_id: str | None) -> ReplaySession | None:
        """Get session by ID or active session."""
        if session_id:
            return self.sessions.get(session_id)
        if self.active_session_id:
            return self.sessions.get(self.active_session_id)
        return None

    def _get_current_bar(self, session: ReplaySession) -> ReplayBar | None:
        """Get the current bar in replay."""
        data_key = f"{session.symbol}_{session.timeframe}"
        bars = self.data_cache.get(data_key, [])

        for bar in bars:
            if bar.timestamp >= session.current_date:
                return bar
        return bars[-1] if bars else None

    def _update_position(self, session: ReplaySession, trade: dict[str, Any]):
        """Update session positions based on trade."""
        # Find existing position
        existing_pos = None
        for pos in session.positions:
            if pos["symbol"] == trade["symbol"] and pos["status"] == "OPEN":
                existing_pos = pos
                break

        if existing_pos:
            # Update or close existing position
            if existing_pos["side"] == trade["side"]:
                # Add to position
                existing_pos["size"] += trade["size"]
            else:
                # Reduce or close position
                existing_pos["size"] -= trade["size"]
                if existing_pos["size"] <= 0:
                    existing_pos["status"] = "CLOSED"
                    pnl = (trade["price"] - existing_pos["entry_price"]) * abs(existing_pos["size"])
                    if existing_pos["side"] == "SELL":
                        pnl = -pnl
                    existing_pos["pnl"] = pnl
                    session.current_balance += pnl
        else:
            # Create new position
            session.positions.append(
                {
                    "position_id": f"pos_{len(session.positions) + 1}",
                    "symbol": trade["symbol"],
                    "side": trade["side"],
                    "size": trade["size"],
                    "entry_price": trade["price"],
                    "current_price": trade["price"],
                    "pnl": 0.0,
                    "status": "OPEN",
                }
            )

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
                if pos["status"] == "OPEN":
                    pos["current_price"] = bar.close
                    pos["pnl"] = (bar.close - pos["entry_price"]) * pos["size"]
                    if pos["side"] == "SELL":
                        pos["pnl"] = -pos["pnl"]

            self._trigger_callback("on_bar", session, bar)

            # Sleep based on speed
            if session.speed != ReplaySpeed.PAUSED:
                sleep_time = 1.0 / session.speed.value
                time.sleep(sleep_time)

        session.state = ReplayState.FINISHED
        self._trigger_callback("on_state_change", session, ReplayState.FINISHED)

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
                logger.error("Callback error: %s", e)

    def get_session_summary(self, session_id: str | None = None) -> dict[str, Any]:
        """Get summary of replay session."""
        session = self._get_session(session_id)
        if not session:
            return {}

        return {
            "session_id": session.session_id,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "state": session.state.value,
            "speed": session.speed.name,
            "start_date": session.start_date.isoformat(),
            "end_date": session.end_date.isoformat(),
            "current_date": session.current_date.isoformat(),
            "initial_balance": session.initial_balance,
            "current_balance": session.current_balance,
            "pnl": session.current_balance - session.initial_balance,
            "pnl_percent": ((session.current_balance / session.initial_balance) - 1) * 100,
            "total_trades": len(session.trades),
            "open_positions": len([p for p in session.positions if p["status"] == "OPEN"]),
        }
