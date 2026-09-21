# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""`ml/verify_model.py` — the gate that decides whether a model may serve.

Six checks: the symlink exists and is a symlink, it resolves to the file the
registry names, the pkl's SHA-256 matches the registry, the Sharpe gate passed,
the state is "active", and the meta file agrees with the registry.

It measured 17%, which for a gate is the wrong kind of number: the covered
sixth was the happy path, so nothing had ever established that any of the six
checks can *fail*. That is the first question `hopefx-dead-controls` asks, and
it is the question this file answers — every check below is driven from both
sides, with a healthy tree that passes and one broken field that must not.

It is a live gate. `scripts/ci/gate_d_model_accuracy.py` shells out to it (CI
Gate D), `.github/workflows/ci.yml:398`, `retrain.yml:127` and
`quarterly_retrain.yml:195` run `python -m ml.verify_model`, and
`scripts/retrain.sh:119` refuses to deploy when it exits non-zero.

The module reads four module-level paths fixed at import from `__file__`, so
every test here redirects them at a tmp tree rather than writing into
`ml/saved_models/`.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import ml.verify_model as vm

PKL_BYTES = b"a pickled model, for the purposes of a checksum"
PKL_SHA = hashlib.sha256(PKL_BYTES).hexdigest()


class ModelTree:
    """A model directory laid out the way the real one is, under tmp_path."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.saved = root / "ml" / "saved_models"
        self.saved.mkdir(parents=True)
        self.pkl = self.saved / "xgb_horizon5_v3.pkl"
        self.pkl.write_bytes(PKL_BYTES)
        self.symlink = self.saved / "current.pkl"
        self.symlink.symlink_to(self.pkl.name)
        self.registry_path = self.saved / "registry.json"
        self.meta_path = self.saved / "advanced_oos_meta.json"
        self.registry: dict[str, Any] = {
            "active_version": "xgb_horizon5_v3",
            "versions": {
                "xgb_horizon5_v3": {
                    "file": "ml/saved_models/xgb_horizon5_v3.pkl",
                    "sha256": PKL_SHA,
                    "sharpe": 1.52,
                    "sharpe_gate_passed": True,
                    "n_trades": 2016,
                    "horizon": 5,
                    "state": "active",
                }
            },
        }
        self.meta: dict[str, Any] = {"horizon": 5, "sha256": PKL_SHA, "oos_accuracy": 0.61}
        self.write()

    @property
    def entry(self) -> dict[str, Any]:
        return self.registry["versions"][self.registry["active_version"]]

    def write(self) -> None:
        self.registry_path.write_text(json.dumps(self.registry))
        self.meta_path.write_text(json.dumps(self.meta))

    def verify(self) -> list[str]:
        self.write()
        return vm.verify()


@pytest.fixture
def tree(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> ModelTree:
    model_tree = ModelTree(tmp_path)
    monkeypatch.setattr(vm, "_SAVED", model_tree.saved)
    monkeypatch.setattr(vm, "_REGISTRY", model_tree.registry_path)
    monkeypatch.setattr(vm, "_SYMLINK", model_tree.symlink)
    monkeypatch.setattr(vm, "_META", model_tree.meta_path)
    return model_tree


def _one(failures: list[str], fragment: str) -> str:
    matches = [f for f in failures if fragment in f]
    assert matches, f"no failure mentioning {fragment!r}; got {failures}"
    return matches[0]


class TestTheGateCanPassAndCanFail:
    """Before any individual check is worth testing: does this gate have two
    outcomes? A verifier that cannot fail is a green tick with no meaning
    behind it, and a verifier that cannot pass gets bypassed within a week."""

    def test_a_healthy_tree_passes_every_check(self, tree: ModelTree) -> None:
        assert tree.verify() == []

    def test_a_broken_tree_fails(self, tree: ModelTree) -> None:
        tree.entry["sha256"] = "0" * 64
        assert tree.verify() != []

    def test_the_healthy_tree_exits_zero(self, tree: ModelTree, capsys) -> None:
        assert vm.main() == 0
        assert "OK" in capsys.readouterr().out

    def test_a_broken_tree_exits_one(self, tree: ModelTree, capsys) -> None:
        tree.entry["state"] = "staging"
        tree.write()
        assert vm.main() == 1


class TestTheRegistryMustBeReadableBeforeAnythingElse:
    def test_a_missing_registry_is_the_only_thing_reported(self, tree: ModelTree) -> None:
        """Reporting six consequential failures when the cause is one missing
        file buries the cause."""
        tree.registry_path.unlink()
        failures = vm.verify()
        assert len(failures) == 1
        assert "registry.json not found" in failures[0]

    def test_a_corrupt_registry_is_reported_as_corrupt_not_as_a_bad_model(self, tree: ModelTree) -> None:
        tree.registry_path.write_text("{not json at all")
        failures = vm.verify()
        assert len(failures) == 1
        assert "not valid JSON" in failures[0]

    def test_a_registry_with_no_active_version_stops_there(self, tree: ModelTree) -> None:
        del tree.registry["active_version"]
        failures = tree.verify()
        assert len(failures) == 1
        assert "missing 'active_version'" in failures[0]

    def test_an_empty_active_version_is_treated_as_absent(self, tree: ModelTree) -> None:
        tree.registry["active_version"] = ""
        assert "missing 'active_version'" in _one(tree.verify(), "active_version")

    def test_an_active_version_with_no_entry_stops_there(self, tree: ModelTree) -> None:
        """Naming a version the registry does not describe is a registry that
        cannot be reasoned about — every later check would read an empty dict
        and report its defaults as the model's properties."""
        tree.registry["active_version"] = "a_version_that_was_never_written"
        failures = tree.verify()
        assert len(failures) == 1
        assert "not found in registry versions" in failures[0]


