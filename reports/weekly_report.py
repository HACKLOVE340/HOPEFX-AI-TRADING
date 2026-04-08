# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
reports/weekly_report.py
========================
Auto-generates a weekly performance report from the paper/live trading run.

Metrics computed
----------------
- Win rate, total trades, avg win/loss
- Sharpe ratio (annualised, daily returns)
- Sortino ratio
- Max drawdown (peak-to-trough)
- Calmar ratio
- Profit factor
- Expectancy per trade

Output formats
--------------
- JSON  (always produced, stored in reports/output/)
- HTML  (Jinja2 template, stored in reports/output/)
- Email (SMTP, optional — set REPORT_EMAIL_TO env var)

Scheduling
----------
Run via APScheduler (wired into api/server.py lifespan) every Monday 08:00 UTC.
Can also be triggered manually:
    python -m reports.weekly_report

Data source labelling
---------------------
Every report carries a ``data_source`` field so Sharpe and P&L numbers are
never published without context:

  "paper_oanda"      — fills from a real OANDA practice account (API-connected)
  "paper_simulation" — fills from the internal paper broker simulation
  "live"             — fills from a live/funded broker account
  "seeded"           — test/seed data; not from any real or simulated fills

The source is determined automatically from the broker state at report time
and can be overridden by passing ``data_source=`` to WeeklyReportGenerator.generate().
"""

from __future__ import annotations

import json
import logging
import math
import os
import smtplib
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ── Data source constants ─────────────────────────────────────────────────────

DATA_SOURCE_PAPER_OANDA = "paper_oanda"  # real OANDA practice account
DATA_SOURCE_PAPER_SIMULATION = "paper_simulation"  # internal paper broker sim
DATA_SOURCE_LIVE = "live"  # funded live account
DATA_SOURCE_SEEDED = "seeded"  # test / seed data

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    side: str  # BUY | SELL
    open_time: datetime
    close_time: datetime
    open_price: float
    close_price: float
    lots: float
    pnl: float  # realised P&L in account currency
    pips: float


@dataclass
class WeeklyReport:
    report_id: str
    week_start: datetime
    week_end: datetime
    generated_at: datetime

    # Trade stats
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float | None  # None if < 10 trades
    avg_win: float
    avg_loss: float
    profit_factor: float | None
    expectancy: float  # avg P&L per trade

    # Return metrics
    gross_pnl: float
    net_pnl: float
    total_return_pct: float

    # Risk metrics
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown_pct: float
    calmar_ratio: float | None

    # Context
    starting_equity: float
    ending_equity: float
    symbols_traded: list[str]
    note: str = ""

    # Data provenance — REQUIRED.  Never publish a Sharpe without labelling source.
    # One of: "paper_oanda" | "paper_simulation" | "live" | "seeded"
    data_source: str = DATA_SOURCE_PAPER_SIMULATION

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("week_start", "week_end", "generated_at"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


# ── Metric calculations ───────────────────────────────────────────────────────


def _sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float | None:
    if len(returns) < 5:
        return None
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    if sigma < 1e-10:
        return None
    return round(mu / sigma * math.sqrt(periods_per_year), 3)


def _sortino(returns: np.ndarray, periods_per_year: int = 252) -> float | None:
    if len(returns) < 5:
        return None
    mu = float(np.mean(returns))
    downside = returns[returns < 0]
    if len(downside) == 0:
        return None
    downside_std = float(np.std(downside, ddof=1))
    if downside_std < 1e-10:
        return None
    return round(mu / downside_std * math.sqrt(periods_per_year), 3)


def _max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / np.where(peak > 0, peak, 1.0)
    return round(float(np.min(dd)), 6)


def _calmar(annual_return: float, max_dd: float) -> float | None:
    if abs(max_dd) < 1e-10:
        return None
    return round(annual_return / abs(max_dd), 3)


def _profit_factor(wins: list[float], losses: list[float]) -> float | None:
    gross_win = sum(w for w in wins if w > 0)
    gross_loss = abs(sum(loss for loss in losses if loss < 0))
    if gross_loss < 1e-10:
        return None
    return round(gross_win / gross_loss, 3)


# ── Report builder ────────────────────────────────────────────────────────────


class WeeklyReportGenerator:
    """
    Generates a weekly performance report from trade records and equity curve.

    Usage:
        gen = WeeklyReportGenerator()
        report = gen.generate(trades, equity_curve, starting_equity)
        gen.save_json(report)
        gen.send_email(report)
    """

    def generate(
        self,
        trades: list[TradeRecord],
        equity_curve: list[tuple[datetime, float]],
        starting_equity: float = 10_000.0,
        week_start: datetime | None = None,
        week_end: datetime | None = None,
        data_source: str | None = None,
    ) -> WeeklyReport:
        now = datetime.now(UTC)
        if week_end is None:
            week_end = now
        if week_start is None:
            week_start = week_end - timedelta(days=7)

        # Filter trades to this week
        week_trades = [t for t in trades if week_start <= t.close_time <= week_end]

        wins = [t.pnl for t in week_trades if t.pnl > 0]
        losses = [t.pnl for t in week_trades if t.pnl <= 0]
        total = len(week_trades)
        gross_pnl = sum(t.pnl for t in week_trades)
        ending_equity = starting_equity + gross_pnl

        # Daily returns from equity curve
        eq_values = [v for _, v in equity_curve if week_start <= _ <= week_end]
        daily_returns = np.array([])
        if len(eq_values) >= 2:
            arr = np.array(eq_values, dtype=float)
            daily_returns = np.diff(arr) / np.where(arr[:-1] > 0, arr[:-1], 1.0)

        dd = _max_drawdown(eq_values) if eq_values else 0.0
        annual_return = (gross_pnl / starting_equity) * 52 if starting_equity > 0 else 0.0

        symbols = list({t.symbol for t in week_trades})

        # Resolve data_source: explicit override > auto-detect > default
        resolved_source = data_source or _detect_data_source()

        return WeeklyReport(
            report_id=str(uuid.uuid4()),
            week_start=week_start,
            week_end=week_end,
            generated_at=now,
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=round(len(wins) / total, 4) if total >= 10 else None,
            avg_win=round(sum(wins) / len(wins), 4) if wins else 0.0,
            avg_loss=round(sum(losses) / len(losses), 4) if losses else 0.0,
            profit_factor=_profit_factor(wins, losses),
            expectancy=round(gross_pnl / total, 4) if total > 0 else 0.0,
            gross_pnl=round(gross_pnl, 4),
            net_pnl=round(gross_pnl, 4),
            total_return_pct=round(gross_pnl / starting_equity * 100, 4) if starting_equity > 0 else 0.0,
            sharpe_ratio=_sharpe(daily_returns),
            sortino_ratio=_sortino(daily_returns),
            max_drawdown_pct=round(dd * 100, 4),
            calmar_ratio=_calmar(annual_return, dd),
            starting_equity=round(starting_equity, 2),
            ending_equity=round(ending_equity, 2),
            symbols_traded=symbols,
            data_source=resolved_source,
            note=("Insufficient trades for statistical significance (< 10)." if total < 10 else ""),
        )

    def save_json(self, report: WeeklyReport) -> Path:
        """Write report to reports/output/weekly_YYYY-MM-DD.json."""
        fname = OUTPUT_DIR / f"weekly_{report.week_end.strftime('%Y-%m-%d')}.json"
        fname.write_text(json.dumps(report.to_dict(), indent=2))
        logger.info("Weekly report saved: %s", fname)
        return fname

    def save_html(self, report: WeeklyReport) -> Path:
        """Render report to HTML using an inline template."""
        html = _render_html(report)
        fname = OUTPUT_DIR / f"weekly_{report.week_end.strftime('%Y-%m-%d')}.html"
        fname.write_text(html, encoding="utf-8")
        logger.info("Weekly HTML report saved: %s", fname)
        return fname

    def send_email(self, report: WeeklyReport) -> bool:
        """
        Send the weekly report via SMTP.

        Required env vars:
          REPORT_EMAIL_TO    — recipient address
          SMTP_HOST          — SMTP server (default: localhost)
          SMTP_PORT          — SMTP port (default: 587)
          SMTP_USER          — SMTP username (optional)
          SMTP_PASSWORD      — SMTP password (optional)
          SMTP_FROM          — sender address (default: reports@hopefx.com)
        """
        to_addr = os.environ.get("REPORT_EMAIL_TO", "")
        if not to_addr:
            logger.info("REPORT_EMAIL_TO not set — skipping email")
            return False

        smtp_host = os.environ.get("SMTP_HOST", "localhost")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASSWORD", "")
        from_addr = os.environ.get("SMTP_FROM", "reports@hopefx.com")

        subject = (
            f"HopeFX Weekly Report — "
            f"w/e {report.week_end.strftime('%d %b %Y')} | "
            f"P&L: {'+' if report.net_pnl >= 0 else ''}"
            f"${report.net_pnl:.2f} | "
            f"Trades: {report.total_trades}"
        )

        html_body = _render_html(report)
        text_body = _render_text(report)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo()
                if smtp_port == 587:
                    server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, [to_addr], msg.as_string())
            logger.info("Weekly report emailed to %s", to_addr)
            return True
        except Exception as exc:
            logger.error("Failed to send weekly report email: %s", exc)
            return False


# ── Data source detection ─────────────────────────────────────────────────────


def _detect_data_source() -> str:
    """
    Auto-detect the data source for the current report.

    Priority:
      1. OANDA practice account with a real (non-PENDING) account_id → paper_oanda
      2. Live trading gate open → live
      3. Internal paper broker simulation → paper_simulation
      4. Fallback → paper_simulation
    """
    try:
        oanda_stamp = Path("data/oanda_paper_start.json")
        if oanda_stamp.exists():
            info = json.loads(oanda_stamp.read_text())
            account_id = info.get("account_id", "PENDING")
            if account_id and account_id != "PENDING" and not account_id.startswith("PENDING"):
                return DATA_SOURCE_PAPER_OANDA
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    try:
        from core.live_trading_gate import get_gate

        live_gate = get_gate()
        if getattr(live_gate, "is_live", False):
            return DATA_SOURCE_LIVE
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return DATA_SOURCE_PAPER_SIMULATION


# ── Templates ─────────────────────────────────────────────────────────────────


def _fmt(val: float | None, suffix: str = "", decimals: int = 2) -> str:
    if val is None:
        return "—"
    return f"{val:.{decimals}f}{suffix}"


_DATA_SOURCE_LABELS: dict[str, str] = {
    DATA_SOURCE_PAPER_OANDA: "Paper — OANDA practice account (API-connected)",
    DATA_SOURCE_PAPER_SIMULATION: "Paper — internal simulation (no real fills)",
    DATA_SOURCE_LIVE: "LIVE — funded account",
    DATA_SOURCE_SEEDED: "TEST/SEEDED — not from real or simulated fills",
}


def _source_label(source: str) -> str:
    return _DATA_SOURCE_LABELS.get(source, source)


def _render_text(r: WeeklyReport) -> str:
    return f"""HopeFX Weekly Performance Report
