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
COVERAGE_THRESHOLD (default 80%).

Designed to be fast: only tests the modules that changed in this commit,
not the entire test suite.

A figure from this gate is therefore NOT the module's coverage across the suite,
and the two must not be compared. `risk/manager.py` reads 43% here and 89.65% in
.coveragerc's recorded measurement; both are correct, because this gate runs one
test file and that figure runs all of them. Quoting this number as the module's
coverage would understate it by 46 points.

Exit codes
----------
0 — coverage gate passed (or no testable modules changed)
1 — coverage below threshold for one or more modules, OR coverage could not be
    measured for one of them. An unmeasured module is not a covered module:
    this gate used to pass a module at 0% while failing one at 25%, because a
    module a test never imports produces no coverage table to parse.

Environment variables
---------------------
COVERAGE_THRESHOLD   : minimum line coverage % (default: 80)
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
from dataclasses import dataclass
from pathlib import Path

_THRESHOLD = int(os.getenv("COVERAGE_THRESHOLD", "80"))
_SKIP = os.getenv("SKIP_COVERAGE_GATE", "0").strip() == "1"

#: Where the recorded debt lives. Generated, never hand-written.
#:
#: 361 modules, every one recorded because measurement returned ``None``. As
#: `_coverage_target` explains, measurement returned ``None`` for *everything*
#: until the dotted-module invocation was fixed, so this list records one broken
#: invocation rather than 361 untested modules. Its former claim — "each entry
#: means no test imports this module" — described a conclusion the gate had no
#: means to reach.
#:
#: Repairing the invocation without this list would swing the gate from passing
#: everything to blocking every commit that touches any of 361 files, and a gate
#: that blocks work people must do gets switched off with SKIP_COVERAGE_GATE=1.
#: So it is the same ratchet the document registry, the freshness checker and the
#: gate-evidence ledger use — a generated file that may only shrink, with
#: pressure in both directions:
#:
#:   * recorded and under the floor  -> reported as DEBT on stderr, does not block
#:   * recorded and AT the floor     -> BLOCKS: delete the line
#:   * not recorded                  -> judged on its number, blocks if short
#:
#: The second rule is the tooth. Without it this is an allowlist, and an
#: allowlist under no pressure is how a ratchet stops being one. See
#: tests/unit/test_coverage_gate_ratchet.py.
#:
#: An over-broad seed is therefore inert while a module stays under the floor and
#: blocks the moment it clears one — the direction that costs nothing. The seed is
#: static (every module whose resolved test file never mentions it) because
#: measuring all 539 candidates takes about two hours:
#:
#:     python scripts/pre_commit_coverage.py --adopt   # regenerate by measurement (slow)
BASELINE_PATH = Path(__file__).resolve().parent.parent / "docs" / "COVERAGE_UNMEASURABLE.txt"


def _load_baseline() -> frozenset[str]:
    if not BASELINE_PATH.exists():
        return frozenset()
    return frozenset(
        line.strip()
        for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )


_EXCLUDED_PATTERNS = frozenset(
    {
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
    }
)


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


def _coverage_target(module_path: Path) -> str:
    """What to hand `--cov=`.

    A dotted *module* name (``risk.manager``) makes coverage resolve and import
    the module itself, which re-initialises numpy's C extension inside a process
    that already imported it via ``tests/conftest.py``:

        numpy/_core/multiarray.py:11: in <module>
            from . import _multiarray_umath, overrides
        ImportError: cannot load module more than once per process

    Every module in scope imports numpy transitively, so the gate could not
    measure a single one — and reported that as "the test may not import the
    module", which blames the test and invites ``SKIP_COVERAGE_GATE=1``.

    A *package* name resolves as a directory and does not import anything, so
    ``--cov=risk`` works where ``--cov=risk.manager`` cannot. The module's own
    figure is then read out of the report by `_parse_module_coverage`.
    """
    parts = Path(str(module_path).replace("\\", "/")).parts
    if len(parts) > 1:
        return parts[0]
    # A module at the repository root has no package to name, and its bare stem
    # would be a dotted module again. `.` measures the tree; the row is read the
    # same way either way.
    return "."


def _coverage_command(module_path: Path, test_path: Path) -> list[str]:
    """The pytest invocation the gate runs. Extracted so it can be asserted."""
    return [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        f"--cov={_coverage_target(module_path)}",
        # NOT `:skip-covered` — a module at 100% would be omitted from the
        # report, and an absent row is indistinguishable from unmeasured, so
        # perfect coverage would fail the gate.
        "--cov-report=term-missing",
        "--cov-config=.coveragerc",
        # .coveragerc carries fail_under=70 for the whole project. This gate
        # judges one module against its own floor, and a non-zero exit from the
        # global figure would be read as "could not measure".
        "--cov-fail-under=0",
        "-q",
        "--no-header",
        "--tb=no",
        "--timeout=30",
    ]


def _parse_module_coverage(output: str, module_path: Path) -> float | None:
    """Read *module_path*'s own row out of a term-missing report.

    Returns None when the module has no row — which means nothing measured it,
    not that it measured zero. TOTAL is deliberately not a fallback: with a
    package-wide ``--cov`` it is the package's number, and reporting it as the
    module's would be a fabricated measurement of exactly the kind this gate
    exists to catch.
    """
    wanted = str(module_path).replace("\\", "/")
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0].replace("\\", "/") != wanted:
            continue
        for token in reversed(parts):
            if token.endswith("%"):
                try:
                    return float(token.rstrip("%"))
                except ValueError:  # nosec B112 — malformed cell; keep scanning
                    continue
    return None