class TestTheSymlinkMustPointAtTheRegisteredModel:
    def test_a_missing_symlink_is_reported(self, tree: ModelTree) -> None:
        tree.symlink.unlink()
        assert "current.pkl symlink missing" in _one(tree.verify(), "symlink missing")

    def test_a_plain_file_in_its_place_is_refused(self, tree: ModelTree) -> None:
        """A `cp` where a `ln -s` was meant leaves a copy that stops tracking
        the registry the moment the next model is promoted."""
        tree.symlink.unlink()
        tree.symlink.write_bytes(PKL_BYTES)
        assert "not a symlink" in _one(tree.verify(), "not a symlink")

    def test_a_symlink_to_another_model_is_refused(self, tree: ModelTree) -> None:
        """The failure this whole check exists for: serving a model the
        registry does not describe, with the registry's Sharpe on the label."""
        other = tree.saved / "some_other_model.pkl"
        other.write_bytes(b"a different model entirely")
        tree.symlink.unlink()
        tree.symlink.symlink_to(other.name)
        failure = _one(tree.verify(), "resolves to")
        assert "some_other_model.pkl" in failure
        assert "xgb_horizon5_v3" in failure

    def test_the_failure_names_what_the_link_actually_points_at(self, tree: ModelTree) -> None:
        other = tree.saved / "some_other_model.pkl"
        other.write_bytes(b"x")
        tree.symlink.unlink()
        tree.symlink.symlink_to(other.name)
        assert "current.pkl → 'some_other_model.pkl'" in _one(tree.verify(), "resolves to")

    def test_a_repo_relative_registry_path_resolves(self, tree: ModelTree) -> None:
        """`file` is recorded relative to the repository root."""
        tree.entry["file"] = "ml/saved_models/xgb_horizon5_v3.pkl"
        assert tree.verify() == []

    def test_a_bare_filename_in_the_registry_also_resolves(self, tree: ModelTree) -> None:
        """Accepted on purpose — `expected_rel` exists so a registry written
        with just the basename is not read as a mismatch."""
        tree.entry["file"] = "xgb_horizon5_v3.pkl"
        assert tree.verify() == []


