# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_monetization_ownership.py
=========================================
Regression tests for the authorisation half of api/monetization.py.

Every route in that module authenticated, and several then acted on an identity
taken from the request body or the URL path rather than the token — which
authenticates the caller and authorises nobody. These tests pin the fixes so the
body-supplied identity cannot come back.

The removed fields are asserted individually rather than as a list: when one of
them reappears, the failing test names it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.auth import TokenPayload
from api.monetization import (
    ActivateCodeRequest,
    AffiliateSignupRequest,
    ManualReviewRequest,
    ReferralRequest,
    RegisterStripeAccountRequest,
    ReviewRequest,
    StrategyListRequest,
    StrategyPurchaseRequest,
    SubmitStrategyRequest,
    SubscribeRequest,
    _assert_affiliate_owner,
    _assert_self_or_operator,
)


def _user(sub: str = "victim-or-caller", role: str = "user") -> TokenPayload:
    return TokenPayload(sub=sub, role=role)


class TestIdentityFieldsAreGone:
    """A caller must not be able to name the account an action applies to.

    Pydantic ignores unknown fields, so an old client that still sends these
    keeps working — the value is simply dropped instead of trusted.
    """

    def test_subscribe_request_has_no_user_id(self):
        assert "user_id" not in SubscribeRequest.model_fields
        # Still accepted on the wire, just ignored — no 422 for stale clients.
        assert not hasattr(SubscribeRequest(tier="starter", user_id="someone-else"), "user_id")

    def test_activate_code_request_has_no_user_id(self):
        assert "user_id" not in ActivateCodeRequest.model_fields

    def test_affiliate_signup_request_has_no_user_id(self):
        assert "user_id" not in AffiliateSignupRequest.model_fields

    def test_referral_request_has_no_referred_user_id(self):
        assert "referred_user_id" not in ReferralRequest.model_fields

    def test_strategy_list_request_has_no_creator_id(self):
        assert "creator_id" not in StrategyListRequest.model_fields

    def test_strategy_purchase_request_has_no_buyer_id(self):
        assert "buyer_id" not in StrategyPurchaseRequest.model_fields

    def test_review_request_has_no_user_id(self):
        assert "user_id" not in ReviewRequest.model_fields

    def test_submit_strategy_request_has_no_creator_id(self):
        assert "creator_id" not in SubmitStrategyRequest.model_fields

    def test_register_stripe_account_request_has_no_creator_id(self):
        assert "creator_id" not in RegisterStripeAccountRequest.model_fields

    def test_manual_review_request_has_no_reviewer_id(self):
        assert "reviewer_id" not in ManualReviewRequest.model_fields


class TestSelfOrOperatorGuard:
    def test_own_records_allowed(self):
        _assert_self_or_operator("u1", _user("u1"))

    def test_other_users_records_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _assert_self_or_operator("u2", _user("u1"))
        # 404, not 403 — a 403 would confirm the id exists.
        assert exc.value.status_code == 404

    @pytest.mark.parametrize("role", ["admin", "superadmin"])
    def test_staff_may_read_across_accounts(self, role):
        _assert_self_or_operator("u2", _user("u1", role=role))

    def test_trader_is_not_an_operator(self):
        """`trader` outranks `user` but is still a customer, not staff."""
        with pytest.raises(HTTPException):
            _assert_self_or_operator("u2", _user("u1", role="trader"))


class TestAffiliateOwnerGuard:
    def test_owner_allowed(self):
        affiliate = MagicMock(user_id="u1")
        with patch("api.monetization.affiliate_manager.get_affiliate", return_value=affiliate):
            _assert_affiliate_owner("aff1", _user("u1"))

    def test_non_owner_rejected(self):
        affiliate = MagicMock(user_id="someone-else")
        with patch("api.monetization.affiliate_manager.get_affiliate", return_value=affiliate):
            with pytest.raises(HTTPException) as exc:
                _assert_affiliate_owner("aff1", _user("u1"))
        assert exc.value.status_code == 404

    def test_unknown_affiliate_rejected(self):
        with patch("api.monetization.affiliate_manager.get_affiliate", return_value=None):
            with pytest.raises(HTTPException):
                _assert_affiliate_owner("nope", _user("u1"))

    def test_staff_bypass_does_not_hit_the_manager(self):
        with patch("api.monetization.affiliate_manager.get_affiliate") as get:
            _assert_affiliate_owner("aff1", _user("u1", role="admin"))
            get.assert_not_called()


class TestPurchaseUsesTheAuthenticatedBuyer:
    @pytest.mark.asyncio
    async def test_buyer_is_the_token_subject(self):
        from api.monetization import purchase_strategy

        strategy = MagicMock(price=99.0, price_monthly=None)
        purchase = MagicMock(purchase_id="p1")
        intent = MagicMock(intent_id="pi_1", client_secret="secret")

        with (
            patch("api.monetization.strategy_marketplace.get_strategy", return_value=strategy),
            patch("api.monetization.strategy_marketplace.purchase_strategy", return_value=purchase) as do_purchase,
            patch("api.monetization.stripe_integration.create_payment_intent", return_value=intent) as create_intent,
        ):
            await purchase_strategy(
                StrategyPurchaseRequest(strategy_id="s1"),
                user=_user("real-caller"),
            )

        assert do_purchase.call_args.kwargs["buyer_id"] == "real-caller"
        # The Stripe metadata is the audit trail — it must name the same buyer.
        assert create_intent.call_args.kwargs["metadata"]["buyer_id"] == "real-caller"


class TestRecordSaleIsOperatorOnly:
    def test_route_requires_admin(self):
        """`record_sale` credits an arbitrary creator an arbitrary amount.

        It is an accounting entry point, so it must not be reachable by an
        ordinary authenticated customer.
        """
        import api.monetization as mon

        route = next(r for r in mon.router.routes if getattr(r, "path", "") == "/api/monetization/marketplace/sales")
        # require_role("admin") wraps get_current_user, so the plain dependency
        # must not be what guards this route.
        dependency_names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies if d.call is not None}
        assert "get_current_user" not in dependency_names
