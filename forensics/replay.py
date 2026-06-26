# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
forensics.replay — failure & decision replay for post-incident reconstruction.

When something goes wrong (or an AI makes a surprising call), you need to answer
two questions deterministically, after the fact:

  * **Decision replay** — "Why did the AI do that, and would today's controls
    have allowed it?" Reconstruct the decision chain (decision → model → prompt →
    features → data → trade) from its recorded trace, verify it is complete, and
    re-run the constitutional invariants against the recorded state.
  * **Failure replay** — "Does this failure still reproduce?" Re-evaluate a
    recorded violation against its recorded inputs through the SAME enforcement
    code path the live system uses, so a bug can be confirmed and a fix proven.

Faithfulness matters: replay drives the real ``invariants.enforcement`` facade
(forced to ``enforce`` semantics so the verdict is unambiguous), not a parallel
copy of the logic. Pure with respect to trading — it never places orders or
mutates state; it only reads recorded records and evaluates predicates.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from invariants import enforcement as enf
from invariants import meta

_DECISION_LINKS = ("decision_id", "model_version", "prompt_hash", "features_hash", "data_snapshot", "trade_id")


@contextlib.contextmanager
def _forced_enforce():
    """Evaluate predicates under enforce semantics regardless of the live mode —
    replay is an offline debug tool, so the verdict must be deterministic."""
    prev = os.environ.get("HOPEFX_INVARIANT_MODE")
    os.environ["HOPEFX_INVARIANT_MODE"] = "enforce"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("HOPEFX_INVARIANT_MODE", None)
        else:
            os.environ["HOPEFX_INVARIANT_MODE"] = prev


def _violations(result: Any) -> list[dict[str, Any]]:
    return [{"rule": v.rule, "severity": v.severity, "message": v.message} for v in result.violations]


# ── decision replay ───────────────────────────────────────────────────────────────
def replay_decision(record: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct and re-evaluate a single recorded decision.

    ``record`` carries the trace links (``decision_id`` … ``trade_id``) and,
    optionally, ``signal`` (the recorded signal state) and ``risk_state`` +
    ``policy`` for a risk-appetite re-evaluation. Returns whether the decision is
    fully reconstructable and whether it would pass today's invariants.
    """
    trace = {link: record.get(link) for link in _DECISION_LINKS}
    trace_gaps = [v.context.get("missing") for v in meta.verify_decision_trace(trace) if v.context]
    reconstructable = not meta.verify_decision_trace(trace)

    violations: list[dict[str, Any]] = []
    with _forced_enforce():
        signal = record.get("signal")
        if signal is not None:
            sig = SimpleNamespace(**signal)
            res = enf.enforce_pre_trade(
                sig,
                data_quality=signal.get("data_quality"),
                equity=signal.get("equity"),
                now=record.get("now"),
                max_staleness_s=record.get("max_staleness_s"),
            )
            violations += _violations(res)
        if "risk_state" in record and "policy" in record:
            res = enf.enforce_risk_appetite(record["risk_state"], record["policy"])
            violations += _violations(res)

    blocking = [v for v in violations if v["severity"] in ("CONSTITUTIONAL", "CRITICAL")]
    return {
        "decision_id": record.get("decision_id"),
        "reconstructable": reconstructable,
        "trace_gaps": [g for g in trace_gaps if g],
        "would_pass_today": not blocking,
        "violations": violations,
    }


# ── failure replay ─────────────────────────────────────────────────────────────────
# Map a recorded failure 'kind' to the enforcement entry point that re-evaluates it.
def _replay_pre_trade(inputs: dict[str, Any]) -> Any:
    sig = SimpleNamespace(**inputs.get("signal", {}))
    return enf.enforce_pre_trade(
        sig,
        data_quality=inputs.get("data_quality"),
        equity=inputs.get("equity"),
        now=inputs.get("now"),
        max_staleness_s=inputs.get("max_staleness_s"),
    )


_FAILURE_KINDS = {
    "pre_trade": _replay_pre_trade,
    "reconciliation": lambda i: enf.enforce_reconciliation(**i),
    "risk_appetite": lambda i: enf.enforce_risk_appetite(i["state"], i["policy"]),
    "ledger": lambda i: enf.enforce_ledger_reconciliation(**i),
    "exposure": lambda i: enf.enforce_exposure(i["exposure"], i["limits"]),
    "var": lambda i: enf.enforce_var(i["portfolio_var"], i["approved_var"]),
    "order_authorization": lambda i: enf.enforce_order_authorization(i.get("order", i)),
}


def replay_failure(record: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate a recorded failure to confirm it reproduces deterministically.

    ``record`` = ``{"kind": <one of _FAILURE_KINDS>, "inputs": {...},
    "expected_violation": bool}``. Returns whether the observed result matches
    the expectation (``reproduced``) — the basis of a regression check: a real
    bug should reproduce; a fixed one should not.
    """
    kind = record.get("kind", "")
    runner = _FAILURE_KINDS.get(kind)
    if runner is None:
        return {"kind": kind, "reproduced": False, "error": f"unknown failure kind {kind!r}",
                "supported": sorted(_FAILURE_KINDS)}
    expected = bool(record.get("expected_violation", True))
    with _forced_enforce():
        try:
            result = runner(record.get("inputs", {}))
        except Exception as exc:
            return {"kind": kind, "reproduced": False, "error": f"{type(exc).__name__}: {exc}"}
    observed = bool(result.violations)
    return {
        "kind": kind,
        "expected_violation": expected,
        "observed_violation": observed,
        "reproduced": observed == expected,
        "violations": _violations(result),
    }


# ── batch / event-log ───────────────────────────────────────────────────────────────
def load_records(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Load replay records from a JSON array file or a JSONL (one object per line)."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] == "[":
        return json.loads(text)
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            with contextlib.suppress(Exception):
                out.append(json.loads(line))
    return out


def replay_batch(records: list[dict[str, Any]], mode: str = "failure") -> dict[str, Any]:
    """Replay a batch of records. ``mode`` is ``failure`` or ``decision``.
    Returns per-record results plus a summary (how many reproduced / would-pass)."""
    fn = replay_failure if mode == "failure" else replay_decision
    results = [fn(r) for r in records]
    if mode == "failure":
        ok = sum(1 for r in results if r.get("reproduced"))
        summary = {"total": len(results), "reproduced": ok, "not_reproduced": len(results) - ok}
    else:
        passes = sum(1 for r in results if r.get("would_pass_today"))
        recon = sum(1 for r in results if r.get("reconstructable"))
        summary = {"total": len(results), "reconstructable": recon, "would_pass_today": passes}
    return {"mode": mode, "summary": summary, "results": results}
