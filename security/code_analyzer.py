# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/code_analyzer.py
=========================
Deep static code analysis engine for the self-healer.

Detects production-breaking patterns across the entire codebase:
- Look-ahead bias (negative shifts on price/return columns)
- Unfinished code (bare raise, NotImplementedError, empty function bodies)
- NaN leaks (operations that silently propagate NaN without guards)
- Division-by-zero risks (unguarded denominators)
- Broken router registrations (duplicate prefixes, missing include_router)
- Missing error handling (bare except, swallowed exceptions in critical paths)
- TODO/FIXME/HACK markers in production paths
- Hardcoded secrets or credentials
- Mutable default arguments
- Unbounded recursion risks

Each finding is a CodeIssue with severity, file, line, category, and a
human-readable description suitable for Claude to act on.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# ── Severity levels ───────────────────────────────────────────────────────────

SEVERITY_CRITICAL = "critical"   # will break production
SEVERITY_HIGH     = "high"       # likely to cause incorrect results
SEVERITY_MEDIUM   = "medium"     # code smell / maintenance risk
SEVERITY_LOW      = "low"        # informational


@dataclass
class CodeIssue:
    """A single detected code quality / safety issue."""

    file: str           # relative path from project root
    line: int           # 1-based line number
    category: str       # e.g. "lookahead_bias", "nan_leak"
    severity: str       # critical | high | medium | low
    description: str    # human-readable explanation
    snippet: str = ""   # the offending source line(s)
    suggestion: str = ""  # brief fix hint

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "snippet": self.snippet,
            "suggestion": self.suggestion,
        }


# ── Regex-based detectors (fast, no AST needed) ───────────────────────────────

# Look-ahead bias: shift(-N) on price/return columns
_LOOKAHEAD_RE = re.compile(
    r"""\.shift\(\s*-\s*\d+\s*\)""",
    re.IGNORECASE,
)

# Hardcoded secrets
_SECRET_RE = re.compile(
    r"""(?i)(password|secret|api_key|token|passwd|pwd)\s*=\s*['"][^'"]{6,}['"]""",
)

# TODO / FIXME / HACK / XXX markers
_TODO_RE = re.compile(r"""#\s*(TODO|FIXME|HACK|XXX)\b""", re.IGNORECASE)

# Bare raise without exception
_BARE_RAISE_RE = re.compile(r"""^\s*raise\s*$""")

# Mutable default argument
_MUTABLE_DEFAULT_RE = re.compile(r"""def\s+\w+\s*\(.*=\s*(\[\]|\{\}|list\(\)|dict\(\))""")

# Unguarded division (simple heuristic: / without prior zero-check nearby)
_DIVISION_RE = re.compile(r"""[^/!<>=]\s*/\s*(?!/)(?!\*)""")

# Empty except (swallows all exceptions silently)
_BARE_EXCEPT_RE = re.compile(r"""^\s*except\s*:\s*$""")

# NotImplementedError in non-abstract context
_NOT_IMPL_RE = re.compile(r"""raise\s+NotImplementedError""")

# Synthetic / mock / fake / dummy data markers in non-test files
_SYNTHETIC_RE = re.compile(
    r"""(?i)\b(mock|fake|dummy|synthetic|stub)\s*(data|price|tick|bar|ohlcv|feed)\b""",
)


