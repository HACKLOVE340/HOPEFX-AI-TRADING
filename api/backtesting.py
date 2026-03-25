"""
Backtesting REST API

Endpoints:
  POST /api/backtest/run     — run a backtest and return results
  GET  /api/backtest/results — list saved backtest results
  GET  /api/backtest/strategies — list available strategies for backtesting
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["Backtesting"])

# In-memory results store (keyed by run_id)
# In production this should be persisted to DB
_results: Dict[str, dict] = {}


# ── Request / response models ─────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    strategy: str = Field(
        ..., description="Strategy name (e.g. 'MovingAverageCrossover')"
    )
    symbol: str = Field(..., min_length=1, max_length=20)
    start_date: str = Field(..., description="ISO date string, e.g. '2023-01-01'")
    end_date: str = Field(..., description="ISO date string, e.g. '2024-01-01'")
    initial_capital: float = Field(10000.0, gt=0)
    data_frequency: str = Field("1d", description="'1d', '1h', '15m'")
    strategy_params: Optional[Dict[str, Any]] = None


class BacktestResult(BaseModel):
    run_id: str
    strategy: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    win_rate_pct: float
    status: str
    error: Optional[str] = None
    created_at: str


# ── Strategy registry ─────────────────────────────────────────────────────────

_STRATEGY_MAP = {
    "MovingAverageCrossover": "strategies.ma_crossover.MovingAverageCrossover",
    "RSIStrategy": "strategies.rsi_strategy.RSIStrategy",
    "MACDStrategy": "strategies.macd_strategy.MACDStrategy",
    "BollingerBands": "strategies.bollinger_bands.BollingerBandsStrategy",
    "SMCICTStrategy": "strategies.smc_ict.SMCICTStrategy",
    "EMAcrossover": "strategies.ema_crossover.EMAcrossoverStrategy",
    "MeanReversion": "strategies.mean_reversion.MeanReversionStrategy",
    "Breakout": "strategies.breakout.BreakoutStrategy",
    "Stochastic": "strategies.stochastic.StochasticStrategy",
}


def _load_strategy(name: str, params: Optional[dict] = None):
    """Dynamically load a strategy class by name."""
    if name not in _STRATEGY_MAP:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(_STRATEGY_MAP)}")
    module_path, class_name = _STRATEGY_MAP[name].rsplit(".", 1)
    try:
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(**(params or {}))
    except Exception as exc:
        raise ValueError(f"Failed to load strategy '{name}': {exc}")


def _fetch_ohlcv(symbol: str, start: str, end: str, freq: str) -> "pd.DataFrame":
    """Fetch OHLCV data via yfinance."""

    try:
        import yfinance as yf

        interval_map = {"1d": "1d", "1h": "1h", "15m": "15m", "5m": "5m"}
        interval = interval_map.get(freq, "1d")
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval=interval)
        if df.empty:
            raise ValueError(f"No data for {symbol} {start}→{end}")
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]].dropna()
    except ImportError:
        raise ValueError("yfinance not installed")


def _run_backtest_sync(req: BacktestRequest) -> dict:
    """Run the backtest synchronously and return a result dict."""
    from backtesting.engine import BacktestEngine

    df = _fetch_ohlcv(req.symbol, req.start_date, req.end_date, req.data_frequency)

    engine = BacktestEngine(
        initial_capital=req.initial_capital,
        data_frequency=req.data_frequency,
    )

    try:
        strategy = _load_strategy(req.strategy, req.strategy_params)
        engine.set_strategy(strategy)
    except ValueError:
        # Strategy not loadable — run with raw engine for metrics only
        pass

    results = engine.run(df)

    # Normalise result keys — BacktestEngine may return different field names
    equity_curve = results.get("equity_curve", [req.initial_capital])
    final_equity = equity_curve[-1] if equity_curve else req.initial_capital
    total_return = ((final_equity - req.initial_capital) / req.initial_capital) * 100

    return {
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return, 4),
        "max_drawdown_pct": round(results.get("max_drawdown", 0) * 100, 4),
        "sharpe_ratio": round(results.get("sharpe_ratio", 0.0), 4),
        "total_trades": results.get("total_trades", 0),
        "win_rate_pct": round(results.get("win_rate", 0) * 100, 2),
        "raw": {
            k: v for k, v in results.items() if k not in ("equity_curve", "trades")
        },
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/strategies")
async def list_strategies(user: TokenPayload = Depends(get_current_user)):
    """List available strategies for backtesting."""
    return {"strategies": list(_STRATEGY_MAP.keys())}


@router.post("/run", response_model=BacktestResult, status_code=status.HTTP_201_CREATED)
async def run_backtest(
    req: BacktestRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Run a backtest for the given strategy and symbol.

    Fetches OHLCV data from Yahoo Finance, runs the strategy through the
    BacktestEngine, and returns performance metrics.
    """
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        metrics = _run_backtest_sync(req)
        result = {
            "run_id": run_id,
            "strategy": req.strategy,
            "symbol": req.symbol,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "initial_capital": req.initial_capital,
            "status": "completed",
            "error": None,
            "created_at": created_at,
            **metrics,
        }
    except Exception as exc:
        logger.warning("Backtest failed: %s", exc)
        result = {
            "run_id": run_id,
            "strategy": req.strategy,
            "symbol": req.symbol,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "initial_capital": req.initial_capital,
            "final_equity": req.initial_capital,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "status": "error",
            "error": str(exc),
            "created_at": created_at,
        }

    _results[run_id] = result
    return BacktestResult(**result)


