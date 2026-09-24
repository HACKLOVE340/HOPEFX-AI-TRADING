"""A0 Task 1 — promotion refuses a model trained on stale data.

``trained_at`` is when the fit ran, not what the fit saw. A model retrained
today on bundled history that ends 2026-03-25 carries a fresh ``trained_at``
and would clear the runtime age gate while having learned from exactly the
same market window as the model it replaces (MODEL-AGE-IS-MTIME in a new
form). ``ModelRegistry.promote`` therefore refuses unless the entry records a
``data_end`` within ``MODEL_MAX_AGE_DAYS``.

Every fixture here passes the statistical gate and the P&L gate, so the only
check left that can refuse is the new one — and each refusal is asserted by
its message and its type, so an earlier gate refusing cannot make these pass.
All registries live under ``tmp_path``; nothing touches ``ml/saved_models``.
"""

from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

import pytest

from ml.model_registry import ModelRegistry, StaleTrainingDataError

_GOOD = {"oos_accuracy": 0.9, "oos_p_value": 0.001, "sharpe_gate_passed": True}


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_MAX_AGE_DAYS", "30")
    art = tmp_path / "m.pkl"
    art.write_bytes(b"x")
    r = ModelRegistry(tmp_path / "registry.json")
    with patch.object(ModelRegistry, "_pnl_reconciliation_check", return_value=(True, "ok")):
        yield r, art


def _days_ago(n: int) -> str:
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_register_records_data_end(reg):
    r, art = reg
    entry = r.register("cand", art, data_end="2026-03-25", **_GOOD)
    assert entry["data_end"] == "2026-03-25"
    assert r.get_version("cand")["data_end"] == "2026-03-25"


def test_promote_refuses_model_trained_on_old_data(reg):
    r, art = reg
    r.register("cand", art, data_end=_days_ago(183), **_GOOD)
    with pytest.raises(StaleTrainingDataError, match=r"training data ends .*183 days old > MODEL_MAX_AGE_DAYS"):
        r.promote("cand")
    assert r.get_version("cand")["state"] == "staging"
    assert json.loads((r._path).read_text())["active_version"] is None


def test_promote_refuses_when_data_end_unknown(reg):
    r, art = reg
    r.register("cand", art, **_GOOD)
    with pytest.raises(StaleTrainingDataError, match="training data ends unknown"):
        r.promote("cand")


def test_promote_refuses_unparseable_data_end(reg):
    r, art = reg
    r.register("cand", art, data_end="last spring", **_GOOD)
    with pytest.raises(StaleTrainingDataError, match="training data ends"):
        r.promote("cand")


def test_refusal_is_catchable_as_value_and_runtime_error(reg):
    """Existing callers catch RuntimeError (bootstrap_from_meta); the plan names ValueError."""
    r, art = reg
    r.register("cand", art, data_end=_days_ago(90), **_GOOD)
    with pytest.raises(ValueError):
        r.promote("cand")
    with pytest.raises(RuntimeError):
        r.promote("cand")


def test_promote_accepts_recent_data(reg):
    r, art = reg
    r.register("cand", art, data_end=_days_ago(5), **_GOOD)
    entry = r.promote("cand")
    assert entry["state"] == "production"


def test_limit_follows_env(reg, monkeypatch):
    r, art = reg
    r.register("cand", art, data_end=_days_ago(20), **_GOOD)
    monkeypatch.setenv("MODEL_MAX_AGE_DAYS", "10")
    with pytest.raises(StaleTrainingDataError, match="20 days old > MODEL_MAX_AGE_DAYS \\(10\\)"):
        r.promote("cand")


def test_bootstrap_without_data_end_registers_but_does_not_promote(reg, tmp_path):
    """The shipped advanced_oos_meta.json has no data_end: bootstrap must not activate it."""
    r, art = reg
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"oos_accuracy": 0.9, "oos_p_value": 0.001, "sharpe_gate": {"gate_passed": True}}))
    entry = r.bootstrap_from_meta(meta_path=meta, model_path=art, name="boot", promote=True)
    assert entry["state"] == "staging"
    assert r.active_version() is None


def test_rollback_is_deliberately_not_gated(reg):
    """An emergency restore of a previously validated model must stay possible."""
    r, art = reg
    r.register("old", art, **_GOOD)  # no data_end, like the shipped active entry
    entry = r.rollback("old")
    assert entry["state"] == "production"
    assert r.active_version()["name"] == "old"
