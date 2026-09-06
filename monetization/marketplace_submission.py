# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
monetization/marketplace_submission.py
=======================================
Strategy submission, audit workflow, and approval pipeline.

Flow:
  1. Creator submits strategy (DRAFT → PENDING_REVIEW)
  2. Automated audit runs: syntax check, backtest gate, risk limits
  3. Human reviewer approves/rejects (PENDING_REVIEW → APPROVED/REJECTED)
  4. Approved strategy becomes ACTIVE on marketplace

Audit checks:
  - Python syntax validation
  - Minimum backtest Sharpe >= 1.0
  - Maximum drawdown <= 25%
  - Minimum 100 trades in backtest
  - No forbidden imports (os.system, subprocess, socket, etc.)
"""

from __future__ import annotations

import ast
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


UTC = timezone.utc

logger = logging.getLogger(__name__)

# ── Forbidden imports that disqualify a strategy ─────────────────────────────
#: Modules a marketplace strategy has no business importing.
#:
#: `"exec"` and `"eval"` used to be in here. They are builtins, not modules —
#: `import exec` is a syntax error — so listing them caught nothing while making
#: the gate look as though it covered them. They are handled properly below, as
#: calls.
_FORBIDDEN_MODULES = frozenset(
    {
        "os",
        "subprocess",
        "socket",
        "shutil",
        "ctypes",
        "multiprocessing",
        "threading",
        "importlib",
        "builtins",
        "pickle",
        "marshal",
        "pty",
    }
)

#: Builtins that turn "some source code" into "arbitrary code or file access".
#: The old check walked import statements only, so every one of these was
#: auto-approved: `__import__('os').system(...)`, `eval(x)`, `exec(payload)`.
_FORBIDDEN_CALLS = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "globals",
        "vars",
    }
)

#: Attribute and string names that exist to reach out of an object graph.
#: `().__class__.__bases__[0].__subclasses__()` is the classic route from a
#: literal to every loaded class, and `f.__globals__` reaches the module's
#: namespace. Defining `__init__` or `__repr__` is not on this list: writing a
#: class is not an escape.
_ESCAPE_ATTRIBUTES = frozenset(
    {
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__mro__",
        "__bases__",
        "__reduce__",
        "__reduce_ex__",
        "__getattribute__",
        "__import__",
        "__dict__",
        "__closure__",
        "__func__",
        "__self__",
    }
)


class AuditStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class SubmissionStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    UNDER_AUDIT = "under_audit"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


@dataclass
class AuditCheck:
    name: str
    passed: bool
    message: str
    severity: str = "error"  # "error" | "warning" | "info"


@dataclass
class AuditReport:
    submission_id: str
    status: AuditStatus
    checks: list[AuditCheck] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    reviewer_id: str | None = None
    reviewer_notes: str = ""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "error")

    def to_dict(self) -> dict:
        return {
            "submission_id": self.submission_id,
            "status": self.status.value,
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "message": c.message,
                    "severity": c.severity,
                }
                for c in self.checks
            ],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "reviewer_id": self.reviewer_id,
            "reviewer_notes": self.reviewer_notes,
        }


@dataclass
class StrategySubmission:
    submission_id: str
    creator_id: str
    name: str
    description: str
    strategy_code: str
    backtest_results: dict
    price_monthly: float
    price_yearly: float
    category: str
    tags: list[str]
    status: SubmissionStatus = SubmissionStatus.DRAFT
    audit_report: AuditReport | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "submission_id": self.submission_id,
            "creator_id": self.creator_id,
            "name": self.name,
            "description": self.description,
            "price_monthly": self.price_monthly,
            "price_yearly": self.price_yearly,
            "category": self.category,
            "tags": self.tags,
            "status": self.status.value,
            "audit_report": self.audit_report.to_dict() if self.audit_report else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "rejection_reason": self.rejection_reason,
        }


class StrategyAuditor:
    """Automated strategy audit engine."""

    # Minimum quality gates
    MIN_SHARPE = 1.0
    MAX_DRAWDOWN = 0.25
    MIN_TRADES = 100

    def run_audit(self, submission: StrategySubmission) -> AuditReport:
        report = AuditReport(
            submission_id=submission.submission_id,
            status=AuditStatus.RUNNING,
        )

        report.checks.append(self._check_syntax(submission.strategy_code))
        report.checks.append(self._check_forbidden_imports(submission.strategy_code))
        report.checks.append(self._check_containment(submission.strategy_code))
        report.checks.append(self._check_sharpe(submission.backtest_results))
        report.checks.append(self._check_drawdown(submission.backtest_results))
        report.checks.append(self._check_trade_count(submission.backtest_results))
        report.checks.append(self._check_description(submission.description))
        report.checks.append(self._check_pricing(submission.price_monthly))

        report.completed_at = datetime.now(UTC)
        report.status = AuditStatus.PASSED if report.passed else AuditStatus.FAILED
        return report

    def _check_syntax(self, code: str) -> AuditCheck:
        try:
            ast.parse(code)
            return AuditCheck("syntax_check", True, "Strategy code is syntactically valid")
        except SyntaxError as e:
            return AuditCheck("syntax_check", False, f"Syntax error: {e}", "error")

    def _check_forbidden_imports(self, code: str) -> AuditCheck:
        """Refuse the obvious routes from submitted source to arbitrary execution.

        **A filter, not containment.** A static check on adversarial source can
        always be worked around; what it buys is that the obvious attempts do
        not sail through an *automatic* approval, which is what this gate grants
        with no human in the path. Real containment is `ai/sandbox/`, which runs
        code under rlimits with no network and a scrubbed environment. The two
        are complementary and neither replaces the other.

        It used to walk import statements only, so `__import__('os').system()`,
        `eval(x)` and `exec(payload)` were all approved for sale.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return AuditCheck("security_check", False, "Cannot parse code", "error")

        found: set[str] = set()
        for node in ast.walk(tree):
            # 1. Imports — what this check used to look at, and only this.
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    root = name.split(".")[0]
                    if root in _FORBIDDEN_MODULES:
                        found.add(f"import {root}")

            # 2. Calls to builtins that execute code or touch the filesystem.
            #    `__import__('os')` is not an import node, which is how it
            #    reached APPROVED.
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in _FORBIDDEN_CALLS:
                    found.add(f"{node.func.id}()")

            # 3. Attribute routes out of the object graph.
            elif isinstance(node, ast.Attribute) and node.attr in _ESCAPE_ATTRIBUTES:
                found.add(f".{node.attr}")

            # 4. The same names reached as strings, e.g.
            #    `getattr(builtins, "__import__")`.
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in _ESCAPE_ATTRIBUTES or node.value in _FORBIDDEN_CALLS:
                    found.add(f"{node.value!r}")

        if found:
            return AuditCheck(
                "security_check",
                False,
                f"Forbidden constructs detected: {', '.join(sorted(found))}",
                "error",
            )
        return AuditCheck("security_check", True, "No forbidden imports or code-execution constructs found")

    #: A submission is executed under containment for no longer than this. A
    #: strategy that cannot import and define itself in a few seconds is not a
    #: strategy this audit can vouch for.
    CONTAINMENT_TIMEOUT_S = 15.0

    def _check_containment(self, code: str) -> AuditCheck:
        """Run the submission under real containment before approving it.

        `ai/sandbox/` had zero production callers. Until this, the only thing
        in front of strategy source submitted by a stranger was the static
        screen above — which says in its own docstring that it is "a filter,
        not containment", and names this sandbox as the containment it needs.
        The code identified the gap and nothing routed to it.

        The screen is NOT replaced. `sandbox.run()` calls it as a pre-filter so
        an obvious payload is refused before a process is spawned, and the
        containment guarantees are tested with the screen off so neither layer
        is load-bearing alone.

        **An unavailable sandbox FAILS the submission.** No `resource` module,
        a platform that cannot fork, any error at all — "we could not contain
        this" must never resolve to "approved for sale". This gate grants
        automatic approval with no human in the path, so the safe direction is
        the only defensible one.
        """
        try:
            from ai.sandbox import runner
        except Exception as exc:
            return AuditCheck(
                "containment_check",
                False,
                f"Sandbox unavailable ({exc}); refusing to approve uncontained code",
                "error",
            )

        try:
            result = runner.run(code, timeout_s=self.CONTAINMENT_TIMEOUT_S, net=False)
        except Exception as exc:
            logger.warning("marketplace: containment run failed (%s)", exc)
            return AuditCheck(
                "containment_check",
                False,
                f"Could not run the submission under containment ({exc})",
                "error",
            )

        if not getattr(result, "ok", False):
            codes = ", ".join(getattr(result, "reason_codes", ()) or ()) or "refused"
            return AuditCheck(
                "containment_check",
                False,
                f"Submission refused by the sandbox: {codes}",
                "error",
            )
        return AuditCheck("containment_check", True, "Submission ran under containment without incident")

    def _check_sharpe(self, bt: dict) -> AuditCheck:
        sharpe = float(bt.get("sharpe_ratio", 0))
        if sharpe >= self.MIN_SHARPE:
            return AuditCheck("sharpe_gate", True, f"Sharpe {sharpe:.2f} >= {self.MIN_SHARPE}")
        return AuditCheck(
            "sharpe_gate",
            False,
            f"Sharpe {sharpe:.2f} below minimum {self.MIN_SHARPE}",
            "error",
        )

    def _check_drawdown(self, bt: dict) -> AuditCheck:
        dd = abs(float(bt.get("max_drawdown", 1.0)))
        if dd <= self.MAX_DRAWDOWN:
            return AuditCheck(
                "drawdown_gate",
                True,
                f"Max drawdown {dd:.1%} <= {self.MAX_DRAWDOWN:.0%}",
            )
        return AuditCheck(
            "drawdown_gate",
            False,
            f"Max drawdown {dd:.1%} exceeds limit {self.MAX_DRAWDOWN:.0%}",
            "error",
        )

    def _check_trade_count(self, bt: dict) -> AuditCheck:
        trades = int(bt.get("total_trades", 0))
        if trades >= self.MIN_TRADES:
            return AuditCheck("trade_count", True, f"{trades} trades >= minimum {self.MIN_TRADES}")
        return AuditCheck(
            "trade_count",
            False,
            f"Only {trades} trades — minimum {self.MIN_TRADES} required",
            "error",
        )

    def _check_description(self, desc: str) -> AuditCheck:
        if len(desc.strip()) >= 100:
            return AuditCheck("description", True, "Description meets minimum length")
        return AuditCheck(
            "description",
            False,
            f"Description too short ({len(desc)} chars, minimum 100)",
            "warning",
        )

    def _check_pricing(self, price: float) -> AuditCheck:
        if price >= 0:
            return AuditCheck("pricing", True, f"Price ${price:.2f} is valid")
        return AuditCheck("pricing", False, "Price cannot be negative", "error")


