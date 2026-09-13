# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Walk every Python file in the repository — the AI's own included — and report.

## Why a parser and not a model

A model call per file, across seventeen hundred files, on a loop meant to stay
awake, is a bill rather than a capability. Its findings would also not be
reproducible: the same file could be clean on Tuesday. So the walk is
deterministic static analysis, and a model is consulted later and per finding,
when there is one specific thing to propose a change for. The paid step then
sits behind the vault and the approval gate rather than in front of them.

## The checks are this repository's own defect history

Not generic lint — `ruff` already runs and is clean. Each check here is a class
of mistake this codebase has actually made:

`dead_control`
    F176 and F260. A guard that exists, reads correctly, and has no production
    caller. `scripts/invariant_coverage.py` "certified" three components that
    were provably unprotected while it did so. A guard whose only callers are
    its own tests is the same defect wearing a green tick.

`unmeasured_as_zero`
    §22. A probe that fails and returns `0`. Worse than no gauge, because zero
    reads as an idle machine rather than as a missing measurement. `None` with
    a reason is the correct answer, and is not flagged.

`float_money`
    `hopefx-money-precision`. A float carrying a price, quantity, lot size,
    notional, P&L, balance, fee or commission.

`silent_except`
    A swallowed exception with no logging. The failure happened and nobody can
    find out that it did.

`permissive_env_default`
    A control that is OFF when its variable is unset. `HEAL_ALLOW_UNSIGNED_PATCHES`
    is deliberately the other way round — the control is on, and turning it off
    takes an explicit opt-out — and this check finds the ones that are not.

## What it will not do

It cannot act. `ai/improve/` imports nothing from `ai/tools/`, calls nothing
that writes, and a test parses every module here to keep both true. A walker
that could apply what it found would be a self-modifying agent with the vault
and the approval gate standing beside it rather than in front of it.

## A skipped file is named

A file that would not parse and was quietly dropped appears in the report as a
file that was walked and found clean. Every skip carries its path and its
reason, and `files_walked` counts only files actually parsed.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field
from typing import Any, Final

from ai.improve.finding import Finding

_ROOT: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[2]

#: Never walked. Auditing site-packages produces findings nobody here can fix.
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {".venv", "venv", "node_modules", "__pycache__", ".git", "build", "dist", ".mypy_cache", ".ruff_cache"}
)

#: The checks, in the order they are reported.
CHECKS: Final[tuple[str, ...]] = (
    "dead_control",
    "unmeasured_as_zero",
    "float_money",
    "silent_except",
    "permissive_env_default",
)

#: A function whose name starts with one of these is a control: something whose
#: whole purpose is to refuse. Its being uncalled is the F176 defect.
_CONTROL_PREFIXES: Final[tuple[str, ...]] = (
    "verify_",
    "enforce_",
    "assert_",
    "require_",
    "check_",
    "validate_",
    "guard_",
    "catastrophic_",
    "is_safe",
    "can_",
)

#: Names that make a value monetary. Matched as substrings of an identifier.
_MONEY_WORDS: Final[tuple[str, ...]] = (
    "price",
    "qty",
    "quantity",
    "lot",
    "notional",
    "pnl",
    "p_and_l",
    "balance",
    "equity",
    "fee",
    "commission",
    "cost",
    "spread",
    "margin",
    "profit",
    "loss",
)

#: `os.getenv(NAME, DEFAULT)` — the default is the second argument, and a call
#: without one has no default to be permissive about.
_GETENV_WITH_DEFAULT: Final[int] = 2

#: A directory whose files are tests. A caller from here does not make a
#: control live -- that is precisely F176.
_TEST_MARKERS: Final[tuple[str, ...]] = ("tests/", "test_", "_test.py", "conftest.py")


