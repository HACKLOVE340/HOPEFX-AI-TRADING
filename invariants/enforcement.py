# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.enforcement — the bridge from pure predicates to the live money path.

The invariant library (``invariants.*``) is inert until something calls it at the
points where money and state move. This module is that single, **fail-safe**
integration surface. It is deliberately the only place the rest of the app
imports for enforcement, so the money-path edits stay tiny and auditable.

Design rules (this is a money-moving system):

* **Feature-flagged.** ``HOPEFX_INVARIANT_MODE`` ∈ {``off``, ``monitor``,
  ``enforce``}. Default ``monitor`` — checks run and log but **never block**, so
  turning the wiring on changes no trading behaviour. Flipping to ``enforce`` is
  the deliberate, explicit activation of blocking/halting.
* **Staged rollout (per-check).** Rather than one global flip that makes every
  check blocking at once, keep the global mode at ``monitor`` and promote
  individual checks via ``HOPEFX_INVARIANT_ENFORCE_KINDS`` (comma-separated
  kinds, or ``all``). ``HOPEFX_INVARIANT_MONITOR_KINDS`` is the inverse — hold a
  named check in monitor while the global mode is ``enforce``. See
  :func:`effective_mode`. This is the safe way to enable enforcement on a live
  desk: one check at a time, watching telemetry between steps.
* **Fail-safe on findings.** In ``enforce`` mode a CONSTITUTIONAL or CRITICAL
  violation blocks the trade / signals a halt. WARNINGs only log.
* **Cannot take the desk down by accident.** A bug *inside this layer* must not
  halt trading. Exceptions raised while checking are swallowed and logged; they
  do not block unless ``HOPEFX_INVARIANT_FAIL_CLOSED=1`` is set explicitly.
* **No raises into callers.** Every public function returns an
  :class:`EnforcementResult`; it never propagates an exception.

Nothing here performs trading I/O. The kill switch is imported lazily and only
*queried/observed* — actual activation is the caller's decision based on the
returned result.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _v,
    summarize,
    verify_capital_equation,
    verify_finite,
    verify_pnl_reconciliation,
    verify_spread,
    verify_tick,
    verify_within_limit,
)
from invariants.ai import verify_trust_floor, verify_trust_score, verify_trust_weighted_allocation
from invariants.governance import verify_action_audited, verify_human_approval, verify_pod_isolation
from invariants.payments import (
    verify_amount_valid,
    verify_balance_after,
    verify_withdrawal_within_balance,
)
from invariants.resilience import verify_recovery_path_exists
from invariants.risk import (
    verify_daily_loss,
    verify_drawdown,
    verify_exposure_limits,
    verify_leverage,
    verify_var,
)
from invariants.systems import verify_blast_radius_contained, verify_no_single_point_of_failure

logger = logging.getLogger("hopefx.invariants")

# ── modes ────────────────────────────────────────────────────────────────────────
MODE_OFF = "off"
MODE_MONITOR = "monitor"
MODE_ENFORCE = "enforce"
_VALID_MODES = (MODE_OFF, MODE_MONITOR, MODE_ENFORCE)
_DEFAULT_MODE = MODE_MONITOR


def current_mode() -> str:
    """Read the *global* enforcement mode from the environment (re-read each call
    so ops can change it without a restart). Unknown values fall back to
    ``monitor``."""
    mode = os.environ.get("HOPEFX_INVARIANT_MODE", _DEFAULT_MODE).strip().lower()
    return mode if mode in _VALID_MODES else _DEFAULT_MODE


# Every check ``kind`` the façade emits — the vocabulary for staged rollout and
# the resolved view in :func:`status`. Keep in sync with the ``_safe(...)`` calls.
KNOWN_KINDS: tuple[str, ...] = (
    "pre_trade",
    "order_authorization",
    "human_approval",
    "reconciliation",
    "ledger",
    "exposure",
    "var",
    "trust_allocation",
    "risk_appetite",
    "policy_governance",
    "spof",
    "blast_radius",
    "action_audit",
    "pod_isolation",
    "recovery_readiness",
    "audit_chain",
)


def _kinds_from_env(var: str) -> frozenset[str]:
    """Parse a comma-separated set of check kinds from ``var`` (lower-cased)."""
    return frozenset(k.strip().lower() for k in os.environ.get(var, "").split(",") if k.strip())


