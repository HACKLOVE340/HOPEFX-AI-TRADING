# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate G — canonical packages must not import from legacy ones, and must
reach data_layer only through its public surface.

It had no test, and injecting found two real gaps in the data_layer rule.
Both were confirmed by execution against the real gate before being fixed:

    from data_layer.sentiment import x    -> exit 0   (should fail)
    import data_layer.internal.thing      -> exit 0   (should fail)
    from data_layer.internal.thing import x -> exit 1 (correct)
    from backtest.engine import x         -> exit 1   (correct)

The first: `_is_data_layer_internal` required `len(parts) >= 3`, so every
top-level private module — `data_layer.sentiment`, `data_layer.microstructure`,
`data_layer.validation` — passed unexamined, even though the rule it
enforces names exactly three public modules. The second: the function
examined only `ast.ImportFrom`, so the plain `import x.y.z` form was never
checked at all.

Fixing both surfaced seven pre-existing violations across api/, ml/ and
backtesting/. They are recorded in KNOWN_VIOLATIONS rather than fixed,
because fixing them means deciding what data_layer's public surface
actually is — owner decision A2 — not changing a gate.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_g_import_discipline.py"


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A disposable repository with one guarded package, data_layer, and a
    legacy package — the three shapes this gate reasons about."""
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)

    for pkg in ("core", "data_layer", "data_layer/internal", "data_layer/feeds", "backtest", "strategy"):
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")

    (root / "data_layer" / "orchestrator.py").write_text("orchestrator = object()\n", encoding="utf-8")
    (root / "data_layer" / "tick_store.py").write_text("store = object()\n", encoding="utf-8")
    (root / "data_layer" / "sentiment.py").write_text("def get_sentiment():\n    return 0\n", encoding="utf-8")
    (root / "data_layer" / "internal" / "thing.py").write_text("x = 1\n", encoding="utf-8")
    (root / "data_layer" / "feeds" / "macro.py").write_text("feed = object()\n", encoding="utf-8")
    (root / "backtest" / "engine.py").write_text("x = 1\n", encoding="utf-8")
    (root / "strategy" / "legacy_engine.py").write_text("x = 1\n", encoding="utf-8")
    (root / "core" / "clean.py").write_text("from data_layer.orchestrator import orchestrator\n", encoding="utf-8")
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )


def _inject(root: Path, rel: str, source: str) -> None:
    """Write a file into the mirror, and prove it landed."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == source, "injection did not land — it would prove nothing"


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_gate_actually_scanned_something(self, mirror: Path) -> None:
        # A gate that walked zero packages passes every case below trivially.
        assert "checked 15 packages" in _run(mirror).stdout