def _run_coverage(module_path: Path, test_path: Path) -> tuple[float | None, str]:
    """
    Run pytest with coverage for a single module/test pair.

    Returns (coverage_pct, output_text); coverage_pct is None when the module's
    own row is absent from the report.
    """
    cmd = _coverage_command(module_path, test_path)

    try:
        result = subprocess.run(  # nosec B603 — fixed args, no shell
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "CI_FAST": "1"},
        )
        output = result.stdout + result.stderr
        return _parse_module_coverage(output, module_path), output
    except subprocess.TimeoutExpired:
        return None, f"Coverage check timed out for {module_path}"
    except Exception as exc:
        return None, f"Coverage check failed: {exc}"


@dataclass(frozen=True)
class Verdict:
    """What the gate decided about one module, and the sentence it says."""

    ok: bool
    message: str
    #: Recorded debt: does not block, but is a warning and goes to stderr like
    #: one. A non-blocking line on stdout is a line nobody reads.
    debt: bool = False


def _judge(module_path: Path, test_path: Path, pct: float | None, *, recorded: bool) -> Verdict:
    """Decide one module. Pure — no I/O, so the decision can be asserted.

    Four states, and the recorded list changes only two of them:

    ================  ==================  ====================================
    measured          recorded            outcome
    ================  ==================  ====================================
    >= threshold      no                  pass
    >= threshold      yes                 BLOCK — the entry is stale, remove it
    < threshold       no                  BLOCK
    < threshold       yes                 DEBT — reported, does not block
    unmeasured        no                  BLOCK
    unmeasured        yes                 DEBT — reported, does not block
    ================  ==================  ====================================

    The stale-entry block is what keeps the record a ratchet. Everything else
    here is an allowlist, and an allowlist under no pressure becomes the reason
    nobody notices the gate stopped saying anything.
    """
    shown = f"{module_path}"
    if pct is None:
        why = (
            f"{shown}: coverage could not be measured (test: {test_path}) — "
            "the test may not import the module, or may fail to collect"
        )
        if recorded:
            return Verdict(True, f"DEBT {why}. Recorded in {BASELINE_PATH.name}; the list may only shrink.", debt=True)
        return Verdict(False, why)

    if pct >= _THRESHOLD:
        if recorded:
            return Verdict(
                False,
                f"{shown}: now measures {pct:.0f}% >= {_THRESHOLD}% and must leave the record. "
                f"Delete its line from docs/{BASELINE_PATH.name} — the list may only shrink, "
                "and an entry that no longer describes anything is how a ratchet quietly stops "
                "being one.",
            )
        return Verdict(True, f"OK   {shown}: {pct:.0f}% >= {_THRESHOLD}%")

    if recorded:
        return Verdict(
            True,
            f"DEBT {shown}: {pct:.0f}% < {_THRESHOLD}% (test: {test_path}). Recorded in "
            f"docs/{BASELINE_PATH.name}. Not permission — raise it and delete the line.",
            debt=True,
        )
    return Verdict(False, f"{shown}: coverage {pct:.0f}% < {_THRESHOLD}% threshold (test: {test_path})")


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
        verdict = _judge(path, test_file, coverage_pct, recorded=str(path).replace("\\", "/") in _load_baseline())

        if verdict.ok:
            print(f"pre_commit_coverage: {verdict.message}", file=sys.stderr if verdict.debt else sys.stdout)
            continue

        failures.append(verdict.message)
        print(f"pre_commit_coverage: FAIL {verdict.message}", file=sys.stderr)
        if coverage_pct is None:
            print(output[:500], file=sys.stderr)

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


def adopt() -> int:
    """Regenerate the baseline by running the gate's own measurement.

    Slow on purpose: it is the only way to produce a set that agrees exactly
    with what the gate does at commit time. The committed seed is a static
    approximation; this replaces it with the measured truth.
    """
    import subprocess as _sp

    repo = Path(__file__).resolve().parent.parent
    listed = _sp.run(  # nosec B603 — fixed args, no shell
        ["git", "ls-files", "*.py"], cwd=repo, capture_output=True, text=True, check=False
    ).stdout.split()

    candidates = [
        Path(f)
        for f in listed
        if not _is_excluded(Path(f)) and not Path(f).name.startswith("test_") and "tests/" not in f
    ]
    candidates = [p for p in candidates if _find_test_file(p) is not None]

    print(f"measuring {len(candidates)} modules — this takes a while", flush=True)
    unmeasurable: list[str] = []
    for i, module in enumerate(candidates, 1):
        test_file = _find_test_file(module)
        assert test_file is not None  # nosec B101 — filtered above
        pct, _ = _run_coverage(module, test_file)
        if pct is None:
            unmeasurable.append(str(module).replace("\\", "/"))
        if i % 50 == 0:
            print(f"  {i}/{len(candidates)} — {len(unmeasurable)} unmeasurable", flush=True)

    # The header is the record's meaning; regenerating must not revert it to
    # the pre-repair wording, which described a measurement that never ran.
    header = [ln for ln in BASELINE_PATH.read_text(encoding="utf-8").splitlines() if ln.startswith("#")]
    header.append("")

    BASELINE_PATH.write_text("\n".join(header + sorted(unmeasurable)) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE_PATH.name}: {len(unmeasurable)} of {len(candidates)} unmeasurable")
    return 0


if __name__ == "__main__":
    if "--adopt" in sys.argv[1:]:
        sys.exit(adopt())
    sys.exit(main(sys.argv[1:]))
