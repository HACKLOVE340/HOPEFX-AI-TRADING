# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.ai_governance — decision integrity, reality & autonomy controls.

Pure predicates from the framework's deepest AI sections: decision determinism &
reproducibility, decision-lineage completeness, prompt version/hash integrity,
context-window completeness, reward-hacking / shadow-objective detection, alpha
decay, belief/objective drift, reality verification (beliefs == reality),
forecast calibration, AI goal alignment, strategy identity/mutation, and the
autonomy controls (self-replication, autonomous capital/strategy limits).
"""

from __future__ import annotations

from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


# ── decision integrity ──────────────────────────────────────────────────────────
def verify_determinism(output_a: Any, output_b: Any) -> list[Violation]:
    """Same inputs must yield the same decision."""
    if output_a != output_b:
        return [
            _v(
                "No Unexplained System Behavior",
                CRITICAL,
                f"non-deterministic decision: {output_a!r} != {output_b!r} for same input",
            )
        ]
    return []


def verify_reproducible(replayed: Any, original: Any) -> list[Violation]:
    """A past decision must be reconstructable exactly (audit / forensics)."""
    if replayed != original:
        return [_v("No Audit Gap", CRITICAL, "decision replay does not match original")]
    return []


def verify_decision_lineage(
    lineage: dict[str, Any],
    required: tuple[str, ...] = ("data", "feature", "model", "signal", "decision", "risk_approval", "execution"),
) -> list[Violation]:
    """Every trade must trace back through the full chain (No Hidden Decision)."""
    missing = [s for s in required if not lineage.get(s)]
    if missing:
        return [_v("No Hidden Decision", CRITICAL, f"incomplete decision lineage; missing: {missing}")]
    return []


def verify_prompt_version(prompt_hash: str, approved_hash: str) -> list[Violation]:
    if approved_hash and prompt_hash != approved_hash:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, "prompt hash != approved version (tamper/drift)")]
    return []


def verify_context_complete(required_context_present: bool) -> list[Violation]:
    """An agent must never act on a truncated/missing context window."""
    if not required_context_present:
        return [_v("No Unverified AI Decision", CRITICAL, "agent operating with truncated/missing context")]
    return []


# ── objective integrity (reward hacking / drift) ────────────────────────────────
def verify_goal_alignment(agent_goal: Any, approved_goal: Any) -> list[Violation]:
    if agent_goal != approved_goal:
        return [
            _v("No Unapproved AI Action", CONSTITUTIONAL, f"AI goal {agent_goal!r} != approved goal {approved_goal!r}")
        ]
    return []


def verify_optimization_target(actual_metric: Any, approved_metric: Any) -> list[Violation]:
    """The model must optimise the approved metric, not a proxy (reward hacking)."""
    if actual_metric != approved_metric:
        return [
            _v(
                "No Unapproved AI Action",
                CRITICAL,
                f"reward hacking: optimizing {actual_metric!r} not approved {approved_metric!r}",
            )
        ]
    return []


def verify_no_shadow_objective(declared_objectives: set[str], active_objectives: set[str]) -> list[Violation]:
    undeclared = active_objectives - declared_objectives
    if undeclared:
        return [_v("No Hidden AI Action", CONSTITUTIONAL, f"undeclared (shadow) objectives: {sorted(undeclared)}")]
    return []


def verify_alpha_decay(current_alpha: float, minimum_alpha: float) -> list[Violation]:
    if _is_finite_number(current_alpha) and current_alpha < minimum_alpha:
        return [_v("No Hidden Risk", WARNING, f"alpha decayed: {current_alpha} < min {minimum_alpha}")]
    return []


# ── reality verification ────────────────────────────────────────────────────────
def verify_belief_matches_reality(belief_error: float, threshold: float) -> list[Violation]:
    """The AI's world-model must not drift far from reality — the supreme failure
    is an all-green system whose understanding of the world is wrong."""
    if not _is_finite_number(belief_error):
        return [_v("No Unexplained System Behavior", CRITICAL, "belief error is non-finite")]
    if belief_error > threshold:
        return [
            _v(
                "No Unexplained System Behavior",
                CRITICAL,
                f"belief drift: model-vs-reality error {belief_error} > {threshold}",
            )
        ]
    return []


def verify_calibration(stated_confidence: float, observed_accuracy: float, tol: float = 0.2) -> list[Violation]:
    """Stated confidence should roughly match observed accuracy (AI honesty)."""
    if not (_is_finite_number(stated_confidence) and _is_finite_number(observed_accuracy)):
        return [_v("No Unverified AI Decision", WARNING, "calibration inputs non-finite")]
    if abs(stated_confidence - observed_accuracy) > tol:
        return [
            _v(
                "No Unverified AI Decision",
                WARNING,
                f"miscalibrated: confidence {stated_confidence} vs accuracy {observed_accuracy}",
            )
        ]
    return []


# ── strategy identity / mutation ────────────────────────────────────────────────
def verify_strategy_approved(version: str, approved_versions: set[str], rollback_exists: bool) -> list[Violation]:
    out: list[Violation] = []
    if version not in approved_versions:
        out.append(_v("No Unapproved AI Action", CONSTITUTIONAL, f"strategy version {version} not approved"))
    if not rollback_exists:
        out.append(_v("No Unrecoverable Failure", CRITICAL, f"strategy {version} has no rollback"))
    return out


def verify_strategy_identity(behavior_distance: float, max_distance: float) -> list[Violation]:
    """A strategy must remain itself — silent mutation/drift is dangerous."""
    if _is_finite_number(behavior_distance) and behavior_distance > max_distance:
        return [
            _v(
                "No Unexplained System Behavior",
                CRITICAL,
                f"strategy silently mutated: behavior distance {behavior_distance} > {max_distance}",
            )
        ]
    return []


# ── autonomy controls ───────────────────────────────────────────────────────────
def verify_no_self_replication(spawned_agents: int, approved: bool) -> list[Violation]:
    """Agents cannot replicate/spawn uncontrolled agent chains without approval."""
    if spawned_agents > 0 and not approved:
        return [
            _v(
                "No Loss Of Human Control",
                CONSTITUTIONAL,
                f"agent spawned {spawned_agents} sub-agents without approval",
            )
        ]
    return []


def verify_autonomous_capital_limit(agent_allocated: float, agent_limit: float) -> list[Violation]:
    """An agent cannot allocate capital beyond its hard limit."""
    if _is_finite_number(agent_allocated) and _is_finite_number(agent_limit) and agent_allocated > agent_limit:
        return [
            _v(
                "No Unauthorized Capital Movement",
                CONSTITUTIONAL,
                f"agent allocated {agent_allocated} > limit {agent_limit}",
            )
        ]
    return []


def verify_autonomous_strategy_control(strategy_auto_deployed: bool, human_approved: bool) -> list[Violation]:
    """Agents cannot deploy new strategies to production without human approval."""
    if strategy_auto_deployed and not human_approved:
        return [_v("No Loss Of Human Control", CONSTITUTIONAL, "strategy auto-deployed without human approval")]
    return []
