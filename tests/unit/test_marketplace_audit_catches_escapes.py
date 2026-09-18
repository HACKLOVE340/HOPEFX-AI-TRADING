"""F222 (TODO item 5) — the marketplace's code audit auto-approved escapes.

`monetization/marketplace_submission.py` is 354 lines named by no test, and it
is a code-review gate: it takes strategy code from a creator, audits it, and on
a pass sets the submission to APPROVED for sale — automatically, with no human
in the path.

Its security check walked the AST for `import` statements against a blocklist.
Measured before the fix, every one of these was **auto-approved**:

    __import__('os').system('id')            security_check passed, APPROVED
    def run(x): return eval(x)               security_check passed, APPROVED
    def run(p): exec(p)                      security_check passed, APPROVED
    getattr(builtins, '__import__')('os')    security_check passed, APPROVED

Only a literal `import os` was caught. The blocklist itself is the tell: it
contains the strings `"exec"` and `"eval"`, which can never appear as a module
name — `import exec` is a syntax error. Listing them made the gate look like it
covered them.

**This is a filter, not containment**, and the fix does not pretend otherwise.
A static check on adversarial source can always be worked around; what it buys
is that the obvious attempts do not sail through an *automatic* approval. Real
containment is `ai/sandbox/`, which runs code under rlimits with no network and
a scrubbed environment. The two are complementary and neither replaces the
other.
"""

from __future__ import annotations

import sys

import pytest


def _module():
    import monetization.marketplace_submission  # noqa: F401

    return sys.modules["monetization.marketplace_submission"]


_MOD = _module()
SubmissionManager = _MOD.SubmissionManager
SubmissionStatus = _MOD.SubmissionStatus

#: Backtest numbers that pass every non-security gate, so the security check is
#: the only thing standing between the code and an automatic approval.
CLEAN_BACKTEST = {"sharpe_ratio": 2.0, "max_drawdown": 0.05, "total_trades": 100}
LONG_DESCRIPTION = "A description long enough to satisfy the hundred-character minimum gate. " * 3


@pytest.fixture
def manager():
    return SubmissionManager()


def _submit(manager, code: str):
    return manager.submit(
        creator_id="creator-1",
        name="Strategy",
        description=LONG_DESCRIPTION,
        strategy_code=code,
        backtest_results=CLEAN_BACKTEST,
        price_monthly=10.0,
        price_yearly=100.0,
    )


def _security_check(submission):
    return next(check for check in submission.audit_report.checks if check.name == "security_check")


# ── the escapes that were auto-approved ──────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "code"),
    [
        ("dunder import", "mod = __import__('os')\nmod.system('id')\n"),
        ("eval", "def run(x):\n    return eval(x)\n"),
        ("exec", "def run(payload):\n    exec(payload)\n"),
        ("compile", "def run(src):\n    return compile(src, '<s>', 'exec')\n"),
        ("builtins getattr", "import builtins\ng = getattr(builtins, '__import__')('os')\n"),
        ("subclasses walk", "esc = ().__class__.__bases__[0].__subclasses__()\n"),
        ("function globals", "def f():\n    pass\nleak = f.__globals__\n"),
        ("builtins dict", "leak = [].__class__.__mro__[1].__dict__\n"),
        ("open a file", "def run():\n    return open('/etc/passwd').read()\n"),
    ],
    ids=lambda value: value if isinstance(value, str) and " " in value else "",
)
def test_an_escape_is_not_auto_approved(manager, label: str, code: str) -> None:
    submission = _submit(manager, code)

    assert _security_check(submission).passed is False, f"{label} passed the security check"
    assert submission.status is SubmissionStatus.REJECTED, f"{label} was auto-approved for sale"


def test_a_plain_forbidden_import_is_still_caught(manager) -> None:
    """The one case that already worked must keep working."""
    submission = _submit(manager, "import os\n")

    assert _security_check(submission).passed is False
    assert submission.status is SubmissionStatus.REJECTED


