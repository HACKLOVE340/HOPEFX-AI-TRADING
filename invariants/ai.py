# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.ai — model, inference, agent & hallucination invariants.

Pure predicates from the framework's AI/model/agent sections: model integrity
(approved hash), drift, confidence, calibration, prediction saturation/entropy,
ensemble dominance, consensus, feature/embedding integrity, hallucination
pre-trade guards, agent authority & tool allow-lists, reasoning-loop bounds,
self-modification guard, and memory ownership. Each returns list[Violation].
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


# ── model integrity & governance ────────────────────────────────────────────────
def verify_model_approved(model_hash: str, approved_hash: str, approved: bool = True) -> list[Violation]:
    """Only an approved, integrity-checked model may run (No Unverified AI Decision)."""
    out: list[Violation] = []
    if not approved:
        out.append(_v("No Unapproved AI Action", CONSTITUTIONAL, "model is not approved for production"))
    if approved_hash and model_hash != approved_hash:
        out.append(_v("No Unverified AI Decision", CONSTITUTIONAL,
                      "model hash does not match approved hash (tamper/corruption)"))
    return out


def verify_drift(drift_score: float, limit: float) -> list[Violation]:
    if not _is_finite_number(drift_score):
        return [_v("No Unverified AI Decision", CRITICAL, "drift score is non-finite")]
    if drift_score > limit:
        return [_v("No Unverified AI Decision", CRITICAL, f"data/model drift {drift_score} exceeds {limit}")]
    return []


def verify_confidence(confidence: float, min_confidence: float) -> list[Violation]:
    """Never execute from weak confidence."""
    if not _is_finite_number(confidence):
        return [_v("No Unverified AI Decision", CONSTITUTIONAL, "prediction confidence is non-finite")]
    if not 0.0 <= confidence <= 1.0:
        return [_v("No Unverified AI Decision", CRITICAL, f"confidence {confidence} outside [0,1]")]
    if confidence < min_confidence:
        return [_v("No Unverified AI Decision", CRITICAL, f"confidence {confidence} < min {min_confidence}")]
    return []


def verify_prediction_entropy(entropy: float, minimum: float) -> list[Violation]:
    """A model that always predicts the same thing has collapsed."""
    if _is_finite_number(entropy) and entropy < minimum:
        return [_v("No Unverified AI Decision", WARNING, f"prediction entropy {entropy} < {minimum} (saturated model)")]
    return []


def verify_ensemble_diversity(weights: Sequence[float], max_single: float = 0.5) -> list[Violation]:
    """No single model may dominate an ensemble (model-collapse guard)."""
    out: list[Violation] = []
    fw = [w for w in weights if _is_finite_number(w)]
    if not fw:
        return out
    if max(fw) > max_single:
        out.append(_v("No Unverified AI Decision", WARNING,
                      f"single model weight {max(fw):.2f} exceeds {max_single:.0%} — ensemble dominance"))
    return out


def verify_consensus(consensus_score: float, minimum: float) -> list[Violation]:
    """Multi-model votes must reach minimum consensus before acting."""
    if _is_finite_number(consensus_score) and consensus_score < minimum:
        return [_v("No Unverified AI Decision", CRITICAL, f"consensus {consensus_score} < min {minimum}")]
    return []


# ── feature / embedding integrity ────────────────────────────────────────────────
def verify_features_finite(features: dict[str, Any]) -> list[Violation]:
    """No feature may be NaN/Inf/None — the most common silent AI failure."""
    bad = [k for k, v in features.items()
           if v is None or (isinstance(v, float) and not _is_finite_number(v))]
    if bad:
        return [_v("No Silent Failure", CRITICAL, f"non-finite/null features: {bad[:8]}", count=len(bad))]
    return []


def verify_embedding(dimension: int, expected_dim: int, norm: float) -> list[Violation]:
    out: list[Violation] = []
    if dimension != expected_dim:
        out.append(_v("No Data Corruption", CRITICAL, f"embedding dim {dimension} != expected {expected_dim}"))
    if not _is_finite_number(norm) or norm <= 0:
        out.append(_v("No Data Corruption", CRITICAL, f"embedding norm invalid ({norm})"))
    return out


# ── hallucination pre-trade guard ───────────────────────────────────────────────
def verify_hallucination_guard(references_real_data: bool, market_data_age_s: float,
                               max_age_s: float, confidence: float, min_confidence: float) -> list[Violation]:
    """Before an AI-driven trade: it must reference real, fresh market data with
    sufficient confidence. Blocks trades on hallucinated/stale context."""
    out: list[Violation] = []
    if not references_real_data:
        out.append(_v("No Unverified AI Decision", CONSTITUTIONAL, "AI decision does not reference real market data"))
    if _is_finite_number(market_data_age_s) and market_data_age_s > max_age_s:
        out.append(_v("No Unverified AI Decision", CRITICAL, f"market data age {market_data_age_s}s > {max_age_s}s"))
    out += verify_confidence(confidence, min_confidence)
    return out


def verify_explainable(explanation: Any) -> list[Violation]:
    """Every trade/recommendation must carry an explanation (No Hidden Decision)."""
    if explanation is None or (isinstance(explanation, str) and not explanation.strip()):
        return [_v("No Hidden Decision", CRITICAL, "decision has no explanation/audit trail")]
    return []


# ── agent authority & containment ───────────────────────────────────────────────
def verify_agent_action_authorized(action: str, allowed_actions: set[str]) -> list[Violation]:
    if action not in allowed_actions:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, f"agent action '{action}' not in approved set")]
    return []


def verify_tool_allowed(tool: str, allowed_tools: set[str]) -> list[Violation]:
    if tool not in allowed_tools:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, f"agent invoked unauthorized tool '{tool}'")]
    return []


def verify_reasoning_depth(depth: int, limit: int) -> list[Violation]:
    """Prevent infinite/recursive agent reasoning loops."""
    if depth > limit:
        return [_v("No Unbounded Failure", CRITICAL, f"reasoning depth {depth} exceeds limit {limit}")]
    return []


def verify_agent_authority(action_risk: float, authority_level: float) -> list[Violation]:
    """An agent cannot take an action whose risk exceeds its authority."""
    if _is_finite_number(action_risk) and _is_finite_number(authority_level) and action_risk > authority_level:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL,
                   f"action risk {action_risk} exceeds agent authority {authority_level}")]
    return []


def verify_agent_no_self_escalation(modified_own_permissions: bool) -> list[Violation]:
    if modified_own_permissions:
        return [_v("No Loss Of Human Control", CONSTITUTIONAL, "agent modified its own permissions")]
    return []


def verify_memory_ownership(memory_owner: Any, pod_id: Any) -> list[Violation]:
    """Agent/pod memory must belong to its pod — no cross-pod/client leakage."""
    if memory_owner != pod_id:
        return [_v("No Cross-Tenant Leakage", CONSTITUTIONAL,
                   f"memory owner {memory_owner!r} != pod {pod_id!r} (memory contamination)")]
    return []
