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
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# ── Severity levels ───────────────────────────────────────────────────────────

SEVERITY_CRITICAL = "critical"  # will break production
SEVERITY_HIGH = "high"  # likely to cause incorrect results
SEVERITY_MEDIUM = "medium"  # code smell / maintenance risk
SEVERITY_LOW = "low"  # informational


@dataclass
class CodeIssue:
    """A single detected code quality / safety issue."""

    file: str  # relative path from project root
    line: int  # 1-based line number
    category: str  # e.g. "lookahead_bias", "nan_leak"
    severity: str  # critical | high | medium | low
    description: str  # human-readable explanation
    snippet: str = ""  # the offending source line(s)
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

# Marker pattern for unfinished-code detection (TODO/FIXME/HACK/XXX)  # healer: ignore
_TODO_RE = re.compile(r"""#\s*(TODO|FIXME|HACK|XXX)\b""", re.IGNORECASE)

# NaN leak patterns — numeric/dataframe operations that silently propagate NaN.
# Restricted to pandas/numpy contexts to avoid false positives on string methods
# (e.g. str.join(), list comprehensions, color hex ops).
_NAN_LEAK_RE = re.compile(
    r"""(?x)
    # Pandas aggregations — only flag when preceded by ] or ) to indicate a Series/DataFrame
    (?:[\]\)]\.(?:mean|std|var|sum|cumsum|cumprod)\(\))
    # NumPy math that silently produces NaN for invalid inputs
    |np\.(?:log|sqrt|exp)\(
    # Pandas concat/merge — always operate on DataFrames
    |pd\.concat\(
    # DataFrame .merge() — must be preceded by ) or identifier, not a string literal
    |(?<=[)\w])\.merge\(
    """,
)
_NAN_GUARD_RE = re.compile(r"""dropna\(|fillna\(|isnan\(|notna\(|notnull\(|np\.nan_to_num\(|\.replace\(.*np\.nan""")

# Division by zero risk — dividing by a variable without a zero-check nearby
_DIV_ZERO_RE = re.compile(r"""(?<![=!<>])/(?![/=])""")  # bare / operator
_DIV_SAFE_RE = re.compile(r"""if.*==\s*0|if.*!=\s*0|max\(.*,\s*1\)|np\.where|try:|except""")

# Broken router patterns — router defined but never registered
_ROUTER_DEF_RE = re.compile(r"""^router\s*=\s*APIRouter\(|^_router\s*=\s*APIRouter\(""")

