# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_gate_broken_imports_baseline.py
===============================================
`scripts/ci/gate_broken_imports.py` finds `from <local.module> import <Name>`
where `<Name>` is not defined in that module. It found the kill switch being
unable to resolve a broker (S-38), database backups that had never run, and a
package layer advertising eleven names that resolved to None — and it was
wired into nothing, so it only ever ran when someone invoked it by hand.

It could not simply be added to CI: it reported 47 findings of mixed severity,
several of them intentional. So it now carries a `KNOWN_BROKEN` baseline and
runs in `tests.yml` as a blocking gate.

A baseline is only worth having if it cannot quietly become an excuse list.
Two properties make that true, and this file pins both:

  * a NEW broken import fails the gate even though a baseline exists;
  * a STALE entry — one that no longer describes a real defect — also fails,
    so fixing an import forces its entry to be deleted in the same change
    rather than lingering to mask the next one.

Without the second property the list only grows, and the gate degrades into a
record of things that used to be true.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE = _REPO_ROOT / "scripts" / "ci" / "gate_broken_imports.py"


def _gate_module():
    spec = importlib.util.spec_from_file_location("gate_broken_imports", _GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scratch_repo(tmp_path_factory, monkeypatch):
    """Point the gate at a throwaway tree instead of the repository."""
    root = tmp_path_factory.mktemp("brokenimports")

    def _install(gate, files: dict[str, str], known_broken: dict | None = None):
        for rel, body in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        monkeypatch.setattr(gate, "REPO_ROOT", root)
        monkeypatch.setattr(gate, "KNOWN_BROKEN", known_broken or {})
        monkeypatch.setattr(gate, "_BINDING_CACHE", {})
        return root

    return _install


def test_the_gate_passes_on_the_current_tree():
    """The baseline is accurate right now — no new findings, no stale entries."""
    assert _gate_module().main() == 0, "run scripts/ci/gate_broken_imports.py for the list"


def test_a_new_broken_import_still_fails(scratch_repo):
    """A baseline must not stop the gate catching the next one."""
    gate = _gate_module()
    scratch_repo(
        gate,
        {
            "target.py": "def real_name():\n    return 1\n",
            "caller.py": "from target import missing_name\n",
        },
    )

    assert gate.main() == 1, "a brand-new broken import passed while a baseline existed"


def test_a_baselined_import_is_allowed(scratch_repo):
    """The other half of the pair, so the check above cannot pass by always failing."""
    gate = _gate_module()
    scratch_repo(
        gate,
        {
            "target.py": "def real_name():\n    return 1\n",
            "caller.py": "from target import missing_name\n",
        },
        known_broken={("caller.py", "missing_name", "target"): "pinned for this test"},
    )

    assert gate.main() == 0, "a baselined import was reported as a new finding"


def test_a_stale_baseline_entry_fails(scratch_repo):
    """Fixing an import must force its entry out of the list."""
    gate = _gate_module()
    scratch_repo(
        gate,
        {
            "target.py": "def real_name():\n    return 1\n",
            "caller.py": "from target import real_name\n",  # no longer broken
        },
        known_broken={("caller.py", "real_name", "target"): "stale — the import was fixed"},
    )

    assert gate.main() == 1, (
        "a KNOWN_BROKEN entry that no longer describes a real defect was accepted; "
        "the list can now accumulate dead entries and mask the next real one"
    )


def test_every_baseline_entry_carries_a_justification():
    """An entry without a reason a reviewer can check is just a silencer."""
    known = _gate_module().KNOWN_BROKEN
    assert known, "the baseline is empty — this test would silently pass"

    for key, reason in known.items():
        assert isinstance(reason, str) and len(reason) >= 20, (
            f"{key} has no usable justification ({reason!r}). Say why it is there and where the fix is tracked."
        )


def test_every_baseline_entry_references_a_backlog_item():
    """Each known defect must be traceable to where its fix is tracked."""
    known = _gate_module().KNOWN_BROKEN
    unreferenced = [key for key, reason in known.items() if "S-" not in reason]
    assert not unreferenced, (
        f"{unreferenced} have no backlog reference (S-NN) in their justification, "
        f"so nothing records what the fix is or who owns it"
    )
