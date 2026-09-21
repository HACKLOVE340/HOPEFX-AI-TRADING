# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§25: one place that decides whether the AI may watch, listen, or remember.

## Why this comes before §18

§18 is ambient awareness — gesture recognition, pointing, attention tracking,
camera and screen source selection. All five rows are continuous observation of
the person using the platform. Building that first and adding privacy controls
afterwards is the wrong order in exactly the way Track S's vault was: the
containment has to bind before the thing it contains exists.

The registry's own note said `Camera is gated; memory and microphone controls
are not centralised.` What "gated" meant was `Depends(_admin)` plus a rate
limit — an authorisation check, which answers "may this ROLE call this
endpoint", and never asks whether the person in front of the camera agreed to
be looked at. Those are different questions and only one of them is consent.

## Default denied, and the default is the whole design

A sensor with no consent record is REFUSED, with a reason. The alternative —
allowed until somebody objects — means the first frame is taken before anyone
was asked, and there is no way to un-take it.

## Unreadable means refuse

The same inversion `ai/improve/cycle.py`'s kill switch makes, for the same
reason. Everywhere else in this codebase an unmeasured thing is reported as
absent rather than guessed at. Here the question is not "what is true" but
"was I permitted", and a system that cannot read its permissions and proceeds
anyway has no permissions.

## A session grant that outlives the session is not a session grant

It is a permanent grant with a reassuring label, which is worse than an honest
permanent one because the operator believes something false about it.

These fail on the pre-fix tree: `ai.privacy.consent` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

NOW = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _clean():
    from ai.privacy import consent

    consent.reset_for_testing()
    yield
    consent.reset_for_testing()


# ── default denied ────────────────────────────────────────────────────────────


def test_a_sensor_nobody_consented_to_is_refused():
    from ai.privacy import consent

    decision = consent.check("owner", "camera", now=NOW)
    assert decision.allowed is False
    assert "no consent" in decision.reason


def test_the_refusal_names_the_sensor_and_the_operator():
    """A refusal an operator cannot act on is a refusal they will route around."""
    from ai.privacy import consent

    decision = consent.check("owner", "microphone", now=NOW)
    assert "microphone" in decision.reason


@pytest.mark.parametrize("sensor", ["camera", "microphone", "memory"])
def test_every_sensor_starts_denied(sensor):
    from ai.privacy import consent

    assert consent.check("owner", sensor, now=NOW).allowed is False


def test_an_unknown_sensor_is_refused_rather_than_defaulted():
    from ai.privacy import consent

    with pytest.raises(ValueError):
        consent.grant("owner", "keylogger", scope="until_revoked", now=NOW)
    assert consent.check("owner", "keylogger", now=NOW).allowed is False


# ── granting ──────────────────────────────────────────────────────────────────


def test_a_granted_sensor_is_allowed():
    from ai.privacy import consent

    consent.grant("owner", "camera", scope="until_revoked", now=NOW)
    assert consent.check("owner", "camera", now=NOW).allowed is True


def test_a_grant_records_when_and_what_so_it_can_be_audited():
    from ai.privacy import consent

    consent.grant("owner", "camera", scope="until_revoked", now=NOW)
    snapshot = consent.snapshot("owner")
    assert snapshot["camera"]["granted"] is True
    assert snapshot["camera"]["at"] == NOW
    assert snapshot["camera"]["scope"] == "until_revoked"


def test_granting_one_sensor_grants_no_other():
    from ai.privacy import consent

    consent.grant("owner", "camera", scope="until_revoked", now=NOW)
    assert consent.check("owner", "microphone", now=NOW).allowed is False
    assert consent.check("owner", "memory", now=NOW).allowed is False


def test_a_grant_needs_an_operator():
    from ai.privacy import consent

    with pytest.raises(ValueError):
        consent.grant("  ", "camera", scope="until_revoked", now=NOW)


def test_an_unknown_scope_is_refused():
    from ai.privacy import consent

    with pytest.raises(ValueError):
        consent.grant("owner", "camera", scope="forever_and_ever", now=NOW)


# ── one operator never consents for another ───────────────────────────────────


def test_one_operators_consent_never_covers_another():
    """The precedent is a P0 in `ai/jobs/runner.py`. Here it would mean one
    admin turning on another admin's camera."""
    from ai.privacy import consent

    consent.grant("ann", "camera", scope="until_revoked", now=NOW)
    assert consent.check("bo", "camera", now=NOW).allowed is False


def test_a_snapshot_shows_only_the_operators_own_consents():
    from ai.privacy import consent

    consent.grant("ann", "camera", scope="until_revoked", now=NOW)
    assert consent.snapshot("bo")["camera"]["granted"] is False


# ── session scope actually expires ────────────────────────────────────────────


def test_a_session_grant_expires():
    """A session grant that outlives the session is a permanent grant with a
    reassuring label, which is worse than an honest permanent one."""
    from ai.privacy import consent

    consent.grant("owner", "camera", scope="session", now=NOW)
    assert consent.check("owner", "camera", now=NOW + 60).allowed is True

    later = NOW + consent.SESSION_SECONDS + 1
    decision = consent.check("owner", "camera", now=later)
    assert decision.allowed is False
    assert "expired" in decision.reason


def test_an_until_revoked_grant_does_not_expire():
    from ai.privacy import consent

    consent.grant("owner", "camera", scope="until_revoked", now=NOW)
    assert consent.check("owner", "camera", now=NOW + 10_000_000).allowed is True


# ── revocation ────────────────────────────────────────────────────────────────


def test_revocation_takes_effect_immediately():
    from ai.privacy import consent

    consent.grant("owner", "camera", scope="until_revoked", now=NOW)
    assert consent.revoke("owner", "camera") is True
    assert consent.check("owner", "camera", now=NOW).allowed is False


def test_revoking_something_never_granted_is_reported_honestly():
    from ai.privacy import consent

    assert consent.revoke("owner", "camera") is False


def test_revocation_is_recorded_rather_than_erasing_the_history():
    """ "They never consented" and "they consented and withdrew it" are
    different facts, and an audit that cannot tell them apart is not one."""
    from ai.privacy import consent

    consent.grant("owner", "camera", scope="until_revoked", now=NOW)
    consent.revoke("owner", "camera", now=NOW + 5)
    snapshot = consent.snapshot("owner")
    assert snapshot["camera"]["granted"] is False
    assert snapshot["camera"]["revoked_at"] == NOW + 5


def test_revoke_all_stops_every_sensor_at_once():
    """The control an operator reaches for when they want it to stop NOW."""
    from ai.privacy import consent

    for sensor in ("camera", "microphone", "memory"):
        consent.grant("owner", sensor, scope="until_revoked", now=NOW)
    revoked = consent.revoke_all("owner", now=NOW + 1)

    assert sorted(revoked) == ["camera", "memory", "microphone"]
    for sensor in ("camera", "microphone", "memory"):
        assert consent.check("owner", sensor, now=NOW + 2).allowed is False


# ── unreadable means refuse ───────────────────────────────────────────────────


def test_a_store_that_cannot_be_read_refuses_rather_than_allowing():
    """The inversion `ai/improve/cycle.py`'s kill switch makes, for the same
    reason: a system that cannot read its permissions and proceeds anyway has
    no permissions."""
    from ai.privacy import consent

    class _Broken:
        def read(self, *_a, **_k):
            raise ConnectionError("store is gone")

        def write(self, *_a, **_k):
            raise ConnectionError("store is gone")

    consent.set_store(_Broken())
    decision = consent.check("owner", "camera", now=NOW)
    assert decision.allowed is False
    assert "could not" in decision.reason.lower()


# ── the camera endpoint actually consults it ──────────────────────────────────


@pytest.mark.asyncio
async def test_the_vision_endpoint_refuses_without_consent(monkeypatch):
    """A control nothing calls is the defect this codebase keeps finding.

    `Depends(_admin)` answers "may this ROLE call this endpoint". It never asks
    whether the person in front of the camera agreed to be looked at.
    """
    import api.safe_agent_platform as sp
    from api.auth import TokenPayload
    from fastapi import HTTPException

    monkeypatch.setattr(sp, "_enforce_rate_limit", _noop)

    body = sp.VisionInterpretRequest(image_b64="aGVsbG8=", media_type="image/png")
    with pytest.raises(HTTPException) as exc:
        await sp.vision_interpret(body, user=TokenPayload(sub="owner", role="admin"))

    assert exc.value.status_code == 403
    assert "consent" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_the_vision_endpoint_proceeds_once_consent_is_given(monkeypatch):
    import api.safe_agent_platform as sp
    from ai.privacy import consent
    from api.auth import TokenPayload

    monkeypatch.setattr(sp, "_enforce_rate_limit", _noop)
    consent.grant("owner", "camera", scope="until_revoked")

    reached = []

    def _interpret(_images, *, operator, hint=None):
        reached.append(operator)
        return {"surface_type": "chart", "confidence": 0.8}

    monkeypatch.setattr("ai.vision.detect.interpret", _interpret)
    body = sp.VisionInterpretRequest(image_b64="aGVsbG8=", media_type="image/png")
    result = await sp.vision_interpret(body, user=TokenPayload(sub="owner", role="admin"))

    assert reached == ["owner"]
    assert result["reason"] == "ok"


@pytest.mark.asyncio
async def test_the_consent_check_happens_before_the_frame_is_decoded(monkeypatch):
    """Refusing after decoding means the frame was already in memory."""
    import api.safe_agent_platform as sp
    from api.auth import TokenPayload
    from fastapi import HTTPException

    monkeypatch.setattr(sp, "_enforce_rate_limit", _noop)
    decoded = []
    monkeypatch.setattr("ai.gateway.client.ImageRef", lambda **kw: decoded.append(kw))

    body = sp.VisionInterpretRequest(image_b64="aGVsbG8=", media_type="image/png")
    with pytest.raises(HTTPException):
        await sp.vision_interpret(body, user=TokenPayload(sub="owner", role="admin"))

    assert decoded == [], "the frame was decoded before consent was checked"


async def _noop(*_a, **_k):
    return None


# ── the registry ──────────────────────────────────────────────────────────────


def test_the_privacy_row_is_live_and_its_evidence_resolves():
    from ai.hub import capabilities

    assert capabilities.verify().discrepancies == ()
    rows = {c.id: c for c in capabilities.REGISTRY}
    assert rows["sec.privacy_controls"].state == "live"


def test_removing_the_grant_turns_the_vision_contract_tests_red():
    """The four vision tests now carry an autouse fixture that grants camera
    consent. That fixture IS the proof the gate binds: without it they fail.

    Asserted structurally rather than by running them twice, because a test
    that reruns another test file is a test that breaks when that file moves.
    """
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "unit" / "test_vision_detection_contract.py").read_text(
        encoding="utf-8"
    )
    assert "from ai.privacy import consent" in source
    assert 'consent.grant("owner", "camera"' in source
