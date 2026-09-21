# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_code_analyzer_suppression_is_uniform.py
======================================================
The zero-tolerance gate is fine. Discovering how to satisfy it was not.

``tests/unit/test_fixes.py::TestCodeAnalyzerClean`` requires
``scan_codebase()`` to return **zero** findings across the whole repository.
That is a good forcing function, and it is only workable if a false positive
can be suppressed with an obvious, documented annotation.

It could not. Each rule in ``security/code_analyzer.py`` grew its own
vocabulary:

===================  ==================================================
rule                 accepted markers
===================  ==================================================
null-object          ``# healer: ignore``, ``# noqa: healer``
look-ahead (line)    ``lookahead-ok``, ``# noqa``
bare except          ``nosec``, ``# noqa``
silent except        ``# noqa``, ``# healer: ignore``
look-ahead (block)   ``lookahead-ok``, ``nosec``, ``intentional``, ``# noqa``
nan leak             ``# healer: ignore`` **only**
===================  ==================================================

So ``# noqa`` — the ordinary Python idiom, honoured by four of these — did
nothing for ``nan_leak``. A developer who hit that rule got a CI failure they
could not resolve without reading the analyzer's source, and the natural next
move is to weaken the gate rather than annotate the line.

This bit for real. Adding ``scripts/derive_feature_stats.py`` tripped
``nan_leak`` at HIGH severity on a line whose *preceding* statement was an
explicit ``np.isfinite`` guard — the detector simply did not recognise
``isfinite`` as a NaN guard, only ``isnan``. The right fix there was to teach
the detector (done: ``isfinite`` is strictly stronger, it excludes ±inf too),
but the episode showed the escape hatch was unreachable.

Every rule now shares one suppression predicate, and every previously-accepted
marker keeps working — this widens what is accepted, it never narrows it, so
no line that suppresses today stops suppressing.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

# Every marker any rule historically honoured. A developer should be able to
# reach for whichever one they know and have it work.
_MARKERS = [
    "# noqa",
    "# noqa: healer",
    "# healer: ignore",
    "nosec",
    "lookahead-ok",
    "intentional",
]


def test_the_shared_predicate_exists():
    from security.code_analyzer import _is_suppressed

    assert callable(_is_suppressed)


@pytest.mark.parametrize("marker", _MARKERS)
def test_every_historical_marker_is_honoured(marker):
    from security.code_analyzer import _is_suppressed

    assert _is_suppressed(f"value = np.sqrt(x)  {marker}"), f"{marker!r} no longer suppresses"


def test_an_unannotated_line_is_not_suppressed():
    """The gate must still bite."""
    from security.code_analyzer import _is_suppressed

    assert not _is_suppressed("value = np.sqrt(x)")
    assert not _is_suppressed("        return df.mean()")


def test_a_marker_in_a_string_literal_does_not_suppress():
    """`"# noqa"` inside data is not an annotation on the statement."""
    from security.code_analyzer import _is_suppressed

    assert not _is_suppressed('MESSAGE = "add # noqa to silence this"')


# ── The rule that had no reachable escape hatch ──────────────────────────────


@pytest.fixture
def neutral_dir():
    """A temp dir with no "test" anywhere in its path.

    The analyzer skips test files via ``is_test = "/test" in rel``, and pytest's
    own ``tmp_path`` is ``/tmp/.../test_<function_name>0/`` — which matches. The
    first version of these tests used ``tmp_path``, so the rule never ran at
    all and the "accepts # noqa" case passed without exercising anything.
    """
    import shutil
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp(prefix="analyzer_fixture_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_nan_leak_accepts_noqa(neutral_dir):
    """The concrete failure: `# noqa` did nothing for this rule."""
    from security.code_analyzer import _analyze_file_regex as scan_path

    src = neutral_dir / "m.py"
    src.write_text("import numpy as np\n\n\ndef f(x):\n    return np.sqrt(x)  # noqa\n")

    findings = [i for i in scan_path(src) if i.category == "nan_leak"]
    assert findings == [], f"# noqa still does not suppress nan_leak: {findings}"


def test_nan_leak_still_fires_without_an_annotation(neutral_dir):
    """Control — without this the test above passes by never firing, which is
    exactly what happened before the neutral_dir fixture existed."""
    from security.code_analyzer import _analyze_file_regex as scan_path

    src = neutral_dir / "m.py"
    src.write_text("import numpy as np\n\n\ndef f(x):\n    return np.sqrt(x)\n")

    findings = [i for i in scan_path(src) if i.category == "nan_leak"]
    assert findings, "nan_leak no longer detects an unguarded numeric op"


# ── The gate's message must name the escape hatch ────────────────────────────


def test_the_failure_message_tells_you_how_to_suppress():
    """A developer reading a CI failure should not have to read the analyzer."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "tests" / "unit" / "test_fixes.py").read_text(encoding="utf-8")

    assert "noqa" in src, (
        "TestCodeAnalyzerClean's failure message does not say how to annotate a false positive, "
        "so the only obvious move on a bad finding is to weaken the gate"
    )


def test_the_repo_is_still_clean():
    """The gate itself, unchanged in strictness."""
    from security.code_analyzer import scan_codebase

    issues = scan_codebase()
    assert issues == [], "\n".join(f"  {i.severity} | {i.category} | {i.file}:{i.line}" for i in issues)