@dataclass(frozen=True)
class WalkReport:
    """What was walked, what was skipped, and what was found.

    `clean` is derived and is False when nothing was checked: a walk that ran no
    checks found nothing, which is not the same as finding nothing wrong.
    """

    files_walked: int = 0
    files_skipped: tuple[tuple[str, str], ...] = ()
    findings: tuple[Finding, ...] = ()
    checks_run: tuple[str, ...] = ()
    #: `(check, reason)` for checks that were asked for and could not be run.
    #: A check dropped without saying so leaves the report reading as though it
    #: had run and found nothing.
    checks_skipped: tuple[tuple[str, str], ...] = ()
    roots: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return bool(self.checks_run) and self.files_walked > 0 and not self.findings

    def summary(self) -> dict[str, Any]:
        by_check: dict[str, int] = {}
        for found in self.findings:
            by_check[found.check] = by_check.get(found.check, 0) + 1
        return {
            "files_walked": self.files_walked,
            "files_skipped": len(self.files_skipped),
            "skipped_detail": [{"path": p, "reason": r} for p, r in self.files_skipped],
            "findings": len(self.findings),
            "by_check": by_check,
            "checks_run": list(self.checks_run),
            "checks_skipped": [{"check": c, "reason": r} for c, r in self.checks_skipped],
            "proposable": sum(1 for f in self.findings if f.proposable),
            "clean": self.clean,
            "roots": list(self.roots),
        }


@dataclass
class _Collected:
    """One pass of parsing, before the cross-file `dead_control` join."""

    findings: list[Finding] = field(default_factory=list)
    #: control name -> (path, line) where it is DEFINED
    controls: dict[str, tuple[str, int]] = field(default_factory=dict)
    #: control name -> whether a non-test file references it
    production_refs: set[str] = field(default_factory=set)
    test_refs: set[str] = field(default_factory=set)


def walk(
    root: pathlib.Path | str | None = None,
    *,
    paths: tuple[str, ...] | None = None,
    checks: tuple[str, ...] | None = None,
) -> WalkReport:
    """Walk `paths` under `root` and report findings.

    `checks` defaults to all of `CHECKS`; passing `()` runs none, and the report
    then says `clean` is False rather than implying a clean bill.
    """
    base = pathlib.Path(root) if root is not None else _ROOT
    active = CHECKS if checks is None else tuple(c for c in checks if c in CHECKS)
    roots = paths or (".",)

    # `dead_control` joins definitions to references across the whole tree. On a
    # partial walk a caller in a directory never entered looks like no caller at
    # all, and the check would report confident "nothing calls this" claims about
    # functions used one directory over. Dropped, and the report says so.
    whole_tree = roots == (".",)
    skipped_checks: list[tuple[str, str]] = []
    if "dead_control" in active and not whole_tree:
        active = tuple(c for c in active if c != "dead_control")
        skipped_checks.append(
            (
                "dead_control",
                "needs a whole-tree walk: on a partial walk a caller in a directory "
                f"not entered ({', '.join(roots)}) is indistinguishable from no caller",
            )
        )

    collected = _Collected()
    skipped: list[tuple[str, str]] = []
    walked = 0

    for target in _python_files(base, roots):
        relative = target.relative_to(base).as_posix()
        try:
            source = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            skipped.append((relative, f"unreadable: {type(exc).__name__}"))
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError) as exc:
            skipped.append((relative, f"would not parse: {type(exc).__name__}"))
            continue

        walked += 1
        lines = source.splitlines()
        _scan(tree, relative, lines, active, collected)

    if "dead_control" in active:
        _join_dead_controls(collected)

    findings = tuple(sorted(collected.findings, key=lambda f: (CHECKS.index(f.check), f.path, f.line)))
    return WalkReport(
        files_walked=walked,
        files_skipped=tuple(skipped),
        findings=findings,
        checks_run=active,
        checks_skipped=tuple(skipped_checks),
        roots=tuple(roots),
    )


