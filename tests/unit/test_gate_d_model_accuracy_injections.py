# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate D — the deployed model is the model the registry says it is.

`gate_d_model_accuracy.py` delegates to `ml.verify_model`, which checks the
active registry entry against what is actually on disk: the `current.pkl`
symlink resolves to the registered file, its SHA-256 matches, the Sharpe
gate passed on a credible number of trades, the state is `active`, and
`advanced_oos_meta.json` agrees with the registry.

This gate was deferred twice — MASTER_OUTSTANDING.md recorded that it
"validates 38 MB of model artefacts resolved from `__file__`, with no env
indirection, so a per-test mirror would make the suite slow" and needed
"a manifest-level injection instead — a different design".

**The premise was wrong, and that is the finding worth recording.** The
gate never requires the artefacts to be *large*; it requires them to be
*consistent*. A 26-byte file whose real SHA-256 is written into a
synthetic registry exercises every check — including the integrity hash,
against a real symlink, in a real subprocess — and the mirror is about a
kilobyte. No env indirection had to be added to the production script, and
nothing here reads or writes the real `ml/saved_models/`.

Result: the gate is alive. All fifteen refusals below were confirmed by
execution, and the wrapper propagates the inner exit code rather than
reporting its own success.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_d_model_accuracy.py"
VERIFY = REPO / "ml" / "verify_model.py"

_PKL_BYTES = b"not a real model, just bytes"


def _registry(sha: str) -> dict[str, Any]:
    return {
        "active_version": "xgb_test_v1",
        "schema_version": 1,
        "versions": {
            "xgb_test_v1": {
                "name": "xgb_test_v1",
                "file": "ml/saved_models/advanced_oos.pkl",
                "sha256": sha,
                "sharpe": 1.52,
                "sharpe_gate_passed": True,
                "n_trades": 2016,
                "state": "active",
                "horizon": 5,
                "oos_accuracy": 0.5734,
            }
        },
    }