def effective_mode(kind: str) -> str:
    """Resolve the enforcement mode for a specific check *kind*.

    This is what makes a **staged** enforce rollout safe on a live money path:
    rather than one global flip that makes every check blocking at once, ops can
    keep the global mode at ``monitor`` and promote individual kinds to
    ``enforce`` one at a time via ``HOPEFX_INVARIANT_ENFORCE_KINDS`` (a
    comma-separated list, or ``all``). The inverse lever
    ``HOPEFX_INVARIANT_MONITOR_KINDS`` demotes named kinds back to ``monitor``
    while the global mode is ``enforce`` — useful to carve out one noisy check
    without losing enforcement everywhere else.

    Precedence: ``off`` (global) wins over everything. Otherwise a per-kind
    promotion/demotion overrides the global mode for that kind only. With no
    per-kind vars set, this is exactly ``current_mode()`` for every kind, so
    behaviour is unchanged by default.
    """
    mode = current_mode()
    if mode == MODE_OFF:
        return MODE_OFF
    k = kind.strip().lower()
    if mode == MODE_MONITOR:
        enforce_kinds = _kinds_from_env("HOPEFX_INVARIANT_ENFORCE_KINDS")
        if "all" in enforce_kinds or k in enforce_kinds:
            return MODE_ENFORCE
        return MODE_MONITOR
    # mode == enforce: allow selectively holding a kind back in monitor.
    if k in _kinds_from_env("HOPEFX_INVARIANT_MONITOR_KINDS"):
        return MODE_MONITOR
    return MODE_ENFORCE


def _fail_closed() -> bool:
    """Whether a checker-internal error should itself block (default: no)."""
    return os.environ.get("HOPEFX_INVARIANT_FAIL_CLOSED", "0").strip() == "1"


# ── result type ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EnforcementResult:
    """Outcome of an enforcement check.

    ``allowed``     — False only in enforce mode when blocking and a blocking
                      violation (or a fail-closed checker error) was found.
    ``should_halt`` — same trigger, surfaced for callers that halt/trip rather
                      than refuse a single action (e.g. the reconciliation loop).
    ``violations``  — every Violation found (all severities).
    ``mode``        — the mode the check ran under.
    ``reason``      — short human string for logs / block reasons.
    """

    allowed: bool
    should_halt: bool
    violations: list[Violation] = field(default_factory=list)
    mode: str = _DEFAULT_MODE
    reason: str = ""

    @property
    def blocking(self) -> bool:
        return any(v.severity in (CONSTITUTIONAL, CRITICAL) for v in self.violations)


def _is_blocking(violations: list[Violation]) -> bool:
    return any(v.severity in (CONSTITUTIONAL, CRITICAL) for v in violations)


def _reason(violations: list[Violation]) -> str:
    blk = [v for v in violations if v.severity in (CONSTITUTIONAL, CRITICAL)]
    head = blk[0] if blk else (violations[0] if violations else None)
    if head is None:
        return "ok"
    extra = f" (+{len(violations) - 1} more)" if len(violations) > 1 else ""
    return f"{head.rule}: {head.message}{extra}"


# ── lightweight in-process telemetry for the /health/invariants endpoint ───────────
_MAX_RECENT = 50
_recent: deque[dict[str, Any]] = deque(maxlen=_MAX_RECENT)
_counters: dict[str, int] = {
    "checks": 0,
    "violations": 0,
    "blocked": 0,
    "halts_signalled": 0,
    "checker_errors": 0,
}


def _record(kind: str, result: EnforcementResult) -> None:
    _counters["checks"] += 1
    if result.violations:
        _counters["violations"] += len(result.violations)
    if not result.allowed:
        _counters["blocked"] += 1
    if result.should_halt:
        _counters["halts_signalled"] += 1
    if result.violations:
        _recent.append(
            {
                "kind": kind,
                "mode": result.mode,
                "allowed": result.allowed,
                "should_halt": result.should_halt,
                "reason": result.reason,
                "counts": summarize(result.violations)["counts"],
            }
        )


