# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_model_registry_and_pipeline_identity.py
========================================================
The last two from the UI sweep. Both are one object being mistaken for another.

**The ML-Ops page watched a pipeline nobody was running.**
``core/startup_factories.py::init_continuous_learning`` constructed its own
``ContinuousLearningPipeline()``, started it, and stored it on ``app_state``.
Every endpoint in ``api/ml_ops.py`` calls ``get_continuous_learning_pipeline()``
— the module-level singleton, a *different* object, lazily constructed on first
request and never started. So the page reported that object's state: PIPELINE
Stopped, RETRAIN STATE idle, DRIFT CHECKS 0, "No shadow deployments", "No
retrain history yet", while the real pipeline ran unobserved and the page's
retrain button pushed work into the idle copy. Sharing one instance also stops
two pipelines independently running drift checks and promotions over the same
models, which the split was one step away from.

**Four registry entries, one file, two accuracies.** The shipped manifest::

    advanced_oos_v1   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.565
    advanced_oos_v2   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.565
    xgb_horizon5_v1   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.565
    xgb_horizon5_v3   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.5734  ← active

Identical bytes cannot have scored two different numbers on a held-out set, so
at least one figure was measured against a model that is not this file. The one
that disagrees is the version serving inference, and it is what the dashboard
prints as "ML MODEL ACCURACY 57.3%".

Every per-entry check passes here: each digest matches its file, because it is
the same file. ``verify()`` asks "do these bytes still hash to what we
recorded?", which cannot see a contradiction *between* entries — so nothing was
positioned to notice. The audit added here compares across entries.

It reports rather than repairs. Which accuracy is correct is a measurement, not
something a migration can infer, and averaging two numbers when one is known to
be wrong would only bury it.

The same audit found a second problem nobody had reported: ``mtf_ensemble_v1``
claims ``oos_accuracy`` 0.6135 — the highest figure in the ML Models table, and
displayed there as 61.4% — while ``ml/saved_models/mtf_ensemble.pkl`` does not
exist. It is retired, so it is not serving; it is still the best-looking number
on the page with no model behind it.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

pytestmark = pytest.mark.unit


# ── The pipeline the page watches must be the pipeline that runs ─────────────


def test_startup_uses_the_module_singleton():
    """A second instance is invisible to every ml_ops endpoint."""
    import ast
    import inspect

    from core.startup_factories import init_continuous_learning

    src = inspect.getsource(init_continuous_learning)
    tree = ast.parse(src.strip())
    constructed = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "ContinuousLearningPipeline"
    ]
    assert constructed == [], "startup builds its own pipeline again; ml_ops reads a different one"
    assert "get_continuous_learning_pipeline()" in src


def test_the_started_instance_is_the_one_the_api_reads():
    """End to end: start via the factory, observe via the accessor."""
    import ml.continuous_learning as cl

    cl._pipeline = None  # fresh module state for this test
    try:
        from core.startup_factories import init_continuous_learning

        class _State:
            inference_engine = None
            model_registry = None

        state = _State()
        started = asyncio.run(init_continuous_learning(state))
        assert started is not None, "the factory failed to start a pipeline"

        observed = cl.get_continuous_learning_pipeline()
        assert observed is started, "the API reads a different object than startup started"
        assert observed.health()["running"] is True, (
            "the page would show PIPELINE Stopped for a pipeline that is running"
        )
    finally:
        cl._pipeline = None


def test_health_reports_the_fields_the_page_renders():
    import ml.continuous_learning as cl

    cl._pipeline = None
    try:
        health = cl.get_continuous_learning_pipeline().health()
        for field in ("running", "retraining_state", "drift_history_count", "shadow_models", "promotion_history"):
            assert field in health, f"{field} missing — the ML-Ops card renders it"
    finally:
        cl._pipeline = None


# ── Registry consistency ─────────────────────────────────────────────────────


def _registry_with(tmp_path, versions: dict, active: str | None = None):
    """A ModelRegistry over a hand-built manifest."""
    from ml.model_registry import ModelRegistry

    manifest = tmp_path / "registry.json"
    manifest.write_text(json.dumps({"versions": versions, "active_version": active}))
    reg = ModelRegistry.__new__(ModelRegistry)
    reg._load = lambda: json.loads(manifest.read_text())  # type: ignore[method-assign]
    return reg


def _entry(sha: str, file: str, acc: float) -> dict:
    return {"sha256": sha, "file": file, "oos_accuracy": acc, "state": "staging"}


def test_a_clean_manifest_is_ok(tmp_path):
    art = tmp_path / "a.pkl"
    art.write_bytes(b"x")
    reg = _registry_with(tmp_path, {"m_v1": _entry("aaaa" * 16, str(art), 0.61)}, active="m_v1")
    audit = reg.audit_manifest()
    assert audit["ok"] is True
    assert audit["metric_conflicts"] == []
    assert audit["missing_artifacts"] == []


