"""The declared Python range must match the interpreter this project actually runs.

Written after a real install failure on a MacBook, 2026-09-19. The user's
`pip install -r requirements.txt` died like this:

    Collecting coincurve<21,>=20.0.0 (from hdwallet<4.0.0,>=3.6.1 ...)
      Using cached coincurve-20.0.0.tar.gz
      Getting requirements to build wheel ... error
      ERROR: Use build.verbose instead of cmake.verbose for scikit-build-core >= 0.10

That is not a code defect and not a broken machine. The chain, measured against
PyPI at the time:

  * requirements.txt:51 takes `hdwallet>=3.6.1,<4.0.0`, and hdwallet pins
    `coincurve<21,>=20.0.0`. 3.6.1 is the LATEST hdwallet, so no newer release
    lifts that pin.
  * coincurve 20.0.0 ships macOS arm64 wheels for cp38-cp312 only.
  * coincurve 21.0.0 does have a cp313 wheel — but hdwallet forbids >=21.

So on Python 3.13 pip has no wheel, falls back to the sdist, and the build dies
deep inside cmake. Nothing in this repository can fix that; the constraint is
upstream.

What this repository COULD do, and did not, is say so. `requires-python` was
">=3.10" with NO upper bound, advertising a 3.13 that demonstrably cannot
install — while the classifiers right beside it already stopped at 3.12. The
two disagreed, and the one pip reads was the wrong one.

The ceiling is not cosmetic. CLAUDE.md pins 3.12 because the committed .pkl
model artifacts are pickled on it, and a different interpreter produces bytes
that fail `ml/__init__.py::_verify_checksum`. A 3.13 environment that DID
install would break the model loader instead — a worse failure, because it is
silent until inference.

This test derives everything from the Dockerfile rather than repeating a
number, so changing the image's Python turns it red instead of letting the
pins rot.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

_ROOT = Path(__file__).resolve().parents[2]


def _dockerfile_python() -> Version:
    """The interpreter production actually runs, read from the image tag."""
    text = (_ROOT / "Dockerfile").read_text()
    m = re.search(r"^FROM\s+python:(\d+)\.(\d+)", text, re.M)
    assert m, "no `FROM python:X.Y` in the Dockerfile — this test cannot anchor"
    return Version(f"{m.group(1)}.{m.group(2)}")


def _pyproject_requires() -> str:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    spec = data["project"]["requires-python"]
    assert spec, "pyproject declares no requires-python"
    return spec


def _setup_py_requires() -> str:
    text = (_ROOT / "setup.py").read_text()
    m = re.search(r"python_requires\s*=\s*[\"']([^\"']+)[\"']", text)
    assert m, "no python_requires in setup.py"
    return m.group(1)


def _ci_matrix_versions() -> list[Version]:
    text = (_ROOT / ".github/workflows/ci.yml").read_text()
    m = re.search(r"python-version:\s*\[([^\]]+)\]", text)
    assert m, "no python-version matrix in ci.yml"
    return [Version(v.strip().strip("\"'")) for v in m.group(1).split(",")]


# ── positive controls: the harness read real things ──────────────────────────


def test_the_harness_found_every_source_it_anchors_on():
    """Without this, an unparsed file makes every assertion below vacuous."""
    assert _dockerfile_python() >= Version("3.10")
    assert _pyproject_requires().strip() != ""
    assert _setup_py_requires().strip() != ""
    assert len(_ci_matrix_versions()) >= 2


# ── the pins agree with each other ───────────────────────────────────────────


def test_setup_py_and_pyproject_declare_the_same_range():
    """Two files, one answer. pip reads one of them; both must say it."""
    assert _setup_py_requires() == _pyproject_requires()


# ── the range matches the runtime ────────────────────────────────────────────


def test_the_range_admits_the_interpreter_production_runs():
    spec = SpecifierSet(_pyproject_requires())
    docker = _dockerfile_python()
    assert docker in spec, f"the Dockerfile runs {docker}, which {spec} excludes"


def test_the_range_admits_every_version_ci_tests():
    spec = SpecifierSet(_pyproject_requires())
    for v in _ci_matrix_versions():
        assert v in spec, f"CI tests {v}, which {spec} excludes"


def test_the_range_has_a_CEILING_and_it_excludes_the_next_minor():
    """The fix. An open-ended floor advertises a Python that cannot install.

    Derived, not hard-coded: whatever the Dockerfile runs, the minor above it
    is unsupported until someone deliberately raises both.
    """
    spec_text = _pyproject_requires()
    spec = SpecifierSet(spec_text)
    assert any(s.operator in ("<", "<=", "==", "~=") for s in spec), (
        f"requires-python is {spec_text!r} — no upper bound, so pip will accept a "
        "Python this project cannot install on and fail deep in a cmake build"
    )
    docker = _dockerfile_python()
    next_minor = Version(f"{docker.major}.{docker.minor + 1}")
    assert next_minor not in spec, (
        f"{spec_text} admits {next_minor}, but hdwallet pins coincurve<21 and "
        f"coincurve 20.0.0 has no {next_minor} wheel — pip builds from sdist and fails"
    )


def test_the_classifiers_match_the_declared_range():
    """The classifiers already stopped at the Dockerfile's minor while
    python_requires ran past it. That disagreement is what this pins shut."""
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    spec = SpecifierSet(_pyproject_requires())
    classified = [
        Version(m.group(1))
        for c in data["project"].get("classifiers", [])
        if (m := re.fullmatch(r"Programming Language :: Python :: (\d+\.\d+)", c))
    ]
    assert classified, "no versioned Python classifiers to check"
    for v in classified:
        assert v in spec, f"classifier claims {v}, which {spec} excludes"


@pytest.mark.parametrize("path", ["setup.py", "pyproject.toml"])
def test_neither_file_claims_a_python_the_other_denies(path: str):
    spec = SpecifierSet(_pyproject_requires() if path == "pyproject.toml" else _setup_py_requires())
    docker = _dockerfile_python()
    assert docker in spec
    assert Version(f"{docker.major}.{docker.minor + 1}") not in spec
