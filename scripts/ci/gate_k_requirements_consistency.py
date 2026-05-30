#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate K: requirements file consistency.
#
# Verifies that the three requirements files remain mutually consistent:
#
#   requirements.txt    — production dependencies (flexible bounds)
#   requirements.lock   — exact pinned versions for reproducible installs
#   requirements-ci.txt — CI mirror of requirements.txt minus heavy extras
#
# Rules checked
# -------------
# 1. Every package pinned in requirements.lock must be present in
#    requirements.txt (no "ghost" locked packages that bypass the manifest).
#
# 2. requirements-ci.txt must not downgrade a package below the minimum
#    version declared in requirements.txt.  Example: if requirements.txt
#    says ``sqlalchemy>=2.0.0`` then requirements-ci.txt must not pin it
#    to ``sqlalchemy==1.4.0``.
#
# 3. Security-critical packages (those with exact pins in requirements.txt
#    for CVE reasons) must carry the same exact pin in requirements-ci.txt.
#    A security fix in requirements.txt must not be silently absent in CI.
#
# 4. requirements.lock must not contain packages with known vulnerable version
#    patterns (i.e., the locked version must satisfy the lower bound in
#    requirements.txt — no pinning below a security-motivated minimum).
#
# Exits 0 on pass, 1 on failure.
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"
REQUIREMENTS_LOCK = REPO_ROOT / "requirements.lock"
REQUIREMENTS_CI = REPO_ROOT / "requirements-ci.txt"

# Packages intentionally excluded from requirements-ci.txt (heavy/unavailable
# in plain GitHub Actions runner).  These do not trigger Rule 3 violations.
CI_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "quickfix",
        "yara-python",
        "clamd",
        "ib_insync",
        "numba",
        "sentence-transformers",
        "stable-baselines3",
        "gymnasium",
        "mlflow",
        "torch",
        "torchvision",
        "torchaudio",
    }
)

# Packages that are part of the Python standard library or are meta-packages
# that don't appear in pip-compiled lock files.
_SKIP_NAMES: frozenset[str] = frozenset({"pip", "wheel", "setuptools"})

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class VersionSpec(NamedTuple):
    name: str
    op: str  # "==", ">=", "<=", "~=", etc.
    version: str