def _meta(sha: str) -> dict[str, Any]:
    return {"horizon": 5, "sha256": sha, "oos_accuracy": 0.5734}


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A disposable repository whose model artefacts are consistent but tiny.

    The real saved_models/ is 38 MB; nothing here needs that. What the gate
    checks is agreement between the registry, the symlink, the hash and the
    meta — all of which a few hundred bytes can express faithfully.
    """
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    saved = root / "ml" / "saved_models"
    saved.mkdir(parents=True)

    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    shutil.copy2(VERIFY, root / "ml" / "verify_model.py")
    # The real ml/__init__.py pulls in the whole ML stack; the gate only needs
    # the package to be importable.
    (root / "ml" / "__init__.py").write_text("", encoding="utf-8")

    pkl = saved / "advanced_oos.pkl"
    pkl.write_bytes(_PKL_BYTES)
    (saved / "current.pkl").symlink_to("advanced_oos.pkl")

    sha = hashlib.sha256(_PKL_BYTES).hexdigest()
    (saved / "registry.json").write_text(json.dumps(_registry(sha), indent=2), encoding="utf-8")
    (saved / "advanced_oos_meta.json").write_text(json.dumps(_meta(sha), indent=2), encoding="utf-8")
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )


def _patch_registry(root: Path, **entry_changes: Any) -> None:
    """Mutate the active registry entry, and prove the edit landed."""
    path = root / "ml" / "saved_models" / "registry.json"
    before = path.read_text(encoding="utf-8")
    data = json.loads(before)
    data["versions"]["xgb_test_v1"].update(entry_changes)
    after = json.dumps(data, indent=2)
    assert after != before, "registry injection did not change anything — it would prove nothing"
    path.write_text(after, encoding="utf-8")


def _patch_meta(root: Path, **changes: Any) -> None:
    path = root / "ml" / "saved_models" / "advanced_oos_meta.json"
    before = path.read_text(encoding="utf-8")
    data = json.loads(before)
    data.update(changes)
    after = json.dumps(data, indent=2)
    assert after != before, "meta injection did not change anything — it would prove nothing"
    path.write_text(after, encoding="utf-8")


class TestTheMirrorIsFaithful:
    def test_a_consistent_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Gate D PASSED" in result.stdout

    def test_the_inner_verifier_actually_ran(self, mirror: Path) -> None:
        # A wrapper that never reached ml.verify_model would pass every case
        # below trivially.
        assert "[verify_model] OK" in _run(mirror).stdout


class TestTheRegistryMustDescribeWhatIsOnDisk:
    def test_a_missing_registry_fails(self, mirror: Path) -> None:
        (mirror / "ml" / "saved_models" / "registry.json").unlink()
        result = _run(mirror)
        assert result.returncode != 0
        assert "registry.json not found" in result.stderr

    def test_an_invalid_registry_fails(self, mirror: Path) -> None:
        (mirror / "ml" / "saved_models" / "registry.json").write_text("{broken", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode != 0
        assert "not valid JSON" in result.stderr

    def test_a_missing_active_version_fails(self, mirror: Path) -> None:
        path = mirror / "ml" / "saved_models" / "registry.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["active_version"]
        path.write_text(json.dumps(data), encoding="utf-8")
        result = _run(mirror)
        assert result.returncode != 0
        assert "active_version" in result.stderr

    def test_an_active_version_absent_from_versions_fails(self, mirror: Path) -> None:
        path = mirror / "ml" / "saved_models" / "registry.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["active_version"] = "xgb_does_not_exist"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = _run(mirror)
        assert result.returncode != 0
        assert "not found in registry versions" in result.stderr


class TestTheSymlinkAndHash:
    def test_a_missing_symlink_fails(self, mirror: Path) -> None:
        (mirror / "ml" / "saved_models" / "current.pkl").unlink()
        result = _run(mirror)
        assert result.returncode != 0
        assert "current.pkl symlink missing" in result.stderr

    def test_a_regular_file_in_place_of_the_symlink_fails(self, mirror: Path) -> None:
        link = mirror / "ml" / "saved_models" / "current.pkl"
        link.unlink()
        link.write_bytes(_PKL_BYTES)
        result = _run(mirror)
        assert result.returncode != 0
        assert "not a symlink" in result.stderr

    def test_a_symlink_to_the_wrong_file_fails(self, mirror: Path) -> None:
        saved = mirror / "ml" / "saved_models"
        (saved / "other.pkl").write_bytes(b"a different model entirely")
        (saved / "current.pkl").unlink()
        (saved / "current.pkl").symlink_to("other.pkl")
        result = _run(mirror)
        assert result.returncode != 0
        assert "expected" in result.stderr

    def test_a_tampered_model_file_fails_the_hash(self, mirror: Path) -> None:
        # The integrity check the 38 MB framing assumed could not be exercised
        # cheaply. It can: the hash does not care how big the file is.
        (mirror / "ml" / "saved_models" / "advanced_oos.pkl").write_bytes(_PKL_BYTES + b" tampered")
        result = _run(mirror)
        assert result.returncode != 0
        assert "SHA-256 mismatch" in result.stderr

    def test_a_registry_entry_with_no_hash_fails(self, mirror: Path) -> None:
        _patch_registry(mirror, sha256="")
        result = _run(mirror)
        assert result.returncode != 0
        assert "no sha256" in result.stderr


class TestTheSharpeGate:
    def test_sharpe_gate_not_passed_fails(self, mirror: Path) -> None:
        _patch_registry(mirror, sharpe_gate_passed=False)
        result = _run(mirror)
        assert result.returncode != 0
        assert "sharpe_gate_passed=False" in result.stderr

    def test_a_sharpe_below_the_floor_fails(self, mirror: Path) -> None:
        _patch_registry(mirror, sharpe=0.4)
        result = _run(mirror)
        assert result.returncode != 0
        assert "Sharpe=0.4" in result.stderr

    def test_too_few_trades_to_be_credible_fails(self, mirror: Path) -> None:
        _patch_registry(mirror, n_trades=12)
        result = _run(mirror)
        assert result.returncode != 0
        assert "not credible" in result.stderr

    def test_a_non_active_state_fails(self, mirror: Path) -> None:
        _patch_registry(mirror, state="staging")
        result = _run(mirror)
        assert result.returncode != 0
        assert "state='staging'" in result.stderr


class TestTheMetaMustAgreeWithTheRegistry:
    def test_a_missing_meta_fails(self, mirror: Path) -> None:
        (mirror / "ml" / "saved_models" / "advanced_oos_meta.json").unlink()
        result = _run(mirror)
        assert result.returncode != 0
        assert "advanced_oos_meta.json not found" in result.stderr

    def test_a_horizon_mismatch_fails(self, mirror: Path) -> None:
        _patch_meta(mirror, horizon=1)
        result = _run(mirror)
        assert result.returncode != 0
        assert "horizon mismatch" in result.stderr

    def test_a_hash_mismatch_between_meta_and_registry_fails(self, mirror: Path) -> None:
        _patch_meta(mirror, sha256="0" * 64)
        result = _run(mirror)
        assert result.returncode != 0
        assert "sha256 mismatch between meta" in result.stderr

    def test_an_unreconciled_null_accuracy_fails(self, mirror: Path) -> None:
        _patch_meta(mirror, oos_accuracy=None)
        result = _run(mirror)
        assert result.returncode != 0
        assert "oos_accuracy=null" in result.stderr


class TestTheWrapperPropagatesRatherThanReportsItsOwnSuccess:
    """Gate D is a thin wrapper. A wrapper that swallowed the inner exit code
    would report PASSED over a failed verification — the shape gates M, K and
    F each had in a different form."""

    def test_a_failure_is_reported_as_gate_d_failed(self, mirror: Path) -> None:
        _patch_registry(mirror, sharpe_gate_passed=False)
        result = _run(mirror)
        assert result.returncode != 0
        assert "Gate D FAILED" in result.stdout
        assert "Gate D PASSED" not in result.stdout

    def test_a_crash_in_the_inner_verifier_is_not_a_pass(self, mirror: Path) -> None:
        (mirror / "ml" / "verify_model.py").write_text(
            "import sys\n\nprint('exploded', file=sys.stderr)\nsys.exit(3)\n", encoding="utf-8"
        )
        result = _run(mirror)
        assert result.returncode == 3, "the wrapper did not propagate the inner exit code"
        assert "Gate D PASSED" not in result.stdout


class TestTheRealTreeStillPasses:
    def test_the_real_gate_passes_against_the_real_artefacts(self) -> None:
        result = subprocess.run(  # nosec B603 — fixed argument list, no shell
            [sys.executable, str(GATE)],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )
        assert result.returncode == 0, f"the real model artefacts are inconsistent:\n{result.stdout}{result.stderr}"
        assert "Gate D PASSED" in result.stdout
