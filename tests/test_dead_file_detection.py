# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_dead_file_detection.py
==================================
Dead-file gate: fail the build when Python files in the project root
contain markers that indicate the file is superseded or unresolved.

Markers detected
----------------
  STATUS: SUPERSEDED
      The file has been explicitly marked as dead code that has been
      replaced by a production implementation elsewhere.

  TODO: Either wire ... or delete
      The file contains a deferred decision that was never resolved.
      The author acknowledged the file is either dead or needs wiring
      but left the decision open.

Why this matters
----------------
Two root-level files accumulated these markers without being resolved:

  enhanced_smart_router.py   — STATUS: SUPERSEDED (replaced by execution/smart_router.py)
  enhanced_realtime_engine.py — STATUS: SUPERSEDED (replaced by data_feed/engine.py)

Dead files in the root directory:
  - Confuse new contributors about which implementation is canonical
  - Diverge silently from the production code they were meant to replace
  - Accumulate import-time side effects that can interfere with tests
  - Inflate the apparent codebase size

Resolution policy
-----------------
When this test fails, you must do ONE of:

  A. Wire the file into production:
       - Import and use the class/function in the appropriate startup path
       - Remove the STATUS: SUPERSEDED and TODO: Either wire markers
       - Add a test that exercises the wired code path

  B. Delete the file:
       - git rm <filename>
       - If the file contains genuinely useful reference code, move it to
         docs/reference/ or a dedicated archive/ directory (not root)

  C. Add to DEAD_FILE_EXEMPTIONS below with a time-boxed justification:
       - Include a target date by which the decision must be made
       - The exemption will be reviewed in the next sprint

Scope
-----
Only Python files directly in the project root are scanned.  Files in
subdirectories (api/, core/, execution/, etc.) are not in scope because
those directories have their own module structure and the markers there
indicate in-progress work rather than abandoned root-level scripts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent

# Marker patterns that indicate a file is dead or has an unresolved decision.
# Each pattern is matched case-insensitively against the full file content.
DEAD_MARKERS: list[re.Pattern] = [
    re.compile(r"STATUS:\s*SUPERSEDED", re.IGNORECASE),
    re.compile(r"TODO:\s*Either\s+wire\b", re.IGNORECASE),
]

# Files explicitly exempted from the dead-marker check.
# Each entry must include a justification and a target resolution date.
# Format: {"filename": "reason — resolve by YYYY-MM-DD"}
DEAD_FILE_EXEMPTIONS: dict[str, str] = {
    # Example (remove when adding a real exemption):
    # "legacy_router.py": "Kept for reference during migration — resolve by 2026-06-01",
}

# ---------------------------------------------------------------------------
# Root file count gate
#
# Root-level .py files are a code smell in a mature project.  Production code
# belongs in packages (api/, core/, execution/, etc.), not the root.
#
# ROOT_FILE_COUNT_CEILING — maximum allowed root .py file count.
# Set to the count at the time this gate was introduced.  Increment only with
# a justification comment when a file genuinely belongs at the root.
# ---------------------------------------------------------------------------
ROOT_FILE_COUNT_CEILING: int = 30  # established 2026-05-15; 30 files at gate introduction