class TestTheChecksumIsTheOnlyProofTheFileIsTheModel:
    def test_a_matching_digest_passes(self, tree: ModelTree) -> None:
        assert tree.verify() == []

    def test_a_changed_file_is_caught(self, tree: ModelTree) -> None:
        """Same path, same symlink, same registry — only the bytes differ.
        Nothing else in these six checks would notice."""
        tree.pkl.write_bytes(PKL_BYTES + b" tampered")
        failure = _one(tree.verify(), "SHA-256 mismatch")
        assert PKL_SHA in failure

    def test_an_entry_with_no_digest_is_refused_rather_than_skipped(self, tree: ModelTree) -> None:
        """The dead-control shape: an absent expectation must not read as a
        satisfied one. Without this branch a registry entry could opt out of
        integrity checking by omitting a field."""
        del tree.entry["sha256"]
        assert "cannot verify integrity" in _one(tree.verify(), "cannot verify")

    def test_an_empty_digest_is_refused_too(self, tree: ModelTree) -> None:
        tree.entry["sha256"] = ""
        assert "cannot verify integrity" in _one(tree.verify(), "cannot verify")

    def test_the_digest_is_computed_over_the_whole_file(self, tmp_path: pathlib.Path) -> None:
        """`_sha256` reads in 64 KiB chunks. A loop that stopped after the
        first chunk would checksum only the first 64 KiB of every model."""
        big = tmp_path / "big.pkl"
        payload = bytes(range(256)) * 1024  # 256 KiB, four chunks
        big.write_bytes(payload)
        assert vm._sha256(big) == hashlib.sha256(payload).hexdigest()

    def test_a_change_past_the_first_chunk_changes_the_digest(self, tmp_path: pathlib.Path) -> None:
        first = tmp_path / "a.pkl"
        second = tmp_path / "b.pkl"
        payload = bytearray(b"\x00" * 200_000)
        first.write_bytes(payload)
        payload[199_999] = 1
        second.write_bytes(payload)
        assert vm._sha256(first) != vm._sha256(second)


class TestTheSharpeGateIsFailClosed:
    """Three separate conditions, each with a default that refuses.

    `entry.get("sharpe", 0.0)`, `entry.get("sharpe_gate_passed", False)` and
    `entry.get("n_trades", 0)` all default to a value that fails. That is the
    property worth pinning: a registry entry cannot get past this gate by
    leaving a field out, which is the ordinary way a hand-edited registry or a
    half-written promotion arrives.
    """

    def test_a_model_that_never_passed_the_gate_is_refused(self, tree: ModelTree) -> None:
        tree.entry["sharpe_gate_passed"] = False
        assert "sharpe_gate_passed=False" in _one(tree.verify(), "sharpe_gate_passed")

    def test_an_absent_gate_flag_is_refused(self, tree: ModelTree) -> None:
        del tree.entry["sharpe_gate_passed"]
        assert _one(tree.verify(), "sharpe_gate_passed")

    def test_an_absent_sharpe_is_refused(self, tree: ModelTree) -> None:
        del tree.entry["sharpe"]
        assert "Sharpe=0.0 < required 1.0" in _one(tree.verify(), "Sharpe=")

    def test_an_absent_trade_count_is_refused(self, tree: ModelTree) -> None:
        del tree.entry["n_trades"]
        assert "n_trades=0 < required 600" in _one(tree.verify(), "n_trades=")

    @pytest.mark.parametrize("sharpe", [0.0, 0.5, 0.99, -2.0])
    def test_a_sharpe_below_the_floor_is_refused(self, tree: ModelTree, sharpe: float) -> None:
        tree.entry["sharpe"] = sharpe
        assert _one(tree.verify(), "< required 1.0")

    def test_a_sharpe_exactly_at_the_floor_passes(self, tree: ModelTree) -> None:
        """The comparison is `<`, so 1.0 is admitted. Pinned so the boundary is
        a decision rather than something that moves by one operator's reading."""
        tree.entry["sharpe"] = 1.0
        assert tree.verify() == []

    @pytest.mark.parametrize("n_trades", [0, 1, 599])
    def test_too_few_trades_makes_the_sharpe_not_credible(self, tree: ModelTree, n_trades: int) -> None:
        """A Sharpe of 3 over 40 trades is noise. The count is what makes the
        ratio mean anything, so it is gated separately."""
        tree.entry["n_trades"] = n_trades
        assert "Sharpe not credible" in _one(tree.verify(), "n_trades=")

    def test_exactly_six_hundred_trades_passes(self, tree: ModelTree) -> None:
        tree.entry["n_trades"] = 600
        assert tree.verify() == []

    def test_a_high_sharpe_does_not_excuse_too_few_trades(self, tree: ModelTree) -> None:
        """The two conditions are independent. If they were combined, an
        implausible Sharpe from a tiny sample would sail through on the
        strength of the number that the small sample produced."""
        tree.entry["sharpe"] = 9.9
        tree.entry["n_trades"] = 12
        assert _one(tree.verify(), "n_trades=12")

    def test_the_gate_flag_alone_does_not_excuse_a_low_sharpe(self, tree: ModelTree) -> None:
        """`sharpe_gate_passed` is written by whatever promoted the model. It
        is a claim; the Sharpe and trade count are the evidence, and they are
        re-checked here rather than trusted."""
        tree.entry["sharpe_gate_passed"] = True
        tree.entry["sharpe"] = 0.1
        assert _one(tree.verify(), "< required 1.0")

    def test_the_declared_floors_are_the_ones_enforced(self) -> None:
        assert vm._REQUIRED_SHARPE == 1.0
        assert vm._REQUIRED_N == 600