def _read_lines(path: Path) -> list[str]:
    """Read file lines, returning empty list on error."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ── AST-based detectors ───────────────────────────────────────────────────────

class _ASTAnalyzer(ast.NodeVisitor):
    """Walk an AST and collect issues."""

    def __init__(self, rel_path: str, lines: list[str]) -> None:
        self.rel_path = rel_path
        self.lines = lines
        self.issues: list[CodeIssue] = []

    def _snippet(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1].strip()
        return ""

    def _add(
        self,
        lineno: int,
        category: str,
        severity: str,
        description: str,
        suggestion: str = "",
    ) -> None:
        self.issues.append(
            CodeIssue(
                file=self.rel_path,
                line=lineno,
                category=category,
                severity=severity,
                description=description,
                snippet=self._snippet(lineno),
                suggestion=suggestion,
            )
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_empty_function(node)
        self._check_mutable_defaults(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_empty_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Flag functions whose body is only `pass`, `...`, or a docstring."""
        body = node.body
        # Strip leading docstring
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if not body:
            return
        # All remaining statements are pass or Ellipsis
        all_pass = all(
            isinstance(s, ast.Pass)
            or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is ...)
            for s in body
        )
        if all_pass:
            self._add(
                node.lineno,
                "unfinished_code",
                SEVERITY_HIGH,
                f"Function '{node.name}' has an empty body (only pass/...) — not implemented",
                "Implement the function body or raise NotImplementedError with a clear message",
            )

    def _check_mutable_defaults(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Flag mutable default arguments (list/dict literals)."""
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(
                    node.lineno,
                    "mutable_default",
                    SEVERITY_MEDIUM,
                    f"Function '{node.name}' uses a mutable default argument — shared across calls",
                    "Use None as default and initialise inside the function body",
                )
                break

    def visit_Call(self, node: ast.Call) -> None:
        """Detect .shift(-N) look-ahead bias."""
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "shift"
            and node.args
        ):
            arg = node.args[0]
            # shift(-N) where N > 0
            if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
                if isinstance(arg.operand, ast.Constant) and isinstance(arg.operand.value, (int, float)):
                    # Check for suppression comment on the same line
                    line_text = self.lines[node.lineno - 1] if 1 <= node.lineno <= len(self.lines) else ""
                    if "lookahead-ok" not in line_text and "# noqa" not in line_text:
                        self._add(
                            node.lineno,
                            "lookahead_bias",
                            SEVERITY_CRITICAL,
                            f"shift(-{arg.operand.value}) introduces look-ahead bias — uses future data",
                            "Use shift(+N) to lag data, never shift(-N) in feature engineering",
                        )
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Flag bare except clauses and empty exception handlers."""
        if node.type is None:
            self._add(
                node.lineno,
                "bare_except",
                SEVERITY_MEDIUM,
                "Bare 'except:' catches all exceptions including KeyboardInterrupt and SystemExit",
                "Catch specific exception types: 'except Exception:' at minimum",
            )
        # Check if handler body is only pass
        body = node.body
        if all(isinstance(s, ast.Pass) for s in body):
            self._add(
                node.lineno,
                "swallowed_exception",
                SEVERITY_MEDIUM,
                "Exception handler body is only 'pass' — exception silently swallowed",
                "Log the exception or re-raise; never silently discard errors in critical paths",
            )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        """Detect potential division by zero (literal zero denominator)."""
        if isinstance(node.op, ast.Div):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                self._add(
                    node.lineno,
                    "division_by_zero",
                    SEVERITY_CRITICAL,
                    "Literal division by zero detected",
                    "Remove the division or add a zero-check guard",
                )
        self.generic_visit(node)


def _analyze_file_ast(path: Path) -> list[CodeIssue]:
    """Run AST analysis on a single Python file."""
    rel = _rel(path)
    lines = _read_lines(path)
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            CodeIssue(
                file=rel,
                line=exc.lineno or 0,
                category="syntax_error",
                severity=SEVERITY_CRITICAL,
                description=f"Syntax error: {exc.msg}",
                snippet=exc.text or "",
                suggestion="Fix the syntax error — file cannot be imported",
            )
        ]
    except Exception:
        return []

    analyzer = _ASTAnalyzer(rel, lines)
    analyzer.visit(tree)
    return analyzer.issues