Week ending: {r.week_end.strftime("%d %b %Y")}
Generated:   {r.generated_at.strftime("%Y-%m-%d %H:%M UTC")}
Data source: {_source_label(r.data_source)}

TRADE SUMMARY
  Total trades:    {r.total_trades}
  Wins / Losses:   {r.winning_trades} / {r.losing_trades}
  Win rate:        {_fmt(r.win_rate * 100 if r.win_rate else None, "%")}
  Avg win:         ${_fmt(r.avg_win)}
  Avg loss:        ${_fmt(r.avg_loss)}
  Profit factor:   {_fmt(r.profit_factor)}
  Expectancy:      ${_fmt(r.expectancy)}

P&L
  Gross P&L:       ${r.gross_pnl:+.2f}
  Net P&L:         ${r.net_pnl:+.2f}
  Return:          {_fmt(r.total_return_pct, "%")}
  Starting equity: ${r.starting_equity:,.2f}
  Ending equity:   ${r.ending_equity:,.2f}

RISK METRICS
  Sharpe ratio:    {_fmt(r.sharpe_ratio)}
  Sortino ratio:   {_fmt(r.sortino_ratio)}
  Max drawdown:    {_fmt(r.max_drawdown_pct, "%")}
  Calmar ratio:    {_fmt(r.calmar_ratio)}

