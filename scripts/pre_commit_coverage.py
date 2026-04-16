#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
scripts/pre_commit_coverage.py
==============================
Pre-commit hook: coverage gate for changed Python modules.

For each staged Python file that has a corresponding test file, runs pytest
with coverage and fails if the module's line coverage drops below
COVERAGE_THRESHOLD (default 70%).

Designed to be fast: only tests the modules that changed in this commit,
not the entire test suite.

Exit codes
----------
0 — coverage gate passed (or no testable modules changed)
1 — coverage below threshold for one or more modules

Environment variables
---------------------
COVERAGE_THRESHOLD   : minimum line coverage % (default: 70)
SKIP_COVERAGE_GATE   : set to "1" to skip this hook (emergency bypass)
CI_FAST              : set to "1" to use reduced estimators (faster CI)

Usage (called by pre-commit framework)
---------------------------------------
    python scripts/pre_commit_coverage.py file1.py file2.py ...
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — pytest subprocess, fixed args
import sys
from pathlib import Path

_THRESHOLD = int(os.getenv("COVERAGE_THRESHOLD", "70"))
_SKIP = os.getenv("SKIP_COVERAGE_GATE", "0").strip() == "1"

# Modules excluded from coverage gate (generated code, migrations, examples)
_EXCLUDED_PATTERNS = frozenset({
    "alembic/",
    "migrations/",
    "examples/",
    "scripts/",
    "docs/",
    "frontend/",
    "mobile/",
    "mobile-app/",
    "dashboard/",
    "grafana/",
    "helm/",
    "k8s/",
    "docker/",
    "nginx/",
})


def _is_excluded(path: Path) -> bool:
    path_str = str(path)
    return any(pat in path_str for pat in _EXCLUDED_PATTERNS)


def _find_test_file(module_path: Path) -> Path | None:
    """
    Find the corresponding test file for a module.

    Search order:
    1. tests/unit/test_{module_name}.py
    2. tests/test_{module_name}.py
    3. tests/unit/test_{parent}_{module_name}.py
    """
    name = module_path.stem
    parent = module_path.parent.name

    candidates = [
        Path("tests") / "unit" / f"test_{name}.py",
        Path("tests") / f"test_{name}.py",
        Path("tests") / "unit" / f"test_{parent}_{name}.py",
        Path("tests") / f"test_{parent}_{name}.py",
        Path("tests") / "unit" / f"test_{parent}.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _run_coverage(module_path: Path, test_path: Path) -> tuple[float | None, str]:
    """
    Run pytest with coverage for a single module/test pair.

    Returns (coverage_pct, output_text) or (None, error_text) on failure.
    """
    module_dotted = str(module_path).replace("/", ".").replace("\\", ".").removesuffix(".py")

    cmd = [
        sys.executable, "-m", "pytest",
        str(test_path),
        f"--cov={module_dotted}",
        "--cov-report=term-missing:skip-covered",
        "--cov-config=.coveragerc",
        "-q",
        "--no-header",
        "--tb=no",
        "--timeout=30",
    ]

    try:
        result = subprocess.run(  # nosec B603 — fixed args, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "CI_FAST": "1"},
        )
        output = result.stdout + result.stderr

        # Parse coverage percentage from pytest-cov output
        # Line format: "TOTAL    123    45    63%"
        for line in output.splitlines():
            if line.strip().startswith("TOTAL"):
                parts = line.split()
                if parts and parts[-1].endswith("%"):
                    try:
                        return float(parts[-1].rstrip("%")), output
                    except ValueError:
                        pass

        return None, output
    except subprocess.TimeoutExpired:
        return None, f"Coverage check timed out for {module_path}"
    except Exception as exc:
        return None, f"Coverage check failed: {exc}"


def main(argv: list[str]) -> int:
    if _SKIP:
        print("pre_commit_coverage: SKIP_COVERAGE_GATE=1 — skipping coverage gate")
        return 0

    if not argv:
        return 0

    failures: list[str] = []
    checked = 0

    for arg in argv:
        path = Path(arg)
        if path.suffix != ".py":
            continue
        if not path.exists():
            continue
        if _is_excluded(path):
            continue
        # Skip test files themselves
        if path.name.startswith("test_") or "tests/" in str(path):
            continue

        test_file = _find_test_file(path)
        if test_file is None:
            # No test file found — skip silently (new module, not yet tested)
            continue

        checked += 1
        coverage_pct, output = _run_coverage(path, test_file)

        if coverage_pct is None:
            # Could not determine coverage — warn but don't block
            print(
                f"pre_commit_coverage: WARNING — could not measure coverage for {path} "
                f"(test: {test_file}). Output:\n{output[:500]}",
                file=sys.stderr,
            )
            continue

        if coverage_pct < _THRESHOLD:
            failures.append(
                f"{path}: coverage {coverage_pct:.0f}% < {_THRESHOLD}% threshold "
                f"(test: {test_file})"
            )
            print(
                f"pre_commit_coverage: FAIL {path}: {coverage_pct:.0f}% < {_THRESHOLD}%",
                file=sys.stderr,
            )
        else:
            print(
                f"pre_commit_coverage: OK   {path}: {coverage_pct:.0f}% >= {_THRESHOLD}%"
            )

    if not checked:
        return 0

    if failures:
        print(
            f"\npre_commit_coverage: {len(failures)} module(s) below {_THRESHOLD}% coverage threshold:",
            file=sys.stderr,
        )
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nAdd tests or set SKIP_COVERAGE_GATE=1 to bypass (not recommended).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
