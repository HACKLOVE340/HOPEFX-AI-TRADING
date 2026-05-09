# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
AuthService — all authentication business logic.

Responsibilities:
- Password hashing (bcrypt via passlib)
- User registration with email verification token
- Login with brute-force protection (5 failures → 15-min lockout)
- JWT access token creation (short-lived, 15 min)
- Refresh token creation + DB storage (long-lived, 7 days)
- Token refresh (rotate refresh token on every use)
- Logout (revoke session row)
- Logout-all (revoke all sessions for user)
- Password reset flow
- 2FA setup + verification (pyotp TOTP)
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

import jwt

logger = logging.getLogger(__name__)

# ── Access-token blacklist (Redis-backed, in-memory fallback) ─────────────────
# Stores jti (JWT ID) of revoked access tokens until their natural expiry.


class _TokenBlacklist:
    """
    Thin wrapper around Redis for access-token revocation.
    Falls back to an in-memory set when Redis is unavailable.

    Connection is attempted lazily on first use and retried at most once
    every _RETRY_INTERVAL_S seconds so a Redis restart is picked up without
    requiring an application restart.
    """

    _RETRY_INTERVAL_S: float = 30.0

    def __init__(self):
        self._redis = None
        self._mem: set = set()
        self._last_attempt: float = 0.0  # epoch of last connection attempt

    def _try_connect(self):
        now = time.monotonic()
        if self._redis is not None:
            return  # already connected
        if now - self._last_attempt < self._RETRY_INTERVAL_S:
            return  # back-off: don't hammer a down Redis
        self._last_attempt = now
        try:
            import redis as _redis_lib

            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", "6379"))
            password = os.getenv("REDIS_PASSWORD") or None
            client = _redis_lib.Redis(
                host=host,
                port=port,
                password=password,
                socket_connect_timeout=0.5,
                socket_timeout=1.0,  # cap ping/op time, not just TCP handshake
                decode_responses=True,
                retry_on_error=[],
                retry=None,
            )
            client.ping()
            self._redis = client
            logger.info("Token blacklist: Redis connected at %s:%s", host, port)
        except Exception as exc:
            # Log the error detail at DEBUG — the traceback adds no actionable
            # information beyond the exception message itself.
            logger.debug("Token blacklist: Redis connect failed: %s", exc)
            # Emit the WARNING once per retry window (i.e. only when we actually
            # attempted a connection, not when we skipped due to back-off).
            logger.warning(
                "Token blacklist: Redis unavailable — using in-memory fallback "
                "(not suitable for multi-process). Will retry in %.0fs.",
                self._RETRY_INTERVAL_S,
            )
            self._redis = None

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Mark a token JTI as revoked for ttl_seconds."""
        self._try_connect()
        if self._redis:
            try:
                self._redis.setex(f"revoked:{jti}", ttl_seconds, "1")
                return
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        self._mem.add(jti)

    def is_revoked(self, jti: str) -> bool:
        self._try_connect()
        if self._redis:
            try:
                return bool(self._redis.exists(f"revoked:{jti}"))
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        return jti in self._mem


_blacklist = _TokenBlacklist()


def revoke_access_token(jti: str, ttl_seconds: int) -> None:
    """Blacklist an access token by its JTI claim."""
    _blacklist.revoke(jti, ttl_seconds)


def is_access_token_revoked(jti: str) -> bool:
    """Return True if the access token has been explicitly revoked."""
    return _blacklist.is_revoked(jti)


# ── Constants ────────────────────────────────────────────────────────────────
# Access-token lifetime is the single source of truth in auth/jwt.py.
# Do NOT define a local ACCESS_TOKEN_EXPIRE_MINUTES constant here — it would
# diverge from jwt.py's _get_access_token_expire_minutes() which reads the
# same env var but with a different default (15 min vs the old 60 min here).
# All callers in this module use _access_token_expire_minutes() instead.
def _access_token_expire_minutes() -> int:
    """Delegate to auth.jwt for the single source of truth on token lifetime."""
    from auth.jwt import _get_access_token_expire_minutes as _jwt_expire
    return _jwt_expire()

REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))
ALGORITHM = "HS256"

# When False (default in development), new accounts are auto-verified and the
# email-verification gate is skipped at login.  Set to True in production so
# users must click the verification link before they can log in.
_REQUIRE_EMAIL_VERIFICATION: bool = os.getenv(
    "REQUIRE_EMAIL_VERIFICATION",
    "true" if os.getenv("APP_ENV", "development").lower() == "production" else "false",
).lower() in ("1", "true", "yes")


def _get_secret() -> str:
    """Return the JWT signing secret.

    Delegates to ``auth.jwt._get_secret()`` — the single source of truth for
    env-var fallback order (SECURITY_JWT_SECRET → JWT_SECRET_KEY) and
    validation (length, CHANGE_ME guard).  Previously this function only read
    SECURITY_JWT_SECRET with no fallback, diverging from auth/jwt.py.
    """
    from auth.jwt import _get_secret as _jwt_get_secret

    return _jwt_get_secret()


def _hash_token(raw: str) -> str:
    """SHA-256 hash of a raw token for safe DB storage."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


