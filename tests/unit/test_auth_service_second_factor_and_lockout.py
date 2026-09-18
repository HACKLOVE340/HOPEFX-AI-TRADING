# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Two-factor enrolment and account lockout, against a real database.

Both are security controls on a money-moving platform, and neither had ever
executed in a test — `auth/service.py` measured 67%, and these two blocks were
most of the gap. A control nobody has run is a control nobody knows works
(F176).

The session factory is a real in-memory SQLite with the real ORM models, not a
stub `query()`. The bugs worth catching here — a secret stored in the clear, a
second factor that is live before it is confirmed, a lockout that counts
successes — all live in the interaction with the database, which a fake session
would answer for.

What is asserted:

* **Enrolment is not activation.** `setup_2fa` must leave `totp_enabled` False.
  A secret that is live the moment it is generated locks the user out of their
  own account between the QR code and the first successful scan.
* **The secret is encrypted at rest**, and the plaintext never equals the
  column.
* **Disabling clears the secret**, so a re-enrolment cannot resurrect an old
  one the user believes is gone.
* **Lockout counts failures, not attempts**, and only recent ones.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

import pytest

pytestmark = [pytest.mark.unit]

USER_EMAIL = "ren@example.test"


@pytest.fixture
def session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.user_models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    class _Ctx:
        def __init__(self):
            self.s = Session()

        def __enter__(self):
            return self.s

        def __exit__(self, *_a):
            self.s.close()
            return False

    return _Ctx


@pytest.fixture
def svc(session_factory):
    from auth.service import AuthService

    return AuthService(session_factory)


@pytest.fixture
def user(session_factory):
    from auth.jwt import hash_password
    from database.user_models import User, UserStatus

    with session_factory() as s:
        u = User(
            id="u-1",
            email=USER_EMAIL,
            username="ren",
            hashed_password=hash_password("correct-horse-battery"),
            status=UserStatus.ACTIVE if hasattr(UserStatus, "ACTIVE") else "active",
            is_email_verified=True,
        )
        s.add(u)
        s.commit()
    return "u-1"


def _row(session_factory, uid="u-1"):
    from database.user_models import User

    with session_factory() as s:
        return s.query(User).filter_by(id=uid).first()


class TestEnrolmentIsNotActivation:
    def test_setup_returns_a_uri_and_a_secret(self, svc, user):
        ok, uri, secret = svc.setup_2fa(user)

        assert ok is True
        assert secret and len(secret) >= 16
        assert uri.startswith("otpauth://totp/")
        # The account label is URL-encoded, so the raw address does not appear.
        assert quote(USER_EMAIL, safe="") in uri or USER_EMAIL in uri
        assert f"secret={secret}" in uri

    def test_setup_leaves_two_factor_disabled_until_confirmed(self, svc, user, session_factory):
        svc.setup_2fa(user)

        assert _row(session_factory).totp_enabled is False, (
            "the second factor went live at enrolment — the user is locked out until they scan"
        )

    def test_the_secret_is_not_stored_in_the_clear_when_a_key_is_configured(
        self, svc, user, session_factory, monkeypatch
    ):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "a" * 40)
        _ok, _uri, secret = svc.setup_2fa(user)

        stored = _row(session_factory).totp_secret
        assert stored, "no secret was persisted at all"
        assert stored != secret, "the TOTP secret is stored in plaintext despite a configured key"

    def test_the_stored_secret_still_decrypts_to_the_one_the_user_scanned(
        self, svc, user, session_factory, monkeypatch
    ):
        from auth.service import decrypt_totp_secret

        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "a" * 40)
        _ok, _uri, secret = svc.setup_2fa(user)

        assert decrypt_totp_secret(_row(session_factory).totp_secret) == secret

    def test_setup_for_an_unknown_user_is_refused(self, svc):
        ok, msg, secret = svc.setup_2fa("nobody")

        assert ok is False
        assert secret is None
        assert "not found" in msg.lower()


