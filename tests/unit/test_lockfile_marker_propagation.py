"""A pip-compile lock file must propagate a parent's environment marker onto
any dependency reachable ONLY through that parent.

Reproduced on 2026-09-24, on a fresh Windows install of `requirements.lock`
(the "exact reproducible install" path the file's own header advertises):

    Building wheel for ed25519-blake2b (pyproject.toml) ... error
    error: Microsoft Visual C++ 14.0 or greater is required.

This is the exact failure `test_hdwallet_marker_skips_windows.py` fixed in
`requirements.txt` three days earlier, by adding `; sys_platform != "win32"`
to the `hdwallet` pin — `ed25519-blake2b` has no Windows wheel and no default
C++ toolchain to build it with there. That fix reached `requirements.lock`
too: `hdwallet==3.6.1 ; sys_platform != "win32"` carries the marker there as
well. But `ed25519-blake2b` — reachable in the lock file ONLY as a transitive
dependency of `hdwallet` (`# via hdwallet`) — carries no marker of its own, so
`pip install -r requirements.lock` on Windows still resolves and tries to
build it. Six siblings have the identical gap: `base58`, `cbor2`, `crcmod`,
`ecdsa`, `pycryptodome`, `pynacl` — every package `hdwallet` pulls in that
is reachable nowhere else in the dependency graph.

The root cause is structural, not a one-off editing slip: `.github/workflows/
lockfile.yml` regenerates `requirements.lock` on every push that touches
`requirements.txt` with plain `pip-compile requirements.txt --output-file
requirements.lock.tmp --strip-extras`, which attaches a marker to a
top-level package's own line but does not propagate that marker onto
packages reachable only as its transitive dependencies. `scripts/
lock_marker_propagation.py --apply` is the fix, run as a post-processing step
in that workflow so the gap cannot silently reappear on the next
regeneration; this test is the guard that catches it if the workflow step is
ever removed or bypassed.

`--id LOCK-MARKER-NOT-PROPAGATED`
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.markers import Marker

_LOCK = Path(__file__).resolve().parents[2] / "requirements.lock"

_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)(?:\s*;\s*(.+))?$")

_WINDOWS_ENV = {
    "sys_platform": "win32",
    "platform_machine": "AMD64",
    "platform_system": "Windows",
}


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _parse_lock() -> dict[str, tuple[str | None, list[str]]]:
    """Return {normalised_name: (own_marker_or_None, [via parent names])}."""
    lines = _LOCK.read_text(encoding="utf-8").splitlines()
    entries: dict[str, tuple[str | None, list[str]]] = {}
    i, n = 0, len(lines)
    while i < n:
        m = _PIN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name, _version, marker = m.group(1), m.group(2), m.group(3)
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
        entries[_normalise(name)] = (marker.strip() if marker else None, via)
        i = j
    return entries


def _effective_marker(
    name: str,
    entries: dict[str, tuple[str | None, list[str]]],
    cache: dict[str, str | None],
    stack: frozenset[str] = frozenset(),
) -> str | None:
    """The marker gating `name`'s install, or None if unconditional.

    None covers both "no marker anywhere on this path" and "parents disagree
    on the marker" — either way there is no single marker to inherit.
    """
    if name in cache:
        return cache[name]
    if name in stack or name not in entries:
        return None
    own_marker, via = entries[name]
    if own_marker:
        cache[name] = own_marker
        return own_marker
    if not via or any(v == "-r requirements.txt" for v in via):
        cache[name] = None
        return None
    parent_markers = {_effective_marker(_normalise(p), entries, cache, stack | {name}) for p in via}
    result = next(iter(parent_markers)) if len(parent_markers) == 1 else None
    cache[name] = result
    return result


def test_the_fixture_still_has_a_marked_parent_to_check_propagation_from():
    """Without this, an edit that strips hdwallet's own marker would make the
    propagation test below pass vacuously — nothing left to check."""
    entries = _parse_lock()
    assert "hdwallet" in entries, "hdwallet is gone from requirements.lock"
    marker, _via = entries["hdwallet"]
    assert marker, "hdwallet lost its own environment marker in requirements.lock"
    assert Marker(marker).evaluate(_WINDOWS_ENV) is False, (
        "hdwallet's marker no longer excludes win32 — this test would no longer be checking anything meaningful"
    )


def test_transitive_deps_reachable_only_through_a_marked_parent_inherit_its_marker():
    """`pip install -r requirements.lock` must skip a transitive dependency on
    exactly the platforms its only parent is skipped on."""
    entries = _parse_lock()
    cache: dict[str, str | None] = {}
    failures = []
    for name, (own_marker, via) in entries.items():
        if own_marker or not via or any(v == "-r requirements.txt" for v in via):
            continue
        parent_markers = {_effective_marker(_normalise(p), entries, cache) for p in via}
        if len(parent_markers) != 1:
            continue  # parents disagree or are themselves unconditional
        (inherited,) = parent_markers
        if inherited is None:
            continue
        if not Marker(inherited).evaluate(_WINDOWS_ENV):
            failures.append(f"{name} — via {', '.join(via)} — should inherit: {inherited}")
    assert not failures, (
        "requirements.lock is missing marker propagation for these transitive "
        "dependencies (each is reachable ONLY through a parent excluded on "
        "this platform, but is itself pinned unconditionally):\n  "
        + "\n  ".join(sorted(failures))
        + "\n\nFix with: python scripts/lock_marker_propagation.py --apply"
    )
