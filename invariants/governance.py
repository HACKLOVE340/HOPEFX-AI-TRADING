# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.governance — backtest integrity, isolation, audit, control & config.

Pure predicates from the framework's governance/compliance/meta sections:
backtest no-lookahead & no-leakage & after-cost viability, tenant/pod isolation,
audit immutability, segregation-of-duties & dual control, config drift,
deployment gates, and existential human-control supremacy. list[Violation].
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


# ── backtesting integrity (false-profit guards) ─────────────────────────────────
def verify_no_lookahead(signal_time: float, trade_time: float) -> list[Violation]:
    """A signal must occur strictly before the trade it triggers."""
    if _is_finite_number(signal_time) and _is_finite_number(trade_time) and signal_time >= trade_time:
        return [
            _v("No Hidden Risk", CONSTITUTIONAL, f"look-ahead bias: signal {signal_time} not before trade {trade_time}")
        ]
    return []


def verify_no_data_leakage(train_ids: Iterable[Any], test_ids: Iterable[Any]) -> list[Violation]:
    """Train and test sets must be disjoint."""
    overlap = set(train_ids) & set(test_ids)
    if overlap:
        return [
            _v(
                "No Hidden Risk",
                CONSTITUTIONAL,
                f"train/test leakage: {len(overlap)} shared samples",
                count=len(overlap),
            )
        ]
    return []


def verify_strategy_viable_after_costs(
    gross_return: float, fees: float, slippage: float, financing: float, taxes: float = 0.0
) -> list[Violation]:
    """A strategy must be profitable AFTER fees, slippage, financing and taxes —
    many backtests pass gross and fail net."""
    if not all(_is_finite_number(x) for x in (gross_return, fees, slippage, financing, taxes)):
        return [_v("No Hidden Loss", CRITICAL, "after-cost components non-finite")]
    net = gross_return - fees - slippage - financing - taxes
    if net <= 0:
        return [
            _v(
                "No Hidden Loss",
                WARNING,
                f"strategy not viable after costs: net {round(net, 6)} (gross {gross_return})",
                net=round(net, 6),
            )
        ]
    return []


# ── isolation (No Cross-Tenant / Cross-Pod Leakage) ─────────────────────────────
def verify_pod_isolation(
    pod_a: dict[str, Any], pod_b: dict[str, Any], keys: tuple[str, ...] = ("positions", "memory", "models", "capital")
) -> list[Violation]:
    """Two pods must never share state across the named dimensions."""
    out: list[Violation] = []
    for k in keys:
        a, b = pod_a.get(k), pod_b.get(k)
        if a is not None and a == b:
            out.append(_v("No Cross-Pod Leakage", CONSTITUTIONAL, f"pods share identical {k} — contamination"))
    return out


# ── audit & ledger immutability ─────────────────────────────────────────────────
def verify_audit_immutable(record_hash: str, stored_hash: str) -> list[Violation]:
    if record_hash != stored_hash:
        return [_v("No Audit Gap", CONSTITUTIONAL, "audit record hash changed (immutability violated)")]
    return []


def verify_audit_complete(
    record: dict[str, Any], required: tuple[str, ...] = ("who", "when", "what", "result")
) -> list[Violation]:
    """Every audited action must record who/when/what/result."""
    missing = [f for f in required if not record.get(f)]
    if missing:
        return [_v("No Audit Gap", CRITICAL, f"audit record missing fields: {missing}")]
    return []


def verify_action_audited(action_id: Any, audited_ids: Iterable[Any]) -> list[Violation]:
    """Every executed AI action / decision must leave a structured audit record
    (No Hidden AI Action). An action whose id is absent from the audit set ran
    without being recorded — a constitutional accountability gap."""
    if action_id is None:
        return [_v("No Hidden AI Action", CRITICAL, "AI action has no id to audit")]
    if action_id not in set(audited_ids):
        return [_v("No Hidden AI Action", CONSTITUTIONAL, f"AI action {action_id!r} executed without an audit record")]
    return []