class TestConfirmation:
    def test_the_right_code_enables_it(self, svc, user, session_factory):
        import pyotp

        _ok, _uri, secret = svc.setup_2fa(user)
        ok, msg = svc.confirm_2fa(user, pyotp.TOTP(secret).now())

        assert ok is True, msg
        assert _row(session_factory).totp_enabled is True

    def test_a_wrong_code_does_not_enable_it(self, svc, user, session_factory):
        svc.setup_2fa(user)
        ok, msg = svc.confirm_2fa(user, "000000")

        assert ok is False
        assert "invalid" in msg.lower()
        assert _row(session_factory).totp_enabled is False, "a wrong code enabled the second factor"

    def test_confirming_without_enrolling_is_refused(self, svc, user):
        ok, msg = svc.confirm_2fa(user, "123456")

        assert ok is False
        assert "not set up" in msg.lower()


class TestDisabling:
    def test_the_right_code_disables_and_clears_the_secret(self, svc, user, session_factory):
        import pyotp

        _ok, _uri, secret = svc.setup_2fa(user)
        svc.confirm_2fa(user, pyotp.TOTP(secret).now())

        ok, _msg = svc.disable_2fa(user, pyotp.TOTP(secret).now())

        assert ok is True
        row = _row(session_factory)
        assert row.totp_enabled is False
        assert row.totp_secret is None, (
            "the old secret survived being disabled — a re-enrolment could resurrect a secret the user believes is gone"
        )

    def test_a_wrong_code_does_not_disable_it(self, svc, user, session_factory):
        import pyotp

        _ok, _uri, secret = svc.setup_2fa(user)
        svc.confirm_2fa(user, pyotp.TOTP(secret).now())

        ok, _msg = svc.disable_2fa(user, "000000")

        assert ok is False
        assert _row(session_factory).totp_enabled is True, "a wrong code turned the second factor off"

    def test_disabling_when_it_was_never_enabled_is_refused(self, svc, user):
        ok, msg = svc.disable_2fa(user, "123456")

        assert ok is False
        assert "not enabled" in msg.lower()


class TestAccountLockout:
    """The DB path, which is what runs when Redis is unreachable — i.e. in this
    environment, and in any single-node deployment."""

    @pytest.fixture(autouse=True)
    def _no_redis(self, monkeypatch):
        """Force the documented DB fallback, deterministically.

        The first version of this fixture set `auth.service._redis_sync = None`
        and did nothing at all: the login path does `import redis as
        _redis_sync` **inside** the function, so that name is a local, not a
        module attribute. The tests were quietly running against the real Redis
        in this environment, one test's lockout key outlived it, and a later
        test found the account already locked — under a randomised order, so it
        looked like a product bug.

        `redis.from_url` is the seam that actually exists. Patching it here
        makes the DB fallback run whether or not a Redis is reachable.
        """
        import redis

        def _unreachable(*_a, **_k):
            raise ConnectionError("redis unreachable (test)")

        monkeypatch.setattr(redis, "from_url", _unreachable)

    def _fail(self, svc, n: int):
        for _ in range(n):
            svc.login(USER_EMAIL, "wrong-password", ip_address="198.51.100.1")

    def test_the_right_password_works_before_any_failures(self, svc, user):
        """Liveness. Every lockout assertion below is meaningless if login is
        broken for an unrelated reason."""
        ok, msg, _payload = svc.login(USER_EMAIL, "correct-horse-battery", ip_address="198.51.100.1")

        assert ok is True, msg

    def test_a_burst_of_wrong_passwords_locks_the_account(self, svc, user):
        from auth.service import MAX_LOGIN_ATTEMPTS

        self._fail(svc, MAX_LOGIN_ATTEMPTS + 1)
        ok, msg, _ = svc.login(USER_EMAIL, "correct-horse-battery", ip_address="198.51.100.1")

        assert ok is False, "the correct password was accepted after the lockout threshold"
        assert "locked" in msg.lower()

    def test_failures_older_than_the_window_do_not_count(self, svc, user, session_factory, monkeypatch):
        import auth.service as asvc
        from auth.service import LOCKOUT_MINUTES, MAX_LOGIN_ATTEMPTS
        from database.user_models import LoginAttempt

        now = asvc._now()
        stale = now - timedelta(minutes=LOCKOUT_MINUTES + 5)
        with session_factory() as s:
            for _ in range(MAX_LOGIN_ATTEMPTS + 3):
                s.add(
                    LoginAttempt(
                        user_id="u-1",
                        email=USER_EMAIL,
                        ip_address="198.51.100.1",
                        success=False,
                        failure_reason="bad_password",
                        attempted_at=stale,
                    )
                )
            s.commit()

        ok, msg, _ = svc.login(USER_EMAIL, "correct-horse-battery", ip_address="198.51.100.1")

        assert ok is True, f"failures outside the {LOCKOUT_MINUTES}-minute window still locked the account: {msg}"

    def test_a_wrong_password_is_recorded_as_a_failure(self, svc, user, session_factory):
        from database.user_models import LoginAttempt

        svc.login(USER_EMAIL, "wrong-password", ip_address="198.51.100.1")

        with session_factory() as s:
            rows = s.query(LoginAttempt).filter_by(user_id="u-1").all()
        assert rows, "nothing was recorded, so the lockout counter can never rise"
        assert any(r.success is False for r in rows)

    def test_an_unknown_email_does_not_reveal_itself(self, svc, user):
        ok, msg, _ = svc.login("nobody@example.test", "whatever", ip_address="198.51.100.1")

        assert ok is False
        assert "not found" not in msg.lower() and "no such" not in msg.lower()


