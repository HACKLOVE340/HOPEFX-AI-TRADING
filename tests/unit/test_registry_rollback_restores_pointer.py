"""A0 dry-run defects 1 and 2 — rollback must restore what verify_model checks.

The A0 rollback drill (docs/audit/plans/2026-09-24-a0-model-retrain.md, Task 5)
promoted a candidate and rolled back to ``xgb_horizon5_v3``. ``active_version``
went back and ``ModelRegistry.verify_active()`` said OK — but
``python -m ml.verify_model``, the check CI and ``scripts/retrain.sh`` run
before a deployment, failed twice over:

1. ``rollback()`` read ``entry["artifact_path"]``, a field ``register()`` has
   never written (it writes ``file``). The branch that repoints
   ``current.pkl`` could not run, so the pointer kept serving the model being
   rolled back FROM while the manifest named the one rolled back TO.
2. ``promote()`` and ``rollback()`` wrote ``state="production"``, while
   ``ml/verify_model.py`` requires ``"active"`` — the value the shipped
   registry.json holds. Neither operation could ever leave a registry that
   verify_model accepts, and every reader that looked for ``"production"``
   (the Sharpe circuit breaker's retirement, the superadmin model list) did
   not recognise the model the platform actually serves.

Every registry here lives under ``tmp_path``; ``ml/verify_model`` is pointed at
it by patching its module paths, never at ``ml/saved_models``.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ml import model_registry, verify_model
from ml.model_registry import ModelRegistry

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Passes every promotion gate: statistical, data recency and (patched) P&L.
_GOOD = {
    "oos_accuracy": 0.9,
    "oos_p_value": 0.001,
    "sharpe_gate_passed": True,
    "n_trades": 700,
}


def _today() -> str:
    return dt.date.today().isoformat()


@pytest.fixture
def two_versions(tmp_path, monkeypatch):
    """A temp registry with A and B registered, P&L gate stubbed open."""
    monkeypatch.setenv("MODEL_MAX_AGE_DAYS", "30")
    a = tmp_path / "a.pkl"
    a.write_bytes(b"model-A")
    b = tmp_path / "b.pkl"
    b.write_bytes(b"model-B")
    reg = ModelRegistry(tmp_path / "registry.json")
    with patch.object(ModelRegistry, "_pnl_reconciliation_check", return_value=(True, "ok")):
        reg.register("A", a, data_end=_today(), **_GOOD)
        reg.register("B", b, data_end=_today(), **_GOOD)
        yield reg, a, b, tmp_path


def _pointer(tmp_path: Path) -> Path:
    link = tmp_path / "current.pkl"
    assert link.is_symlink(), "current.pkl was never created — the harness observed nothing"
    return link.resolve()


# ── Defect 1: the pointer ──────────────────────────────────────────────────────


def test_rollback_repoints_current_pkl_at_the_restored_artifact(two_versions):
    reg, a, b, tmp_path = two_versions
    reg.promote("A")
    reg.promote("B")
    assert _pointer(tmp_path) == b.resolve()  # the harness is live: promote moved it

    reg.rollback("A")

    assert reg._load()["active_version"] == "A"
    assert _pointer(tmp_path) == a.resolve(), "rollback left current.pkl serving the model it rolled back from"


def test_rollback_resolves_a_repo_relative_file_like_the_shipped_registry(two_versions, monkeypatch):
    """The shipped entries record ``file`` relative to the repository root
    (``ml/saved_models/advanced_oos.pkl``) and no ``artifact_path`` at all.
    Rollback must resolve that from any working directory."""
    reg, a, b, tmp_path = two_versions
    reg.promote("B")
    manifest = reg._load()
    manifest["versions"]["A"]["file"] = os.path.relpath(a, _REPO_ROOT)
    assert "artifact_path" not in manifest["versions"]["A"]
    reg._save(manifest)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    reg.rollback("A")

    assert _pointer(tmp_path) == a.resolve()


def test_rollback_to_a_missing_artifact_refuses_and_changes_nothing(two_versions):
    """Reporting a rollback that did not repoint the pointer is the defect in a
    new form: refuse before touching the manifest instead."""
    reg, a, b, tmp_path = two_versions
    reg.promote("A")
    reg.promote("B")
    a.unlink()
    before = reg._load()

    with pytest.raises(FileNotFoundError):
        reg.rollback("A")

    assert reg._load() == before
    assert _pointer(tmp_path) == b.resolve()


def test_the_pointer_is_relative_so_a_committed_link_survives_a_clone(two_versions):
    """The shipped current.pkl is ``-> advanced_oos.pkl``. An absolute link
    written in one checkout names a path that does not exist in the next, and
    verify_model then reports the symlink missing."""
    reg, a, b, tmp_path = two_versions
    reg.promote("A")
    target = os.readlink(tmp_path / "current.pkl")
    assert not os.path.isabs(target), f"current.pkl -> {target!r} is absolute"
    assert (tmp_path / target).resolve() == a.resolve()


# ── Defect 2: one state vocabulary ─────────────────────────────────────────────


def test_promote_writes_the_state_verify_model_requires(two_versions):
    reg, *_ = two_versions
    reg.promote("A")
    assert reg.get_version("A")["state"] == "active"


def test_rollback_writes_the_state_verify_model_requires(two_versions):
    reg, *_ = two_versions
    reg.promote("A")
    reg.promote("B")
    reg.rollback("A")
    assert reg.get_version("A")["state"] == "active"
    assert reg.get_version("B")["state"] == "retired"


@pytest.mark.parametrize("prior_state", ["active", "production"])
def test_promote_retires_the_previous_active_version(two_versions, prior_state):
    """The shipped registry's serving entry says ``active``; a registry written
    by the old promote() says ``production``. Both must be retired, or two
    entries claim to be serving."""
    reg, *_ = two_versions
    reg.promote("A")
    manifest = reg._load()
    manifest["versions"]["A"]["state"] = prior_state
    reg._save(manifest)

    reg.promote("B")

    states = {n: e["state"] for n, e in reg.list_versions().items()}
    assert states == {"A": "retired", "B": "active"}


def _as_shipped(reg: ModelRegistry, name: str) -> None:
    """Give *name* the serving state the shipped registry.json records, so the
    reader under test is exercised on the real vocabulary rather than on
    whatever promote() happens to write."""
    manifest = reg._load()
    manifest["versions"][name]["state"] = "active"
    reg._save(manifest)


def test_sharpe_circuit_breaker_retires_the_model_that_is_actually_serving(two_versions, monkeypatch):
    """``_retire_model`` only retired ``state == "production"``. The serving
    entry in the shipped registry says ``active``, so a tripped breaker left it
    promotable without review."""
    from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

    reg, *_ = two_versions
    reg.promote("A")
    _as_shipped(reg, "A")
    monkeypatch.setattr(model_registry, "_registry", reg)

    asyncio.run(SharpeCircuitBreaker()._retire_model("A", "test trip"))

    entry = reg.get_version("A")
    assert entry["state"] == "retired"
    assert entry["retired_reason"] == "test trip"


def test_superadmin_model_list_shows_the_serving_model_as_active(two_versions, monkeypatch):
    from api.superadmin.ml_ai import list_ml_models

    reg, *_ = two_versions
    reg.promote("A")
    _as_shipped(reg, "A")
    monkeypatch.setattr(model_registry, "_registry", reg)

    out = asyncio.run(list_ml_models(user=None))

    status = {m["name"]: m["status"] for m in out["models"]}
    assert status["A"] == "active", status


def test_register_records_sharpe_so_verify_model_can_read_it(two_versions):
    """verify_model's Sharpe floor reads ``entry["sharpe"]``; register() had no
    way to write it, so no registered model could pass verify_model without a
    hand edit of registry.json."""
    reg, a, *_ = two_versions
    reg.register("A", a, data_end=_today(), sharpe=1.5, **_GOOD)
    assert reg.get_version("A")["sharpe"] == 1.5


# ── End to end: register → promote → rollback → verify_model ───────────────────


def _point_verify_model_at(monkeypatch, directory: Path) -> None:
    monkeypatch.setattr(verify_model, "_SAVED", directory)
    monkeypatch.setattr(verify_model, "_REGISTRY", directory / "registry.json")
    monkeypatch.setattr(verify_model, "_SYMLINK", directory / "current.pkl")
    monkeypatch.setattr(verify_model, "_META", directory / "advanced_oos_meta.json")


def _register_with_sharpe(reg, a, b) -> None:
    reg.register("A", a, data_end=_today(), sharpe=1.5, **_GOOD)
    reg.register("B", b, data_end=_today(), sharpe=1.5, **_GOOD)


def test_register_promote_rollback_then_verify_model_passes(two_versions, monkeypatch):
    reg, a, b, tmp_path = two_versions
    _register_with_sharpe(reg, a, b)
    # The trainer writes this sidecar beside the artifact; verify_model reads it.
    (tmp_path / "advanced_oos_meta.json").write_text(json.dumps({"oos_accuracy": 0.9}))
    _point_verify_model_at(monkeypatch, tmp_path)

    reg.promote("A")
    assert verify_model.verify() == []
    reg.promote("B")
    assert verify_model.verify() == []

    reg.rollback("A")

    assert verify_model.verify() == [], "verify_model refuses the registry rollback() leaves behind"
    assert _pointer(tmp_path) == a.resolve()
    assert reg._load()["active_version"] == "A"


def test_verify_model_still_refuses_a_non_active_state(two_versions, monkeypatch):
    """The fix is in the writers. verify_model's check stays exactly as strict:
    a legacy ``production`` entry is still refused."""
    reg, a, b, tmp_path = two_versions
    _register_with_sharpe(reg, a, b)
    (tmp_path / "advanced_oos_meta.json").write_text(json.dumps({"oos_accuracy": 0.9}))
    _point_verify_model_at(monkeypatch, tmp_path)
    reg.promote("A")
    manifest = reg._load()
    manifest["versions"]["A"]["state"] = "production"
    reg._save(manifest)

    failures = verify_model.verify()

    assert any("expected 'active'" in f for f in failures), failures


def test_verify_model_passes_on_the_shipped_registry_unchanged():
    """The real registry holds ``active`` and must keep passing without edits."""
    assert verify_model.verify() == []
