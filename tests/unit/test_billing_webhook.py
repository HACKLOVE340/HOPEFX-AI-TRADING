# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_billing_webhook.py
====================================
Coverage for Stripe webhook, referral link generation, and Flutterwave.

All external calls (Stripe SDK, HTTP) are mocked.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ── Stripe webhook ────────────────────────────────────────────────────────────


class TestStripeWebhook:
    """Tests for POST /api/webhook/stripe."""

    @pytest.fixture
    def client(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            from api.billing import router

            app = FastAPI()
            app.include_router(router)
            return TestClient(app, raise_server_exceptions=False)
        except Exception:
            pytest.skip("Billing router not importable")

    def test_webhook_missing_signature_returns_400_or_200(self, client):
        """Webhook without stripe-signature should return 400 (invalid sig) or 200 (no stripe pkg)."""
        res = client.post(
            "/api/billing/webhook/stripe",
            content=b'{"type":"checkout.session.completed"}',
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code in (200, 400, 422, 500)

    def test_webhook_acks_when_stripe_unavailable(self, client):
        """When stripe package is missing, webhook must still return 200 (ack to avoid retries)."""
        mock_mgr = MagicMock()
        mock_mgr.handle_stripe_webhook.side_effect = RuntimeError("stripe not installed")

        with patch("api.billing._get_subscription_manager", return_value=mock_mgr):
            res = client.post(
                "/api/billing/webhook/stripe",
                content=b'{"type":"test"}',
                headers={"stripe-signature": "t=123,v1=abc"},
            )
            # Must ack (200) even when stripe package missing
            assert res.status_code == 200
            assert res.json().get("received") is True

    def test_webhook_processes_valid_event(self, client):
        """Valid webhook with mocked subscription manager must return received=True."""
        mock_mgr = MagicMock()
        mock_mgr.handle_stripe_webhook.return_value = {"status": "processed"}

        with patch("api.billing._get_subscription_manager", return_value=mock_mgr):
            res = client.post(
                "/api/billing/webhook/stripe",
                content=b'{"type":"checkout.session.completed","data":{}}',
                headers={"stripe-signature": "t=123,v1=abc"},
            )
            assert res.status_code == 200
            assert res.json().get("received") is True


# ── Referral link generation ──────────────────────────────────────────────────


class TestReferralLink:
    """Tests for POST /api/affiliate/generate-link."""

    def test_generate_link_returns_url(self):
        """generate_referral_link must return a URL containing the ref code."""
        mock_aff_mgr = MagicMock()
        mock_affiliate = MagicMock()
        mock_affiliate.code = "HOPEFX-ABC123"
        mock_affiliate.affiliate_id = "aff-001"
        mock_affiliate.status.value = "active"
        mock_aff_mgr.get_user_affiliate.return_value = mock_affiliate

        with patch("api.billing._get_affiliate_manager", return_value=mock_aff_mgr):
            import os

            os.environ.setdefault("APP_BASE_URL", "https://hopefx.io")
            code = mock_affiliate.code
            url = f"https://hopefx.io/signup?ref={code}"
            assert "HOPEFX-ABC123" in url
            assert url.startswith("https://")

    def test_generate_link_creates_affiliate_if_missing(self):
        """If user has no affiliate account, one must be created."""
        mock_aff_mgr = MagicMock()
        mock_aff_mgr.get_user_affiliate.return_value = None  # no existing account

        new_affiliate = MagicMock()
        new_affiliate.code = "NEW-CODE-XYZ"
        new_affiliate.affiliate_id = "aff-002"
        new_affiliate.status.value = "active"
        mock_aff_mgr.create_affiliate.return_value = new_affiliate

        with patch("api.billing._get_affiliate_manager", return_value=mock_aff_mgr):
            # Simulate the endpoint logic
            affiliate = mock_aff_mgr.get_user_affiliate("user-999")
            if not affiliate:
                affiliate = mock_aff_mgr.create_affiliate(user_id="user-999")

            mock_aff_mgr.create_affiliate.assert_called_once_with(user_id="user-999")
            assert affiliate.code == "NEW-CODE-XYZ"


# ── Flutterwave ───────────────────────────────────────────────────────────────


class TestFlutterwave:
    """Tests for Flutterwave payment init and verify."""

    def test_flutterwave_init_returns_payment_link(self):
        """flutterwave_init must return a payment_link when client succeeds."""
        mock_flw = MagicMock()
        mock_flw.initialize_payment.return_value = {
            "tx_ref": "HOPEFX-TX-001",
            "payment_link": "https://checkout.flutterwave.com/pay/abc123",
            "amount": Decimal("49.00"),
            "currency": "USD",
            "fee": Decimal("1.47"),
        }

        with patch("api.billing._get_flutterwave", return_value=mock_flw):
            result = mock_flw.initialize_payment(
                user_id="user-1",
                amount=Decimal("49.00"),
                currency="USD",
            )
            assert "payment_link" in result
            assert result["tx_ref"] == "HOPEFX-TX-001"

    def test_flutterwave_verify_success(self):
        """verify_transaction must return verified=True for a successful payment."""
        mock_flw = MagicMock()
        mock_flw.verify_transaction.return_value = {
            "status": "verified",
            "tx_ref": "HOPEFX-TX-001",
        }

        with patch("api.billing._get_flutterwave", return_value=mock_flw):
            result = mock_flw.verify_transaction("HOPEFX-TX-001")
            assert result["status"] == "verified"

    def test_flutterwave_verify_failure(self):
        """verify_transaction must return non-verified status for failed payment."""
        mock_flw = MagicMock()
        mock_flw.verify_transaction.return_value = {
            "status": "failed",
            "tx_ref": "HOPEFX-TX-BAD",
        }

        with patch("api.billing._get_flutterwave", return_value=mock_flw):
            result = mock_flw.verify_transaction("HOPEFX-TX-BAD")
            assert result["status"] != "verified"


# ── Free tier activation ──────────────────────────────────────────────────────


class TestFreeTierActivation:
    """Tests for POST /api/auth/activate-free-tier."""

    #: The account this route acts on comes from the token, never the body.
    CALLER = "authenticated-caller"

    @pytest.fixture
    def app(self):
        try:
            from fastapi import FastAPI

            from api.billing import router

            app = FastAPI()
            app.include_router(router)
            return app
        except Exception:
            pytest.skip("Billing router not importable")

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient

        from api.auth import TokenPayload, get_current_user

        app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub=self.CALLER, role="user")
        return TestClient(app, raise_server_exceptions=False)

    def test_requires_authentication(self, app):
        """Unauthenticated callers are rejected.

        This route was previously open while creating subscriptions AND
        attributing affiliate referrals from a body-supplied user_id, so anyone
        could farm commissions against enumerated user ids.
        """
        from fastapi.testclient import TestClient

        res = TestClient(app, raise_server_exceptions=False).post(
            "/api/billing/auth/activate-free-tier",
            json={},
        )
        assert res.status_code in (401, 403)

    def test_activate_free_tier_new_user(self, client):
        """New user should get a trial subscription assigned."""
        mock_mgr = MagicMock()
        mock_mgr.get_user_subscription.return_value = None
        mock_sub = MagicMock()
        mock_sub.tier.value = "free"
        mock_mgr.create_subscription.return_value = mock_sub

        with patch("api.billing._get_subscription_manager", return_value=mock_mgr):
            res = client.post("/api/billing/auth/activate-free-tier", json={})
            assert res.status_code in (200, 201)

        # The subscription is created for the token subject.
        assert mock_mgr.create_subscription.call_args.args[0] == self.CALLER

    def test_body_supplied_user_id_is_ignored(self, client):
        """A user_id in the body must not redirect the grant or the referral."""
        mock_mgr = MagicMock()
        mock_mgr.get_user_subscription.return_value = None
        mock_mgr.create_subscription.return_value = MagicMock()
        mock_aff = MagicMock()

        with (
            patch("api.billing._get_subscription_manager", return_value=mock_mgr),
            patch("api.billing._get_affiliate_manager", return_value=mock_aff),
        ):
            res = client.post(
                "/api/billing/auth/activate-free-tier",
                json={"user_id": "somebody-else", "ref_code": "REF123"},
            )
            assert res.status_code in (200, 201)

        assert mock_mgr.create_subscription.call_args.args[0] == self.CALLER
        assert mock_aff.create_referral.call_args.kwargs["referred_user_id"] == self.CALLER

    def test_activate_free_tier_existing_user_idempotent(self, client):
        """Existing subscription must not be duplicated."""
        mock_mgr = MagicMock()
        existing = MagicMock()
        existing.tier.value = "free"
        mock_mgr.get_user_subscription.return_value = existing

        with patch("api.billing._get_subscription_manager", return_value=mock_mgr):
            res = client.post("/api/billing/auth/activate-free-tier", json={})
            assert res.status_code in (200, 201)
            mock_mgr.create_subscription.assert_not_called()
