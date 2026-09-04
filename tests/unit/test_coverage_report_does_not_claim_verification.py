# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The safety scorecard must not report a verification it never performed.

`scripts/invariant_coverage.py` is the operator-facing safety report. On the
current tree it printed:

    Critical-component coverage:
       ✅ protected    12/12
       ✅ monitored    12/12
       ✅ alerted      12/12
    ...
    FULL COVERAGE ✅

**Every one of those values is a hand-typed `True`** in
`invariants/registry.py`'s `CRITICAL_COMPONENTS`. `coverage_counts()` counts how
many dict entries say `True`. It inspects no code, calls no predicate and probes
no component, so the report cannot return anything other than a near-perfect
score — a literal cannot fail (F176).

Set against this audit's own findings, the claim was measurably false while it
was being printed: `market_data_feed` was marked protected while
`execution/engine.py` skipped the data-layer gate in exactly the condition it
existed for (F84); `order_execution` was marked protected while the active paper
path had no risk layer at all (F142); `kill_switch` was marked alerted while
critical alerts never left the log (F159).

Real probes for twelve components are a project. What is not acceptable in the
meantime is a report that reads as verification. The manifest is a legitimate
*declaration* of intent; only the claim was false.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _render() -> str:
    """Capture the human-readable report."""
    import contextlib
    import io

    from scripts import invariant_coverage

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # argv passed explicitly: main() reading sys.argv would parse
        # pytest's own arguments, exit 2, and hand every assertion below an
        # empty string to pass against.
        try:
            invariant_coverage.main([])
        except SystemExit:
            pass
    return buf.getvalue()


def test_the_report_never_claims_full_coverage():
    """The headline. 'FULL COVERAGE' from hand-typed literals is the finding."""
    assert "FULL COVERAGE" not in _render()


def test_the_report_says_the_matrix_is_declared_not_measured():
    out = _render().lower()
    assert "declared" in out, "the report does not distinguish a declaration from a measurement"


def test_the_report_states_that_nothing_was_probed():
    """An operator must not have to know how coverage_counts() works to read
    this correctly."""
    out = _render().lower()
    assert "not verified" in out or "no probe" in out or "unverified" in out


def test_the_report_does_not_use_a_tick_for_a_declaration():
    """A green tick beside a hand-typed True is the whole problem: it reads as
    a passed check."""
    out = _render()
    declared_section = out.split("Critical components")[0]
    assert "✅" not in declared_section, "a declaration is rendered as a passed check"


def test_the_declared_counts_are_still_reported():
    """The manifest is a legitimate statement of intent and remains useful.
    Only the claim of verification was false -- the fix must not delete the
    information."""
    out = _render()
    assert "12" in out


def test_coverage_counts_still_returns_the_declared_counts():
    """meta.verify_*_coverage consumes these; the fix is to the report's
    language, not to the registry's data."""
    from invariants.registry import CRITICAL_COMPONENTS, coverage_counts

    counts = coverage_counts()
    total = len(CRITICAL_COMPONENTS)
    for dim in ("protected", "monitored", "alerted", "recoverable"):
        covered, reported_total = counts[dim]
        assert reported_total == total
        assert 0 <= covered <= total


def test_the_registry_figures_are_real_and_labelled_as_such():
    """The predicate count IS measured -- registry.discover_predicates() walks
    the package. Reporting measured and declared facts side by side is how a
    reader can tell them apart."""
    from invariants.registry import registry_summary

    summary = registry_summary()
    assert summary["predicates"] > 0
    out = _render()
    assert str(summary["predicates"]) in out


def test_the_exit_code_does_not_signal_success_for_a_declaration(monkeypatch):
    """A CI job gating on this must not read 'nobody has checked' as 'passed'."""
    from scripts import invariant_coverage

    report = invariant_coverage.build_report()
    assert "declared" in str(report).lower() or "verified" in str(report).lower(), (
        "the machine-readable report gives a consumer no way to tell that the component matrix is a declaration"
    )


def test_the_report_names_which_components_are_actually_probed():
    """The gap between declared and checked has to be visible, not implied.
    Right now the honest answer is 'none' -- which is exactly what has to be
    printed until a probe exists."""
    from scripts.invariant_coverage import PROBED_COMPONENTS

    out = _render()
    assert "Probed for real" in out
    if not PROBED_COMPONENTS:
        assert "none of the" in out
    else:
        for name in PROBED_COMPONENTS:
            assert name in out
