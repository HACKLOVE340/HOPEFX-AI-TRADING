"""A refused model artifact must not look like one that was never installed.

`ml.__init__._try_load` returned `None` for three different things:

    absent      the file is not there
    refused     `_verify_checksum` rejected it — mismatch, or unlisted in
                production, which is an integrity event
    unreadable  it loaded and then failed to unpickle

`_load_models()` is a priority chain: registry-active model, then
`advanced_oos.pkl`, then the macro and baseline pairs. `_load_from_registry`
checks `pkl_file.exists()` itself BEFORE calling `_try_load`, so a `None` there
can only mean refused or unreadable — never absent — and it returned
`(None, "")`, which is exactly what "no registry configured" returns.

So an integrity refusal on the ACTIVE model fell through and loaded a DIFFERENT
model, and the only trace at the decision point was a warning. The system went
on predicting, from a model nobody selected. `hopefx-dead-controls` second
shape: the control fired correctly and the caller carried on regardless.

What this file does NOT change is the fallback POLICY. Whether an integrity
refusal on the active model should halt inference or substitute the next model
is the owner's call (MASTER_OUTSTANDING §A8, which names making the distinction
available as the part engineering may do without one). This makes the refusal
distinguishable and loud; it does not decide what to do about it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def artifacts(tmp_path, monkeypatch):
    """A model directory with a real checksum manifest."""
    import ml

    d = tmp_path / "saved_models"
    d.mkdir()
    good = d / "good.pkl"
    good.write_bytes(b"not really a pickle, but it has a checksum")
    tampered = d / "tampered.pkl"
    tampered.write_bytes(b"original bytes")

    manifest = {
        "good.pkl": ml._sha256(good),
        "tampered.pkl": ml._sha256(tampered),
    }
    (d / "model_checksums.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Now change the tampered file so it no longer matches what is recorded.
    tampered.write_bytes(b"different bytes entirely")

    # Production: no bootstrapping, so an unlisted or mismatched file is refused.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(ml, "_bootstrap_allowed", lambda _p: False, raising=False)
    return d


class TestTheThreeOutcomesAreDistinguishable:
    def test_an_absent_artifact_reports_absent(self, artifacts):
        from ml import load_artifact

        result = load_artifact(artifacts / "nope.pkl")
        assert result.status == "absent"
        assert result.value is None
        assert not result.ok

    def test_a_refused_artifact_reports_refused(self, artifacts):
        from ml import load_artifact

        result = load_artifact(artifacts / "tampered.pkl")
        assert result.status == "refused", "a checksum mismatch is an integrity event, not a missing file"
        assert result.value is None
        assert not result.ok

    def test_an_unlisted_artifact_is_refused_not_absent(self, artifacts):
        """In production an unlisted file is refused — and it EXISTS, so
        reporting it as absent would be doubly wrong."""
        from ml import load_artifact

        stray = artifacts / "stray.pkl"
        stray.write_bytes(b"arrived without being recorded")
        result = load_artifact(stray)
        assert result.status == "refused"

    def test_an_unreadable_artifact_reports_unreadable(self, artifacts):
        """It passed integrity and then failed to unpickle — a different
        problem with a different remedy."""
        from ml import load_artifact

        result = load_artifact(artifacts / "good.pkl")
        assert result.status == "unreadable"
        assert result.value is None

    def test_every_failure_carries_a_reason(self, artifacts):
        from ml import load_artifact

        for name in ("nope.pkl", "tampered.pkl", "good.pkl"):
            result = load_artifact(artifacts / name)
            assert result.reason, f"{name} gave no reason for {result.status}"


class TestTheOldEntryPointStillBehaves:
    """`_try_load` has five call sites in this module. Changing its contract
    would be a refactor; adding a richer one beside it is not."""

    def test_try_load_still_returns_none_for_every_failure(self, artifacts):
        from ml import _try_load

        for name in ("nope.pkl", "tampered.pkl", "good.pkl"):
            assert _try_load(artifacts / name) is None


class TestARefusedActiveModelIsNotSilent:
    def test_the_registry_says_loudly_that_it_refused(self, artifacts, monkeypatch, caplog):
        """The consequence this whole file exists for.

        `_load_from_registry` returned `(None, "")` — the same value as "no
        registry configured" — and `_load_models` then loaded a different model.
        """
        import ml

        # The real key names, read from ml/__init__.py rather than guessed:
        # `active_version`, and `versions[<v>]["file"]` as an absolute path so
        # the module's relative-path resolution is not involved.
        registry = {
            "active_version": "v1",
            "versions": {"v1": {"file": str(artifacts / "tampered.pkl")}},
        }
        (artifacts / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
        monkeypatch.setattr(ml, "_saved", lambda name: artifacts / name, raising=False)

        with caplog.at_level(logging.CRITICAL, logger="ml"):
            model, version = ml._load_from_registry()

        assert model is None
        assert any(
            record.levelno >= logging.ERROR and "refus" in record.getMessage().lower() for record in caplog.records
        ), (
            "an integrity refusal on the ACTIVE model was reported at warning or below, "
            "indistinguishable from an unconfigured registry, while the chain went on to "
            "load a different model"
        )


class TestTheRemediationCommandIsNotWrong:
    def test_it_does_not_tell_the_operator_to_use_python_310(self):
        """CLAUDE.md: production is 3.12, CI tests 3.11 and 3.12, and 3.10 is
        tested by nothing. An operator following this message produces artifacts
        under an interpreter neither CI nor production ever loads — which is the
        exact failure the pin exists to prevent."""
        source = Path(__file__).resolve().parents[2] / "ml" / "__init__.py"
        text = source.read_text(encoding="utf-8")
        assert "Python 3.10" not in text, "the remediation command names an interpreter nothing runs"
