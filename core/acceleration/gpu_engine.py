# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/acceleration/gpu_engine.py
================================
GPU inference engine — ONNX Runtime / TorchScript model serving with
optional CUDA acceleration.

The GARCH/Monte Carlo risk classes previously in this file have been moved
to core/risk/advanced_engine.py (L-6 fix).  They are re-exported here for
backward compatibility so existing imports continue to work.
"""

# ── Backward-compat re-exports (risk classes now live in core/risk/) ──────────
from core.risk.advanced_engine import (  # noqa: F401
    CopulaRiskModel,
    GARCHModel,
    MonteCarloRiskEngine,
    RealTimeRiskMonitor,
    RiskMetrics,
)

# ---------------------------------------------------------------------------
# GPU acceleration — ONNX Runtime / TorchScript inference engine.
# Falls back to CPU when CUDA / torch is unavailable.
# ---------------------------------------------------------------------------

import logging as _logging
import numpy as np
from dataclasses import dataclass
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
        self._torch_model = _torch.jit.load(str(path), map_location=map_location)  # nosec B614 — TorchScript load, path validated by caller
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
        prices_clean = np.nan_to_num(np.asarray(prices, dtype=float), nan=0.0)
        denom = np.where(prices_clean[:-1] != 0, prices_clean[:-1], 1.0)
        returns = np.diff(prices_clean) / denom
        # Simple feature set: returns, rolling mean, rolling std
        window = min(20, len(returns))
        rolling_mean = np.convolve(returns, np.ones(window) / window, mode="valid")
        rolling_std = np.nan_to_num(
            np.array([returns[i : i + window].std() for i in range(len(returns) - window + 1)]),
            nan=0.0,
        )
        min_len = min(len(returns), len(rolling_mean), len(rolling_std))
        return np.column_stack(
            [
                returns[-min_len:],
                rolling_mean[-min_len:],
                rolling_std[-min_len:],
            ],
        )
