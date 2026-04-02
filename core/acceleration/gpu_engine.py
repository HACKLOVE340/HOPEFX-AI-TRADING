# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# core/risk/advanced_engine.py
"""
HOPEFX Advanced Risk Engine
Monte Carlo simulation with GARCH volatility and copula correlation
"""

from dataclasses import dataclass
from decimal import Decimal
import logging

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    var_95: float
    var_99: float
    cvar_95: float  # Expected shortfall
    cvar_99: float
    volatility: float
    max_drawdown: float
    tail_risk: float
    correlation_stress: float


class GARCHModel:
    """GARCH(1,1) with Student-t innovations"""

    def __init__(self):
        self.omega = 0.000001
        self.alpha = 0.1
        self.beta = 0.85
        self.nu = 5  # Degrees of freedom

    def fit(self, returns: np.ndarray):
        """Fit GARCH parameters via MLE"""

        def _garch_params_invalid(omega, alpha, beta, nu) -> bool:
            """Return True when GARCH(1,1)-t parameters are outside the stationarity region."""
            non_positive_omega = omega <= 0
            negative_alpha = alpha < 0
            negative_beta = beta < 0
            non_stationary = alpha + beta >= 1
            invalid_df = nu <= 2  # Student-t requires df > 2 for finite variance
            return non_positive_omega or negative_alpha or negative_beta or non_stationary or invalid_df

        def neg_log_likelihood(params):
            omega, alpha, beta, nu = params
            if _garch_params_invalid(omega, alpha, beta, nu):
                return 1e10

            variance = np.zeros(len(returns))
            variance[0] = np.var(returns)

            for t in range(1, len(returns)):
                variance[t] = omega + alpha * returns[t - 1] ** 2 + beta * variance[t - 1]

            # Student-t log-likelihood
            log_likelihood = -np.sum(
                np.log(stats.t.pdf(returns / np.sqrt(variance), nu) / np.sqrt(variance)),
            )
            return log_likelihood

        result = minimize(
            neg_log_likelihood,
            [self.omega, self.alpha, self.beta, self.nu],
            method="L-BFGS-B",
            bounds=[(1e-8, 1), (0, 1), (0, 1), (2.1, 30)],
        )

        self.omega, self.alpha, self.beta, self.nu = result.x
        return self

    def forecast(self, horizon: int = 1) -> np.ndarray:
        """Forecast conditional volatility"""
        # Simplified: assumes last variance known
        last_var = self.omega / (1 - self.alpha - self.beta)
        forecasts = np.zeros(horizon)

        for h in range(horizon):
            if h == 0:
                forecasts[h] = last_var
            else:
                forecasts[h] = self.omega + (self.alpha + self.beta) * forecasts[h - 1]

        return np.sqrt(forecasts)

    def simulate(self, n_sims: int = 10000, horizon: int = 5) -> np.ndarray:
        """Simulate future paths"""
        simulated = np.zeros((n_sims, horizon))
        variance = np.ones(n_sims) * self.omega / (1 - self.alpha - self.beta)

        for t in range(horizon):
            variance = self.omega + self.alpha * simulated[:, t - 1] ** 2 + self.beta * variance
            simulated[:, t] = np.sqrt(variance) * stats.t.rvs(self.nu, size=n_sims)

        return simulated


class CopulaRiskModel:
    """Vine copula for modeling tail dependencies"""

    def __init__(self):
        self.marginals = {}
        self.correlation = np.eye(2)

    def fit(self, returns: pd.DataFrame):
        """Fit copula to multivariate returns"""
        # Fit marginal distributions (Johnson SU)
        for col in returns.columns:
            params = stats.johnsonsu.fit(returns[col].dropna())
            self.marginals[col] = params

        # Transform to uniform
        uniform = pd.DataFrame()
        for col in returns.columns:
            uniform[col] = stats.johnsonsu.cdf(returns[col], *self.marginals[col])

        # Fit Gaussian copula (simplified)
        self.correlation = uniform.corr().values

        return self

    def simulate(self, n_sims: int = 10000) -> pd.DataFrame:
        """Simulate correlated returns"""
        # Generate correlated uniforms
        normal = np.random.multivariate_normal(
            np.zeros(len(self.marginals)),
            self.correlation,
            n_sims,
        )
        uniform = stats.norm.cdf(normal)

        # Transform back
        simulated = pd.DataFrame()
        for i, col in enumerate(self.marginals.keys()):
            simulated[col] = stats.johnsonsu.ppf(uniform[:, i], *self.marginals[col])

        return simulated


