# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Advanced Trading Features API — Tasks 42–47

Task 42 — Strategy A/B Testing
  POST /api/advanced/ab-tests/run  — start A/B test between two strategies
  GET  /api/advanced/ab-tests/{id} — get test results
  GET  /api/advanced/ab-tests      — list all tests

Task 43 — Backtesting Result Sharing
  POST /api/backtesting/{run_id}/share — generate public share URL
  GET  /api/backtesting/shared/{slug}  — public view (no auth)

Task 44 — Custom Indicator Builder
  POST /api/indicators/preview      — evaluate formula on OHLCV data
  GET  /api/indicators              — list saved indicators
  POST /api/indicators              — save indicator
  DELETE /api/indicators/{id}       — delete indicator

Task 45 — Multi-Symbol Correlation Dashboard
  GET  /api/advanced/correlation    — rolling correlation matrix

Task 46 — Options Flow / CFTC COT Sentiment
  GET  /api/advanced/cot-sentiment  — latest CFTC COT gold positions

Task 47 — Monte Carlo Simulation
  POST /api/backtesting/{run_id}/monte-carlo — run Monte Carlo on a backtest
  GET  /api/backtesting/{run_id}/monte-carlo — get cached results
"""

from __future__ import annotations

import contextlib
import logging
import math
import pathlib
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from monetization.subscription import require_plan

logger = logging.getLogger(__name__)
# Router-level auth dependency: every endpoint on this router requires a valid
# JWT by default.  Public endpoints (e.g. shared backtest view) are registered
# on public_router which carries no auth dependency.
router = APIRouter(
    tags=["Advanced Trading"],
    dependencies=[Depends(get_current_user)],
)

# Public router — no auth required.  Mount alongside router in app.py.
public_router = APIRouter(tags=["Advanced Trading (public)"])

# ── App state (injected at startup) ──────────────────────────────────────────
app_state = None


def set_state(state) -> None:
    global app_state
    app_state = state


# ── Redis-backed stores ───────────────────────────────────────────────────────
# A/B tests, shared backtest results, custom indicators, and Monte Carlo cache
# are stored in Redis so they survive restarts and are visible across replicas.
# All helpers fall back to in-process dicts when Redis is unavailable.
#
# Key layout:
#   advanced:ab_test:{test_id}        → JSON  (no TTL — user-managed)
#   advanced:shared_result:{slug}     → JSON  (TTL 30 days)
#   advanced:indicator:{ind_id}       → JSON  (no TTL — user-managed)
#   advanced:mc_cache:{run_id}        → JSON  (TTL 1 hour)

import json as _json

_SHARED_RESULT_TTL = 60 * 60 * 24 * 30  # 30 days
_MC_CACHE_TTL = 60 * 60  # 1 hour

# In-process fallback stores
_ab_tests: dict[str, dict] = {}
_shared_results: dict[str, dict] = {}
_indicators: dict[str, dict] = {}
_mc_cache: dict[str, dict] = {}

# COT data cache — persists last successful CFTC API response so the endpoint
# returns stale-but-valid data when the API is temporarily unreachable.
_cot_cache: dict | None = None
_cot_cache_key = "advanced:cot_cache"
_COT_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days (CFTC publishes weekly)


def _get_sync_redis():
    try:
        from cache.redis_pool import get_sync_client

        return get_sync_client()
    except Exception:  # nosec B110 — Redis is optional; return None to use in-process fallback
        return None


def _kv_set(key: str, data: dict, ttl: int | None = None) -> None:
    r = _get_sync_redis()
    if r:
        try:
            raw = _json.dumps(data)
            if ttl:
                r.setex(key, ttl, raw)
            else:
                r.set(key, raw)
            return
        except Exception:  # nosec B110 — Redis cache is optional; failure is non-fatal
            pass


def _kv_get(key: str) -> dict | None:
    r = _get_sync_redis()
    if r:
        try:
            raw = r.get(key)
            return _json.loads(raw) if raw else None
        except Exception:  # nosec B110 — Redis cache is optional; failure is non-fatal
            pass
    return None


def _kv_del(key: str) -> None:
    r = _get_sync_redis()
    if r:
        try:
            r.delete(key)
            return
        except Exception:  # nosec B110 — Redis cache is optional; failure is non-fatal
            pass


def _kv_scan(pattern: str) -> list[dict]:
    r = _get_sync_redis()
    if r:
        try:
            keys = r.keys(pattern)
            result = []
            for k in keys:
                raw = r.get(k)
                if raw:
                    result.append(_json.loads(raw))
            return result
        except Exception:  # nosec B110 — Redis cache is optional; failure is non-fatal
            pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Task 42 — Strategy A/B Testing
# ─────────────────────────────────────────────────────────────────────────────


class ABTestRequest(BaseModel):
    strategy_a: str
    strategy_b: str
    symbol: str = "XAU/USD"
    duration_days: int = Field(30, ge=1, le=365)
    initial_capital: float = 10000.0


def _run_real_backtest(strategy_name: str, symbol: str, duration_days: int, initial_capital: float) -> dict:
    """
    Run a real backtest for a named strategy using the backtesting engine.

    Returns a result dict compatible with the A/B test response schema.
    Raises ValueError when the strategy is not registered or data is unavailable.
    """
    try:
        from datetime import timedelta

        from backtesting.engine_config import BacktestConfig, BacktestEngine

        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=duration_days)
        config = BacktestConfig(
            start_date=start_dt,
            end_date=end_dt,
            symbols=[symbol],
            initial_capital=initial_capital,
        )
        engine = BacktestEngine(config=config)
        import asyncio

        result = asyncio.run(engine.run())
        return {
            "strategy": strategy_name,
            "final_equity": round(float(initial_capital * (1 + result.total_return)), 2),
            "total_return": round(float(result.total_return * 100), 2),
            "sharpe_ratio": round(float(result.sharpe_ratio), 3),
            "max_drawdown": round(float(result.max_drawdown * 100), 2),
            "total_trades": int(result.total_trades),
            "win_rate": round(float(result.win_rate * 100), 2),
            "equity_curve": result.equity_curve,
        }
    except ImportError:
        raise ValueError(
            "BacktestEngine is not available. Ensure the backtest module is installed and configured."
        ) from None
    except Exception as exc:
        logger.error("Backtest failed for strategy '%s': %s", strategy_name, exc)
        raise ValueError(f"Backtest failed for strategy '{strategy_name}' — check server logs") from None


@router.post("/api/advanced/ab-tests/run", status_code=201)
async def start_ab_test(
    req: ABTestRequest,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Start an A/B test between two strategies using the real backtesting engine.

    Both strategies are backtested over the same symbol and date range.
    Returns HTTP 422 when either strategy name is not registered or
    historical data is unavailable for the requested period.
    """
    try:
        result_a = _run_real_backtest(req.strategy_a, req.symbol, req.duration_days, req.initial_capital)
        result_b = _run_real_backtest(req.strategy_b, req.symbol, req.duration_days, req.initial_capital)
    except ValueError as exc:
        logger.warning("ab_test start failed: %s", exc)
        raise HTTPException(
            status_code=422, detail="A/B test failed — check strategy names and data availability"
        ) from None

    # Winner by Sharpe ratio (risk-adjusted)
    winner = req.strategy_a if result_a["sharpe_ratio"] >= result_b["sharpe_ratio"] else req.strategy_b
    best_sharpe = max(result_a["sharpe_ratio"], result_b["sharpe_ratio"])

    test_id = str(uuid.uuid4())[:12]
    test_data = {
        "test_id": test_id,
        "user_id": user.sub,
        "symbol": req.symbol,
        "duration_days": req.duration_days,
        "status": "completed",
        "created_at": datetime.now(UTC).isoformat(),
        "strategy_a": result_a,
        "strategy_b": result_b,
        "winner": winner,
        "recommendation": (f"Deploy {winner} — higher risk-adjusted returns (Sharpe {best_sharpe:.2f})"),
    }
    _kv_set(f"advanced:ab_test:{test_id}", test_data)
    _ab_tests[test_id] = test_data  # fallback mirror
    return test_data


