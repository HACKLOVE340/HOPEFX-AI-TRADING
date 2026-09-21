"""D1 — the strategy execution gate must not be disabled by its own default.

`StrategyExecutionBoundary.evaluate` short-circuited `ExecutionScope.RESEARCH`
to allowed=True before any check, and both call sites defaulted to that scope:

    DynamicStrategyRegistry.activate_strategy(version_id, scope=ExecutionScope.RESEARCH, ...)
    StrategyOrchestra.activate_ai_strategy(strategy_id, scope=ExecutionScope.RESEARCH, ...)

Every production caller omits the argument (api/dynamic_strategies.py x3,
api/nocode.py, api/brain.py), so the gate returned allowed=True for a candidate
with no validation, no evidence and no approval — and the caller then set
StrategyState.ACTIVE, a real activation. The scope argument described what the
caller claimed, not what happened.

These tests pin the two properties that close it: research scope is not a
blanket allow, and the scope must be stated by the caller rather than defaulted.
"""

import inspect

import pytest

from core.ai_contracts import HumanApproval, ResearchCandidate, StrategyLifecycle, ValidationReport
from ml.research_validation_gate import evaluate_research_validation
from strategies.strategy_execution_boundary import (
    ExecutionScope,
    StrategyExecutionBoundary,
)


def _bare_candidate() -> ResearchCandidate:
    """The weakest possible candidate: no validation, no evidence, no approval."""
    return ResearchCandidate(
        candidate_id="c1",
        name="n",
        source_hash="s",
        skill_version="v",
        prompt_hash="p",
        data_scope="d",
    )


def _passing_evidence():
    return evaluate_research_validation(
        replay_ok=True,
        walk_forward_ok=True,
        leakage_check_ok=True,
        slippage_costs_ok=True,
        model_quality_ok=True,
    )


# ── the escape hatch ──────────────────────────────────────────────────────────


def test_research_scope_is_not_a_blanket_allow() -> None:
    decision = StrategyExecutionBoundary().evaluate(_bare_candidate(), ExecutionScope.RESEARCH)
    assert not decision.allowed, "research scope short-circuits every check"
    assert decision.reason_code == "RESEARCH_LIFECYCLE_REQUIRED"


def test_research_scope_allows_a_candidate_that_is_actually_in_research() -> None:
    """Research work is still permitted — the gate checks, it does not forbid."""
    candidate = _bare_candidate()
    assert candidate.lifecycle is StrategyLifecycle.RESEARCH
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.RESEARCH, research_only=True)
    assert decision.allowed
    assert decision.reason_code == "RESEARCH_ALLOWED"


def test_a_promoted_candidate_cannot_be_activated_under_research_scope() -> None:
    """The bypass in production: a live-approved candidate waved through as 'research'."""
    report = ValidationReport(passed=True, checks={"replay": True})
    candidate = (
        ResearchCandidate(
            candidate_id="c1",
            name="n",
            source_hash="s",
            skill_version="v",
            prompt_hash="p",
            data_scope="d",
            validation=report,
        )
        .attach_research_validation(_passing_evidence())
        .transition(StrategyLifecycle.VALIDATED)
        .transition(StrategyLifecycle.PAPER_PENDING)
    )
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.RESEARCH)
    assert not decision.allowed, "a promoted candidate must not activate as research"


# ── the default argument ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("module", "cls", "method"),
    [
        ("strategies.dynamic_registry", "DynamicStrategyRegistry", "activate_strategy"),
        ("core.strategy_orchestra", "StrategyOrchestra", "activate_ai_strategy"),
    ],
)
def test_activation_requires_an_explicitly_declared_scope(module: str, cls: str, method: str) -> None:
    import importlib

    fn = getattr(getattr(importlib.import_module(module), cls), method)
    param = inspect.signature(fn).parameters["scope"]
    assert param.default is inspect.Parameter.empty, (
        f"{cls}.{method} defaults its scope; a default is what disabled this gate"
    )
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
        f"{cls}.{method} takes scope positionally; keyword-only makes the claim explicit at the call site"
    )


