#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/paper_trading_starter.py
=================================
One-command 30-day OANDA paper trading runner for HOPEFX.

Usage
-----
    python scripts/paper_trading_starter.py

What it does
------------
1. Loads credentials from .env (OANDA_API_KEY, OANDA_ACCOUNT_ID, TELEGRAM_*)
2. Connects to OANDA practice environment
3. Runs the hopefx_engine loop for up to 30 days
4. Logs every trade, drawdown, and slippage to data/paper_trades.csv
5. Sends a Telegram summary every 24 h
6. Hard-stops if drawdown exceeds 3 % of starting equity
7. Writes data/oanda_paper_start.json on first run (backup anchor)

Environment variables (all read from .env)
------------------------------------------
OANDA_API_KEY          — OANDA practice API key
OANDA_ACCOUNT_ID       — OANDA practice account ID
OANDA_ENVIRONMENT      — "practice" (default)
TELEGRAM_BOT_TOKEN     — Telegram bot token for daily alerts
TELEGRAM_CHAT_ID       — Telegram chat/channel ID
PAPER_MAX_DD_PCT       — Kill threshold (default 0.03 = 3 %)
PAPER_DURATION_DAYS    — Run duration in days (default 30)
OANDA_INSTRUMENTS      — Comma-separated instruments (default XAU_USD,EUR_USD)
"""

from __future__ import annotations

import csv
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── dotenv ────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv optional; env vars may already be set

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("paper_starter")

# ── constants ─────────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

TRADES_CSV = DATA_DIR / "paper_trades.csv"
START_JSON = DATA_DIR / "oanda_paper_start.json"
STATUS_JSON = DATA_DIR / "paper_trading_status.json"

CSV_HEADERS = [
    "timestamp",
    "instrument",
    "side",
    "units",
    "entry_price",
    "exit_price",
    "pnl",
    "slippage_pips",
    "drawdown_pct",
    "balance",
]

OANDA_BASE = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


# ── helpers ───────────────────────────────────────────────────────────────────


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _require(key: str) -> str:
    val = _env(key)
    if not val:
        logger.error("Missing required env var: %s", key)
        sys.exit(1)
    return val


# ── Telegram alert ────────────────────────────────────────────────────────────


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message; returns True on success."""
    if not token or not chat_id:
        logger.warning("Telegram not configured — skipping alert")
        return False
    try:
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - API URL is always https://
            return resp.status == 200
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


# ── OANDA REST helpers ────────────────────────────────────────────────────────


class OANDAPaperClient:
    """Minimal OANDA v20 REST client for paper trading."""

    def __init__(self, api_key: str, account_id: str, environment: str = "practice"):
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = OANDA_BASE.get(environment, OANDA_BASE["practice"])
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> dict[str, Any]:
        import urllib.request

        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers=self._headers)
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 - API URL is always https://
            return json.loads(resp.read())

    def _post(self, path: str, body: dict) -> dict[str, Any]:
        import urllib.request

        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 - API URL is always https://
            return json.loads(resp.read())

    def get_account(self) -> dict[str, Any]:
        return self._get(f"/v3/accounts/{self.account_id}/summary")

    def get_price(self, instrument: str) -> float | None:
        try:
            resp = self._get(f"/v3/accounts/{self.account_id}/pricing?instruments={instrument}")
            prices = resp.get("prices", [])
            if prices:
                bid = float(prices[0].get("bids", [{}])[0].get("price", 0))
                ask = float(prices[0].get("asks", [{}])[0].get("price", 0))
                return (bid + ask) / 2
        except Exception as exc:
            logger.warning("Price fetch failed for %s: %s", instrument, exc)
        return None

    def place_market_order(self, instrument: str, units: int) -> dict[str, Any]:
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        return self._post(f"/v3/accounts/{self.account_id}/orders", body)

    def close_all_positions(self) -> None:
        try:
            positions = self._get(f"/v3/accounts/{self.account_id}/openPositions")
            for pos in positions.get("positions", []):
                instrument = pos["instrument"]
                long_units = int(pos.get("long", {}).get("units", 0))
                short_units = int(pos.get("short", {}).get("units", 0))
                if long_units > 0:
                    self.place_market_order(instrument, -long_units)
                if short_units < 0:
                    self.place_market_order(instrument, abs(short_units))
        except Exception as exc:
            logger.error("Failed to close positions: %s", exc)


# ── CSV logger ────────────────────────────────────────────────────────────────


class TradeLogger:
    def __init__(self, path: Path = TRADES_CSV):
        self.path = path
        self._init_csv()

    def _init_csv(self) -> None:
        if not self.path.exists():
            with Path(self.path).open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()

    def log(self, record: dict[str, Any]) -> None:
        with Path(self.path).open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writerow({k: record.get(k, "") for k in CSV_HEADERS})


