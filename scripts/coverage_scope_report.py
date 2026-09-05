#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/coverage_scope_report.py — what the coverage gate can actually see.

A coverage percentage is a fraction of the code the tool was pointed at, not of
the application. `.coveragerc [run] source` names a subset of packages, and
`omit` removes modules from inside them — so "74% coverage" and "Per-module
coverage gate (>=80%) PASSED" are both true statements about a scope nobody
prints (F221, F105).

This prints the scope. It measures three things, none of them declared:

  1. Application LOC, by package.
  2. How much of it `[run] source` reaches.
  3. Which modules `omit` removes from inside that, and how much they weigh.

It is deliberately not a gate on the *percentage* — raising `source` to cover
everything would drop the number below the CI floor overnight and tell you
nothing you did not already know. It is a gate on **honesty**: the scope is
reported next to the coverage figure, so nobody reads a subset as the whole.

That is the same correction applied to `scripts/invariant_coverage.py` for F176.
A measurement that does not state its scope is not a measurement.

Usage:
    python scripts/coverage_scope_report.py
    python scripts/coverage_scope_report.py --json
    python scripts/coverage_scope_report.py --fail-under-share 30

Exit codes: 0 normally; 1 if --fail-under-share is given and the measured share
is below it.
"""

from __future__ import annotations

import argparse
import configparser
import fnmatch
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that are not application code.
_SKIP_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    "build",
    "dist",
    "tests",
    "alembic",
    "migrations",
    ".mypy_cache",
    ".pytest_cache",
    "htmlcov",
}
_MIN_PACKAGE_LOC = 200


def _statement_count(path: Path) -> int:
    """Non-blank, non-comment lines — a stand-in for statements that needs no import."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    total = 0
    in_docstring = False
    delim = ""
    for raw in lines:
        line = raw.strip()
        if in_docstring:
            if delim in line:
                in_docstring = False
            continue
        if not line or line.startswith("#"):
            continue
        if line.startswith(('"""', "'''")):
            delim = line[:3]
            if not (line.endswith(delim) and len(line) > 3):
                in_docstring = True
            continue
        total += 1
    return total


def _application_files() -> list[Path]:
    out = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        out.append(path)
    return out


def _read_coveragerc() -> tuple[list[str], list[str]]:
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / ".coveragerc")
    if not parser.has_section("run"):
        return [], []
    source = [s.strip() for s in parser.get("run", "source", fallback="").splitlines() if s.strip()]
    omit = [s.strip() for s in parser.get("run", "omit", fallback="").splitlines() if s.strip()]
    return source, omit


def _omitted(rel: str, omit: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(f"/{rel}", pattern) for pattern in omit)


def build_report() -> dict:
    source, omit = _read_coveragerc()
    source_set = set(source)

    by_package: dict[str, dict[str, int]] = {}
    for path in _application_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        package = rel.split("/")[0] if "/" in rel else "(root)"
        loc = _statement_count(path)
        if not loc:
            continue
        entry = by_package.setdefault(package, {"loc": 0, "in_source": 0, "omitted": 0})
        entry["loc"] += loc
        if package in source_set or rel in source_set:
            entry["in_source"] += loc
            if _omitted(rel, omit):
                entry["omitted"] += loc

    total = sum(p["loc"] for p in by_package.values())
    in_source = sum(p["in_source"] for p in by_package.values())
    omitted = sum(p["omitted"] for p in by_package.values())
    measured = in_source - omitted

    return {
        "total_application_loc": total,
        "in_source_loc": in_source,
        "omitted_from_source_loc": omitted,
        "measured_loc": measured,
        "measured_share_pct": round(100.0 * measured / total, 1) if total else 0.0,
        "source_packages": sorted(source_set),
        "unmeasured_packages": sorted(
            (name, p["loc"])
            for name, p in by_package.items()
            if name not in source_set and p["loc"] >= _MIN_PACKAGE_LOC
        ),
        "omit_patterns": omit,
        "by_package": {k: v for k, v in sorted(by_package.items(), key=lambda kv: -kv[1]["loc"])},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Report what the coverage gate measures")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-under-share", type=float, default=None)
    args = ap.parse_args(argv)

    report = build_report()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("HOPEFX coverage SCOPE report\n" + "=" * 62)
        print("A coverage percentage is a fraction of what the tool was pointed at.")
        print("This is what it was pointed at.\n")
        print(f"  application statements          {report['total_application_loc']:>8,}")
        print(f"  inside [run] source             {report['in_source_loc']:>8,}")
        print(f"  removed by omit, inside source  {report['omitted_from_source_loc']:>8,}")
        print(
            f"  ACTUALLY MEASURED               {report['measured_loc']:>8,}"
            f"   ({report['measured_share_pct']}% of the application)"
        )
        print("-" * 62)
        print("Largest packages the gate never sees:")
        for name, loc in sorted(report["unmeasured_packages"], key=lambda kv: -kv[1])[:12]:
            print(f"   {loc:>8,}  {name}/")
        print("-" * 62)
        print("Whatever the coverage figure says, it says it about the measured")
        print("subset above — not about the application.")

    if args.fail_under_share is not None and report["measured_share_pct"] < args.fail_under_share:
        print(
            f"\nFAIL: the gate measures {report['measured_share_pct']}% of the application, "
            f"below the required {args.fail_under_share}%.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