# ── TOTP secret encryption at rest ───────────────────────────────────────────
# Uses Fernet (AES-128-CBC + HMAC-SHA256) keyed from CONFIG_ENCRYPTION_KEY.
# Falls back to base64 identity encoding when cryptography is not installed.


def _get_fernet():
    try:
        import base64

        from cryptography.fernet import Fernet

        raw_key = os.getenv("CONFIG_ENCRYPTION_KEY", "")
        if not raw_key:
            return None
        # Derive a 32-byte key from the env var via SHA-256, then base64url-encode
        key_bytes = hashlib.sha256(raw_key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(fernet_key)
    except Exception:
        logger.debug("_get_fernet: key derivation failed", exc_info=True)
        return None


def encrypt_totp_secret(plain: str) -> str:
    """Encrypt a TOTP secret for DB storage. Returns base64 ciphertext or plain if unavailable."""
    f = _get_fernet()
    if f:
        return f.encrypt(plain.encode()).decode()
    return plain  # fallback: store plain (warn in logs)


def decrypt_totp_secret(stored: str) -> str:
    """Decrypt a stored TOTP secret. Returns plain text."""
    f = _get_fernet()
    if f:
        try:
            return f.decrypt(stored.encode()).decode()
        except Exception:
            logger.debug("decrypt_totp_secret: decryption failed (may be plain)", exc_info=True)
            # May already be plain (migration case)
            return stored
    return stored


# ── Password hashing ─────────────────────────────────────────────────────────
# Delegate to auth.jwt which uses bcrypt (BLAKE2b pre-hash, cost 12).
# BLAKE2b normalises the input to ≤72 bytes before bcrypt to avoid bcrypt's
# silent 72-byte truncation for long passwords.
# A single implementation ensures the hash written at registration is always
# the same scheme verified at login — previously this module used pbkdf2_sha256
# while auth.jwt used bcrypt, causing "hash could not be identified" on login.
from auth.jwt import hash_password, verify_password

# ── TOTP (2FA) ───────────────────────────────────────────────────────────────
try:
    import pyotp as _pyotp

    def generate_totp_secret() -> str:
        return _pyotp.random_base32()

    def get_totp_uri(secret: str, email: str) -> str:
        return _pyotp.totp.TOTP(secret).provisioning_uri(email, issuer_name="HOPEFX")

    def verify_totp(secret: str, code: str) -> bool:
        return _pyotp.TOTP(secret).verify(code, valid_window=1)

except ImportError:

    def generate_totp_secret() -> str:  # type: ignore[misc]
        return secrets.token_hex(20)

    def get_totp_uri(secret: str, email: str) -> str:  # type: ignore[misc]
        return f"otpauth://totp/HOPEFX:{email}?secret={secret}&issuer=HOPEFX"

    def verify_totp(secret: str, code: str) -> bool:  # type: ignore[misc]
        logger.warning("pyotp not installed — 2FA verification always fails")
        return False


class AuthService:
    """
    Stateless auth service. Requires a SQLAlchemy session_factory.
    All methods open their own short-lived sessions.

    Threading model
    ---------------
    All public methods are synchronous (blocking SQLAlchemy calls).
    Callers in async contexts **must** wrap calls with ``asyncio.to_thread()``:

        result = await asyncio.to_thread(service.register, email, username, password)

    ``auth/router.py`` already applies this pattern for all 16 call-sites.

    Migration path
    --------------
    Future work: migrate to async SQLAlchemy (``AsyncSession``) so the DB calls
    are native coroutines. Track in issue #async-auth-service.
    """

    def __init__(self, session_factory):
        self._sf = session_factory

    # ── Registration ─────────────────────────────────────────────────────────

    def register(
        self,
        email: str,
        username: str,
        password: str,
        role: str = "trader",
    ) -> tuple[bool, str, str | None]:
        """
        Create a new user account.

        Returns (success, message, email_verify_token).
        The caller is responsible for sending the verification email.
        """
        from database.user_models import User, UserStatus

        email = email.lower().strip()
        username = username.strip()

        if len(password) < 8:
            return False, "Password must be at least 8 characters", None

        with self._sf() as session:
            if session.query(User).filter_by(email=email).first():
                return False, "Email already registered", None
            if session.query(User).filter_by(username=username).first():
                return False, "Username already taken", None

            # When email verification is disabled (dev/test), auto-verify the
            # account so users can log in immediately after registration.
            auto_verify = not _REQUIRE_EMAIL_VERIFICATION
            verify_token = secrets.token_urlsafe(32)
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                username=username,
                hashed_password=hash_password(password),
                role=role,
                status=UserStatus.ACTIVE.value if auto_verify else UserStatus.PENDING_VERIFICATION.value,
                is_email_verified=auto_verify,
                email_verify_token=None if auto_verify else _hash_token(verify_token),
                email_verify_expires=None if auto_verify else _now() + timedelta(hours=24),
            )
            session.add(user)
            session.commit()
            logger.info("User registered: %s (auto_verified=%s)", email, auto_verify)
            if auto_verify:
                return (True, "Registration successful.", None)
            return (
                True,
                "Registration successful. Check your email to verify.",
                verify_token,
            )

    # ── Email verification ────────────────────────────────────────────────────

    def verify_email(self, token: str) -> tuple[bool, str]:
        from database.user_models import User, UserStatus

        token_hash = _hash_token(token)
        with self._sf() as session:
            user = session.query(User).filter_by(email_verify_token=token_hash).first()
            if not user:
                return False, "Invalid or expired verification token"
            if user.email_verify_expires and _now() > user.email_verify_expires.replace(
                tzinfo=UTC,
            ):
                return False, "Verification token expired. Request a new one."
            user.is_email_verified = True
            user.status = UserStatus.ACTIVE.value
            user.email_verify_token = None
            user.email_verify_expires = None
            session.commit()
            logger.info("Email verified: %s", user.email)
            return True, "Email verified successfully"

    def resend_verification(self, email: str) -> tuple[bool, str, str | None]:
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(email=email.lower().strip()).first()
            if not user:
                return False, "Email not found", None
            if user.is_email_verified:
                return False, "Email already verified", None
            token = secrets.token_urlsafe(32)
            user.email_verify_token = _hash_token(token)
            user.email_verify_expires = _now() + timedelta(hours=24)
            session.commit()
            return True, "Verification email resent", token

    # ── Login ─────────────────────────────────────────────────────────────────

    def login(
        self,
        email: str,
        password: str,
        ip_address: str = "unknown",
        device_info: str = "",
        totp_code: str | None = None,
    ) -> tuple[bool, str, dict | None]:
        """
        Authenticate user. Returns (success, message, token_dict).

        token_dict = {
            "access_token": str,
            "refresh_token": str,
            "token_type": "bearer",  # nosec B105 - OAuth2 token_type value, not a credential
            "expires_in": int (seconds),
            "user": {id, email, username, role}
        }
        """
        from database.user_models import LoginAttempt, User, UserStatus

        email = email.lower().strip()

        with self._sf() as session:
            user = session.query(User).filter_by(email=email).first()

            # Record attempt regardless of outcome
            def _record(success: bool, reason: str = ""):
                session.add(
                    LoginAttempt(
                        user_id=user.id if user else None,
                        email=email,
                        ip_address=ip_address,
                        success=success,
                        failure_reason=reason if not success else None,
                    ),
                )
                session.commit()
                # Prometheus metric
                try:
                    from core.metrics import AUTH_ATTEMPTS

                    if success:
                        AUTH_ATTEMPTS.labels(outcome="success").inc()
                    elif reason == "account_locked":
                        AUTH_ATTEMPTS.labels(outcome="locked").inc()
                    else:
                        AUTH_ATTEMPTS.labels(outcome="failure").inc()
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)

            if not user:
                _record(False, "user_not_found")
                return False, "Invalid credentials", None

            # Brute-force lockout — Redis counter-based (fast path, cross-pod)
            # with DB fallback when Redis is unavailable.
            #
            # Redis key layout:
            #   hopefx:auth:lockout:{user_id}   — SET when account is locked (TTL=LOCKOUT_MINUTES*60)
            #   hopefx:auth:failures:{user_id}  — INCR counter of recent failures (same TTL)
            #
            # Every failed attempt increments the failures counter in Redis so
            # all pods see the same count without a DB round-trip. When the
            # counter reaches MAX_LOGIN_ATTEMPTS the lockout key is set.
            _LOCKOUT_KEY = f"hopefx:auth:lockout:{user.id}"
            _FAILURES_KEY = f"hopefx:auth:failures:{user.id}"
            _LOCKOUT_TTL_SECS = LOCKOUT_MINUTES * 60
            _redis_locked = False
            # _rc is only set when a live, ping-verified Redis connection exists.
            # from_url() is lazy — it does not connect until the first command,
            # so we must call ping() to confirm reachability before trusting _rc.
            _rc = None
            try:
                import redis as _redis_sync
                _rc_candidate = _redis_sync.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
                _rc_candidate.ping()  # raises if Redis is unreachable
                _rc = _rc_candidate
                _redis_locked = bool(_rc.exists(_LOCKOUT_KEY))
            except Exception as _redis_exc:
                logger.warning(
                    "auth: Redis unavailable for lockout check (user=%s) — falling back to DB: %s",
                    user.id,
                    _redis_exc,
                )
                _rc = None  # ensure _rc is None so mirror guards below are correct

            if _redis_locked:
                _record(False, "account_locked")
                return (
                    False,
                    f"Account locked. Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes.",
                    None,
                )

            # DB fallback: count recent failures within the lockout window
            cutoff = _now() - timedelta(minutes=LOCKOUT_MINUTES)
            recent_failures = (
                session.query(LoginAttempt)
                .filter(
                    LoginAttempt.user_id == user.id,
                    LoginAttempt.success == False,  # noqa: E712
                    LoginAttempt.attempted_at >= cutoff,
                )
                .count()
            )
            if recent_failures >= MAX_LOGIN_ATTEMPTS:
                # Mirror lockout to Redis so other pods see it immediately.
                if _rc is not None:
                    try:
                        _rc.setex(_LOCKOUT_KEY, _LOCKOUT_TTL_SECS, "1")
                        # Reset the failures counter — lockout key is now authoritative.
                        _rc.delete(_FAILURES_KEY)
                        logger.info(
                            "auth: lockout mirrored to Redis for user=%s (TTL=%ds)",
                            user.id,
                            _LOCKOUT_TTL_SECS,
                        )
                    except Exception as _mirror_exc:
                        logger.warning(
                            "auth: failed to mirror lockout to Redis for user=%s: %s",
                            user.id,
                            _mirror_exc,
                        )
                _record(False, "account_locked")
                return (
                    False,
                    f"Account locked. Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes.",
                    None,
                )

            if not verify_password(password, user.hashed_password):
                # Mirror this failure to Redis so all pods have an up-to-date count.
                if _rc is not None:
                    try:
                        pipe = _rc.pipeline()
                        pipe.incr(_FAILURES_KEY)
                        # Set/refresh TTL on the failures counter so it expires
                        # after the lockout window even if no further attempts occur.
                        pipe.expire(_FAILURES_KEY, _LOCKOUT_TTL_SECS)
                        pipe_results = pipe.execute()
                        new_count = pipe_results[0] if pipe_results else 0
                        logger.info(
                            "auth: failure mirrored to Redis for user=%s (count=%d/%d)",
                            user.id,
                            new_count,
                            MAX_LOGIN_ATTEMPTS,
                        )
                        # If the counter just reached the threshold, set the lockout key.
                        if new_count >= MAX_LOGIN_ATTEMPTS:
                            _rc.setex(_LOCKOUT_KEY, _LOCKOUT_TTL_SECS, "1")
                            _rc.delete(_FAILURES_KEY)
                            logger.warning(
                                "auth: Redis lockout key set for user=%s after %d failures",
                                user.id,
                                new_count,
                            )
                    except Exception as _mirror_exc:
                        logger.warning(
                            "auth: failed to mirror failure count to Redis for user=%s: %s",
                            user.id,
                            _mirror_exc,
                        )
                _record(False, "wrong_password")
                return False, "Invalid credentials", None

            if _REQUIRE_EMAIL_VERIFICATION and not user.is_email_verified:
                _record(False, "email_not_verified")
                return False, "Please verify your email before logging in.", None

            if user.status != UserStatus.ACTIVE.value:
                _record(False, f"status_{user.status}")
                return False, f"Account is {user.status}. Contact support.", None

            # 2FA check
            if user.totp_enabled:
                if not totp_code:
                    return False, "2FA code required", None
                plain_secret = decrypt_totp_secret(user.totp_secret)
                if not verify_totp(plain_secret, totp_code):
                    _record(False, "invalid_2fa")
                    return False, "Invalid 2FA code", None

            # Issue tokens
            access_token = self._create_access_token(user)
            raw_refresh, _ = self._create_refresh_session(
                user,
                ip_address,
                device_info,
                session,
            )

            # Update last login
            user.last_login_at = _now()
            user.last_login_ip = ip_address
            _record(True)

            # Clear Redis lockout and failures keys on successful login.
            # _rc is already ping-verified from the lockout check above.
            # If it was None (Redis was down at login time), attempt a fresh
            # verified connection so a recovered Redis gets cleaned up.
            try:
                _clear_rc = _rc
                if _clear_rc is None:
                    import redis as _redis_sync
                    _clear_rc = _redis_sync.from_url(
                        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                        decode_responses=True,
                        socket_connect_timeout=1,
                        socket_timeout=1,
                    )
                    _clear_rc.ping()  # validate before use
                _clear_rc.delete(
                    f"hopefx:auth:lockout:{user.id}",
                    f"hopefx:auth:failures:{user.id}",
                )
                logger.info("auth: Redis lockout/failures keys cleared for user=%s", user.id)
            except Exception as _clear_exc:
                logger.warning(
                    "auth: could not clear Redis lockout keys for user=%s (non-fatal): %s",
                    user.id,
                    _clear_exc,
                )

            return (
                True,
                "Login successful",
                {
                    "access_token": access_token,
                    "refresh_token": raw_refresh,
                    "token_type": "bearer",  # nosec B105 - OAuth2 token_type value, not a credential
                    "expires_in": _access_token_expire_minutes() * 60,
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "role": user.role,
                        "plan": getattr(user, "plan", "free"),
                        "kyc_status": user.kyc_status,
                        "totp_enabled": user.totp_enabled,
                        "is_email_verified": getattr(user, "is_email_verified", False),
                    },
                },
            )

    # ── Token refresh ─────────────────────────────────────────────────────────

    def refresh(
        self,
        raw_refresh_token: str,
        ip_address: str = "unknown",
    ) -> tuple[bool, str, dict | None]:
        """
        Rotate refresh token. Old token is revoked, new pair issued.
        """
        from database.user_models import User, UserSession

        token_hash = _hash_token(raw_refresh_token)
        with self._sf() as session:
            sess_row = (
                session.query(UserSession)
                .filter_by(refresh_token_hash=token_hash, is_revoked=False)
                .with_for_update()
                .first()
            )
            if not sess_row:
                return False, "Invalid or expired refresh token", None
            _expires = sess_row.expires_at if sess_row.expires_at.tzinfo else sess_row.expires_at.replace(tzinfo=UTC)
            if _now() > _expires:
                sess_row.is_revoked = True
                session.commit()
                return False, "Refresh token expired. Please log in again.", None

            user = session.query(User).filter_by(id=sess_row.user_id).first()
            if not user or user.status != "active":
                return False, "User account inactive", None

            # Revoke old session, recording its last activity time.
            now = _now()
            sess_row.is_revoked = True
            sess_row.revoked_at = now
            sess_row.last_active_at = now

            # Issue new pair
            access_token = self._create_access_token(user)
            raw_new, _ = self._create_refresh_session(
                user,
                ip_address,
                sess_row.device_info or "",
                session,
            )
            session.commit()

            return (
                True,
                "Token refreshed",
                {
                    "access_token": access_token,
                    "refresh_token": raw_new,
                    "token_type": "bearer",  # nosec B105 - OAuth2 token_type value, not a credential
                    "expires_in": _access_token_expire_minutes() * 60,
                },
            )

    # ── Logout ────────────────────────────────────────────────────────────────

    def logout(
        self,
        raw_refresh_token: str | None,
        access_token: str | None = None,
    ) -> tuple[bool, str]:
        from database.user_models import UserSession

        # Revoke refresh session in DB (only when a refresh token was supplied)
        if raw_refresh_token:
            token_hash = _hash_token(raw_refresh_token)
            with self._sf() as session:
                sess_row = session.query(UserSession).filter_by(refresh_token_hash=token_hash).first()
                if sess_row:
                    sess_row.is_revoked = True
                    sess_row.revoked_at = _now()
                    session.commit()

        # Blacklist the access token immediately so it can't be reused
        if access_token:
            try:
                payload = jwt.decode(
                    access_token,
                    _get_secret(),
                    algorithms=[ALGORITHM],
                )
                jti = payload.get("jti")
                exp = payload.get("exp", 0)
                if jti:
                    ttl = max(0, exp - int(_now().timestamp()))
                    revoke_access_token(jti, ttl + 60)  # +60s buffer
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)  # expired or invalid — no need to blacklist

        return True, "Logged out successfully"

    def logout_all(self, user_id: str) -> tuple[bool, str]:
        """Revoke all active sessions for a user (e.g. after password change)."""
        from database.user_models import UserSession

        with self._sf() as session:
            session.query(UserSession).filter_by(
                user_id=user_id,
                is_revoked=False,
            ).update({"is_revoked": True, "revoked_at": _now()})
            session.commit()
        return True, "All sessions revoked"

    # ── Password reset ────────────────────────────────────────────────────────

    def request_password_reset(self, email: str) -> tuple[bool, str, str | None]:
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(email=email.lower().strip()).first()
            if not user:
                # Don't reveal whether email exists
                return (
                    True,
                    "If that email is registered, a reset link has been sent.",
                    None,
                )
            token = secrets.token_urlsafe(32)
            user.password_reset_token = _hash_token(token)
            user.password_reset_expires = _now() + timedelta(hours=1)
            session.commit()
            return True, "Password reset email sent", token

    def reset_password(self, token: str, new_password: str) -> tuple[bool, str]:
        from database.user_models import User

        if len(new_password) < 8:
            return False, "Password must be at least 8 characters"

        token_hash = _hash_token(token)
        with self._sf() as session:
            user = session.query(User).filter_by(password_reset_token=token_hash).first()
            if not user:
                return False, "Invalid or expired reset token"
            _reset_expires = user.password_reset_expires
            if _reset_expires and not _reset_expires.tzinfo:
                _reset_expires = _reset_expires.replace(tzinfo=UTC)
            if _reset_expires and _now() > _reset_expires:
                return False, "Reset token expired. Request a new one."
            user.hashed_password = hash_password(new_password)
            user.password_reset_token = None
            user.password_reset_expires = None
            session.commit()
            # Revoke all sessions after password change
            self.logout_all(user.id)
            logger.info("Password reset for user: %s", user.email)
            return True, "Password reset successfully. Please log in."

    # ── 2FA ──────────────────────────────────────────────────────────────────

    def setup_2fa(self, user_id: str) -> tuple[bool, str, str | None]:
        """Generate TOTP secret (encrypted at rest). User must confirm before enabling."""
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return False, "User not found", None
            secret = generate_totp_secret()
            user.totp_secret = encrypt_totp_secret(secret)  # encrypted at rest
            user.totp_enabled = False  # not active until confirmed
            session.commit()
            uri = get_totp_uri(secret, user.email)
            return True, uri, secret

    def confirm_2fa(self, user_id: str, code: str) -> tuple[bool, str]:
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user or not user.totp_secret:
                return False, "2FA not set up"
            plain_secret = decrypt_totp_secret(user.totp_secret)
            if not verify_totp(plain_secret, code):
                return False, "Invalid code"
            user.totp_enabled = True
            session.commit()
            return True, "2FA enabled successfully"

    def disable_2fa(self, user_id: str, code: str) -> tuple[bool, str]:
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user or not user.totp_enabled:
                return False, "2FA not enabled"
            plain_secret = decrypt_totp_secret(user.totp_secret)
            if not verify_totp(plain_secret, code):
                return False, "Invalid code"
            user.totp_enabled = False
            user.totp_secret = None
            session.commit()
            return True, "2FA disabled"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _create_access_token(self, user) -> str:
        now = _now()
        payload = {
            "sub": user.id,
            "email": user.email,
            "username": user.username,
            "role": user.role,
            "jti": secrets.token_hex(16),  # unique token ID for blacklisting
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(minutes=_access_token_expire_minutes())).timestamp(),
            ),
            "type": "access",
        }
        return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)

    def _create_refresh_session(
        self,
        user,
        ip_address: str,
        device_info: str,
        session,
    ) -> tuple[str, object]:
        from database.user_models import UserSession

        now = _now()
        raw_token = secrets.token_urlsafe(48)
        sess_row = UserSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            refresh_token_hash=_hash_token(raw_token),
            device_info=device_info[:255] if device_info else None,
            ip_address=ip_address,
            expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
            last_active_at=now,
        )
        session.add(sess_row)
        return raw_token, sess_row

    def get_user_by_id(self, user_id: str):
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if user is not None:
                # Expunge so the object can be accessed after the session closes
                # without triggering DetachedInstanceError on column attributes.
                session.expunge(user)
            return user

    def get_user_by_email(self, email: str):
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(email=email.lower().strip()).first()
            if user is not None:
                session.expunge(user)
            return user

    def get_user_by_username(self, username: str):
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(username=username.strip()).first()
            if user is not None:
                session.expunge(user)
            return user