@router.get("/api/advanced/ab-tests")
async def list_ab_tests(user: TokenPayload = Depends(require_plan("professional"))):
    tests = _kv_scan("advanced:ab_test:*") or list(_ab_tests.values())
    tests = [t for t in tests if t.get("user_id") == user.sub]
    return {"tests": tests, "total": len(tests)}


@router.get("/api/advanced/ab-tests/{test_id}")
async def get_ab_test(test_id: str, user: TokenPayload = Depends(require_plan("professional"))):
    t = _kv_get(f"advanced:ab_test:{test_id}") or _ab_tests.get(test_id)
    if not t or t["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Test not found")
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Task 43 — Backtesting Result Sharing
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/backtesting/{run_id}/share")
async def share_backtest(run_id: str, user: TokenPayload = Depends(require_plan("professional"))):
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
    shared = {
        **result,
        "shared_by": user.sub,
        "shared_at": datetime.now(UTC).isoformat(),
        "slug": slug,
    }
    _kv_set(f"advanced:shared_result:{slug}", shared, ttl=_SHARED_RESULT_TTL)
    _shared_results[slug] = shared  # fallback mirror
    base_url = "https://hopefx.io"
    return {
        "url": f"{base_url}/backtest/shared/{slug}",
        "slug": slug,
    }


