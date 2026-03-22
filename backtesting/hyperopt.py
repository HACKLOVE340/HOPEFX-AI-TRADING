"""
Hyperopt — Bayesian Strategy Parameter Optimization

Uses Optuna (TPE sampler) to find optimal strategy parameters
far more efficiently than grid search.

Comparable to FreqTrade's hyperopt but integrated with HOPEFX's
backtesting engine and strategy framework.

Usage:
    from backtesting.hyperopt import HyperoptEngine, ParamSpace

    space = {
        "period":    ParamSpace.int(5, 50),
        "oversold":  ParamSpace.float(20.0, 40.0),
        "overbought":ParamSpace.float(60.0, 80.0),
    }

    engine = HyperoptEngine(
        strategy_class=RSIStrategy,
        market_data=df,           # OHLCV DataFrame
        param_space=space,
        n_trials=100,
        metric="sharpe_ratio",    # or "total_return", "calmar_ratio", "win_rate"
        direction="maximize",
    )
    result = engine.run()
    print(result.best_params)
    print(result.best_value)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Parameter space helpers ──────────────────────────────────────────────────

@dataclass
class _Param:
    kind: str          # "int" | "float" | "categorical" | "bool"
    low: Any = None
    high: Any = None
    choices: Any = None
    step: Any = None
    log: bool = False  # log-scale for float/int


class ParamSpace:
    """Helpers to define the search space for each parameter."""

    @staticmethod
    def int(low: int, high: int, step: int = 1) -> _Param:
        return _Param("int", low=low, high=high, step=step)

    @staticmethod
    def float(low: float, high: float, step: float = None, log: bool = False) -> _Param:
        return _Param("float", low=low, high=high, step=step, log=log)

    @staticmethod
    def categorical(choices: List[Any]) -> _Param:
        return _Param("categorical", choices=choices)

    @staticmethod
    def bool() -> _Param:
        return _Param("categorical", choices=[True, False])


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class HyperoptResult:
    best_params: Dict[str, Any]
    best_value: float
    metric: str
    n_trials: int
    duration_seconds: float
    all_trials: List[Dict[str, Any]] = field(default_factory=list)
    study_name: str = ""

    def summary(self) -> str:
        lines = [
            f"Hyperopt Result — {self.metric}",
            f"  Best value : {self.best_value:.6f}",
            f"  Best params: {self.best_params}",
            f"  Trials     : {self.n_trials}",
            f"  Duration   : {self.duration_seconds:.1f}s",
        ]
        return "\n".join(lines)


# ── Core engine ──────────────────────────────────────────────────────────────

class HyperoptEngine:
    """
    Bayesian hyperparameter optimizer for HOPEFX strategies.

    Wraps Optuna's TPE sampler. Each trial:
      1. Samples parameters from the defined space
      2. Instantiates the strategy with those parameters
      3. Runs a fast vectorised backtest on the provided OHLCV data
      4. Returns the chosen metric as the objective value

    The engine is framework-agnostic: any callable that accepts
    ``(params, market_data)`` and returns a float can be used as
    the objective via ``custom_objective``.
    """

    def __init__(
        self,
        strategy_class,
        market_data: pd.DataFrame,
        param_space: Dict[str, _Param],
        n_trials: int = 100,
        metric: str = "sharpe_ratio",
        direction: Literal["maximize", "minimize"] = "maximize",
        initial_capital: float = 100_000.0,
        commission: float = 0.001,       # 0.1% per trade
        slippage: float = 0.0005,        # 0.05% per trade
        timeout_seconds: Optional[float] = None,
        n_jobs: int = 1,
        custom_objective: Optional[Callable] = None,
        study_name: str = "hopefx_hyperopt",
        seed: int = 42,
    ):
        self.strategy_class = strategy_class
        self.market_data = market_data.copy()
        self.param_space = param_space
        self.n_trials = n_trials
        self.metric = metric
        self.direction = direction
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.timeout_seconds = timeout_seconds
        self.n_jobs = n_jobs
        self.custom_objective = custom_objective
        self.study_name = study_name
        self.seed = seed
        self._study = None

    def run(self) -> HyperoptResult:
        """Run the optimization and return the best result."""
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            raise ImportError("optuna is required for hyperopt. pip install optuna")

        import optuna

        t0 = time.time()
        sampler = optuna.samplers.TPESampler(seed=self.seed)
        self._study = optuna.create_study(
            direction=self.direction,
            sampler=sampler,
            study_name=self.study_name,
        )

        self._study.optimize(
            self._objective,
            n_trials=self.n_trials,
            timeout=self.timeout_seconds,
            n_jobs=self.n_jobs,
            show_progress_bar=False,
        )

        best = self._study.best_trial
        all_trials = [
            {
                "number": t.number,
                "value": t.value,
                "params": t.params,
                "state": str(t.state),
            }
            for t in self._study.trials
        ]

        result = HyperoptResult(
            best_params=best.params,
            best_value=best.value,
            metric=self.metric,
            n_trials=len(self._study.trials),
            duration_seconds=time.time() - t0,
            all_trials=all_trials,
            study_name=self.study_name,
        )
        logger.info(result.summary())
        return result

    def _objective(self, trial) -> float:
        params = self._suggest_params(trial)

        if self.custom_objective:
            try:
                return self.custom_objective(params, self.market_data)
            except Exception as exc:
                logger.debug("Custom objective failed: %s", exc)
                return float("-inf") if self.direction == "maximize" else float("inf")

        return self._backtest_objective(params)

    def _suggest_params(self, trial) -> Dict[str, Any]:
        params = {}
        for name, spec in self.param_space.items():
            if spec.kind == "int":
                params[name] = trial.suggest_int(
                    name, spec.low, spec.high,
                    step=spec.step or 1,
                    log=spec.log,
                )
            elif spec.kind == "float":
                if spec.step:
                    params[name] = trial.suggest_float(
                        name, spec.low, spec.high, step=spec.step
                    )
                else:
                    params[name] = trial.suggest_float(
                        name, spec.low, spec.high, log=spec.log
                    )
            elif spec.kind == "categorical":
                params[name] = trial.suggest_categorical(name, spec.choices)
        return params

    def _backtest_objective(self, params: Dict[str, Any]) -> float:
        """
        Vectorised backtest — no loop overhead, runs in milliseconds.

        Instantiates the strategy, generates signals on the full
        OHLCV DataFrame, then computes the requested metric.
        """
        try:
            from strategies.base import StrategyConfig
            cfg = StrategyConfig(
                name=self.strategy_class.__name__,
                symbol=self.market_data.get("symbol", ["XAUUSD"])[0]
                if hasattr(self.market_data, "get") else "XAUUSD",
                timeframe="1h",
                parameters=params,
            )
            strategy = self.strategy_class(cfg, **params)
        except TypeError:
            # Strategy doesn't accept **params — pass via config only
            try:
                from strategies.base import StrategyConfig
                cfg = StrategyConfig(
                    name=self.strategy_class.__name__,
                    symbol="XAUUSD",
                    timeframe="1h",
                    parameters=params,
                )
                strategy = self.strategy_class(cfg)
            except Exception as exc:
                logger.debug("Strategy init failed: %s", exc)
                return float("-inf") if self.direction == "maximize" else float("inf")

        # Generate signals using the legacy dict-signal method if available
        df = self.market_data.copy()
        if not {"open", "high", "low", "close"}.issubset(df.columns):
            return float("-inf") if self.direction == "maximize" else float("inf")

        try:
            gen = getattr(strategy, "_generate_dict_signal", None) or \
                  getattr(strategy, "generate_signal_from_data", None)
            if gen is None:
                # Use analyze + generate_signal path
                prices = df["close"].tolist()
                signals = []
                window = min(50, len(prices))
                for i in range(window, len(prices)):
                    data = {"prices": prices[max(0, i-100):i+1], "price": prices[i]}
                    analysis = strategy.analyze(data)
                    sig = strategy.generate_signal(analysis)
                    signals.append(sig.signal_type.value if sig else "HOLD")
            else:
                # Rolling window approach for dict-signal strategies
                signals = []
                for i in range(50, len(df)):
                    window_df = df.iloc[max(0, i-100):i+1].copy()
                    result = gen(window_df)
                    signals.append(result.get("type", "HOLD"))

            return self._compute_metric(df, signals)
        except Exception as exc:
            logger.debug("Backtest failed for params %s: %s", params, exc)
            return float("-inf") if self.direction == "maximize" else float("inf")

    def _compute_metric(self, df: pd.DataFrame, signals: List[str]) -> float:
        """Compute the target metric from a signal list."""
        close = df["close"].values
        n = len(signals)
        offset = len(close) - n

        returns = np.diff(close[offset:]) / close[offset:-1]
        position = 0.0
        equity = [self.initial_capital]
        current = self.initial_capital

        for i, sig in enumerate(signals[:-1]):
            ret = returns[i]
            if sig == "BUY" and position <= 0:
                cost = abs(position) * close[offset + i] * (self.commission + self.slippage)
                current -= cost
                position = 1.0
            elif sig == "SELL" and position >= 0:
                cost = abs(position) * close[offset + i] * (self.commission + self.slippage)
                current -= cost
                position = -1.0

            current *= (1 + position * ret)
            equity.append(current)

        equity = np.array(equity)
        total_return = (equity[-1] - equity[0]) / equity[0]

        if self.metric == "total_return":
            return float(total_return)

        period_returns = np.diff(equity) / equity[:-1]
        if len(period_returns) < 2:
            return 0.0

        if self.metric == "sharpe_ratio":
            mean_r = np.mean(period_returns)
            std_r = np.std(period_returns)
            return float(mean_r / std_r * np.sqrt(252)) if std_r > 0 else 0.0

        if self.metric == "calmar_ratio":
            peak = np.maximum.accumulate(equity)
            drawdown = (peak - equity) / peak
            max_dd = np.max(drawdown)
            annual_return = total_return * (252 / max(len(equity), 1))
            return float(annual_return / max_dd) if max_dd > 0 else 0.0

        if self.metric == "win_rate":
            wins = np.sum(period_returns > 0)
            return float(wins / len(period_returns)) if len(period_returns) > 0 else 0.0

        if self.metric == "profit_factor":
            gross_profit = np.sum(period_returns[period_returns > 0])
            gross_loss = abs(np.sum(period_returns[period_returns < 0]))
            return float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

        if self.metric == "max_drawdown":
            peak = np.maximum.accumulate(equity)
            drawdown = (peak - equity) / peak
            return float(-np.max(drawdown))  # negative so "maximize" = minimize drawdown

        return float(total_return)

    def get_param_importance(self) -> Dict[str, float]:
        """Return parameter importance scores (requires completed study)."""
        if self._study is None:
            return {}
        try:
            import optuna
            return optuna.importance.get_param_importances(self._study)
        except Exception:
            return {}

    def plot_optimization_history(self):
        """Return a plotly figure of the optimization history."""
        if self._study is None:
            return None
        try:
            import optuna.visualization as vis
            return vis.plot_optimization_history(self._study)
        except Exception:
            return None

    def plot_param_importances(self):
        """Return a plotly figure of parameter importances."""
        if self._study is None:
            return None
        try:
            import optuna.visualization as vis
            return vis.plot_param_importances(self._study)
        except Exception:
            return None


# ── REST API router ──────────────────────────────────────────────────────────

def create_hyperopt_router():
    """FastAPI router for hyperopt endpoints."""
    from fastapi import APIRouter, BackgroundTasks, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/hyperopt", tags=["Hyperopt"])
    _jobs: Dict[str, Any] = {}

    class HyperoptRequest(BaseModel):
        strategy: str
        symbol: str = "XAUUSD"
        timeframe: str = "1h"
        n_trials: int = 50
        metric: str = "sharpe_ratio"
        direction: str = "maximize"
        param_space: Dict[str, Any] = {}

    class HyperoptStatus(BaseModel):
        job_id: str
        status: str
        result: Optional[Dict] = None

    @router.post("/run", response_model=HyperoptStatus, summary="Start a hyperopt job")
    async def run_hyperopt(req: HyperoptRequest, background_tasks: BackgroundTasks):
        import uuid
        job_id = str(uuid.uuid4())[:8]
        _jobs[job_id] = {"status": "running", "result": None}

        def _run():
            try:
                import yfinance as yf
                _TICKER_MAP = {"XAUUSD": "GC=F", "BTCUSD": "BTC-USD",
                               "EURUSD": "EURUSD=X"}
                ticker = _TICKER_MAP.get(req.symbol, req.symbol)
                df = yf.download(ticker, period="1y", interval=req.timeframe,
                                 progress=False, auto_adjust=True)
                df.columns = [c.lower() for c in df.columns]

                # Resolve strategy class
                _STRATEGY_MAP = {
                    "RSIStrategy": ("strategies.rsi_strategy", "RSIStrategy"),
                    "MACDStrategy": ("strategies.macd_strategy", "MACDStrategy"),
                    "BollingerBands": ("strategies.bollinger_bands", "BollingerBandsStrategy"),
                    "MovingAverageCrossover": ("strategies.ma_crossover", "MovingAverageCrossover"),
                }
                if req.strategy not in _STRATEGY_MAP:
                    _jobs[job_id] = {"status": "error",
                                     "result": {"error": f"Unknown strategy: {req.strategy}"}}
                    return

                mod_path, cls_name = _STRATEGY_MAP[req.strategy]
                import importlib
                mod = importlib.import_module(mod_path)
                strategy_class = getattr(mod, cls_name)

                # Build param space from request
                space = {}
                for name, spec in req.param_space.items():
                    kind = spec.get("kind", "int")
                    if kind == "int":
                        space[name] = ParamSpace.int(spec["low"], spec["high"],
                                                      spec.get("step", 1))
                    elif kind == "float":
                        space[name] = ParamSpace.float(spec["low"], spec["high"],
                                                        spec.get("step"))
                    elif kind == "categorical":
                        space[name] = ParamSpace.categorical(spec["choices"])

                engine = HyperoptEngine(
                    strategy_class=strategy_class,
                    market_data=df,
                    param_space=space,
                    n_trials=req.n_trials,
                    metric=req.metric,
                    direction=req.direction,
                )
                result = engine.run()
                _jobs[job_id] = {
                    "status": "completed",
                    "result": {
                        "best_params": result.best_params,
                        "best_value": result.best_value,
                        "metric": result.metric,
                        "n_trials": result.n_trials,
                        "duration_seconds": result.duration_seconds,
                    },
                }
            except Exception as exc:
                _jobs[job_id] = {"status": "error", "result": {"error": str(exc)}}

        background_tasks.add_task(_run)
        return HyperoptStatus(job_id=job_id, status="running")

    @router.get("/status/{job_id}", response_model=HyperoptStatus)
    async def get_status(job_id: str):
        if job_id not in _jobs:
            raise HTTPException(404, f"Job {job_id} not found")
        job = _jobs[job_id]
        return HyperoptStatus(job_id=job_id, status=job["status"], result=job["result"])

    @router.get("/strategies")
    async def list_strategies():
        return {"strategies": ["RSIStrategy", "MACDStrategy",
                               "BollingerBands", "MovingAverageCrossover"]}

    @router.get("/metrics")
    async def list_metrics():
        return {"metrics": ["sharpe_ratio", "total_return", "calmar_ratio",
                            "win_rate", "profit_factor", "max_drawdown"]}

    return router
