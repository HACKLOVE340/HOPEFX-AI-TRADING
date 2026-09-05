from __future__ import annotations

"""Fail-closed validation boundary for AI-proposed Python repairs.

The sandbox validates a candidate in a disposable directory and never writes to
application paths. Applying a repair remains owned by SelfHealer and requires
its existing signing, approval, quarantine, and rollback controls.
"""

import ast
import os
import subprocess  # nosec B404 — fixed validation command in disposable directory
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxValidation:
    accepted: bool
    reason_codes: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""


_BANNED_IMPORTS = frozenset({"os", "sys", "subprocess", "socket", "pathlib", "shutil", "ctypes", "importlib", "pickle"})
_BANNED_CALLS = frozenset({"eval", "exec", "compile", "open", "__import__", "input"})


def _static_check(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ("syntax_error",)

    reasons: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in _BANNED_IMPORTS:
                    reasons.append(f"banned_import:{alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".", 1)[0] in _BANNED_IMPORTS:
                reasons.append(f"banned_import:{node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALLS:
            reasons.append(f"banned_call:{node.func.id}")
    return tuple(dict.fromkeys(reasons))


def validate_repair_source(source: str, *, timeout_seconds: float = 5.0) -> SandboxValidation:
    """Validate source without importing it or mutating the repository."""
    if not source.strip():
        return SandboxValidation(False, ("empty_source",))
    static_reasons = _static_check(source)
    if static_reasons:
        return SandboxValidation(False, static_reasons)

    with tempfile.TemporaryDirectory(prefix="hopefx-repair-") as temp_dir:
        candidate = Path(temp_dir) / "candidate.py"
        candidate.write_text(source, encoding="utf-8")
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        try:
            result = subprocess.run(  # nosec B603 — executable and args are constants
                [sys.executable, "-B", "-m", "py_compile", str(candidate)],
                cwd=temp_dir,
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SandboxValidation(False, ("validation_timeout",))
        if result.returncode != 0:
            return SandboxValidation(False, ("compile_failed",), result.stdout, result.stderr)
    return SandboxValidation(True, ("validated_in_disposable_directory",), result.stdout, result.stderr)


__all__ = ["SandboxValidation", "validate_repair_source"]