def _python_files(base: pathlib.Path, roots: tuple[str, ...]):
    for entry in roots:
        start = base / entry
        if not start.exists():
            continue
        for target in sorted(start.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in target.parts):
                continue
            yield target


def _is_test_path(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1]
    return relative.startswith("tests/") or "/tests/" in relative or name.startswith("test_") or name == "conftest.py"


def _snippet(lines: list[str], line: int, span: int = 2) -> str:
    start = max(0, line - 1 - span)
    return "\n".join(lines[start : line - 1 + span + 1])


def _proposable(relative: str) -> bool:
    from ai.vault import protected

    return not protected.is_protected(relative)


def _scan(tree: ast.AST, relative: str, lines: list[str], active: tuple[str, ...], collected: _Collected) -> None:
    is_test = _is_test_path(relative)
    proposable = _proposable(relative)

    def add(check: str, line: int, claim: str, severity: str = "medium") -> None:
        collected.findings.append(
            Finding(
                check=check,
                path=relative,
                line=line,
                claim=claim,
                snippet=_snippet(lines, line),
                severity=severity,  # type: ignore[arg-type]
                proposable=proposable,
            )
        )

    for node in ast.walk(tree):
        if "dead_control" in active:
            _collect_controls(node, relative, is_test, collected)
        if "silent_except" in active:
            _check_silent_except(node, add)
        if "unmeasured_as_zero" in active:
            _check_unmeasured_zero(node, add)
        if "float_money" in active:
            _check_float_money(node, add)
        if "permissive_env_default" in active:
            _check_permissive_env(node, add)


# ── dead_control ──────────────────────────────────────────────────────────────


def _collect_controls(node: ast.AST, relative: str, is_test: bool, collected: _Collected) -> None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        # A decorated function is reached through its decorator, not by name: a
        # FastAPI route handler has no by-name caller anywhere and is live. The
        # first real run reported api/superadmin/platform.py:validate_platform_config
        # dead, and it is a mounted endpoint.
        if not is_test and not node.decorator_list and node.name.startswith(_CONTROL_PREFIXES):
            collected.controls.setdefault(node.name, (relative, node.lineno))
        return
    name = None
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    if not name or not name.startswith(_CONTROL_PREFIXES):
        return
    (collected.test_refs if is_test else collected.production_refs).add(name)


def _join_dead_controls(collected: _Collected) -> None:
    """A control is dead when nothing outside its own definition calls it.

    The definition site itself registers as neither a production nor a test
    reference, because `_collect_controls` returns before recording a name for a
    `FunctionDef`. A control referenced only from a test path is reported with
    that fact in the claim: tests are exactly what made F176 look covered.
    """
    for name, (path, line) in sorted(collected.controls.items()):
        if name in collected.production_refs:
            continue
        only_tests = name in collected.test_refs
        claim = (
            f"{name} is a control with no production caller; its only references are in tests, "
            "which is the shape of F176 — a predicate that could not fail because nothing ran it"
            if only_tests
            else f"{name} is a control and nothing calls it anywhere; it cannot refuse what it never sees"
        )
        collected.findings.append(
            Finding(
                check="dead_control",
                path=path,
                line=line,
                claim=claim,
                severity="high",
                proposable=_proposable(path),
            )
        )


# ── the single-node checks ────────────────────────────────────────────────────


def _check_silent_except(node: ast.AST, add) -> None:
    if not isinstance(node, ast.ExceptHandler):
        return
    body = node.body
    if len(body) != 1:
        return
    only = body[0]
    if isinstance(only, ast.Pass):
        add(
            "silent_except",
            node.lineno,
            "an exception is swallowed with no log line; the failure happened and nobody can find out that it did",
        )
    elif isinstance(only, ast.Return) and only.value is None:
        add(
            "silent_except",
            node.lineno,
            "an exception returns None with no log line; the caller cannot tell a real None from a failure",
        )