def _decide(kind: str, violations: list[Violation], *, checker_error: bool = False) -> EnforcementResult:
    """Turn a violation list into a mode-aware decision and record it.

    The single place mode semantics live:
      * off      → always allow, no logging beyond debug.
      * monitor  → log findings, never block.
      * enforce  → block/halt on a blocking violation (or fail-closed error).
    """
    mode = effective_mode(kind)
    blocking = _is_blocking(violations) or (checker_error and _fail_closed())
    reason = _reason(violations) if violations else ("checker_error" if checker_error else "ok")

    if mode == MODE_OFF:
        result = EnforcementResult(True, False, violations, mode, reason)
        _record(kind, result)
        return result

    # Log: blocking findings loudly, warnings at warning level.
    if violations:
        if _is_blocking(violations):
            logger.error("INVARIANT[%s/%s] blocking violation(s): %s", kind, mode, reason)
        else:
            logger.warning("INVARIANT[%s/%s] warning(s): %s", kind, mode, reason)

    if mode == MODE_MONITOR:
        result = EnforcementResult(True, False, violations, mode, reason)
        _record(kind, result)
        return result

    # enforce
    allowed = not blocking
    result = EnforcementResult(allowed, blocking, violations, mode, reason)
    _record(kind, result)
    return result


def _safe(kind: str, fn: Any) -> EnforcementResult:
    """Run a checker thunk; never let an internal error reach the caller."""
    if effective_mode(kind) == MODE_OFF:
        return EnforcementResult(True, False, [], MODE_OFF, "off")
    try:
        violations = fn() or []
    except Exception as exc:  # checker bug must not crash the money path
        _counters["checker_errors"] += 1
        logger.exception(
            "INVARIANT[%s] checker raised — failing %s: %s", kind, "CLOSED" if _fail_closed() else "OPEN", exc
        )
        return _decide(kind, [], checker_error=True)
    return _decide(kind, violations)


def _resolve_epoch(signal, names: tuple[str, ...]) -> float | None:
    """Return the first usable timestamp from *names* as a POSIX float.

    Accepts ``int``/``float`` epochs **and** ``datetime`` objects. Accepting
    only numerics meant the freshness check silently found nothing to measure:
    ``_MinimalSignal`` carries no timestamp at all, and the brain's ``Signal``
    carries a ``datetime`` — so the "never trade on a stale tick" invariant
    could not fire on either signal type used in production.
    See docs/HARDENING_BACKLOG.md S5-01.

    Naive datetimes are assumed UTC, matching the rest of the data layer.
    """
    for name in names:
        raw = getattr(signal, name, None)
        if isinstance(raw, bool) or raw is None:
            continue
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, datetime):
            ts = raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
            return ts.timestamp()
    return None


# ════════════════════════════════════════════════════════════════════════════════
# 1. PRE-TRADE GATE
# ════════════════════════════════════════════════════════════════════════════════
def enforce_pre_trade(
    signal: Any,
    *,
    data_quality: float | None = None,
    equity: float | None = None,
    min_confidence: float = 0.0,
    now: float | None = None,
    max_staleness_s: float | None = None,
) -> EnforcementResult:
    """Verify constitutional invariants on a signal/order *before* it can size.

    Reads attributes defensively (``getattr``) so it works with any signal-like
    object. Checks: finite confidence/probability/equity, valid tick price &
    spread, an optional minimum confidence floor, and — when the signal carries a
    timestamp and ``now``/``max_staleness_s`` are supplied — market-data
    freshness (No Unverified AI Decision: never trade on a stale tick). In
    enforce mode a blocking violation makes ``allowed`` False so the caller
    refuses the order.
    """

    def _check() -> list[Violation]:
        out: list[Violation] = []
        conf = getattr(signal, "confidence", None)
        prob = getattr(signal, "probability", None)
        mid = getattr(signal, "tick_mid", None)
        spread = getattr(signal, "tick_spread", None)

        if conf is not None:
            out += verify_finite(conf, "signal.confidence")
        if prob is not None:
            out += verify_finite(prob, "signal.probability")
        if equity is not None:
            out += verify_finite(equity, "equity")
        if data_quality is not None:
            out += verify_finite(data_quality, "data_quality")

        # Tick price sanity (only when a live mid is present and positive-intended).
        if isinstance(mid, (int, float)) and not isinstance(mid, bool) and mid > 0:
            out += verify_tick(mid, 0.0)
            if isinstance(spread, (int, float)) and not isinstance(spread, bool) and spread >= 0:
                # bid/ask reconstructed from mid ± half-spread must not cross.
                half = spread / 2.0
                out += verify_spread(mid - half, mid + half)

        # Confidence floor (No Unverified AI Decision) — only if asked for.
        if min_confidence > 0 and isinstance(conf, (int, float)) and not isinstance(conf, bool):
            out += verify_within_limit(
                min_confidence,
                conf,
                "min_confidence_vs_confidence",
                rule="No Unverified AI Decision",
                severity=CRITICAL,
            )

        # Market-data freshness — never trade on a stale tick. Only runs when a
        # timestamp is present on the signal and a budget was supplied; the first
        # attribute among (tick_ts, tick_timestamp, ts, timestamp) wins.
        if now is not None and max_staleness_s is not None:
            tick_ts = _resolve_epoch(signal, ("tick_ts", "tick_timestamp", "ts", "timestamp"))
            if tick_ts is not None:
                out += verify_within_limit(
                    now - tick_ts,
                    max_staleness_s,
                    "market_data_staleness_s",
                    rule="No Unverified AI Decision",
                    severity=CRITICAL,
                )
        return out

    return _safe("pre_trade", _check)


