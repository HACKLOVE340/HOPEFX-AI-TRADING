# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ci_workflow_parity.py
=====================================
`ci.yml` and `tests.yml` run the same suite against the same coverage gate.
They must run it in the same environment, or the gate means two things.

They are not redundant — `tests.yml` also fires on pushes to `claude/**` and
`copilot/**`, which `ci.yml` does not cover, so feature branches get coverage
reporting from it. But it had no postgres service and set no `DATABASE_URL`,
so every DB-backed branch was skipped or took its fallback path. The identical
`.coveragerc` and identical `--cov-fail-under=70` then produced:

    ci.yml     71.53%   pass
    tests.yml  69.60%   fail

The gate was unreachable by construction, and `tests.yml` failed on **every**
commit to main. That is worse than having no gate: a check that can never pass
is a check nobody reads, and it sat red alongside genuine failures all day.

These tests pin the parity rather than the numbers. Coverage will move; what
must not move is the two workflows disagreeing about what they measure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _test_job(filename: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / filename).read_text(encoding="utf-8"))["jobs"]["test"]


def _coverage_step(job: dict) -> dict:
    for step in job["steps"]:
        if "--cov-fail-under" in str(step.get("run", "")):
            return step
    raise AssertionError("no coverage-gated pytest step found")


def test_both_workflows_provide_the_same_service_containers():
    """A missing database is why the two disagreed by two percentage points."""
    ci = _test_job("ci.yml")
    tests = _test_job("tests.yml")

    assert sorted(ci["services"]) == sorted(tests["services"]), (
        f"service sets differ: ci.yml={sorted(ci['services'])} tests.yml={sorted(tests['services'])}"
    )


def test_both_workflows_run_the_suite_against_the_same_database():
    ci_env = _coverage_step(_test_job("ci.yml"))["env"]
    tests_env = _coverage_step(_test_job("tests.yml"))["env"]

    assert "DATABASE_URL" in tests_env, "tests.yml runs the suite with no database configured"
    assert ci_env["DATABASE_URL"] == tests_env["DATABASE_URL"], (
        "the two workflows point at different databases, so their coverage cannot be compared"
    )


def test_both_workflows_gate_at_the_same_threshold():
    """If the thresholds ever diverge, the parity above stops mattering."""
    import re

    ci_run = _coverage_step(_test_job("ci.yml"))["run"]
    tests_run = _coverage_step(_test_job("tests.yml"))["run"]

    pat = re.compile(r"--cov-fail-under=(\d+)")
    ci_gate = pat.search(ci_run).group(1)
    tests_gate = pat.search(tests_run).group(1)

    assert ci_gate == tests_gate, f"ci.yml gates at {ci_gate}%, tests.yml at {tests_gate}%"


def test_both_workflows_use_the_same_coverage_config():
    """Different configs would measure different file sets under one threshold."""
    ci_run = _coverage_step(_test_job("ci.yml"))["run"]
    tests_run = _coverage_step(_test_job("tests.yml"))["run"]

    assert "--cov-config=.coveragerc" in ci_run
    assert "--cov-config=.coveragerc" in tests_run


def test_both_workflows_select_the_same_tests():
    """A different marker expression changes what is measured."""
    ci_run = _coverage_step(_test_job("ci.yml"))["run"]
    tests_run = _coverage_step(_test_job("tests.yml"))["run"]

    marker = "not slow and not e2e"
    assert marker in ci_run
    assert marker in tests_run


def test_the_postgres_service_is_reachable_at_the_url_the_env_points_to():
    """Wiring check: a service on a different port would fail at connect time."""
    job = _test_job("tests.yml")
    env = _coverage_step(job)["env"]

    assert "5432:5432" in job["services"]["postgres"]["ports"]
    assert "localhost:5432" in env["DATABASE_URL"]