class MonteCarloRiskEngine:
    """Full portfolio risk simulation"""

    def __init__(self, n_sims: int = 100000):
        self.n_sims = n_sims
        self.garch_models = {}
        self.copula = CopulaRiskModel()
        self.historical_returns = pd.DataFrame()

    def add_asset(self, symbol: str, returns: np.ndarray):
        """Add asset to risk model"""
        self.historical_returns[symbol] = returns

        # Fit GARCH
        garch = GARCHModel()
        garch.fit(returns)
        self.garch_models[symbol] = garch

    def calculate_portfolio_risk(self, weights: dict[str, float]) -> RiskMetrics:
        """Calculate full risk metrics via Monte Carlo"""
        # Simulate using copula for dependencies
        copula_sims = self.copula.simulate(self.n_sims)

        # Apply GARCH volatility scaling
        scaled_returns = pd.DataFrame()
        for col in copula_sims.columns:
            if col in self.garch_models:
                vol = self.garch_models[col].forecast(len(copula_sims))
                scaled_returns[col] = copula_sims[col] * vol[: len(copula_sims)]

        # Calculate portfolio returns
        portfolio_returns = sum(scaled_returns[col] * weights.get(col, 0) for col in scaled_returns.columns)

        # Risk metrics
        var_95 = np.percentile(portfolio_returns, 5)
        var_99 = np.percentile(portfolio_returns, 1)
        cvar_95 = portfolio_returns[portfolio_returns <= var_95].mean()
        cvar_99 = portfolio_returns[portfolio_returns <= var_99].mean()

        # Max drawdown
        cumulative = (1 + portfolio_returns).cumprod()
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max

        return RiskMetrics(
            var_95=float(var_95),
            var_99=float(var_99),
            cvar_95=float(cvar_95),
            cvar_99=float(cvar_99),
            volatility=float(portfolio_returns.std()),
            max_drawdown=float(drawdown.min()),
            tail_risk=float(abs(var_99 / var_95)) if var_95 != 0 else 0,
            correlation_stress=float(self._stress_correlation(weights)),
        )

    def _stress_correlation(self, weights: dict[str, float]) -> float:
        """Calculate correlation under stress (tail dependence)"""
        # Simplified: use historical correlation in worst 5% of days
        if len(self.historical_returns) < 100:
            return 0.5

        worst_days = self.historical_returns.sum(axis=1).quantile(0.05)
        stress_data = self.historical_returns[self.historical_returns.sum(axis=1) <= worst_days]

        if len(stress_data) < 10:
            return 0.5

        return float(stress_data.corr().values.mean())


class RealTimeRiskMonitor:
    """Continuous risk monitoring with automatic position adjustment"""

    def __init__(self, risk_engine: MonteCarloRiskEngine):
        self.risk_engine = risk_engine
        self.limits = {
            "var_95_daily": -0.02,  # 2% daily VaR limit
            "cvar_95_daily": -0.03,  # 3% expected shortfall
            "max_drawdown": -0.10,  # 10% max drawdown
            "tail_risk": 3.0,  # Tail risk ratio limit
        }
        self.current_risk: RiskMetrics | None = None
        self.kill_switch_triggered = False

    def update_portfolio(
        self,
        positions: dict[str, Decimal],
        prices: dict[str, Decimal],
    ):
        """Recalculate risk with current positions"""
        total_value = sum(positions[s] * prices[s] for s in positions)

        weights = {s: float(positions[s] * prices[s] / total_value) if total_value > 0 else 0 for s in positions}

        self.current_risk = self.risk_engine.calculate_portfolio_risk(weights)
        return self._check_limits()

    def _check_limits(self) -> list[str]:
        """Check if any risk limits breached"""
        if not self.current_risk:
            return []

        violations = []

        if self.current_risk.var_95 < self.limits["var_95_daily"]:
            violations.append(f"VaR 95%: {self.current_risk.var_95:.2%}")

        if self.current_risk.cvar_95 < self.limits["cvar_95_daily"]:
            violations.append(f"CVaR 95%: {self.current_risk.cvar_95:.2%}")

        if self.current_risk.max_drawdown < self.limits["max_drawdown"]:
            violations.append(f"Max DD: {self.current_risk.max_drawdown:.2%}")

        if violations:
            self._trigger_kill_switch(violations)

        return violations

    def _trigger_kill_switch(self, violations: list[str]):
        """Emergency position reduction"""
        logger.critical("RISK LIMIT BREACH: %s", ", ".join(violations))
        self.kill_switch_triggered = True
        # Signal to close all positions