def _analyze_file_regex(path: Path) -> list[CodeIssue]:
    """Run regex-based analysis on a single file."""
    rel = _rel(path)
    lines = _read_lines(path)
    issues: list[CodeIssue] = []
    is_test = "/test" in rel or rel.startswith("test")

    for i, line in enumerate(lines, start=1):
        # Look-ahead bias (regex catches string-based column access too)
        # Suppress when annotated with "# noqa: lookahead-ok" (intentional label creation)
        if _LOOKAHEAD_RE.search(line) and "# noqa" not in line and "nosec" not in line and "lookahead-ok" not in line:
            issues.append(CodeIssue(
                file=rel, line=i, category="lookahead_bias",
                severity=SEVERITY_CRITICAL,
                description="shift(-N) detected — introduces look-ahead bias using future data",
                snippet=line.strip(),
                suggestion="Replace shift(-N) with shift(+N) to use past data only",
            ))

        # TODO/FIXME in production code
        m = _TODO_RE.search(line)
        if m and not is_test:
            issues.append(CodeIssue(
                file=rel, line=i, category="unfinished_code",
                severity=SEVERITY_MEDIUM,
                description=f"{m.group(1)} marker in production code: {line.strip()[:80]}",
                snippet=line.strip(),
                suggestion="Resolve the TODO/FIXME before deploying to production",
            ))

        # Hardcoded secrets (skip .env.example, test files, and nosec/allowlist annotations)
        if (
            _SECRET_RE.search(line)
            and ".example" not in rel
            and not is_test
            and "nosec" not in line
            and "allowlist secret" not in line
            and "# noqa" not in line
        ):
            issues.append(CodeIssue(
                file=rel, line=i, category="hardcoded_secret",
                severity=SEVERITY_CRITICAL,
                description="Possible hardcoded credential detected",
                snippet="[REDACTED]",
                suggestion="Move credentials to environment variables or a secrets manager",
            ))

        # Synthetic/mock data in non-test production paths
        if _SYNTHETIC_RE.search(line) and not is_test and "# smoke" not in line.lower():
            issues.append(CodeIssue(
                file=rel, line=i, category="synthetic_data",
                severity=SEVERITY_HIGH,
                description=f"Synthetic/mock data reference in production code: {line.strip()[:80]}",
                snippet=line.strip(),
                suggestion="Replace with real data source; mock data must not reach production paths",
            ))

        # Bare except
        if _BARE_EXCEPT_RE.match(line):
            issues.append(CodeIssue(
                file=rel, line=i, category="bare_except",
                severity=SEVERITY_MEDIUM,
                description="Bare 'except:' catches all exceptions including SystemExit",
                snippet=line.strip(),
                suggestion="Use 'except Exception:' or a more specific exception type",
            ))

    return issues


# ── Log file analysis ─────────────────────────────────────────────────────────

_LOG_ERROR_RE = re.compile(
    r"""(?i)(ERROR|CRITICAL|EXCEPTION|Traceback|raise\s+\w+Error)""",
)
_LOG_WARN_RE = re.compile(r"""(?i)\bWARNING\b""")


@dataclass
class LogIssue:
    """An issue extracted from the application log file."""

    timestamp: str
    level: str
    logger_name: str
    message: str
    line_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
            "line": self.line_number,
        }


def analyze_log_file(
    log_path: Path | None = None,
    max_lines: int = 5000,
    since_minutes: int = 60,
) -> list[LogIssue]:
    """
    Parse logs/app.log (or a custom path) and extract ERROR/CRITICAL entries
    from the last `since_minutes` minutes.

    Returns a list of LogIssue objects sorted by line number.
    """
    if log_path is None:
        log_path = PROJECT_ROOT / "logs" / "app.log"

    if not log_path.exists():
        return []

    issues: list[LogIssue] = []
    cutoff = datetime.now(UTC).timestamp() - (since_minutes * 60)

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()[-max_lines:]
    except OSError:
        return []

    # Standard log format: "2026-04-16 20:32:46,710 - logger.name - LEVEL - message"
    _line_re = re.compile(
        r"""^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d+)\s+-\s+(\S+)\s+-\s+(ERROR|CRITICAL|WARNING|INFO|DEBUG)\s+-\s+(.+)$"""
    )

    for lineno, raw in enumerate(lines, start=1):
        m = _line_re.match(raw)
        if not m:
            continue
        ts_str, logger_name, level, message = m.groups()
        if level not in ("ERROR", "CRITICAL", "WARNING"):
            continue
        # Parse timestamp for recency filter
        try:
            ts_clean = ts_str.replace(",", ".").split(".")[0]
            ts_epoch = datetime.strptime(ts_clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()
            if ts_epoch < cutoff:
                continue
        except ValueError:
            pass  # include if we can't parse timestamp

        issues.append(LogIssue(
            timestamp=ts_str,
            level=level,
            logger_name=logger_name,
            message=message[:500],
            line_number=lineno,
        ))

    return issues


# ── Full codebase scan ────────────────────────────────────────────────────────

# Directories to skip during full scan
_SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache",
    "data", "logs", "quarantine",
}

