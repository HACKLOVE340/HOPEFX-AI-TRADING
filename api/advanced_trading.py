# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Advanced Trading Features API — Tasks 42–47

Task 42 — Strategy A/B Testing
  POST /api/ab-test/start          — start A/B test between two strategies
  GET  /api/ab-test/{test_id}      — get test results
  GET  /api/ab-test                — list all tests

Task 43 — Backtesting Result Sharing
  POST /api/backtest/{run_id}/share — generate public share URL
  GET  /api/backtest/shared/{slug}  — public view (no auth)

Task 44 — Custom Indicator Builder
  POST /api/indicators/preview      — evaluate formula on OHLCV data
  GET  /api/indicators              — list saved indicators
  POST /api/indicators              — save indicator
  DELETE /api/indicators/{id}       — delete indicator

Task 45 — Multi-Symbol Correlation Dashboard
  GET  /api/correlation             — rolling correlation matrix

Task 46 — Options Flow / CFTC COT Sentiment
  GET  /api/cot/gold                — latest CFTC COT gold positions

Task 47 — Monte Carlo Simulation
  POST /api/backtest/{run_id}/monte-carlo — run Monte Carlo on a backtest
  GET  /api/backtest/{run_id}/monte-carlo — get cached results
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Advanced Trading"])

# ── App state (injected at startup) ──────────────────────────────────────────
app_state = None


def set_state(state) -> None:
    global app_state
    app_state = state


# ── In-memory stores ──────────────────────────────────────────────────────────
_ab_tests: dict[str, dict] = {}
_shared_results: dict[str, dict] = {}  # slug → backtest result
_indicators: dict[str, dict] = {}
_mc_cache: dict[str, dict] = {}  # run_id → monte carlo result


# ─────────────────────────────────────────────────────────────────────────────
# Task 42 — Strategy A/B Testing
# ─────────────────────────────────────────────────────────────────────────────


class ABTestRequest(BaseModel):
    strategy_a: str
    strategy_b: str
    symbol: str = "XAU/USD"
    duration_days: int = Field(30, ge=1, le=365)
    initial_capital: float = 10000.0


def _run_real_backtest(
    strategy_name: str, symbol: str, duration_days: int, initial_capital: float
) -> dict:
    """
    Run a real backtest for a named strategy using the backtesting engine.

    Returns a result dict compatible with the A/B test response schema.
    Raises ValueError when the strategy is not registered or data is unavailable.
    """
    try:
        from backtesting.engine_config import BacktestEngine

        engine = BacktestEngine()
        result = engine.run(
            strategy=strategy_name,
            symbol=symbol,
            days=duration_days,
            initial_capital=initial_capital,
        )
        return {
            "strategy": strategy_name,
            "final_equity": round(
                float(result.get("final_equity", initial_capital)), 2
            ),
            "total_return": round(float(result.get("total_return_pct", 0.0)), 2),
            "sharpe_ratio": round(float(result.get("sharpe_ratio", 0.0)), 3),
            "max_drawdown": round(float(result.get("max_drawdown_pct", 0.0)), 2),
            "total_trades": int(result.get("total_trades", 0)),
            "win_rate": round(float(result.get("win_rate_pct", 0.0)), 2),
            "equity_curve": result.get("equity_curve", []),
        }
    except ImportError:
        raise ValueError(
            "BacktestEngine is not available. "
            "Ensure the backtest module is installed and configured."
        ) from None
    except Exception as exc:
        raise ValueError(f"Backtest failed for strategy '{strategy_name}': {exc}") from exc


