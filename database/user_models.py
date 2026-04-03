# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
User, session, and token database models for the main app.

Uses SQLAlchemy (same ORM as the rest of database/models.py) so all tables
live in the same database and share the same Base / session factory.
"""

from __future__ import annotations

import enum
import sys
import uuid
from datetime import UTC, datetime

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, enum.Enum):
        """Backport of enum.StrEnum for Python < 3.11."""


def _utcnow() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from database.models import Base


class UserRole(StrEnum):
    USER = "user"
    TRADER = "trader"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"
    DELETED = "deleted"


class User(Base):
    """Core user account."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.TRADER.value)
    status = Column(String(30), nullable=False, default=UserStatus.PENDING_VERIFICATION.value)

    # Verification
    is_email_verified = Column(Boolean, default=False, nullable=False)
    email_verify_token = Column(String(255), nullable=True)
    email_verify_expires = Column(DateTime, nullable=True)

    # Password reset
    password_reset_token = Column(String(255), nullable=True)
    password_reset_expires = Column(DateTime, nullable=True)

    # 2FA
    totp_secret = Column(String(64), nullable=True)  # encrypted TOTP secret
    totp_enabled = Column(Boolean, default=False)

    # KYC
    kyc_status = Column(String(20), default="unverified")  # unverified/pending/approved/rejected

    # Metadata
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)

    # Relations
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    login_attempts = relationship("LoginAttempt", back_populates="user", cascade="all, delete-orphan")
    accounts = relationship("Account", back_populates="user", lazy="dynamic")

    __table_args__ = (
        # email uniqueness enforced by Column(unique=True) — no separate index needed
        Index("idx_users_username", "username"),
        Index("idx_users_status", "status"),
    )

    def __repr__(self):
        return f"<User id={self.id} email={self.email} role={self.role}>"


class UserSession(Base):
    """
    Refresh token store — one row per active session.
    Deleting a row revokes that session immediately.
    """

    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    refresh_token_hash = Column(String(64), unique=True, nullable=False)  # SHA-256 of raw token
    device_info = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    is_revoked = Column(Boolean, default=False)

    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_token_hash", "refresh_token_hash"),
    )


class LoginAttempt(Base):
    """Tracks failed login attempts for brute-force protection."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    ip_address = Column(String(45), nullable=False, index=True)
    success = Column(Boolean, default=False)
    failure_reason = Column(String(100), nullable=True)
    attempted_at = Column(DateTime, default=_utcnow, index=True)

    user = relationship("User", back_populates="login_attempts")

    __table_args__ = (
        Index("idx_login_ip_time", "ip_address", "attempted_at"),
        Index("idx_login_email_time", "email", "attempted_at"),
    )