# ---------------------------------------------------------------------------
# GPU acceleration stubs — used by main_ultimate_integrated.py
# Falls back to CPU when CUDA / torch is unavailable.
# ---------------------------------------------------------------------------

import logging as _logging
from pathlib import Path as _Path


_gpu_logger = _logging.getLogger(__name__)

try:
    import torch as _torch

    _HAS_CUDA = _torch.cuda.is_available()
except ImportError:
    _torch = None  # type: ignore[assignment]
    _HAS_CUDA = False


@dataclass
class GPUConfig:
    device: str = "cuda" if _HAS_CUDA else "cpu"
    batch_size: int = 64
    max_latency_ms: float = 5.0
    fallback_to_cpu: bool = True


class GPUInferenceEngine:
    """
    GPU-accelerated inference engine.

    Supports three model backends (selected automatically by what is available):
      1. ONNX Runtime  — fastest CPU/GPU inference; loads ``model_path`` as an
         ONNX file when ``onnxruntime`` is installed.
      2. PyTorch       — loads ``model_path`` as a TorchScript (.pt) file when
         ``torch`` is installed and ONNX Runtime is absent.
      3. No model      — raises ``RuntimeError`` on ``predict()`` so callers
         fail loudly rather than silently returning garbage.

    Usage
    -----
        engine = GPUInferenceEngine(model_path="ml/saved_models/hopefx.onnx")
        predictions = engine.predict(feature_array)   # shape (N, features)

    The ``model_path`` argument is optional; if omitted the engine looks for
    ``ml/saved_models/hopefx.onnx`` then ``ml/saved_models/hopefx.pt`` relative
    to the project root.  A ``RuntimeError`` is raised at predict-time (not
    init-time) when no model file is found, so the engine can be constructed
    during startup before the model is trained.
    """

    # Default search paths relative to the project root (parent of core/).
    _DEFAULT_ONNX = _Path(__file__).parent.parent.parent / "ml" / "saved_models" / "hopefx.onnx"
    _DEFAULT_PT = _Path(__file__).parent.parent.parent / "ml" / "saved_models" / "hopefx.pt"

    def __init__(
        self,
        config: GPUConfig | None = None,
        model_path: str | None = None,
    ) -> None:
        self.config = config or GPUConfig()
        self.device = self.config.device
        if self.device == "cuda" and not _HAS_CUDA:
            _gpu_logger.warning(
                "CUDA requested but not available — falling back to CPU",
            )
            self.device = "cpu"

        self._ort_session = None  # onnxruntime.InferenceSession
        self._torch_model = None  # torch.jit.ScriptModule
        self._input_name: str = "input"

        # Resolve model path
        if model_path is not None:
            resolved = _Path(model_path)
        elif self._DEFAULT_ONNX.exists():
            resolved = self._DEFAULT_ONNX
        elif self._DEFAULT_PT.exists():
            resolved = self._DEFAULT_PT
        else:
            resolved = None

        if resolved is not None:
            self._load_model(resolved)

        _gpu_logger.info(
            "GPUInferenceEngine initialised on device=%s model=%s",
            self.device,
            resolved or "none (will raise on predict)",
        )

    # ── model loading ─────────────────────────────────────────────────────────

    def _load_model(self, path: _Path) -> None:
        """Load an ONNX or TorchScript model from *path*."""
        suffix = path.suffix.lower()
        if suffix == ".onnx":
            self._load_onnx(path)
        elif suffix in (".pt", ".pth"):
            self._load_torchscript(path)
        else:
            raise ValueError(
                f"Unsupported model format '{suffix}'. Provide an ONNX (.onnx) or TorchScript (.pt/.pth) file."
            )

    def _load_onnx(self, path: _Path) -> None:
        """Load an ONNX model via onnxruntime."""
        try:
            import onnxruntime as _ort  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required to load ONNX models. "
                "Install it with: pip install onnxruntime-gpu  (or onnxruntime for CPU-only)"
            ) from exc

        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"] if self.device == "cuda" else ["CPUExecutionProvider"]
        )
        self._ort_session = _ort.InferenceSession(str(path), providers=providers)
        self._input_name = self._ort_session.get_inputs()[0].name
        _gpu_logger.info("ONNX model loaded from %s (providers=%s)", path, providers)

    def _load_torchscript(self, path: _Path) -> None:
        """Load a TorchScript model via torch.jit.load."""
        if _torch is None:
            raise ImportError("torch is required to load TorchScript models. Install it with: pip install torch")
        map_location = _torch.device(self.device)
        self._torch_model = _torch.jit.load(str(path), map_location=map_location)
        self._torch_model.eval()
        _gpu_logger.info("TorchScript model loaded from %s (device=%s)", path, self.device)

    def load_model(self, model_path: str) -> None:
        """Load or replace the inference model at runtime."""
        self._ort_session = None
        self._torch_model = None
        self._load_model(_Path(model_path))

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(self, features: np.ndarray) -> np.ndarray:
        """
        Run inference on *features* and return predictions as a numpy array.

        Parameters
        ----------
        features : np.ndarray
            2-D array of shape ``(N, num_features)`` or 1-D array of shape
            ``(num_features,)`` which is automatically expanded to ``(1, num_features)``.

        Returns
        -------
        np.ndarray
            Model output array.  Shape depends on the loaded model's output layer.

        Raises
        ------
        RuntimeError
            When no model has been loaded (neither ONNX nor TorchScript file
            was found at init time and ``load_model()`` has not been called).
        """
        if features.ndim == 1:
            features = features[np.newaxis, :]

        # ── ONNX Runtime path ─────────────────────────────────────────────────
        if self._ort_session is not None:
            inputs = {self._input_name: features.astype(np.float32)}
            outputs = self._ort_session.run(None, inputs)
            return outputs[0]

        # ── PyTorch path ──────────────────────────────────────────────────────
        if self._torch_model is not None and _torch is not None:
            t = _torch.tensor(features, dtype=_torch.float32, device=self.device)
            with _torch.no_grad():
                out = self._torch_model(t)
            return out.cpu().numpy()

        # ── No model loaded ───────────────────────────────────────────────────
        raise RuntimeError(
            "GPUInferenceEngine has no model loaded. "
            "Call load_model(path) with an ONNX or TorchScript file before calling predict(). "
            f"Default search paths checked: {self._DEFAULT_ONNX}, {self._DEFAULT_PT}"
        )

    def batch_predict(self, feature_batches: list[np.ndarray]) -> list[np.ndarray]:
        """Run predict() on each batch and return a list of output arrays."""
        return [self.predict(b) for b in feature_batches]


class GPUFeatureEngine:
    """
    GPU-accelerated feature engineering.
    Falls back to numpy when CUDA is unavailable.
    """

    def __init__(self):
        self.device = "cuda" if _HAS_CUDA else "cpu"
        _gpu_logger.info("GPUFeatureEngine initialised on device=%s", self.device)

    def compute_features(self, prices: np.ndarray) -> np.ndarray:
        """Compute technical features from a price array."""
        if len(prices) < 2:
            return prices
        returns = np.diff(prices) / prices[:-1]
        # Simple feature set: returns, rolling mean, rolling std
        window = min(20, len(returns))
        rolling_mean = np.convolve(returns, np.ones(window) / window, mode="valid")
        rolling_std = np.array(
            [returns[i : i + window].std() for i in range(len(returns) - window + 1)],
        )
        min_len = min(len(returns), len(rolling_mean), len(rolling_std))
        return np.column_stack(
            [
                returns[-min_len:],
                rolling_mean[-min_len:],
                rolling_std[-min_len:],
            ],
        )