# ── Status writer ─────────────────────────────────────────────────────────────


def write_status(data: dict[str, Any]) -> None:
    """Write /api/status/paper-trading compatible JSON."""
    payload = {**data, "updated_at": datetime.now(UTC).isoformat()}
    STATUS_JSON.write_text(json.dumps(payload, indent=2))


# ── Main engine loop ──────────────────────────────────────────────────────────


class PaperTradingRunner:
    """
    Runs a 30-day paper trading session against OANDA practice.

    Signals are generated by a simple momentum rule (price vs 20-bar SMA)
    as a stand-in until hopefx_engine is fully wired. Replace
    _generate_signal() with the real engine call when ready.
    """

    def __init__(self):
        self.api_key = _require("OANDA_API_KEY")
        self.account_id = _require("OANDA_ACCOUNT_ID")
        self.environment = _env("OANDA_ENVIRONMENT", "practice")
        self.tg_token = _env("TELEGRAM_BOT_TOKEN")
        self.tg_chat = _env("TELEGRAM_CHAT_ID")
        self.max_dd_pct = float(_env("PAPER_MAX_DD_PCT", "0.03"))
        self.duration_s = float(_env("PAPER_DURATION_DAYS", "30")) * 86400
        self.instruments = [i.strip() for i in _env("OANDA_INSTRUMENTS", "XAU_USD,EUR_USD").split(",")]
        self.poll_interval = 60  # seconds between signal checks

        self.client = OANDAPaperClient(self.api_key, self.account_id, self.environment)
        self.trade_logger = TradeLogger()

        self.start_balance: float = 0.0
        self.peak_balance: float = 0.0
        self.current_balance: float = 0.0
        self.trade_count: int = 0
        self.start_time: float = time.time()
        self._price_history: dict[str, list[float]] = {i: [] for i in self.instruments}
        self._running = True

        # Graceful shutdown on SIGINT/SIGTERM
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

    def _handle_stop(self, *_) -> None:
        logger.info("Shutdown signal received — closing positions")
        self._running = False

    # ── account bootstrap ─────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        logger.info("Connecting to OANDA %s …", self.environment)
        summary = self.client.get_account()
        acct = summary.get("account", {})
        self.start_balance = float(acct.get("balance", 0))
        self.peak_balance = self.start_balance
        self.current_balance = self.start_balance

        if self.start_balance == 0:
            logger.error("Account balance is 0 — check OANDA credentials")
            sys.exit(1)

        logger.info(
            "Account %s | Balance: %.2f %s",
            self.account_id,
            self.start_balance,
            acct.get("currency", "USD"),
        )

        # Write start anchor (backup)
        if not START_JSON.exists():
            anchor = {
                "account_id": self.account_id,
                "start_balance": self.start_balance,
                "start_time": datetime.now(UTC).isoformat(),
                "environment": self.environment,
                "instruments": self.instruments,
            }
            START_JSON.write_text(json.dumps(anchor, indent=2))
            logger.info("Wrote start anchor → %s", START_JSON)

        write_status(
            {
                "complete": False,
                "start_balance": self.start_balance,
                "current_balance": self.start_balance,
                "drawdown_pct": 0.0,
                "trade_count": 0,
                "elapsed_days": 0.0,
            }
        )

    # ── signal generation (momentum) ─────────────────────────────────────────

    def _generate_signal(self, instrument: str, price: float) -> str | None:
        """
        Simple 20-bar SMA momentum signal.
        Returns "BUY", "SELL", or None.
        Replace with hopefx_engine.generate_signal() for production.
        """
        history = self._price_history[instrument]
        history.append(price)
        if len(history) > 20:
            history.pop(0)
        if len(history) < 20:
            return None
        sma = sum(history) / len(history)
        if price > sma * 1.001:
            return "BUY"
        if price < sma * 0.999:
            return "SELL"
        return None

    # ── drawdown check ────────────────────────────────────────────────────────

    def _check_drawdown(self) -> float:
        """Returns current drawdown fraction from peak. Triggers kill if > max."""
        if self.peak_balance == 0:
            return 0.0
        dd = (self.peak_balance - self.current_balance) / self.peak_balance
        if dd > self.max_dd_pct:
            logger.critical(
                "DRAWDOWN BREACH: %.2f%% > %.2f%% limit — activating kill switch",
                dd * 100,
                self.max_dd_pct * 100,
            )
            self.client.close_all_positions()
            send_telegram(
                self.tg_token,
                self.tg_chat,
                f"🚨 <b>HOPEFX KILL SWITCH</b>\n"
                f"Drawdown {dd * 100:.2f}% exceeded {self.max_dd_pct * 100:.0f}% limit.\n"
                f"All positions closed. Session halted.",
            )
            self._running = False
        return dd

    # ── daily summary ─────────────────────────────────────────────────────────

    def _send_daily_summary(self, dd: float) -> None:
        elapsed_days = (time.time() - self.start_time) / 86400
        pnl = self.current_balance - self.start_balance
        msg = (
            f"📊 <b>HOPEFX Daily Paper Report</b>\n"
            f"Day {elapsed_days:.1f} / {self._duration_days()}\n"
            f"Balance: <b>${self.current_balance:,.2f}</b>\n"
            f"P&L: {'+' if pnl >= 0 else ''}{pnl:,.2f}\n"
            f"Drawdown: {dd * 100:.2f}%\n"
            f"Trades: {self.trade_count}\n"
            f"Instruments: {', '.join(self.instruments)}"
        )
        send_telegram(self.tg_token, self.tg_chat, msg)

    def _duration_days(self) -> str:
        return _env("PAPER_DURATION_DAYS", "30")

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._bootstrap()
        logger.info(
            "Starting %s-day paper session | Kill at %.0f%% DD",
            self._duration_days(),
            self.max_dd_pct * 100,
        )

        last_daily_alert = time.time()
        end_time = self.start_time + self.duration_s

        while self._running and time.time() < end_time:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Tick error: %s", exc)

            # Daily Telegram alert
            if time.time() - last_daily_alert >= 86400:
                dd = self._check_drawdown()
                self._send_daily_summary(dd)
                last_daily_alert = time.time()

            time.sleep(self.poll_interval)

        # Session complete
        elapsed_days = (time.time() - self.start_time) / 86400
        complete = elapsed_days >= float(self._duration_days()) * 0.99
        write_status(
            {
                "complete": complete,
                "start_balance": self.start_balance,
                "current_balance": self.current_balance,
                "drawdown_pct": self._check_drawdown(),
                "trade_count": self.trade_count,
                "elapsed_days": round(elapsed_days, 2),
            }
        )
        logger.info(
            "Session ended. Complete=%s | Trades=%d | Balance=%.2f",
            complete,
            self.trade_count,
            self.current_balance,
        )
        if complete:
            send_telegram(
                self.tg_token,
                self.tg_chat,
                f"✅ <b>30-day paper run COMPLETE</b>\n"
                f"Trades: {self.trade_count} | Final balance: ${self.current_balance:,.2f}\n"
                f"P&L: {self.current_balance - self.start_balance:+,.2f}\n"
                f"Ready to review FEATURE_LIVE_TRADING=true checklist.",
            )

    def _tick(self) -> None:
        """One polling cycle: fetch prices, generate signals, execute, log."""
        try:
            summary = self.client.get_account()
            acct = summary.get("account", {})
            self.current_balance = float(acct.get("balance", self.current_balance))
            self.peak_balance = max(self.peak_balance, self.current_balance)
        except Exception as exc:
            logger.warning("Account refresh failed: %s", exc)

        dd = self._check_drawdown()
        if not self._running:
            return

        for instrument in self.instruments:
            price = self.client.get_price(instrument)
            if price is None:
                continue

            signal = self._generate_signal(instrument, price)
            if signal is None:
                continue

            # Position size: 0.5% of balance per trade (conservative paper sizing)
            units = max(1, int(self.current_balance * 0.005 / price))
            if signal == "SELL":
                units = -units

            entry_price = price
            try:
                resp = self.client.place_market_order(instrument, units)
                fill = resp.get("orderFillTransaction", {})
                fill_price = float(fill.get("price", entry_price))
                slippage = abs(fill_price - entry_price)
                # Slippage in pips (instrument-dependent; approximate)
                pip_size = 0.01 if "JPY" in instrument else 0.0001
                slippage_pips = slippage / pip_size

                self.trade_count += 1
                record = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "instrument": instrument,
                    "side": signal,
                    "units": abs(units),
                    "entry_price": entry_price,
                    "exit_price": fill_price,
                    "pnl": fill.get("pl", 0),
                    "slippage_pips": round(slippage_pips, 2),
                    "drawdown_pct": round(dd * 100, 4),
                    "balance": self.current_balance,
                }
                self.trade_logger.log(record)
                logger.info(
                    "TRADE #%d %s %s %d units @ %.5f (slip %.2f pips)",
                    self.trade_count,
                    signal,
                    instrument,
                    abs(units),
                    fill_price,
                    slippage_pips,
                )

                write_status(
                    {
                        "complete": False,
                        "start_balance": self.start_balance,
                        "current_balance": self.current_balance,
                        "drawdown_pct": round(dd * 100, 4),
                        "trade_count": self.trade_count,
                        "elapsed_days": round((time.time() - self.start_time) / 86400, 2),
                    }
                )

            except Exception as exc:
                logger.error("Order failed for %s: %s", instrument, exc)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = PaperTradingRunner()
    runner.run()
