# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_admin_password_reset.py
=======================================
`POST /admin/users/{user_id}/reset-password` always answered

    {"ok": true, "message": "Password reset email queued"}

and never queued anything. An admin helping a locked-out user got a green
response; the user got no email and stayed locked out.

Two independent reasons, either alone sufficient:

1. **The import does not resolve.** The handler did
   `from core.email_service import email_service` and called
   `email_service.send_password_reset(email)`. `core/email_service.py` is a
   module of functions — `_send`, `send_verification_email`,
   `send_password_reset_email`, `send_login_alert`. There is no
   `email_service` object and no `send_password_reset` method. ImportError,
   caught by the handler's own `except Exception`, logged at WARNING.

2. **The email lookup reads a store that never holds emails.** It read
   `db_get(f"user:{user_id}")`. Grepping every writer of that namespace finds
   only `ban_user`, `suspend_user` and `unban_user` in this same file, which
   write `{"user_id": ..., "status": ..., "ban_reason": ...}`. No writer ever
   puts an `email` in it. So `u.get("email", "")` was `""` for every user who
   has ever existed, and the `if email:` guard skipped the send even in the
   world where the import worked. The real user record is the SQL `User` row —
   what `auth/service.py` and this file's own KYC handler use.

`/admin/settings/test-smtp` had the same dead-import problem with
`get_email_service()`, so SMTP could never be verified from the admin panel.

**The open question this closes: may an admin mint a reset token?**

No, and it does not need to. `auth/service.py::request_password_reset` already
mints one — `secrets.token_urlsafe(32)`, stored as a hash with a one-hour
expiry — and `auth/router.py::forgot_password` signs it with
`_SALT_PASSWORD_RESET` and mails it. A second minting path would mean a second
expiry policy, a second hashing choice and a second thing to get wrong, on the
endpoint with the highest blast radius in the admin panel.

So the admin endpoint triggers the *existing* flow. The consequences are the
point: the token goes to the user's registered address and never appears in the
admin's response, so an admin cannot read it, replay it, or take over an
account. The admin causes a reset; they do not perform one.

Enumeration safety differs deliberately. `/auth/forgot-password` is anonymous
and must not reveal whether an address is registered. This endpoint is behind
`require_role("admin")` and the caller supplies a `user_id` they already
administer, so "that user does not exist" is useful to them and reveals nothing
they could not already read from the user list.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestTheDeadImports:
    def test_core_email_service_has_no_email_service_object(self):
        import core.email_service as svc

        assert not hasattr(svc, "email_service")
        assert not hasattr(svc, "get_email_service")

    def test_core_email_service_does_have_the_real_sender(self):
        import core.email_service as svc

        assert callable(svc.send_password_reset_email)
        assert callable(svc._send)

    def test_admin_no_longer_imports_the_names_that_do_not_exist(self):
        from pathlib import Path

        src = Path("api/admin.py").read_text()
        assert "import email_service" not in src, (
            "core.email_service exports no `email_service` object; the import "
            "raises into the handler's own except and the reset is silently dropped"
        )
        assert "get_email_service" not in src


class TestTheAdminDoesNotMintTokens:
    def test_admin_py_contains_no_token_minting(self):
        """One minting path, in auth/service.py. Not two."""
        from pathlib import Path

        src = Path("api/admin.py").read_text()
        assert "token_urlsafe" not in src
        assert "password_reset_token" not in src, (
            "the reset token is minted and hashed by auth/service.py; api/admin.py "
            "must trigger that flow, not implement a second one"
        )

    def test_the_shared_helper_is_what_both_callers_use(self):
        from auth.password_reset import send_password_reset_for_email

        assert callable(send_password_reset_for_email)

    def test_forgot_password_uses_the_same_helper(self):
        """Otherwise the two paths drift on expiry, salt, or hashing."""
        import inspect

        from auth.router import forgot_password

        assert "send_password_reset_for_email" in inspect.getsource(forgot_password)


class TestTheHelperDrivesTheRealFlow:
    def test_it_returns_none_for_an_unknown_address(self, monkeypatch):
        """request_password_reset yields no token for an address it does not know."""
        from auth import password_reset as pr

        monkeypatch.setattr(pr, "_request_reset", lambda email: (True, "If that email is registered…", None))
        sender = MagicMock()
        monkeypatch.setattr(pr, "_send_password_reset_email", sender)

        assert pr.send_password_reset_for_email("nobody@example.invalid") is None
        sender.assert_not_called()

    def test_it_signs_the_token_before_mailing_it(self, monkeypatch):
        """The raw DB token must go through the signer, which carries the expiry.

        The signed value is not asserted to *differ* from the raw one: when
        itsdangerous is absent, `_make_signed_token` documents that it returns
        the raw `tok` — already a `secrets.token_urlsafe(32)` verified by SHA-256
        hash — so a difference check would pass or fail on which packages happen
        to be installed rather than on this module's behaviour. What must hold
        either way is that the signer is the thing producing what gets mailed.
        """
        from auth import password_reset as pr

        raw = "raw-token-value"
        monkeypatch.setattr(pr, "_request_reset", lambda email: (True, "ok", raw))
        signer = MagicMock(return_value="signed-envelope")
        monkeypatch.setattr(pr, "_sign", signer)
        sent: dict = {}
        monkeypatch.setattr(
            pr, "_send_password_reset_email", lambda to, user, tok: sent.update(to=to, token=tok) or True
        )

        token = pr.send_password_reset_for_email("trader@hopefx.io")

        signer.assert_called_once_with(raw, "trader@hopefx.io")
        assert token == "signed-envelope"
        assert sent["token"] == "signed-envelope", "the mailed link must carry the signed token, not the DB one"
        assert sent["to"] == "trader@hopefx.io"