class SubmissionManager:
    """Manages the full strategy submission and approval lifecycle."""

    def __init__(self) -> None:
        self._submissions: dict[str, StrategySubmission] = {}
        self._auditor = StrategyAuditor()

    def submit(
        self,
        creator_id: str,
        name: str,
        description: str,
        strategy_code: str,
        backtest_results: dict,
        price_monthly: float,
        price_yearly: float,
        category: str = "algorithmic",
        tags: list[str] | None = None,
    ) -> StrategySubmission:
        sub = StrategySubmission(
            submission_id=str(uuid.uuid4()),
            creator_id=creator_id,
            name=name,
            description=description,
            strategy_code=strategy_code,
            backtest_results=backtest_results,
            price_monthly=price_monthly,
            price_yearly=price_yearly,
            category=category,
            tags=tags or [],
            status=SubmissionStatus.PENDING_REVIEW,
        )
        self._submissions[sub.submission_id] = sub
        logger.info("Strategy submitted: %s by %s", name, creator_id)

        # Run automated audit immediately
        sub.status = SubmissionStatus.UNDER_AUDIT
        report = self._auditor.run_audit(sub)
        sub.audit_report = report
        sub.updated_at = datetime.now(UTC)

        if report.passed:
            sub.status = SubmissionStatus.APPROVED
            logger.info("Strategy auto-approved: %s", sub.submission_id)
        else:
            sub.status = SubmissionStatus.REJECTED
            sub.rejection_reason = "; ".join(c.message for c in report.checks if not c.passed and c.severity == "error")
            logger.warning("Strategy rejected: %s — %s", sub.submission_id, sub.rejection_reason)

        return sub

    def manual_approve(self, submission_id: str, reviewer_id: str, notes: str = "") -> bool:
        sub = self._submissions.get(submission_id)
        if not sub:
            return False
        sub.status = SubmissionStatus.APPROVED
        sub.updated_at = datetime.now(UTC)
        if sub.audit_report:
            sub.audit_report.reviewer_id = reviewer_id
            sub.audit_report.reviewer_notes = notes
            sub.audit_report.status = AuditStatus.PASSED
        logger.info("Strategy manually approved: %s by %s", submission_id, reviewer_id)
        return True

    def manual_reject(self, submission_id: str, reviewer_id: str, reason: str) -> bool:
        sub = self._submissions.get(submission_id)
        if not sub:
            return False
        sub.status = SubmissionStatus.REJECTED
        sub.rejection_reason = reason
        sub.updated_at = datetime.now(UTC)
        if sub.audit_report:
            sub.audit_report.reviewer_id = reviewer_id
            sub.audit_report.status = AuditStatus.FAILED
        return True

    def get(self, submission_id: str) -> StrategySubmission | None:
        return self._submissions.get(submission_id)

    def list_by_creator(self, creator_id: str) -> list[StrategySubmission]:
        return [s for s in self._submissions.values() if s.creator_id == creator_id]

    def list_pending(self) -> list[StrategySubmission]:
        return [s for s in self._submissions.values() if s.status == SubmissionStatus.PENDING_REVIEW]


# Module-level singleton
submission_manager = SubmissionManager()