def _check_unmeasured_zero(node: ast.AST, add) -> None:
    if not isinstance(node, ast.ExceptHandler):
        return
    for statement in ast.walk(node):
        if not isinstance(statement, ast.Return):
            continue
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int | float) and value.value == 0:
            add(
                "unmeasured_as_zero",
                statement.lineno,
                "a failed measurement returns 0, which reads as an idle machine rather than as a missing "
                "reading; None with a reason is the honest answer",
                severity="high",
            )


def _check_float_money(node: ast.AST, add) -> None:
    if not isinstance(node, ast.Assign):
        return
    call = node.value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "float"):
        return
    for target in node.targets:
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        lowered = name.lower()
        if any(word in lowered for word in _MONEY_WORDS):
            add(
                "float_money",
                node.lineno,
                f"{name} carries money and is a float; binary floating point cannot represent a decimal price "
                "exactly, and the error compounds through sizing and P&L",
                severity="high",
            )
            return


# Argument-less string methods a flag expression may chain onto the read before
# comparing. `os.getenv(...).strip().lower() == "true"` is the house idiom, and
# matching the un-chained form alone is what made this check blind (see below).
_STR_METHODS = frozenset({"lower", "upper", "strip", "lstrip", "rstrip", "casefold", "title"})
_PERMISSIVE_DEFAULTS = frozenset({"false", "0", "no", "off", "", "none", "disabled"})
_UNDECIDABLE = object()

# Flags that DISABLE a control when set. Off is their safe state, so "off unless
# set" is the correct configuration and reporting it would call correct code a
# defect. `HEAL_ALLOW_UNSIGNED_PATCHES` is the case this module's own docstring
# names: without a signing key the patch queue is refused, and that flag is the
# only way through, deliberately not defaulted.
#
# This is a name-based exclusion, which is the weakest kind of evidence in this
# repository and is used here because nothing stronger is available statically —
# polarity lives in the variable's meaning, not its syntax. It is kept narrow and
# pinned by tests in both directions: that these stay excluded, and that a
# control-ENABLING flag (DRIFT_BLOCK, WS_AUTH_REQUIRED, REDIS_FORCE_TLS) is still
# reported. Without the second, widening this set to silence a noisy finding is
# invisible, and an exclusion list becomes an excuse list.
_OPT_OUT_MARKERS = (
    "SKIP",
    "DISABLE",
    "BYPASS",
    "IGNORE",
    "UNSAFE",
    "INSECURE",
    "ALLOW_UNSIGNED",
    "OPT_OUT",
    "NO_VERIFY",
)


def _is_opt_out(variable: str) -> bool:
    upper = variable.upper()
    return any(marker in upper for marker in _OPT_OUT_MARKERS)


def _env_read(node: ast.AST) -> tuple[str, str, list[str]] | None:
    """Unwrap a chained read down to `os.getenv` / `os.environ.get`.

    Returns (variable, default, methods-in-source-order), or None if this is not
    an environment read carrying a literal default.
    """
    methods: list[str] = []
    cur = node
    while (
        isinstance(cur, ast.Call)
        and isinstance(cur.func, ast.Attribute)
        and cur.func.attr in _STR_METHODS
        and not cur.args
        and not cur.keywords
    ):
        methods.append(cur.func.attr)
        cur = cur.func.value

    if not (isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute)):
        return None
    reader = cur.func
    is_getenv = reader.attr == "getenv"
    is_environ_get = reader.attr == "get" and isinstance(reader.value, ast.Attribute) and reader.value.attr == "environ"
    if not (is_getenv or is_environ_get):
        return None
    if len(cur.args) < _GETENV_WITH_DEFAULT:
        # No default: unset raises or yields None rather than silently disabling
        # a control, and there is nothing to fold. Claiming either way here would
        # be Rule 2's unmeasured-rendered-as-a-finding.
        return None

    name_node, default_node = cur.args[0], cur.args[1]
    if not (isinstance(default_node, ast.Constant) and isinstance(default_node.value, str)):
        return None
    variable = name_node.value if isinstance(name_node, ast.Constant) and isinstance(name_node.value, str) else "?"
    # Collected outermost-first while descending; source order is the reverse.
    return variable, default_node.value, list(reversed(methods))


