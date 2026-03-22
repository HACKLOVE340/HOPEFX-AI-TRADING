"""
Telegram Bot Controller

Lets traders manage HOPEFX via Telegram messages.

Commands:
    /start          — welcome + help
    /status         — account balance, open positions, P&L
    /positions      — list all open positions
    /balance        — account balance only
    /signals        — latest strategy brain signals
    /health         — API health check
    /pause          — pause auto-trading
    /resume         — resume auto-trading
    /stop           — emergency stop (close all + pause)
    /help           — command list

Setup:
    1. Create a bot via @BotFather → get TELEGRAM_BOT_TOKEN
    2. Get your chat ID via @userinfobot → set TELEGRAM_CHAT_ID
    3. Set env vars and the bot starts automatically on app startup.

Environment variables:
    TELEGRAM_BOT_TOKEN   — bot token from BotFather
    TELEGRAM_CHAT_ID     — your personal or group chat ID (comma-separated for multiple)
    TELEGRAM_ALLOWED_IDS — same as TELEGRAM_CHAT_ID (alias)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_COMMANDS = """
/status    — balance, positions, daily P&L
/positions — open positions
/balance   — account balance
/signals   — latest strategy signals
/health    — system health
/pause     — pause auto-trading
/resume    — resume auto-trading
/stop      — emergency stop (close all)
/help      — this list
""".strip()


class TelegramBot:
    """
    Async Telegram bot that bridges chat commands to app_state.

    Pass ``app_state`` after construction so the bot can read
    live data (broker, risk_manager, strategy_brain, etc.).
    """

    def __init__(
        self,
        token: Optional[str] = None,
        allowed_chat_ids: Optional[List[int]] = None,
        app_state: Any = None,
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        raw_ids = os.getenv("TELEGRAM_CHAT_ID", os.getenv("TELEGRAM_ALLOWED_IDS", ""))
        if allowed_chat_ids:
            self.allowed_ids: List[int] = allowed_chat_ids
        else:
            self.allowed_ids = [
                int(x.strip()) for x in raw_ids.split(",") if x.strip().lstrip("-").isdigit()
            ]
        self.app_state = app_state
        self._app = None          # telegram.ext.Application
        self._paused = False
        self._running = False

    # ── Public API ───────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(self.token)

    async def start(self):
        """Start the bot (non-blocking — runs as background task)."""
        if not self.is_configured():
            logger.warning("Telegram bot not started: TELEGRAM_BOT_TOKEN not set")
            return
        try:
            from telegram.ext import Application, CommandHandler
            self._app = Application.builder().token(self.token).build()
            self._register_handlers()
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            self._running = True
            logger.info("Telegram bot started (allowed_ids=%s)", self.allowed_ids)
        except Exception as exc:
            logger.error("Telegram bot failed to start: %s", exc)

    async def stop(self):
        if self._app and self._running:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as exc:
                logger.warning("Telegram bot stop error: %s", exc)
            self._running = False

    async def send_message(self, text: str, chat_id: Optional[int] = None):
        """Send a message to all allowed chats (or a specific one)."""
        if not self._app:
            return
        targets = [chat_id] if chat_id else self.allowed_ids
        for cid in targets:
            try:
                await self._app.bot.send_message(chat_id=cid, text=text,
                                                  parse_mode="Markdown")
            except Exception as exc:
                logger.warning("Telegram send to %s failed: %s", cid, exc)

    async def notify_signal(self, symbol: str, direction: str,
                             confidence: float, price: float):
        """Broadcast a trading signal to all allowed chats."""
        emoji = "🟢" if direction.upper() == "BUY" else "🔴"
        msg = (
            f"{emoji} *Signal* — {symbol}\n"
            f"Direction: `{direction.upper()}`\n"
            f"Confidence: `{confidence:.0%}`\n"
            f"Price: `{price:,.5f}`\n"
            f"Time: `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`"
        )
        await self.send_message(msg)

    async def notify_trade(self, symbol: str, side: str, quantity: float,
                            price: float, order_id: str = ""):
        """Broadcast a trade execution."""
        emoji = "✅" if side.upper() == "BUY" else "🔻"
        msg = (
            f"{emoji} *Trade Executed* — {symbol}\n"
            f"Side: `{side.upper()}`\n"
            f"Qty: `{quantity}`\n"
            f"Price: `{price:,.5f}`\n"
            f"ID: `{order_id}`"
        )
        await self.send_message(msg)

    async def notify_alert(self, title: str, body: str, level: str = "INFO"):
        """Send a generic alert."""
        icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🚨", "CRITICAL": "🆘"}
        icon = icons.get(level.upper(), "ℹ️")
        await self.send_message(f"{icon} *{title}*\n{body}")

    # ── Command handlers ─────────────────────────────────────────────────────

    def _register_handlers(self):
        from telegram.ext import CommandHandler
        cmds = {
            "start": self._cmd_start,
            "help": self._cmd_help,
            "status": self._cmd_status,
            "positions": self._cmd_positions,
            "balance": self._cmd_balance,
            "signals": self._cmd_signals,
            "health": self._cmd_health,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "stop": self._cmd_stop,
        }
        for name, handler in cmds.items():
            self._app.add_handler(CommandHandler(name, self._guard(handler)))

    def _guard(self, fn: Callable) -> Callable:
        """Wrap a handler to enforce allowed_ids check."""
        async def wrapper(update, context):
            if self.allowed_ids and update.effective_chat.id not in self.allowed_ids:
                await update.message.reply_text("⛔ Unauthorized.")
                return
            await fn(update, context)
        return wrapper

    async def _cmd_start(self, update, context):
        await update.message.reply_text(
            f"👋 *HOPEFX AI Trading Bot*\n\n{_COMMANDS}", parse_mode="Markdown"
        )

    async def _cmd_help(self, update, context):
        await update.message.reply_text(f"*Commands:*\n{_COMMANDS}", parse_mode="Markdown")

    async def _cmd_status(self, update, context):
        lines = ["*📊 Status*"]
        broker = getattr(self.app_state, "broker", None)
        if broker:
            try:
                info = await broker.get_account_info() if asyncio.iscoroutinefunction(
                    broker.get_account_info) else broker.get_account_info()
                lines.append(f"Balance: `${info.balance:,.2f}`")
                lines.append(f"Equity: `${info.equity:,.2f}`")
                lines.append(f"Positions: `{info.positions_count}`")
            except Exception as exc:
                lines.append(f"Broker error: {exc}")
        else:
            lines.append("No broker connected")
        lines.append(f"Auto-trade: `{'PAUSED' if self._paused else 'ACTIVE'}`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_positions(self, update, context):
        broker = getattr(self.app_state, "broker", None)
        if not broker:
            await update.message.reply_text("No broker connected.")
            return
        try:
            positions = await broker.get_positions() if asyncio.iscoroutinefunction(
                broker.get_positions) else broker.get_positions()
            if not positions:
                await update.message.reply_text("No open positions.")
                return
            lines = ["*📈 Open Positions*"]
            for p in positions:
                pnl_sign = "+" if p.unrealized_pnl >= 0 else ""
                lines.append(
                    f"`{p.symbol}` {p.side} {p.quantity} "
                    f"@ {p.entry_price:.5f} | PnL: {pnl_sign}{p.unrealized_pnl:.2f}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as exc:
            await update.message.reply_text(f"Error: {exc}")

    async def _cmd_balance(self, update, context):
        broker = getattr(self.app_state, "broker", None)
        if not broker:
            await update.message.reply_text("No broker connected.")
            return
        try:
            info = await broker.get_account_info() if asyncio.iscoroutinefunction(
                broker.get_account_info) else broker.get_account_info()
            await update.message.reply_text(
                f"💰 *Balance*: `${info.balance:,.2f}`\n"
                f"💼 *Equity*: `${info.equity:,.2f}`\n"
                f"📉 *Margin used*: `${info.margin_used:,.2f}`",
                parse_mode="Markdown",
            )
        except Exception as exc:
            await update.message.reply_text(f"Error: {exc}")

    async def _cmd_signals(self, update, context):
        brain = getattr(self.app_state, "strategy_brain", None)
        if not brain:
            await update.message.reply_text("Strategy Brain not running.")
            return
        history = getattr(brain, "signal_history", [])
        if not history:
            await update.message.reply_text("No signals yet.")
            return
        lines = ["*🧠 Recent Signals*"]
        for sig in list(history)[-5:]:
            lines.append(
                f"`{sig.get('symbol','?')}` {sig.get('direction','?')} "
                f"conf={sig.get('confidence', 0):.0%}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_health(self, update, context):
        initialized = getattr(self.app_state, "initialized", False)
        db_ok = getattr(self.app_state, "db_engine", None) is not None
        brain_ok = getattr(self.app_state, "strategy_brain", None) is not None
        lines = [
            "*🏥 Health*",
            f"API: `{'✅' if initialized else '❌'}`",
            f"Database: `{'✅' if db_ok else '❌'}`",
            f"Strategy Brain: `{'✅' if brain_ok else '❌'}`",
            f"Auto-trade: `{'PAUSED ⏸' if self._paused else 'ACTIVE ▶️'}`",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_pause(self, update, context):
        self._paused = True
        os.environ["SIGNAL_ENGINE_AUTO_TRADE"] = "false"
        await update.message.reply_text("⏸ Auto-trading *paused*.", parse_mode="Markdown")

    async def _cmd_resume(self, update, context):
        self._paused = False
        os.environ["SIGNAL_ENGINE_AUTO_TRADE"] = "true"
        await update.message.reply_text("▶️ Auto-trading *resumed*.", parse_mode="Markdown")

    async def _cmd_stop(self, update, context):
        self._paused = True
        os.environ["SIGNAL_ENGINE_AUTO_TRADE"] = "false"
        broker = getattr(self.app_state, "broker", None)
        closed = 0
        if broker:
            try:
                positions = await broker.get_positions() if asyncio.iscoroutinefunction(
                    broker.get_positions) else broker.get_positions()
                for pos in positions:
                    try:
                        if asyncio.iscoroutinefunction(broker.close_position):
                            await broker.close_position(pos.symbol)
                        else:
                            broker.close_position(pos.symbol)
                        closed += 1
                    except Exception:
                        pass
            except Exception:
                pass
        await update.message.reply_text(
            f"🛑 *Emergency stop*\nAuto-trade paused. Closed {closed} position(s).",
            parse_mode="Markdown",
        )


# Module-level singleton — wired up in app.py startup
_bot_instance: Optional[TelegramBot] = None


def get_telegram_bot() -> Optional[TelegramBot]:
    return _bot_instance


def init_telegram_bot(app_state: Any) -> Optional[TelegramBot]:
    """Create and return the bot instance. Called from app.py startup."""
    global _bot_instance
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return None
    _bot_instance = TelegramBot(app_state=app_state)
    return _bot_instance
