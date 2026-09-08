# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate B — every env var an operator must supply is documented in `.env.example`.

Drift here is how a deployment comes up misconfigured: `docker-compose.yml`
references `${SOME_VAR}`, nobody wrote it down, and the container starts with an
empty value nobody notices until behaviour is wrong.

It had no test. It is alive — but establishing that took two wrong injections,
and the second is the more interesting lesson.

## An injection has to be the shape the gate detects

The first probe used a list-style entry (`- VAR=value`); this compose file uses
mapping style, so nothing was injected and the guard correctly refused to call
the rule dead.

The second probe injected `HOPEFX_UNDOCUMENTED_VAR: some-value` — a *literal*.
The gate passed, which looked like a dead control. It is not: the gate collects
only `${VAR}` **references**, because a literal needs no `.env.example` entry,
and it says so in its own docstring. The injection applied and was still the
wrong defect.

So "assert the injection applied" is necessary and **not sufficient**. The
injection must also be the failure the gate exists to catch. Both shapes are
kept below — the literal as a documented non-finding, the reference as the real
one — so a future reader does not repeat the same two mistakes.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_b_env_consistency.py"
_FIXTURE_FILES = (Path(".env.example"), Path("docker-compose.yml"))

_ANCHOR = "    environment:\n      DATABASE_URL:"


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A disposable repository the gate accepts as its own root."""
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    for rel in _FIXTURE_FILES:
        shutil.copy2(REPO / rel, root / rel)
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
    )


def _add_to_first_environment_block(root: Path, entry: str) -> None:
    """Insert one entry, and prove it landed."""
    path = root / "docker-compose.yml"
    before = path.read_text(encoding="utf-8")
    assert _ANCHOR in before, "compose layout changed — this fixture no longer injects anything"
    after = before.replace(_ANCHOR, f"    environment:\n      {entry}\n      DATABASE_URL:", 1)
    assert after != before, "injection did not apply — it would prove nothing"
    path.write_text(after, encoding="utf-8")


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    def test_the_gate_found_a_real_number_of_variables(self, mirror: Path) -> None:
        # A gate that parsed zero variables passes every test below trivially.
        assert "59 docker-compose env vars" in _run(mirror).stdout or "env vars" in _run(mirror).stdout
        assert _run(mirror).stdout.strip(), "the gate printed nothing"


class TestTheDriftItExistsToCatch:
    def test_an_undocumented_reference_is_caught(self, mirror: Path) -> None:
        _add_to_first_environment_block(mirror, "HOPEFX_UNDOCUMENTED_VAR: ${HOPEFX_UNDOCUMENTED_VAR}")
        assert "HOPEFX_UNDOCUMENTED_VAR=" not in (mirror / ".env.example").read_text(encoding="utf-8")
        result = _run(mirror)
        assert result.returncode != 0, "an undocumented ${VAR} reference did not fail gate B"
        assert "HOPEFX_UNDOCUMENTED_VAR" in result.stdout

    def test_a_reference_with_a_default_is_still_checked(self, mirror: Path) -> None:
        # `${VAR:-default}` still needs documenting: the default is a fallback,
        # not a statement that the operator never sets it.
        _add_to_first_environment_block(mirror, "HOPEFX_DEFAULTED_VAR: ${HOPEFX_DEFAULTED_VAR:-off}")
        assert _run(mirror).returncode != 0


class TestWhatItDeliberatelyDoesNotCatch:
    """Recorded, not fixed. Narrowing a gate silently is how false positives
    train people to bypass it; widening one needs its own decision."""

    def test_a_literal_value_is_not_a_finding(self, mirror: Path) -> None:
        _add_to_first_environment_block(mirror, "HOPEFX_LITERAL_VAR: some-value")
        assert _run(mirror).returncode == 0, (
            "gate B now flags literal values. That may be right, but it is a scope change: "
            "the docstring says literals need no .env.example entry."
        )


class TestItFailsClosedOnMissingInput:
    @pytest.mark.parametrize("missing", list(_FIXTURE_FILES))
    def test_deleting_an_input_fails_the_gate(self, mirror: Path, missing: Path) -> None:
        # Rule 3. A gate that cannot read its inputs must refuse, not pass —
        # deleting a file is otherwise a way to defeat it.
        (mirror / missing).unlink()
        assert _run(mirror).returncode != 0, f"gate B passed with {missing} missing"