def test_the_rejection_names_what_was_found(manager) -> None:
    """A creator has to be able to fix it, and a reviewer to audit the decision."""
    submission = _submit(manager, "def run(x):\n    return eval(x)\n")

    assert "eval" in _security_check(submission).message
    assert "eval" in (submission.rejection_reason or "")


# ── legitimate strategy code still passes ────────────────────────────────────


def test_ordinary_strategy_code_is_approved(manager) -> None:
    """A gate that refuses everything is not a fix."""
    code = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "\n"
        "class GeneratedStrategy:\n"
        "    def __init__(self, lookback: int = 20) -> None:\n"
        "        self.lookback = lookback\n"
        "\n"
        "    def signal(self, frame: pd.DataFrame) -> float:\n"
        "        fast = frame['close'].rolling(self.lookback).mean()\n"
        "        slow = frame['close'].rolling(self.lookback * 3).mean()\n"
        "        return float(np.sign(fast.iloc[-1] - slow.iloc[-1]))\n"
    )
    submission = _submit(manager, code)

    assert _security_check(submission).passed is True
    assert submission.status is SubmissionStatus.APPROVED


def test_defining_dunder_methods_is_not_an_escape(manager) -> None:
    """`__init__` and `__repr__` are how classes are written, not an attack."""
    code = (
        "class GeneratedStrategy:\n"
        "    def __init__(self) -> None:\n"
        "        self.state = 0\n"
        "\n"
        "    def __repr__(self) -> str:\n"
        "        return 'GeneratedStrategy()'\n"
        "\n"
        "    def __len__(self) -> int:\n"
        "        return 1\n"
    )
    submission = _submit(manager, code)

    assert _security_check(submission).passed is True


def test_the_blocklist_no_longer_lists_things_that_cannot_be_imported() -> None:
    """`import exec` is a syntax error. Listing it made the gate look wider."""
    assert "exec" not in _MOD._FORBIDDEN_MODULES
    assert "eval" not in _MOD._FORBIDDEN_MODULES
    assert "os" in _MOD._FORBIDDEN_MODULES


# ── the rest of the gate, previously untested ────────────────────────────────


def test_unparseable_code_is_rejected(manager) -> None:
    submission = _submit(manager, "def broken(:\n")

    assert submission.status is SubmissionStatus.REJECTED


@pytest.mark.parametrize(
    ("backtest", "failing_check"),
    [
        ({"sharpe_ratio": 0.1, "max_drawdown": 0.05, "total_trades": 100}, "sharpe_gate"),
        ({"sharpe_ratio": 2.0, "max_drawdown": 0.9, "total_trades": 100}, "drawdown_gate"),
        ({"sharpe_ratio": 2.0, "max_drawdown": 0.05, "total_trades": 1}, "trade_count"),
    ],
    ids=["sharpe", "drawdown", "trade_count"],
)
def test_a_failing_performance_gate_rejects(manager, backtest: dict, failing_check: str) -> None:
    submission = manager.submit(
        creator_id="creator-1",
        name="Strategy",
        description=LONG_DESCRIPTION,
        strategy_code="x = 1\n",
        backtest_results=backtest,
        price_monthly=10.0,
        price_yearly=100.0,
    )

    failed = {check.name for check in submission.audit_report.checks if not check.passed}
    assert failing_check in failed
    assert submission.status is SubmissionStatus.REJECTED


def test_a_short_description_warns_but_does_not_reject(manager) -> None:
    """Severity is load-bearing: only "error" checks decide the outcome."""
    submission = manager.submit(
        creator_id="creator-1",
        name="Strategy",
        description="too short",
        strategy_code="x = 1\n",
        backtest_results=CLEAN_BACKTEST,
        price_monthly=10.0,
        price_yearly=100.0,
    )

    description_check = next(c for c in submission.audit_report.checks if c.name == "description")
    assert description_check.passed is False
    assert description_check.severity == "warning"
    assert submission.status is SubmissionStatus.APPROVED