def _literal(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple | ast.List | ast.Set) and all(isinstance(e, ast.Constant) for e in node.elts):
        return [e.value for e in node.elts]
    return _UNDECIDABLE


def _flag_is_off_by_default(compare: ast.Compare, default: str, methods: list[str]):
    """Evaluate the flag expression against its own default. True == off.

    This is the part that makes the check hard to slip past. It does not match a
    shape; it asks what the expression *yields* when the variable is unset, so a
    spelling nobody anticipated still has to evaluate to False to be reported —
    and a control that is ON by default is not reported however permissive its
    default string looks (`== "false"` with default `"false"` is on).
    """
    if len(compare.ops) != 1 or len(compare.comparators) != 1:
        return _UNDECIDABLE
    value: object = default
    for method in methods:
        try:
            value = getattr(value, method)()
        except Exception:  # pragma: no cover - a method we mis-modelled
            return _UNDECIDABLE
    other = _literal(compare.comparators[0])
    if other is _UNDECIDABLE:
        return _UNDECIDABLE
    op = compare.ops[0]
    try:
        if isinstance(op, ast.Eq):
            return value == other
        if isinstance(op, ast.NotEq):
            return value != other
        if isinstance(op, ast.In):
            return value in other
        if isinstance(op, ast.NotIn):
            return value not in other
    except TypeError:
        return _UNDECIDABLE
    return _UNDECIDABLE


def _check_permissive_env(node: ast.AST, add) -> None:
    """A control that is OFF when its variable is unset.

    This check passed for the life of the module while finding nothing. It
    required the comparison's LEFT to BE the `getenv` call, so it matched only
    `os.getenv("X", "false") == "true"` — and measured 2026-09-13, not one of the
    38 permissive defaults in this tree is written that way. They wrap the read,
    almost always in `.lower()`. Its test used the un-wrapped form too, so the
    fixture agreed with the check and neither agreed with the codebase.

    It now unwraps the chain, accepts `os.environ.get`, reads annotated
    assignments, and decides by folding the default through the expression
    rather than by recognising a shape.
    """
    if isinstance(node, ast.AnnAssign):
        targets: list[ast.AST] = [node.target] if node.value is not None else []
        value = node.value
    elif isinstance(node, ast.Assign):
        targets = list(node.targets)
        value = node.value
    else:
        return
    if not isinstance(value, ast.Compare):
        return

    read = _env_read(value.left)
    if read is None:
        return
    variable, default, methods = read
    if _is_opt_out(variable):
        # Off is this flag's safe state; see _OPT_OUT_MARKERS.
        return

    verdict = _flag_is_off_by_default(value, default, methods)
    if verdict is _UNDECIDABLE:
        # Surfaced rather than swallowed: the default looks permissive and the
        # expression could not be evaluated, so a reader is told what is unknown
        # instead of the finding disappearing because the spelling was novel.
        if default.strip().lower() not in _PERMISSIVE_DEFAULTS:
            return
        severity, claim = (
            "medium",
            f"{{name}} reads {variable} with a permissive default ({default!r}) in a comparison this "
            "check could not evaluate, so whether the control is off when unset is UNDETERMINED — "
            "read it by hand rather than assuming either answer",
        )
    elif verdict is False:
        severity, claim = (
            "high",
            f"{{name}} is off unless {variable} is set, so the control it gates is off in every "
            "environment that has not been told otherwise — including a fresh deployment",
        )
    else:
        return

    for target in targets:
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        add("permissive_env_default", node.lineno, claim.format(name=name), severity=severity)
        return