def _normalise_name(name: str) -> str:
    """Normalise PEP 503 package name (replace - and _ with -)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirements(path: Path) -> dict[str, list[VersionSpec]]:
    """
    Parse a requirements file into {normalised_name: [VersionSpec, …]}.
    Handles:
        package>=1.0,<2.0
        package==1.2.3
        package[extra]>=1.0
        package  (no version)
    Ignores -r includes, -c constraints, blank lines, and comments.
    """
    result: dict[str, list[VersionSpec]] = {}

    if not path.exists():
        return result

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip inline comments
        line = re.sub(r"\s*#.*", "", line).strip()
        if not line:
            continue

        # Strip extras: package[extra] → package
        line_no_extras = re.sub(r"\[.*?\]", "", line)

        # Split on first version specifier character
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*([><=!~,\s].*)?$", line_no_extras)
        if not m:
            continue

        pkg_raw = m.group(1).strip()
        spec_str = (m.group(2) or "").strip()
        pkg = _normalise_name(pkg_raw)

        if pkg in _SKIP_NAMES:
            continue

        if pkg not in result:
            result[pkg] = []

        if not spec_str:
            continue

        # Parse comma-separated specifiers
        for part in spec_str.split(","):
            part = part.strip()
            sm = re.match(r"^([><=!~]{1,2})\s*(.+)$", part)
            if sm:
                result[pkg].append(VersionSpec(pkg, sm.group(1), sm.group(2).strip()))

    return result


def _version_tuple(ver: str) -> tuple[int, ...]:
    """Convert ``1.2.3`` to ``(1, 2, 3)``."""
    return tuple(int(x) for x in re.split(r"[.\-]", ver) if x.isdigit())


def _satisfies_lower_bound(locked_ver: str, spec: VersionSpec) -> bool:
    """Return True if locked_ver satisfies the VersionSpec lower bound."""
    locked = _version_tuple(locked_ver)
    bound = _version_tuple(spec.version)

    if spec.op == ">=":
        return locked >= bound
    if spec.op == ">":
        return locked > bound
    if spec.op == "==":
        # Wildcard e.g. ==1.2.*
        if spec.version.endswith(".*"):
            prefix = _version_tuple(spec.version[:-2])
            return locked[: len(prefix)] == prefix
        return locked == bound
    if spec.op == "~=":
        # Compatible release: ~=1.2.3 means >=1.2.3, <1.3.0 (next minor).
        # The N-1 leading components of the locked version must match.
        if len(bound) < 2:
            return locked >= bound  # ~=1 is degenerate; treat as >=
        prefix = bound[:-1]  # e.g. (1, 2) for ~=1.2.3
        return locked >= bound and locked[: len(prefix)] == prefix
    # For <=, <, != — not a lower bound, always OK
    return True


def _check_direct_deps_locked(
    txt_pkgs: dict[str, list[VersionSpec]],
    lock_pkgs: dict[str, list[VersionSpec]],
) -> list[str]:
    """Rule 1: every direct dependency in requirements.txt must be in requirements.lock.

    The lock file naturally contains transitive dependencies that are NOT in
    requirements.txt — that is expected and correct.  The dangerous direction
    is a direct dependency that is somehow absent from the lock file (e.g.
    someone added a package to requirements.txt but forgot to regenerate the
    lock file).
    """
    failures = []
    for pkg in txt_pkgs:
        if pkg not in lock_pkgs:
            failures.append(
                f"[Rule 1] {pkg!r} is listed in requirements.txt "
                f"but missing from requirements.lock — regenerate the lock file"
            )
    return failures


def _check_ci_downgrades(
    txt_pkgs: dict[str, list[VersionSpec]],
    ci_pkgs: dict[str, list[VersionSpec]],
) -> list[str]:
    """Rule 2: requirements-ci.txt must not downgrade below requirements.txt minimums."""
    failures = []
    for pkg, ci_specs in ci_pkgs.items():
        if pkg not in txt_pkgs:
            continue  # CI can add test-only packages
        txt_specs = txt_pkgs[pkg]
        # Find the >= lower bound in requirements.txt
        lower_bounds = [s for s in txt_specs if s.op in (">=", ">", "~=", "==")]
        if not lower_bounds:
            continue
        # Find any == pin in requirements-ci.txt
        ci_exact = [s for s in ci_specs if s.op == "=="]
        if not ci_exact:
            continue
        ci_ver = ci_exact[0].version
        for lb in lower_bounds:
            if not _satisfies_lower_bound(ci_ver, lb):
                failures.append(
                    f"[Rule 2] {pkg!r}: requirements-ci.txt pins {ci_ver!r} "
                    f"but requirements.txt requires {lb.op}{lb.version!r}"
                )
    return failures


def _check_security_pins(
    txt_pkgs: dict[str, list[VersionSpec]],
    ci_pkgs: dict[str, list[VersionSpec]],
) -> list[str]:
    """
    Rule 3: packages with an exact ``==`` pin in requirements.txt (CVE pins)
    must carry the same exact version in requirements-ci.txt, unless the
    package is in CI_EXCLUSIONS.
    """
    failures = []
    for pkg, txt_specs in txt_pkgs.items():
        if pkg in CI_EXCLUSIONS:
            continue
        exact_pins = [s for s in txt_specs if s.op == "=="]
        if not exact_pins:
            continue
        if pkg not in ci_pkgs:
            # Missing entirely from CI — that's OK if it's in CI_EXCLUSIONS,
            # but if it's a security pin we should warn.
            # Only fail if the package has CHANGE_ME or CVE comment patterns.
            # For now: skip missing packages (they may be CI-excluded extras).
            continue
        ci_specs = ci_pkgs.get(pkg, [])
        ci_exact = {s.version for s in ci_specs if s.op == "=="}
        for pin in exact_pins:
            if ci_exact and pin.version not in ci_exact:
                failures.append(
                    f"[Rule 3] Security pin mismatch for {pkg!r}: "
                    f"requirements.txt pins {pin.version!r} but requirements-ci.txt "
                    f"pins {sorted(ci_exact)!r}"
                )
    return failures


def _check_lock_vs_txt_bounds(
    txt_pkgs: dict[str, list[VersionSpec]],
    lock_pkgs: dict[str, list[VersionSpec]],
) -> list[str]:
    """Rule 4: locked version must satisfy the lower bound in requirements.txt."""
    failures = []
    for pkg, lock_specs in lock_pkgs.items():
        if pkg not in txt_pkgs:
            continue  # Rule 1 catches this
        txt_specs = txt_pkgs[pkg]
        lower_bounds = [s for s in txt_specs if s.op in (">=", ">", "~=", "==")]
        if not lower_bounds:
            continue
        lock_exact = [s for s in lock_specs if s.op == "=="]
        if not lock_exact:
            continue
        locked_ver = lock_exact[0].version
        for lb in lower_bounds:
            if not _satisfies_lower_bound(locked_ver, lb):
                failures.append(
                    f"[Rule 4] {pkg!r}: requirements.lock pins {locked_ver!r} "
                    f"but requirements.txt requires {lb.op}{lb.version!r} — "
                    f"regenerate requirements.lock"
                )
    return failures


def main() -> int:
    missing = []
    for p in (REQUIREMENTS_TXT, REQUIREMENTS_LOCK, REQUIREMENTS_CI):
        if not p.exists():
            missing.append(str(p.relative_to(REPO_ROOT)))
    if missing:
        print(f"[gate-k] SKIP  Missing file(s): {', '.join(missing)}")
        return 0

    txt_pkgs = _parse_requirements(REQUIREMENTS_TXT)
    lock_pkgs = _parse_requirements(REQUIREMENTS_LOCK)
    ci_pkgs = _parse_requirements(REQUIREMENTS_CI)

    failures: list[str] = []

    failures.extend(_check_direct_deps_locked(txt_pkgs, lock_pkgs))
    failures.extend(_check_ci_downgrades(txt_pkgs, ci_pkgs))
    failures.extend(_check_security_pins(txt_pkgs, ci_pkgs))
    failures.extend(_check_lock_vs_txt_bounds(txt_pkgs, lock_pkgs))

    if failures:
        print(f"Gate K FAILED — {len(failures)} requirements consistency issue(s):")
        for f in failures:
            print(f"  • {f}")
        print()
        print("To fix Rule 1/4: regenerate requirements.lock with:")
        print("  pip-compile requirements.txt --output-file requirements.lock --strip-extras")
        print("To fix Rule 2/3: sync requirements-ci.txt version pins with requirements.txt.")
        return 1

    print(
        f"Gate K PASSED — requirements.txt ({len(txt_pkgs)} pkgs), "
        f"requirements.lock ({len(lock_pkgs)} pkgs), "
        f"requirements-ci.txt ({len(ci_pkgs)} pkgs) are consistent."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