# Exhaustive list of every .py file that is permitted to exist in the root.
# Adding a new root-level file requires adding it here with a justification.
# This is the canonical record of "intentional root files" for the project.
ROOT_KNOWN_FILES: frozenset[str] = frozenset(
    {
        # ── Package / project infrastructure ──────────────────────────────────
        "__init__.py",  # makes the root a namespace package
        "setup.py",  # legacy setuptools entry point (pyproject.toml preferred)
        "conftest.py",  # pytest root conftest — must be at root for test discovery
        "validation.py",  # pydantic/marshmallow schema validation helpers (shared)
        # ── Application entry points ───────────────────────────────────────────
        "app.py",  # FastAPI application factory — imported by uvicorn
        "run.py",  # CLI entry point: python run.py
        "cli.py",  # Click CLI: hopefx <command>
        "quickstart.py",  # Interactive quickstart wizard for new operators
        "celery_app.py",  # Celery application instance — imported by workers
        # ── Trading engine entry points ────────────────────────────────────────
        "hopefx_engine.py",  # Legacy engine entry point (superseded by core/main_loop.py)
        "trader_full.py",  # Full trader bootstrap (used by docker CMD)
        "kill_switch.py",  # Kill switch singleton — imported by app.py and trading engine
        "forward_test.py",  # Walk-forward test runner (run manually, not in CI)
        "real_data_backtest.py",  # Real-data backtest runner (run manually)
        # ── ML / model management ─────────────────────────────────────────────
        "ml_model_trainer.py",  # Model training entry point (run by retrain CI job)
        "enhanced_ml_predictor.py",  # Enhanced predictor (used by ml_model_trainer)
        "enhanced_backtest_engine.py",  # Enhanced backtest (used by real_data_backtest)
        # ── Infrastructure / deployment ────────────────────────────────────────
        "deploy.py",  # Deployment automation script
        "database_init.py",  # One-time DB initialisation (run by entrypoint.sh)
        "update_artifacts.py",  # CI artifact update script
        # ── Monitoring / health ────────────────────────────────────────────────
        "health_check_service.py",  # Health check service (imported by app.py)
        "heartbeat_monitor.py",  # Heartbeat monitor (run as sidecar)
        "prometheus_monitoring.py",  # Prometheus metrics exporter
        # ── Integrations ──────────────────────────────────────────────────────
        "connect_to_life.py",  # Live data connection bootstrap
        "news_filter_integration.py",  # News filter integration (wired into data pipeline)
        "rate_limiting_configuration.py",  # Rate limiting config (imported by app.py)
        "security_service.py",  # Security service (imported by app.py)
        # ── Documentation / tooling ───────────────────────────────────────────
        "api_documentation_generator.py",  # Generates OpenAPI docs
        "comprehensive_test_framework.py",  # Test framework utilities
        "deployment_guide.py",  # Interactive deployment guide
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _root_python_files() -> list[Path]:
    """Return all non-dotfile *.py files directly in REPO_ROOT (non-recursive).

    Dotfiles (e.g. .greptile.py) are excluded — they are tooling configs,
    not production code, and should not be subject to the dead-file or
    root-count gates.
    """
    return sorted(f for f in REPO_ROOT.glob("*.py") if not f.name.startswith("."))


def _scan_root_python_files() -> list[tuple[Path, list[tuple[str, int]]]]:
    """
    Scan all non-dotfile *.py files directly in REPO_ROOT (non-recursive).

    Returns a list of (path, [(marker_text, line_number), ...]) for every
    file that contains at least one dead marker.
    """
    results: list[tuple[Path, list[tuple[str, int]]]] = []

    for py_file in _root_python_files():
        if py_file.name in DEAD_FILE_EXEMPTIONS:
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        hits: list[tuple[str, int]] = []
        for lineno, line in enumerate(content.splitlines(), 1):
            for pattern in DEAD_MARKERS:
                m = pattern.search(line)
                if m:
                    hits.append((line.strip(), lineno))
                    break  # one hit per line is enough

        if hits:
            results.append((py_file, hits))

    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_dead_files_in_root() -> None:
    """
    No Python file in the project root may contain STATUS: SUPERSEDED or
    TODO: Either wire ... or delete.

    Failure means a dead or unresolved file exists in the root directory.
    See the module docstring for the resolution policy.
    """
    dead_files = _scan_root_python_files()

    if not dead_files:
        return  # all clear

    lines: list[str] = [
        f"\n{len(dead_files)} dead/unresolved Python file(s) found in project root.\n"
        "Resolution: wire the file into production, delete it, or add it to\n"
        "DEAD_FILE_EXEMPTIONS in tests/test_dead_file_detection.py with a\n"
        "justification and target resolution date.\n"
    ]

    for path, hits in dead_files:
        lines.append(f"  {path.name}")
        for text, lineno in hits:
            lines.append(f"    line {lineno:4d}: {text[:100]}")

    pytest.fail("\n".join(lines))


def test_exemptions_are_still_present() -> None:
    """
    Every file in DEAD_FILE_EXEMPTIONS must still exist in the root directory.

    A stale exemption entry means the file was deleted (good!) but the
    exemption was not cleaned up.  Remove the entry from DEAD_FILE_EXEMPTIONS.
    """
    stale: list[str] = []
    for filename in DEAD_FILE_EXEMPTIONS:
        if not (REPO_ROOT / filename).exists():
            stale.append(filename)

    if stale:
        pytest.fail(
            f"\n{len(stale)} DEAD_FILE_EXEMPTIONS entry/entries refer to files that "
            "no longer exist.\nRemove them from DEAD_FILE_EXEMPTIONS:\n" + "\n".join(f"  {f}" for f in stale)
        )


def test_root_python_file_count_has_not_grown() -> None:
    """
    The number of Python files in the project root must not exceed the
    established baseline.

    Root-level Python files are a code smell in a mature project — production
    code belongs in packages (api/, core/, execution/, etc.), not the root.
    Every new root-level .py file must be a deliberate decision, not an
    accidental drop.

    Dotfiles (e.g. .greptile.py) are excluded — they are tooling configs.

    When this test fails it means a new .py file was added to the root.
    You must do ONE of:

      A. Move it into the appropriate package directory.
      B. If it genuinely belongs at the root (e.g. conftest.py, setup.py),
         increment ROOT_FILE_COUNT_CEILING below with a justification comment.

    Baseline
    --------
    The ceiling is set to the count at the time this gate was introduced
    (30 files).  It is a ceiling, not an exact count — deletions are fine.
    """
    py_files = _root_python_files()
    count = len(py_files)

    print(
        f"\n[root-file-count] current={count}  ceiling={ROOT_FILE_COUNT_CEILING}\n"
        "Root .py files: " + ", ".join(f.name for f in py_files)
    )

    assert count <= ROOT_FILE_COUNT_CEILING, (
        f"Root Python file count ({count}) exceeds ceiling ({ROOT_FILE_COUNT_CEILING}).\n"
        f"{count - ROOT_FILE_COUNT_CEILING} new file(s) were added to the project root.\n"
        "Move them into the appropriate package directory, or if they genuinely\n"
        "belong at the root, increment ROOT_FILE_COUNT_CEILING in\n"
        "tests/test_dead_file_detection.py with a justification comment.\n\n"
        "Current root .py files:\n" + "\n".join(f"  {f.name}" for f in py_files)
    )


def test_root_python_files_are_known() -> None:
    """
    Every Python file in the project root must be in ROOT_KNOWN_FILES.

    This is a stricter companion to test_root_python_file_count_has_not_grown:
    it catches file renames and new additions by name, not just count.

    Dotfiles (e.g. .greptile.py) are excluded — they are tooling configs.

    When this test fails it means an unknown file appeared in the root.
    Either add it to ROOT_KNOWN_FILES with a justification, or move it into
    a package directory.
    """
    py_files = {f.name for f in _root_python_files()}
    unknown = py_files - ROOT_KNOWN_FILES

    if unknown:
        pytest.fail(
            f"\n{len(unknown)} unknown Python file(s) found in project root.\n"
            "Either move them into a package directory or add them to\n"
            "ROOT_KNOWN_FILES in tests/test_dead_file_detection.py with a\n"
            "justification comment explaining why they belong at the root.\n\n"
            "Unknown files:\n" + "\n".join(f"  {f}" for f in sorted(unknown))
        )

    # Also report files in ROOT_KNOWN_FILES that no longer exist (stale entries)
    stale = ROOT_KNOWN_FILES - py_files
    if stale:
        print(
            f"\n[INFO] {len(stale)} ROOT_KNOWN_FILES entry/entries no longer exist "
            "(file was deleted or moved — remove from ROOT_KNOWN_FILES):\n" + "\n".join(f"  {f}" for f in sorted(stale))
        )


def test_dead_markers_not_in_subdirectory_modules() -> None:
    """
    Informational scan: report STATUS: SUPERSEDED markers found in
    subdirectory modules (api/, core/, execution/, etc.).

    This test does NOT fail the build — subdirectory markers indicate
    in-progress work rather than abandoned root-level scripts.  The output
    is printed to the CI log so the team can track and resolve them.
    """
    subdirs = [
        "api",
        "core",
        "execution",
        "brokers",
        "data",
        "data_feed",
        "ml",
        "risk",
        "strategy",
        "strategies",
        "utils",
    ]

    found: list[str] = []
    for subdir in subdirs:
        subdir_path = REPO_ROOT / subdir
        if not subdir_path.is_dir():
            continue
        for py_file in sorted(subdir_path.rglob("*.py")):
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
                for pattern in DEAD_MARKERS:
                    if pattern.search(line):
                        rel = py_file.relative_to(REPO_ROOT)
                        found.append(f"  {rel}:{lineno}  {line.strip()[:80]}")
                        break

    if found:
        print(
            f"\n[INFO] {len(found)} STATUS: SUPERSEDED / TODO: Either wire marker(s) "
            "found in subdirectory modules (not blocking):\n" + "\n".join(found)
        )
    else:
        print("\n[INFO] No dead markers found in subdirectory modules.")
