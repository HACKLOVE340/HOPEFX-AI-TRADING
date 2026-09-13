# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Converting an amount to cents must round, not truncate (F206).

`int(amount * 100)` truncates toward zero, and truncation always takes the same
side of the rounding, so the loss accumulates in one direction rather than
averaging out. Which side depends on what the call is doing, and both are wrong:

* a CHARGE truncated under-bills — $10.999 is collected as $10.99;
* a REFUND truncated keeps the remainder — the customer is paid $10.99 of the
  $11.00 they are owed, and the platform keeps the cent.

`monetization/revenue_split.to_cents` and `monetization/payment_processor.to_cents`
both quantize ROUND_HALF_UP, and `payments/fintech/paystack.py` does the same
inline. Three call sites did not. These tests drive each one with a stubbed
Stripe and assert the integer that reaches the API.

Half-up, not `round()`: `round()` is banker's rounding, which is not what an
invoice means (see the hopefx-money-precision skill).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit


def _stripe_module():
    """The MODULE, not the singleton that shadows its name.

    `monetization/__init__.py` binds the name `stripe_integration` to an
    INSTANCE of StripeIntegration, so `import monetization.stripe_integration as
    si` hands back the object rather than the module and every attribute lookup
    on it fails with a message that reads like a typo. Same shadowing family as
    the two SecureVault classes and the two OANDABroker classes. Import it by
    module path instead.
    """
    import importlib

    return importlib.import_module("monetization.stripe_integration")


class _CapturingStripe:
    """Records the kwargs each Stripe call receives."""

    def __init__(self) -> None:
        self.calls: dict[str, dict] = {}

    def _record(self, name):
        def inner(**kwargs):
            self.calls[name] = kwargs
            return type(
                "R",
                (),
                {"id": f"{name}_1", "status": "succeeded", "amount": kwargs.get("amount", 0), "client_secret": "cs_1"},
            )()

        return inner

    @property
    def PaymentIntent(self):
        return type("PI", (), {"create": staticmethod(self._record("payment_intent"))})

    @property
    def Refund(self):
        return type("RF", (), {"create": staticmethod(self._record("refund"))})


# ── the helper both packages already agree on ────────────────────────────────


@pytest.mark.parametrize(
    ("amount", "cents"),
    [("10.999", 1100), ("0.999", 100), ("24.995", 2500), ("10.005", 1001), ("1.00", 100), ("0.004", 0)],
)
def test_to_cents_rounds_half_up(amount, cents):
    from monetization.payment_processor import to_cents

    assert to_cents(Decimal(amount)) == cents


def test_truncation_and_rounding_actually_differ_here():
    """The positive control: without it the assertions above could be trivial."""
    assert int(Decimal("0.999") * 100) == 99
    from monetization.payment_processor import to_cents

    assert to_cents(Decimal("0.999")) == 100


# ── the three call sites ─────────────────────────────────────────────────────


def test_a_charge_does_not_under_bill(monkeypatch):
    """monetization/stripe_integration.py — create_payment_intent."""
    si = _stripe_module()

    fake = _CapturingStripe()
    monkeypatch.setattr(si, "_stripe", fake, raising=False)
    integration = si.StripeIntegration.__new__(si.StripeIntegration)
    monkeypatch.setattr(integration, "_require_stripe", lambda: None, raising=False)

    integration.create_payment_intent(customer_id="cus_1", amount=Decimal("0.999"), currency="usd")
    assert "payment_intent" in fake.calls, "Stripe was never called; the test never reached the conversion"
    assert fake.calls["payment_intent"]["amount"] == 100, "a charge truncated to 99 under-bills by a cent"


def test_a_refund_does_not_short_the_customer(monkeypatch):
    """monetization/stripe_integration.py — refund_payment.

    The direction that matters most: truncating a refund keeps the remainder on
    the platform's side, against the person owed the money.
    """
    si = _stripe_module()

    fake = _CapturingStripe()
    monkeypatch.setattr(si, "_stripe", fake, raising=False)
    integration = si.StripeIntegration.__new__(si.StripeIntegration)
    monkeypatch.setattr(integration, "_require_stripe", lambda: None, raising=False)

    integration.refund_payment("pi_1", amount=Decimal("24.995"))
    assert "refund" in fake.calls, "Stripe was never called; the test never reached the conversion"
    assert fake.calls["refund"]["amount"] == 2500, "a refund truncated to 2499 shorts the customer a cent"


# ── Third site: api/payments.py, the fiat deposit ─────────────────────────────
# Found 2026-09-13, months after the two above were fixed. The F206 probe scanned
# `monetization/*.py` and `payments/**/*.py` and never looked in `api/`, so
# `int(req.amount * 100)` at the Stripe deposit sat in scope-shadow the whole
# time — the probe's own docstring warns against a pattern "satisfied by
# vocabulary rather than by behaviour" and then had a blind spot in its file
# list. The probe now scans `api/*.py` too.


def test_a_fiat_deposit_does_not_undercharge(monkeypatch):
    """api/payments.py — `_fiat_deposit_impl`, the Stripe branch.

    `int(10.999 * 100)` is 1099: the customer is charged 10.99 for a 10.999
    deposit, and the cent has to come from somewhere. `1.005` is worse — as a
    float it is 1.00499…, so truncation loses the cent to the binary error as
    well as to the rounding.
    """
    import asyncio
    import sys
    from types import SimpleNamespace

    calls: dict = {}

    class _FakeIntent:
        @staticmethod
        def create(**kwargs):
            calls.update(kwargs)
            return SimpleNamespace(client_secret="not-a-secret")  # pragma: allowlist secret

    fake_stripe = SimpleNamespace(api_key="", PaymentIntent=_FakeIntent)
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)
    monkeypatch.setenv("FIAT_PROVIDER", "stripe")

    from api.payments import FiatDepositRequest, _fiat_deposit_impl

    asyncio.run(_fiat_deposit_impl(FiatDepositRequest(amount=10.999, method="card")))

    assert calls, "Stripe was never called; the test never reached the conversion"
    assert calls["amount"] == 1100, (
        f"a deposit of 10.999 was charged {calls['amount']} cents — truncated to 1099, which undercharges by a cent"
    )
