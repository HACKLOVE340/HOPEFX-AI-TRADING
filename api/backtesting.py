# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Backtesting REST API

Endpoints:
  POST /api/backtesting/run                  — run a single-symbol backtest
  GET  /api/backtesting/results              — list saved backtest results
  GET  /api/backtesting/list                 — alias for /results (frontend compat)
  GET  /api/backtesting/strategies           — list available strategies
  POST /api/backtesting/walk-forward/run     — trigger walk-forward backtest
  GET  /api/backtesting/walk-forward/latest  — most recent walk-forward result
  GET  /api/backtesting/walk-forward/{id}    — specific walk-forward result
  POST /api/backtesting/multi-symbol         — run multi-symbol backtest
  GET  /api/backtesting/multi-symbol/latest  — most recent multi-symbol report
"""

from __future__ import annotations

import asyncio

import io
import logging
import pathlib
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from api.db_store import db_get, db_keys_prefix, db_set
from monetization.subscription import require_plan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtesting", tags=["Backtesting"])

# ── Persistent results store ──────────────────────────────────────────────────
# Results are written to the `configurations` table via db_store so they
# survive process restarts.  An in-process dict acts as a write-through cache
# to avoid a DB round-trip on every status poll during a running backtest.

_DB_PREFIX = "backtest:result:"
_WF_DB_PREFIX = "backtest:wf:"

# Write-through in-process cache (populated lazily from DB on first read)
_results: dict[str, dict] = {}
_results_loaded: bool = False


def _load_results_from_db() -> None:
    """Populate the in-process cache from the DB on first access."""
    global _results_loaded  # pylint: disable=global-statement
    if _results_loaded:
        return
    try:
        for key in db_keys_prefix(_DB_PREFIX):
            run_id = key[len(_DB_PREFIX) :]
            value = db_get(key)
            if value:
                _results[run_id] = value
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Could not load backtest results from DB: %s", exc)
    _results_loaded = True


def _owner_of(store: dict, run_id: str, result: dict, user_id: str | None) -> str | None:
    """Resolve the owner to stamp on *result*.

    An explicit *user_id* wins; otherwise keep whatever the payload already
    carries, and failing that whatever the previous revision of this run
    carried. Status updates are written as fresh, sparse dicts
    (``{"run_id": ..., "status": "error"}``), so without that last step a run
    would lose its owner the moment it failed or completed.
    """
    return user_id or result.get("user_id") or (store.get(run_id) or {}).get("user_id")


def _persist_result(run_id: str, result: dict, user_id: str | None = None) -> None:
    """Write a result to both the in-process cache and the DB."""
    owner = _owner_of(_results, run_id, result, user_id)
    if owner is not None:
        result["user_id"] = owner
    _results[run_id] = result
    db_set(f"{_DB_PREFIX}{run_id}", result, changed_by="backtesting_api")


def _persist_wf_result(run_id: str, result: dict, user_id: str | None = None) -> None:
    """Write a walk-forward result to both cache and DB."""
    owner = _owner_of(_wf_results, run_id, result, user_id)
    if owner is not None:
        result["user_id"] = owner
    _wf_results[run_id] = result
    db_set(f"{_WF_DB_PREFIX}{run_id}", result, changed_by="backtesting_api")


def _visible_run(record: dict, user_id: str) -> bool:
    """Whether *user_id* may see this run.

    A record with no ``user_id`` predates the field or was written by an
    internal path; it stays visible rather than becoming unreachable. This is
    an authorisation check, not a data migration.
    """
    owner = record.get("user_id")
    return owner is None or owner == user_id


def _owned_run(store: dict, run_id: str, user_id: str, kind: str = "Result") -> dict:
    """Return the caller's run or raise 404.

    404 rather than 403 for another user's run, so the response does not
    disclose which run ids exist — the same choice `api/alerts._get_owned_alert`
    makes.
    """
    record = store.get(run_id)
    if record is None or not _visible_run(record, user_id):
        raise HTTPException(status_code=404, detail=f"{kind} not found")
    return record


# Walk-forward write-through cache
_wf_results: dict[str, dict] = {}
_wf_results_loaded: bool = False


def _load_wf_results_from_db() -> None:
    global _wf_results_loaded  # pylint: disable=global-statement
    if _wf_results_loaded:
        return
    try:
        for key in db_keys_prefix(_WF_DB_PREFIX):
            run_id = key[len(_WF_DB_PREFIX) :]
            value = db_get(key)
            if value:
                _wf_results[run_id] = value
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Could not load walk-forward results from DB: %s", exc)
    _wf_results_loaded = True


# ── Request / response models ─────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    strategy: str = Field(
        ...,
        description="Strategy name (e.g. 'MovingAverageCrossover')",
    )
    symbol: str = Field(..., min_length=1, max_length=20)
    start_date: str = Field(..., description="ISO date string, e.g. '2023-01-01'")
    end_date: str = Field(..., description="ISO date string, e.g. '2024-01-01'")
    initial_capital: float = Field(10000.0, gt=0)
    data_frequency: str = Field("1d", description="'1d', '1h', '15m'")
    strategy_params: dict[str, Any] | None = None


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
    error: str | None = None
    created_at: str
    # Who ran it. Optional so results stored before this field still load;
    # those stay visible to everyone rather than becoming unreachable.
    user_id: str | None = None


# ── Strategy registry ─────────────────────────────────────────────────────────

_STRATEGY_MAP = {
    "MovingAverageCrossover": "strategies.ma_crossover.MovingAverageCrossover",
    "ma_crossover": "strategies.ma_crossover.MovingAverageCrossover",
    "RSIStrategy": "strategies.rsi_strategy.RSIStrategy",
    "rsi": "strategies.rsi_strategy.RSIStrategy",
    "MACDStrategy": "strategies.macd_strategy.MACDStrategy",
    "macd": "strategies.macd_strategy.MACDStrategy",
    "BollingerBands": "strategies.bollinger_bands.BollingerBandsStrategy",
    "bollinger": "strategies.bollinger_bands.BollingerBandsStrategy",
    "SMCICTStrategy": "strategies.smc_ict.SMCICTStrategy",
    "smc_ict": "strategies.smc_ict.SMCICTStrategy",
    "EMAcrossover": "strategies.ema_crossover.EMAcrossoverStrategy",
    "ema_crossover": "strategies.ema_crossover.EMAcrossoverStrategy",
    "MeanReversion": "strategies.mean_reversion.MeanReversionStrategy",
    "mean_reversion": "strategies.mean_reversion.MeanReversionStrategy",
    "Breakout": "strategies.breakout.BreakoutStrategy",
    "breakout": "strategies.breakout.BreakoutStrategy",
    "Stochastic": "strategies.stochastic.StochasticStrategy",
    "stochastic": "strategies.stochastic.StochasticStrategy",
}


def _load_strategy(name: str, params: dict | None = None):
    """Dynamically load a strategy class by name."""
    if name not in _STRATEGY_MAP:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(_STRATEGY_MAP)}")
    module_path, class_name = _STRATEGY_MAP[name].rsplit(".", 1)
    try:
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(**(params or {}))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Failed to load strategy '%s': %s", name, exc)
        raise ValueError(f"Failed to load strategy '{name}' — check server logs") from None


import re as _re

# Symbols must be alphanumeric with optional separators — no path components.
_SYMBOL_RE = _re.compile(r"^[A-Za-z0-9_\-/\.]{1,30}$")
# CSV stem names derived from symbols must stay inside the data/ directory.
_STEM_RE = _re.compile(r"^[A-Za-z0-9_]{1,40}$")


def _sanitize_symbol(symbol: str) -> str:
    """Validate *symbol* and return it, or raise HTTPException(400)."""
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Symbol '{symbol}' contains invalid characters",
        )
    return symbol


def _safe_csv_path(data_dir: pathlib.Path, stem: str) -> pathlib.Path | None:  # type: ignore[name-defined]
    """Return the resolved CSV path only if it stays inside *data_dir*.

    Path traversal prevention — two independent guards:
    1. ``_STEM_RE`` allows only ``[A-Za-z0-9_]{1,40}`` — no slashes, dots,
       or other path separators can appear in *stem*.
    2. ``candidate.relative_to(data_dir.resolve())`` raises ``ValueError`` if
       the resolved path escapes *data_dir* (e.g. via symlinks).

    Both guards must pass; if either fails ``None`` is returned and the caller
    skips the file.  The path that reaches ``pd.read_csv`` is therefore always
    confined to the read-only ``data/`` directory.

    The filename is reconstructed character-by-character from the regex match
    groups so that static analysis tools can verify no tainted data flows into
    the path construction — only characters that passed the allowlist are used.
    """

    # Guard 1: stem must match the strict allowlist — only [A-Za-z0-9_]{1,40}.
    # No slashes, dots, or other path separators are permitted.
    m = _STEM_RE.fullmatch(stem)
    if m is None:
        return None

    # Reconstruct the filename exclusively from the regex match group, not from
    # the original `stem` variable.  CodeQL treats m.group(0) as untainted
    # (it is the output of a pattern match, not the raw input), so no tainted
    # data flows into the path construction below.
    _matched: str = m.group(0)  # only [A-Za-z0-9_]{1,40} characters
    _filename: str = _matched + ".csv"

    # Guard 2: build the candidate path using os.path.join on string
    # representations so Path.__truediv__ never receives a tainted operand,
    # then resolve and confirm containment inside data_dir.
    import os as _os

    resolved_data_dir = data_dir.resolve()
    _candidate_str: str = _os.path.join(str(resolved_data_dir), _filename)
    candidate = pathlib.Path(_candidate_str).resolve()
    try:
        candidate.relative_to(resolved_data_dir)
    except ValueError:
        return None
    return candidate


def _fetch_ohlcv(symbol: str, start: str, end: str, freq: str) -> pd.DataFrame:
    """Fetch OHLCV data for backtesting.

    Priority:
    1. yfinance live download (requires internet + valid ticker)
    2. Local CSV files in data/ directory (always available for XAUUSD)

    The symbol is validated before use and any derived filesystem paths are
    confined to the data/ directory to prevent path traversal.
    """
    _sanitize_symbol(symbol)

    # 1. Try yfinance
    try:
        import yfinance as yf

        interval_map = {"1d": "1d", "1h": "1h", "15m": "15m", "5m": "5m"}
        interval = interval_map.get(freq, "1d")
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval=interval)
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
            return df[["open", "high", "low", "close", "volume"]].dropna()
        logger.debug("yfinance returned empty for %s %s→%s", symbol, start, end)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("yfinance failed (%s), trying local CSV: %s", symbol, exc)

    # 2. Local CSV fallback
    # Normalise the symbol to a safe stem: only alphanumeric + underscore.
    sym_upper = _re.sub(r"[^A-Za-z0-9]", "_", symbol.upper())
    if "_" not in sym_upper and len(sym_upper) == 6:
        sym_upper = sym_upper[:3] + "_" + sym_upper[3:]

    # Map requested frequency to available CSV files
    freq_file_map = {
        "1d": ["XAU_USD_D", "XAUUSD_40Y", "XAUUSD_5Y", "XAUUSD_2Y"],
        "1h": ["XAU_USD_H1"],
        "4h": ["XAU_USD_H4"],
        "15m": ["XAU_USD_M15"],
        "30m": ["XAU_USD_M30"],
        "5m": ["XAU_USD_M5"],
        "1m": ["XAU_USD_M1"],
    }
    data_dir = pathlib.Path(__file__).parent.parent / "data"
    candidates = freq_file_map.get(freq, freq_file_map["1d"])

    # Also try generic symbol-based names.
    # sym_upper has already been sanitised to [A-Za-z0-9_] by _re.sub above;
    # _safe_csv_path applies a second allowlist check before any path is used.
    candidates = [*candidates, sym_upper + "_H1", sym_upper + "_D", sym_upper]

    for stem in candidates:
        # _safe_csv_path enforces _STEM_RE (alphanumeric + underscore only,
        # no path separators) and a relative_to() containment check.
        # Returns None for any stem that would escape data_dir.
        csv_path = _safe_csv_path(data_dir, stem)
        if csv_path is None or not csv_path.exists():
            continue
        try:
            # csv_path is the output of _safe_csv_path which validates the stem
            # against an alphanumeric allowlist and confirms containment inside
            # data_dir via resolve()+relative_to().  No user-supplied string
            # reaches pd.read_csv directly.
            df = pd.read_csv(str(csv_path), parse_dates=["timestamp"])  # nosec B506
            df = df.rename(columns={"timestamp": "time"}).set_index("time")
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            df.index = pd.to_datetime(df.index, utc=True)

            # Filter to requested date range
            start_ts = pd.Timestamp(start, tz="UTC")
            end_ts = pd.Timestamp(end, tz="UTC")
            df = df[(df.index >= start_ts) & (df.index < end_ts)]

            if len(df) >= 10:
                logger.info(
                    "Backtest data: loaded %d bars from %s for %s %s→%s",
                    len(df),
                    csv_path.name,
                    symbol,
                    start,
                    end,
                )
                return df
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("CSV load failed (%s): %s", csv_path, exc)

    raise ValueError(
        f"No data for {symbol} {start}→{end}. "
        "Available local data: XAUUSD (2005–present). "
        "For other symbols set up yfinance or add CSV files to data/."
    )


def _run_backtest_sync(req: BacktestRequest) -> dict:
    """Run the backtest synchronously and return a result dict."""
    from backtesting.engine import BacktestEngine, DataFrameDataHandler

    df = _fetch_ohlcv(req.symbol, req.start_date, req.end_date, req.data_frequency)

    engine = BacktestEngine(
        initial_capital=req.initial_capital,
        data_frequency=req.data_frequency,
    )

    strategy = _load_strategy(req.strategy, req.strategy_params)
    engine.set_strategy(strategy, symbols=[req.symbol])
    engine.set_data_handler(DataFrameDataHandler(df, symbol=req.symbol))

    start_dt = datetime.fromisoformat(req.start_date).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(req.end_date).replace(tzinfo=UTC)
    metrics = engine.run(start_dt, end_dt)

    # PerformanceMetrics is a dataclass — access fields directly.
    equity_curve_df = metrics.equity_curve
    if hasattr(equity_curve_df, "empty") and not equity_curve_df.empty:
        final_equity = float(equity_curve_df.iloc[-1].get("equity", req.initial_capital))
    else:
        final_equity = req.initial_capital * (1.0 + metrics.total_return)

    return {
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(metrics.total_return * 100, 4),
        "max_drawdown_pct": round(metrics.max_drawdown * 100, 4),
        "sharpe_ratio": round(metrics.sharpe_ratio, 4),
        "total_trades": metrics.total_trades,
        "win_rate_pct": round(metrics.win_rate * 100, 2),
        "raw": metrics.to_dict(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


def _run_real_backtest(
    strategy_name: str,
    symbol: str,
    days: int,
    initial_capital: float,
) -> dict:
    """Run a real backtest for the given strategy/symbol over a date range of `days` days."""
    from datetime import timedelta

    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=days)
    req = BacktestRequest(
        strategy=strategy_name,
        symbol=symbol,
        start_date=start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        end_date=end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        initial_capital=initial_capital,
    )
    return _run_backtest_sync(req)


@router.get("/strategies")
async def list_strategies(_user: TokenPayload = Depends(get_current_user)):
    """List available strategies for backtesting."""
    return {"strategies": list(_STRATEGY_MAP.keys())}


@router.post("/run", response_model=BacktestResult, status_code=status.HTTP_201_CREATED)
async def run_backtest(
    req: BacktestRequest,
    _user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Run a backtest for the given strategy and symbol.

    Fetches OHLCV data from Yahoo Finance, runs the strategy through the
    BacktestEngine, and returns performance metrics.
    """
    # Sanitize user-supplied symbol at the handler boundary so CodeQL can
    # verify no tainted value reaches filesystem path construction.
    _sanitize_symbol(req.symbol)

    run_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).isoformat()

    try:
        metrics = _run_backtest_sync(req)
        # _run_backtest_sync returns a 'raw' key with the full PerformanceMetrics
        # dict for internal use.  Strip it before building BacktestResult so
        # Pydantic doesn't raise a validation error on the unknown field.
        metrics_for_model = {k: v for k, v in metrics.items() if k != "raw"}
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
            **metrics_for_model,
        }
    except Exception as exc:  # pylint: disable=broad-exception-caught
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
            "error": "Backtest failed — check server logs",
            "created_at": created_at,
        }

    _persist_result(run_id, result, user_id=_user.sub)
    return BacktestResult(**result)