class TestTheEndpoint:
    def _call(self, user_id: str):
        import asyncio
        from types import SimpleNamespace

        from api.admin import reset_user_password

        return asyncio.run(reset_user_password(user_id, user=SimpleNamespace(sub="admin-1", email="admin@hopefx.io")))

    def test_an_unknown_user_is_not_reported_as_queued(self):
        """The blanket ok:true was the whole defect."""
        with patch("auth.password_reset.send_password_reset_for_email", return_value=None):
            result = self._call(f"missing-{uuid.uuid4().hex}")

        assert result["ok"] is False
        assert "queued" not in str(result.get("message", "")).lower()

    def test_a_known_user_triggers_the_real_send(self):
        with (
            patch("api.admin._lookup_user_email", return_value="trader@hopefx.io"),
            patch("auth.password_reset.send_password_reset_for_email", return_value="signed.tok.en") as helper,
        ):
            result = self._call("user-42")

        assert result["ok"] is True
        helper.assert_called_once_with("trader@hopefx.io")

    def test_the_response_never_carries_the_token(self):
        """An admin must not be able to read the token and take the account."""
        with (
            patch("api.admin._lookup_user_email", return_value="trader@hopefx.io"),
            patch("auth.password_reset.send_password_reset_for_email", return_value="signed.tok.en"),
        ):
            result = self._call("user-42")

        assert "signed.tok.en" not in str(result), (
            "the reset token must reach the user's inbox and nowhere else; an admin "
            "who can read it can complete the reset themselves"
        )

    def test_a_send_failure_is_reported_rather_than_swallowed(self):
        with (
            patch("api.admin._lookup_user_email", return_value="trader@hopefx.io"),
            patch("auth.password_reset.send_password_reset_for_email", side_effect=RuntimeError("smtp down")),
        ):
            result = self._call("user-42")

        assert result["ok"] is False


class TestSmtpTest:
    def _call(self, payload=None):
        import asyncio
        from types import SimpleNamespace

        from api.admin import test_smtp

        return asyncio.run(
            test_smtp(payload or {"email": "admin@hopefx.io"}, user=SimpleNamespace(sub="admin@hopefx.io"))
        )

    def test_it_uses_the_real_sender(self):
        import inspect

        from api.admin import test_smtp

        src = inspect.getsource(test_smtp)
        assert "get_email_service" not in src
        assert "_send" in src

    def test_an_unconfigured_transport_is_not_reported_as_working(self):
        """The defect this endpoint exists to detect.

        `_send` returns True with no transport configured — it logs the message
        instead. Right for a signup email in dev; useless here, where the whole
        question is whether mail is configured at all.
        """
        with patch("core.email_service.active_transport", return_value=None):
            result = self._call()

        assert result["ok"] is False
        assert "transport" in result["error"].lower()

    def test_a_configured_transport_that_accepts_reports_success(self):
        with (
            patch("core.email_service.active_transport", return_value="smtp"),
            patch("core.email_service._send", return_value=True),
        ):
            result = self._call()

        assert result["ok"] is True
        assert result["transport"] == "smtp"

    def test_a_configured_transport_that_refuses_reports_failure(self):
        with (
            patch("core.email_service.active_transport", return_value="smtp"),
            patch("core.email_service._send", return_value=False),
        ):
            result = self._call()

        assert result["ok"] is False


class TestTheTransportProbe:
    def test_it_reports_none_when_nothing_is_configured(self, monkeypatch):
        import core.email_service as svc

        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.setattr(svc, "_smtp_config", lambda: None)

        assert svc.active_transport() is None

    def test_sendgrid_wins_over_smtp_exactly_as_send_orders_them(self, monkeypatch):
        """Drift between the probe and _send would make the probe a lie."""
        import core.email_service as svc

        monkeypatch.setenv("SENDGRID_API_KEY", "sg-fixture-key")
        monkeypatch.setattr(svc, "_smtp_config", lambda: {"host": "mail.example.test"})

        assert svc.active_transport() == "sendgrid"

    def test_smtp_is_reported_when_only_smtp_is_configured(self, monkeypatch):
        import core.email_service as svc

        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.setattr(svc, "_smtp_config", lambda: {"host": "mail.example.test"})

        assert svc.active_transport() == "smtp"
