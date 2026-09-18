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


#: The modules F105 and §E49 fought to get measured. `.coveragerc` once removed
#: each of these from inside a package that IS measured, so "risk/ >= 80%" was a
#: true statement about the part of risk/ that does not move money.
SAFETY_MODULES_THAT_MUST_STAY_MEASURED = (
    "risk/manager.py",
    "risk/pre_trade_gate.py",
    "execution/engine.py",
    "execution/fix_router.py",
    "core/decision/HOPEFXDecisionEngine.py",
)


def _omit_patterns() -> list[str]:
    """The omit list as coverage.py sees it — comments stripped by configparser."""
    import configparser
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    parser = configparser.ConfigParser()
    parser.read(root / ".coveragerc")
    return [s.strip() for s in parser.get("run", "omit", fallback="").splitlines() if s.strip()]


def test_the_safety_modules_are_not_omitted():
    """The code that moves money stays inside the gate that guards it.

    This replaces `test_the_report_subtracts_the_omit_list`, which asserted
    `omitted_from_source_loc > 1_000`. That was a proxy, written while the
    exclusions were live, for "the exclusions are being counted". §E49 lifted
    them on 2026-09-10, the weight fell to 806, and the proxy went red — while
    the defect it stood for had been *fixed*. Read literally it required that
    over a thousand statements of in-source code stay hidden from the gate,
    which is the defect rather than the requirement.

    Matched with fnmatch, not equality: `risk/*` hides `risk/manager.py` just
    as effectively as naming it, and an assertion that only checks for the
    literal string is one rename away from proving nothing.
    """
    from fnmatch import fnmatch

    patterns = _omit_patterns()
    hidden = {
        module: [p for p in patterns if fnmatch(module, p) or fnmatch(module, p.lstrip("*/"))]
        for module in SAFETY_MODULES_THAT_MUST_STAY_MEASURED
    }
    hidden = {m: p for m, p in hidden.items() if p}
    assert not hidden, (
        "`.coveragerc` omits code on the money path, so its coverage figure is a "
        f"statement about everything except the dangerous part: {hidden}. "
        "F105 and §E49 removed these exclusions deliberately; re-adding one needs "
        "an owner decision, not a quiet commit."
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
