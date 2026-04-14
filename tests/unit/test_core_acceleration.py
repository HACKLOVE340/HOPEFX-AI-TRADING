# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_acceleration.py
======================================
Coverage tests for core/acceleration/__init__.py (gpu_engine.py).

torch/cupy are not installed in CI — tests exercise the module-level
constants and the graceful-degradation branches.
"""

from __future__ import annotations

import pytest

import core.acceleration as acc_pkg
from core.acceleration import GPUConfig, HAS_TORCH


def test_has_torch_is_bool():
    assert isinstance(HAS_TORCH, bool)


def test_gpu_config_defaults():
    cfg = GPUConfig()
    assert cfg.device == "cuda"
    assert cfg.batch_size == 64
    assert cfg.max_latency_ms == 5.0
    assert cfg.mixed_precision is True


def test_gpu_config_custom():
    cfg = GPUConfig(device="cpu", batch_size=32, max_latency_ms=10.0, mixed_precision=False)
    assert cfg.device == "cpu"
    assert cfg.batch_size == 32
    assert cfg.mixed_precision is False


def test_gpu_config_is_dataclass():
    from dataclasses import fields

    f_names = {f.name for f in fields(GPUConfig)}
    assert "device" in f_names
    assert "batch_size" in f_names
    assert "max_latency_ms" in f_names
    assert "mixed_precision" in f_names


def test_gpu_inference_engine_requires_torch():
    if HAS_TORCH:
        pytest.skip("torch is installed")
    from core.acceleration import GPUInferenceEngine

    with pytest.raises((ImportError, Exception)):
        GPUInferenceEngine()


def test_gpu_feature_engine_requires_cupy():
    from core.acceleration import GPUFeatureEngine

    with pytest.raises((ImportError, Exception)):
        GPUFeatureEngine()


def test_quantized_transformer_requires_torch():
    if HAS_TORCH:
        pytest.skip("torch is installed")
    from core.acceleration import QuantizedTransformer

    with pytest.raises((ImportError, Exception)):
        QuantizedTransformer()


def test_module_exports_expected_names():
    expected = {"GPUConfig", "GPUInferenceEngine", "GPUFeatureEngine", "QuantizedTransformer", "HAS_TORCH"}
    assert expected.issubset(set(dir(acc_pkg)))


def test_has_torch_false_in_ci():
    try:
        import torch  # noqa: F401

        pytest.skip("torch is installed")
    except ImportError:
        assert HAS_TORCH is False
