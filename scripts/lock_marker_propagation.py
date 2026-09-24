#!/usr/bin/env python3
"""Propagate a pinned package's environment marker onto any dependency in
`requirements.lock` that is reachable ONLY as that package's transitive
dependency.

`pip-compile` attaches an environment marker (`; sys_platform != "win32"`) to
a top-level package's own line in the generated lock file, but does not
propagate that marker onto packages that are only reachable as *its*
transitive dependencies. Left alone, this silently reopens exactly the class
of failure the marker exists to prevent: `pip install -r requirements.lock`
on the excluded platform still resolves the unmarked transitive package and
tries to build it — see `tests/unit/test_lockfile_marker_propagation.py`
(`--id LOCK-MARKER-NOT-PROPAGATED`) for the concrete `hdwallet` /
`ed25519-blake2b` / Windows instance this was written for.

Run as a post-processing step in `.github/workflows/lockfile.yml`, right
after `pip-compile` regenerates `requirements.lock.tmp` and before the header
is prepended, so the gap cannot reappear on the next automated regeneration.

Usage:
    python scripts/lock_marker_propagation.py            # report only, exit 1 if gaps found
    python scripts/lock_marker_propagation.py --check    # same, explicit
    python scripts/lock_marker_propagation.py --apply    # rewrite requirements.lock in place
    python scripts/lock_marker_propagation.py --apply --file path/to/lock  # non-default path
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "requirements.lock"

_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)(?:\s*;\s*(.+))?$")


@dataclass
class Entry:
    name: str
    version: str
    marker: str | None
    via: list[str]
    line_no: int


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_lock(lines: list[str]) -> dict[str, Entry]:
    entries: dict[str, Entry] = {}
    i, n = 0, len(lines)
    while i < n:
        m = _PIN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name, version, marker = m.group(1), m.group(2), m.group(3)
        via: list[str] = []
        j = i + 1
        if j < n and lines[j].strip() == "# via":
            j += 1
            while j < n and lines[j].startswith("    #   "):
                via.append(lines[j].strip()[2:].strip())
                j += 1
        elif j < n and lines[j].strip().startswith("# via "):
            via.append(lines[j].strip()[len("# via ") :].strip())
            j += 1
        entries[_normalise(name)] = Entry(
            name=name,
            version=version,
            marker=marker.strip() if marker else None,
            via=via,
            line_no=i,
        )
        i = j
    return entries


def compute_propagation(entries: dict[str, Entry]) -> dict[str, str]:
    """Return {normalised_name: marker_to_add}.

    A package inherits a marker only when EVERY one of its `# via` parents
    resolves (recursively) to that same single marker. A package required
    directly by `requirements.txt`, or reached through parents that disagree
    on their marker, is left alone — propagating there would be a guess, not
    a fact recoverable from the lock file.
    """
    resolved: dict[str, str | None] = {}

    def effective(key: str, stack: frozenset[str]) -> str | None:
        if key in resolved:
            return resolved[key]
        if key in stack or key not in entries:
            return None
        entry = entries[key]
        if entry.marker:
            resolved[key] = entry.marker
            return entry.marker
        if not entry.via or any(v == "-r requirements.txt" for v in entry.via):
            resolved[key] = None
            return None
        parents = {effective(_normalise(p), stack | {key}) for p in entry.via}
        result = next(iter(parents)) if len(parents) == 1 else None
        resolved[key] = result
        return result

    to_add: dict[str, str] = {}
    for key in entries:
        marker = effective(key, frozenset())
        if marker and not entries[key].marker:
            to_add[key] = marker
    return to_add


def render(lines: list[str], entries: dict[str, Entry], to_add: dict[str, str]) -> list[str]:
    out = list(lines)
    for key, marker in to_add.items():
        entry = entries[key]
        out[entry.line_no] = f"{entry.name}=={entry.version} ; {marker}"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="rewrite the lock file in place")
    parser.add_argument("--check", action="store_true", help="report gaps and exit 1 if any (default)")
    parser.add_argument("--file", type=Path, default=DEFAULT_LOCK, help="path to the lock file")
    args = parser.parse_args(argv)

    lines = args.file.read_text(encoding="utf-8").splitlines()
    entries = parse_lock(lines)
    to_add = compute_propagation(entries)

    if not to_add:
        print("[lock-marker-propagation] OK — every transitive-only dependency already carries its parent's marker.")
        return 0

    if args.apply:
        new_lines = render(lines, entries, to_add)
        args.file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"[lock-marker-propagation] Applied {len(to_add)} marker(s) to {args.file}:")
        for key in sorted(to_add):
            print(f"  {entries[key].name} ; {to_add[key]}")
        return 0

    print(
        f"[lock-marker-propagation] {len(to_add)} transitive dependenc{'y' if len(to_add) == 1 else 'ies'} missing a propagated marker:"
    )
    for key in sorted(to_add):
        entry = entries[key]
        print(f"  {entry.name} — via {', '.join(entry.via)} — should carry: {to_add[key]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