# ════════════════════════════════════════════════════════════════════════════════
# 2. RECONCILIATION LOOP
# ════════════════════════════════════════════════════════════════════════════════
def enforce_reconciliation(
    *,
    internal_value: float | None = None,
    external_value: float | None = None,
    value_tol: float = 0.01,
    pnl: tuple[float, float, float] | None = None,
    extra: list[Violation] | None = None,
) -> EnforcementResult:
    """Verify capital/PnL reconciliation on a cycle.

    ``internal_value``/``external_value`` — aggregate book value the platform
    believes vs. what the broker reports; a mismatch beyond ``value_tol`` is a
    CONSTITUTIONAL breach (No Hidden Loss). ``pnl`` is ``(realized, unrealized,
    total)`` for the PnL identity. ``extra`` lets callers fold in violations they
    computed with other predicates. ``should_halt`` is the signal to trip the
    kill switch (the caller performs the actual activation).
    """

    def _check() -> list[Violation]:
        out: list[Violation] = list(extra or [])
        if internal_value is not None and external_value is not None:
            out += verify_within_limit(
                abs(internal_value - external_value),
                value_tol,
                "book_value_reconciliation_gap",
                rule="No Hidden Loss",
                severity=CONSTITUTIONAL,
            )
        if pnl is not None:
            realized, unrealized, total = pnl
            out += verify_pnl_reconciliation(realized, unrealized, total)
        return out

    return _safe("reconciliation", _check)


# ════════════════════════════════════════════════════════════════════════════════
# 2b. EXPOSURE — per-dimension/per-symbol limits (No Hidden Exposure)
# ════════════════════════════════════════════════════════════════════════════════
def enforce_exposure(exposure: dict[str, float], limits: dict[str, float]) -> EnforcementResult:
    """Verify each exposure dimension (per-symbol notional, sector, leverage)
    stays within its approved limit. ``exposure`` and ``limits`` share keys; a
    dimension over its limit is a CRITICAL breach (No Hidden Exposure).
    ``should_halt`` is set so a caller may halt/trip on a breach in enforce mode.
    """
    return _safe("exposure", lambda: verify_exposure_limits(exposure, limits))


def enforce_var(portfolio_var: float, approved_var: float) -> EnforcementResult:
    """Assert portfolio Value-at-Risk stays within the approved limit each cycle
    (No Hidden Risk). Both are positive loss magnitudes (USD)."""
    return _safe("var", lambda: verify_var(portfolio_var, approved_var))


def enforce_trust_allocation(allocations: dict[str, dict[str, float]], floor: float = 0.0) -> EnforcementResult:
    """Enforce AI subsystem trust scoring (architecture #7): every trust score is
    valid [0,1], no distrusted subsystem (trust < ``floor``) holds capital, and
    capital is not inverted vs trust. ``allocations`` maps name -> {trust, capital}."""

    def _check() -> list[Violation]:
        out: list[Violation] = []
        for name, a in allocations.items():
            out += verify_trust_score(a.get("trust"), name)
            if floor > 0:
                out += verify_trust_floor(a.get("trust"), a.get("capital", 0.0), floor)
        out += verify_trust_weighted_allocation(allocations)
        return out

    return _safe("trust_allocation", _check)


