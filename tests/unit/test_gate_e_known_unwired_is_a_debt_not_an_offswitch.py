# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`KNOWN_UNWIRED` must stay a debt record, not a place things go to be forgotten.

Gate E reported zero dead files for its whole life. On 2026-09-09 three stacked
defects in its own detection were fixed — single-file guarded packages were
skipped, bare-package imports were not resolved, and a substring match excluded
every mirrored test file — and it immediately surfaced twelve unreferenced
modules, failing CI.

Deleting them is not an option (the owner's standing instruction), and wiring
twelve modules blind would be worse than leaving them: several are alternates
for something already running. So each is recorded with the reason it stays,
the same shape as gate-g's KNOWN_VIOLATIONS.

An allowlist with no pressure on it becomes an off-switch. Three properties keep
this one honest:

1. every entry carries a real reason, so nobody can add a path and move on;
2. no entry is stale — a module that has since been wired must leave the list,
   otherwise the list slowly stops describing anything;
3. every entry still exists, so a deleted file does not linger as a ghost.

Anything *not* in the registry still fails the gate, which is the part that
matters: a newly orphaned module blocks the build.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ci"))


@pytest.fixture(scope="module")
def gate():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gate_e_dead_files", REPO / "scripts" / "ci" / "gate_e_dead_files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEveryEntryIsJustified:
    def test_the_registry_is_not_empty(self, gate) -> None:
        # If this ever empties legitimately, delete the registry rather than
        # leaving an unused escape hatch lying about.
        assert gate.KNOWN_UNWIRED, "KNOWN_UNWIRED is empty — remove it rather than keeping an unused hatch"

    def test_every_entry_carries_a_substantial_reason(self, gate) -> None:
        thin = {p: r for p, r in gate.KNOWN_UNWIRED.items() if len(r.strip()) < 40}
        assert not thin, f"these entries have no real justification: {sorted(thin)}"

    def test_no_reason_is_a_placeholder(self, gate) -> None:
        banned = ("tbd", "todo", "fixme", "later", "for now", "temporarily")
        lazy = {p: r for p, r in gate.KNOWN_UNWIRED.items() if any(b in r.lower() for b in banned)}
        assert not lazy, f"placeholder reasons are how a debt record becomes a graveyard: {sorted(lazy)}"


class TestTheListDescribesReality:
    def test_every_listed_file_exists(self, gate) -> None:
        missing = [p for p in gate.KNOWN_UNWIRED if not (REPO / p).exists()]
        assert not missing, f"listed but gone — remove the entry: {missing}"

    def test_no_listed_file_has_since_been_wired(self, gate) -> None:
        """A module that gained a caller must leave the list.

        Otherwise the registry stops being a to-do and becomes scenery, and the
        next reader cannot tell which entries still describe something true.
        """
        wired = []
        for rel in sorted(gate.KNOWN_UNWIRED):
            dotted = rel.removesuffix(".py").replace("/", ".")
            for path in REPO.rglob("*.py"):
                r = path.relative_to(REPO).as_posix()
                if r == rel or r.startswith(("tests/", ".venv/", "scripts/")) or "__pycache__" in r:
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        names = {node.module} | {f"{node.module}.{a.name}" for a in node.names if a.name != "*"}
                    elif isinstance(node, ast.Import):
                        names = {a.name for a in node.names}
                    else:
                        continue
                    if dotted in names:
                        wired.append(f"{rel} (imported by {r})")
                        break
                if wired and wired[-1].startswith(rel):
                    break
        assert not wired, "these are wired now and should be removed from KNOWN_UNWIRED: " + "; ".join(wired)


class TestTheGateStillBites:
    def test_an_unlisted_orphan_still_fails(self, gate, tmp_path, monkeypatch) -> None:
        """The registry must narrow the gate, never disable it."""
        import subprocess
        import tempfile

        mirror = pathlib.Path(tempfile.mkdtemp(prefix="gate_e_known_"))
        for name in ("risk", "scripts/ci"):
            (mirror / name).mkdir(parents=True, exist_ok=True)
        (mirror / "risk" / "__init__.py").write_text("")
        (mirror / "risk" / "wired.py").write_text("VALUE = 1\n")
        (mirror / "risk" / "orphan.py").write_text("# nothing imports this\nVALUE = 2\n")
        (mirror / "app.py").write_text("from risk.wired import VALUE\n")

        gate_src = (REPO / "scripts" / "ci" / "gate_e_dead_files.py").read_text()
        (mirror / "scripts" / "ci" / "gate_e_dead_files.py").write_text(gate_src)

        result = subprocess.run(
            [sys.executable, str(mirror / "scripts" / "ci" / "gate_e_dead_files.py")],
            capture_output=True,
            text=True,
            cwd=mirror,
            check=False,
        )
        assert result.returncode == 1, (
            f"an unlisted orphan did not fail the gate — the registry disabled it.\n{result.stdout}"
        )
        assert "orphan.py" in result.stdout
