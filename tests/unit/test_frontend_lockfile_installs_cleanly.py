# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_frontend_lockfile_installs_cleanly.py
=====================================================
The frontend lockfile must satisfy ``npm ci``, because the Docker build is
``npm ci`` and a broken one takes the whole deployment down.

This is here because it happened. Adding ESLint installed
``@eslint/js@^10.0.1`` alongside ``eslint@^9.39.5``. ``@eslint/js`` v10 declares
``peerOptional eslint@^10.0.0``, so the pair cannot resolve::

    npm error Could not resolve dependency:
    npm error peerOptional eslint@"^10.0.0" from @eslint/js@10.0.1
    npm error Conflicting peer dependency: eslint@10.8.1

``Dockerfile:10`` is ``RUN npm ci``, so every one of the six images failed to
build and the deployment came down with it.

It was "verified" beforehand with ``npm ci --dry-run`` run inside the working
tree, where ``node_modules`` was already populated. That checks almost nothing:
the real build starts from two files and an empty directory. This test does
what the Dockerfile does —

    COPY frontend/package.json frontend/package-lock.json ./
    RUN npm ci

— by copying exactly those two files into an empty temp directory and running a
real ``npm ci`` there.

Marked ``slow``: it performs a full dependency install (~20s warm, longer cold)
and needs network, so it is excluded from the default fast suite the same way
the rest of the slow set is. Run it before changing frontend dependencies:

    pytest tests/unit/test_frontend_lockfile_installs_cleanly.py -m slow
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess  # nosec B404 — invoking npm with a fixed argv, no shell
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FRONTEND = _ROOT / "frontend"


def _npm() -> str | None:
    return shutil.which("npm")


# ── Cheap checks — these run in the fast suite ───────────────────────────────


@pytest.mark.unit
def test_package_json_and_lockfile_are_both_present():
    """Dockerfile:9 copies both; a missing lockfile turns `npm ci` into an error."""
    assert (_FRONTEND / "package.json").is_file()
    assert (_FRONTEND / "package-lock.json").is_file()


@pytest.mark.unit
def test_eslint_and_eslint_js_majors_agree():
    """The exact break, as a cheap assertion.

    `@eslint/js` declares a peer dependency on a matching `eslint` major. A v10
    `@eslint/js` beside a v9 `eslint` is unresolvable, and `npm ci` fails hard
    rather than warning.
    """
    pkg = json.loads((_FRONTEND / "package.json").read_text())
    dev = pkg.get("devDependencies", {})

    eslint = dev.get("eslint")
    eslint_js = dev.get("@eslint/js")
    if not eslint or not eslint_js:
        pytest.skip("eslint is not a dependency of this project")

    def major(spec: str) -> str:
        return spec.lstrip("^~>=< ").split(".")[0]

    assert major(eslint) == major(eslint_js), (
        f"eslint {eslint} and @eslint/js {eslint_js} are different majors — "
        "npm ci cannot resolve this and the Docker build will fail"
    )


@pytest.mark.unit
def test_every_dependency_in_package_json_is_in_the_lockfile():
    """A dependency added without regenerating the lockfile fails `npm ci`."""
    pkg = json.loads((_FRONTEND / "package.json").read_text())
    lock = json.loads((_FRONTEND / "package-lock.json").read_text())

    locked = lock.get("packages", {}).get("", {})
    for section in ("dependencies", "devDependencies"):
        declared = set(pkg.get(section, {}))
        recorded = set(locked.get(section, {}))
        missing = declared - recorded
        assert not missing, (
            f"{section} present in package.json but not the lockfile: {sorted(missing)} — run `npm install`"
        )


# ── The real thing — what the Docker build actually runs ─────────────────────


@pytest.mark.slow
def test_npm_ci_succeeds_from_a_clean_directory():
    """Exactly Dockerfile:9-10: two files into an empty dir, then `npm ci`.

    A dry run inside the working tree passes while this fails, which is how the
    broken lockfile reached the server.
    """
    npm = _npm()
    if npm is None:
        pytest.skip("npm not available")

    with tempfile.TemporaryDirectory(prefix="npmci_") as tmp:
        work = pathlib.Path(tmp)
        shutil.copy2(_FRONTEND / "package.json", work / "package.json")
        shutil.copy2(_FRONTEND / "package-lock.json", work / "package-lock.json")

        result = subprocess.run(  # nosec B603 — fixed argv, shell=False
            [npm, "ci", "--no-audit", "--no-fund"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )

    assert result.returncode == 0, (
        "npm ci failed from a clean directory — the Docker build (Dockerfile:10) will fail "
        f"the same way:\n\n{result.stderr[-4000:]}"
    )