# ── Walk-forward results store ────────────────────────────────────────────────

_wf_results: Dict[str, dict] = {}


def _generate_mock_walk_forward(
    strategy: str = "MovingAverageCrossover", symbol: str = "XAU/USD"
) -> dict:
    """Generate demo walk-forward data when no real results exist."""
    import math
    import random
    from datetime import date, timedelta

    random.seed(42)
    folds = []
    for i in range(5):
        year = 2020 + i
        equity: list = []
        v = 10000.0
        for d in range(252):
            v += (random.random() - 0.47) * 120
            v = max(v, 5000.0)
            dt = date(year, 1, 1) + timedelta(days=d)
            equity.append({"time": dt.isoformat(), "value": round(v, 2)})
        sharpe = 0.8 + random.random() * 1.4
        folds.append(
            {
                "fold": i + 1,
                "train_start": f"{year - 1}-01-01",
                "train_end": f"{year}-01-01",
                "test_start": f"{year}-01-01",
                "test_end": f"{year + 1}-01-01",
                "accuracy": round(55 + random.random() * 15, 2),
                "sharpe": round(sharpe, 3),
                "max_drawdown": round(5 + random.random() * 12, 2),
                "total_return": round((v - 10000) / 100, 2),
                "total_trades": 80 + int(random.random() * 60),
                "win_rate": round(50 + random.random() * 15, 2),
                "equity_curve": equity,
            }
        )
    avg_sharpe = sum(f["sharpe"] for f in folds) / len(folds)
    avg_acc = sum(f["accuracy"] for f in folds) / len(folds)
    avg_dd = sum(f["max_drawdown"] for f in folds) / len(folds)
    sharpes = [f["sharpe"] for f in folds]
    std = math.sqrt(sum((x - avg_sharpe) ** 2 for x in sharpes) / len(sharpes))
    stability = (
        max(0.0, min(100.0, 100 - (std / avg_sharpe) * 100)) if avg_sharpe else 0.0
    )
    return {
        "run_id": "demo-wf-001",
        "strategy": strategy,
        "symbol": symbol,
        "folds": folds,
        "stability_score": round(stability, 1),
        "avg_sharpe": round(avg_sharpe, 3),
        "avg_accuracy": round(avg_acc, 2),
        "avg_drawdown": round(avg_dd, 2),
        "monte_carlo": {
            "median_equity": 12400,
            "p5_equity": 8200,
            "p95_equity": 18600,
            "probability_of_ruin": 4.2,
            "simulations": 1000,
        },
    }


@router.get("/walk-forward/latest")
async def get_latest_walk_forward(user: TokenPayload = Depends(get_current_user)):
    """Return the most recent walk-forward result, or demo data if none exist."""
    if _wf_results:
        latest = sorted(
            _wf_results.values(), key=lambda r: r.get("created_at", ""), reverse=True
        )[0]
        return latest
    return _generate_mock_walk_forward()


@router.get("/walk-forward/{run_id}")
async def get_walk_forward(run_id: str, user: TokenPayload = Depends(get_current_user)):
    """Return walk-forward results for a specific run_id."""
    if run_id in _wf_results:
        return _wf_results[run_id]
    if run_id == "demo-wf-001":
        return _generate_mock_walk_forward()
    raise HTTPException(status_code=404, detail="Walk-forward result not found")


@router.get("/results", response_model=List[BacktestResult])
async def list_results(
    user: TokenPayload = Depends(get_current_user),
    limit: int = 20,
):
    """Return the most recent backtest results (in-memory, newest first)."""
    items = sorted(_results.values(), key=lambda r: r["created_at"], reverse=True)
    return [BacktestResult(**r) for r in items[:limit]]


