# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A failed login must not reveal whether the email is registered.

F144, STRIDE-I across the operator-surface trust boundary. `AuthService.login`
looked the user up and, finding none, returned before `verify_password` was ever
reached:

    user = session.query(User).filter_by(email=email).first()
    ...
    if not user:
        _record(False, "user_not_found")
        return False, "Invalid credentials", None

Both branches return the same message, so the *response* gives nothing away. The
*clock* gives away everything: a registered address pays bcrypt at cost factor
12, an unregistered one pays a SELECT that misses.

Measured on this machine before the fix, twelve attempts each with a fresh user
so the lockout never short-circuits bcrypt:

    registered email   median:   309.04 ms
    unregistered email median:     1.20 ms
    gap                       :   307.84 ms   (257x)

That is not a subtle side channel to be teased out with statistics — it is two
orders of magnitude, visible over a network, and it needs no credentials and
trips no lockout, because an address that does not exist has no counter to
increment. An attacker walks a list of addresses and learns which are customers.

(An earlier measurement of the same thing showed a 1.16 ms gap and was wrong:
it reused one account, so after five attempts the lockout returned early and
bcrypt never ran. The control being measured had switched itself off.)

The fix is to spend the same work either way: verify the supplied password
against a fixed dummy hash when no user was found. The first test below asserts
the mechanism and is deterministic; the second measures the outcome with a
deliberately loose bound, because a timing assertion tight enough to be precise
is tight enough to be flaky on a shared runner.
"""

from __future__ import annotations

import statistics
import time
import uuid

import pytest

from auth.jwt import hash_password

pytestmark = pytest.mark.unit

# A test fixture, not a credential.
_PASSWORD = "correct horse battery staple"  # pragma: allowlist secret


@pytest.fixture(scope="module")
def _hashed_password() -> str:
    """Hash once. bcrypt at cost 12 is ~300 ms and this is a fixture, not the subject."""
    return hash_password(_PASSWORD)


@pytest.fixture
def session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.user_models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    class _Ctx:
        def __enter__(self):
            self.s = Session()
            return self.s

        def __exit__(self, *_a):
            self.s.close()
            return False

    return _Ctx


@pytest.fixture
def svc(session_factory):
    from auth.service import AuthService

    return AuthService(session_factory)


def _register(session_factory, hashed: str) -> str:
    """A fresh active user, so no lockout counter is carried between attempts."""
    from database.user_models import User, UserStatus

    email = f"{uuid.uuid4().hex}@example.test"
    with session_factory() as s:
        s.add(
            User(
                email=email,
                username=uuid.uuid4().hex[:12],
                hashed_password=hashed,
                status=UserStatus.ACTIVE,
                role="trader",
            )
        )
        s.commit()
    return email


def test_an_unknown_email_still_pays_the_password_verification_cost(svc, monkeypatch):
    """The deterministic half: the work must happen, not merely take as long.

    Asserted at the mechanism rather than the clock, so this test says the same
    thing on a fast laptop and a contended CI runner.
    """
    from auth import service

    calls: list[str] = []
    original = service.verify_password

    def _spy(plain, hashed):
        calls.append(hashed)
        return original(plain, hashed)

    monkeypatch.setattr(service, "verify_password", _spy)

    ok, message, token = svc.login(f"{uuid.uuid4().hex}@example.test", "whatever")

    assert ok is False
    assert token is None
    assert calls, (
        "no password verification ran for an unregistered email — the request returns "
        "as soon as the SELECT misses, which is the whole side channel"
    )


def test_the_refusal_message_is_identical_either_way(svc, session_factory, _hashed_password):
    """The response must stay indistinguishable — the fix must not change that."""
    known = _register(session_factory, _hashed_password)

    ok_known, msg_known, tok_known = svc.login(known, "wrong-password")
    ok_unknown, msg_unknown, tok_unknown = svc.login(f"{uuid.uuid4().hex}@example.test", "wrong-password")

    assert (ok_known, tok_known) == (False, None)
    assert (ok_unknown, tok_unknown) == (False, None)
    assert msg_known == msg_unknown


def test_a_correct_password_still_authenticates(svc, session_factory, _hashed_password):
    """The positive control.

    Without it, every assertion above is satisfied by a login that refuses
    everyone — which would be indistinguishable in exactly the way the tests
    are asking about.
    """
    email = _register(session_factory, _hashed_password)

    ok, _message, token = svc.login(email, _PASSWORD)

    assert ok is True
    assert token is not None and token.get("access_token")


@pytest.mark.slow
def test_login_timing_does_not_separate_registered_from_unregistered(svc, session_factory, _hashed_password):
    """The outcome half, with a bound loose enough not to flake.

    Before the fix the ratio was ~257x. Anything under 4x has closed the channel
    for practical purposes; a tighter assertion would measure the runner's load
    rather than this code. Marked slow because bcrypt at cost 12 is ~300 ms and
    this runs it a dozen times.
    """
    registered: list[float] = []
    unregistered: list[float] = []

    for _ in range(6):
        email = _register(session_factory, _hashed_password)

        t0 = time.perf_counter()
        svc.login(email, "wrong-password")
        registered.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        svc.login(f"{uuid.uuid4().hex}@example.test", "wrong-password")
        unregistered.append(time.perf_counter() - t0)

    known = statistics.median(registered)
    unknown = statistics.median(unregistered)
    ratio = max(known, unknown) / max(min(known, unknown), 1e-9)

    assert ratio < 4.0, (
        f"login time still separates registered from unregistered: "
        f"{known * 1000:.1f} ms vs {unknown * 1000:.1f} ms ({ratio:.0f}x)"
    )