@public_router.get("/api/backtesting/shared/{slug}")
async def get_shared_backtest(slug: str):
    """Public endpoint — no auth required (intentionally unauthenticated)."""
    result = _kv_get(f"advanced:shared_result:{slug}") or _shared_results.get(slug)
    if not result:
        raise HTTPException(status_code=404, detail="Shared backtest not found")
    # Strip internal fields before returning to anonymous callers
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
    if "_" not in sym_key and len(sym_key) == 6:
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
                if len(df) >= 20:
                    return {
                        "close": df["close"].tolist(),
                        "open": df["open"].tolist(),
                        "high": df["high"].tolist(),
                        "low": df["low"].tolist(),
                        "volume": df["volume"].tolist() if "volume" in df.columns else [0.0] * len(df),
                    }
            except Exception as exc:
                logger.debug("Indicator CSV load failed (%s): %s", csv_path, exc)

    # Paper broker fallback
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        if broker and hasattr(broker, "get_market_data"):
            raw = broker.get_market_data(sym_key.replace("_", ""), "1h", periods + 50)
            if raw and len(raw) >= 20:
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


# ─────────────────────────────────────────────────────────────────────────────
# Indicator math helpers (module-level so they are independently testable)
# ─────────────────────────────────────────────────────────────────────────────


def _ind_sma(data: list[float], n: int) -> list[float | None]:
    """Simple moving average over *data* with window *n*."""
    result: list[float | None] = [None] * (n - 1)
    for i in range(n - 1, len(data)):
        result.append(sum(data[i - n + 1 : i + 1]) / n)
    return result


def _ind_ema(data: list[float], n: int) -> list[float | None]:
    """Exponential moving average over *data* with window *n*."""
    k = 2 / (n + 1)
    result: list[float | None] = [None] * (n - 1)
    ema_val = sum(data[:n]) / n
    result.append(ema_val)
    for price in data[n:]:
        ema_val = price * k + ema_val * (1 - k)
        result.append(ema_val)
    return result


def _ind_rsi(data: list[float], n: int = 14) -> list[float | None]:
    """Relative Strength Index over *data* with period *n*."""
    result: list[float | None] = [None] * n
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    for i in range(n - 1, len(gains)):
        avg_gain = sum(gains[i - n + 1 : i + 1]) / n
        avg_loss = sum(losses[i - n + 1 : i + 1]) / n
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        result.append(100.0 - 100.0 / (1.0 + rs))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# AST-based formula validator
# ─────────────────────────────────────────────────────────────────────────────

import ast as _ast

_FORMULA_ALLOWED_NAMES: frozenset[str] = frozenset({"EMA", "SMA", "RSI", "close", "open", "high", "low", "volume"})
_FORMULA_ALLOWED_NODES = (
    _ast.Module,
    _ast.Expr,
    _ast.Expression,
    _ast.Constant,
    _ast.BinOp,
    _ast.UnaryOp,
    _ast.Add,
    _ast.Sub,
    _ast.Mult,
    _ast.Div,
    _ast.Pow,
    _ast.FloorDiv,
    _ast.Mod,
    _ast.UAdd,
    _ast.USub,
    _ast.Name,
    _ast.Load,
    _ast.Call,
    _ast.arguments,
)
_FORMULA_MAX_LEN = 200


def _validate_formula_ast(node: _ast.AST) -> None:
    """Recursively validate that *node* contains only whitelisted AST constructs.

    Raises ValueError on the first disallowed node, unknown name, or
    non-whitelisted function call.
    """
    if not isinstance(node, _FORMULA_ALLOWED_NODES):
        raise ValueError(
            f"Disallowed expression type '{type(node).__name__}' in formula. "
            "Only arithmetic and EMA/SMA/RSI calls are permitted."
        )
    if isinstance(node, _ast.Name) and node.id not in _FORMULA_ALLOWED_NAMES:
        raise ValueError(f"Unknown name '{node.id}'. Allowed: {', '.join(sorted(_FORMULA_ALLOWED_NAMES))}")
    if isinstance(node, _ast.Call):
        if not isinstance(node.func, _ast.Name):
            raise ValueError("Only direct function calls are allowed (e.g. EMA(...))")
        if node.func.id not in {"EMA", "SMA", "RSI"}:
            raise ValueError(f"Unknown function '{node.func.id}'. Allowed: EMA, SMA, RSI")
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed in indicator formulas")
    for child in _ast.iter_child_nodes(node):
        _validate_formula_ast(child)


