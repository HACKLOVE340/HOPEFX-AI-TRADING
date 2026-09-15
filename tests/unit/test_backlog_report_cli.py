"""Regression tests for the documented repository reporting commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _run_script(name: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(  # nosec B603 — fixed project-owned argv
        [sys.executable, str(REPO / "scripts" / name)],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_documented_backlog_report_invocation_runs_from_repository_root() -> None:
    """A fresh checkout must support the command shown in backlog_report.py."""
    result = _run_script("backlog_report.py")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("WHAT IS LEFT TO BUILD OR FIX")
    assert "Generated from the repository." in result.stdout


def test_documented_docs_freshness_invocation_runs_from_repository_root() -> None:
    """A fresh checkout must support the command used by its pre-commit hook."""
    result = _run_script("docs_freshness.py")

    assert result.returncode == 0, result.stderr
    assert "blocking" in result.stdout
    assert "baselined" in result.stdout