def test_no_production_caller_omits_the_scope() -> None:
    """The defect was never in the gate alone -- it was that nobody passed a scope.

    Parsed with AST rather than grepped: `dynamic_registry.py` mentions
    `activate_strategy()` twice in prose, and a regex over source treats a
    docstring as a call site (audit finding F255).

    Scoped to the two gated methods. `StrategyOrchestra.activate_strategy` is
    the legacy non-AI path -- it takes no candidate and reaches no boundary --
    so it is deliberately not covered here.
    """
    import ast
    import pathlib

    GATED = {"activate_ai_strategy"}
    offenders: list[str] = []
    for path in sorted(pathlib.Path().glob("[abcdefghijklmnopqrstuvwxyz]*/**/*.py")):
        parts = path.parts
        if parts[0] in {"tests", "scripts", "docs"} or ".venv" in parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            receiver = ast.unparse(node.func.value)
            gated = attr in GATED or (attr == "activate_strategy" and receiver.endswith("registry"))
            if not gated:
                continue
            if not any(kw.arg == "scope" for kw in node.keywords):
                offenders.append(f"{path}:{node.lineno}  {ast.unparse(node)[:90]}")
    assert not offenders, "activation call sites that declare no scope:\n" + "\n".join(offenders)


# ── paper and live still gated ────────────────────────────────────────────────


def test_paper_and_live_still_require_evidence() -> None:
    boundary = StrategyExecutionBoundary()
    for scope in (ExecutionScope.PAPER, ExecutionScope.LIVE):
        decision = boundary.evaluate(_bare_candidate(), scope)
        assert not decision.allowed
        assert decision.reason_code == "VALIDATION_REQUIRED"


def test_live_still_requires_a_live_scoped_approval() -> None:
    report = ValidationReport(passed=True, checks={"replay": True})
    candidate = (
        ResearchCandidate(
            candidate_id="c1",
            name="n",
            source_hash="s",
            skill_version="v",
            prompt_hash="p",
            data_scope="d",
            validation=report,
        )
        .attach_research_validation(_passing_evidence())
        .transition(StrategyLifecycle.VALIDATED)
    )
    paper_approval = HumanApproval(approver_id="op-1", scope="paper")
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.LIVE, paper_approval)
    assert not decision.allowed
    assert decision.reason_code == "LIVE_APPROVAL_REQUIRED"


# ── D2: the research-evidence hash must be backed by real evidence ────────────


def test_a_forged_evidence_hash_cannot_promote() -> None:
    """`research_validation_hash` was a free string with no production writer.

    The gate required only that it be non-empty, while its reason code claimed
    replay, walk-forward, leakage, slippage and model quality had all passed —
    and `evaluate_research_validation`, which computes that, had no caller
    outside its own test. The string "x" satisfied it.
    """
    forged = ResearchCandidate(
        candidate_id="c",
        name="n",
        source_hash="s",
        skill_version="v",
        prompt_hash="p",
        data_scope="d",
        validation=ValidationReport(passed=True, checks={"x": True}),
        research_validation_hash="x",
    ).transition(StrategyLifecycle.VALIDATED)

    with pytest.raises(ValueError, match="research validation evidence"):
        forged.transition(StrategyLifecycle.PAPER_PENDING)

    decision = StrategyExecutionBoundary().evaluate(forged, ExecutionScope.PAPER)
    assert not decision.allowed
    assert decision.reason_code == "RESEARCH_VALIDATION_REQUIRED"


def test_failing_evidence_cannot_be_attached() -> None:
    failing = evaluate_research_validation(
        replay_ok=True,
        walk_forward_ok=False,
        leakage_check_ok=True,
        slippage_costs_ok=True,
        model_quality_ok=True,
    )
    assert not failing.passed
    with pytest.raises(ValueError, match="walk_forward_failed"):
        _bare_candidate().attach_research_validation(failing)


def test_genuine_evidence_promotes() -> None:
    """The gate must still permit the legitimate path, or it is just a wall."""
    candidate = (
        ResearchCandidate(
            candidate_id="c",
            name="n",
            source_hash="s",
            skill_version="v",
            prompt_hash="p",
            data_scope="d",
            validation=ValidationReport(passed=True, checks={"x": True}),
        )
        .attach_research_validation(_passing_evidence())
        .transition(StrategyLifecycle.VALIDATED)
    )
    assert candidate.transition(StrategyLifecycle.PAPER_PENDING).lifecycle is (StrategyLifecycle.PAPER_PENDING)