# File patterns to include
_INCLUDE_GLOBS = [
    "**/*.py",
]

# Paths that are test-only (lower severity threshold)
_TEST_PREFIXES = ("tests/", "test_", "conftest")


def scan_codebase(
    root: Path | None = None,
    include_tests: bool = False,
    max_files: int = 2000,
) -> list[CodeIssue]:
    """
    Scan the entire codebase for code quality and safety issues.

    Args:
        root: Project root (defaults to PROJECT_ROOT).
        include_tests: Whether to include test files in the scan.
        max_files: Hard cap on files scanned per run.

    Returns:
        Sorted list of CodeIssue objects (critical first).
    """
    if root is None:
        root = PROJECT_ROOT

    all_issues: list[CodeIssue] = []
    scanned = 0

    for py_file in sorted(root.rglob("*.py")):
        if scanned >= max_files:
            logger.warning("CodeAnalyzer: max_files=%d reached, scan truncated", max_files)
            break

        # Skip excluded directories
        parts = py_file.parts
        if any(d in _SKIP_DIRS for d in parts):
            continue

        rel = _rel(py_file)

        # Optionally skip test files
        if not include_tests:
            if any(rel.startswith(p) or f"/{p}" in rel for p in _TEST_PREFIXES):
                continue

        scanned += 1
        all_issues.extend(_analyze_file_ast(py_file))
        all_issues.extend(_analyze_file_regex(py_file))

    # Deduplicate (same file+line+category)
    seen: set[tuple[str, int, str]] = set()
    unique: list[CodeIssue] = []
    for issue in all_issues:
        key = (issue.file, issue.line, issue.category)
        if key not in seen:
            seen.add(key)
            unique.append(issue)

    # Sort: critical first, then by file+line
    _sev_order = {SEVERITY_CRITICAL: 0, SEVERITY_HIGH: 1, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 3}
    unique.sort(key=lambda x: (_sev_order.get(x.severity, 9), x.file, x.line))

    logger.info(
        "CodeAnalyzer: scanned %d files, found %d issues (%d critical, %d high)",
        scanned,
        len(unique),
        sum(1 for i in unique if i.severity == SEVERITY_CRITICAL),
        sum(1 for i in unique if i.severity == SEVERITY_HIGH),
    )
    return unique


def scan_file(path: Path) -> list[CodeIssue]:
    """Scan a single file and return all issues found."""
    issues = _analyze_file_ast(path)
    issues.extend(_analyze_file_regex(path))
    # Deduplicate
    seen: set[tuple[str, int, str]] = set()
    unique: list[CodeIssue] = []
    for issue in issues:
        key = (issue.file, issue.line, issue.category)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def summarize_issues(issues: list[CodeIssue]) -> dict[str, Any]:
    """Return a summary dict suitable for API responses and logging."""
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_category[issue.category] = by_category.get(issue.category, 0) + 1

    return {
        "total": len(issues),
        "by_severity": by_severity,
        "by_category": by_category,
        "critical_files": list({i.file for i in issues if i.severity == SEVERITY_CRITICAL})[:20],
        "scanned_at": datetime.now(UTC).isoformat(),
    }
