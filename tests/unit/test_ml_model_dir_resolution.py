# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_model_dir_resolution.py
==========================================
`ML_MODEL_DIR` had four different defaults, and the readers ignored it.

    scripts/retrain_model.py:55   os.getenv("ML_MODEL_DIR", "ml/saved_models")
    ml/run_training.py:42         os.getenv("ML_MODEL_DIR", "ml/saved_models")
    ml/hourly_trainer.py:58       os.getenv("ML_MODEL_DIR", "ml/models")      <- different
    .env.example:858              ML_MODEL_DIR=models                          <- different again
    helm/hopefx/values.yaml:77    ML_MODEL_DIR: "/app/data/models"             <- production

    ml/inference_engine.py:52     Path(__file__).parent / "saved_models"       <- ignores it
    ml/__init__.py:92             Path(__file__).parent / "saved_models"       <- ignores it

Only the three *writers* honoured the variable. Both *readers* hardcoded the
packaged directory. So in a production deployment, where Helm sets
`ML_MODEL_DIR=/app/data/models`, every retrain wrote to `/app/data/models` and
inference kept loading `<site-packages>/ml/saved_models` — the artifacts baked
into the container at build time. The retraining pipeline has never changed
what the model serves. It ran, it succeeded, it wrote files, and nothing read
them.

`ml/hourly_trainer.py` is worse still: its `ml/models` default is a directory
no reader consults under any configuration, so even locally its output went
nowhere.

The fix is one resolver, `ml.model_paths.model_dir()`, used by readers and
writers alike.

**Readers search, they do not switch.** `ML_MODEL_DIR` is preferred, and the
packaged `ml/saved_models` remains the fallback. Switching outright would mean
a deployment whose `ML_MODEL_DIR` points at an empty volume — a fresh pod
before the first retrain, a bad mount — would find no model at all, turning a
configuration mistake into an outage or, worse, a silent degradation on a
system that moves money. Searching means a configured directory with fresh
models wins, and a misconfigured one degrades to exactly today's behaviour
while logging that it did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


class TestTheResolverExists:
    def test_it_is_importable(self):
        from ml.model_paths import model_dir

        assert callable(model_dir)

    def test_the_packaged_directory_is_the_default(self):
        from ml.model_paths import model_dir, packaged_model_dir

        assert model_dir() == packaged_model_dir()
        assert packaged_model_dir().name == "saved_models"

    def test_ml_model_dir_overrides_it(self, monkeypatch, tmp_path):
        from ml.model_paths import model_dir

        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))

        assert model_dir() == tmp_path

    def test_an_empty_value_is_treated_as_unset(self, monkeypatch):
        """`ML_MODEL_DIR=` in an env file must not resolve to the process cwd."""
        from ml.model_paths import model_dir, packaged_model_dir

        monkeypatch.setenv("ML_MODEL_DIR", "   ")

        assert model_dir() == packaged_model_dir()


class TestReadersSearchRatherThanSwitch:
    def test_a_file_in_the_configured_directory_wins(self, monkeypatch, tmp_path):
        from ml.model_paths import find_model_file

        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        (tmp_path / "registry.json").write_text("{}")

        assert find_model_file("registry.json") == tmp_path / "registry.json"

    def test_it_falls_back_to_the_packaged_directory(self, monkeypatch, tmp_path):
        """An empty ML_MODEL_DIR must degrade to today's behaviour, not to nothing.

        A fresh pod before its first retrain, or a bad volume mount, would
        otherwise leave a money-moving system with no model at all.
        """
        from ml.model_paths import find_model_file, packaged_model_dir

        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        packaged = packaged_model_dir()
        existing = next((p.name for p in packaged.glob("*.json")), None)
        assert existing, "expected the repository to ship at least one packaged artifact"

        assert find_model_file(existing) == packaged / existing

    def test_a_name_in_neither_place_returns_none(self, monkeypatch, tmp_path):
        from ml.model_paths import find_model_file

        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))

        assert find_model_file("definitely-not-a-real-artifact.pkl") is None

    def test_the_fallback_is_logged_when_the_variable_was_set(self, monkeypatch, tmp_path, caplog):
        """Silent fallback is how this went unnoticed for so long."""
        import logging

        from ml.model_paths import find_model_file, packaged_model_dir

        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        existing = next((p.name for p in packaged_model_dir().glob("*.json")), None)

        with caplog.at_level(logging.WARNING, logger="ml.model_paths"):
            find_model_file(existing)

        assert any("ML_MODEL_DIR" in r.message for r in caplog.records)

    def test_no_warning_when_the_variable_was_never_set(self, monkeypatch, caplog):
        import logging

        from ml.model_paths import find_model_file, packaged_model_dir

        monkeypatch.delenv("ML_MODEL_DIR", raising=False)
        existing = next((p.name for p in packaged_model_dir().glob("*.json")), None)

        with caplog.at_level(logging.WARNING, logger="ml.model_paths"):
            find_model_file(existing)

        assert not [r for r in caplog.records if "ML_MODEL_DIR" in r.message]