Symbols traded: {", ".join(r.symbols_traded) or "—"}
{r.note}
"""


def _render_html(r: WeeklyReport) -> str:
    pnl_color = "#22c55e" if r.net_pnl >= 0 else "#ef4444"
    pnl_sign = "+" if r.net_pnl >= 0 else ""

    # Data source badge colour
    _source_colors: dict[str, str] = {
        DATA_SOURCE_LIVE: "#22c55e",
        DATA_SOURCE_PAPER_OANDA: "#3b82f6",
        DATA_SOURCE_PAPER_SIMULATION: "#f59e0b",
        DATA_SOURCE_SEEDED: "#ef4444",
    }
    source_color = _source_colors.get(r.data_source, "#94a3b8")
    source_label = _source_label(r.data_source)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>HopeFX Weekly Report</title>
<style>
  body {{ font-family: 'Inter', Arial, sans-serif; background: #0f172a; color: #f1f5f9;
         margin: 0; padding: 24px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 24px;
           max-width: 680px; margin: 0 auto; }}
  h1 {{ color: #3b82f6; font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #94a3b8; font-size: 13px; margin-bottom: 12px; }}
  .source-badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px;
                   font-size: 11px; font-weight: 700; text-transform: uppercase;
                   letter-spacing: 0.5px; margin-bottom: 20px;
                   background: {source_color}22; color: {source_color};
                   border: 1px solid {source_color}55; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  th {{ text-align: left; color: #94a3b8; font-size: 12px; text-transform: uppercase;
        padding: 6px 0; border-bottom: 1px solid #334155; }}
  td {{ padding: 8px 0; border-bottom: 1px solid #1e293b; font-size: 14px; }}
  td:last-child {{ text-align: right; font-weight: 600; }}
  .pnl {{ color: {pnl_color}; font-size: 28px; font-weight: 700; }}
  .section {{ color: #3b82f6; font-size: 13px; font-weight: 600;
              text-transform: uppercase; margin: 20px 0 8px; }}
  .note {{ color: #f59e0b; font-size: 12px; margin-top: 16px; }}
  .footer {{ color: #475569; font-size: 11px; margin-top: 24px; text-align: center; }}
</style>
</head>
<body>
<div class="card">
  <h1>HopeFX Weekly Report</h1>
  <div class="sub">Week ending {r.week_end.strftime("%d %b %Y")} &nbsp;·&nbsp;
    Generated {r.generated_at.strftime("%Y-%m-%d %H:%M UTC")}</div>
  <div class="source-badge">Data source: {source_label}</div>

  <div class="pnl">{pnl_sign}${r.net_pnl:,.2f}</div>
  <div style="color:#94a3b8;font-size:13px;margin-bottom:20px;">
    Net P&amp;L &nbsp;·&nbsp; {_fmt(r.total_return_pct, "%")} return
  </div>

  <div class="section">Trade Summary</div>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Total trades</td><td>{r.total_trades}</td></tr>
    <tr><td>Wins / Losses</td><td>{r.winning_trades} / {r.losing_trades}</td></tr>
    <tr><td>Win rate</td><td>{_fmt(r.win_rate * 100 if r.win_rate else None, "%")}</td></tr>
    <tr><td>Avg win</td><td>${_fmt(r.avg_win)}</td></tr>
    <tr><td>Avg loss</td><td>${_fmt(r.avg_loss)}</td></tr>
    <tr><td>Profit factor</td><td>{_fmt(r.profit_factor)}</td></tr>
    <tr><td>Expectancy / trade</td><td>${_fmt(r.expectancy)}</td></tr>
  </table>

  <div class="section">Risk Metrics</div>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Sharpe ratio (ann.)</td><td>{_fmt(r.sharpe_ratio)}</td></tr>
    <tr><td>Sortino ratio</td><td>{_fmt(r.sortino_ratio)}</td></tr>
    <tr><td>Max drawdown</td><td>{_fmt(r.max_drawdown_pct, "%")}</td></tr>
    <tr><td>Calmar ratio</td><td>{_fmt(r.calmar_ratio)}</td></tr>
    <tr><td>Starting equity</td><td>${r.starting_equity:,.2f}</td></tr>
    <tr><td>Ending equity</td><td>${r.ending_equity:,.2f}</td></tr>
  </table>

  <div style="color:#94a3b8;font-size:12px;">
    Symbols: {", ".join(r.symbols_traded) or "—"}
  </div>
  {f'<div class="note">⚠ {r.note}</div>' if r.note else ""}
  <div class="footer">HopeFX AI Trading · Automated weekly report</div>
</div>
</body>
</html>"""


