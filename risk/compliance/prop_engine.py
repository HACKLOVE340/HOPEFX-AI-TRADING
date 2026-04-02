# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/compliance/prop_engine.py
==============================
Prop-firm compliance engine.

Loads rules from prop_firm_mode.json and enforces:
  - Daily drawdown limit (default 5 %)
  - Maximum total drawdown (default 10 %)
  - News blackout window (default ±5 min around high-impact events)
  - Weekend auto-close (Friday 21:00 UTC → Monday 00:00 UTC)
  - Trailing high-water mark for drawdown calculation
  - Kill-switch + Telegram alert on breach

Config file schema (prop_firm_mode.json):
  {
    "daily_dd": 0.05,
    "max_dd": 0.10,
    "news_blackout": 5,
    "weekend_close": true,
    "breach_action": "pause",
    "telegram_token": "...",
    "telegram_chat_id": "..."
  }
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time, timezone

UTC = timezone.utc
from enum import Enum, auto
from pathlib import Path
from collections.abc import Callable

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class PropFirmConfig:
    daily_dd: float = 0.05  # Max daily drawdown fraction
    max_dd: float = 0.10  # Max total drawdown fraction
    news_blackout: int = 5  # Minutes before/after high-impact news
    weekend_close: bool = True  # Auto-close before weekend
    breach_action: str = "pause"  # "pause" | "liquidate"
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @classmethod
    def from_file(cls, path: str | Path = "prop_firm_mode.json") -> PropFirmConfig:
        """Load config from JSON file; fall back to defaults if file absent."""
        p = Path(path)
        if not p.exists():
            logger.warning("prop_firm_mode.json not found — using defaults")
            return cls()
        with p.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(
            daily_dd=data.get("daily_dd", 0.05),
            max_dd=data.get("max_dd", 0.10),
            news_blackout=data.get("news_blackout", 5),
            weekend_close=data.get("weekend_close", True),
            breach_action=data.get("breach_action", "pause"),
            telegram_token=data.get("telegram_token", ""),
            telegram_chat_id=data.get("telegram_chat_id", ""),
        )


# ---------------------------------------------------------------------------
# Breach types
# ---------------------------------------------------------------------------


class BreachType(Enum):
    DAILY_DD = auto()
    MAX_DD = auto()
    NEWS_BLACKOUT = auto()
    WEEKEND = auto()


# ---------------------------------------------------------------------------
# Kill-switch
# ---------------------------------------------------------------------------


