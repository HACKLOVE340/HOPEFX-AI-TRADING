# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The caller check — Group 3 Chapters 13 and 14.

The capability registry verifies that each row's evidence locator **resolves**.
It has no opinion about whether anything **calls** it. That gap produced a real
defect: `stack.agent_runtime` was marked live while `run_isolated` was imported
by nothing outside its own tests — a dead control inside the work that closed a
row about isolation.

Traceability therefore needs four links, not three:

    requirement -> implementation -> SOMETHING CALLS IT -> test -> the test can fail

This module supplies the third.

## It is a screen, not a proof, and says so

Matching is by symbol name. A capability invoked through an alias, a dynamic
lookup, a registry of handlers or a string in a config file will be missed. The
output is therefore triaged, never trusted as a verdict — a row it flags is a row
to look at, not a row to demote automatically.

## The positive control is mandatory

The first version of this sweep reported **154 dead capabilities** while
examining nothing at all: `rg` was invoked with no path argument from a process
whose stdin was a file at EOF, so ripgrep searched *stdin* rather than walking
the repository, found nothing, and every row looked dead.

It was caught only because a symbol known to be mounted in `App.tsx` came back
with zero references. So this module asserts a **known-good control symbol before
trusting any result**, and refuses to report at all if that assertion fails. A
sweep that cannot find something it knows is there has not measured anything.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent

#: A symbol that is certainly called in production. If the sweep cannot find this,
#: the sweep is broken and every other result is meaningless.
CONTROL_SYMBOL: Final = "PresenceAnywhere"
CONTROL_MIN_FILES: Final = 2

_EXCLUDE: Final[tuple[str, ...]] = (
    "--glob",
    "!node_modules",
    "--glob",
    "!.venv",
    "--glob",
    "!__pycache__",
    "--glob",
    "!docs/**",
    "--glob",
    "!ai/hub/capabilities.py",
    # And this module. Documenting the triage put `DEFAULT_MAX_CONCURRENT`,
    # `GatewayPatcher` and `COLLAPSE_ABOVE` into the docstrings below; the
    # sweep counted itself as a production caller and three rows silently left
    # the flagged list. A checker that reads prose is not reading code — the
    # same trap as `security/code_analyzer.py`'s docstring scan (F255), except
    # here it produced FALSE NEGATIVES, which is the direction that hides a
    # dead control instead of merely wasting an inspection.
    "--glob",
    "!scripts/capability_callers.py",
)
_EXCLUDE_TESTS: Final[tuple[str, ...]] = (
    "--glob",
    "!*test*",
    "--glob",
    "!tests/**",
    "--glob",
    "!**/test/**",
)


class SweepBroken(RuntimeError):
    """The sweep could not find a symbol known to be present."""


@dataclass
class Row:
    capability: str
    section: str
    symbol: str
    production_files: int
    any_files: int
    module_reached: bool = False

    @property
    def uncalled(self) -> bool:
        """No file outside tests names this symbol, other than its own definition."""
        return self.production_files <= 1

    @property
    def priority(self) -> str:
        """Triage order for a flagged row, from the two signals together.

        `unreached` — nothing in production names the symbol AND nothing
        imports the module it lives in. The strongest evidence this screen can
        offer that a capability is not wired up.

        `symbol-only` — the module IS imported in production, but this symbol
        is never named. Often a default argument, a factory, or an import
        chain, and then the row is false. Sometimes the module is imported for
        a different export and this symbol really is unreachable, as with
        `hub/layout.ts` — imported for `readLayout`, while `COLLAPSE_ABOVE`
        sits behind an exported function nobody calls. So it is a lower
        priority to inspect, never a reason to skip inspecting.
        """
        return "symbol-only" if self.module_reached else "unreached"


def _files_naming(symbol: str, *, exclude_tests: bool, repo: Path) -> list[str]:
    cmd = ["rg", "-l", "--no-messages", re.escape(symbol), *_EXCLUDE]
    if exclude_tests:
        cmd += list(_EXCLUDE_TESTS)
    # An explicit path, and stdin closed. Without BOTH, ripgrep reads stdin and
    # reports nothing — the defect that made the first version of this sweep
    # confidently claim 154 dead capabilities having read no files.
    cmd.append(str(repo))
    out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False).stdout.strip()
    return [line for line in out.split("\n") if line]


def _module_locator(evidence: str) -> tuple[str, str] | None:
    """Split an evidence locator into (kind, module), or None if it names none.

    Two shapes are used in the registry: a dotted Python module
    (`ai.jobs.runner:DEFAULT_MAX_CONCURRENT`) and a repository path
    (`frontend/src/hub/layout.ts:COLLAPSE_ABOVE`).
    """
    head = evidence.rsplit(":", 1)[0].strip()
    if not head:
        return None
    if "/" in head:
        return ("path", head)
    if "." in head:
        return ("python", head)
    return None