class TestLegacyImports:
    def test_import_from_a_legacy_package_fails(self, mirror: Path) -> None:
        _inject(mirror, "core/bad.py", "from backtest.engine import x\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "legacy package" in result.stdout
        assert "core/bad.py" in result.stdout

    def test_plain_import_of_a_legacy_package_fails(self, mirror: Path) -> None:
        _inject(mirror, "core/bad.py", "import strategy.legacy_engine\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "legacy package" in result.stdout

    def test_a_top_level_file_is_scanned_too(self, mirror: Path) -> None:
        _inject(mirror, "toplevel_app.py", "from backtest.engine import x\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "toplevel_app.py" in result.stdout


class TestTheDataLayerPublicSurface:
    @pytest.mark.parametrize(
        "source",
        [
            "from data_layer.orchestrator import orchestrator\n",
            "from data_layer.tick_store import store\n",
            "from data_layer.feeds.macro import feed\n",
            "import data_layer\n",
        ],
    )
    def test_the_public_surface_is_allowed(self, mirror: Path, source: str) -> None:
        _inject(mirror, "core/user.py", source)
        result = _run(mirror)
        assert result.returncode == 0, f"{source!r} was rejected:\n{result.stdout}"

    def test_a_deep_internal_import_fails(self, mirror: Path) -> None:
        # The one shape that already worked before the fix.
        _inject(mirror, "core/user.py", "from data_layer.internal.thing import x\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "data_layer internal" in result.stdout

    def test_a_two_segment_private_import_fails(self, mirror: Path) -> None:
        # Defect 1, confirmed exit 0 before the fix: `len(parts) >= 3` meant a
        # top-level private module was never examined, though the public
        # surface is exactly three names.
        _inject(mirror, "core/user.py", "from data_layer.sentiment import get_sentiment\n")
        result = _run(mirror)
        assert result.returncode == 1, "a direct import of a private data_layer module did not fail the gate"
        assert "data_layer.sentiment" in result.stdout

    def test_the_plain_import_statement_form_fails(self, mirror: Path) -> None:
        # Defect 2, confirmed exit 0 before the fix: only ImportFrom was
        # examined, so `import data_layer.internal.thing` was never checked.
        _inject(mirror, "core/user.py", "import data_layer.internal.thing\n")
        result = _run(mirror)
        assert result.returncode == 1, "`import data_layer.internal.thing` did not fail the gate"
        assert "data_layer.internal.thing" in result.stdout

    def test_files_inside_data_layer_may_import_each_other(self, mirror: Path) -> None:
        # Documented scope, not a bypass: the rule is about reaching internals
        # from OUTSIDE data_layer.
        _inject(mirror, "data_layer/consumer.py", "from data_layer.internal.thing import x\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout


class TestTheKnownViolationsEscapeHatchIsScoped:
    """KNOWN_VIOLATIONS downgrades a listed violation to a warning. A list
    that silenced anything else — or that could not be narrowed — would be an
    off-switch rather than a debt record, so both directions are pinned."""

    def _set_known(self, root: Path, entries: str) -> None:
        gate = root / "scripts" / "ci" / GATE.name
        src = gate.read_text(encoding="utf-8")
        marker = "KNOWN_VIOLATIONS: frozenset[str] = frozenset("
        assert marker in src, "KNOWN_VIOLATIONS declaration moved — this fixture no longer patches anything"
        head, _, tail = src.partition(marker)
        _, _, after = tail.partition("\n)")
        patched = f"{head}KNOWN_VIOLATIONS: frozenset[str] = frozenset({entries}\n){after}"
        assert patched != src, "patch did not apply — it would prove nothing"
        gate.write_text(patched, encoding="utf-8")

    def test_a_listed_violation_warns_instead_of_failing(self, mirror: Path) -> None:
        _inject(mirror, "core/known.py", "from backtest.engine import x\n")
        self._set_known(mirror, '{"core/known.py:backtest.engine"}')
        result = _run(mirror)
        assert result.returncode == 0, result.stdout
        assert "WARN" in result.stdout
        assert "core/known.py:1" in result.stdout

    def test_an_unlisted_violation_still_fails_alongside_a_listed_one(self, mirror: Path) -> None:
        _inject(mirror, "core/known.py", "from backtest.engine import x\n")
        _inject(mirror, "core/fresh.py", "from backtest.engine import x\n")
        self._set_known(mirror, '{"core/known.py:backtest.engine"}')
        result = _run(mirror)
        assert result.returncode == 1, "a new violation was swallowed by the known-violations list"
        assert "core/fresh.py" in result.stdout

    def test_a_listed_entry_does_not_cover_another_module_in_the_same_file(self, mirror: Path) -> None:
        # This is where the narrowness has to hold. The keys used to carry line
        # numbers, and this test pinned that a listed entry did not cover the
        # same file on a *different line* — which turned out to be granularity
        # in the wrong dimension (see the KNOWN_VIOLATIONS comment in the gate).
        # The property worth having is that listing one import does not
        # silence a different one.
        _inject(mirror, "core/known.py", "from backtest.engine import x\nfrom strategy.legacy import y\n")
        self._set_known(mirror, '{"core/known.py:backtest.engine"}')
        result = _run(mirror)
        assert result.returncode == 1, "listing one legacy import silenced a different one in the same file"
        assert "strategy.legacy" in result.stdout

    def test_a_listed_entry_does_not_cover_the_same_module_in_another_file(self, mirror: Path) -> None:
        _inject(mirror, "core/known.py", "from backtest.engine import x\n")
        _inject(mirror, "brain/elsewhere.py", "from backtest.engine import x\n")
        self._set_known(mirror, '{"core/known.py:backtest.engine"}')
        result = _run(mirror)
        assert result.returncode == 1
        assert "brain/elsewhere.py" in result.stdout

    def test_moving_a_listed_import_down_the_file_is_not_a_new_violation(self, mirror: Path) -> None:
        """The regression this re-keying exists for.

        Under line-number keys, adding any lines above a recorded import made
        the gate fail CI claiming a brand-new violation in an import nobody
        had touched — which is what happened to ml/inference_engine.py's
        data_layer.validation import when it moved from line 1097 to 1184.
        The repair for that false failure was "bump the number", and a bumped
        number is indistinguishable in a diff from allowlisting a real new
        import.
        """
        _inject(mirror, "core/known.py", "from backtest.engine import x\n")
        self._set_known(mirror, '{"core/known.py:backtest.engine"}')
        assert _run(mirror).returncode == 0, "baseline is wrong — the listed import should warn, not fail"

        # Same import, twenty lines further down. Nothing about the debt changed.
        _inject(mirror, "core/known.py", "import os\n" * 20 + "from backtest.engine import x\n")
        result = _run(mirror)
        assert result.returncode == 0, (
            "moving a recorded import down the file was reported as a NEW violation:\n" + result.stdout
        )
        assert "WARN" in result.stdout


class TestTheRealRepositoryDebtIsRecorded:
    def test_the_seven_known_violations_are_still_warnings_not_failures(self) -> None:
        """The real gate against the real tree: seven pre-existing data_layer
        imports are recorded debt, so the gate passes while naming them."""
        result = subprocess.run(  # nosec B603 — fixed argument list, no shell
            [sys.executable, str(GATE)],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )
        assert result.returncode == 0, f"the real tree has a NEW violation:\n{result.stdout}"
        assert "WARN" in result.stdout
        assert "data_layer.validation" in result.stdout