# ── APScheduler integration ───────────────────────────────────────────────────


def schedule_weekly_report(scheduler: object) -> None:
    """
    Register the weekly report job with an APScheduler instance.

    Call this from api/server.py lifespan after creating the scheduler:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        from reports.weekly_report import schedule_weekly_report
        schedule_weekly_report(scheduler)
        scheduler.start()
    """
    try:
        scheduler.add_job(  # type: ignore[union-attr]
            _run_weekly_report_job,
            trigger="cron",
            day_of_week="mon",
            hour=8,
            minute=0,
            timezone="UTC",
            id="weekly_performance_report",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Weekly performance report scheduled: every Monday 08:00 UTC")
    except Exception as exc:
        logger.warning("Failed to schedule weekly report: %s", exc)


async def _run_weekly_report_job() -> None:
    """APScheduler job: pull trade data, generate report, save + email."""
    logger.info("Running weekly performance report job...")
    try:
        trades, equity_curve, starting_equity, data_source = await _load_trade_data()
        gen = WeeklyReportGenerator()
        report = gen.generate(trades, equity_curve, starting_equity, data_source=data_source)
        gen.save_json(report)
        gen.save_html(report)
        gen.send_email(report)
        logger.info(
            "Weekly report complete: trades=%d pnl=%.2f sharpe=%s source=%s",
            report.total_trades,
            report.net_pnl,
            report.sharpe_ratio,
            report.data_source,
        )
    except Exception:
        logger.exception("Weekly report job failed: %s")


async def _load_trade_data() -> tuple:
    """
    Load trade records, equity curve, and data source from the active broker.

    Returns (trades, equity_curve, starting_equity, data_source).
    """
    trades: list[TradeRecord] = []
    equity_curve: list[tuple[datetime, float]] = []
    starting_equity = 10_000.0
    data_source = _detect_data_source()

    try:
        from app import app_state  # type: ignore[import]

        broker = getattr(app_state, "broker", None)
        if broker is None:
            return trades, equity_curve, starting_equity, data_source

        # Refine source from broker type if available
        broker_type = type(broker).__name__.lower()
        if "oanda" in broker_type:
            data_source = DATA_SOURCE_PAPER_OANDA
        elif "live" in broker_type:
            data_source = DATA_SOURCE_LIVE
        else:
            data_source = DATA_SOURCE_PAPER_SIMULATION

        # Load closed trades
        if hasattr(broker, "get_closed_trades"):
            raw = broker.get_closed_trades()
            for t in raw:
                trades.append(
                    TradeRecord(
                        trade_id=str(t.get("id", uuid.uuid4())),
                        symbol=t.get("symbol", ""),
                        side=t.get("side", "BUY"),
                        open_time=datetime.fromisoformat(t["open_time"]) if "open_time" in t else datetime.now(UTC),
                        close_time=datetime.fromisoformat(t["close_time"]) if "close_time" in t else datetime.now(UTC),
                        open_price=float(t.get("open_price", 0)),
                        close_price=float(t.get("close_price", 0)),
                        lots=float(t.get("lots", 0)),
                        pnl=float(t.get("pnl", 0)),
                        pips=float(t.get("pips", 0)),
                    )
                )

        # Load equity curve
        if hasattr(broker, "get_equity_history"):
            history = broker.get_equity_history()
            equity_curve = [(datetime.fromtimestamp(float(ts), tz=UTC), float(val)) for ts, val in history]
            if equity_curve:
                starting_equity = equity_curve[0][1]

    except Exception as exc:
        logger.debug("Trade data load failed: %s", exc)

    return trades, equity_curve, starting_equity, data_source


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def _main() -> None:
        trades, equity_curve, starting_equity, data_source = await _load_trade_data()
        gen = WeeklyReportGenerator()
        report = gen.generate(trades, equity_curve, starting_equity, data_source=data_source)
        json_path = gen.save_json(report)
        html_path = gen.save_html(report)
        logger.info(_render_text(report))
        logger.info(f"\nSaved: {json_path}")
        logger.info(f"Saved: {html_path}")

    asyncio.run(_main())
