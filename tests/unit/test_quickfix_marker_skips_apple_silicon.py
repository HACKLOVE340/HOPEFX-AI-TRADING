"""`quickfix` must not be demanded on a machine where it cannot compile.

A MacBook install died here on 2026-09-19, on Python 3.12 (so past the
requires-python cap added the same day):

    Building wheel for quickfix (pyproject.toml) ... error
    C++/AtomicCount.h:163: error: unrecognized instruction mnemonic
        "lock\\n\\t"
    <inline asm>:2:2: note: instantiated into assembly here
        xadd x9, [x8]

`lock` and `xadd` are x86 instructions. The build target was
`macosx-26.0-arm64-cpython-312` — Apple Silicon. quickfix's AtomicCount.h
carries hand-written x86 inline assembly with no ARM64 path, so the compiler is
being handed x86 mnemonics for an ARM register file. (`tr1/memory` not found is
the same file's other age showing.)

Measured against PyPI at the time: quickfix publishes **zero wheels**, for any
platform, at 1.15.1 AND at 1.16.0 (latest). It is always compiled from source,
so there is no binary path around the assembly.

This is NOT a missing-headers problem, and the comment beside the pin said
"On macOS: brew install quickfix", which sends the reader to install a C++
library that cannot fix an architecture mismatch.

It is also not load-bearing for running the platform. `execution/fix_adapter.py`
guards the import and falls back — quickfix, then pyfixmsg, then simplefix, then
a stub — and `requirements-ci.txt` already excludes quickfix outright, which is
why CI and the dev sandbox install cleanly. Only `requirements.txt` demanded it,
under a marker that excluded Windows and nothing else.

The FIX bridge itself stays a real subsystem (`brokers/ibkr_fix_bridge.py`,
`execution/fix_adapter.py`); quickfix is its preferred PRODUCTION backend, which
is an x86 deployment. This only stops a local install from failing on hardware
where the package provably cannot build.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.markers import Marker

_REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements.txt"


def _quickfix_marker() -> Marker:
    for line in _REQUIREMENTS.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or not line.lower().startswith("quickfix"):
            continue
        _, sep, marker = line.partition(";")
        assert sep, f"the quickfix pin carries no environment marker at all: {line!r}"
        return Marker(marker.strip())
    pytest.fail("no quickfix requirement found in requirements.txt")


def _env(system: str, machine: str) -> dict[str, str]:
    return {
        "sys_platform": system,
        "platform_machine": machine,
        "platform_system": {"darwin": "Darwin", "linux": "Linux", "win32": "Windows"}[system],
    }


# ── positive control ──────────────────────────────────────────────────────────


def test_the_marker_is_parsed_and_actually_discriminates():
    """Without this, a marker that selects everything would satisfy nothing below."""
    m = _quickfix_marker()
    results = {m.evaluate(_env(s, a)) for s, a in (("linux", "x86_64"), ("win32", "AMD64"))}
    assert len(results) == 2, "the marker returns the same answer for Linux x86 and Windows"


# ── the defect ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("machine", ["arm64", "aarch64"])
def test_it_is_not_demanded_on_arm(machine: str):
    """x86 inline asm cannot assemble on ARM, and there is no wheel to fall back to."""
    assert not _quickfix_marker().evaluate(_env("darwin", machine)), (
        f"requirements.txt demands quickfix on darwin/{machine}, where its "
        "hand-written `lock`/`xadd` inline assembly cannot compile"
    )


def test_it_is_not_demanded_on_linux_arm_either():
    assert not _quickfix_marker().evaluate(_env("linux", "aarch64"))


# ── and is still requested where it CAN build ─────────────────────────────────


def test_it_is_still_requested_on_x86_linux():
    """The counterweight. quickfix is the preferred production backend and the
    production target is x86 — narrowing must not drop it there."""
    assert _quickfix_marker().evaluate(_env("linux", "x86_64"))


def test_it_is_still_excluded_on_windows():
    """The condition that was already there must survive the widening."""
    assert not _quickfix_marker().evaluate(_env("win32", "AMD64"))


# ── the advice beside it must not send the reader somewhere useless ───────────


def test_the_macos_comment_does_not_prescribe_a_brew_install_that_cannot_help():
    text = _REQUIREMENTS.read_text()
    assert not re.search(r"On macOS:\s*brew install quickfix", text), (
        "the pin still advises `brew install quickfix` for macOS — that installs "
        "the C++ library, which cannot fix x86 assembly on an ARM64 machine"
    )
