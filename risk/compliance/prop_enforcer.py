# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/compliance/prop_enforcer.py
=================================
PropEnforcer middleware — enforces prop-firm trading rules before every order.

Loads rules from prop_firm_mode.json (or the path in PROP_FIRM_CONFIG env var).
Supports FTMO, Goat Funded, and any firm whose rules fit the schema.

Config schema (prop_firm_mode.json subset used here)
-----------------------------------------------------
{
  "daily_dd":        0.05,   // max daily drawdown fraction
  "max_dd":          0.10,   // max total drawdown fraction
  "news_blackout":   300,    // seconds before/after high-impact news to block
  "weekend_close":   true,   // auto-close Friday 21:00 UTC → Monday 00:00 UTC
  "breach_action":   "pause" // "pause" | "liquidate"
}

Usage
-----
    from risk.compliance.prop_enforcer import PropEnforcer

    enforcer = PropEnforcer()
    enforcer.update_balance(current_equity=98000, start_of_day_equity=100000)

    # Before every order:
    ok, reason = enforcer.before_execute(instrument="XAU_USD")
    if not ok:
        raise RuntimeError(f"Order blocked: {reason}")

    # UTC midnight reset (call from a scheduler):
    enforcer.daily_reset(new_equity=98000)

Thread-safety
-------------
All state mutations are protected by threading.Lock.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from datetime import time as dtime
from enum import Enum, auto
from pathlib import Path

logger = logging.getLogger(__name__)

# ── default config path ───────────────────────────────────────────────────────
_DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "prop_firm_mode.json"


# ── enums ─────────────────────────────────────────────────────────────────────


class BreachType(Enum):
    DAILY_DD = auto()
    TOTAL_DD = auto()
    NEWS_WINDOW = auto()
    WEEKEND = auto()
    KILL_SWITCH = auto()


class BreachAction(Enum):
    PAUSE = "pause"
    LIQUIDATE = "liquidate"


# ── config dataclass ──────────────────────────────────────────────────────────


@dataclass
class PropConfig:
    daily_dd: float = 0.05  # 5 % daily drawdown limit
    max_dd: float = 0.10  # 10 % total drawdown limit
    news_blackout: int = 300  # seconds (5 min) around high-impact news
    weekend_close: bool = True  # close before Friday 21:00 UTC
    breach_action: str = "pause"
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @classmethod
    def from_file(cls, path: Path = _DEFAULT_CONFIG) -> PropConfig:
        """
        Load from prop_firm_mode.json.
        Falls back to defaults if file is absent or malformed.
        Reads the flat keys (daily_dd, max_dd, …) used by the legacy schema
        AND the nested enforcement block used by the full schema.
        """
        if not path.exists():
            logger.warning("prop_firm_mode.json not found at %s — using defaults", path)
            return cls()
        try:
            raw = json.loads(path.read_text())
            # Support both flat and nested schemas
            enforcement = raw.get("enforcement", {})
            firms = raw.get("firms", {})
            active = raw.get("active_firm", "")
            firm_cfg = firms.get(active, {}) if active else {}
            dd_cfg = firm_cfg.get("drawdown", {})

            daily_dd = (
                raw.get("daily_dd")
                or enforcement.get("max_daily_drawdown_pct", 5.0) / 100
                or dd_cfg.get("max_daily_drawdown_pct", 5.0) / 100
            )
            max_dd = (
                raw.get("max_dd")
                or enforcement.get("max_total_drawdown_pct", 10.0) / 100
                or dd_cfg.get("max_total_drawdown_pct", 10.0) / 100
            )
            news_blackout = int(
                raw.get("news_blackout")
                or firm_cfg.get("news_trading", {}).get("blackout_minutes_before_news", 5) * 60
                or 300,
            )
            # weekend_close: explicit key wins; fall back to firm config.
            # weekend_holding_allowed=False means weekend_close=True (must close).
            if "weekend_close" in raw:
                weekend_close = bool(raw["weekend_close"])
            else:
                weekend_holding_allowed = firm_cfg.get("overnight_holding", {}).get("weekend_holding_allowed", True)
                weekend_close = not weekend_holding_allowed
            return cls(
                daily_dd=float(daily_dd),
                max_dd=float(max_dd),
                news_blackout=news_blackout,
                weekend_close=weekend_close,
                breach_action=raw.get("breach_action", "pause"),
                telegram_token=raw.get("telegram_token", os.environ.get("TELEGRAM_BOT_TOKEN", "")),
                telegram_chat_id=raw.get("telegram_chat_id", os.environ.get("TELEGRAM_CHAT_ID", "")),
            )
        except Exception as exc:
            logger.error("Failed to parse prop_firm_mode.json: %s — using defaults", exc)
            return cls()