class KillSwitch:
    """Thread-safe kill-switch that halts all order flow."""

    def __init__(self) -> None:
        self._active = threading.Event()

    def activate(self, reason: str = "") -> None:
        self._active.set()
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    def deactivate(self) -> None:
        self._active.clear()
        logger.info("Kill switch deactivated")

    @property
    def is_active(self) -> bool:
        return self._active.is_set()


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class PropComplianceEngine:
    """
    Enforces prop-firm trading rules before every order.

    Usage:
        engine = PropComplianceEngine.from_config_file()
        engine.update_equity(current_equity)

        # In order flow:
        allowed, reason = engine.before_order(news_events=[...])
        if not allowed:
            return  # blocked

    The engine resets daily P&L at UTC 00:00 via a background thread.
    """

    def __init__(
        self,
        config: PropFirmConfig,
        initial_equity: float = 100_000.0,
        on_breach: Callable[[BreachType, str], None] | None = None,
    ) -> None:
        self.cfg = config
        self.kill_switch = KillSwitch()
        self._on_breach = on_breach

        # Equity tracking
        self._lock = threading.RLock()
        self._initial_equity = initial_equity
        self._high_water_mark = initial_equity  # trailing HWM for max DD
        self._day_start_equity = initial_equity  # reset daily
        self._current_equity = initial_equity

        # Pause flag (softer than kill-switch; re-enabled after reset)
        self._paused = False

        # Scheduled news events: list of UTC datetime objects
        self._news_events: list[datetime] = []

        # Start daily reset thread
        self._reset_thread = threading.Thread(
            target=self._daily_reset_loop,
            daemon=True,
            name="PropDailyReset",
        )
        self._reset_thread.start()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config_file(
        cls,
        path: str | Path = "prop_firm_mode.json",
        initial_equity: float = 100_000.0,
    ) -> PropComplianceEngine:
        cfg = PropFirmConfig.from_file(path)
        return cls(cfg, initial_equity)

    # ------------------------------------------------------------------
    # Equity updates
    # ------------------------------------------------------------------

    def update_equity(self, equity: float) -> None:
        """Call after every fill or mark-to-market update."""
        with self._lock:
            self._current_equity = equity
            self._high_water_mark = max(self._high_water_mark, equity)

    # ------------------------------------------------------------------
    # News calendar
    # ------------------------------------------------------------------

    def set_news_events(self, events: list[datetime]) -> None:
        """Register upcoming high-impact news event timestamps (UTC)."""
        with self._lock:
            self._news_events = sorted(events)

    # ------------------------------------------------------------------
    # Pre-order gate
    # ------------------------------------------------------------------

    def before_order(
        self,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """
        Call before placing any order.

        Returns:
            (True, "") if order is allowed.
            (False, reason) if blocked; also triggers kill-switch/pause.
        """
        now = now or datetime.now(UTC)

        if self.kill_switch.is_active:
            return False, "Kill switch active"

        if self._paused:
            return False, "Trading paused by compliance engine"

        with self._lock:
            # 1. Daily drawdown check
            daily_dd = self._daily_drawdown()
            if daily_dd >= self.cfg.daily_dd:
                self._breach(
                    BreachType.DAILY_DD,
                    f"Daily DD {daily_dd:.2%} ≥ limit {self.cfg.daily_dd:.2%}",
                )
                return False, f"Daily drawdown limit breached ({daily_dd:.2%})"

            # 2. Max total drawdown check
            total_dd = self._total_drawdown()
            if total_dd >= self.cfg.max_dd:
                self._breach(
                    BreachType.MAX_DD,
                    f"Total DD {total_dd:.2%} ≥ limit {self.cfg.max_dd:.2%}",
                )
                return False, f"Max drawdown limit breached ({total_dd:.2%})"

            # 3. News blackout
            if self._in_news_blackout(now):
                self._breach(
                    BreachType.NEWS_BLACKOUT,
                    "High-impact news blackout window",
                )
                return False, "News blackout window active"

            # 4. Weekend close
            if self.cfg.weekend_close and self._is_weekend_window(now):
                self._breach(BreachType.WEEKEND, "Weekend trading window")
                return False, "Weekend — trading disabled"

        return True, ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _daily_drawdown(self) -> float:
        """Drawdown from today's opening equity."""
        if self._day_start_equity <= 0:
            return 0.0
        loss = self._day_start_equity - self._current_equity
        return max(loss / self._day_start_equity, 0.0)

    def _total_drawdown(self) -> float:
        """Drawdown from trailing high-water mark."""
        if self._high_water_mark <= 0:
            return 0.0
        loss = self._high_water_mark - self._current_equity
        return max(loss / self._high_water_mark, 0.0)

    def _in_news_blackout(self, now: datetime) -> bool:
        """True if `now` is within ±news_blackout minutes of any scheduled event."""
        from datetime import timedelta

        window = timedelta(minutes=self.cfg.news_blackout)
        return any(abs((now - event).total_seconds()) <= window.total_seconds() for event in self._news_events)

    def _is_weekend_window(self, now: datetime) -> bool:
        """
        True between Friday 21:00 UTC and Sunday 23:00 UTC.
        Forex markets close Friday ~21:00 UTC and reopen Sunday ~22:00 UTC.
        """
        weekday = now.weekday()  # 0=Mon … 6=Sun
        t = now.time()

        if weekday == 4 and t >= time(21, 0):  # Friday after 21:00
            return True
        if weekday == 5:  # Saturday
            return True
        return weekday == 6 and t < time(23, 0)  # Sunday before 23:00

    def _breach(self, breach_type: BreachType, detail: str) -> None:
        """Handle a compliance breach: pause/kill + alert."""
        logger.warning("Compliance breach [%s]: %s", breach_type.name, detail)

        if self.cfg.breach_action == "pause":
            self._paused = True
        else:
            self.kill_switch.activate(detail)

        self._send_telegram_alert(f"⚠️ PROP BREACH [{breach_type.name}]: {detail}")

        if self._on_breach:
            try:
                self._on_breach(breach_type, detail)
            except Exception:
                logger.exception("on_breach callback raised")

    def _send_telegram_alert(self, message: str) -> None:
        """Fire-and-forget Telegram notification."""
        token = self.cfg.telegram_token
        chat_id = self.cfg.telegram_chat_id
        if not token or not chat_id:
            return
        # URL is constructed from a server-side config token — not user input.
        url = f"https://api.telegram.org/bot{token}/sendMessage"  # nosec B310
        try:
            requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)  # nosec B113
        except Exception as exc:
            logger.warning("Telegram alert failed: %s", exc)

    # ------------------------------------------------------------------
    # Daily reset (runs in background thread)
    # ------------------------------------------------------------------

    def _daily_reset_loop(self) -> None:
        """
        Wakes at UTC 00:00 each day to reset daily equity baseline
        and clear the pause flag (breach_action='pause' only).
        """
        import time as _time

        while True:
            now = datetime.now(UTC)
            # Seconds until next midnight UTC
            next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            from datetime import timedelta

            next_midnight += timedelta(days=1)
            sleep_secs = (next_midnight - now).total_seconds()
            _time.sleep(max(sleep_secs, 1))

            with self._lock:
                self._day_start_equity = self._current_equity
                if self.cfg.breach_action == "pause":
                    self._paused = False
                    logger.info(
                        "Daily reset: pause cleared, day_start_equity=%.2f",
                        self._day_start_equity,
                    )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Return current compliance state as a plain dict."""
        with self._lock:
            return {
                "kill_switch": self.kill_switch.is_active,
                "paused": self._paused,
                "current_equity": self._current_equity,
                "high_water_mark": self._high_water_mark,
                "day_start_equity": self._day_start_equity,
                "daily_dd": round(self._daily_drawdown(), 6),
                "total_dd": round(self._total_drawdown(), 6),
                "daily_dd_limit": self.cfg.daily_dd,
                "max_dd_limit": self.cfg.max_dd,
            }