def test_duplicate_artifacts_are_reported_even_when_they_agree(tmp_path):
    """Not a fault on its own — but the VERSION column is sha256[:8], so four
    rows share one value and the operator needs to see why."""
    art = tmp_path / "a.pkl"
    art.write_bytes(b"x")
    sha = "bbbb" * 16
    reg = _registry_with(
        tmp_path, {"m_v1": _entry(sha, str(art), 0.6), "m_v2": _entry(sha, str(art), 0.6)}, active="m_v1"
    )
    audit = reg.audit_manifest()
    assert audit["duplicate_artifacts"] == {sha: ["m_v1", "m_v2"]}
    assert audit["metric_conflicts"] == [], "identical metrics are not a conflict"
    assert audit["ok"] is True


def test_one_artifact_with_two_accuracies_is_a_conflict(tmp_path):
    """The shipped defect, in miniature."""
    art = tmp_path / "a.pkl"
    art.write_bytes(b"x")
    sha = "cccc" * 16
    reg = _registry_with(
        tmp_path,
        {"m_v1": _entry(sha, str(art), 0.565), "m_v3": _entry(sha, str(art), 0.5734)},
        active="m_v3",
    )
    audit = reg.audit_manifest()
    assert audit["ok"] is False
    assert len(audit["metric_conflicts"]) == 1
    conflict = audit["metric_conflicts"][0]
    assert conflict["versions"] == ["m_v1", "m_v3"]
    assert conflict["conflicting"]["oos_accuracy"] == [0.565, 0.5734]
    assert conflict["active_among_them"] is True, "the serving model's own metrics are in dispute"


def test_a_conflict_that_excludes_the_active_model_is_flagged_differently(tmp_path):
    art = tmp_path / "a.pkl"
    art.write_bytes(b"x")
    other = tmp_path / "b.pkl"
    other.write_bytes(b"y")
    sha = "dddd" * 16
    reg = _registry_with(
        tmp_path,
        {
            "old_v1": _entry(sha, str(art), 0.50),
            "old_v2": _entry(sha, str(art), 0.60),
            "live_v1": _entry("eeee" * 16, str(other), 0.57),
        },
        active="live_v1",
    )
    conflict = reg.audit_manifest()["metric_conflicts"][0]
    assert conflict["active_among_them"] is False


def test_a_registry_entry_whose_file_is_gone_is_reported(tmp_path):
    """mtf_ensemble_v1 claims 61.4% — the best number in the table — and its
    .pkl does not exist."""
    reg = _registry_with(tmp_path, {"ghost_v1": _entry("ffff" * 16, str(tmp_path / "nope.pkl"), 0.6135)})
    audit = reg.audit_manifest()
    assert audit["missing_artifacts"] == ["ghost_v1"]
    assert audit["ok"] is False


def test_an_entry_that_disagrees_with_its_artifact_metadata_is_named(tmp_path):
    """Retraining in place leaves older entries describing a model that is gone.

    The trainer writes ``<stem>_meta.json`` in the same run as the ``.pkl``, so
    it is the measurement and a registry entry is a copy. When the two differ,
    the entry is stale — and this names which one, rather than only saying two
    entries disagree.
    """
    art = tmp_path / "advanced_oos.pkl"
    art.write_bytes(b"x")
    (tmp_path / "advanced_oos_meta.json").write_text(
        json.dumps({"oos_accuracy": 0.5734, "trained_at": "2026-06-26T22:30:43Z"})
    )
    reg = _registry_with(
        tmp_path,
        {"old_v1": _entry("1111" * 16, str(art), 0.565), "new_v3": _entry("1111" * 16, str(art), 0.5734)},
        active="new_v3",
    )
    audit = reg.audit_manifest()
    stale = audit["stale_metrics"]
    assert [s["version"] for s in stale] == ["old_v1"], "the up-to-date entry must not be flagged"
    assert stale[0]["recorded_oos_accuracy"] == 0.565
    assert stale[0]["artifact_oos_accuracy"] == 0.5734
    assert audit["ok"] is False


def test_an_entry_matching_its_artifact_is_not_flagged(tmp_path):
    art = tmp_path / "m.pkl"
    art.write_bytes(b"x")
    (tmp_path / "m_meta.json").write_text(json.dumps({"oos_accuracy": 0.61}))
    reg = _registry_with(tmp_path, {"m_v1": _entry("2222" * 16, str(art), 0.61)}, active="m_v1")
    assert reg.audit_manifest()["stale_metrics"] == []


def test_an_artifact_without_a_sidecar_is_not_guessed_at(tmp_path):
    """No metadata is not evidence of a mismatch."""
    art = tmp_path / "m.pkl"
    art.write_bytes(b"x")
    reg = _registry_with(tmp_path, {"m_v1": _entry("3333" * 16, str(art), 0.61)}, active="m_v1")
    assert reg.audit_manifest()["stale_metrics"] == []