class TestEveryWriterUsesTheSameDirectory:
    @pytest.mark.parametrize(
        "module_path",
        ["ml/hourly_trainer.py", "ml/run_training.py", "scripts/retrain_model.py"],
    )
    def test_no_writer_carries_its_own_default(self, module_path):
        src = Path(module_path).read_text()
        assert 'os.getenv("ML_MODEL_DIR"' not in src, (
            f"{module_path} resolves ML_MODEL_DIR itself; four such call sites gave "
            f"four different defaults, and hourly_trainer's pointed at a directory "
            f"no reader ever consults"
        )
        assert "model_paths" in src

    def test_the_hourly_trainer_no_longer_writes_somewhere_nothing_reads(self, monkeypatch):
        """ml/models was its default; no reader looks there under any config."""
        from ml.model_paths import model_dir

        monkeypatch.delenv("ML_MODEL_DIR", raising=False)

        import importlib

        import ml.hourly_trainer as ht

        importlib.reload(ht)

        assert Path(ht._MODEL_DIR).resolve() == model_dir().resolve()


class TestTheReadersHonourIt:
    @pytest.mark.parametrize("module_path", ["ml/inference_engine.py", "ml/__init__.py"])
    def test_the_reader_does_not_hardcode_the_packaged_path(self, module_path):
        src = Path(module_path).read_text()
        assert 'parent / "saved_models"' not in src, (
            f"{module_path} hardcodes the packaged directory, so a deployment that "
            f"sets ML_MODEL_DIR retrains into a directory inference never reads — "
            f"which is the state production has been in"
        )


class TestConfigurationAgrees:
    def test_env_example_matches_the_resolver_default(self):
        """.env.example said `models`, a fourth value nothing else used."""
        import re

        src = Path(".env.example").read_text()
        match = re.search(r"^ML_MODEL_DIR=(\S*)", src, re.MULTILINE)

        assert match, "ML_MODEL_DIR should still be documented"
        assert match.group(1) == "ml/saved_models", (
            f".env.example offers {match.group(1)!r}; copying it produces a deployment "
            f"whose trainers and readers disagree"
        )

    def test_the_superadmin_page_reports_the_real_default(self):
        src = Path("api/superadmin/reliability.py").read_text()
        assert '"ML_MODEL_DIR": "ml/saved_models"' in src


class TestChecksumsFollowTheDirectory:
    """A retrained artifact must not be refused as a forgery.

    `_verify_checksum` matches on `path.name` against a single checksum file.
    Once readers could load from `ML_MODEL_DIR`, a retrained `advanced_oos.pkl`
    there had the same *name* as the packaged one and a different hash, so it
    tripped

        MODEL INTEGRITY FAILURE: advanced_oos.pkl checksum mismatch ...
        The file may have been tampered with. Refusing to load.

    and `_try_load` returned None. That defeats the whole point of resolving
    `ML_MODEL_DIR` — retrained models still never reach inference — and it does
    so while crying tampering, which is the worst way to fail: an operator
    chasing a security incident that is really a path change.

    Checksums are now per directory. Each directory keeps its own baseline, so
    the tamper-detection property is unchanged within a directory while a fresh
    retrain target records its baseline on first load.
    """

    def test_a_fresh_directory_records_its_own_baseline(self, tmp_path):
        import ml as ml_pkg

        (tmp_path / "advanced_oos.pkl").write_bytes(b"retrained-artifact")

        assert ml_pkg._verify_checksum(tmp_path / "advanced_oos.pkl") is True
        assert (tmp_path / "model_checksums.json").exists(), (
            "the retrain directory must get its own baseline, not be judged against the packaged one"
        )

    def test_a_retrained_artifact_is_not_flagged_as_tampering(self, tmp_path):
        """Same filename as a packaged model, different bytes — must be allowed."""
        import ml as ml_pkg

        packaged_names = [p.name for p in ml_pkg._PACKAGED.glob("*.pkl")]
        assert packaged_names, "expected the repository to ship packaged .pkl artifacts"
        name = packaged_names[0]

        (tmp_path / name).write_bytes(b"freshly retrained, different bytes")

        assert ml_pkg._verify_checksum(tmp_path / name) is True

    def test_tampering_within_a_directory_is_still_refused(self, tmp_path):
        """The property that matters must survive the change."""
        import ml as ml_pkg

        target = tmp_path / "advanced_oos.pkl"
        target.write_bytes(b"original")
        assert ml_pkg._verify_checksum(target) is True  # records the baseline

        target.write_bytes(b"modified after the baseline was recorded")

        assert ml_pkg._verify_checksum(target) is False

    def test_the_packaged_directory_keeps_its_committed_baseline(self):
        """CI verifies these; the file must stay where it is."""
        import ml as ml_pkg

        assert ml_pkg._checksum_file_for(ml_pkg._PACKAGED) == ml_pkg._PACKAGED / "model_checksums.json"
