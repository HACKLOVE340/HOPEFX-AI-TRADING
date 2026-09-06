"""F222 (TODO item 5) — `monetization/payment_processor.py` moved money untested.

628 lines, named by no test file in the repository, and it is the platform's
revenue path: it creates Stripe PaymentIntents, activates subscriptions, marks
invoices paid, issues refunds and runs dunning.

Writing the first test found two defects, both reproduced by execution before
being fixed.

**A payment that was never charged was reported as succeeded.**
`create_stripe_payment_intent` returns `None` on a `StripeError` — a declined
card, a rate limit, an outage. `process_payment` guarded the assignment with
`if intent_id:` and then fell straight through to `mark_succeeded()`,
`mark_invoice_paid()` and `SubscriptionStatus.ACTIVE`, returning True. Measured:
no PaymentIntent, no money, status `succeeded`, subscription active. That is the
audit's signature defect — success reported for work that did not happen — on
the path that collects revenue.

**Sub-cent amounts were truncated, not rounded.** `int(amount * 100)` makes
Decimal("10.999") into 1099 cents. On a charge that under-bills; on a refund it
under-refunds, which favours the platform against the customer. Money rounds
half-up to the cent, per the `hopefx-money-precision` skill.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from monetization.payment_processor import Payment, PaymentProcessor, PaymentStatus


@pytest.fixture
def processor() -> PaymentProcessor:
    return PaymentProcessor(stripe_api_key="sk_test_not_a_real_key")  # pragma: allowlist secret


@pytest.fixture
def payment(processor: PaymentProcessor) -> Payment:
    record = Payment(
        payment_id="pay-1",
        user_id="u-1",
        subscription_id="sub-1",
        invoice_id="inv-1",
        amount=Decimal("49.00"),
    )
    processor._payments["pay-1"] = record
    return record


# ── a charge that did not happen is not a success ────────────────────────────


def test_a_refused_charge_is_not_reported_as_succeeded(processor: PaymentProcessor, payment: Payment) -> None:
    """`create_stripe_payment_intent` returns None on any StripeError.

    A declined card, a rate limit and an outage all land here. None of them
    moved money, so none of them is a succeeded payment.
    """
    with patch.object(processor, "create_stripe_payment_intent", return_value=None):
        result = processor.process_payment("pay-1")

    assert result is False
    assert payment.status is PaymentStatus.FAILED
    assert payment.stripe_payment_intent_id is None
    assert payment.error_message, "a failed payment must record why"


def test_a_refused_charge_does_not_activate_the_subscription(processor: PaymentProcessor, payment: Payment) -> None:
    """The expensive half of the defect: unpaid access, granted."""
    subscription = MagicMock()
    subscription.stripe_customer_id = "cus_1"

    with (
        patch.object(processor, "create_stripe_payment_intent", return_value=None),
        patch("monetization.payment_processor.subscription_manager") as manager,
        patch("monetization.payment_processor.invoice_generator") as invoices,
    ):
        manager.get_subscription.return_value = subscription
        processor.process_payment("pay-1")

    invoices.mark_invoice_paid.assert_not_called()
    assert subscription.status is not True
    # `sub.status = ACTIVE` is the assignment that granted access.
    assert not any(call for call in subscription.mock_calls if "status" in str(call)), (
        "the subscription was touched for a payment that never went through"
    )


def test_a_charge_that_succeeds_still_completes_the_whole_flow(processor: PaymentProcessor, payment: Payment) -> None:
    """The fix must not break the path that works."""
    subscription = MagicMock()
    subscription.stripe_customer_id = "cus_1"

    with (
        patch.object(processor, "create_stripe_payment_intent", return_value="pi_123"),
        patch("monetization.payment_processor.subscription_manager") as manager,
        patch("monetization.payment_processor.invoice_generator") as invoices,
    ):
        manager.get_subscription.return_value = subscription
        result = processor.process_payment("pay-1")

    assert result is True
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.stripe_payment_intent_id == "pi_123"
    invoices.mark_invoice_paid.assert_called_once_with("inv-1")


def test_an_unknown_payment_id_is_refused(processor: PaymentProcessor) -> None:
    assert processor.process_payment("no-such-payment") is False


def test_a_raising_provider_fails_the_payment(processor: PaymentProcessor, payment: Payment) -> None:
    """An unconfigured Stripe raises rather than returning None. Same outcome."""
    with patch.object(processor, "create_stripe_payment_intent", side_effect=RuntimeError("no key")):
        assert processor.process_payment("pay-1") is False

    assert payment.status is PaymentStatus.FAILED


# ── money converts to cents by rounding, not truncation ──────────────────────


@pytest.mark.parametrize(
    ("amount", "expected_cents"),
    [
        (Decimal("49.00"), 4900),
        (Decimal("0.01"), 1),
        (Decimal("10.999"), 1100),  # truncation gave 1099
        (Decimal("0.999"), 100),  # truncation gave 99
        (Decimal("10.994"), 1099),  # rounds down, correctly
        (Decimal("0.005"), 1),  # half rounds up, not to even
    ],
)
def test_amounts_round_half_up_to_the_cent(amount: Decimal, expected_cents: int) -> None:
    """`int(amount * 100)` truncated. On a refund that favours the platform."""
    from monetization.payment_processor import to_cents

    assert to_cents(amount) == expected_cents


def _module():
    """The module object, not the singleton.

    `monetization/__init__.py` re-exports each singleton under its own module's
    name, so `import monetization.payment_processor as m` binds the
    PaymentProcessor instance and every patch lands on the object instead of the
    module. sys.modules holds the real one.
    """
    import sys

    import monetization.payment_processor  # noqa: F401 — ensure it is imported

    return sys.modules["monetization.payment_processor"]


def test_the_charge_sends_the_rounded_amount(processor: PaymentProcessor) -> None:
    module = _module()

    stripe = MagicMock()
    stripe.PaymentIntent.create.return_value = MagicMock(id="pi_1")
    with (
        patch.object(module, "_STRIPE_AVAILABLE", True),
        patch.object(module, "_stripe", stripe),
    ):
        processor.create_stripe_payment_intent(amount=Decimal("10.999"), currency="usd")

    assert stripe.PaymentIntent.create.call_args.kwargs["amount"] == 1100


def test_a_partial_refund_sends_the_rounded_amount(processor: PaymentProcessor, payment: Payment) -> None:
    """Truncating a refund keeps the remainder. That direction matters."""
    module = _module()

    payment.status = PaymentStatus.SUCCEEDED
    payment.stripe_payment_intent_id = "pi_1"

    stripe = MagicMock()
    stripe.Refund.create.return_value = MagicMock(id="re_1")
    stripe.error.StripeError = Exception
    with (
        patch.object(module, "_STRIPE_AVAILABLE", True),
        patch.object(module, "_stripe", stripe),
        patch("monetization.payment_processor.invoice_generator"),
    ):
        assert processor.refund_payment("pay-1", amount=Decimal("10.999")) is True

    assert stripe.Refund.create.call_args.kwargs["amount"] == 1100


# ── refunds respect state ────────────────────────────────────────────────────


def test_an_unsucceeded_payment_cannot_be_refunded(processor: PaymentProcessor, payment: Payment) -> None:
    payment.status = PaymentStatus.FAILED

    assert processor.refund_payment("pay-1") is False
    assert payment.status is PaymentStatus.FAILED


def test_an_unknown_payment_cannot_be_refunded(processor: PaymentProcessor) -> None:
    assert processor.refund_payment("no-such-payment") is False
