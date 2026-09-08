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

    @property
    def uncalled(self) -> bool:
        """No file outside tests names this symbol, other than its own definition."""
        return self.production_files <= 1


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

    from ai.hub.capabilities import REGISTRY

    rows: list[Row] = []
    for cap in REGISTRY:
        if cap.state != "live" or ":" not in (cap.evidence or ""):
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
    print(f"control: {CONTROL_SYMBOL} found in {control} production files — sweep is reading the repo")
    print(f"screened: {len(rows)} live rows with a symbol locator")
    print(f"flagged:  {len(flagged)} with no production caller beyond their own definition\n")
    for r in sorted(flagged, key=lambda r: (r.production_files, r.section)):
        print(f"  §{r.section:<4} {r.capability:<38} {r.symbol:<28} prod={r.production_files} any={r.any_files}")
    if flagged:
        print("\nThis is a SCREEN, not a verdict. Symbol matching misses aliases and dynamic")
        print("lookup, so each row is one to inspect rather than one to demote.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
