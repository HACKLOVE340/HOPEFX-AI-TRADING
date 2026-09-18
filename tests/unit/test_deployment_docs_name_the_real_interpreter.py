# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Both deployment guides told the reader to install the wrong Python.

`DEPLOYMENT.md` opens with

    Python 3.12 (must match the Docker image — `python:3.12-slim`)

and then, 160 lines later, hands the reader

    sudo apt-get install -y python3.10 python3.10-venv ...
    python3.10 -m venv venv

`docs/DEPLOYMENT.md` is worse: it states "Python 3.10, 3.11, or 3.12" up top,
installs 3.10 in one section and 3.12 in another.

CLAUDE.md already names why this is not cosmetic. The stated reason for pinning
the interpreter is pickle compatibility with the committed `.pkl` artifacts
under `ml/saved_models/`; anyone following the install block produces artifacts
under an interpreter that neither CI nor production ever loads. A header nobody
copy-pastes does not undo a command block everybody does.

The version is read from the Dockerfile rather than written here, because a
constant in a test is one more place that goes stale — the same defect in a
different costume. If the Dockerfile's Python changes, this test changes with
it, which is also what CLAUDE.md asks for ("if you change the Dockerfile's
Python, change the retrain workflows in the same commit").
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
DEPLOYMENT_DOCS = ("DEPLOYMENT.md", "docs/DEPLOYMENT.md")


def _dockerfile_python() -> str:
    text = (REPO / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^FROM\s+python:(\d+\.\d+)", text, re.MULTILINE)
    assert match, "no `FROM python:X.Y` in the Dockerfile — this test cannot know the target"
    return match.group(1)


class TestTheGuidesInstallWhatProductionRuns:
    @pytest.mark.parametrize("relative", DEPLOYMENT_DOCS)
    def test_no_command_names_a_different_interpreter(self, relative: str) -> None:
        target = _dockerfile_python()
        text = (REPO / relative).read_text(encoding="utf-8")

        wrong: list[tuple[int, str]] = []
        for number, line in enumerate(text.splitlines(), start=1):
            for found in re.findall(r"python(\d+\.\d+)", line):
                if found != target:
                    wrong.append((number, line.strip()))
        assert not wrong, (
            f"{relative} tells the reader to use a Python other than {target}, "
            f"which is what the Dockerfile runs:\n" + "\n".join(f"  line {n}: {line}" for n, line in wrong[:10])
        )

    @pytest.mark.parametrize("relative", DEPLOYMENT_DOCS)
    def test_the_stated_requirement_matches_the_dockerfile(self, relative: str) -> None:
        target = _dockerfile_python()
        text = (REPO / relative).read_text(encoding="utf-8")
        head = "\n".join(text.splitlines()[:20])
        assert target in head, f"{relative} does not state Python {target} in its opening lines:\n{head}"


class TestTheTestItselfIsMeasuringSomething:
    def test_it_reads_the_dockerfile_rather_than_a_constant(self) -> None:
        # A hardcoded "3.12" here would be a fourth place to go stale, which is
        # the defect this file exists to catch.
        assert _dockerfile_python() == "3.12"