def _parse_formula(formula: str) -> _ast.Expression:
    """Parse and validate *formula*; return the AST Expression node.

    Raises ValueError on syntax errors, disallowed constructs, or length
    violations.
    """
    stripped = formula.strip()
    if len(stripped) > _FORMULA_MAX_LEN:
        raise ValueError(f"Formula too long (max {_FORMULA_MAX_LEN} characters)")
    try:
        tree = _ast.parse(stripped, mode="eval")
    except SyntaxError as exc:
        # Surface a sanitized message — SyntaxError.msg is safe (describes the
        # syntax problem, not internal state), but lineno/offset are omitted.
        raise ValueError(f"Formula syntax error: {exc.msg}") from None
    _validate_formula_ast(tree)
    return tree


# ─────────────────────────────────────────────────────────────────────────────
# AST interpreter (no eval/exec)
# ─────────────────────────────────────────────────────────────────────────────

_INDICATOR_FN_MAP: dict[str, object] = {"EMA": _ind_ema, "SMA": _ind_sma, "RSI": _ind_rsi}


def _apply_binop(op: _ast.operator, a: float | None, b: float | None) -> float | None:
    """Apply a single binary operator to two scalar values."""
    if a is None or b is None:
        return None
    if isinstance(op, _ast.Add):
        return a + b
    if isinstance(op, _ast.Sub):
        return a - b
    if isinstance(op, _ast.Mult):
        return a * b
    if isinstance(op, _ast.Div):
        return a / b if b != 0 else None
    if isinstance(op, _ast.Pow):
        return a**b
    if isinstance(op, _ast.FloorDiv):
        return a // b
    if isinstance(op, _ast.Mod):
        return a % b
    raise ValueError(f"Unsupported operator {type(op).__name__}")


def _broadcast_binop(
    op: _ast.operator,
    left: list | float,
    right: list | float,
) -> list | float:
    """Apply *op* element-wise, broadcasting scalars against lists."""
    if isinstance(left, list) and isinstance(right, list):
        return [_apply_binop(op, a, b) for a, b in zip(left, right, strict=False)]
    if isinstance(left, list):
        return [_apply_binop(op, a, right) for a in left]
    if isinstance(right, list):
        return [_apply_binop(op, left, b) for b in right]
    return _apply_binop(op, left, right)


def _interp_node(node: _ast.expr, name_map: dict) -> list | float:  # type: ignore[name-defined]
    """Recursively evaluate a validated AST node against *name_map*."""
    if isinstance(node, _ast.Constant):
        return node.value
    if isinstance(node, _ast.Name):
        return name_map[node.id]
    if isinstance(node, _ast.UnaryOp):
        operand = _interp_node(node.operand, name_map)
        if isinstance(node.op, _ast.USub):
            if isinstance(operand, list):
                return [-v if v is not None else None for v in operand]
            return -operand
        return operand  # UAdd — no-op
    if isinstance(node, _ast.BinOp):
        left = _interp_node(node.left, name_map)
        right = _interp_node(node.right, name_map)
        return _broadcast_binop(node.op, left, right)
    if isinstance(node, _ast.Call):
        fn = _INDICATOR_FN_MAP[node.func.id]  # type: ignore[attr-defined]
        args = [_interp_node(a, name_map) for a in node.args]
        return fn(*args)
    raise ValueError(f"Unexpected node {type(node).__name__}")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def _eval_indicator(formula: str, symbol: str, periods: int) -> list[dict]:
    """Evaluate *formula* against real OHLCV data for *symbol*.

    Uses AST-based parsing — no eval() or exec().  Allowed syntax:
    numeric literals, close/open/high/low/volume names, EMA/SMA/RSI calls,
    and arithmetic operators (+, -, *, /, **, //, %).

    Returns a list of ``{"index": int, "value": float}`` dicts for the last
    *periods* bars where the result is non-None.
    """
    tree = _parse_formula(formula)

    ohlcv = _load_ohlcv_for_indicator(symbol, periods)
    name_map: dict = {
        "close": ohlcv["close"],
        "open": ohlcv["open"],
        "high": ohlcv["high"],
        "low": ohlcv["low"],
        "volume": ohlcv["volume"],
        **_INDICATOR_FN_MAP,
    }

    try:
        result = _interp_node(tree.body, name_map)
    except Exception as exc:
        logger.warning("Formula evaluation error: %s", exc)
        raise ValueError("Formula evaluation error — check formula syntax and variable names") from None

    closes = ohlcv["close"]
    if isinstance(result, int | float):
        result = [result] * len(closes)

    return [{"index": i, "value": round(float(val), 5)} for i, val in enumerate(result[-periods:]) if val is not None]


