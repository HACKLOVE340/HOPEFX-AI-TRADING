# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate F — the API the documentation shows must be the API the code has.

Scans fenced ```python blocks in ARCHITECTURE.md, AGENTS.md and
CONTRIBUTING.md, and checks that every `from x import y` resolves and every
PascalCase call refers to something the repository actually defines. It had
no test.

Injecting found the same defect this ratchet has now hit three times —
gate M with a missing dataset, gate K with a missing requirements file, and
here with a missing document:

    all three documents absent -> "[gate-f] PASS — checked 3 docs, no violations", exit 0

A rename of ARCHITECTURE.md turned the gate off with CI green, and the
count in that message came from `len(DOCS_TO_SCAN)` — the length of a
constant tuple — not from anything read. Fixed the way gates M and K were:
a missing document fails closed, `DOC_ALLOW_SKIP=1` is the explicit local
opt-out, and the number reported is now what was actually checked.

The mirror uses synthetic docs against a small synthetic module tree,
because the real documents reference the real repository's modules and
`_repo_defines_name` resolves against REPO_ROOT. One test at the end runs
the real gate against the real tree, so the mirror cannot drift into
proving something about a repository that does not exist.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_f_doc_consistency.py"

_GOOD_DOC = """# Title

Some prose.

```python
from mypkg.thing import RealClass

instance = RealClass()
```
"""


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A disposable repository: the real gate, a small module tree, and the
    three documents the gate insists on."""
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)

    (root / "mypkg").mkdir()
    (root / "mypkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "mypkg" / "thing.py").write_text(
        "class RealClass:\n    pass\n\n\ndef real_function():\n    return 1\n", encoding="utf-8"
    )

    for name in ("ARCHITECTURE.md", "AGENTS.md", "CONTRIBUTING.md"):
        (root / name).write_text(_GOOD_DOC, encoding="utf-8")
    return root


def _run(root: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
        env=full_env,
    )


def _set_doc(root: Path, name: str, body: str) -> None:
    path = root / name
    before = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(body, encoding="utf-8")
    assert path.read_text(encoding="utf-8") != before, "injection did not change the document"


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_reported_count_is_what_was_read(self, mirror: Path) -> None:
        # The old message took its number from len(DOCS_TO_SCAN), so it read
        # "checked 3 docs" even when it had opened none.
        assert "checked 3 docs" in _run(mirror).stdout


class TestASkipIsNotAPass:
    """Third instance of this shape in the ratchet, after gates M and K."""

    def test_one_missing_document_fails(self, mirror: Path) -> None:
        (mirror / "ARCHITECTURE.md").unlink()
        result = _run(mirror)
        assert result.returncode == 1, "a renamed ARCHITECTURE.md silently disabled the gate"
        assert "ARCHITECTURE.md" in result.stdout

    def test_all_documents_missing_fails_rather_than_claiming_three_were_checked(self, mirror: Path) -> None:
        for name in ("ARCHITECTURE.md", "AGENTS.md", "CONTRIBUTING.md"):
            (mirror / name).unlink()
        result = _run(mirror)
        assert result.returncode == 1
        assert "no violations" not in result.stdout, "the gate reported a clean result having read nothing"

    def test_the_opt_out_is_explicit_and_works(self, mirror: Path) -> None:
        (mirror / "AGENTS.md").unlink()
        result = _run(mirror, env={"DOC_ALLOW_SKIP": "1"})
        assert result.returncode == 0
        assert "SKIP" in result.stdout
        assert "DOC_ALLOW_SKIP" in result.stdout

    def test_the_opt_out_does_not_apply_when_unset(self, mirror: Path) -> None:
        # The positive control for the case above: the escape hatch must be
        # something you reach for, not the default.
        (mirror / "AGENTS.md").unlink()
        result = _run(mirror, env={"DOC_ALLOW_SKIP": ""})
        assert result.returncode == 1


class TestRule1ImportsResolve:
    def test_a_module_that_does_not_exist_fails(self, mirror: Path) -> None:
        _set_doc(
            mirror,
            "ARCHITECTURE.md",
            "# T\n\n```python\nfrom mypkg.gone import RealClass\n```\n",
        )
        result = _run(mirror)
        assert result.returncode == 1
        assert "mypkg.gone" in result.stdout

    def test_a_name_missing_from_a_real_module_fails(self, mirror: Path) -> None:
        _set_doc(
            mirror,
            "ARCHITECTURE.md",
            "# T\n\n```python\nfrom mypkg.thing import RenamedClass\n```\n",
        )
        result = _run(mirror)
        assert result.returncode == 1
        assert "RenamedClass" in result.stdout

    def test_a_correct_import_passes(self, mirror: Path) -> None:
        _set_doc(
            mirror,
            "ARCHITECTURE.md",
            "# T\n\n```python\nfrom mypkg.thing import real_function\n```\n",
        )
        result = _run(mirror)
        assert result.returncode == 0, result.stdout

    def test_external_packages_are_not_resolved(self, mirror: Path) -> None:
        # Documented scope: stdlib and third-party imports are skipped, not
        # looked up in the repo.
        _set_doc(
            mirror,
            "ARCHITECTURE.md",
            "# T\n\n```python\nfrom fastapi import APIRouter\nfrom pathlib import Path\n```\n",
        )
        result = _run(mirror)
        assert result.returncode == 0, result.stdout


class TestRule2ReferencedClassesExist:
    def test_a_class_the_repo_does_not_define_fails(self, mirror: Path) -> None:
        _set_doc(mirror, "ARCHITECTURE.md", "# T\n\n```python\nx = NuclearWordmapScorer()\n```\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "NuclearWordmapScorer" in result.stdout

    def test_a_class_the_repo_does_define_passes(self, mirror: Path) -> None:
        _set_doc(mirror, "ARCHITECTURE.md", "# T\n\n```python\nx = RealClass()\n```\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout

    def test_placeholder_names_are_skipped(self, mirror: Path) -> None:
        # Documented scope: SKIP_NAMES covers illustrative names like
        # MyStrategy that a doc example is expected to invent.
        _set_doc(mirror, "ARCHITECTURE.md", "# T\n\n```python\ns = MyStrategy()\nb = BaseBroker()\n```\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout

    def test_only_fenced_python_blocks_are_scanned(self, mirror: Path) -> None:
        # Prose naming a class that does not exist is not a code claim.
        _set_doc(mirror, "ARCHITECTURE.md", "# T\n\nThe NuclearWordmapScorer() handles scoring.\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout


class TestTheRealTreeStillPasses:
    def test_the_real_gate_passes_against_the_real_documents(self) -> None:
        result = subprocess.run(  # nosec B603 — fixed argument list, no shell
            [sys.executable, str(GATE)],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )
        assert result.returncode == 0, f"the real docs drifted from the code:\n{result.stdout}"
        assert "checked 3 docs" in result.stdout