class TestOnlyAnActiveModelMayServe:
    @pytest.mark.parametrize("state", ["staging", "retired", "failed", "unknown", ""])
    def test_any_other_state_is_refused(self, tree: ModelTree, state: str) -> None:
        tree.entry["state"] = state
        assert f"state='{state}'" in _one(tree.verify(), "expected 'active'")

    def test_an_absent_state_is_refused(self, tree: ModelTree) -> None:
        """A version promoted by something that did not write the field must
        not inherit "active" by default."""
        del tree.entry["state"]
        assert "state='unknown'" in _one(tree.verify(), "expected 'active'")


class TestTheMetaFileMustAgreeWithTheRegistry:
    """Two files describe the same model. When they disagree, one of them is
    describing a model that is not the one on disk, and there is no way to tell
    which from inside either file."""

    def test_a_missing_meta_file_is_refused(self, tree: ModelTree) -> None:
        tree.meta_path.unlink()
        assert "advanced_oos_meta.json not found" in _one(vm.verify(), "not found")

    def test_a_corrupt_meta_file_is_reported_and_the_rest_still_runs(self, tree: ModelTree) -> None:
        """A parse failure must not skip the checks that follow it — they are
        the ones about accuracy."""
        tree.meta_path.write_text("{{{")
        failures = vm.verify()
        assert _one(failures, "advanced_oos_meta.json is not valid JSON")
        assert _one(failures, "oos_accuracy=null")

    def test_a_horizon_that_disagrees_is_refused(self, tree: ModelTree) -> None:
        """Horizon is how many bars ahead the model predicts. A mismatch means
        the thing being scored is not the thing being served."""
        tree.meta["horizon"] = 10
        assert "horizon mismatch: meta=10, registry=5" in _one(tree.verify(), "horizon mismatch")

    def test_a_horizon_absent_from_either_side_is_not_a_mismatch(self, tree: ModelTree) -> None:
        """Deliberate: the check is for disagreement, not for completeness.
        Absent on either side means there is nothing to compare."""
        del tree.meta["horizon"]
        assert tree.verify() == []
        tree.meta["horizon"] = 5
        del tree.entry["horizon"]
        assert tree.verify() == []

    def test_a_digest_that_disagrees_is_refused(self, tree: ModelTree) -> None:
        tree.meta["sha256"] = "f" * 64
        assert "sha256 mismatch between meta" in _one(tree.verify(), "sha256 mismatch between meta")

    def test_an_absent_digest_on_either_side_is_not_a_mismatch(self, tree: ModelTree) -> None:
        del tree.meta["sha256"]
        assert tree.verify() == []

    def test_an_unreconciled_accuracy_is_refused(self, tree: ModelTree) -> None:
        """`oos_accuracy: null` is what the meta file looks like before the OOS
        run has been reconciled into it — a model whose out-of-sample
        performance nobody has measured."""
        tree.meta["oos_accuracy"] = None
        failure = _one(tree.verify(), "oos_accuracy=null")
        assert "python ml/train_advanced.py" in failure, "the failure should say how to fix it"

    def test_an_absent_accuracy_is_refused_the_same_way(self, tree: ModelTree) -> None:
        del tree.meta["oos_accuracy"]
        assert _one(tree.verify(), "oos_accuracy=null")

    @pytest.mark.parametrize("accuracy", [0.0, 0.5, 0.61, 1.0])
    def test_any_measured_accuracy_satisfies_this_check(self, tree: ModelTree, accuracy: float) -> None:
        """Pinned because it is easy to read this check as an accuracy floor.
        It is not — it only asserts the number exists. Nothing in this file
        refuses a model for being *inaccurate*; the Sharpe gate is the
        performance gate."""
        tree.meta["oos_accuracy"] = accuracy
        assert tree.verify() == []


