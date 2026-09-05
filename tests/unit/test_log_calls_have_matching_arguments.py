# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A log call whose placeholders and arguments disagree does not log.

`logging` formats lazily, so `logger.exception("Payment failed for %s: %s", pid)`
raises inside the logging machinery and prints `--- Logging error ---` in place
of the record. The call site looks correct, the linter is silent, and the line
that was supposed to explain a failure is the line that fails.

33 such calls were live, all reached only on an error path -- which is exactly
where the log is the only evidence there is. Two shapes:

**32 x an orphaned trailing placeholder.** `logger.exception(...)` appends the
traceback itself, so someone removed the `exc` argument and left the `: %s`::

    logger.exception("Stripe PaymentIntent failed: %s")     # 1 placeholder, 0 args
    logger.exception("Order placement failed for %s: %s", user_id)

**1 x an unescaped literal percent**, in `brain/brain.py`::

    logger.critical("CATASTROPHIC LOSS: Equity $%s < 50% of Balance $%s", equity, balance)

`50% o` is read as a `%o` conversion, so the call needs three arguments and gets
two: ``TypeError: %o format: an integer is required, not float``. The brain's
loudest alert never emitted.

**Method note.** The first version of this scan reported 53 mismatches. It
counted `%%` as a placeholder -- `%.2f%% of` contains `% o`, which matches an
octal conversion -- so twenty of the fifty-three were the detector's fault, in
files where nothing was wrong. Stripping `%%` before counting brings it to 33,
which is what was actually fixed. A scanner that indicts correct code is worse
than none, and the tell was that the "defects" clustered in careful,
percentage-formatting code.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", "migrations", ".git", "build", "dist"}
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}

# A printf conversion specifier. `%%` is stripped from the string *before* this
# is applied -- see the method note above.
_CONVERSION = re.compile(r"%[-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa]")

# The receiver has to look like a logger. `.info()` is not exclusively a logging
# method -- tests/unit/test_ultimate_helpers.py calls `stats.info("latency_ms",
# value)` on a metrics object, which is correct code the first version of this
# scan reported as broken. Matching on the method name alone indicts anything
# that happens to share a verb.
_LOGGER_NAMES = {"logger", "log", "LOGGER", "LOG", "_logger", "_log"}


def _is_logger(node: ast.Attribute) -> bool:
    target = node.value
    if isinstance(target, ast.Name):
        return target.id in _LOGGER_NAMES
    if isinstance(target, ast.Attribute):  # self.logger, cls._log, mod.logger
        return target.attr in _LOGGER_NAMES
    return False


def _placeholder_count(fmt: str) -> int:
    return len(_CONVERSION.findall(fmt.replace("%%", "")))


def _mismatches() -> list[str]:
    out: list[str] = []
    for path in sorted(_ROOT.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.relative_to(_ROOT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in _LOG_METHODS or not _is_logger(node.func):
                continue
            args = node.args
            if node.func.attr == "log":
                args = args[1:]  # logger.log(level, fmt, *args)
            if not args or not isinstance(args[0], ast.Constant) or not isinstance(args[0].value, str):
                continue
            fmt = args[0].value
            if "%(" in fmt:  # mapping-style formatting takes a single dict
                continue
            if any(isinstance(a, ast.Starred) for a in args):
                continue
            supplied = len(args) - 1
            expected = _placeholder_count(fmt)
            if expected != supplied:
                rel = path.relative_to(_ROOT)
                out.append(f"{rel}:{node.lineno} expects {expected} args, got {supplied}: {fmt[:60]!r}")
    return out


def test_no_log_call_has_mismatched_arguments():
    found = _mismatches()
    assert not found, "log calls that will raise instead of logging:\n  " + "\n  ".join(found)


def test_the_scanner_recognises_the_two_shapes_that_were_fixed(tmp_path):
    """Guards the scanner itself. A guard that cannot fail is the defect this
    audit keeps finding, so the detector is exercised against known-bad input
    rather than trusted because the repo is clean."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        'logger.exception("Stripe PaymentIntent failed: %s")\n'
        'logger.critical("Equity $%s < 50% of Balance $%s", 1, 2)\n',
        encoding="utf-8",
    )
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _LOG_METHODS
        and _is_logger(n.func)
        and n.args
        and isinstance(n.args[0], ast.Constant)
    ]
    bad = [c for c in calls if _placeholder_count(c.args[0].value) != len(c.args) - 1]
    assert len(bad) == 2, f"the scanner no longer detects the shapes it was written for (found {len(bad)})"


def test_the_scanner_ignores_non_logger_receivers(tmp_path):
    """`stats.info("latency_ms", value)` is a metrics call, not a log call."""
    sample = tmp_path / "metrics.py"
    sample.write_text('stats.info("latency_ms", 12)\nrecorder.error("db_error", 1)\n', encoding="utf-8")
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    flagged = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and _is_logger(n.func)
    ]
    assert flagged == [], "a metrics object was mistaken for a logger"


def test_the_scanner_does_not_indict_escaped_percents():
    """The false-positive that made the first scan report 53 instead of 33."""
    assert _placeholder_count("Prop-firm drawdown: %.2f%% of %.2f%% limit") == 2
    assert _placeholder_count("100%% complete") == 0
    assert _placeholder_count("%d items, %.1f%% done") == 2


def test_the_catastrophic_loss_alert_formats():
    """Pinned by name. This one is not a log hygiene nit -- it is the brain's
    most severe alert, and it raised instead of emitting."""
    import inspect

    import brain.brain as brain_mod

    src = inspect.getsource(brain_mod)
    assert "CATASTROPHIC LOSS" in src
    for line in src.splitlines():
        if "CATASTROPHIC LOSS" in line and "logger" in line:
            assert "50%%" in line, "the literal percent is unescaped again; the alert will not emit"
            break
    else:
        pytest.fail("the CATASTROPHIC LOSS log call is gone")