class TestStoringATotpSecretWithoutAKey:
    """`encrypt_totp_secret` returns the plaintext when CONFIG_ENCRYPTION_KEY is
    unset, and `setup_2fa` writes it to the column under a comment that says
    "encrypted at rest".

    `config/startup_validator.py` requires that key for production, so this is a
    misconfiguration rather than a certain hole — but it is the shape this
    repository keeps finding: a control that degrades to nothing and does not
    say so. A database leak in that configuration hands over every user's TOTP
    secret, which is the whole second factor.

    The behaviour is pinned, not changed: refusing to enrol without a key is a
    posture decision for the owner (filed). What is asserted is that it is
    announced.
    """

    def test_without_a_key_the_secret_is_stored_as_plaintext(self, monkeypatch):
        from auth.service import decrypt_totp_secret, encrypt_totp_secret

        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
        stored = encrypt_totp_secret("SOMESECRET234567")

        assert stored == "SOMESECRET234567", (
            "encryption now happens without a configured key — a posture change; update this test and the owner task"
        )
        assert decrypt_totp_secret(stored) == "SOMESECRET234567"

    def test_storing_plaintext_is_announced(self, monkeypatch, caplog):
        import logging

        from auth.service import encrypt_totp_secret

        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
        caplog.set_level(logging.INFO, logger="auth.service")
        encrypt_totp_secret("SOMESECRET234567")

        loud = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert loud, "a TOTP secret was stored unencrypted and nothing above DEBUG said so"

    def test_the_message_names_what_is_unprotected(self, monkeypatch, caplog):
        import logging

        from auth.service import encrypt_totp_secret

        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
        caplog.set_level(logging.INFO, logger="auth.service")
        encrypt_totp_secret("SOMESECRET234567")

        text = " ".join(r.getMessage().lower() for r in caplog.records if r.levelno >= logging.ERROR)
        assert "totp" in text and ("plaintext" in text or "unencrypted" in text), (
            f"the log does not say a TOTP secret is unprotected: {text!r}"
        )

    def test_a_configured_key_is_silent(self, monkeypatch, caplog):
        """Liveness for the three tests above: the warning must be conditional,
        not unconditional."""
        import logging

        from auth.service import encrypt_totp_secret

        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "a" * 40)
        caplog.set_level(logging.INFO, logger="auth.service")
        encrypt_totp_secret("SOMESECRET234567")

        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
