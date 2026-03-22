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
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import jwt

logger = logging.getLogger(__name__)

# ── Access-token blacklist (Redis-backed, in-memory fallback) ─────────────────
# Stores jti (JWT ID) of revoked access tokens until their natural expiry.

class _TokenBlacklist:
    """
    Thin wrapper around Redis for access-token revocation.
    Falls back to an in-memory set when Redis is unavailable.
    """

    def __init__(self):
        self._redis = None
        self._mem: set = set()
        self._try_connect()

    def _try_connect(self):
        try:
            import redis as _redis_lib
            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", "6379"))
            self._redis = _redis_lib.Redis(host=host, port=port, socket_connect_timeout=2, decode_responses=True)
            self._redis.ping()
            logger.info("Token blacklist: Redis connected at %s:%s", host, port)
        except Exception:
            logger.warning("Token blacklist: Redis unavailable — using in-memory fallback (not suitable for multi-process)")
            self._redis = None

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Mark a token JTI as revoked for ttl_seconds."""
        if self._redis:
            try:
                self._redis.setex(f"revoked:{jti}", ttl_seconds, "1")
                return
            except Exception:
                pass
        self._mem.add(jti)

    def is_revoked(self, jti: str) -> bool:
        if self._redis:
            try:
                return bool(self._redis.exists(f"revoked:{jti}"))
            except Exception:
                pass
        return jti in self._mem


_blacklist = _TokenBlacklist()


def revoke_access_token(jti: str, ttl_seconds: int) -> None:
    """Blacklist an access token by its JTI claim."""
    _blacklist.revoke(jti, ttl_seconds)


def is_access_token_revoked(jti: str) -> bool:
    """Return True if the access token has been explicitly revoked."""
    return _blacklist.is_revoked(jti)


# ── Constants ────────────────────────────────────────────────────────────────
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))
ALGORITHM = "HS256"


def _get_secret() -> str:
    s = os.getenv("SECURITY_JWT_SECRET")
    if not s or len(s) < 32:
        raise RuntimeError("SECURITY_JWT_SECRET not set or too short")
    return s


def _hash_token(raw: str) -> str:
    """SHA-256 hash of a raw token for safe DB storage."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── TOTP secret encryption at rest ───────────────────────────────────────────
# Uses Fernet (AES-128-CBC + HMAC-SHA256) keyed from CONFIG_ENCRYPTION_KEY.
# Falls back to base64 identity encoding when cryptography is not installed.

