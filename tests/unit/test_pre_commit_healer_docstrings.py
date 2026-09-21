# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_pre_commit_healer_docstrings.py
================================================
The placeholder hook flagged prose as a hardcoded credential.

``scripts/pre_commit_healer.py`` blocks commits containing ``CHANGE_ME`` and
friends, and already meant to exempt docstrings — its own comment says "skip
lines that are inside comments explaining what to change". It implemented that
as ``stripped.startswith('\"\"\"')``, which only ever matches the line that
*opens* a docstring. So a placeholder named on a docstring's first line was
exempt and the identical word three lines further down was reported as a
hardcoded credential.

That surfaced while documenting the placeholder-validation fix: the docstring
explaining which secret had been accepted was itself blocked as a secret.

The fix is an AST-derived set of docstring line spans. These tests exist because
the change loosens a security-relevant hook, so the exemption has to be shown to
stop at docstrings — an ordinary assigned string containing a placeholder is
still a finding, which is the case the hook exists for.
"""

from __future__ import annotations

import importlib.util
import pathlib
import textwrap

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _healer():
    spec = importlib.util.spec_from_file_location("_healer", _ROOT / "scripts/pre_commit_healer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _check(tmp_path: pathlib.Path, source: str, name: str = "sample.py") -> list[str]:
    path = tmp_path / name
    path.write_text(textwrap.dedent(source))
    return _healer().check_file(path)


def _placeholder_issues(issues: list[str]) -> list[str]:
    return [i for i in issues if "hardcoded placeholder" in i]


# ── The regression ───────────────────────────────────────────────────────────


def test_a_placeholder_on_a_later_docstring_line_is_not_a_finding(tmp_path):
    """The exact shape that blocked the commit."""
    issues = _check(
        tmp_path,
        '''
        def is_placeholder(value: str) -> bool:
            """True when *value* is an unreplaced example placeholder.

            ``CHANGE_ME_generate_64_char_hex_secret`` is 37 characters, so it
            cleared the length floor and passed.
            """
            return value.startswith("X")
        ''',
    )
    assert _placeholder_issues(issues) == []


def test_the_opening_line_was_already_exempt_and_still_is(tmp_path):
    """Establishes the inconsistency this fixes: same word, same docstring."""
    issues = _check(tmp_path, '"""CHANGE_ME on the opening line."""\n')
    assert _placeholder_issues(issues) == []


@pytest.mark.parametrize(
    "source",
    [
        '"""Module docstring.\n\nCHANGE_ME on a later line.\n"""\n',
        'class C:\n    """Class docstring.\n\n    CHANGE_ME here.\n    """\n',
        'async def f():\n    """Async docstring.\n\n    CHANGE_ME here.\n    """\n',
    ],
    ids=["module", "class", "async-function"],
)
def test_every_docstring_kind_is_covered(tmp_path, source):
    assert _placeholder_issues(_check(tmp_path, source)) == []


# ── The exemption stops at docstrings ────────────────────────────────────────


def test_a_real_hardcoded_placeholder_is_still_blocked(tmp_path):
    """The case the hook exists for. If this passes, the hook is decorative."""
    issues = _placeholder_issues(_check(tmp_path, 'API_KEY = "CHANGE_ME_real_secret"\n'))
    assert len(issues) == 1
    assert ":1:" in issues[0]


def test_an_ordinary_string_is_not_exempt_just_because_it_is_a_string(tmp_path):
    """A string literal is only exempt when it is a *docstring*.

    Widening this to all strings would exempt the assignment above, which is
    precisely the finding worth having.
    """
    source = '''
    """Module docstring."""

    DEFAULTS = {
        "endpoint": "CHANGE_ME_leaked",
    }
    '''
    assert len(_placeholder_issues(_check(tmp_path, source))) == 1


def test_a_string_positioned_after_a_docstring_is_not_swallowed(tmp_path):
    """An off-by-one in the span end would exempt the line following it."""
    source = '''
    def f():
        """Doc.

        Multi-line.
        """
        token = "CHANGE_ME_still_a_finding"
        return token
    '''
    assert len(_placeholder_issues(_check(tmp_path, source))) == 1


def test_a_bare_string_expression_is_not_treated_as_a_docstring(tmp_path):
    """Only the first statement of a module/class/function is a docstring."""
    source = '''
    """Real docstring."""

    "CHANGE_ME_not_a_docstring"
    '''
    assert len(_placeholder_issues(_check(tmp_path, source))) == 1


# ── Behaviour preserved around the restructure ───────────────────────────────


def test_an_unparseable_file_still_reports_its_line_findings_and_the_error(tmp_path):
    """The parse moved ahead of the line loop; on SyntaxError the line-level
    findings must still be reported, and the syntax error after them."""
    issues = _check(tmp_path, 'API_KEY = "CHANGE_ME_x"\ndef broken(:\n')
    assert any("hardcoded placeholder" in i for i in issues)
    assert any("syntax error" in i for i in issues)
    assert issues.index(next(i for i in issues if "hardcoded placeholder" in i)) < issues.index(
        next(i for i in issues if "syntax error" in i)
    )


def test_the_explicit_ignore_marker_still_works(tmp_path):
    source = 'PREFIX = "CHANGE_ME"  # healer: ignore\n'
    assert _placeholder_issues(_check(tmp_path, source)) == []


def test_other_checks_are_unaffected(tmp_path):
    """The restructure touched shared setup, so confirm a neighbouring check."""
    issues = _check(tmp_path, "def f():\n    pass\n")
    assert any("bare `pass`" in i for i in issues)


# ── The file that started it ─────────────────────────────────────────────────


def test_the_startup_validator_passes_its_own_hook():
    """config/startup_validator.py both defines the placeholder constant and
    documents the placeholder it used to accept."""
    issues = _healer().check_file(_ROOT / "config/startup_validator.py")
    assert issues == [], f"the hook still blocks the validator: {issues}"