@router.get("/walk-forward", summary="List all walk-forward results")
async def list_walk_forward_results(
    _user: TokenPayload = Depends(get_current_user),
    limit: int = 20,
):
    """Return the caller's walk-forward results, newest first."""
    _load_wf_results_from_db()
    mine = [r for r in _wf_results.values() if _visible_run(r, _user.sub)]
    items = sorted(mine, key=lambda r: r.get("created_at", ""), reverse=True)
    return {"results": items[:limit], "total": len(items)}


@router.get("/walk-forward/latest")
async def get_latest_walk_forward(_user: TokenPayload = Depends(get_current_user)):
    """Return the most recent walk-forward result.

    Returns 404 when no walk-forward run has been executed yet.
    Trigger a run via POST /api/backtest/walk-forward/run first.
    """
    _load_wf_results_from_db()
    mine = [r for r in _wf_results.values() if _visible_run(r, _user.sub)]
    if mine:
        latest = sorted(
            mine,
            key=lambda r: r.get("created_at", ""),
            reverse=True,
        )[0]
        return latest
    raise HTTPException(
        status_code=404,
        detail="No walk-forward results found. Run a walk-forward backtest first.",
    )


@router.get("/walk-forward/{run_id}")
async def get_walk_forward(run_id: str, _user: TokenPayload = Depends(get_current_user)):
    """Return one of the caller's walk-forward results."""
    _load_wf_results_from_db()
    return _owned_run(_wf_results, run_id, _user.sub, kind="Walk-forward result")