def test_the_shipped_artifact_metadata_resolves_the_conflict():
    """Which accuracy is right is answerable, and the answer is on disk."""
    from ml.model_registry import get_registry

    audit = get_registry().audit_manifest()
    stale = {s["version"] for s in audit["stale_metrics"]}
    assert stale == {"advanced_oos_v1", "advanced_oos_v2", "xgb_horizon5_v1"}, stale
    assert audit["active_version"] not in stale, (
        "the serving entry should be the one that matches the artifact's own metadata"
    )
    for finding in audit["stale_metrics"]:
        assert finding["artifact_oos_accuracy"] == pytest.approx(0.5734)


def test_model_identity_doc_names_the_actual_active_version():
    """The doc said the active model was xgb_horizon5_v1 at 59.9% — a model that
    was overwritten in place and no longer exists."""
    import pathlib

    doc = (pathlib.Path(__file__).resolve().parents[2] / "ml/saved_models/MODEL_IDENTITY.md").read_text()
    from ml.model_registry import get_registry

    active = get_registry().audit_manifest()["active_version"]
    assert f"`{active}`" in doc, f"MODEL_IDENTITY.md does not mention the active version {active}"
    # The doc may still cite 59.9% while explaining that it is stale; what it
    # must not do is present it as the model's accuracy. Check the metrics row.
    accuracy_rows = [ln for ln in doc.splitlines() if ln.startswith("| OOS accuracy ")]
    assert accuracy_rows, "the metrics table has no OOS accuracy row"
    assert any("57.34" in ln for ln in accuracy_rows), accuracy_rows
    assert not any("59.9" in ln for ln in accuracy_rows), (
        f"the stale accuracy is still stated as the model's: {accuracy_rows}"
    )


def test_the_shipped_manifest_is_audited_and_the_known_faults_are_found():
    """Against the real committed registry.json, not a fixture."""
    from ml.model_registry import get_registry

    audit = get_registry().audit_manifest()
    assert audit["ok"] is False, "the shipped manifest is self-consistent now — update this test"
    conflicts = audit["metric_conflicts"]
    assert conflicts, "the four-entries-one-file conflict is no longer detected"
    assert any(c["active_among_them"] for c in conflicts), (
        "the serving version is no longer among the conflicting entries"
    )


# ── The findings must reach a screen ─────────────────────────────────────────


def test_the_models_endpoint_marks_shared_artifacts_and_conflicts():
    import os

    os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
    os.environ.setdefault("CSRF_PROTECTION", "false")
    os.environ["STARTUP_GATE"] = "false"
    import jwt
    from fastapi.testclient import TestClient

    from app import app

    headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": "superadmin", "role": "superadmin", "type": "access", "exp": int(time.time()) + 3600},
            os.environ["SECURITY_JWT_SECRET"],
            algorithm="HS256",
        )
    }
    r = TestClient(app, raise_server_exceptions=False).get("/api/superadmin/ml/models", headers=headers)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert "integrity" in body, "the page cannot show what it is not told"
    shared = [m for m in body["models"] if m.get("shares_artifact_with")]
    assert shared, "four entries share one artifact and no row says so"
    assert any(m.get("metrics_conflict") for m in body["models"]), "the conflicting rows are unmarked"


def test_the_diagnostics_check_grades_a_serving_conflict_as_critical():
    from security.diagnostics import DiagnosticsEngine

    results = asyncio.run(DiagnosticsEngine()._check_model_registry())
    assert results[0].check_name == "model_registry"
    assert results[0].status == "critical", (
        f"the serving model's metrics are in dispute; got {results[0].status}: {results[0].message}"
    )
    assert results[0].remediation


def test_the_check_runs_in_the_full_suite():
    import inspect

    from security.diagnostics import DiagnosticsEngine

    assert "_check_model_registry()" in inspect.getsource(DiagnosticsEngine.run_full_diagnostic)


def test_the_superadmin_page_can_describe_the_check():
    from api.superadmin.diagnostics import _CHECK_DESCRIPTIONS

    assert "model_registry" in _CHECK_DESCRIPTIONS


def test_the_models_table_renders_the_collision():
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/pages/superadmin/MLAISection.tsx").read_text()
    assert "shares_artifact_with" in src, "four identical version cells with nothing to explain them"
    assert "metrics_conflict" in src


def test_the_audit_never_repairs_the_numbers():
    """Guard the judgement call: which accuracy is right is a measurement.
    Averaging or silently preferring one would bury a known-wrong figure."""
    import inspect

    from ml.model_registry import ModelRegistry

    src = inspect.getsource(ModelRegistry.audit_manifest)
    for forbidden in ("_save", "self.register", "entry[", "mean(", "sum("):
        assert forbidden not in src, f"audit_manifest mutates or derives metrics ({forbidden})"