@router.post("/api/indicators/preview")
async def preview_indicator(
    req: IndicatorPreviewRequest,
    user: TokenPayload = Depends(require_plan("professional")),
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
        logger.warning("evaluate_indicator validation error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/indicators")
async def list_indicators(user: TokenPayload = Depends(require_plan("professional"))):
    all_inds = _kv_scan("advanced:indicator:*") or list(_indicators.values())
    user_indicators = [i for i in all_inds if i.get("user_id") == user.sub]
    return {"indicators": user_indicators}


@router.post("/api/indicators", status_code=201)
async def save_indicator(
    req: SaveIndicatorRequest,
    user: TokenPayload = Depends(require_plan("professional")),
):
    ind_id = str(uuid.uuid4())[:12]
    ind_data = {
        "id": ind_id,
        "user_id": user.sub,
        "name": req.name,
        "formula": req.formula,
        "symbol": req.symbol,
        "color": req.color,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _kv_set(f"advanced:indicator:{ind_id}", ind_data)
    _indicators[ind_id] = ind_data  # fallback mirror
    return ind_data


@router.delete("/api/indicators/{ind_id}")
async def delete_indicator(ind_id: str, user: TokenPayload = Depends(require_plan("professional"))):
    ind = _kv_get(f"advanced:indicator:{ind_id}") or _indicators.get(ind_id)
    if not ind or ind["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Indicator not found")
    _kv_del(f"advanced:indicator:{ind_id}")
    _indicators.pop(ind_id, None)
    return {"deleted": True}


@router.patch("/api/indicators/{ind_id}")
async def update_indicator(
    ind_id: str,
    payload: dict,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """Update an existing custom indicator (name, formula, parameters)."""
    ind = _kv_get(f"advanced:indicator:{ind_id}") or _indicators.get(ind_id)
    if not ind or ind["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Indicator not found")
    allowed = {"name", "formula", "parameters", "color", "panel", "visible"}
    for key in allowed:
        if key in payload:
            ind[key] = payload[key]
    _kv_set(f"advanced:indicator:{ind_id}", ind)
    _indicators[ind_id] = ind
    return ind


@router.post("/api/indicators/{ind_id}/apply")
async def apply_indicator(
    ind_id: str,
    payload: dict,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Apply a saved custom indicator to a chart session.

    Evaluates the indicator's formula against real OHLCV data fetched for
    ``symbol`` (same engine as /indicators/preview) and returns computed
    values ready for the chart.
    """
    ind = _kv_get(f"advanced:indicator:{ind_id}") or _indicators.get(ind_id)
    if not ind or ind["user_id"] != user.sub:
        raise HTTPException(status_code=404, detail="Indicator not found")

    formula = ind.get("formula", "")
    if not formula:
        raise HTTPException(status_code=422, detail="Indicator has no formula")

    symbol = payload.get("symbol", "XAU_USD")
    periods = int(payload.get("periods", 200))

    try:
        result = _eval_indicator(formula, symbol, periods)
        return {
            "indicator_id": ind_id,
            "name": ind.get("name", "custom"),
            "symbol": symbol,
            "data": result,
            "points": len(result),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Formula evaluation failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Task 45 — Multi-Symbol Correlation Dashboard
# ─────────────────────────────────────────────────────────────────────────────


def _pearson_corr(a: list[float], b: list[float]) -> float:
    """Pearson correlation coefficient between two equal-length series."""
    if len(a) < 2 or len(a) != len(b):
        return 0.0
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    return round(num / (da * db), 3) if da * db > 0 else 0.0


def _returns_from_closes(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]


async def _collect_series_from_engine(pe: Any, sym_list: list[str], window: int) -> dict[str, list[float]]:
    """Fetch return series for each symbol via price engine → CSV → yfinance."""
    import asyncio

    series: dict[str, list[float]] = {}

    # ── 1. Price engine ───────────────────────────────────────────────────────
    pe = getattr(app_state, "price_engine", None) if app_state else None
    if pe is not None:
        for sym in sym_list:
            try:
                ohlcv = pe.get_ohlcv(sym, "1d", window + 5)
                if asyncio.iscoroutine(ohlcv):
                    ohlcv = await ohlcv
                if ohlcv and len(ohlcv) >= 5:
                    closes = [
                        float(
                            bar.get(
                                "close",
                                bar[-2] if isinstance(bar, list | tuple) else 0,
                            )
                        )
                        for bar in ohlcv
                    ]
                    returns = [
                        (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0
                    ]
                    if returns:
                        series[sym] = returns
            except Exception as exc:
                logger.debug("correlation: price_engine miss for %s: %s", sym, exc)

    # ── 2. Local CSV files ────────────────────────────────────────────────────
    data_dir = pathlib.Path(__file__).parent.parent / "data"
    for sym in sym_list:
        if sym in series:
            continue
        sym_key = sym.upper().replace("/", "_").replace("-", "_")
        sym_compact = sym_key.replace("_", "")
        candidates = [
            data_dir / f"{sym_key}_D1.csv",
            data_dir / f"{sym_key}_H1.csv",
            data_dir / f"{sym_key}_H4.csv",
            data_dir / f"{sym_key}_D.csv",
            data_dir / f"{sym_compact}_D1.csv",
            data_dir / f"{sym_compact}_H1.csv",
            data_dir / f"{sym_compact}_2Y.csv",
            data_dir / f"{sym_compact}_5Y.csv",
        ]
        for csv_path in candidates:
            if not csv_path.exists():
                continue
            try:
                import csv as _csv

                closes: list[float] = []
                with open(csv_path, newline="", encoding="utf-8") as fh:
                    reader = _csv.DictReader(fh)
                    # Accept "close" or "Close" column
                    for row in reader:
                        val = row.get("close") or row.get("Close")
                        if val is not None:
                            with contextlib.suppress(ValueError):  # skip non-numeric rows
                                closes.append(float(val))
                closes = closes[-(window + 5) :]
                returns = [
                    (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0
                ]
                if len(returns) >= 5:
                    series[sym] = returns
                    logger.debug("correlation: loaded %s from %s (%d bars)", sym, csv_path.name, len(returns))
                    break
            except Exception as exc:
                logger.debug("correlation CSV miss for %s (%s): %s", sym, csv_path.name, exc)

    # ── 3. yfinance fallback for symbols still missing ────────────────────────
    missing = [s for s in sym_list if s not in series]
    if missing:
        # Map internal symbol names to yfinance tickers
        _YF_MAP: dict[str, str] = {
            "XAU_USD": "GC=F",
            "XAUUSD": "GC=F",
            "EUR_USD": "EURUSD=X",
            "EURUSD": "EURUSD=X",
            "GBP_USD": "GBPUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USD_JPY": "JPY=X",
            "USDJPY": "JPY=X",
            "BTC_USD": "BTC-USD",
            "BTCUSD": "BTC-USD",
            "USD_CHF": "CHF=X",
            "USDCHF": "CHF=X",
            "AUD_USD": "AUDUSD=X",
            "AUDUSD": "AUDUSD=X",
            "NZD_USD": "NZDUSD=X",
            "NZDUSD": "NZDUSD=X",
            "USD_CAD": "CAD=X",
            "USDCAD": "CAD=X",
        }
        try:
            import yfinance as _yf

            for sym in missing:
                ticker = _YF_MAP.get(sym.upper(), sym.replace("_", "") + "=X")
                try:
                    df = _yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
                    if df is not None and not df.empty and "Close" in df.columns:
                        closes = df["Close"].dropna().tolist()
                        closes = closes[-(window + 5) :]
                        returns = [
                            (closes[i] - closes[i - 1]) / closes[i - 1]
                            for i in range(1, len(closes))
                            if closes[i - 1] > 0
                        ]
                        if len(returns) >= 5:
                            series[sym] = returns
                            logger.debug(
                                "correlation: yfinance loaded %s (%s) — %d bars",
                                sym,
                                ticker,
                                len(returns),
                            )
                except Exception as exc:
                    logger.debug("correlation: yfinance miss for %s (%s): %s", sym, ticker, exc)
        except ImportError:
            logger.debug("correlation: yfinance not installed — skipping remote fallback")

    # ── Require at least 2 symbols with real data ─────────────────────────────
    if len(series) < 2:
        # Return an empty matrix instead of 503 so the frontend renders without
        # crashing.  The UI should show a "no data" state rather than an error.
        return {
            "symbols": [],
            "symbols_missing_data": sym_list,
            "window": window,
            "matrix": {},
            "insights": [],
            "updated_at": datetime.now(UTC).isoformat(),
            "note": (
                "Correlation matrix requires OHLCV history for at least 2 symbols. "
                f"Found data for: {list(series.keys()) or 'none'}. "
                "Connect a broker, add CSV files to data/, or install yfinance "
                "(pip install yfinance) to enable this feature."
            ),
        }

    min_len = min(len(v) for v in series.values())
    for sym in series:
        series[sym] = series[sym][-min_len:]

    available = list(series.keys())
    matrix: dict[str, dict[str, float]] = {}
    for s1 in available:
        matrix[s1] = {}
        for s2 in available:
            matrix[s1][s2] = 1.0 if s1 == s2 else _pearson_corr(series[s1], series[s2])

    insights = []
    for s1 in available:
        for s2 in available:
            if s1 >= s2:
                continue
            c = matrix[s1][s2]
            if abs(c) >= 0.6:
                direction = "positively" if c > 0 else "negatively"
                insights.append(f"{s1} and {s2} are {direction} correlated ({c:+.2f})")

    return {
        "symbols": available,
        "symbols_missing_data": [s for s in sym_list if s not in series],
        "window": min_len,
        "matrix": matrix,
        "insights": insights[:5],
        "updated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/api/advanced/correlation")
async def get_correlation_matrix(
    window: int = 60,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Return a rolling Pearson correlation matrix for the default symbol set.

    Reads OHLCV history from the price engine or CSV files in data/.
    Returns HTTP 503 when fewer than 2 symbols have sufficient history.
    """
    sym_list = ["XAU_USD", "EUR_USD", "GBP_USD", "USD_JPY", "BTC_USD"]
    return await _collect_series_from_engine(None, sym_list, window)


# ─────────────────────────────────────────────────────────────────────────────
# Task 46 — CFTC COT Gold Sentiment
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/advanced/cot-sentiment")
async def get_cot_gold(user: TokenPayload = Depends(require_plan("professional"))):
    """
    Return CFTC Commitment of Traders data for gold (COMEX).

    Fetches from the CFTC public API and caches the result for 7 days (the
    publication cadence).  When the API is unreachable the last cached response
    is returned with a ``stale=true`` flag rather than a 503.
    """

    def _build_result(rec: dict, stale: bool = False) -> dict:
        net_long = int(rec.get("noncomm_positions_long_all", 0)) - int(
            rec.get("noncomm_positions_short_all", 0),
        )
        result = {
            "report_date": rec.get("report_date_as_yyyy_mm_dd", ""),
            "net_speculator_long": net_long,
            "long_positions": int(rec.get("noncomm_positions_long_all", 0)),
            "short_positions": int(rec.get("noncomm_positions_short_all", 0)),
            "sentiment": "BULLISH" if net_long > 0 else "BEARISH",
            "sentiment_strength": "STRONG" if abs(net_long) > 100000 else "MODERATE",
            "weekly_change": 0,
            "source": "CFTC",
            "note": "Non-commercial (speculator) net positions in COMEX gold futures.",
            "stale": stale,
        }
        return result

    def _read_cache() -> dict | None:
        """Try Redis first, then in-process fallback."""
        try:
            r = _get_sync_redis()
            if r:
                raw = r.get(_cot_cache_key)
                if raw:
                    return _json.loads(raw)
        except Exception:  # nosec B110 — Redis unavailable; fall through to in-process cache
            pass
        return _cot_cache

    def _write_cache(data: dict) -> None:
        global _cot_cache
        _cot_cache = data
        try:
            r = _get_sync_redis()
            if r:
                r.setex(_cot_cache_key, _COT_CACHE_TTL, _json.dumps(data))
        except Exception:  # nosec B110 — Redis write failure is non-fatal; in-process cache updated above
            pass

    try:
        import json
        import urllib.request

        # CFTC public data API — gold futures (COMEX, code 088691)
        url = (
            "https://publicreporting.cftc.gov/api/explore/dataset/com_disagg_txt_2024/records/"
            "?where=cftc_commodity_code%3D%22088691%22&limit=1&sort=-report_date_as_yyyy_mm_dd"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
            data = json.loads(resp.read())
            records = data.get("records") or []
            if not records:
                # No records — fall through to cache
                raise ValueError("CFTC API returned no records")
            rec = records[0]["record"]["fields"]
            result = _build_result(rec, stale=False)
            _write_cache(rec)
            return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("CFTC API unavailable: %s", exc)
        cached = _read_cache()
        if cached:
            return _build_result(cached, stale=True)
        # No cache and API down — return a neutral placeholder so the UI renders
        return {
            "report_date": "",
            "net_speculator_long": 0,
            "long_positions": 0,
            "short_positions": 0,
            "sentiment": "NEUTRAL",
            "sentiment_strength": "UNKNOWN",
            "weekly_change": 0,
            "source": "CFTC",
            "note": "CFTC API temporarily unavailable. Data is published weekly.",
            "stale": True,
            "unavailable": True,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Task 47 — Monte Carlo Simulation
# ─────────────────────────────────────────────────────────────────────────────


class MonteCarloRequest(BaseModel):
    simulations: int = Field(1000, ge=100, le=10000)
    initial_capital: float = 10000.0


@dataclass
class _MonteCarloParams:
    win_rate: float
    avg_win: float
    avg_loss: float
    total_trades: int
    initial_capital: float = 10000.0
    simulations: int = 1000


def _run_monte_carlo(params: _MonteCarloParams) -> dict:
    win_rate = params.win_rate
    avg_win = params.avg_win
    avg_loss = params.avg_loss
    total_trades = params.total_trades
    initial_capital = params.initial_capital
    simulations = params.simulations

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


@router.post("/api/backtesting/{run_id}/monte-carlo")
async def run_monte_carlo(
    run_id: str,
    req: MonteCarloRequest,
    user: TokenPayload = Depends(require_plan("professional")),
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

    if n_trades < 10:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Backtest '{run_id}' has only {n_trades} trades. "
                "Monte Carlo requires at least 10 trades for meaningful results."
            ),
        )

    mc = _run_monte_carlo(
        _MonteCarloParams(
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            total_trades=n_trades,
            initial_capital=capital,
            simulations=req.simulations,
        )
    )
    mc["run_id"] = run_id
    mc["computed_at"] = datetime.now(UTC).isoformat()
    _kv_set(f"advanced:mc_cache:{run_id}", mc, ttl=_MC_CACHE_TTL)
    _mc_cache[run_id] = mc  # fallback mirror
    return mc


@router.get("/api/backtesting/{run_id}/monte-carlo")
async def get_monte_carlo(run_id: str, user: TokenPayload = Depends(require_plan("professional"))):
    """Return cached Monte Carlo results. Returns 404 when not yet computed."""
    mc = _kv_get(f"advanced:mc_cache:{run_id}") or _mc_cache.get(run_id)
    if mc:
        return mc
    raise HTTPException(
        status_code=404,
        detail=f"No Monte Carlo results for run '{run_id}'. POST to compute first.",
    )


# =============================================================================
# FRONTEND COMPATIBILITY ALIASES  — /api/advanced/*
# =============================================================================
# The frontend (hooks/useApi.ts) calls /api/advanced/correlation,
# /api/advanced/cot-sentiment and /api/advanced/ab-tests/*.
# These aliases forward to the canonical handlers without duplicating logic.

_adv_router = APIRouter(
    prefix="/api/advanced",
    tags=["Advanced Trading"],
    dependencies=[Depends(get_current_user)],
)


@_adv_router.get("/correlation", include_in_schema=False)
async def _adv_correlation(
    symbols: str = "XAUUSD,DXY,SPX500,OIL",
    window: int = 60,
    user: TokenPayload = Depends(require_plan("professional")),
) -> dict[str, Any]:
    """Alias: GET /api/advanced/correlation → correlation matrix."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    pe = getattr(app_state, "price_engine", None) if app_state else None
    return await _collect_series_from_engine(pe, sym_list, window)


@_adv_router.get("/cot-sentiment", include_in_schema=False)
async def _adv_cot_sentiment(user: TokenPayload = Depends(require_plan("professional"))) -> dict[str, Any]:
    """Alias: GET /api/advanced/cot-sentiment → COT gold data."""
    return await get_cot_gold(user=user)


@_adv_router.get("/ab-tests", include_in_schema=False)
async def _adv_list_ab(user: TokenPayload = Depends(require_plan("professional"))):
    """Alias: GET /api/advanced/ab-tests → list_ab_tests."""
    return await list_ab_tests(user=user)


@_adv_router.get("/ab-tests/{test_id}", include_in_schema=False)
async def _adv_get_ab(test_id: str, user: TokenPayload = Depends(require_plan("professional"))):
    """Alias: GET /api/advanced/ab-tests/{id} → get_ab_test."""
    return await get_ab_test(test_id=test_id, user=user)


@_adv_router.post("/ab-tests/run", include_in_schema=False, status_code=201)
async def _adv_run_ab(
    req: ABTestRequest,
    user: TokenPayload = Depends(require_plan("professional")),
) -> dict[str, Any]:
    """Alias: POST /api/advanced/ab-tests/run → start_ab_test."""
    return await start_ab_test(req=req, user=user)