# ── breach record ─────────────────────────────────────────────────────────────


@dataclass
class BreachRecord:
    breach_type: BreachType
    timestamp: str
    detail: str


# ── PropEnforcer ──────────────────────────────────────────────────────────────


class PropEnforcer:
    """
    Middleware that gates every order through prop-firm compliance rules.

    Lifecycle
    ---------
    1. Instantiate once at app startup.
    2. Call update_balance() on every account equity update.
    3. Call before_execute() before placing any order.
    4. Wire daily_reset() to a UTC 00:00 scheduler.
    5. Register on_breach callbacks for kill-switch / alert integration.
    """

    def __init__(
        self,
        config_path: Path = _DEFAULT_CONFIG,
        kill_switch_fn: Callable[[str], None] | None = None,
    ):
        self.cfg = PropConfig.from_file(config_path)
        self._lock = threading.Lock()

        # Balances
        self._start_balance: float = 0.0  # set on first update_balance call
        self._high_water_mark: float = 0.0  # trailing peak equity
        self._sod_equity: float = 0.0  # start-of-day equity (reset at UTC 00:00)
        self._current_equity: float = 0.0

        # State
        self._halted: bool = False
        self._halt_reason: str = ""
        self._breach_log: list[BreachRecord] = []
        self._news_events: list[float] = []  # UTC timestamps of upcoming news

        # Alert-sent flags — reset at daily_reset() to avoid repeated messages
        self._daily_alert_sent: bool = False
        self._total_alert_sent: bool = False

        # External kill-switch callback (e.g. KillSwitch.activate)
        self._kill_switch_fn = kill_switch_fn

        # Breach callbacks
        self._on_breach_callbacks: list[Callable[[BreachType, str], None]] = []

        logger.info(
            "PropEnforcer loaded — daily_dd=%.1f%% max_dd=%.1f%% news_blackout=%ds weekend_close=%s",
            self.cfg.daily_dd * 100,
            self.cfg.max_dd * 100,
            self.cfg.news_blackout,
            self.cfg.weekend_close,
        )

    # ── public API ────────────────────────────────────────────────────────────

    def update_balance(self, current_equity: float, start_of_day_equity: float | None = None) -> None:
        """
        Update equity state. Call on every account snapshot.

        Fires a Telegram warning (non-halting) when daily drawdown reaches
        80% of the configured daily limit (alert_pct_of_limit = 0.80 by default).
        The alert is sent at most once per trading day; daily_reset() clears it.

        Parameters
        ----------
        current_equity      : latest floating equity
        start_of_day_equity : if provided, overrides the stored SOD value
                              (use on first call of the day)
        """
        with self._lock:
            self._current_equity = current_equity
            if self._start_balance == 0:
                self._start_balance = current_equity
                self._high_water_mark = current_equity
                self._sod_equity = current_equity
            if start_of_day_equity is not None:
                self._sod_equity = start_of_day_equity
            self._high_water_mark = max(self._high_water_mark, current_equity)

            # ── 80% daily drawdown warning alert ─────────────────────────────
            # Fires once when daily DD reaches 80% of the limit (non-halting).
            # Uses a small epsilon to avoid float precision misses at exactly 80%.
            _ALERT_EPSILON = 1e-9
            if self._sod_equity > 0 and not self._daily_alert_sent:
                daily_dd = (self._sod_equity - self._current_equity) / self._sod_equity
                alert_threshold = self.cfg.daily_dd * 0.80 - _ALERT_EPSILON
                if daily_dd >= alert_threshold and daily_dd < self.cfg.daily_dd:
                    self._daily_alert_sent = True
                    detail = (
                        f"Daily drawdown at {daily_dd * 100:.2f}% — "
                        f"approaching {self.cfg.daily_dd * 100:.1f}% limit "
                        f"(SOD={self._sod_equity:.2f} current={self._current_equity:.2f}). "
                        f"Remaining buffer: {(self.cfg.daily_dd - daily_dd) * self._sod_equity:.2f}"
                    )
                    logger.warning("PropEnforcer 80%% daily DD alert: %s", detail)
                    self._send_telegram_warning(detail)

            # ── 80% total drawdown warning alert ─────────────────────────────
            if self._high_water_mark > 0 and not self._total_alert_sent:
                total_dd = (self._high_water_mark - self._current_equity) / self._high_water_mark
                alert_threshold = self.cfg.max_dd * 0.80 - _ALERT_EPSILON
                if total_dd >= alert_threshold and total_dd < self.cfg.max_dd:
                    self._total_alert_sent = True
                    detail = (
                        f"Total drawdown at {total_dd * 100:.2f}% — "
                        f"approaching {self.cfg.max_dd * 100:.1f}% limit "
                        f"(HWM={self._high_water_mark:.2f} current={self._current_equity:.2f}). "
                        f"Remaining buffer: {(self.cfg.max_dd - total_dd) * self._high_water_mark:.2f}"
                    )
                    logger.warning("PropEnforcer 80%% total DD alert: %s", detail)
                    self._send_telegram_warning(detail)

    def daily_reset(self, new_equity: float) -> None:
        """
        UTC 00:00 reset — update high-water mark and SOD equity.
        Wire to a scheduler (APScheduler, asyncio task, or cron).
        """
        with self._lock:
            self._sod_equity = new_equity
            self._high_water_mark = max(self._high_water_mark, new_equity)
            # Clear daily halt if it was a daily-DD breach (total-DD stays)
            if self._halted and self._halt_reason.startswith("DAILY_DD"):
                self._halted = False
                self._halt_reason = ""
                logger.info("Daily reset — daily-DD halt cleared")
            # Reset daily alert flag so the warning fires again next session
            self._daily_alert_sent = False
        logger.info(
            "PropEnforcer daily reset | SOD equity=%.2f HWM=%.2f",
            new_equity,
            self._high_water_mark,
        )

    def register_news_event(self, utc_timestamp: float) -> None:
        """Register a high-impact news event (Unix UTC timestamp)."""
        with self._lock:
            self._news_events.append(utc_timestamp)

    def register_on_breach(self, callback: Callable[[BreachType, str], None]) -> None:
        """Register a callback invoked on every breach (breach_type, detail)."""
        self._on_breach_callbacks.append(callback)

    def before_execute(self, instrument: str = "") -> tuple[bool, str]:
        """
        Gate check — call before placing any order.

        Returns
        -------
        (True, "")           — order is allowed
        (False, reason_str)  — order is blocked; reason explains why
        """
        with self._lock:
            # 1. Already halted
            if self._halted:
                return False, f"Trading halted: {self._halt_reason}"

            now_utc = datetime.now(UTC)

            # 2. Weekend window check
            if self.cfg.weekend_close and self._is_weekend_window(now_utc):
                reason = "Weekend trading window — positions must be closed (Fri 21:00–Mon 00:00 UTC)"
                self._trigger_breach(BreachType.WEEKEND, reason, halt=False)
                return False, reason

            # 3. News blackout check
            if self._is_news_blackout(now_utc.timestamp()):
                reason = f"News blackout window ({self.cfg.news_blackout}s around high-impact event)"
                self._trigger_breach(BreachType.NEWS_WINDOW, reason, halt=False)
                return False, reason

            # 4. Daily drawdown check
            if self._sod_equity > 0:
                daily_dd = (self._sod_equity - self._current_equity) / self._sod_equity
                if daily_dd >= self.cfg.daily_dd:
                    reason = (
                        f"DAILY_DD breach: {daily_dd * 100:.2f}% >= {self.cfg.daily_dd * 100:.1f}% limit "
                        f"(SOD={self._sod_equity:.2f} current={self._current_equity:.2f})"
                    )
                    self._trigger_breach(BreachType.DAILY_DD, reason, halt=True)
                    return False, reason

            # 5. Total drawdown check (from high-water mark)
            if self._high_water_mark > 0:
                total_dd = (self._high_water_mark - self._current_equity) / self._high_water_mark
                if total_dd >= self.cfg.max_dd:
                    reason = (
                        f"TOTAL_DD breach: {total_dd * 100:.2f}% >= {self.cfg.max_dd * 100:.1f}% limit "
                        f"(HWM={self._high_water_mark:.2f} current={self._current_equity:.2f})"
                    )
                    self._trigger_breach(BreachType.TOTAL_DD, reason, halt=True)
                    return False, reason

        return True, ""

    def status(self) -> dict:
        """Return current enforcer state as a dict (for API/health endpoints)."""
        with self._lock:
            daily_dd = (self._sod_equity - self._current_equity) / self._sod_equity if self._sod_equity > 0 else 0.0
            total_dd = (
                (self._high_water_mark - self._current_equity) / self._high_water_mark
                if self._high_water_mark > 0
                else 0.0
            )
            return {
                "halted": self._halted,
                "halt_reason": self._halt_reason,
                "current_equity": self._current_equity,
                "high_water_mark": self._high_water_mark,
                "sod_equity": self._sod_equity,
                "daily_dd_pct": round(daily_dd * 100, 4),
                "total_dd_pct": round(total_dd * 100, 4),
                "daily_dd_limit": self.cfg.daily_dd * 100,
                "total_dd_limit": self.cfg.max_dd * 100,
                "breach_count": len(self._breach_log),
                "last_breach": self._breach_log[-1].__dict__ if self._breach_log else None,
            }

    # ── internal helpers ──────────────────────────────────────────────────────

    def _is_weekend_window(self, now: datetime) -> bool:
        """True between Friday 21:00 UTC and Monday 00:00 UTC."""
        weekday = now.weekday()  # 0=Mon … 6=Sun
        t = now.time()
        if weekday == 4 and t >= dtime(21, 0):  # Friday after 21:00
            return True
        if weekday == 5:  # Saturday
            return True
        return weekday == 6 and t < dtime(0, 1)  # Sunday before 00:01

    def _is_news_blackout(self, now_ts: float) -> bool:
        """True if now is within news_blackout seconds of any registered event."""
        window = self.cfg.news_blackout
        # Purge stale events (> 2× window in the past)
        self._news_events = [e for e in self._news_events if e > now_ts - window * 2]
        return any(abs(now_ts - event_ts) <= window for event_ts in self._news_events)

    def _trigger_breach(self, breach_type: BreachType, detail: str, halt: bool) -> None:
        """Record breach, optionally halt, fire callbacks, send Telegram alert."""
        record = BreachRecord(
            breach_type=breach_type,
            timestamp=datetime.now(UTC).isoformat(),
            detail=detail,
        )
        self._breach_log.append(record)
        logger.warning("PropEnforcer breach [%s]: %s", breach_type.name, detail)

        if halt:
            self._halted = True
            self._halt_reason = detail
            # Fire external kill switch
            if self._kill_switch_fn:
                try:
                    self._kill_switch_fn(detail)
                except Exception as exc:
                    logger.error("Kill switch callback failed: %s", exc)

        # Fire registered callbacks
        for cb in self._on_breach_callbacks:
            try:
                cb(breach_type, detail)
            except Exception as exc:
                logger.error("Breach callback error: %s", exc)

        # Telegram alert
        self._send_telegram_alert(breach_type, detail)

    def _send_telegram_warning(self, detail: str) -> None:
        """
        Send a non-halting Telegram warning (80% drawdown threshold reached).
        Uses the same token/chat_id as breach alerts but with a warning emoji.
        """
        token = self.cfg.telegram_token
        chat_id = self.cfg.telegram_chat_id
        if not token or not chat_id:
            return
        try:
            import urllib.parse
            import urllib.request

            text = (
                f"⚠️ <b>HOPEFX PropEnforcer — DRAWDOWN WARNING</b>\n"
                f"{detail}\n"
                f"Time: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"<i>Trading continues — monitor closely.</i>"
            )
            data = urllib.parse.urlencode(
                {"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            ).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=8)  # nosec B310 - URL is always https://api.telegram.org
        except Exception as exc:
            logger.warning("PropEnforcer Telegram warning failed: %s", exc)

    def _send_telegram_alert(self, breach_type: BreachType, detail: str) -> None:
        token = self.cfg.telegram_token
        chat_id = self.cfg.telegram_chat_id
        if not token or not chat_id:
            return
        try:
            import urllib.parse
            import urllib.request

            emoji = {
                "DAILY_DD": "🔴",
                "TOTAL_DD": "🚨",
                "NEWS_WINDOW": "📰",
                "WEEKEND": "🌙",
                "KILL_SWITCH": "⛔",
            }.get(breach_type.name, "⚠️")
            text = (
                f"{emoji} <b>HOPEFX PropEnforcer — {breach_type.name}</b>\n"
                f"{detail}\n"
                f"Time: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            data = urllib.parse.urlencode(
                {"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            ).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=8)  # nosec B310 - webhook URL validated as https:// in config
        except Exception as exc:
            logger.warning("PropEnforcer Telegram alert failed: %s", exc)


# ── module-level singleton (optional convenience) ─────────────────────────────

_default_enforcer: PropEnforcer | None = None


def get_enforcer() -> PropEnforcer:
    """Return the module-level singleton, creating it on first call."""
    global _default_enforcer
    if _default_enforcer is None:
        _default_enforcer = PropEnforcer()
    return _default_enforcer