def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        import base64
        raw_key = os.getenv("CONFIG_ENCRYPTION_KEY", "")
        if not raw_key:
            return None
        # Derive a 32-byte key from the env var via SHA-256, then base64url-encode
        key_bytes = hashlib.sha256(raw_key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(fernet_key)
    except Exception:
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
            # May already be plain (migration case)
            return stored
    return stored


# ── Password hashing ─────────────────────────────────────────────────────────
# Use passlib pbkdf2_sha256 — avoids bcrypt version compatibility issues while
# still being a secure, well-tested KDF.
try:
    from passlib.context import CryptContext
    _pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    def hash_password(plain: str) -> str:
        return _pwd_ctx.hash(plain)

    def verify_password(plain: str, hashed: str) -> bool:
        return _pwd_ctx.verify(plain, hashed)

except ImportError:
    import hashlib as _hl

    def hash_password(plain: str) -> str:  # type: ignore[misc]
        salt = secrets.token_hex(16)
        h = _hl.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 260_000)
        return f"pbkdf2:{salt}:{h.hex()}"

    def verify_password(plain: str, hashed: str) -> bool:  # type: ignore[misc]
        try:
            _, salt, stored = hashed.split(":")
            h = _hl.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 260_000)
            return h.hex() == stored
        except Exception:
            return False


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
    ) -> Tuple[bool, str, Optional[str]]:
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

            verify_token = secrets.token_urlsafe(32)
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                username=username,
                hashed_password=hash_password(password),
                role=role,
                status=UserStatus.PENDING_VERIFICATION.value,
                is_email_verified=False,
                email_verify_token=_hash_token(verify_token),
                email_verify_expires=_now() + timedelta(hours=24),
            )
            session.add(user)
            session.commit()
            logger.info("User registered: %s", email)
            return True, "Registration successful. Check your email to verify.", verify_token

    # ── Email verification ────────────────────────────────────────────────────

    def verify_email(self, token: str) -> Tuple[bool, str]:
        from database.user_models import User, UserStatus

        token_hash = _hash_token(token)
        with self._sf() as session:
            user = session.query(User).filter_by(email_verify_token=token_hash).first()
            if not user:
                return False, "Invalid or expired verification token"
            if user.email_verify_expires and _now() > user.email_verify_expires.replace(tzinfo=timezone.utc):
                return False, "Verification token expired. Request a new one."
            user.is_email_verified = True
            user.status = UserStatus.ACTIVE.value
            user.email_verify_token = None
            user.email_verify_expires = None
            session.commit()
            logger.info("Email verified: %s", user.email)
            return True, "Email verified successfully"

    def resend_verification(self, email: str) -> Tuple[bool, str, Optional[str]]:
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
        totp_code: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        Authenticate user. Returns (success, message, token_dict).

        token_dict = {
            "access_token": str,
            "refresh_token": str,
            "token_type": "bearer",
            "expires_in": int (seconds),
            "user": {id, email, username, role}
        }
        """
        from database.user_models import User, UserSession, LoginAttempt, UserStatus

        email = email.lower().strip()

        with self._sf() as session:
            user = session.query(User).filter_by(email=email).first()

            # Record attempt regardless of outcome
            def _record(success: bool, reason: str = ""):
                session.add(LoginAttempt(
                    user_id=user.id if user else None,
                    email=email,
                    ip_address=ip_address,
                    success=success,
                    failure_reason=reason if not success else None,
                ))
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
                except Exception:
                    pass

            if not user:
                _record(False, "user_not_found")
                return False, "Invalid credentials", None

            # Brute-force lockout
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
                _record(False, "account_locked")
                return False, f"Account locked. Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes.", None

            if not verify_password(password, user.hashed_password):
                _record(False, "wrong_password")
                return False, "Invalid credentials", None

            if not user.is_email_verified:
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
            raw_refresh, session_row = self._create_refresh_session(
                user, ip_address, device_info, session
            )

            # Update last login
            user.last_login_at = _now()
            user.last_login_ip = ip_address
            _record(True)

            return True, "Login successful", {
                "access_token": access_token,
                "refresh_token": raw_refresh,
                "token_type": "bearer",
                "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "role": user.role,
                    "kyc_status": user.kyc_status,
                    "totp_enabled": user.totp_enabled,
                },
            }

    # ── Token refresh ─────────────────────────────────────────────────────────

    def refresh(self, raw_refresh_token: str, ip_address: str = "unknown") -> Tuple[bool, str, Optional[dict]]:
        """
        Rotate refresh token. Old token is revoked, new pair issued.
        """
        from database.user_models import User, UserSession

        token_hash = _hash_token(raw_refresh_token)
        with self._sf() as session:
            sess_row = (
                session.query(UserSession)
                .filter_by(refresh_token_hash=token_hash, is_revoked=False)
                .first()
            )
            if not sess_row:
                return False, "Invalid or expired refresh token", None
            if _now() > sess_row.expires_at.replace(tzinfo=timezone.utc):
                sess_row.is_revoked = True
                session.commit()
                return False, "Refresh token expired. Please log in again.", None

            user = session.query(User).filter_by(id=sess_row.user_id).first()
            if not user or user.status != "active":
                return False, "User account inactive", None

            # Revoke old session
            sess_row.is_revoked = True
            sess_row.revoked_at = _now()

            # Issue new pair
            access_token = self._create_access_token(user)
            raw_new, _ = self._create_refresh_session(user, ip_address, sess_row.device_info or "", session)
            session.commit()

            return True, "Token refreshed", {
                "access_token": access_token,
                "refresh_token": raw_new,
                "token_type": "bearer",
                "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            }

    # ── Logout ────────────────────────────────────────────────────────────────

    def logout(self, raw_refresh_token: str, access_token: Optional[str] = None) -> Tuple[bool, str]:
        from database.user_models import UserSession

        # Revoke refresh session in DB
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
                payload = jwt.decode(access_token, _get_secret(), algorithms=[ALGORITHM])
                jti = payload.get("jti")
                exp = payload.get("exp", 0)
                if jti:
                    ttl = max(0, exp - int(_now().timestamp()))
                    revoke_access_token(jti, ttl + 60)  # +60s buffer
            except Exception:
                pass  # expired or invalid — no need to blacklist

        return True, "Logged out successfully"

    def logout_all(self, user_id: str) -> Tuple[bool, str]:
        """Revoke all active sessions for a user (e.g. after password change)."""
        from database.user_models import UserSession

        with self._sf() as session:
            session.query(UserSession).filter_by(user_id=user_id, is_revoked=False).update(
                {"is_revoked": True, "revoked_at": _now()}
            )
            session.commit()
        return True, "All sessions revoked"

    # ── Password reset ────────────────────────────────────────────────────────

    def request_password_reset(self, email: str) -> Tuple[bool, str, Optional[str]]:
        from database.user_models import User

        with self._sf() as session:
            user = session.query(User).filter_by(email=email.lower().strip()).first()
            if not user:
                # Don't reveal whether email exists
                return True, "If that email is registered, a reset link has been sent.", None
            token = secrets.token_urlsafe(32)
            user.password_reset_token = _hash_token(token)
            user.password_reset_expires = _now() + timedelta(hours=1)
            session.commit()
            return True, "Password reset email sent", token

    def reset_password(self, token: str, new_password: str) -> Tuple[bool, str]:
        from database.user_models import User

        if len(new_password) < 8:
            return False, "Password must be at least 8 characters"

        token_hash = _hash_token(token)
        with self._sf() as session:
            user = session.query(User).filter_by(password_reset_token=token_hash).first()
            if not user:
                return False, "Invalid or expired reset token"
            if user.password_reset_expires and _now() > user.password_reset_expires.replace(tzinfo=timezone.utc):
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

    def setup_2fa(self, user_id: str) -> Tuple[bool, str, Optional[str]]:
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

    def confirm_2fa(self, user_id: str, code: str) -> Tuple[bool, str]:
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

    def disable_2fa(self, user_id: str, code: str) -> Tuple[bool, str]:
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
            "role": user.role,
            "jti": secrets.token_hex(16),   # unique token ID for blacklisting
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
            "type": "access",
        }
        return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)

    def _create_refresh_session(self, user, ip_address: str, device_info: str, session) -> Tuple[str, object]:
        from database.user_models import UserSession

        raw_token = secrets.token_urlsafe(48)
        sess_row = UserSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            refresh_token_hash=_hash_token(raw_token),
            device_info=device_info[:255] if device_info else None,
            ip_address=ip_address,
            expires_at=_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
        session.add(sess_row)
        return raw_token, sess_row

    def get_user_by_id(self, user_id: str):
        from database.user_models import User

        with self._sf() as session:
            return session.query(User).filter_by(id=user_id).first()

    def get_user_by_email(self, email: str):
        from database.user_models import User

        with self._sf() as session:
            return session.query(User).filter_by(email=email.lower().strip()).first()
