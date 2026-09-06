"""The Stripe webhook handlers claimed actions they never performed.

`monetization/stripe_integration.py`'s `handle_webhook` dispatched every event
to a handler that logged one line and returned a success claim:

    def _handle_subscription_deleted(self, data):
        logger.info("Subscription deleted: %s", data.get("id"))
        return {"status": "success", "action": "access_revoked"}

Measured, on the live path (`api/monetization.py` calls this singleton after
verifying the signature):

    customer.subscription.deleted  -> {'status': 'success', 'action': 'access_revoked'}
    checkout.session.completed     -> {'status': 'success', 'action': 'subscription_activated'}
    customer.subscription.created  -> {'status': 'success', 'action': 'access_granted'}
    invoice.paid                   -> {'status': 'success', 'action': 'invoice_confirmed'}

Nothing was revoked, activated, granted or confirmed. This audit's signature
defect — success reported for work that did not happen — on the path that
decides who keeps paid access. **A cancelled subscription reported
`access_revoked` and the customer kept access indefinitely**, and the endpoint
then returned `{"received": true}` so Stripe marked the webhook delivered and
never retried.

A correct implementation already existed in
`monetization/subscription.py::handle_stripe_webhook` — activate, cancel,
suspend, all real. Two handlers for the same events, one of them decorative, is
the root of it. These now delegate to that one, and an event with no
implementation says so instead of claiming success.
"""

from __future__ import annotations

import sys

import pytest


def _module(name: str):
    __import__(name)
    return sys.modules[name]


_SI = _module("monetization.stripe_integration")
_SUB = _module("monetization.subscription")

SubscriptionStatus = _SUB.SubscriptionStatus
SubscriptionTier = _SUB.SubscriptionTier


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch):
    """A clean SubscriptionManager, wired in where the handlers look for it."""
    fresh = _SUB.SubscriptionManager()
    monkeypatch.setattr(_SUB, "subscription_manager", fresh)
    return fresh


@pytest.fixture
def integration():
    return _SI.StripeIntegration()


def _subscribed(manager, user_id: str = "u-1"):
    sub = manager.create_subscription(
        user_id=user_id,
        tier=SubscriptionTier.PROFESSIONAL,
        stripe_subscription_id="sub_stripe_1",
        stripe_customer_id="cus_stripe_1",
    )
    sub.status = SubscriptionStatus.ACTIVE
    return sub


# ── the handlers do the work they claim ──────────────────────────────────────


def test_a_cancelled_subscription_is_actually_revoked(manager, integration) -> None:
    """The expensive one: the customer kept paid access after cancelling."""
    sub = _subscribed(manager)

    result = integration.handle_webhook(
        "customer.subscription.deleted", {"id": "sub_stripe_1", "customer": "cus_stripe_1"}
    )

    assert sub.status is SubscriptionStatus.CANCELLED, "access was not revoked"
    assert result["status"] == "success"


def test_a_failed_invoice_actually_suspends(manager, integration) -> None:
    sub = _subscribed(manager)

    integration.handle_webhook("invoice.payment_failed", {"id": "in_1", "customer": "cus_stripe_1"})

    assert sub.status is SubscriptionStatus.SUSPENDED


def test_a_completed_checkout_actually_activates(manager, integration) -> None:
    integration.handle_webhook(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "subscription": "sub_stripe_9",
            "customer": "cus_stripe_9",
            "metadata": {"user_id": "u-new", "tier": "professional"},
        },
    )

    sub = manager.get_user_subscription("u-new")
    assert sub is not None, "checkout completed and no subscription exists"
    assert sub.status is SubscriptionStatus.ACTIVE
    assert sub.stripe_subscription_id == "sub_stripe_9"


# ── an action that did not happen is never reported as success ───────────────


def test_an_unmatched_cancellation_does_not_claim_success(manager, integration) -> None:
    """No subscription carries that Stripe id, so nothing was revoked.

    Reporting success here is how the original defect stayed invisible: the
    endpoint returns 200, Stripe marks the webhook delivered, and nobody
    ever learns the account was not touched.
    """
    _subscribed(manager)

    result = integration.handle_webhook("customer.subscription.deleted", {"id": "sub_does_not_exist"})

    assert result["status"] != "success"
    assert "no_matching_subscription" in str(result).lower() or "not_found" in str(result).lower()


def test_an_unmatched_failed_invoice_does_not_claim_success(manager, integration) -> None:
    _subscribed(manager)

    result = integration.handle_webhook("invoice.payment_failed", {"id": "in_1", "customer": "cus_nope"})

    assert result["status"] != "success"


def test_a_checkout_without_a_user_id_is_refused(manager, integration) -> None:
    """Activating a subscription for nobody is worse than refusing."""
    result = integration.handle_webhook("checkout.session.completed", {"id": "cs_1", "metadata": {}})

    assert result["status"] != "success"
    assert manager.get_user_subscription("") is None


# ── events with no implementation say so ─────────────────────────────────────


@pytest.mark.parametrize(
    "event_type",
    ["customer.subscription.created", "customer.subscription.updated", "invoice.paid", "payment_intent.succeeded"],
)
def test_an_unimplemented_event_does_not_claim_an_action(integration, event_type: str) -> None:
    """`access_granted` and `invoice_confirmed` were claims about nothing.

    Acknowledged is honest — Stripe needs a 200 so it stops retrying, and the
    subscription lifecycle is driven by checkout/deleted/payment_failed. What is
    not honest is naming an action that no code performs.
    """
    result = integration.handle_webhook(event_type, {"id": "evt_1"})

    claimed = str(result.get("action", "")).lower()
    for lie in ("access_granted", "access_revoked", "invoice_confirmed", "subscription_activated"):
        assert lie not in claimed, f"{event_type} still claims {lie}"


def test_an_unknown_event_is_ignored_not_claimed(integration) -> None:
    result = integration.handle_webhook("some.event.we.do.not.handle", {"id": "evt_2"})

    assert result["status"] == "ignored"


# ── Stripe retries; the handlers must be idempotent ──────────────────────────


def test_a_replayed_cancellation_is_harmless(manager, integration) -> None:
    """Stripe retries delivery. Re-cancelling a cancelled subscription is fine;
    what must not happen is a second, different side effect."""
    sub = _subscribed(manager)

    first = integration.handle_webhook("customer.subscription.deleted", {"id": "sub_stripe_1"})
    second = integration.handle_webhook("customer.subscription.deleted", {"id": "sub_stripe_1"})

    assert sub.status is SubscriptionStatus.CANCELLED
    assert first["status"] == "success"
    assert second["status"] in {"success", "duplicate"}


def test_a_replayed_checkout_does_not_create_a_second_subscription(manager, integration) -> None:
    payload = {
        "id": "cs_1",
        "subscription": "sub_stripe_9",
        "customer": "cus_stripe_9",
        "metadata": {"user_id": "u-new", "tier": "professional"},
    }

    integration.handle_webhook("checkout.session.completed", payload)
    integration.handle_webhook("checkout.session.completed", payload)

    owned = [s for s in manager._subscriptions.values() if s.user_id == "u-new"]
    assert len(owned) == 1, f"a replayed checkout created {len(owned)} subscriptions"
