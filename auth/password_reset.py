# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
auth/password_reset.py
======================
The one place a password reset is issued.

Two callers need this: the anonymous ``POST /auth/forgot-password`` and the
authenticated ``POST /admin/users/{user_id}/reset-password``. They differ in
who asks and in what they may say back — not in how the token is made.

The sequence was previously inline in ``auth/router.py::forgot_password``,
which is why the admin endpoint tried to invent its own and instead invented
nothing at all: it imported an ``email_service`` object that
``core/email_service.py`` does not define, swallowed the ImportError, and
answered ``{"ok": true, "message": "Password reset email queued"}`` to every
call. Nothing was ever queued.

Duplicating the sequence would have meant a second expiry policy, a second
hashing choice and a second salt on the highest-blast-radius endpoint in the
admin panel. Hence one function.

What it guarantees, and why each part matters:

* The raw token exists only between ``request_password_reset`` and the signing
  call. Only its SHA hash reaches the database, and only the *signed* form
  reaches the user, so a leaked database row cannot be redeemed.
* The signed token is returned to the caller for one reason — the test-mode
  ``_dev_reset_token`` that ``/auth/forgot-password`` already exposed under
  ``APP_ENV=test``. **No production response may include it.** An admin who can
  read a user's reset token can complete the reset and take the account, which
  is precisely the authority an admin is not supposed to have here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _request_reset(email: str):
    """Mint and store the reset token. Indirected so tests can substitute it."""
    from auth.router import _svc

    return _svc().request_password_reset(email)


def _send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    from core.email_service import send_password_reset_email

    return send_password_reset_email(to_email, username, token)


def _sign(raw_token: str, email: str) -> str:
    from auth.router import _PASSWORD_RESET_TTL, _SALT_PASSWORD_RESET, _make_signed_token

    return _make_signed_token(
        {"tok": raw_token, "email": email},
        salt=_SALT_PASSWORD_RESET,
        max_age_seconds=_PASSWORD_RESET_TTL,
    )


def _username_for(email: str) -> str:
    try:
        from auth.router import _svc

        user = _svc().get_user_by_email(email)
        if user is not None and getattr(user, "username", None):
            return user.username
    except Exception as exc:
        logger.debug("password reset: username lookup failed for %s: %s", email, exc)
    return email


def send_password_reset_for_email(email: str) -> str | None:
    """Issue a password reset for *email* and mail the link.

    Returns the **signed** token on success, or ``None`` when the address is
    not registered. Callers must not put the return value in a production
    response; it exists for the ``APP_ENV=test`` affordance that
    ``/auth/forgot-password`` already had.

    Raises nothing for an unknown address — that is a normal outcome, and the
    anonymous caller must not be able to tell it apart from success. A failure
    to *send* does propagate, so an authenticated admin can be told the mail
    did not go out rather than being shown a false confirmation.
    """
    _ok, _msg, raw_token = _request_reset(email)
    if not raw_token:
        return None

    signed = _sign(raw_token, email)
    _send_password_reset_email(email, _username_for(email), signed)
    return signed
