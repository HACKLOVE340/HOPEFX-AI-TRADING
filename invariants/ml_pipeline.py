# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.ml_pipeline — feature store, training & model-registry invariants.

Pure predicates from the framework's feature-store / training-pipeline / model-
registry sections: online↔offline feature parity, feature schema match, dataset
completeness, training reproducibility, checkpoint/lineage presence, registry
approval & signing, and GPU/cost governance. Each returns list[Violation].
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


def verify_feature_schema(features: Mapping[str, Any], expected_schema: set[str]) -> list[Violation]:
    """Served features must match the training schema (no missing/extra columns)."""
    present = set(features)
    missing = expected_schema - present
    extra = present - expected_schema
    out: list[Violation] = []
    if missing:
        out.append(_v("No Unverified AI Decision", CRITICAL, f"feature schema missing columns: {sorted(missing)[:8]}"))
    if extra:
        out.append(_v("No Unverified AI Decision", WARNING, f"unexpected feature columns: {sorted(extra)[:8]}"))
    return out


def verify_online_offline_parity(online_val: float, offline_val: float, tol: float = 1e-6) -> list[Violation]:
    """A feature computed online must match its offline (training) value."""
    if not (_is_finite_number(online_val) and _is_finite_number(offline_val)):
        return [_v("No Unverified AI Decision", CRITICAL, "feature parity values non-finite")]
    if abs(online_val - offline_val) > tol:
        return [
            _v(
                "No Unverified AI Decision",
                CRITICAL,
                f"online/offline feature skew {abs(online_val - offline_val)} > {tol}",
            )
        ]
    return []


def verify_dataset_complete(rows: int, expected_min: int, null_rate: float, max_null: float = 0.05) -> list[Violation]:
    out: list[Violation] = []
    if rows < expected_min:
        out.append(_v("No Unverified AI Decision", CRITICAL, f"training dataset undersized: {rows} < {expected_min}"))
    if _is_finite_number(null_rate) and null_rate > max_null:
        out.append(_v("No Unverified AI Decision", WARNING, f"dataset null rate {null_rate} > {max_null}"))
    return out


def verify_training_reproducible(seed_recorded: bool, metrics_recorded: bool) -> list[Violation]:
    """A training run must record its seed + metrics to be reproducible."""
    missing = [n for n, ok in (("seed", seed_recorded), ("metrics", metrics_recorded)) if not ok]
    if missing:
        return [_v("No Audit Gap", CRITICAL, f"training run not reproducible; missing: {missing}")]
    return []


def verify_model_lineage(
    meta: Mapping[str, Any], required: tuple[str, ...] = ("owner", "training_record", "validation_record", "approved")
) -> list[Violation]:
    """Every registered model must carry full governance metadata."""
    missing = [f for f in required if not meta.get(f)]
    if missing:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, f"model registry metadata incomplete: {missing}")]
    return []


def verify_model_signed(signature: Any) -> list[Violation]:
    if not signature:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, "model artifact is not signed")]
    return []


def verify_inference_cost(cost: float, budget: float) -> list[Violation]:
    if _is_finite_number(cost) and _is_finite_number(budget) and cost > budget:
        return [_v("No Hidden Loss", WARNING, f"inference cost {cost} exceeds budget {budget}")]
    return []


def verify_gpu_allocation(allocated: float, available: float) -> list[Violation]:
    if _is_finite_number(allocated) and _is_finite_number(available) and allocated > available:
        return [_v("No Unbounded Failure", CRITICAL, f"GPU over-allocation: {allocated} > available {available}")]
    return []