def _import_patterns(kind: str, module: str) -> list[str]:
    """Every way production actually reaches a module, as regexes.

    The third Python form is the one that matters and the one most easily
    forgotten: `from ai.memory import governance` names the package, not the
    module, so a search for `from ai.memory.governance import` misses it
    entirely. That form defeated two hand-written sweeps before it was written
    down here.
    """
    if kind == "python":
        pkg, _, leaf = module.rpartition(".")
        pats = [
            rf"from\s+{re.escape(module)}\s+import",
            rf"import\s+{re.escape(module)}\b",
        ]
        if pkg:
            pats.append(rf"from\s+{re.escape(pkg)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b")
        return pats
    # A TS/TSX import names the module without its extension.
    stem = module.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return [rf"""from\s+['"][^'"\n]*\b{re.escape(stem)}['"]"""]


def _module_is_reached(evidence: str, *, repo: Path) -> bool:
    """Does any production file import the module this capability lives in?

    A SECOND signal, never a substitute for the symbol count. A module can be
    imported for one export while the capability's own symbol stays
    unreachable, so folding this into `uncalled` would turn a screen into a
    report that cannot fail — the exact shape this repository keeps removing.
    """
    located = _module_locator(evidence)
    if located is None:
        return False
    kind, module = located
    own_file = module.replace(".", "/") + ".py" if kind == "python" else module

    for pattern in _import_patterns(kind, module):
        cmd = ["rg", "-l", "--no-messages", pattern, *_EXCLUDE, *_EXCLUDE_TESTS, str(repo)]
        out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False).stdout.strip()
        hits = [line for line in out.split("\n") if line and not line.endswith(own_file)]
        if hits:
            return True
    return False


def assert_sweep_works(repo: Path | None = None) -> int:
    """Prove the sweep can find something before believing anything it says.

    Returns the control's file count so a caller can log it. Raises `SweepBroken`
    rather than returning a falsy value, because the failure this guards against
    is precisely a result that looks like a clean answer.
    """
    base = repo or REPO
    found = _files_naming(CONTROL_SYMBOL, exclude_tests=True, repo=base)
    if len(found) < CONTROL_MIN_FILES:
        raise SweepBroken(
            f"the control symbol {CONTROL_SYMBOL!r} was found in {len(found)} production files "
            f"(expected at least {CONTROL_MIN_FILES}); the sweep is not reading the repository, "
            "so every other result would be meaningless"
        )
    return len(found)


def sweep(repo: Path | None = None) -> list[Row]:
    """Every live capability whose evidence names a symbol, with its caller count."""
    base = repo or REPO
    assert_sweep_works(base)

    from ai.hub.capabilities import REGISTRY, ROLLUP_IDS

    rows: list[Row] = []
    for cap in REGISTRY:
        if cap.state != "live" or ":" not in (cap.evidence or ""):
            continue
        # A derived roll-up has no caller of its id BY DESIGN — `layer_state()`
        # computes it from the rows beneath. Screening it produced four
        # permanent false positives, and a screen that is always wrong about
        # the same four rows teaches its readers to skim the rest.
        if cap.id in ROLLUP_IDS:
            continue
        symbol = cap.evidence.split(":")[-1]
        if not symbol or not symbol[0].isalpha():
            continue
        rows.append(
            Row(
                capability=cap.id,
                section=cap.section,
                symbol=symbol,
                production_files=len(_files_naming(symbol, exclude_tests=True, repo=base)),
                any_files=len(_files_naming(symbol, exclude_tests=False, repo=base)),
                module_reached=_module_is_reached(cap.evidence, repo=base),
            )
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capability caller screen (Group 3 Ch 13).")
    parser.add_argument("--check", action="store_true")
    parser.parse_args(argv)

    try:
        control = assert_sweep_works()
    except SweepBroken as exc:
        print(f"SWEEP BROKEN: {exc}")
        return 2

    rows = sweep()
    flagged = [r for r in rows if r.uncalled]
    unreached = [r for r in flagged if r.priority == "unreached"]
    symbol_only = [r for r in flagged if r.priority == "symbol-only"]

    print(f"control: {CONTROL_SYMBOL} found in {control} production files — sweep is reading the repo")
    print(f"screened: {len(rows)} live rows with a symbol locator (derived roll-ups excluded)")
    print(f"flagged:  {len(flagged)} with no production caller beyond their own definition")
    print(f"          {len(unreached)} unreached · {len(symbol_only)} symbol-only\n")

    def _show(title: str, group: list[Row], note: str) -> None:
        if not group:
            return
        print(f"{title}  ({len(group)})")
        print(f"  {note}")
        for r in sorted(group, key=lambda r: (r.production_files, r.section)):
            print(f"  §{r.section:<4} {r.capability:<38} {r.symbol:<28} prod={r.production_files} any={r.any_files}")
        print()

    _show(
        "UNREACHED",
        unreached,
        "nothing names the symbol AND nothing imports its module — inspect these first",
    )
    _show(
        "SYMBOL-ONLY",
        symbol_only,
        "the module IS imported in production; often a default argument, a factory or an "
        "import chain,\n  but sometimes the module is imported for a different export and this "
        "symbol really is dead",
    )

    if flagged:
        print("This is a SCREEN, not a verdict. Symbol matching misses aliases and dynamic")
        print("lookup, so each row is one to inspect rather than one to demote — including")
        print("the symbol-only ones, which are lower priority and not dismissed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
