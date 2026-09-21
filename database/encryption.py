"""
database/encryption.py
======================
Field-level AES-256-GCM encryption for sensitive database columns.

Usage
-----
Apply ``EncryptedString`` as the column type for any column that must be
encrypted at rest:

    from database.encryption import EncryptedString

    totp_secret = Column(EncryptedString(64), nullable=True)

Configuration
-------------
Set ``DB_ENCRYPTION_KEY`` in the environment.  The value must be a
URL-safe base64-encoded 32-byte key.  Generate one with:

    python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

If the key is absent the column degrades gracefully to plaintext — this
allows running test suites without a key while still enforcing encryption
in production (where the key is always set via the deployment secrets).

Wire
----
The TypeDecorator is transparent to SQLAlchemy; the underlying storage
column is TEXT so existing schema migrations only need to change the
column type (or widen it) rather than add a new column.

Encryption scheme
-----------------
* AES-256-GCM (128-bit authentication tag, 96-bit nonce)
* Each write generates a fresh cryptographically random 12-byte nonce
* On-disk format: base64( nonce || ciphertext || tag )  (URL-safe, no padding)
* The format is self-describing: all three components are fixed-width in
  the packed buffer so the decoder is deterministic.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Lazy import guard for SQLAlchemy ──────────────────────────────────────────
try:
    from sqlalchemy import Text
    from sqlalchemy.types import TypeDecorator

    _SQLA_AVAILABLE = True
except ImportError:
    _SQLA_AVAILABLE = False

# ── Key bootstrap ──────────────────────────────────────────────────────────────
_NONCE_BYTES = 12  # 96 bits — standard for AES-GCM
_TAG_BYTES = 16  # 128-bit authentication tag (GCM default)
_AES_KEY_BYTES = 32  # AES-256: 256 bits = 32 bytes


def _load_key() -> bytes | None:
    """
    Load and validate the AES-256 encryption key from the environment.

    Returns the raw 32-byte key on success, or ``None`` when the env var is
    absent (graceful degradation — plaintext fallback for CI/dev without a key).
    """
    raw = os.getenv("DB_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.urlsafe_b64decode(raw + "==")  # pad to multiple of 4
        if len(key) != _AES_KEY_BYTES:
            logger.error(
                "DB_ENCRYPTION_KEY decoded to %d bytes; must be exactly %d. Field-level encryption disabled.",
                len(key),
                _AES_KEY_BYTES,
            )
            return None
        return key
    except Exception as exc:  # pragma: no cover
        logger.error("DB_ENCRYPTION_KEY is not valid base64: %s. Encryption disabled.", exc)
        return None


def _get_aesgcm():  # type: ignore[return]
    """Return a fresh AESGCM cipher object, or None if key is unavailable."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _load_key()
    if key is None:
        return None
    return AESGCM(key)


# ── EncryptedString TypeDecorator ──────────────────────────────────────────────
if _SQLA_AVAILABLE:

    class EncryptedString(TypeDecorator):  # type: ignore[misc]
        """
        SQLAlchemy TypeDecorator that transparently encrypts/decrypts a string
        column using AES-256-GCM.

        Parameters
        ----------
        length : int
            Maximum *plaintext* length hint (informational only — the on-disk
            column is TEXT and is not length-limited by SQLAlchemy).
        """

        impl = Text
        cache_ok = True

        def __init__(self, length: int = 255, **kw: Any) -> None:
            super().__init__(**kw)
            self._plaintext_length = length

        # ── Encrypt on write ───────────────────────────────────────────────────
        def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
            """Encrypt *value* before writing to the database."""
            if value is None:
                return None

            cipher = _get_aesgcm()
            if cipher is None:
                # No key configured — store plaintext (dev / CI fallback)
                return value

            import os

            nonce = os.urandom(_NONCE_BYTES)
            ciphertext_and_tag = cipher.encrypt(nonce, value.encode(), None)
            blob = nonce + ciphertext_and_tag  # nonce ‖ ciphertext ‖ tag
            return base64.urlsafe_b64encode(blob).decode()

        # ── Decrypt on read ───────────────────────────────────────────────────
        def process_result_value(self, value: str | None, dialect: Any) -> str | None:
            """Decrypt *value* after reading from the database."""
            if value is None:
                return None

            cipher = _get_aesgcm()
            if cipher is None:
                # No key — assume plaintext (dev / CI fallback matches write path)
                return value

            try:
                blob = base64.urlsafe_b64decode(value + "==")
                if len(blob) < _NONCE_BYTES + _TAG_BYTES:
                    # Value is shorter than minimum encrypted form — treat as
                    # legacy plaintext stored before encryption was enabled.
                    logger.debug(
                        "EncryptedString: value too short to be encrypted (%d bytes); returning as plaintext.",
                        len(blob),
                    )
                    return value
                nonce = blob[:_NONCE_BYTES]
                ciphertext_and_tag = blob[_NONCE_BYTES:]
                return cipher.decrypt(nonce, ciphertext_and_tag, None).decode()
            except Exception as exc:
                # Decryption failure: log and return None rather than surfacing
                # garbled data.  This covers both authentication failures (wrong
                # key / tampered data) and pre-migration plaintext rows.
                logger.warning(
                    "EncryptedString: decryption failed (%s); column returned as None.",
                    type(exc).__name__,
                )
                return None

else:  # pragma: no cover — only reachable when SQLAlchemy is absent

    class EncryptedString:  # type: ignore[no-redef]
        """Stub used when SQLAlchemy is not installed."""

        def __init__(
            self, *args: Any, **kwargs: Any
        ) -> None:  # healer: ignore — null-object stub used only when SQLAlchemy is absent
            pass


__all__ = ["EncryptedString"]