def enforce_risk_appetite(state: dict[str, Any], policy: dict[str, Any]) -> EnforcementResult:
    """Enforce the firm's Risk Appetite Framework against live ``state``.

    ``policy`` is a loaded risk-appetite policy (see ``risk.risk_appetite``).
    ``state`` may contain any of: ``daily_loss_pct``, ``drawdown_pct``,
    ``portfolio_var`` (USD), ``leverage``, ``symbol_exposures`` (name->USD),
    ``traded_symbol``, ``jurisdiction``. Each present field is checked against the
    policy; off-limits symbols/jurisdictions are refused outright. This is the
    technical half of the governance process: the system actually obeys the
    signed risk policy, not just a document.
    """

    def _check() -> list[Violation]:
        out: list[Violation] = []
        limits = dict(policy.get("limits", {}) or {})
        prohibited = policy.get("prohibited", {}) or {}
        allowed_jur = set(policy.get("allowed_jurisdictions", []) or [])

        if "daily_loss_pct" in state and "max_daily_loss_pct" in limits:
            out += verify_daily_loss(state["daily_loss_pct"], limits["max_daily_loss_pct"])
        if "drawdown_pct" in state and "max_drawdown_pct" in limits:
            out += verify_drawdown(state["drawdown_pct"], limits["max_drawdown_pct"])
        if "leverage" in state and "max_leverage" in limits:
            out += verify_leverage(state["leverage"], limits["max_leverage"])
        if "portfolio_var" in state and float(limits.get("approved_var_usd", 0) or 0) > 0:
            out += verify_var(state["portfolio_var"], limits["approved_var_usd"])
        if "symbol_exposures" in state and "max_symbol_exposure_usd" in limits:
            exposures = dict(state["symbol_exposures"])
            caps = dict.fromkeys(exposures, limits["max_symbol_exposure_usd"])
            out += verify_exposure_limits(exposures, caps)

        sym = state.get("traded_symbol")
        if sym is not None and sym in set(prohibited.get("symbols", []) or []):
            out.append(
                _v("No Unauthorized Trade", CONSTITUTIONAL, f"trade on prohibited symbol {sym!r} (risk-appetite)")
            )

        jur = state.get("jurisdiction")
        if jur is not None:
            if jur in set(prohibited.get("jurisdictions_blocked", []) or []):
                out.append(_v("No Compliance Breach", CONSTITUTIONAL, f"trade in blocked jurisdiction {jur!r}"))
            elif allowed_jur and jur not in allowed_jur:
                out.append(_v("No Compliance Breach", CRITICAL, f"jurisdiction {jur!r} not in allowed set"))
        return out

    return _safe("risk_appetite", _check)


def enforce_policy_governance(policy: dict[str, Any], today: str | None = None) -> EnforcementResult:
    """Surface governance-hygiene problems with the risk-appetite policy itself
    (unsigned, placeholder approver, overdue review). An unsigned/overdue policy
    governing capital is itself a control failure."""

    def _check() -> list[Violation]:
        from risk.risk_appetite import validate_policy

        return [_v("No Loss Of Human Control", CRITICAL, msg) for msg in validate_policy(policy, today)]

    return _safe("policy_governance", _check)


def enforce_ledger_reconciliation(
    *,
    opening: float,
    deposits: float,
    realized: float,
    withdrawals: float,
    fees: float,
    closing: float,
    tol: float = 0.01,
) -> EnforcementResult:
    """Assert the capital equation holds (No Hidden Capital):
    opening + deposits + realized − withdrawals − fees == closing. A breach means
    an accounting/reconciliation bug or fraud; ``should_halt`` flags it."""
    return _safe(
        "ledger",
        lambda: verify_capital_equation(opening, deposits, realized, withdrawals, fees, closing, tol),
    )