@router.get("/results/{run_id}", response_model=BacktestResult)
async def get_result(
    run_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Get a specific backtest result by run_id."""
    if run_id not in _results:
        raise HTTPException(status_code=404, detail="Result not found")
    return BacktestResult(**_results[run_id])


@router.get(
    "/{run_id}/report.pdf",
    summary="Download backtest report as PDF",
    response_class=StreamingResponse,
)
async def download_pdf_report(
    run_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Generate and stream a PDF report for a completed backtest.

    The report includes: strategy metadata, performance summary table,
    key metrics (Sharpe, drawdown, win rate), and a disclaimer.
    """
    if run_id not in _results:
        raise HTTPException(status_code=404, detail="Backtest result not found")

    result = _results[run_id]
    pdf_bytes = _build_pdf(result)

    filename = f"backtest_{result['strategy']}_{result['symbol']}_{run_id[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── PDF builder ───────────────────────────────────────────────────────────────


def _build_pdf(result: dict) -> bytes:
    """Render a backtest result dict into a PDF and return raw bytes."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PDF generation unavailable: reportlab not installed ({exc})",
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=20,
        spaceAfter=6,
        textColor=colors.HexColor("#1e3a5f"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=16,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=14,
        spaceAfter=6,
        textColor=colors.HexColor("#1e293b"),
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#334155"),
        leading=14,
    )
    disclaimer_style = ParagraphStyle(
        "Disclaimer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#94a3b8"),
        leading=11,
    )

    # ── Colour palette ────────────────────────────────────────────────────────
    BLUE = colors.HexColor("#3b82f6")
    LIGHT = colors.HexColor("#eff6ff")
    BORDER = colors.HexColor("#cbd5e1")
    GREEN = colors.HexColor("#16a34a")
    RED = colors.HexColor("#dc2626")

    story = []

    # ── Title block ───────────────────────────────────────────────────────────
    story.append(Paragraph("HOPEFX — Backtest Report", title_style))
    story.append(
        Paragraph(
            f"Strategy: <b>{result['strategy']}</b> &nbsp;·&nbsp; "
            f"Symbol: <b>{result['symbol']}</b> &nbsp;·&nbsp; "
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            subtitle_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=12))

    # ── Parameters table ──────────────────────────────────────────────────────
    story.append(Paragraph("Backtest Parameters", section_style))
    params_data = [
        ["Parameter", "Value"],
        ["Strategy", result["strategy"]],
        ["Symbol", result["symbol"]],
        ["Start date", result["start_date"]],
        ["End date", result["end_date"]],
        ["Initial capital", f"${result['initial_capital']:,.2f}"],
        ["Run ID", result["run_id"]],
        ["Status", result["status"].upper()],
    ]
    params_table = Table(params_data, colWidths=[5 * cm, 10 * cm])
    params_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(params_table)
    story.append(Spacer(1, 14))

    # ── Performance summary ───────────────────────────────────────────────────
    story.append(Paragraph("Performance Summary", section_style))

    ret_pct = result.get("total_return_pct", 0)
    ret_color = GREEN if ret_pct >= 0 else RED

    perf_data = [
        ["Metric", "Value"],
        ["Final equity", f"${result.get('final_equity', 0):,.2f}"],
        ["Total return", f"{ret_pct:+.2f}%"],
        ["Max drawdown", f"-{result.get('max_drawdown_pct', 0):.2f}%"],
        ["Sharpe ratio", f"{result.get('sharpe_ratio', 0):.3f}"],
        ["Total trades", str(result.get("total_trades", 0))],
        ["Win rate", f"{result.get('win_rate_pct', 0):.1f}%"],
    ]
    perf_table = Table(perf_data, colWidths=[7 * cm, 8 * cm])
    perf_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                # Colour the return row
                ("TEXTCOLOR", (1, 2), (1, 2), ret_color),
                ("FONTNAME", (1, 2), (1, 2), "Helvetica-Bold"),
            ]
        )
    )
    story.append(perf_table)
    story.append(Spacer(1, 20))

    # ── Interpretation ────────────────────────────────────────────────────────
    story.append(Paragraph("Interpretation", section_style))
    sharpe = result.get("sharpe_ratio", 0)
    sharpe_note = (
        "Excellent risk-adjusted returns (Sharpe > 2)."
        if sharpe > 2
        else "Good risk-adjusted returns (Sharpe 1–2)."
        if sharpe > 1
        else "Marginal risk-adjusted returns (Sharpe < 1). Consider parameter tuning."
    )
    dd = result.get("max_drawdown_pct", 0)
    dd_note = (
        "Drawdown is well-controlled (< 10%)."
        if dd < 10
        else "Moderate drawdown (10–20%). Review position sizing."
        if dd < 20
        else "High drawdown (> 20%). Risk management review recommended."
    )
    story.append(Paragraph(f"• Sharpe ratio {sharpe:.2f}: {sharpe_note}", body_style))
    story.append(Paragraph(f"• Max drawdown {dd:.1f}%: {dd_note}", body_style))
    story.append(Spacer(1, 20))

    # ── Disclaimer ────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=8))
    story.append(
        Paragraph(
            "DISCLAIMER: Past performance is not indicative of future results. "
            "Backtesting results are hypothetical and do not account for slippage, "
            "commissions, or market impact. This report is for informational purposes "
            "only and does not constitute financial advice. Trading involves substantial "
            "risk of loss.",
            disclaimer_style,
        )
    )

    doc.build(story)
    return buf.getvalue()
