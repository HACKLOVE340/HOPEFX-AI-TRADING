"""`hdwallet` must not be demanded on a machine that has no C++ compiler.

A Windows install died here on 2026-09-21, on the vendored Python 3.12,
during `pip install -r requirements.txt`:

    Building wheel for ed25519-blake2b (pyproject.toml) ... error
    error: Microsoft Visual C++ 14.0 or greater is required.
    Get it with "Microsoft C++ Build Tools":
    https://visualstudio.microsoft.com/visual-cpp-build-tools/

`ed25519-blake2b` is a transitive dependency of `hdwallet` (used for its
Monero curve support) and ships no Windows wheel, so it always compiles from
source there. Windows carries no C++ toolchain by default, unlike Linux
(gcc via build-essential) or macOS (Xcode Command Line Tools), so this is not
a missing-library problem a user can `pip install` their way around — it
needs a multi-gigabyte Visual Studio component before `pip` can even start.

This is the exact shape `quickfix` already hit and was fixed for
(`tests/unit/test_quickfix_marker_skips_apple_silicon.py`, 2026-09-19):
a native-extension dependency, pinned unconditionally in `requirements.txt`,
that cannot build on a platform with no wheel and no local toolchain — so
installing the platform's own requirements file fails before the app has
had any chance to run.

It is not load-bearing for running the platform. `payments/crypto/
address_generator.py` and `payments/crypto/bitcoin.py` both guard the import
and raise a clear `RuntimeError` naming the missing package rather than
crashing or fabricating an address (see `test_crypto_deposit_addresses_are_
real.py`, F222) — so a deployment without hdwallet loses crypto deposit
address generation, loudly, and nothing else. `requirements-ci.txt` pins
hdwallet independently of `requirements.txt`, on the Linux runner where it
already builds cleanly, so this change does not weaken the coverage that
verifies real BIP-vector-correct addresses on every push — it only stops a
Windows install of the base platform from being blocked by a feature it
was never going to reach without also installing hdwallet by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from packaging.markers import Marker

_REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements.txt"


def _hdwallet_marker() -> Marker:
    for line in _REQUIREMENTS.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or not line.lower().startswith("hdwallet"):
            continue
        _, sep, marker = line.partition(";")
        assert sep, f"the hdwallet pin carries no environment marker at all: {line!r}"
        return Marker(marker.strip())
    pytest.fail("no hdwallet requirement found in requirements.txt")


def _env(system: str, machine: str) -> dict[str, str]:
    return {
        "sys_platform": system,
        "platform_machine": machine,
        "platform_system": {"darwin": "Darwin", "linux": "Linux", "win32": "Windows"}[system],
    }


# ── positive control ──────────────────────────────────────────────────────────


def test_the_marker_is_parsed_and_actually_discriminates():
    """Without this, a marker that selects everything would satisfy nothing below."""
    m = _hdwallet_marker()
    results = {m.evaluate(_env(s, a)) for s, a in (("linux", "x86_64"), ("win32", "AMD64"))}
    assert len(results) == 2, "the marker returns the same answer for Linux x86 and Windows"


# ── the defect ────────────────────────────────────────────────────────────────


def test_it_is_not_demanded_on_windows():
    """ed25519-blake2b has no Windows wheel and no default C++ toolchain to build it with."""
    assert not _hdwallet_marker().evaluate(_env("win32", "AMD64")), (
        "requirements.txt demands hdwallet on win32, where ed25519-blake2b "
        "requires Microsoft Visual C++ Build Tools that are not installed by default"
    )


# ── and is still requested where it CAN build ─────────────────────────────────


def test_it_is_still_requested_on_linux():
    """CI (requirements-ci.txt) pins hdwallet independently and builds it there
    today — narrowing requirements.txt must not silently drop coverage there too."""
    assert _hdwallet_marker().evaluate(_env("linux", "x86_64"))


def test_it_is_still_requested_on_macos():
    """Xcode Command Line Tools ship a usable C++ toolchain, unlike a bare Windows install."""
    assert _hdwallet_marker().evaluate(_env("darwin", "arm64"))
    assert _hdwallet_marker().evaluate(_env("darwin", "x86_64"))
