# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""`scripts/e2e_production_validation.py` checks do what their names promise.

The script prints "All critical checks passed. System is production-ready."
Twenty-two checks stand behind that sentence and none of them was tested.

Two named an import they never performed:

* **"Execution: ExecutionEngine imports cleanly, no forbidden imports"** read
  `execution/execution.py` as TEXT and imported nothing. `ExecutionEngine` is
  in `execution/engine.py` — a different file, which the check never opened.
  So it validated a module with no production importer while the class in its
  own title went unchecked, and "imports cleanly" was tested by nothing.
* **"API: data_layer router importable, no forbidden imports"** did the
  forbidden-import half properly over seven patterns, and never imported the
  router, so "importable" was likewise untested.

This is F176 with a false label attached: a control that exists, reads
plausibly, and does not do the thing its name is the promise of. A checker that
reads prose is not reading code — and a checker that reads the wrong file is
not reading anything relevant.

Nothing here loosens either check. Both still fail on a forbidden import; they
now also fail on an import error, which is what they always claimed to catch.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def script():
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        return importlib.import_module("e2e_production_validation")
    finally:
        sys.path.pop(0)


class TestTheHarnessIsLive:
    def test_the_script_exposes_its_checks(self, script):
        assert callable(script.check_execution)
        assert callable(script.check_api)

    def test_a_check_returns_true_when_it_passes(self, script, monkeypatch):
        """The decorator swallows exceptions and returns False, so a check that
        cannot run looks exactly like a check that failed. Confirm the healthy
        shape before asserting anything about the unhealthy one."""
        monkeypatch.chdir(REPO)
        assert script.check_api() is True


class TestTheExecutionCheckReadsTheFileItNames:
    """Proven by behaviour, not by reading the source.

    The first draft of these tests used `inspect.getsource(check_execution)` —
    which returns the DECORATOR'S WRAPPER, not the check, so it was asserting
    over the wrong function's text entirely. A text match tests how code is
    written; calling it tests what it does.
    """

    def test_it_passes_on_the_real_repository(self, script, monkeypatch):
        monkeypatch.chdir(REPO)
        assert script.check_execution() is True

    def test_it_fails_when_the_import_is_broken(self, script, monkeypatch):
        """The half that was never tested. Breaking the import must fail the
        check — otherwise "imports cleanly" is decoration."""
        monkeypatch.chdir(REPO)
        monkeypatch.setitem(sys.modules, "execution.engine", None)

        assert script.check_execution() is False

    def test_a_forbidden_import_in_engine_py_fails_the_check(self, script, monkeypatch, tmp_path):
        """engine.py is where ExecutionEngine lives, so engine.py is what the
        check must screen."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "execution").mkdir()
        (tmp_path / "execution" / "engine.py").write_text("from data_layer.lineage.store import Thing\n")

        assert script.check_execution() is False

    def test_it_no_longer_screens_the_module_with_no_production_importer(self, script, monkeypatch, tmp_path):
        """The positive form of the fix: a forbidden import in
        `execution/execution.py` — the file the check used to read, and which
        nothing in production imports — is no longer what this check is about.

        Screened by `check_architecture`, which lists that path explicitly, so
        nothing stops being covered.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "execution").mkdir()
        (tmp_path / "execution" / "engine.py").write_text("# clean\n")
        (tmp_path / "execution" / "execution.py").write_text("from data_layer.lineage.store import Thing\n")

        assert script.check_execution() is True, "the check is still reading the wrong file"

    def test_the_architecture_check_still_covers_that_file(self, script):
        """So the fix moves responsibility rather than dropping it."""
        import inspect

        source = inspect.getsource(script.check_architecture.__wrapped__)
        assert "execution/execution.py" in source


class TestTheApiCheckActuallyImports:
    def test_it_passes_on_the_real_repository(self, script, monkeypatch):
        monkeypatch.chdir(REPO)
        assert script.check_api() is True

    def test_it_fails_when_the_router_cannot_be_imported(self, script, monkeypatch):
        monkeypatch.chdir(REPO)
        monkeypatch.setitem(sys.modules, "api.data_layer", None)

        assert script.check_api() is False

    def test_it_still_fails_on_a_forbidden_import(self, script, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "api").mkdir()
        (tmp_path / "api" / "data_layer.py").write_text("from data_layer.lineage.store import Thing\n")

        assert script.check_api() is False


class TestTheTwoImportGatesAgree:
    """`data_layer`'s public surface is defined in one place and enforced in two.

    `scripts/ci/gate_g_import_discipline.py` runs in pre-commit and holds
    `DATA_LAYER_PUBLIC = {"orchestrator", "tick_store", "feeds"}`. CLAUDE.md and
    ADR 0013 say the same: the public surface is `data_layer.orchestrator`,
    `data_layer.tick_store`, `data_layer.feeds.*`.

    `scripts/e2e_production_validation.py` listed `"from data_layer.feeds."` as
    FORBIDDEN — stricter than the documented rule, and contradicting the gate
    that actually runs. Because the validation script is not wired into CI,
    that disagreement was invisible until someone ran it by hand, whereupon it
    reported a legitimate import as a critical violation and printed "Fix
    before deploying".

    A detector that cries wolf trains its readers to ignore it. That warning is
    written in this repository's own `compliance/auditor.py`, about this exact
    failure mode.

    Two gates enforcing one boundary must not disagree about where it is.
    """

    @staticmethod
    def _gate_g_public() -> set[str]:
        sys.path.insert(0, str(REPO / "scripts" / "ci"))
        try:
            mod = importlib.import_module("gate_g_import_discipline")
            return set(mod.DATA_LAYER_PUBLIC)
        finally:
            sys.path.pop(0)

    @staticmethod
    def _e2e_forbidden(script) -> list[str]:
        import inspect
        import re

        source = inspect.getsource(script.check_architecture.__wrapped__)
        block = source.split("FORBIDDEN", 1)[1].split("]", 1)[0]
        return re.findall(r'"from (data_layer\.[a-z_]+)\.', block)

    def test_both_gates_are_readable(self, script):
        """Liveness: two empty sets agree about everything."""
        assert self._gate_g_public(), "gate-g's public surface is empty"
        assert self._e2e_forbidden(script), "the e2e forbidden list did not parse"

    def test_no_public_sub_package_is_listed_as_forbidden(self, script):
        public = self._gate_g_public()
        forbidden = {f.split(".", 1)[1] for f in self._e2e_forbidden(script)}

        overlap = public & forbidden
        assert not overlap, (
            f"the e2e validation script forbids {sorted(overlap)}, which "
            f"scripts/ci/gate_g_import_discipline.py and CLAUDE.md both declare PUBLIC. "
            f"Two gates enforcing one boundary must agree about where it is."
        )

    def test_the_architecture_check_passes_on_the_real_repository(self, script, monkeypatch):
        """The consequence: it was reporting a legitimate import as critical."""
        monkeypatch.chdir(REPO)
        assert script.check_architecture() is True
