# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_activation_bridge.py
====================================
Tests for monetization/activation.py — the payment → entitlement bridge.

This is the code path where money has already arrived. Every test here describes
a way the customer could pay and not get what they bought.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from monetization.activation import (
    UnknownPlanError,
    activate_paid_plan,
    resolve_plan_price_usd,
)
from monetization.pricing import SubscriptionTier
from monetization.subscription import SubscriptionStatus, subscription_manager

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _clean_subscription_manager():
    """The manager is a module-level dict — isolate tests from each other."""
    subscription_manager._subscriptions.clear()
    subscription_manager._user_subscriptions.clear()
    yield
    subscription_manager._subscriptions.clear()
    subscription_manager._user_subscriptions.clear()


class TestResolvePlanPrice:
    """The price must never come from the client."""

    @pytest.mark.parametrize(
        ("plan_id", "expected"),
        [
            ("starter", 1800.0),
            ("professional", 4500.0),
            ("enterprise", 7500.0),
            ("elite", 10000.0),
        ],
    )
    def test_returns_catalogue_price(self, plan_id, expected):
        assert resolve_plan_price_usd(plan_id) == expected

    def test_case_insensitive(self):
        assert resolve_plan_price_usd("Professional") == 4500.0

    def test_unknown_plan_rejected(self):
        with pytest.raises(UnknownPlanError):
            resolve_plan_price_usd("platinum-deluxe")

    def test_empty_plan_rejected(self):
        with pytest.raises(UnknownPlanError):
            resolve_plan_price_usd("")

    def test_free_is_not_purchasable(self):
        """Checking out the free plan would create a zero-value payment."""
        with pytest.raises(UnknownPlanError):
            resolve_plan_price_usd("free")

    def test_billing_catalogue_agrees_with_pricing_manager(self):
        """`_PLANS` and `pricing_manager` must not drift apart.

        `_PLANS` is what GET /api/billing/plans shows the customer; the pricing
        manager is what we charge. If these disagree, we quote one price and take
        another.
        """
        from api.billing import _PLANS

        for plan in _PLANS:
            price = float(plan["price_usd_monthly"])
            if price <= 0:
                continue
            assert resolve_plan_price_usd(plan["id"]) == price, (
                f"catalogue drift on {plan['id']}: /billing/plans says {price}"
            )


def _db_session_returning(user_row):
    """A stand-in session whose query(...).filter(...).first() yields `user_row`."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = user_row
    return session


class TestActivatePaidPlan:
    def test_writes_the_durable_user_plan(self):
        row = MagicMock(plan="free")
        session = _db_session_returning(row)

        with patch("monetization.activation._get_db_session", return_value=session):
            assert activate_paid_plan("u1", "professional", source="crypto", reference="PAY_1") is True

        assert row.plan == "professional"
        session.commit.assert_called_once()
        session.close.assert_called_once()

    def test_new_subscription_is_active_not_pending(self):
        """create_subscription() returns paid tiers as PENDING, and is_active()
        rejects PENDING. Without the flip the customer pays and stays gated."""
        session = _db_session_returning(MagicMock(plan="free"))

        with patch("monetization.activation._get_db_session", return_value=session):
            activate_paid_plan("u1", "elite", source="crypto", reference="PAY_2")

        sub = subscription_manager.get_user_subscription("u1")
        assert sub is not None
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.tier == SubscriptionTier.ELITE
        assert sub.is_active()

    def test_lapsed_subscription_is_renewed_not_just_reactivated(self):
        """A returning customer whose subscription expired must come back active.

        Setting status=ACTIVE without moving end_date leaves is_active() False,
        because it checks start <= now <= end. They would pay and stay gated.
        """
        stale = subscription_manager.create_subscription("u1", SubscriptionTier.STARTER)
        stale.start_date = datetime.now(UTC) - timedelta(days=90)
        stale.end_date = datetime.now(UTC) - timedelta(days=60)
        stale.status = SubscriptionStatus.EXPIRED

        session = _db_session_returning(MagicMock(plan="starter"))
        with patch("monetization.activation._get_db_session", return_value=session):
            activate_paid_plan("u1", "professional", source="flutterwave", reference="FLW-1")

        sub = subscription_manager.get_user_subscription("u1")
        assert sub.tier == SubscriptionTier.PROFESSIONAL
        assert sub.is_active(), "renewing customer is still gated after paying"

    def test_existing_subscription_is_updated_in_place(self):
        """create_subscription() overwrites _user_subscriptions unconditionally,
        orphaning the previous record. Upgrades must reuse it."""
        original = subscription_manager.create_subscription("u1", SubscriptionTier.STARTER)

        session = _db_session_returning(MagicMock(plan="starter"))
        with patch("monetization.activation._get_db_session", return_value=session):
            activate_paid_plan("u1", "enterprise", source="crypto", reference="PAY_3")

        sub = subscription_manager.get_user_subscription("u1")
        assert sub.subscription_id == original.subscription_id
        assert sub.tier == SubscriptionTier.ENTERPRISE


class TestActivationFailuresAreLoudButNotFatal:
    """The callers are webhook handlers behind idempotency guards.

    If activation raised and the handler 500'd, the provider would retry, the
    retry would be short-circuited as a duplicate, and the grant would vanish.
    """

    def test_no_database_returns_false(self, caplog):
        with patch("monetization.activation._get_db_session", return_value=None):
            assert activate_paid_plan("u1", "elite", source="crypto", reference="PAY_4") is False
        assert "PAID BUT NOT PERSISTED" in caplog.text

    def test_missing_user_row_returns_false(self, caplog):
        session = _db_session_returning(None)
        with patch("monetization.activation._get_db_session", return_value=session):
            assert activate_paid_plan("ghost", "elite", source="crypto", reference="PAY_5") is False
        assert "PAID BUT NOT ACTIVATED" in caplog.text

    def test_commit_failure_rolls_back_and_returns_false(self, caplog):
        session = _db_session_returning(MagicMock(plan="free"))
        session.commit.side_effect = RuntimeError("connection lost")

        with patch("monetization.activation._get_db_session", return_value=session):
            assert activate_paid_plan("u1", "elite", source="crypto", reference="PAY_6") is False

        session.rollback.assert_called_once()
        session.close.assert_called_once()
        assert "PAID BUT NOT PERSISTED" in caplog.text

    def test_unknown_plan_returns_false(self, caplog):
        assert activate_paid_plan("u1", "not-a-plan", source="crypto", reference="PAY_7") is False
        assert "PAID BUT NOT ACTIVATED" in caplog.text

    @pytest.mark.parametrize(("user_id", "plan_id"), [("", "elite"), ("u1", "")])
    def test_missing_identity_returns_false(self, user_id, plan_id, caplog):
        assert activate_paid_plan(user_id, plan_id, source="crypto", reference="PAY_8") is False
        assert "PAID BUT NOT ACTIVATED" in caplog.text

    def test_durable_write_survives_an_in_memory_failure(self, caplog):
        """Ordering is deliberate: the customer keeps what they paid for even if
        the in-process gating update fails."""
        row = MagicMock(plan="free")
        session = _db_session_returning(row)

        with (
            patch("monetization.activation._get_db_session", return_value=session),
            patch(
                "monetization.activation._write_subscription_manager",
                side_effect=RuntimeError("manager exploded"),
            ),
        ):
            assert activate_paid_plan("u1", "elite", source="crypto", reference="PAY_9") is True

        assert row.plan == "elite"
        assert "recovers on restart" in caplog.text
