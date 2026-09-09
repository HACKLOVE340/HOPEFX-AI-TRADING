# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Nothing installed the pre-commit hooks, so none of the ratchets ever fired.

CLAUDE.md leans on seven ratcheted checks — document registry, documentation
freshness, Group 4 source preservation, volume-index drift, gate injection
evidence, stated-figure drift, and the per-module coverage gate — with the
sentence "the ratcheted checks below run in `pre-commit`, so a regression blocks
rather than accumulating".

They do not run. `.pre-commit-config.yaml` configures them correctly and
`scripts/bootstrap_dev.py` never runs `pre-commit install`, so a fresh clone has
no hook under `.git/hooks/`. Every one of those gates protects only a
contributor who remembers to invoke it by hand. That is the exact shape
`.claude/skills/hopefx-dead-controls` catalogues: a control that exists, is
documented accurately, and is never invoked — here applied to the machinery
whose job is catching that shape.

Two properties are asserted, and the second is the one that keeps this honest:

1. bootstrap runs `pre-commit install`;
2. it does not *fail* when it cannot — a developer without pre-commit on PATH
   must still get a working .env and seeded users. A bootstrap that dies on an
   optional step is a bootstrap people stop running, and then nothing is
   installed for a second reason.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import scripts.bootstrap_dev as boot


class TestItInstallsTheHooks:
    def test_bootstrap_runs_pre_commit_install(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        def _fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))

            class _R:
                returncode = 0
                stdout = "pre-commit installed at .git/hooks/pre-commit\n"
                stderr = ""

            return _R()

        monkeypatch.setattr(boot.subprocess, "run", _fake_run)
        assert boot.install_git_hooks(verbose=False) is True
        assert any("pre-commit" in " ".join(c) and "install" in c for c in calls), calls

    def test_a_missing_pre_commit_does_not_break_bootstrap(self, monkeypatch, caplog) -> None:
        import logging

        def _boom(*args, **kwargs):
            raise FileNotFoundError("pre-commit")

        monkeypatch.setattr(boot.subprocess, "run", _boom)
        with caplog.at_level(logging.WARNING):
            assert boot.install_git_hooks(verbose=True) is False
        assert any(r.levelno >= logging.WARNING for r in caplog.records), (
            "the hooks were not installed and nothing said so"
        )

    def test_a_nonzero_exit_is_reported_not_swallowed(self, monkeypatch, caplog) -> None:
        """Success reported for work that did not happen is the defect this
        whole exercise has been removing. It applies to this function too."""
        import logging

        class _R:
            returncode = 1
            stdout = ""
            stderr = "not a git repository"

        monkeypatch.setattr(boot.subprocess, "run", lambda *a, **k: _R())
        with caplog.at_level(logging.WARNING):
            assert boot.install_git_hooks(verbose=True) is False
        assert any("not a git repository" in r.getMessage() for r in caplog.records)


class TestBootstrapCallsIt:
    def test_the_step_is_part_of_bootstrap(self, monkeypatch) -> None:
        seen = {"called": False}
        monkeypatch.setattr(boot, "install_git_hooks", lambda verbose=True: seen.__setitem__("called", True))
        monkeypatch.setattr(boot, "_generate_env", lambda: False)
        monkeypatch.setattr(boot, "build_frontend", lambda verbose=True: True)
        for name in ("_seed_superadmin", "_seed_admin", "_seed_trader"):
            monkeypatch.setattr(boot, name, lambda: "x")

        boot.bootstrap(verbose=False)
        assert seen["called"], "bootstrap does not install the hooks it documents"
