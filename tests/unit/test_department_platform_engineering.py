# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Platform Engineering — three read actions, and one that stays declared.

Spec §4 Cluster A, third department. `scan_secrets`, `check_broken_imports` and
`run_tests` are implemented; `propose_fix` is not, for the same reason
`propose_derisk` is not — a proposal needs somewhere to land that a human
reviews, and inventing that under time pressure is how a proposal becomes an
action nobody approved.

**`run_tests` is bounded, and the bound is a safety property rather than
tidiness.** An agent that can spawn the full suite on a box that also executes
trades can starve the trading engine of CPU — the same argument that makes the
local model runtime refuse an oversized tier. So it requires an explicit target
and enforces a timeout, and it will not run the whole suite by omission. A tool
that does something enormous when you forget an argument is a tool that will
eventually do something enormous.

`check_broken_imports` is deliberately AST-based rather than a grep. F255 in
this repository was a checker that read docstrings as if they were source; a
regex over import lines would flag every import named inside a comment or a
string. Reading the parse tree is the only way to know an import is an import.
"""

from __future__ import annotations

import pytest

from ai import departments
from ai.departments import platform_engineering
from core.ai_tool_permissions import ToolRisk

pytestmark = pytest.mark.unit


# ── what is wired ────────────────────────────────────────────────────────────


def test_the_three_read_actions_are_implemented():
    for name in ("scan_secrets", "check_broken_imports", "run_tests"):
        action = departments.action_by_name(f"platform_engineering.{name}")
        assert action.handler is not None, name
        assert action.risk is ToolRisk.READ_ONLY, name


def test_propose_fix_stays_unimplemented():
    assert departments.action_by_name("platform_engineering.propose_fix").handler is None


def test_everything_wired_across_all_departments_is_still_read_only():
    """The invariant that matters more than which department is next."""
    for action in departments.implemented_actions():
        assert action.risk is ToolRisk.READ_ONLY, action.name
        assert action.requires_approval is False, action.name


# ── check_broken_imports: parse trees, not regexes ───────────────────────────


def test_a_clean_module_reports_no_broken_imports(tmp_path):
    (tmp_path / "clean.py").write_text("import os\nimport sys\n\nprint(os, sys)\n")
    result = platform_engineering.check_broken_imports(root=str(tmp_path))
    assert result["available"] is True
    assert result["broken"] == []


def test_an_unresolvable_import_is_found(tmp_path):
    (tmp_path / "bad.py").write_text("import totally_not_a_real_module_xyz\n")
    result = platform_engineering.check_broken_imports(root=str(tmp_path))
    assert result["available"] is True
    assert any("totally_not_a_real_module_xyz" in row["module"] for row in result["broken"])


def test_an_import_named_only_in_a_comment_or_string_is_not_flagged(tmp_path):
    """F255: a checker that reads prose is not reading code."""
    (tmp_path / "prose.py").write_text(
        "# import totally_not_a_real_module_xyz\n"
        'DOC = "import totally_not_a_real_module_xyz"\n'
        '"""import totally_not_a_real_module_xyz"""\n'
        "import os\nprint(os, DOC)\n"
    )
    result = platform_engineering.check_broken_imports(root=str(tmp_path))
    assert result["broken"] == [], result["broken"]


def test_a_file_that_will_not_parse_is_reported_not_skipped_silently(tmp_path):
    """A syntax error is a finding. Skipping it quietly is how it survives."""
    (tmp_path / "broken_syntax.py").write_text("def oops(:\n")
    result = platform_engineering.check_broken_imports(root=str(tmp_path))
    assert result["unparseable"], "a file that cannot be parsed must be reported"


# ── run_tests: bounded by construction ───────────────────────────────────────


def test_run_tests_refuses_without_a_target():
    """Forgetting the argument must not run the whole suite."""
    result = platform_engineering.run_tests()
    assert result["available"] is False
    assert "target_required" in result["reason"]


def test_run_tests_refuses_a_target_that_escapes_the_repository():
    """A path argument is an obvious way to reach outside the tree."""
    result = platform_engineering.run_tests(target="../../etc")
    assert result["available"] is False
    assert "unsafe_target" in result["reason"]


def test_run_tests_passes_a_timeout_to_the_runner():
    seen: dict[str, object] = {}

    def fake_run(argv, timeout):
        seen["argv"] = argv
        seen["timeout"] = timeout
        return {"returncode": 0, "stdout": "1 passed", "stderr": ""}

    result = platform_engineering.run_tests(target="tests/unit/test_nothing.py", run=fake_run)
    assert result["available"] is True
    assert seen["timeout"] > 0
    assert "tests/unit/test_nothing.py" in seen["argv"]


def test_a_failing_test_run_is_reported_as_failing_not_as_unavailable():
    """A red suite is an answer. Reporting it as "unavailable" hides it."""
    result = platform_engineering.run_tests(
        target="tests/unit/x.py",
        run=lambda argv, timeout: {"returncode": 1, "stdout": "1 failed", "stderr": ""},
    )
    assert result["available"] is True
    assert result["passed"] is False


def test_a_runner_that_times_out_says_so():
    def boom(argv, timeout):
        raise TimeoutError("exceeded")

    result = platform_engineering.run_tests(target="tests/unit/x.py", run=boom)
    assert result["available"] is False
    assert "timeout" in result["reason"].lower()


# ── scan_secrets ─────────────────────────────────────────────────────────────


def test_scan_secrets_returns_a_count_not_the_secrets():
    """Reporting the value of a found credential leaks it into the audit log."""
    result = platform_engineering.scan_secrets(
        scan=lambda: [
            # A fabricated value, present so the assertion below can prove it
            # does NOT reach the result. It is not a credential.
            {"filename": "a.py", "line_number": 3, "type": "AWS Key", "secret": "AKIAREAL"}  # pragma: allowlist secret
        ]
    )
    assert result["available"] is True
    assert result["finding_count"] == 1
    assert "AKIAREAL" not in repr(result)


def test_scan_secrets_reports_a_scanner_failure():
    def boom():
        raise RuntimeError("baseline unreadable")

    result = platform_engineering.scan_secrets(scan=boom)
    assert result["available"] is False
    assert "baseline unreadable" in result["reason"]
    assert "finding_count" not in result, "an unavailable scan must not report zero findings"


# ── through the bus ──────────────────────────────────────────────────────────


def test_check_broken_imports_runs_through_the_bus():
    bus = departments.build_tool_bus()
    result = bus.invoke(
        "platform_engineering.check_broken_imports",
        operator="tester",
        allowed_actions={"platform_engineering.check_broken_imports"},
        root="ai/departments",
    )
    assert result.allowed is True
    assert result.value["available"] is True


# ── the REAL default paths, executed ─────────────────────────────────────────
#
# Every scan_secrets test above injects a fake scanner, and the real one shipped
# calling a detect_secrets function that does not exist in the installed
# version. It passed every test. These execute the defaults.


def test_the_real_secret_scanner_runs_against_the_committed_baseline():
    result = platform_engineering.scan_secrets()
    assert result["available"] is True, result.get("reason")
    assert isinstance(result["finding_count"], int)


def test_the_real_scanner_never_returns_a_secret_value():
    """The baseline stores hashes; none of them should cross this boundary."""
    import json

    result = platform_engineering.scan_secrets()
    rendered = repr(result)
    with open(".secrets.baseline", encoding="utf-8") as fh:
        data = json.load(fh)
    hashes = [
        s.get("hashed_secret")
        for secrets in (data.get("results") or {}).values()
        for s in (secrets or [])
        if s.get("hashed_secret")
    ]
    assert hashes, "baseline has no entries — this test would pass vacuously"
    for digest in hashes[:50]:
        assert digest not in rendered


def test_a_missing_baseline_is_reported_not_crashed():
    result = platform_engineering.scan_secrets(
        scan=lambda: platform_engineering._default_secret_scan("no-such-baseline.json")
    )
    assert result["available"] is False
    assert "scan_failed" in result["reason"]