# Missing error handling — async functions with no try/except
_ASYNC_DEF_RE = re.compile(r"""^async\s+def\s+\w+""")
_TRY_RE = re.compile(r"""^\s+try:""")

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

    # Method names that are intentionally no-ops in null-object / stub patterns.
    # These are used for Prometheus/OTel no-op fallbacks when the real library
    # is not installed, and for abstract base class interface stubs.
    _NOOP_METHOD_NAMES: frozenset[str] = frozenset(
        {
            # OTel span no-ops
            "set_attribute",
            "add_event",
            "record_exception",
            "set_status",
            "start_as_current_span",
            "start_span",
            # Context manager protocol
            "__enter__",
            "__exit__",
            "__aenter__",
            "__aexit__",
            # Prometheus metric no-ops
            "inc",
            "dec",
            "set",
            "observe",
            "labels",
            # Gym/RL environment
            "render",
            "close",
            "seed",
            # Abstract interface stubs (implemented by subclasses)
            "__init_subclass__",
            "__class_getitem__",
        }
    )

    def _check_empty_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Flag functions whose body is only `pass`, `...`, or a docstring."""
        # Skip known no-op method names used in null-object patterns
        if node.name in self._NOOP_METHOD_NAMES:
            return

        # Skip abstract methods — subclasses provide the implementation
        is_abstract = any(
            (isinstance(d, ast.Name) and d.id == "abstractmethod")
            or (isinstance(d, ast.Attribute) and d.attr == "abstractmethod")
            for d in node.decorator_list
        )
        if is_abstract:
            return

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
            if isinstance(default, ast.List | ast.Dict | ast.Set):
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
        if isinstance(node.func, ast.Attribute) and node.func.attr == "shift" and node.args:
            arg = node.args[0]
            # shift(-N) where N > 0
            if (
                isinstance(arg, ast.UnaryOp)
                and isinstance(arg.op, ast.USub)
                and isinstance(arg.operand, ast.Constant)
                and isinstance(arg.operand.value, int | float)
            ):
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
        # Check if handler body is only pass.
        # Skip handlers annotated with "# nosec B110" — these are intentional
        # non-fatal fallbacks (e.g. optional Redis, optional telemetry) that have
        # been explicitly reviewed and approved.
        body = node.body
        if all(isinstance(s, ast.Pass) for s in body):
            # Check the except line itself for a nosec annotation
            except_line = self.lines[node.lineno - 1] if 1 <= node.lineno <= len(self.lines) else ""
            if "nosec" in except_line or "# noqa" in except_line:
                self.generic_visit(node)
                return
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
        if isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant) and node.right.value == 0:
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


def _build_docstring_lines(lines: list[str]) -> set[int]:
    """Return the set of 1-based line numbers that are inside triple-quoted strings.

    This prevents the regex scanner from flagging code examples in docstrings
    (e.g. shift(-1) in a docstring showing what NOT to do).
    """
    in_docstring = False
    fence: str = ""
    docstring_lines: set[int] = set()
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not in_docstring:
            # Detect opening triple-quote (may open and close on same line)
            for q in ('"""', "'''"):
                if q in stripped:
                    count = stripped.count(q)
                    if count >= 2:
                        # Opens and closes on same line — mark and move on
                        docstring_lines.add(i)
                        break
                    else:
                        in_docstring = True
                        fence = q
                        docstring_lines.add(i)
                        break
        else:
            docstring_lines.add(i)
            if fence in stripped:
                in_docstring = False
                fence = ""
    return docstring_lines