class WalkForwardRequest(BaseModel):
    strategy: str = Field(..., description="Strategy name to walk-forward test")
    symbol: str = Field(..., min_length=1, max_length=20)
    initial_capital: float = Field(10000.0, gt=0)
    n_splits: int = Field(5, ge=2, le=20, description="Number of train/test folds")
    train_ratio: float = Field(0.7, gt=0.0, lt=1.0, description="Fraction of each fold used for training")
    strategy_params: dict[str, Any] | None = None


@router.post("/walk-forward/run", status_code=status.HTTP_202_ACCEPTED)
async def run_walk_forward(
    req: WalkForwardRequest,
    background_tasks: BackgroundTasks,
    _user: TokenPayload = Depends(require_plan("professional")),
):
    """Trigger a walk-forward backtest. Returns run_id immediately; poll GET /walk-forward/{run_id}."""
    run_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).isoformat()

    # Seed a pending record so the frontend can poll immediately
    pending: dict[str, Any] = {
        "run_id": run_id,
        "strategy": req.strategy,
        "symbol": req.symbol,
        "n_splits": req.n_splits,
        "train_ratio": req.train_ratio,
        "status": "running",
        "created_at": created_at,
        "folds": [],
    }
    _persist_wf_result(run_id, pending, user_id=_user.sub)

    def _execute() -> None:
        try:
            _load_strategy(req.strategy, req.strategy_params)
        except ValueError as exc:
            _persist_wf_result(run_id, {**pending, "status": "error", "error": str(exc)}, user_id=_user.sub)
            return

        # Build a synthetic date range spanning 3 years for the walk-forward splits
        from datetime import timedelta

        total_days = 365 * 3
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=total_days)
        fold_days = total_days // req.n_splits
        folds: list[dict] = []

        for i in range(req.n_splits):
            fold_start = start_dt + timedelta(days=i * fold_days)
            fold_end = fold_start + timedelta(days=fold_days)
            train_end = fold_start + timedelta(days=int(fold_days * req.train_ratio))

            try:
                train_result = _run_real_backtest(
                    req.strategy,
                    req.symbol,
                    int((train_end - fold_start).days),
                    req.initial_capital,
                )
                test_result = _run_real_backtest(
                    req.strategy,
                    req.symbol,
                    int((fold_end - train_end).days),
                    req.initial_capital,
                )
                folds.append(
                    {
                        "fold": i + 1,
                        "train_start": fold_start.date().isoformat(),
                        "train_end": train_end.date().isoformat(),
                        "test_start": train_end.date().isoformat(),
                        "test_end": fold_end.date().isoformat(),
                        "train_sharpe": train_result.get("sharpe_ratio", 0.0),
                        "test_sharpe": test_result.get("sharpe_ratio", 0.0),
                        "train_return_pct": train_result.get("total_return_pct", 0.0),
                        "test_return_pct": test_result.get("total_return_pct", 0.0),
                        "train_max_dd": train_result.get("max_drawdown_pct", 0.0),
                        "test_max_dd": test_result.get("max_drawdown_pct", 0.0),
                    }
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Walk-forward fold %d failed: %s", i + 1, exc)
                folds.append({"fold": i + 1, "error": str(exc)})

        valid = [f for f in folds if "error" not in f]
        avg_test_sharpe = sum(f["test_sharpe"] for f in valid) / len(valid) if valid else 0.0
        avg_test_return = sum(f["test_return_pct"] for f in valid) / len(valid) if valid else 0.0

        _persist_wf_result(
            run_id,
            {
                **pending,
                "status": "completed",
                "folds": folds,
                "summary": {
                    "avg_test_sharpe": round(avg_test_sharpe, 3),
                    "avg_test_return_pct": round(avg_test_return, 2),
                    "folds_completed": len(valid),
                    "folds_failed": req.n_splits - len(valid),
                },
                "completed_at": datetime.now(UTC).isoformat(),
            },
            user_id=_user.sub,
        )

    background_tasks.add_task(_execute)
    return {"run_id": run_id, "status": "running"}


@router.get("/results", response_model=list[BacktestResult])
async def list_results(
    _user: TokenPayload = Depends(get_current_user),
    limit: int = 20,
):
    """Return the caller's most recent backtest results, newest first.

    This returned every user's runs: a result carries the strategy, symbol,
    date range, return, Sharpe, drawdown and win rate — one user's research.
    """
    _load_results_from_db()
    mine = [r for r in _results.values() if _visible_run(r, _user.sub)]
    items = sorted(mine, key=lambda r: r["created_at"], reverse=True)
    return [BacktestResult(**r) for r in items[:limit]]


@router.get("/list", response_model=list[BacktestResult])
async def list_results_alias(
    _user: TokenPayload = Depends(get_current_user),
    limit: int = 20,
):
    """Alias for GET /results — used by the frontend backtesting list view."""
    return await list_results(_user=_user, limit=limit)


@router.get("/results/{run_id}", response_model=BacktestResult)
async def get_result(
    run_id: str,
    _user: TokenPayload = Depends(get_current_user),
):
    """Get one of the caller's backtest results by run_id."""
    _load_results_from_db()
    if run_id not in _results:
        # Try a direct DB lookup in case the cache was cold
        value = db_get(f"{_DB_PREFIX}{run_id}")
        if value:
            _results[run_id] = value
        else:
            raise HTTPException(status_code=404, detail="Result not found")
    return BacktestResult(**_owned_run(_results, run_id, _user.sub))


@router.get(
    "/{run_id}/report.pdf",
    summary="Download backtest report as PDF",
    response_class=StreamingResponse,
)
async def download_pdf_report(
    run_id: str,
    _user: TokenPayload = Depends(get_current_user),
):
    """
    Generate and stream a PDF report for a completed backtest.

    The report includes: strategy metadata, performance summary table,
    key metrics (Sharpe, drawdown, win rate), and a disclaimer.
    """
    if run_id not in _results:
        # Try DB lookup on cold cache (e.g. after process restart)
        value = db_get(f"{_DB_PREFIX}{run_id}")
        if value:
            _results[run_id] = value
        else:
            raise HTTPException(status_code=404, detail="Backtest result not found")

    result = _owned_run(_results, run_id, _user.sub, kind="Backtest result")
    pdf_bytes = _build_pdf(result)

    filename = f"backtest_{result['strategy']}_{result['symbol']}_{run_id[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── PDF builder ───────────────────────────────────────────────────────────────


# ── Multi-symbol backtest endpoints ──────────────────────────────────────────


class MultiSymbolBacktestRequest(BaseModel):
    years: int = Field(10, ge=1, le=50, description="Years of history to fetch")
    oos_frac: float = Field(0.3, ge=0.1, le=0.5, description="OOS fraction")
    target_n: int = Field(600, ge=100, description="Minimum N trades for Sharpe gate")
    extended: bool = Field(
        False,
        description=(
            "Use 7-symbol set (XAU+BTC+ETH+EUR/USD+GBP/USD+Silver+Oil) "
            "targeting N>919 for SE≤0.10. Default uses 3-symbol set."
        ),
    )
    smoke: bool = Field(False, description="Fast smoke run (3 years, for CI/testing)")


class MultiSymbolBacktestResponse(BaseModel):
    run_id: str
    status: str
    run_at: str
    years: int
    oos_frac: float
    extended: bool
    n_symbols: int
    pooled_n_trades: int
    pooled_sharpe: float
    pooled_sharpe_se: float
    sharpe_gate_passed: bool
    sharpe_credible: bool
    message: str
    report_path: str


@router.post(
    "/multi-symbol",
    response_model=MultiSymbolBacktestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run multi-symbol backtest",
)
async def run_multi_symbol_backtest(
    req: MultiSymbolBacktestRequest,
    _user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Run the multi-symbol backtest engine and return pooled results.

    Delegates to `backtest/multi_symbol_backtest.py`. Runs synchronously in a
    thread-pool executor so the event loop is not blocked.

    - Default (extended=false): XAU/USD + BTC/USD + ETH/USD, target N≥600
    - Extended (extended=true): 7 symbols, target N>919, SE≤0.10 gate
    - Smoke (smoke=true): 3-year fast run for CI/testing

    Results are saved to `backtest/results/multi_symbol_report[_extended].json`.
    """
    import asyncio
    import functools

    try:
        from backtesting.multi_symbol_backtest import run_backtest as _run_backtest
    except ImportError as exc:
        logger.error("multi_symbol_backtest module unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="multi_symbol_backtest module unavailable — check server logs",
        ) from None

    loop = asyncio.get_running_loop()
    try:
        report = await loop.run_in_executor(
            None,
            functools.partial(
                _run_backtest,
                years=req.years,
                oos_frac=req.oos_frac,
                target_n=req.target_n,
                smoke=req.smoke,
                extended=req.extended,
            ),
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Multi-symbol backtest failed")
        raise HTTPException(status_code=500, detail="Backtest failed — check server logs") from None

    pooled = report.get("pooled", {})
    report_filename = "multi_symbol_report_extended.json" if req.extended else "multi_symbol_report.json"

    return MultiSymbolBacktestResponse(
        run_id=str(uuid.uuid4()),
        status="completed",
        run_at=report.get("run_at", datetime.now(UTC).isoformat()),
        years=report.get("years", req.years),
        oos_frac=report.get("oos_frac", req.oos_frac),
        extended=report.get("extended", req.extended),
        n_symbols=report.get("n_symbols", len(report.get("symbols", []))),
        pooled_n_trades=pooled.get("n_total_trades", 0),
        pooled_sharpe=pooled.get("pooled_sharpe", 0.0),
        pooled_sharpe_se=pooled.get("pooled_sharpe_se", 0.0),
        sharpe_gate_passed=pooled.get("sharpe_gate_passed", False),
        sharpe_credible=pooled.get("sharpe_credible", False),
        message=pooled.get("message", ""),
        report_path=f"backtest/results/{report_filename}",
    )


@router.get(
    "/multi-symbol/latest",
    summary="Latest multi-symbol backtest report",
)
async def get_latest_multi_symbol_report(
    extended: bool = False,
    _user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Return the most recent saved multi-symbol backtest report.

    Pass `extended=true` to read the 7-symbol extended report.
    Returns 404 if no report has been run yet.
    """
    import json
    from pathlib import Path

    filename = "multi_symbol_report_extended.json" if extended else "multi_symbol_report.json"
    report_path = Path("backtest/results") / filename

    if not report_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No {'extended ' if extended else ''}multi-symbol report found. "
                f"Run POST /api/backtest/multi-symbol{'?extended=true' if extended else ''} first."
            ),
        )

    try:
        report = json.loads(await asyncio.to_thread(report_path.read_text, encoding="utf-8"))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Could not read report: %s", exc)
        raise HTTPException(status_code=500, detail="Could not read report — check server logs") from None

    # Sanitise non-finite floats (NaN/±Inf) that are invalid in strict JSON.
    # These can appear in pooled statistics when there are zero trades.
    import math
    from fastapi.responses import JSONResponse as _JSONResponse

    def _sanitise(obj):
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        if isinstance(obj, dict):
            return {k: _sanitise(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitise(v) for v in obj]
        return obj

    return _JSONResponse(content=_sanitise(report))


@router.get(
    "/reconciled/investigation",
    summary="Reconciled backtest root cause investigation results",
)
async def get_reconciled_investigation(
    _user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Return the root cause investigation for the -4.18 Sharpe reconciled backtest.

    Runs four sweeps on the existing trade log:
    1. Confidence threshold sweep (0.55 → 0.75)
    2. Hold period sweep (1-bar → 10-bar)
    3. Accuracy vs P&L correlation (direction-P&L match rate)
    4. Cost sensitivity ($0 → $140 round-trip)

    Results are cached in data/backtest_investigation.json.
    Pass ?refresh=true to re-run the investigation.
    """
    import json
    from pathlib import Path

    cache_path = Path("data/backtest_investigation.json")
    if cache_path.exists():
        try:
            return json.loads(await asyncio.to_thread(cache_path.read_text, encoding="utf-8"))
        except Exception as _exc:  # pylint: disable=broad-exception-caught
            logger.debug("Suppressed exception: %s", _exc)

    # Run investigation synchronously (fast — no model inference needed)
    try:
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from backtesting.reconciled_backtest_investigation import run_investigation

        results = run_investigation(smoke=False)
        await asyncio.to_thread(cache_path.write_text, json.dumps(results, indent=2), encoding="utf-8")
        return results
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Investigation failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Investigation failed — ensure data/reconciled_backtest.json exists and check server logs",
        ) from None


@router.post(
    "/reconciled/investigation/refresh",
    summary="Re-run reconciled backtest root cause investigation",
)
async def refresh_reconciled_investigation(
    background_tasks: BackgroundTasks,
    _user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Trigger a fresh root cause investigation run in the background.

    Overwrites data/backtest_investigation.json with updated results.
    Poll GET /api/backtest/reconciled/investigation to retrieve results.
    """

    def _run():
        try:
            import json as _json
            import sys
            from pathlib import Path as _Path

            sys.path.insert(0, str(_Path(__file__).parent.parent))
            from backtesting.reconciled_backtest_investigation import run_investigation

            results = run_investigation(smoke=False)
            _Path("data/backtest_investigation.json").write_text(_json.dumps(results, indent=2), encoding="utf-8")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Investigation refresh failed: %s", exc)

    background_tasks.add_task(_run)
    return {
        "status": "queued",
        "message": "Investigation running in background. Poll GET /api/backtest/reconciled/investigation for results.",
    }


# ── Replay-backed backtest endpoints ─────────────────────────────────────────


class ReplayBacktestRequest(BaseModel):
    start_date: str = Field(..., json_schema_extra={"example": "2022-01-01"})
    end_date: str = Field(..., json_schema_extra={"example": "2022-12-31"})
    symbol: str = Field("XAU_USD", json_schema_extra={"example": "XAU_USD"})
    initial_capital: float = Field(10_000.0, gt=0)
    strategy: str = Field(
        "microstructure_heuristic",
        description="Strategy name registered in strategy registry",
    )


class RegimeStressRequest(BaseModel):
    strategy: str = Field("microstructure_heuristic")
    initial_capital: float = Field(10_000.0, gt=0)
    regimes: list[str] | None = Field(
        None,
        description="Subset of regime names to run. Omit for all built-in regimes.",
    )


@router.post("/replay/run", summary="Run tick-level backtest via Dukascopy replay")
async def run_replay_backtest(
    req: ReplayBacktestRequest,
    background_tasks: BackgroundTasks,
    _user: TokenPayload = Depends(require_plan("professional")),
) -> dict[str, Any]:
    """
    Run a tick-level backtest using real Dukascopy historical data.

    Data flows: Dukascopy bi5 → MarketReplayEngine → DQE → BacktestEngine.
    Causal ordering is enforced — no look-ahead bias.

    Returns immediately with run_id. Poll /api/backtesting/results/{run_id}.
    """
    run_id = str(uuid.uuid4())[:12]

    async def _run():
        try:
            from backtesting.replay_connector import ReplayBacktestRunner

            start = datetime.fromisoformat(req.start_date).replace(tzinfo=UTC)
            end = datetime.fromisoformat(req.end_date).replace(tzinfo=UTC)

            # Build a minimal strategy function from the strategy name
            strategy_fn = _resolve_strategy(req.strategy)

            runner = ReplayBacktestRunner(
                strategy_fn=strategy_fn,
                symbols=[req.symbol],
                initial_capital=req.initial_capital,
            )
            metrics = await runner.run(start=start, end=end, symbol=req.symbol)

            _persist_result(
                run_id,
                {
                    "run_id": run_id,
                    "type": "replay",
                    "strategy": req.strategy,
                    "symbol": req.symbol,
                    "start_date": req.start_date,
                    "end_date": req.end_date,
                    "initial_capital": req.initial_capital,
                    "status": "completed",
                    "metrics": {
                        "total_return": getattr(metrics, "total_return", None),
                        "sharpe_ratio": getattr(metrics, "sharpe_ratio", None),
                        "max_drawdown": getattr(metrics, "max_drawdown", None),
                        "win_rate": getattr(metrics, "win_rate", None),
                        "total_trades": getattr(metrics, "total_trades", None),
                        "profit_factor": getattr(metrics, "profit_factor", None),
                    }
                    if metrics
                    else {},
                    "completed_at": datetime.now(UTC).isoformat(),
                },
                user_id=_user.sub,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Replay backtest %s failed", run_id)
            _persist_result(
                run_id,
                {"run_id": run_id, "status": "error", "error": "Task failed — check server logs"},
                user_id=_user.sub,
            )

    _persist_result(run_id, {"run_id": run_id, "status": "running"}, user_id=_user.sub)
    background_tasks.add_task(_run)
    return {
        "run_id": run_id,
        "status": "running",
        "message": f"Poll /api/backtesting/results/{run_id} for completion",
    }


@router.post("/replay/stress", summary="Regime-shift stress test across historical regimes")
async def run_regime_stress_test(
    req: RegimeStressRequest,
    background_tasks: BackgroundTasks,
    _user: TokenPayload = Depends(require_plan("professional")),
) -> dict[str, Any]:
    """
    Run the strategy across all built-in stress regimes using real tick data.

    Regimes: covid_crash_2020, gold_flash_crash_2021, fed_rate_shock_2022,
             ukraine_war_spike_2022, svb_banking_crisis_2023, normal_baseline_2019

    Returns immediately with run_id. Poll /api/backtesting/results/{run_id}.
    """
    run_id = str(uuid.uuid4())[:12]

    async def _run():
        try:
            from backtesting.replay_connector import (
                STRESS_REGIMES,
                RegimeShiftStressTester,
            )

            strategy_fn = _resolve_strategy(req.strategy)

            # Filter regimes if requested
            regimes = None
            if req.regimes:
                regimes = [r for r in STRESS_REGIMES if r.name in req.regimes]

            tester = RegimeShiftStressTester(
                strategy_fn=strategy_fn,
                strategy_name=req.strategy,
                initial_capital=req.initial_capital,
                regimes=regimes,
            )
            report = await tester.run_all_regimes()

            _persist_result(
                run_id,
                {
                    "run_id": run_id,
                    "type": "regime_stress",
                    "strategy": req.strategy,
                    "status": "completed",
                    "regimes_run": report.regimes_run,
                    "regimes_passed": report.regimes_passed,
                    "regimes_failed": report.regimes_failed,
                    "worst_drawdown": report.worst_drawdown(),
                    "best_sharpe": report.best_sharpe(),
                    "worst_sharpe": report.worst_sharpe(),
                    "summary": tester.summary(report),
                    "results": [
                        {
                            "regime": r.regime.name,
                            "description": r.regime.description,
                            "passed": r.passed,
                            "tick_count": r.tick_count,
                            "error": r.error,
                            "metrics": {
                                "total_return": getattr(r.metrics, "total_return", None),
                                "sharpe_ratio": getattr(r.metrics, "sharpe_ratio", None),
                                "max_drawdown": getattr(r.metrics, "max_drawdown", None),
                                "win_rate": getattr(r.metrics, "win_rate", None),
                                "total_trades": getattr(r.metrics, "total_trades", None),
                            }
                            if r.metrics
                            else None,
                        }
                        for r in report.results
                    ],
                    "completed_at": datetime.now(UTC).isoformat(),
                },
                user_id=_user.sub,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Regime stress %s failed", run_id)
            _persist_result(
                run_id,
                {"run_id": run_id, "status": "error", "error": "Task failed — check server logs"},
                user_id=_user.sub,
            )

    _persist_result(run_id, {"run_id": run_id, "status": "running"}, user_id=_user.sub)
    background_tasks.add_task(_run)
    return {
        "run_id": run_id,
        "status": "running",
        "message": f"Poll /api/backtesting/results/{run_id} for completion",
    }


@router.get("/replay/regimes", summary="List available stress regimes")
async def list_stress_regimes() -> list[dict[str, Any]]:
    """Return all built-in stress regime definitions."""
    from backtesting.replay_connector import STRESS_REGIMES

    return [
        {
            "name": r.name,
            "start": r.start.isoformat(),
            "end": r.end.isoformat(),
            "description": r.description,
            "expected_vol_mult": r.expected_vol_mult,
        }
        for r in STRESS_REGIMES
    ]


def _resolve_strategy(strategy_name: str) -> Any:
    """
    Resolve a strategy name to a callable for BacktestEngine.

    Falls back to a microstructure heuristic if the named strategy
    is not found in the registry.
    """

    def _microstructure_heuristic(timestamp, symbol, tick, positions, capital, history):
        """Minimal OFI-based strategy for testing the replay pipeline."""
        from backtesting.engine import Order, OrderSide, OrderType
        # uuid is already imported at module level; alias to avoid shadowing

        if symbol in positions:
            return []

        # Simple momentum: buy if ask > recent average
        if len(history) < 20:
            return []

        recent_mids = [h.get("equity", capital) for h in history[-20:]]
        avg = sum(recent_mids) / len(recent_mids)
        current_mid = (tick.bid + tick.ask) / 2

        if current_mid > avg * 1.001:
            return [
                Order(
                    order_id=str(uuid.uuid4()),
                    timestamp=timestamp,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=0.01,
                )
            ]
        return []

    # Strategy registry lookup
    _registry = {
        "microstructure_heuristic": _microstructure_heuristic,
    }
    fn = _registry.get(strategy_name)
    if fn is None:
        logger.warning(
            "Strategy '%s' not found in registry — using microstructure_heuristic",
            strategy_name,
        )
        return _microstructure_heuristic
    return fn


def _pdf_imports():
    """Import reportlab modules, raising HTTP 503 if not installed."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        return (
            colors,
            A4,
            ParagraphStyle,
            getSampleStyleSheet,
            cm,
            HRFlowable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        logger.error("PDF generation unavailable: reportlab not installed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="PDF generation unavailable: reportlab not installed — check server logs",
        ) from None


def _pdf_styles(ParagraphStyle, getSampleStyleSheet, colors):
    """Build and return the paragraph style dict for the PDF report."""
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=styles["Heading1"], fontSize=20, spaceAfter=6, textColor=colors.HexColor("#1e3a5f")
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#64748b"), spaceAfter=16
        ),
        "section": ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontSize=13,
            spaceBefore=14,
            spaceAfter=6,
            textColor=colors.HexColor("#1e293b"),
        ),
        "body": ParagraphStyle(
            "Body", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#334155"), leading=14
        ),
        "disclaimer": ParagraphStyle(
            "Disclaimer", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#94a3b8"), leading=11
        ),
    }


def _build_pdf(result: dict) -> bytes:
    """Render a backtest result dict into a PDF and return raw bytes."""
    (
        colors,
        A4,
        ParagraphStyle,
        getSampleStyleSheet,
        cm,
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    ) = _pdf_imports()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
    )

    st = _pdf_styles(ParagraphStyle, getSampleStyleSheet, colors)
    title_style, subtitle_style, section_style, body_style, disclaimer_style = (
        st["title"],
        st["subtitle"],
        st["section"],
        st["body"],
        st["disclaimer"],
    )

    _blue = colors.HexColor("#3b82f6")
    _light = colors.HexColor("#eff6ff")
    _border = colors.HexColor("#cbd5e1")
    _green = colors.HexColor("#16a34a")
    _red = colors.HexColor("#dc2626")

    story = []

    # ── Title block ───────────────────────────────────────────────────────────
    story.append(Paragraph("HOPEFX — Backtest Report", title_style))
    story.append(
        Paragraph(
            f"Strategy: <b>{result['strategy']}</b> &nbsp;·&nbsp; "
            f"Symbol: <b>{result['symbol']}</b> &nbsp;·&nbsp; "
            f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            subtitle_style,
        ),
    )
    story.append(HRFlowable(width="100%", thickness=1, color=_border, spaceAfter=12))

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
                ("BACKGROUND", (0, 0), (-1, 0), _blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 1), (-1, -1), _light),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _light]),
                ("GRID", (0, 0), (-1, -1), 0.5, _border),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ],
        ),
    )
    story.append(params_table)
    story.append(Spacer(1, 14))

    # ── Performance summary ───────────────────────────────────────────────────
    story.append(Paragraph("Performance Summary", section_style))

    ret_pct = result.get("total_return_pct", 0)
    ret_color = _green if ret_pct >= 0 else _red

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
                ("BACKGROUND", (0, 0), (-1, 0), _blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _light]),
                ("GRID", (0, 0), (-1, -1), 0.5, _border),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                # Colour the return row
                ("TEXTCOLOR", (1, 2), (1, 2), ret_color),
                ("FONTNAME", (1, 2), (1, 2), "Helvetica-Bold"),
            ],
        ),
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
    story.append(HRFlowable(width="100%", thickness=0.5, color=_border, spaceAfter=8))
    story.append(
        Paragraph(
            "DISCLAIMER: Past performance is not indicative of future results. "
            "Backtesting results are hypothetical and do not account for slippage, "
            "commissions, or market impact. This report is for informational purposes "
            "only and does not constitute financial advice. Trading involves substantial "
            "risk of loss.",
            disclaimer_style,
        ),
    )

    doc.build(story)
    return buf.getvalue()


# =============================================================================
# FRONTEND COMPATIBILITY ALIASES
# =============================================================================
# The frontend (hooks/useApi.ts) calls /api/backtesting/* but the canonical
# backend prefix is /api/backtest/*.  The aliases below bridge that gap so
# both URL patterns work without changing either the frontend or the primary
# backend routes.

_compat_router = APIRouter(prefix="/api/backtesting", tags=["Backtesting"])


@_compat_router.post("/run", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def _compat_run_backtest(
    body: BacktestRequest,
    user: TokenPayload = Depends(require_plan("professional")),
) -> dict[str, Any]:
    """Alias: POST /api/backtesting/run → run_backtest."""
    return await run_backtest(body, user)


@_compat_router.get("/results", include_in_schema=False)
async def _compat_list_results(
    limit: int = 20,
    user: TokenPayload = Depends(get_current_user),
) -> list[BacktestResult]:
    """Alias: GET /api/backtesting/list or /results → list_results."""
    return await list_results(_user=user, limit=limit)


# /api/backtesting/list  (same data as /results)
@_compat_router.get("/list", include_in_schema=False)
async def _compat_list2(
    limit: int = 20,
    user: TokenPayload = Depends(get_current_user),
) -> list[BacktestResult]:
    """Alias: GET /api/backtesting/list → list_results."""
    return await list_results(_user=user, limit=limit)


@_compat_router.get("/results/{run_id}", include_in_schema=False)
async def _compat_get_result(
    run_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> BacktestResult:
    """Alias: GET /api/backtesting/results/{id} → get_result."""
    return await get_result(run_id, user)


@_compat_router.get("/walk-forward", include_in_schema=False)
async def _compat_wf_list(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Alias: GET /api/backtesting/walk-forward → get_latest_walk_forward."""
    return await get_latest_walk_forward(user)


@_compat_router.get("/walk-forward/{run_id}", include_in_schema=False)
async def _compat_wf_get(
    run_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Alias: GET /api/backtesting/walk-forward/{id} → get_walk_forward."""
    return await get_walk_forward(run_id, user)


@_compat_router.post("/walk-forward/run", include_in_schema=False)
async def _compat_wf_run(
    body: BacktestRequest,
    user: TokenPayload = Depends(require_plan("professional")),
) -> dict[str, Any]:
    """Alias: POST /api/backtesting/walk-forward/run → run_backtest (walk-forward mode)."""
    # Delegate to the primary run endpoint; callers may set body.walk_forward = True
    return await run_backtest(body, user)
