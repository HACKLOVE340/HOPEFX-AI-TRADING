# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
notifications/email_triggers.py
================================
Typed helpers that fire transactional emails for the three key events:

  1. Trade filled   → trade_fill.html
  2. Daily P&L      → daily_report.html
  3. Risk halt      → risk_halt.html

Each function is a thin wrapper around the NotificationManager's email
channel. They are safe to call even when SMTP/SendGrid is not configured —
the manager falls back to logging only.

Usage
-----
    from notifications.email_triggers import (
        send_trade_fill_email,
        send_daily_report_email,
        send_risk_halt_email,
    )

    # In execution pipeline after a fill:
    send_trade_fill_email(
        to="trader@example.com",
        symbol="XAUUSD",
        direction="buy",
        quantity=0.1,
        fill_price=2050.0,
        net_pnl=None,          # None for open trades
    )

    # In daily scheduler:
    send_daily_report_email(
        to="trader@example.com",
        date="2026-03-25",
        daily_pnl=312.50,
        daily_pnl_pct=0.31,
        total_trades=3,
        win_rate_pct=66.7,
        equity=105_312.50,
    )

    # In risk manager on halt:
    send_risk_halt_email(
        to="trader@example.com",
        reason="Daily loss limit reached",
        drawdown_pct=5.02,
        limit_pct=5.0,
    )
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Recipient address for system alerts (configurable via env)
_DEFAULT_TO = os.getenv("SMTP_TO", "")


def _get_email_channel():
    """Return the EmailChannel from the global NotificationManager, or None."""
    try:
        from notifications.manager import NotificationManager

        mgr = NotificationManager.get_instance()
        return mgr.channels.get("email")
    except Exception as exc:
        logger.debug("Email channel unavailable: %s", exc)
        return None


def _send(
    to: str,
    subject: str,
    template: str,
    **context,
) -> bool:
    """
    Render `template` and send to `to`.

    Falls back to plain-text logging when the email channel is not configured.
    Never raises — email failures must not crash the trading pipeline.
    """
    if not to:
        logger.debug("email_triggers: no recipient address — skipping %s", template)
        return False

    try:
        from notifications.email_renderer import render_email

        html = render_email(template, **context)
    except Exception as exc:
        logger.warning("email_triggers: template render failed (%s): %s", template, exc)
        html = None

    channel = _get_email_channel()
    if channel is None:
        # Log-only fallback — safe for dev/test environments
        logger.info(
            "[EMAIL-LOG] to=%s subject=%r template=%s context=%s",
            to,
            subject,
            template,
            {k: v for k, v in context.items() if k not in ("html",)},
        )
        return True

    try:
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Fire-and-forget from async context
            asyncio.ensure_future(
                channel.send_email_async([to], subject, plain_body=subject, html_body=html)
            )
            return True
        else:
            return loop.run_until_complete(
                channel.send_email_async([to], subject, plain_body=subject, html_body=html)
            )
    except Exception as exc:
        logger.error("email_triggers: send failed for %s: %s", template, exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────


def send_trade_fill_email(
    symbol: str,
    direction: str,
    quantity: float,
    fill_price: float,
    net_pnl: Optional[float] = None,
    commission: float = 0.0,
    to: str = "",
) -> bool:
    """
    Send a trade-filled confirmation email.

    Parameters
    ----------
    symbol      : Instrument (e.g. "XAUUSD")
    direction   : "buy" or "sell"
    quantity    : Lots / units filled
    fill_price  : Average fill price
    net_pnl     : Net P&L if closing trade, None for opening
    commission  : Commission charged
    to          : Recipient email (defaults to SMTP_TO env var)
    """
    recipient = to or _DEFAULT_TO
    subject = f"Trade Filled: {direction.upper()} {quantity:.2f} {symbol} @ {fill_price:,.2f}"
    return _send(
        to=recipient,
        subject=subject,
        template="trade_fill.html",
        symbol=symbol,
        direction=direction.upper(),
        quantity=quantity,
        fill_price=f"{fill_price:,.2f}",
        net_pnl=f"{net_pnl:+,.2f}" if net_pnl is not None else "Open trade",
        commission=f"{commission:.2f}",
        filled_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


def send_daily_report_email(
    date: str,
    daily_pnl: float,
    daily_pnl_pct: float,
    total_trades: int,
    win_rate_pct: float,
    equity: float,
    to: str = "",
) -> bool:
    """
    Send the daily P&L summary email.

    Parameters
    ----------
    date          : Report date string (e.g. "2026-03-25")
    daily_pnl     : Net P&L for the day in USD
    daily_pnl_pct : Daily P&L as a percentage of equity
    total_trades  : Number of trades closed today
    win_rate_pct  : Win rate for today's trades
    equity        : Current account equity
    to            : Recipient email (defaults to SMTP_TO env var)
    """
    recipient = to or _DEFAULT_TO
    pnl_sign = "+" if daily_pnl >= 0 else ""
    subject = f"HOPEFX Daily Report {date} — {pnl_sign}{daily_pnl:,.2f} ({pnl_sign}{daily_pnl_pct:.2f}%)"
    return _send(
        to=recipient,
        subject=subject,
        template="daily_report.html",
        report_date=date,
        daily_pnl=f"{pnl_sign}{daily_pnl:,.2f}",
        daily_pnl_pct=f"{pnl_sign}{daily_pnl_pct:.2f}%",
        total_trades=total_trades,
        win_rate_pct=f"{win_rate_pct:.1f}%",
        equity=f"{equity:,.2f}",
    )


def send_risk_halt_email(
    reason: str,
    drawdown_pct: float,
    limit_pct: float,
    to: str = "",
) -> bool:
    """
    Send an immediate risk-halt alert email.

    Parameters
    ----------
    reason       : Human-readable halt reason
    drawdown_pct : Current drawdown percentage
    limit_pct    : The limit that was breached
    to           : Recipient email (defaults to SMTP_TO env var)
    """
    recipient = to or _DEFAULT_TO
    subject = f"⚠ HOPEFX RISK HALT — {reason}"
    return _send(
        to=recipient,
        subject=subject,
        template="risk_halt.html",
        reason=reason,
        drawdown_pct=f"{drawdown_pct:.2f}%",
        limit_pct=f"{limit_pct:.2f}%",
        halted_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