def enforce_wallet_movement(
    *,
    before: float,
    delta: float,
    after: float,
    available: float | None = None,
    tol: float = 0.01,
) -> EnforcementResult:
    """Assert a single wallet credit/debit is sound before it is recorded.

    ``before + delta`` must equal ``after`` (No Unauthorized Capital Movement),
    the amount must be finite and positive, and a debit must not exceed
    ``available``. Wired from payments/wallet.py; runs under the ``ledger`` kind
    alongside enforce_ledger_reconciliation, which checks the same property over
    a whole account period rather than one movement.

    The write path additionally refuses on its own exact-Decimal check, because
    a balance that does not reconcile must never be recorded regardless of
    HOPEFX_INVARIANT_MODE. This wrapper is what makes the violation *observable*
    — counted, logged and surfaced by enforcement.status.
    """

    def _check() -> list[Violation]:
        violations = verify_amount_valid(abs(delta))
        violations += verify_balance_after(before, delta, after, tol)
        if available is not None and delta < 0:
            violations += verify_withdrawal_within_balance(abs(delta), available)
        return violations

    return _safe("ledger", _check)


def enforce_no_spof(dependencies: dict[str, dict[str, Any]]) -> EnforcementResult:
    """Assert no critical dependency is a single point of failure (No Critical
    Single Point Of Failure). ``dependencies`` maps name -> {critical, redundancy,
    failover}."""
    return _safe("spof", lambda: verify_no_single_point_of_failure(dependencies))


def enforce_blast_radius(failed_components: int, total_components: int, max_fraction: float = 0.5) -> EnforcementResult:
    """Assert a single failure cannot take down most of the platform
    (No Unbounded Failure)."""
    return _safe(
        "blast_radius", lambda: verify_blast_radius_contained(failed_components, total_components, max_fraction)
    )


def enforce_action_audited(action_id: Any, audited_ids: Any) -> EnforcementResult:
    """Assert an executed AI action/decision left a structured audit record
    (No Hidden AI Action)."""
    return _safe("action_audit", lambda: verify_action_audited(action_id, audited_ids))


# ════════════════════════════════════════════════════════════════════════════════
# 3. ORDER AUTHORIZATION — no order reaches a broker without passing the risk gate
# ════════════════════════════════════════════════════════════════════════════════
def enforce_order_authorization(order: Any) -> EnforcementResult:
    """Assert an order carries proof it passed the risk gate (a non-empty
    ``risk_approval_token``) and is linked to a decision (``decision_id``).

    This is the choke-point guarantee for No Unauthorized Trade + No Hidden
    Decision: in enforce mode an order missing either is refused. Reads both
    attributes and ``metadata`` defensively so it works with the OMS Order
    dataclass or a plain dict-like.
    """

    def _get(name: str) -> Any:
        val = getattr(order, name, None)
        if not val and isinstance(getattr(order, "metadata", None), dict):
            val = order.metadata.get(name)
        if not val and isinstance(order, dict):
            val = order.get(name)
        return val

    def _check() -> list[Violation]:
        out: list[Violation] = []
        if not _get("risk_approval_token"):
            out.append(
                _v("No Unauthorized Trade", CONSTITUTIONAL, "order has no risk-approval token (risk gate bypassed?)")
            )
        if not _get("decision_id"):
            out.append(_v("No Hidden Decision", CRITICAL, "order has no linked decision id"))
        return out

    return _safe("order_authorization", _check)


# ════════════════════════════════════════════════════════════════════════════════
# 3b. HUMAN APPROVAL — large notionals need a named human (four-eyes / dual control)
# ════════════════════════════════════════════════════════════════════════════════
def enforce_human_approval(order: Any, threshold: float | None = None) -> EnforcementResult:
    """Require a named human approver on orders at/above a notional threshold.

    The threshold comes from ``threshold`` or the ``RISK_HUMAN_APPROVAL_NOTIONAL_USD``
    env var (default ``0`` = gate disabled). Notional is read defensively as
    ``notional_usd``/``notional``, else ``abs(quantity) * (price|tick_mid)``. The
    approver is read from ``approved_by``/``approver`` (attr, ``metadata``, or dict
    key). In enforce mode a large order with no approver is refused (No Loss Of
    Human Control) — the human-in-the-loop gate the readiness map calls for.
    """
    if threshold is None:
        try:
            threshold = float(os.environ.get("RISK_HUMAN_APPROVAL_NOTIONAL_USD", "0") or 0)
        except (TypeError, ValueError):
            threshold = 0.0

    def _get(name: str) -> Any:
        val = getattr(order, name, None)
        if not val and isinstance(getattr(order, "metadata", None), dict):
            val = order.metadata.get(name)
        if not val and isinstance(order, dict):
            val = order.get(name)
        return val

    def _num(name: str) -> float | None:
        v = _get(name)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _check() -> list[Violation]:
        notional = _num("notional_usd")
        if notional is None:
            notional = _num("notional")
        if notional is None:
            qty = _num("quantity") or _num("size")
            px = _num("price") or _num("tick_mid") or _num("fill_price")
            notional = abs(qty) * px if (qty is not None and px is not None) else float("nan")
        approver = _get("approved_by") or _get("approver")
        return verify_human_approval(notional, float(threshold or 0.0), approver)

    return _safe("human_approval", _check)


