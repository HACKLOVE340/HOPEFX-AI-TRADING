# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_source_text_helper.py
=====================================
Tests for the helper that stops tests matching their own prose.

Many tests here pin a fix by asserting a string is present in, or absent from,
a module's source. The convention in this repository is also that a fix
documents the defect it replaces — so the explanation contains the very string
the assertion looks for, and the test passes or fails for the wrong reason.

That happened four separate times before this helper existed, each time
"solved" by a private function in the one file, so the next file repeated it:

* ``filter_by(id=...)`` matched the comment saying it had been removed;
* a placeholder scan matched its own description of a placeholder;
* a check that the 'Resource ID' column was deleted matched the JSX comment
  saying it was deleted;
* a check that "check REDIS_URL" was gone matched the comment quoting it.

A helper is only worth having if it is exactly right, so it is tested here.
Two properties matter and pull against each other: it must remove **all** prose
(or the original bug returns) and **no** code (or assertions pass vacuously,
which is worse — a silently vacuous test looks like a passing one).
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from tests.support.source_text import code_only, python_code_only, tsx_code_only

pytestmark = pytest.mark.unit


def _write(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body))
    return path


# ── Prose is removed ─────────────────────────────────────────────────────────


def test_a_module_docstring_is_removed(tmp_path):
    path = _write(
        tmp_path,
        "m.py",
        '''
        """This mentions SECRET_MARKER in prose."""
        x = 1
    ''',
    )
    out = python_code_only(path)
    assert "SECRET_MARKER" not in out
    assert "x = 1" in out


def test_a_function_docstring_is_removed(tmp_path):
    path = _write(
        tmp_path,
        "m.py",
        '''
        def f():
            """Explains why SECRET_MARKER was deleted."""
            return 2
    ''',
    )
    out = python_code_only(path)
    assert "SECRET_MARKER" not in out
    assert "return 2" in out


def test_a_trailing_comment_is_removed_but_its_line_of_code_survives(tmp_path):
    path = _write(
        tmp_path,
        "m.py",
        """
        value = 3  # SECRET_MARKER lives here
    """,
    )
    out = python_code_only(path)
    assert "SECRET_MARKER" not in out
    assert "value = 3" in out


def test_a_multiline_docstring_is_removed_entirely(tmp_path):
    path = _write(
        tmp_path,
        "m.py",
        '''
        def f():
            """Line one.

            Line two mentions SECRET_MARKER.
            """
            return 4
    ''',
    )
    assert "SECRET_MARKER" not in python_code_only(path)


# ── Code is not removed ──────────────────────────────────────────────────────


def test_adjacency_is_preserved(tmp_path):
    """The failure that produced this test.

    An earlier version re-joined tokens with spaces, turning
    ``{"client": "async"}`` into ``{ "client" : "async" }`` — which broke every
    substring assertion the helper existed to serve, silently, by making them
    all fail.
    """
    path = _write(
        tmp_path,
        "m.py",
        '''
        """Prose."""
        payload = {"client": "async", "reason": code}
    ''',
    )
    assert '{"client": "async", "reason": code}' in python_code_only(path)


def test_a_string_literal_that_is_not_a_docstring_survives(tmp_path):
    """A triple-quoted value assigned to a name is code, not prose."""
    path = _write(
        tmp_path,
        "m.py",
        '''
        TEMPLATE = """SECRET_MARKER inside a value"""
    ''',
    )
    assert "SECRET_MARKER" in python_code_only(path)


def test_a_hash_inside_a_string_is_not_treated_as_a_comment(tmp_path):
    path = _write(
        tmp_path,
        "m.py",
        """
        channel = "#elite-support"
    """,
    )
    assert '"#elite-support"' in python_code_only(path)


def test_indentation_is_preserved(tmp_path):
    path = _write(
        tmp_path,
        "m.py",
        '''
        def f():
            """Doc."""
            if True:
                return 5
    ''',
    )
    assert "        return 5" in python_code_only(path)


# ── TSX ──────────────────────────────────────────────────────────────────────


def test_jsx_comments_are_removed(tmp_path):
    path = _write(
        tmp_path,
        "c.tsx",
        """
        const A = () => (
          <div>
            {/* SECRET_MARKER explains a deletion */}
            <span>{value}</span>
          </div>
        );
    """,
    )
    out = tsx_code_only(path)
    assert "SECRET_MARKER" not in out
    assert "<span>{value}</span>" in out


def test_jsdoc_and_line_comments_are_removed(tmp_path):
    path = _write(
        tmp_path,
        "c.tsx",
        """
        /** SECRET_MARKER in jsdoc */
        // SECRET_MARKER in a line comment
        export const x = 1;
    """,
    )
    out = tsx_code_only(path)
    assert "SECRET_MARKER" not in out
    assert "export const x = 1;" in out


def test_a_url_in_tsx_code_is_not_mistaken_for_a_comment(tmp_path):
    """`//` inside a string is not a comment."""
    path = _write(
        tmp_path,
        "c.tsx",
        """
        const url = 'https://example.com/path';
    """,
    )
    assert "https://example.com/path" in tsx_code_only(path)


# ── Dispatch ─────────────────────────────────────────────────────────────────


def test_code_only_dispatches_on_extension(tmp_path):
    py = _write(tmp_path, "m.py", '"""SECRET_MARKER."""\nx = 1\n')
    tsx = _write(tmp_path, "c.tsx", "{/* SECRET_MARKER */}\nconst y = 2;\n")
    assert "SECRET_MARKER" not in code_only(py)
    assert "SECRET_MARKER" not in code_only(tsx)
    assert "x = 1" in code_only(py)
    assert "const y = 2;" in code_only(tsx)


def test_a_module_object_is_accepted():
    """Callers usually have the module, not its path."""
    from cache import redis_client

    out = code_only(redis_client)
    assert "def get_redis" in out


# ── It works on the real files it was built for ──────────────────────────────


def test_it_strips_the_four_files_that_caused_it():
    """Each of these documents a string that a test asserts is absent."""
    root = pathlib.Path(__file__).resolve().parents[2]
    cases = [
        (root / "cache/redis_client.py", "check REDIS_URL"),
        (root / "frontend/src/pages/superadmin/AuditTrailSection.tsx", "'Resource ID'"),
    ]
    for path, marker in cases:
        if not path.exists():
            pytest.skip(f"{path} not present")
        assert marker in path.read_text(), f"{path} no longer documents {marker!r} — case is stale"
        assert marker not in code_only(path), f"{marker!r} survived stripping in {path}"