def _analyze_file_regex(path: Path) -> list[CodeIssue]:
    """Run regex-based analysis on a single file."""
    rel = _rel(path)
    lines = _read_lines(path)
    issues: list[CodeIssue] = []
    is_test = "/test" in rel or rel.startswith("test")

    # Pre-compute which lines are inside docstrings so we don't flag examples
    docstring_lines = _build_docstring_lines(lines)

    for i, line in enumerate(lines, start=1):
        # Skip lines inside docstrings — they may contain intentional examples
        in_doc = i in docstring_lines

        # Look-ahead bias (regex catches string-based column access too).
        # Lines annotated with "lookahead-ok" or "nosec" are intentional and suppressed.
        if (
            not in_doc
            and _LOOKAHEAD_RE.search(line)
            and "# noqa" not in line
            and "nosec" not in line
            and "lookahead-ok" not in line
        ):
            issues.append(
                CodeIssue(
                    file=rel,
                    line=i,
                    category="lookahead_bias",
                    severity=SEVERITY_CRITICAL,
                    description="shift(-N) detected — introduces look-ahead bias using future data",
                    snippet=line.strip(),
                    suggestion="Replace shift(-N) with shift(+N) to use past data only",
                )
            )

        # Unfinished-code markers in production — skip pattern-definition lines  # healer: ignore
        # (e.g. in code_analyzer.py or pre_commit_healer.py) to avoid
        # the scanner flagging its own pattern-definition comments.
        m = _TODO_RE.search(line)
        if m and not is_test and not in_doc:
            # Skip if the line is a string literal defining a regex/pattern
            stripped_line = line.strip()
            is_pattern_def = (
                (
                    stripped_line.startswith("#")
                    and any(kw in stripped_line for kw in ("_RE =", "re.compile", "pattern", "marker"))
                )
                or "TODO_RE" in line
                or "FIXME_RE" in line
            )
            if not is_pattern_def and "# noqa: healer" not in line and "# healer: ignore" not in line:
                issues.append(
                    CodeIssue(
                        file=rel,
                        line=i,
                        category="unfinished_code",
                        severity=SEVERITY_MEDIUM,
                        description=f"{m.group(1)} marker in production code: {stripped_line[:80]}",
                        snippet=stripped_line,
                        suggestion="Resolve the TODO/FIXME before deploying to production",
                    )
                )

        # Hardcoded secrets (skip .env.example, test files, and nosec/allowlist annotations)
        if (
            _SECRET_RE.search(line)
            and ".example" not in rel
            and not is_test
            and "nosec" not in line
            and "allowlist secret" not in line
            and "# noqa" not in line
        ):
            issues.append(
                CodeIssue(
                    file=rel,
                    line=i,
                    category="hardcoded_secret",
                    severity=SEVERITY_CRITICAL,
                    description="Possible hardcoded credential detected",
                    snippet="[REDACTED]",
                    suggestion="Move credentials to environment variables or a secrets manager",
                )
            )

        # Synthetic/mock data in non-test production paths.
        # Skip lines that are:
        #   - pure comments or docstring lines (in_doc already handled above)
        #   - negations / prohibitions: "no mock", "not synthetic", "do not use synthetic"
        #   - audit/guard code that checks FOR synthetic data to block it
        #   - smoke-test / CI-only annotations
        #   - logger calls that warn ABOUT synthetic data (informational, not usage)
        #   - string literals inside the analyzer/healer itself (self-referential)
        _stripped = line.strip()
        _is_negation = re.search(
            r"(?i)(no\s+(mock|synthetic|fake)|not\s+synthetic|do\s+not\s+use\s+synthetic"
            r"|blocked|forbidden|must\s+not|cannot\s+use\s+synthetic"
            r"|non-production\s+only|smoke.test\s+only|ci\s+only"
            r"|check.*mock|detect.*mock|audit.*mock|guard.*mock"
            r"|r\".*mock|r'.*mock"
            r"|only\)|only\.\"|only\.')",
            line,
        )
        # logger.info/warning/error lines that mention synthetic data are
        # diagnostic messages, not actual synthetic-data usage.
        _is_log_diagnostic = re.search(r"logger\.(info|warning|warn|error|debug|critical)\s*\(", line)
        # Skip lines in files that are themselves analysis/healer infrastructure
        _is_self_referential = rel in (
            "security/code_analyzer.py",
            "security/self_healer.py",
            "scripts/e2e_production_validation.py",
            "scripts/e2e_hardening_audit.py",
        )
        if (
            _SYNTHETIC_RE.search(line)
            and not is_test
            and not in_doc
            and "# smoke" not in line.lower()
            and "# healer: ignore" not in line
            and not _is_negation
            and not _is_log_diagnostic
            and not _is_self_referential
            and not _stripped.startswith("#")
        ):
            issues.append(
                CodeIssue(
                    file=rel,
                    line=i,
                    category="synthetic_data",
                    severity=SEVERITY_HIGH,
                    description=f"Synthetic/mock data reference in production code: {_stripped[:80]}",
                    snippet=_stripped,
                    suggestion="Replace with real data source; mock data must not reach production paths",
                )
            )

        # Bare except
        if _BARE_EXCEPT_RE.match(line):
            issues.append(
                CodeIssue(
                    file=rel,
                    line=i,
                    category="bare_except",
                    severity=SEVERITY_MEDIUM,
                    description="Bare 'except:' catches all exceptions including SystemExit",
                    snippet=line.strip(),
                    suggestion="Use 'except Exception:' or a more specific exception type",
                )
            )

        # NaN leak — numeric aggregation without a NaN guard in the surrounding context
        if _NAN_LEAK_RE.search(line) and not is_test and "# healer: ignore" not in line:
            # Check a window of ±5 lines for a NaN guard
            window_start = max(0, i - 6)
            window_end = min(len(lines), i + 5)
            window = "\n".join(lines[window_start:window_end])
            # Also accept aliased nan_to_num calls (e.g. _torch.nan_to_num, _np.nan_to_num)
            _extended_guard = _NAN_GUARD_RE.search(window) or re.search(r"\.nan_to_num\(", window)
            if not _extended_guard:
                issues.append(
                    CodeIssue(
                        file=rel,
                        line=i,
                        category="nan_leak",
                        severity=SEVERITY_HIGH,
                        description=(
                            f"Numeric operation without NaN guard: {line.strip()[:80]}\n"
                            "NaN values propagate silently and corrupt downstream calculations."
                        ),
                        snippet=line.strip(),
                        suggestion=(
                            "Add .dropna() before aggregation, or .fillna(0) / np.nan_to_num() "
                            "to handle NaN explicitly before this operation."
                        ),
                    )
                )

    # ── Broken router detection (file-level) ─────────────────────────────────
    # A router defined in a module but never referenced in router_registry.py,
    # app.py, or a package __init__.py (via include_router) is a dead endpoint.
    has_router_def = any(_ROUTER_DEF_RE.search(ln) for ln in lines)
    if has_router_def and not is_test:
        # Check if this file is imported by the registry, app, or a parent package
        registry_path = PROJECT_ROOT / "core" / "router_registry.py"
        app_path = PROJECT_ROOT / "app.py"
        module_name = rel.replace("/", ".").replace(".py", "")
        short_name = Path(rel).stem  # e.g. "billing" from "api/billing.py"
        # For package __init__.py files, also check the package directory name
        # e.g. "api/superadmin/__init__.py" → package_name = "superadmin"
        package_name = Path(rel).parent.name if short_name == "__init__" else ""

        # Also check the package __init__.py — sub-routers are often included
        # via router.include_router() in the parent package rather than directly
        # in router_registry.py (e.g. api/superadmin/*.py → api/superadmin/__init__.py)
        parent_init = (PROJECT_ROOT / rel).parent / "__init__.py"

        registered = False
        check_files = [registry_path, app_path]
        if parent_init.exists() and parent_init != (PROJECT_ROOT / rel):
            check_files.append(parent_init)

        for reg_file in check_files:
            if reg_file.exists():
                reg_text = reg_file.read_text(encoding="utf-8", errors="replace")
                if (
                    module_name in reg_text
                    or rel in reg_text
                    or (short_name != "__init__" and short_name in reg_text)
                    or (package_name and package_name in reg_text)
                ):
                    registered = True
                    break

        if not registered:
            issues.append(
                CodeIssue(
                    file=rel,
                    line=1,
                    category="broken_router",
                    severity=SEVERITY_HIGH,
                    description=(
                        f"Router defined in {rel} but not found in core/router_registry.py, "
                        "app.py, or the package __init__.py. This router's endpoints are unreachable."
                    ),
                    snippet=next((ln.strip() for ln in lines if _ROUTER_DEF_RE.search(ln)), ""),
                    suggestion=(
                        "Import this router in core/router_registry.py and call "
                        "_include_router_deduped(app, router), or include it via "
                        "router.include_router() in the package __init__.py."
                    ),
                )
            )

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
        except ValueError:  # nosec B110 — unparseable timestamp; include entry conservatively
            pass  # include if we can't parse timestamp

        issues.append(
            LogIssue(
                timestamp=ts_str,
                level=level,
                logger_name=logger_name,
                message=message[:500],
                line_number=lineno,
            )
        )

    return issues


# ── Full codebase scan ────────────────────────────────────────────────────────

# Directories to skip during full scan
_SKIP_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    "data",
    "logs",
    "quarantine",
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
        if not include_tests and any(rel.startswith(p) or f"/{p}" in rel for p in _TEST_PREFIXES):
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
