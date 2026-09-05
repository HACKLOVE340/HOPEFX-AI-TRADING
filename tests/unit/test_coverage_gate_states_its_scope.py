# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A coverage percentage that does not state its scope is not a measurement.

CI runs a step called **"Run tests with coverage (full suite, 70% baseline)"**
and nine more called **"Coverage gate - <package> (80% required)"**. Both
numbers are true about the subset `.coveragerc` points at, and neither says what
that subset is.

Measured by `scripts/coverage_scope_report.py`:

    application statements           247,706
    inside [run] source               81,244
    removed by omit, inside source    14,541
    ACTUALLY MEASURED                 66,703   (26.9% of the application)

`api/` (42,229 statements — the largest package in the codebase),
`monetization/`, `payments/`, `security/`, `database/` and `data_layer/` are not
in `source` at all, and the `omit` list removes `risk/manager.py`,
`risk/pre_trade_gate.py`, `execution/engine.py`, `execution/fix_router.py` and
`core/decision/HOPEFXDecisionEngine.py` **from inside** the packages that are
(F221, confirming F105).

F221 reported 34% from raw LOC. The figure above is lower because it counts
statements and subtracts the omit list, which F221 named but did not weigh.

This is F176's shape with a percentage instead of a tick: a number that reads as
a statement about the application and is a statement about a quarter of it. The
fix there was to make the report say what it measured, and it is the fix here.

These tests do not gate the coverage *percentage* — raising `source` to the whole
application would drop it below the CI floor overnight and teach nobody
anything. They gate the *honesty*: the scope is computed from the real config,
reported next to the coverage figure in CI, and cannot silently shrink.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def report():
    from scripts.coverage_scope_report import build_report

    return build_report()


def test_the_report_measures_rather_than_declares(report):
    """Every number comes from walking the tree and parsing `.coveragerc`. A
    hardcoded figure here would be F176 exactly."""
    assert report["total_application_loc"] > 100_000, "the application scan found almost nothing"
    assert report["in_source_loc"] > 0
    assert report["measured_loc"] == report["in_source_loc"] - report["omitted_from_source_loc"]


def test_the_report_subtracts_the_omit_list(report):
    """F221 named the omit list but did not weigh it. It is not a rounding
    error: it removes the risk manager, the pre-trade gate, the execution engine
    and the decision engine from inside packages that ARE measured."""
    assert report["omitted_from_source_loc"] > 1_000, (
        "the omit list weighs nothing, which would mean the risk and execution exclusions are not being counted"
    )


def test_the_scope_is_reported_not_implied(report):
    """The largest unmeasured packages must be named, not left to be discovered."""
    unmeasured = dict(report["unmeasured_packages"])
    assert "api" in unmeasured, "api/ is the biggest package in the repo and must be named as unmeasured"
    assert unmeasured["api"] > 10_000


def test_ci_prints_the_scope_beside_the_coverage_number():
    """A report nobody runs is a report that does not exist — the finding this
    whole phase is about."""
    from pathlib import Path

    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "coverage_scope_report.py" in workflow, (
        "the coverage scope is computed but never printed in CI, so the coverage percentage still stands alone"
    )


def test_the_measured_share_cannot_silently_shrink(report):
    """A floor, not a target. It fails if someone narrows `source` or grows
    `omit` — which is how the scope got here in the first place: every entry in
    that list was added one at a time, each with a reason, and nobody was
    watching the total."""
    assert report["measured_share_pct"] >= 25.0, (
        f"the coverage gate now measures {report['measured_share_pct']}% of the application, "
        "down from 26.9%. Widening `omit` or narrowing `source` needs a deliberate "
        "decision, not a quiet commit."
    )


def test_the_omit_reasons_are_still_true_or_flagged():
    """`.coveragerc` justifies each risk/execution exclusion as 'covered by
    integration tests'. That is a claim, and this file's whole subject is claims
    nobody checks — so at minimum the modules named must still exist. An omit
    entry for a deleted file silently shrinks nothing but proves nobody re-read
    the list."""
    import configparser
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    parser = configparser.ConfigParser()
    parser.read(root / ".coveragerc")
    omit = [s.strip() for s in parser.get("run", "omit", fallback="").splitlines() if s.strip()]

    stale = [pattern for pattern in omit if "*" not in pattern and not (root / pattern).exists()]
    assert not stale, f"`.coveragerc` omits modules that no longer exist — nobody has re-read the list: {stale}"