@router.post("/api/ab-test/start", status_code=201)
async def start_ab_test(
    req: ABTestRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Start an A/B test between two strategies using the real backtesting engine.

    Both strategies are backtested over the same symbol and date range.
    Returns HTTP 422 when either strategy name is not registered or
    historical data is unavailable for the requested period.
    """
    try:
        result_a = _run_real_backtest(
            req.strategy_a, req.symbol, req.duration_days, req.initial_capital
        )
        result_b = _run_real_backtest(
            req.strategy_b, req.symbol, req.duration_days, req.initial_capital
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Winner by Sharpe ratio (risk-adjusted)
    winner = (
        req.strategy_a
        if result_a["sharpe_ratio"] >= result_b["sharpe_ratio"]
        else req.strategy_b
    )
    best_sharpe = max(result_a["sharpe_ratio"], result_b["sharpe_ratio"])

    test_id = str(uuid.uuid4())[:12]
    _ab_tests[test_id] = {
        "test_id": test_id,
        "user_id": user.sub,
        "symbol": req.symbol,
        "duration_days": req.duration_days,
        "status": "completed",
        "created_at": datetime.now(UTC).isoformat(),
        "strategy_a": result_a,
        "strategy_b": result_b,
        "winner": winner,
        "recommendation": (
            f"Deploy {winner} — higher risk-adjusted returns (Sharpe {best_sharpe:.2f})"
        ),
    }
    return _ab_tests[test_id]


@router.get("/api/ab-test")
async def list_ab_tests(user: TokenPayload = Depends(get_current_user)):
    tests = [t for t in _ab_tests.values() if t["user_id"] == user.sub]
    return {"tests": tests, "total": len(tests)}


@router.get("/api/ab-test/{test_id}")
async def get_ab_test(test_id: str, user: TokenPayload = Depends(get_current_user)):
    t = _ab_tests.get(test_id)
    if not t or t["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Test not found")
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Task 43 — Backtesting Result Sharing
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/backtest/{run_id}/share")
async def share_backtest(run_id: str, user: TokenPayload = Depends(get_current_user)):
    """
    Generate a public share URL for a completed backtest result.
    Returns 404 when the run_id does not correspond to a real backtest.
    """
    from api.backtesting import _results

    result = _results.get(run_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Backtest run '{run_id}' not found. Run a backtest first.",
        )

    slug = f"{run_id[:8]}-{uuid.uuid4().hex[:6]}"
    _shared_results[slug] = {
        **result,
        "shared_by": user.sub,
        "shared_at": datetime.now(UTC).isoformat(),
        "slug": slug,
    }
    base_url = "https://hopefx.io"
    return {
        "url": f"{base_url}/backtest/shared/{slug}",
        "slug": slug,
    }


@router.get("/api/backtest/shared/{slug}")
async def get_shared_backtest(slug: str):
    """Public endpoint — no auth required."""
    result = _shared_results.get(slug)
    if not result:
        raise HTTPException(status_code=404, detail="Shared backtest not found")
    # Strip internal fields
    public = {k: v for k, v in result.items() if k not in ("shared_by",)}
    return public


# ─────────────────────────────────────────────────────────────────────────────
# Task 44 — Custom Indicator Builder
# ─────────────────────────────────────────────────────────────────────────────


class IndicatorPreviewRequest(BaseModel):
    formula: str = Field(..., description="e.g. 'EMA(close, 20) / EMA(close, 50)'")
    symbol: str = "XAU/USD"
    periods: int = Field(50, ge=10, le=500)


class SaveIndicatorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    formula: str
    symbol: str = "XAU/USD"
    color: str = "#60a5fa"


def _load_ohlcv_for_indicator(symbol: str, periods: int) -> dict:
    """
    Load real OHLCV data for the indicator preview.

    Priority:
    1. CSV files in data/ directory
    2. Paper broker get_market_data()

    Raises ValueError when no real data is available.
    """
    import pathlib
    import pandas as pd

    sym_key = symbol.upper().replace("/", "_").replace("-", "_")
    if "_" not in sym_key and len(sym_key) == 6:  # noqa: PLR2004
        sym_key = sym_key[:3] + "_" + sym_key[3:]

    data_dir = pathlib.Path(__file__).parent.parent / "data"
    candidates = [
        data_dir / f"{sym_key}_H1.csv",
        data_dir / f"{sym_key.replace('_', '')}_H1.csv",
    ]
    for csv_path in candidates:
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path).tail(periods + 50)
                if len(df) >= 20:  # noqa: PLR2004
                    return {
                        "close": df["close"].tolist(),
                        "open": df["open"].tolist(),
                        "high": df["high"].tolist(),
                        "low": df["low"].tolist(),
                        "volume": df["volume"].tolist()
                        if "volume" in df.columns
                        else [0.0] * len(df),
                    }
            except Exception as exc:
                logger.debug("Indicator CSV load failed (%s): %s", csv_path, exc)

    # Paper broker fallback
    try:
        from app import app_state

        broker = getattr(app_state, "broker", None)
        if broker and hasattr(broker, "get_market_data"):
            raw = broker.get_market_data(sym_key.replace("_", ""), "1h", periods + 50)
            if raw and len(raw) >= 20:  # noqa: PLR2004
                import pandas as pd

                df = pd.DataFrame(raw)
                return {
                    "close": df["close"].tolist(),
                    "open": df["open"].tolist(),
                    "high": df["high"].tolist(),
                    "low": df["low"].tolist(),
                    "volume": df.get("volume", pd.Series([0.0] * len(df))).tolist(),
                }
    except Exception as exc:
        logger.debug("Indicator broker load failed: %s", exc)

    raise ValueError(
        f"No OHLCV data available for {symbol}. "
        "Connect a broker or add a CSV file to data/ to use the indicator builder."
    )


def _eval_indicator(formula: str, symbol: str, periods: int) -> list[dict]:
    """
    Safe formula evaluator using AST-based parsing — no eval() or exec().

    Allowed syntax
    --------------
    - Numeric literals (int, float)
    - Names: close, open, high, low, volume, EMA, SMA, RSI
    - Arithmetic operators: +, -, *, /, ** (unary -, unary +)
    - Function calls to EMA, SMA, RSI only
    - Parentheses for grouping

    Any other construct (attribute access, subscript, import, lambda,
    comprehension, comparison, boolean op, etc.) raises ValueError before
    any computation occurs.
    """
    import ast

    # ── AST whitelist ─────────────────────────────────────────────────────────
    _ALLOWED_NAMES = frozenset(
        {"EMA", "SMA", "RSI", "close", "open", "high", "low", "volume"}
    )
    _ALLOWED_NODES = (
        ast.Module,
        ast.Expr,
        ast.Expression,
        # Literals
        ast.Constant,
        # Arithmetic
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.FloorDiv,
        ast.Mod,
        ast.UAdd,
        ast.USub,
        # Names and calls (validated separately)
        ast.Name,
        ast.Load,
        ast.Call,
        # Needed for multi-arg calls
        ast.arguments,
    )

    def _check_node(node: ast.AST) -> None:
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(
                f"Disallowed expression type '{type(node).__name__}' in formula. "
                "Only arithmetic and EMA/SMA/RSI calls are permitted."
            )
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_NAMES:
            raise ValueError(
                f"Unknown name '{node.id}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_NAMES))}"
            )
        if isinstance(node, ast.Call):
            # Function must be a bare Name, not an attribute or subscript
            if not isinstance(node.func, ast.Name):
                raise ValueError(
                    "Only direct function calls are allowed (e.g. EMA(...))"
                )
            if node.func.id not in {"EMA", "SMA", "RSI"}:
                raise ValueError(
                    f"Unknown function '{node.func.id}'. Allowed: EMA, SMA, RSI"
                )
            if (
                node.keywords or node.starargs
                if hasattr(node, "starargs")
                else node.keywords
            ):
                raise ValueError(
                    "Keyword arguments are not allowed in indicator formulas"
                )
        for child in ast.iter_child_nodes(node):
            _check_node(child)

    # ── Parse and validate ────────────────────────────────────────────────────
    formula_stripped = formula.strip()
    if len(formula_stripped) > 200:  # noqa: PLR2004
        raise ValueError("Formula too long (max 200 characters)")

    try:
        tree = ast.parse(formula_stripped, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Formula syntax error: {exc}") from exc

    _check_node(tree)

    # ── Build data namespace ──────────────────────────────────────────────────
    ohlcv = _load_ohlcv_for_indicator(symbol, periods)
    closes = ohlcv["close"]
    opens = ohlcv["open"]
    highs = ohlcv["high"]
    lows = ohlcv["low"]
    volumes = ohlcv["volume"]

    def sma(data: list[float], n: int) -> list[float]:
        result: list = [None] * (n - 1)
        for i in range(n - 1, len(data)):
            result.append(sum(data[i - n + 1 : i + 1]) / n)
        return result

    def ema(data: list[float], n: int) -> list[float]:
        k = 2 / (n + 1)
        result: list = [None] * (n - 1)
        ema_val = sum(data[:n]) / n
        result.append(ema_val)
        for price in data[n:]:
            ema_val = price * k + ema_val * (1 - k)
            result.append(ema_val)
        return result

    def rsi(data: list[float], n: int = 14) -> list[float]:
        result: list = [None] * n
        gains, losses = [], []
        for i in range(1, len(data)):
            diff = data[i] - data[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        for i in range(n - 1, len(gains)):
            avg_gain = sum(gains[i - n + 1 : i + 1]) / n
            avg_loss = sum(losses[i - n + 1 : i + 1]) / n
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            result.append(100 - 100 / (1 + rs))
        return result

    # ── AST interpreter (no eval/exec) ────────────────────────────────────────
    _fn_map = {"EMA": ema, "SMA": sma, "RSI": rsi}
    _name_map = {
        "close": closes,
        "open": opens,
        "high": highs,
        "low": lows,
        "volume": volumes,
        **_fn_map,
    }

    def _interp(node: ast.expr):  # type: ignore[name-defined]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return _name_map[node.id]
        if isinstance(node, ast.UnaryOp):
            operand = _interp(node.operand)
            if isinstance(node.op, ast.USub):
                return (
                    [-v if v is not None else None for v in operand]
                    if isinstance(operand, list)
                    else -operand
                )
            return operand
        if isinstance(node, ast.BinOp):
            left = _interp(node.left)
            right = _interp(node.right)
            op = node.op

            # Scalar × list or list × scalar
            def _apply(a, b):
                if isinstance(op, ast.Add):
                    return a + b
                if isinstance(op, ast.Sub):
                    return a - b
                if isinstance(op, ast.Mult):
                    return a * b
                if isinstance(op, ast.Div):
                    return a / b if b != 0 else None
                if isinstance(op, ast.Pow):
                    return a**b
                if isinstance(op, ast.FloorDiv):
                    return a // b
                if isinstance(op, ast.Mod):
                    return a % b
                raise ValueError(f"Unsupported operator {type(op).__name__}")

            if isinstance(left, list) and isinstance(right, list):
                return [
                    _apply(a, b) if a is not None and b is not None else None
                    for a, b in zip(left, right, strict=False)
                ]
            if isinstance(left, list):
                return [_apply(a, right) if a is not None else None for a in left]
            if isinstance(right, list):
                return [_apply(left, b) if b is not None else None for b in right]
            return _apply(left, right)
        if isinstance(node, ast.Call):
            fn = _fn_map[node.func.id]  # type: ignore[attr-defined]
            args = [_interp(a) for a in node.args]
            return fn(*args)
        raise ValueError(f"Unexpected node {type(node).__name__}")

    try:
        result = _interp(tree.body)
    except Exception as exc:
        raise ValueError(f"Formula evaluation error: {exc}") from exc

    if isinstance(result, (int, float)):
        result = [result] * len(closes)

    output = []
    for i, val in enumerate(result[-periods:]):
        if val is not None:
            output.append({"index": i, "value": round(float(val), 5)})
    return output


@router.post("/api/indicators/preview")
async def preview_indicator(
    req: IndicatorPreviewRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Evaluate a custom indicator formula against real OHLCV data.
    Returns HTTP 400 when the formula is invalid or data is unavailable.
    """
    try:
        data = _eval_indicator(req.formula, req.symbol, req.periods)
        return {
            "formula": req.formula,
            "symbol": req.symbol,
            "data": data,
            "points": len(data),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/indicators")
async def list_indicators(user: TokenPayload = Depends(get_current_user)):
    user_indicators = [i for i in _indicators.values() if i["user_id"] == user.sub]
    return {"indicators": user_indicators}


@router.post("/api/indicators", status_code=201)
async def save_indicator(
    req: SaveIndicatorRequest,
    user: TokenPayload = Depends(get_current_user),
):
    ind_id = str(uuid.uuid4())[:12]
    _indicators[ind_id] = {
        "id": ind_id,
        "user_id": user.sub,
        "name": req.name,
        "formula": req.formula,
        "symbol": req.symbol,
        "color": req.color,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return _indicators[ind_id]


@router.delete("/api/indicators/{ind_id}")
async def delete_indicator(ind_id: str, user: TokenPayload = Depends(get_current_user)):
    ind = _indicators.get(ind_id)
    if not ind or ind["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Indicator not found")
    del _indicators[ind_id]
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Task 45 — Multi-Symbol Correlation Dashboard
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/correlation")
async def get_correlation(
    symbols: str = "XAU/USD,EUR/USD,DXY,SPX,US10Y,VIX",
    window: int = 30,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return rolling correlation matrix for the given symbols.

    Uses real OHLCV from:
    1. price_engine.get_ohlcv() — live broker history
    2. CSV files in data/ directory

    Returns HTTP 503 when fewer than 2 symbols have sufficient real data
    to compute a meaningful correlation matrix.
    """
    import pathlib

    sym_list = [s.strip() for s in symbols.split(",")]

    # ── Collect real return series ────────────────────────────────────────────
    series: dict[str, list[float]] = {}

    # 1. Price engine
    pe = getattr(app_state, "price_engine", None) if app_state else None
    if pe is not None:
        for sym in sym_list:
            try:
                import asyncio

                ohlcv = pe.get_ohlcv(sym, "1d", window + 5)
                if asyncio.iscoroutine(ohlcv):
                    ohlcv = await ohlcv
                if ohlcv and len(ohlcv) >= 5:  # noqa: PLR2004
                    closes = [
                        float(
                            bar.get(
                                "close",
                                bar[-2] if isinstance(bar, (list, tuple)) else 0,
                            )
                        )
                        for bar in ohlcv
                    ]
                    returns = [
                        (closes[i] - closes[i - 1]) / closes[i - 1]
                        for i in range(1, len(closes))
                        if closes[i - 1] > 0
                    ]
                    if returns:
                        series[sym] = returns
            except Exception as exc:
                logger.debug("correlation: price_engine miss for %s: %s", sym, exc)

    # 2. CSV fallback for symbols still missing
    data_dir = pathlib.Path(__file__).parent.parent / "data"
    for sym in sym_list:
        if sym in series:
            continue
        sym_key = sym.upper().replace("/", "_").replace("-", "_")
        candidates = [
            data_dir / f"{sym_key}_D1.csv",
            data_dir / f"{sym_key}_H1.csv",
            data_dir / f"{sym_key.replace('_', '')}_H1.csv",
        ]
        for csv_path in candidates:
            if csv_path.exists():
                try:
                    import pandas as _pd

                    df = _pd.read_csv(csv_path, usecols=["close"]).tail(window + 5)
                    closes = df["close"].tolist()
                    returns = [
                        (closes[i] - closes[i - 1]) / closes[i - 1]
                        for i in range(1, len(closes))
                        if closes[i - 1] > 0
                    ]
                    if len(returns) >= 5:  # noqa: PLR2004
                        series[sym] = returns
                        break
                except Exception as exc:
                    logger.debug("correlation CSV miss for %s: %s", sym, exc)

    # Require at least 2 symbols with real data
    if len(series) < 2:  # noqa: PLR2004
        raise HTTPException(
            status_code=503,
            detail={
                "error": "insufficient_data",
                "message": (
                    "Correlation matrix requires real OHLCV history for at least 2 symbols. "
                    f"Found data for: {list(series.keys()) or 'none'}. "
                    "Connect a broker or add CSV files to data/ to enable this feature."
                ),
                "symbols_with_data": list(series.keys()),
                "symbols_requested": sym_list,
            },
        )

    # Align all series to the same length (shortest available)
    min_len = min(len(v) for v in series.values())
    for sym in series:
        series[sym] = series[sym][-min_len:]

    # ── Compute correlation matrix ────────────────────────────────────────────
    def corr(a: list[float], b: list[float]) -> float:
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        da = math.sqrt(sum((x - ma) ** 2 for x in a))
        db = math.sqrt(sum((x - mb) ** 2 for x in b))
        return round(num / (da * db), 3) if da * db > 0 else 0.0

    # Only include symbols that have data
    available = list(series.keys())
    matrix = {}
    for s1 in available:
        matrix[s1] = {}
        for s2 in available:
            matrix[s1][s2] = 1.0 if s1 == s2 else corr(series[s1], series[s2])

    insights = []
    for s1 in available:
        for s2 in available:
            if s1 >= s2:
                continue
            c = matrix[s1][s2]
            if abs(c) >= 0.6:  # noqa: PLR2004
                direction = "positively" if c > 0 else "negatively"
                insights.append(f"{s1} and {s2} are {direction} correlated ({c:+.2f})")

    missing = [s for s in sym_list if s not in series]
    return {
        "symbols": available,
        "symbols_missing_data": missing,
        "window": min_len,
        "matrix": matrix,
        "insights": insights[:5],
        "updated_at": datetime.now(UTC).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 46 — CFTC COT Gold Sentiment
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/cot/gold")
async def get_cot_gold():
    """
    Return CFTC Commitment of Traders data for gold (COMEX).
    Fetches from CFTC public API. Returns HTTP 503 when the API is unreachable.
    """
    try:
        import json
        import urllib.request

        # CFTC public data API — gold futures (COMEX, code 088691)
        url = "https://publicreporting.cftc.gov/api/explore/dataset/com_disagg_txt_2024/records/?where=cftc_commodity_code%3D%22088691%22&limit=1&sort=-report_date_as_yyyy_mm_dd"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - hardcoded https:// CFTC public API URL
            data = json.loads(resp.read())
            if data.get("records"):
                rec = data["records"][0]["record"]["fields"]
                net_long = int(rec.get("noncomm_positions_long_all", 0)) - int(
                    rec.get("noncomm_positions_short_all", 0),
                )
                return {
                    "report_date": rec.get("report_date_as_yyyy_mm_dd", ""),
                    "net_speculator_long": net_long,
                    "long_positions": int(rec.get("noncomm_positions_long_all", 0)),
                    "short_positions": int(rec.get("noncomm_positions_short_all", 0)),
                    "sentiment": "BULLISH" if net_long > 0 else "BEARISH",
                    "sentiment_strength": "STRONG"
                    if abs(net_long) > 100000  # noqa: PLR2004
                    else "MODERATE",
                    "source": "CFTC",
                    "note": "Non-commercial (speculator) net positions in COMEX gold futures.",
                }
    except Exception as exc:
        logger.warning("CFTC API unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "cftc_unavailable",
                "message": (
                    "CFTC public API is currently unreachable. "
                    "Data is published weekly — retry after the next report release."
                ),
            },
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Task 47 — Monte Carlo Simulation
# ─────────────────────────────────────────────────────────────────────────────


class MonteCarloRequest(BaseModel):
    simulations: int = Field(1000, ge=100, le=10000)
    initial_capital: float = 10000.0


def _run_monte_carlo(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    total_trades: int,
    initial_capital: float,
    simulations: int,
) -> dict:
    # Use OS entropy so each run produces independent results
    rng = random.Random()  # nosec B311 - Monte Carlo simulation, not cryptographic use
    final_equities = []
    ruin_count = 0
    ruin_threshold = initial_capital * 0.5  # 50% drawdown = ruin

    for _ in range(simulations):
        equity = initial_capital
        for _ in range(total_trades):
            if rng.random() < win_rate:
                equity += avg_win
            else:
                equity -= avg_loss
            if equity <= ruin_threshold:
                ruin_count += 1
                break
        final_equities.append(equity)

    final_equities.sort()
    n = len(final_equities)
    median = final_equities[n // 2]
    p5 = final_equities[int(n * 0.05)]
    p25 = final_equities[int(n * 0.25)]
    p75 = final_equities[int(n * 0.75)]
    p95 = final_equities[int(n * 0.95)]

    # Distribution histogram (20 buckets)
    min_e, max_e = final_equities[0], final_equities[-1]
    bucket_size = (max_e - min_e) / 20 if max_e > min_e else 1
    histogram = [0] * 20
    for e in final_equities:
        idx = min(int((e - min_e) / bucket_size), 19)
        histogram[idx] += 1

    return {
        "simulations": simulations,
        "initial_capital": initial_capital,
        "median_equity": round(median, 2),
        "p5_equity": round(p5, 2),
        "p25_equity": round(p25, 2),
        "p75_equity": round(p75, 2),
        "p95_equity": round(p95, 2),
        "probability_of_ruin": round(ruin_count / simulations * 100, 2),
        "expected_return_pct": round(
            (median - initial_capital) / initial_capital * 100,
            2,
        ),
        "histogram": histogram,
        "histogram_min": round(min_e, 2),
        "histogram_max": round(max_e, 2),
    }


@router.post("/api/backtest/{run_id}/monte-carlo")
async def run_monte_carlo(
    run_id: str,
    req: MonteCarloRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Run Monte Carlo simulation on a completed backtest result.
    Returns 404 when the run_id does not correspond to a real backtest.
    """
    from api.backtesting import _results

    result = _results.get(run_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Backtest run '{run_id}' not found. Run a backtest first.",
        )

    win_rate = float(result.get("win_rate_pct", 0)) / 100
    avg_win = float(result.get("avg_win", 0))
    avg_loss = float(result.get("avg_loss", 0))
    n_trades = int(result.get("total_trades", 0))
    capital = req.initial_capital or float(result.get("initial_capital", 10000))

    if n_trades < 10:  # noqa: PLR2004
        raise HTTPException(
            status_code=422,
            detail=(
                f"Backtest '{run_id}' has only {n_trades} trades. "
                "Monte Carlo requires at least 10 trades for meaningful results."
            ),
        )

    mc = _run_monte_carlo(
        win_rate, avg_win, avg_loss, n_trades, capital, req.simulations
    )
    mc["run_id"] = run_id
    mc["computed_at"] = datetime.now(UTC).isoformat()
    _mc_cache[run_id] = mc
    return mc


@router.get("/api/backtest/{run_id}/monte-carlo")
async def get_monte_carlo(run_id: str, user: TokenPayload = Depends(get_current_user)):
    """Return cached Monte Carlo results. Returns 404 when not yet computed."""
    if run_id in _mc_cache:
        return _mc_cache[run_id]
    raise HTTPException(
        status_code=404,
        detail=f"No Monte Carlo results for run '{run_id}'. POST to compute first.",
    )