class TestEverythingWrongIsReportedInOnePass:
    def test_independent_failures_are_collected_not_short_circuited(self, tree: ModelTree) -> None:
        """One fix, one CI round trip. A gate that reports the first problem
        only makes a six-problem tree take six runs."""
        tree.entry["sharpe"] = 0.1
        tree.entry["n_trades"] = 3
        tree.entry["state"] = "staging"
        tree.entry["sharpe_gate_passed"] = False
        tree.meta["oos_accuracy"] = None
        assert len(tree.verify()) == 5

    def test_a_missing_symlink_does_not_hide_the_sharpe_gate(self, tree: ModelTree) -> None:
        """Checks 4 to 6 read the registry, not the file, so a broken symlink
        must not take them down with it."""
        tree.symlink.unlink()
        tree.entry["sharpe"] = 0.1
        failures = tree.verify()
        assert _one(failures, "symlink missing")
        assert _one(failures, "< required 1.0")


class TestTheCommandLineSurface:
    def test_a_pass_reports_what_it_approved(self, tree: ModelTree, capsys) -> None:
        """The line an operator reads to confirm which model is live."""
        assert vm.main() == 0
        out = capsys.readouterr().out
        assert "active=xgb_horizon5_v3" in out
        assert "sharpe=1.52" in out
        assert "n_trades=2016" in out
        assert "horizon=5" in out
        assert "state=active" in out

    def test_a_failure_goes_to_stderr_not_stdout(self, tree: ModelTree, capsys) -> None:
        """`scripts/retrain.sh` and Gate D read the exit code, but a human
        reads the stream. Failures on stdout get lost in a green log."""
        tree.entry["state"] = "staging"
        tree.write()
        assert vm.main() == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.err
        assert "FAILED" not in captured.out

    def test_every_failure_is_numbered_in_the_output(self, tree: ModelTree, capsys) -> None:
        tree.entry["sharpe"] = 0.1
        tree.entry["state"] = "staging"
        tree.write()
        vm.main()
        err = capsys.readouterr().err
        assert "[1]" in err and "[2]" in err

    def test_the_module_is_runnable_as_a_command(self) -> None:
        """CI runs `python -m ml.verify_model`; the workflows depend on the
        module having a `__main__` entry point that returns an exit code."""
        assert callable(vm.main)
        source = pathlib.Path(vm.__file__).read_text()
        assert "sys.exit(main())" in source


class TestWhereThisGateActuallyRuns:
    """The docstring says "run at startup and in CI". Only half of that holds,
    and the half that does not is worth writing down.

    CI and the retrain script run this module. Process startup does not:
    `core/main_loop.py:279` calls `_verify_model_registry()`, which is a
    different and narrower check — it verifies the active model's SHA-256 via
    `ModelRegistry` and nothing else. The Sharpe floor, the trade-count
    credibility floor, the state check and the meta reconciliation in this file
    are enforced only before deployment, never by the process that serves.

    A model promoted out of band — by hand, or by a job that writes the
    registry without running this — would therefore serve. Recorded rather than
    changed: wiring a `sys.exit(1)` into startup is a decision about what takes
    the platform down, not a coverage task.
    """

    def test_the_startup_check_is_a_different_and_narrower_one(self) -> None:
        main_loop = (REPO / "core" / "main_loop.py").read_text()
        assert "_verify_model_registry()" in main_loop
        assert "ml.verify_model" not in main_loop, (
            "startup now calls this module — update this test and the docstring together"
        )

    def test_the_sharpe_floor_is_named_nowhere_in_the_startup_path(self) -> None:
        main_loop = (REPO / "core" / "main_loop.py").read_text()
        assert "sharpe_gate_passed" not in main_loop

    def test_ci_runs_it_as_a_module(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        assert "python -m ml.verify_model" in workflow

    def test_the_deploy_script_refuses_to_deploy_when_it_fails(self) -> None:
        script = (REPO / "scripts" / "retrain.sh").read_text()
        assert "python3 -m ml.verify_model || fail" in script