def verify_hash_chain(
    records: list[dict[str, Any]], *, hash_field: str = "hash", prev_field: str = "prev_hash", genesis: str = "0" * 64
) -> list[Violation]:
    """A tamper-evident audit log must form an unbroken hash chain: each record's
    ``prev_field`` must equal the previous record's ``hash_field`` (the first
    links to ``genesis``). A break is evidence of tampering or a lost record
    (No Audit Gap). Records are taken in the order given.
    """
    out: list[Violation] = []
    expected_prev = genesis
    for i, rec in enumerate(records):
        prev = rec.get(prev_field, genesis if i == 0 else None)
        if prev != expected_prev:
            out.append(
                _v(
                    "No Audit Gap",
                    CONSTITUTIONAL,
                    f"audit hash-chain broken at record {i}: prev {prev!r} != expected {expected_prev!r}",
                    index=i,
                )
            )
            break
        cur = rec.get(hash_field)
        if not cur:
            out.append(_v("No Audit Gap", CONSTITUTIONAL, f"audit record {i} has no {hash_field}", index=i))
            break
        expected_prev = cur
    return out


# ── separation of duties / dual control ─────────────────────────────────────────
def verify_segregation_of_duties(creator: Any, approver: Any) -> list[Violation]:
    if creator is not None and creator == approver:
        return [_v("No Compliance Breach", CONSTITUTIONAL, "creator and approver are the same party")]
    return []


def verify_dual_control(approvals: Iterable[Any], required: int = 2) -> list[Violation]:
    distinct = {a for a in approvals if a is not None}
    if len(distinct) < required:
        return [
            _v(
                "No Unauthorized Capital Movement",
                CONSTITUTIONAL,
                f"dual control: {len(distinct)} distinct approvals < required {required}",
            )
        ]
    return []


# ── config / deployment / control ───────────────────────────────────────────────
def verify_config_unchanged(runtime_config: Any, approved_config: Any) -> list[Violation]:
    if runtime_config != approved_config:
        return [_v("No Unexplained System Behavior", CRITICAL, "runtime config drifted from approved config")]
    return []


def verify_deployment_gates(gates: dict[str, bool]) -> list[Violation]:
    failed = [g for g, ok in gates.items() if not ok]
    if failed:
        return [_v("No Unrecoverable Failure", CRITICAL, f"deployment gates not passed: {failed}")]
    return []


def verify_human_supremacy(human_authority: float, system_authority: float) -> list[Violation]:
    """The ultimate invariant: humans can always outrank/stop the system."""
    if (
        _is_finite_number(human_authority)
        and _is_finite_number(system_authority)
        and human_authority <= system_authority
    ):
        return [_v("No Loss Of Human Control", CONSTITUTIONAL, "human authority does not exceed system authority")]
    return []


def verify_human_approval(notional: float, threshold: float, approved_by: Any) -> list[Violation]:
    """Large trades require a named human approver (four-eyes / dual control).

    Institutional control: an order whose notional reaches ``threshold`` must
    carry a non-empty ``approved_by`` (the human who authorized it). Autonomous
    capital movement at/above the threshold without a human in the loop is a
    CONSTITUTIONAL breach (No Loss Of Human Control). ``threshold <= 0`` disables
    the gate. A non-finite notional is treated as unknown and not blocked here
    (other gates catch bad numbers).
    """
    if threshold <= 0 or not _is_finite_number(notional):
        return []
    if abs(notional) >= threshold and not (isinstance(approved_by, str) and approved_by.strip()):
        return [
            _v(
                "No Loss Of Human Control",
                CONSTITUTIONAL,
                f"order notional {abs(notional):.2f} >= human-approval threshold {threshold:.2f} "
                "but carries no approver (approved_by)",
            )
        ]
    return []