# ════════════════════════════════════════════════════════════════════════════════
# ISOLATION — no cross-tenant / cross-pod leakage
# ════════════════════════════════════════════════════════════════════════════════
def enforce_pod_isolation(
    pod_a: dict[str, Any], pod_b: dict[str, Any], keys: tuple[str, ...] = ("positions", "memory", "models", "capital")
) -> EnforcementResult:
    """Assert two pods/tenants share no state across the named dimensions. Shared
    identical state is a CONSTITUTIONAL breach (No Cross-Pod Leakage)."""
    return _safe("pod_isolation", lambda: verify_pod_isolation(pod_a, pod_b, keys))


# ════════════════════════════════════════════════════════════════════════════════
# RECOVERY — no unrecoverable failure
# ════════════════════════════════════════════════════════════════════════════════
def enforce_recovery_readiness(paths: dict[str, tuple[bool, bool]]) -> EnforcementResult:
    """Assert each critical subsystem has a recovery path that exists and has been
    tested. ``paths`` maps name -> (has_path, tested). A missing/untested path is
    a CRITICAL gap (No Unrecoverable Failure)."""

    def _check() -> list[Violation]:
        out: list[Violation] = []
        for name, (has_path, tested) in paths.items():
            out += verify_recovery_path_exists(name, has_path, tested)
        return out

    return _safe("recovery_readiness", _check)


# ════════════════════════════════════════════════════════════════════════════════
# AUDIT CHAIN — tamper-evident audit log (No Audit Gap)
# ════════════════════════════════════════════════════════════════════════════════
def enforce_audit_chain(intact: bool, *, broken_at: Any = None) -> EnforcementResult:
    """Assert the audit hash-chain verified intact. A broken chain is a
    CONSTITUTIONAL breach (No Audit Gap) — evidence of tampering or loss."""

    def _check() -> list[Violation]:
        if not intact:
            return [_v("No Audit Gap", CONSTITUTIONAL, f"audit hash-chain integrity broken (at {broken_at!r})")]
        return []

    return _safe("audit_chain", _check)


# ════════════════════════════════════════════════════════════════════════════════
# 4. STATUS (for /health/invariants)
# ════════════════════════════════════════════════════════════════════════════════
def status() -> dict[str, Any]:
    """Live enforcement status for the control center / health endpoint.

    Includes a self-check that the invariant engine itself is operable (it must
    return ``[]`` on a trivially-valid input) — monitoring the monitor.
    """
    engine_ok = True
    try:
        engine_ok = verify_pnl_reconciliation(1.0, 1.0, 2.0) == []
    except Exception:  # pragma: no cover - defensive
        engine_ok = False

    mode = current_mode()
    resolved = {k: effective_mode(k) for k in KNOWN_KINDS}
    return {
        "mode": mode,
        "active": mode != MODE_OFF,
        # True if *any* check blocks — global enforce OR a staged per-kind promotion.
        "blocking_enabled": any(m == MODE_ENFORCE for m in resolved.values()),
        "fail_closed": _fail_closed(),
        "enforce_kinds": sorted(_kinds_from_env("HOPEFX_INVARIANT_ENFORCE_KINDS")),
        "monitor_kinds": sorted(_kinds_from_env("HOPEFX_INVARIANT_MONITOR_KINDS")),
        "resolved": resolved,
        "engine_healthy": engine_ok,
        "counters": dict(_counters),
        "recent": list(_recent),
        "ok": engine_ok and _counters["checker_errors"] == 0,
    }


def reset_telemetry() -> None:
    """Reset counters/recent — test fixtures only."""
    _recent.clear()
    for k in _counters:
        _counters[k] = 0
