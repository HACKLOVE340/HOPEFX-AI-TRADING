# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Platform Engineering — the Code Auditor's read tools. Spec §4 Cluster A.

Three actions here; `propose_fix` is declared without a handler for the same
reason `propose_derisk` is — a proposal needs somewhere to land that a human
reviews, and inventing that in passing is how a proposal becomes an action
nobody approved.

Two design points that are safety properties rather than style:

**`run_tests` is bounded by construction.** An agent that can spawn the full
suite on a box that also executes trades starves the trading engine of CPU —
the same argument that makes the local model runtime refuse an oversized tier.
It requires an explicit target, refuses one that escapes the repository, and
enforces a timeout. A tool that does something enormous when you forget an
argument will eventually do something enormous.

**`check_broken_imports` walks the parse tree.** F255 in this repository was a
checker that read docstrings as source; a regex over import lines would flag
every module named inside a comment or a string literal. Only the AST knows an
import is an import.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import subprocess  # nosec B404 - fixed argv, no shell; see _default_run
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

#: A test run an agent starts must not outlive the operator's patience or the
#: trading engine's CPU.
TEST_TIMEOUT_S: Final = 300.0

#: Directories with nothing to audit, skipped so a scan of the tree does not
#: spend its time in site-packages.
_SKIP_DIRS: Final = frozenset({".venv", "node_modules", "__pycache__", ".git", "build", "dist"})


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    """No answer keys. An unavailable check must not report a result."""
    return {"available": False, "reason": reason, **extra}


# ── imports ──────────────────────────────────────────────────────────────────


def _module_resolves(name: str) -> bool:
    """Whether `name` can be found without importing it.

    find_spec, not import: importing to test an import runs module-level code,
    and this is a read-only audit tool that must not have side effects on the
    thing it is auditing.
    """
    root = name.split(".")[0]
    if root in sys.builtin_module_names:
        return True
    try:
        return importlib.util.find_spec(root) is not None
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        return False


def check_broken_imports(*, root: str = ".", **_: Any) -> dict[str, Any]:
    """Every import in the tree that does not resolve."""
    base = Path(root)
    if not base.exists():
        return _unavailable("root_not_found", root=root)

    broken: list[dict[str, Any]] = []
    unparseable: list[dict[str, str]] = []
    scanned = 0
    seen_missing: set[str] = set()

    for path in sorted(base.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            # A file that will not parse is a finding, not something to skip
            # quietly — skipping is how it survives a hundred audits.
            unparseable.append({"file": str(path), "error": f"line {exc.lineno}: {exc.msg}"})
            continue
        except OSError as exc:
            unparseable.append({"file": str(path), "error": str(exc)})
            continue

        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # A relative import resolves against the package, not sys.path.
                if node.level:
                    continue
                names = [node.module] if node.module else []
            for name in names:
                if not name or _module_resolves(name):
                    continue
                key = f"{path}:{name}"
                if key in seen_missing:
                    continue
                seen_missing.add(key)
                broken.append(
                    {
                        "file": str(path),
                        "line": getattr(node, "lineno", 0),
                        "module": name,
                    }
                )

    return {
        "available": True,
        "root": root,
        "files_scanned": scanned,
        "broken": broken,
        "unparseable": unparseable,
    }


# ── tests ────────────────────────────────────────────────────────────────────


def _target_is_safe(target: str) -> bool:
    """Refuse a target that escapes the repository or reaches an absolute path."""
    cleaned = target.strip()
    if not cleaned or cleaned.startswith("-") or cleaned.startswith("/"):
        return False
    return ".." not in Path(cleaned).parts


def _default_run(argv: list[str], timeout: float) -> dict[str, Any]:
    completed = subprocess.run(  # nosec B603 - fixed argv, no shell
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-2000:],
    }


def run_tests(
    *,
    target: str = "",
    timeout_s: float = TEST_TIMEOUT_S,
    run: Callable[[list[str], float], dict[str, Any]] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Run a BOUNDED selection of the test suite and report the result.

    Refuses without a target rather than running everything: this box also
    executes trades, and a full suite started by an agent that forgot an
    argument is CPU the trading engine no longer has.
    """
    if not target.strip():
        return _unavailable("target_required: name a test file, directory or -k expression")
    if not _target_is_safe(target):
        return _unavailable("unsafe_target: must be a relative path inside the repository", target=target)

    runner = run or _default_run
    argv = [sys.executable, "-m", "pytest", target, "-q", "--timeout=60", "-p", "no:randomly"]
    try:
        outcome = runner(argv, timeout_s)
    except Exception as exc:
        # A timeout is a real answer about a slow suite, distinct from a
        # failing one, so it is reported as unavailable-with-reason rather
        # than dressed up as a red run.
        logger.warning("platform_engineering.run_tests: %s failed (%s)", target, exc)
        return _unavailable(f"run_failed: {type(exc).__name__}: {exc}", target=target)

    return {
        "available": True,
        "target": target,
        "passed": int(outcome.get("returncode", 1)) == 0,
        "returncode": outcome.get("returncode"),
        "output": str(outcome.get("stdout", ""))[-4000:],
    }


# ── secrets ──────────────────────────────────────────────────────────────────


def _default_secret_scan(baseline_path: str = ".secrets.baseline") -> list[dict[str, Any]]:
    """Findings from the repository's own detect-secrets baseline.

    Reads the baseline JSON rather than calling detect_secrets' Python API.
    The first version of this called `baseline.load_baseline_from_file`, which
    does not exist in the installed version — the module exposes `load_from_file`
    — and every test passed anyway because they all injected a fake scanner.
    A handler nothing ever executes is not a handler.

    The committed file format is small and stable, and reading it directly means
    this does not break again when the library renames a function.
    """
    import json

    data = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    findings: list[dict[str, Any]] = []
    for filename, secrets in (data.get("results") or {}).items():
        for secret in secrets or []:
            findings.append(
                {
                    "filename": filename,
                    "line_number": secret.get("line_number", 0),
                    "type": secret.get("type", ""),
                }
            )
    return findings


def scan_secrets(*, scan: Callable[[], list[dict[str, Any]]] | None = None, **_: Any) -> dict[str, Any]:
    """Committed-credential findings — counts and locations, never values.

    The value of a found credential is deliberately not returned. This answer
    goes into the tool audit log and then into a model's context; putting the
    secret itself in either is a second leak on top of the first.
    """
    scanner = scan or _default_secret_scan
    try:
        findings = list(scanner())
    except Exception as exc:
        logger.warning("platform_engineering.scan_secrets failed (%s)", exc)
        return _unavailable(f"scan_failed: {exc}")

    return {
        "available": True,
        "finding_count": len(findings),
        "findings": [
            {
                "file": str(f.get("filename", "")),
                "line": f.get("line_number", 0),
                "type": str(f.get("type", "")),
            }
            for f in findings[:100]
        ],
    }


__all__ = ["check_broken_imports", "run_tests", "scan_secrets"]
