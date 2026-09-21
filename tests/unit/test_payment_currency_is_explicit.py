"""TODO item 6 — the chain a user's money is on must not be a guess.

`PaymentGateway._process_crypto` read the currency out of `payment.description`:

    currency = (payment.description or "BTC").strip().upper()

`description` is a description. A blank one silently became **BTC**, so a user
paying in ETH could be handed a Bitcoin address — and coins sent to an address
on the wrong chain are, in the general case, gone.

Since F267 the address generator raises on an unknown currency rather than
inventing one, which contains the blast radius. It does not close this: "BTC" is
a *known* currency, so the default sails straight through that check. The
guess has to stop at the source.

This file is also `payments/payment_gateway.py`'s first test — it is one of the
eight modules F222 found with no test naming them at all (TODO item 5).
"""

from __future__ import annotations

import pytest

from payments.payment_gateway import Payment, PaymentGateway, PaymentMethod, PaymentStatus


@pytest.fixture
def gateway() -> PaymentGateway:
    return PaymentGateway()


@pytest.fixture
def address_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture what the address generator is asked for, without generating one."""
    import payments.crypto.address_generator  # noqa: F401 — ensure it is in sys.modules

    calls: list[dict] = []

    class _Generator:
        @staticmethod
        def generate_address(*, user_id: str, currency: str) -> str:
            calls.append({"user_id": user_id, "currency": currency})
            return f"addr-{currency.lower()}-1"

    # Via sys.modules, not `import payments.crypto.address_generator as module`:
    # the package re-exports the singleton under the same name as its module, so
    # attribute lookup returns the AddressGenerator instance and the patch lands
    # on the object instead of the module.
    import sys

    module = sys.modules["payments.crypto.address_generator"]
    monkeypatch.setattr(module, "address_generator", _Generator())
    return calls


# ── the currency is carried, not inferred ─────────────────────────────────────


def test_an_explicit_currency_reaches_the_address_generator(gateway: PaymentGateway, address_calls: list) -> None:
    payment = gateway.create_payment(amount=50.0, method=PaymentMethod.CRYPTO, user_id="u-1", currency="ETH")

    assert gateway.process_payment(payment.id) is True
    assert address_calls == [{"user_id": "u-1", "currency": "ETH"}]
    assert payment.transaction_id == "addr-eth-1"


def test_a_missing_currency_is_refused_not_defaulted(gateway: PaymentGateway, address_calls: list) -> None:
    """The whole finding: a blank field must not decide which chain money goes to."""
    payment = gateway.create_payment(amount=50.0, method=PaymentMethod.CRYPTO, user_id="u-2")

    assert gateway.process_payment(payment.id) is False
    assert payment.status is PaymentStatus.FAILED
    assert address_calls == [], "an address was generated for a currency nobody specified"


def test_a_blank_currency_is_refused(gateway: PaymentGateway, address_calls: list) -> None:
    payment = gateway.create_payment(amount=50.0, method=PaymentMethod.CRYPTO, user_id="u-3", currency="   ")

    assert gateway.process_payment(payment.id) is False
    assert address_calls == []


def test_the_description_no_longer_decides_the_chain(gateway: PaymentGateway, address_calls: list) -> None:
    """A description that happens to read "BTC" is still a description."""
    payment = gateway.create_payment(amount=50.0, method=PaymentMethod.CRYPTO, user_id="u-4", description="BTC")

    assert gateway.process_payment(payment.id) is False
    assert address_calls == [], "the description was read as a currency"


def test_the_currency_is_normalised_but_never_invented(gateway: PaymentGateway, address_calls: list) -> None:
    payment = gateway.create_payment(amount=50.0, method=PaymentMethod.CRYPTO, user_id="u-5", currency=" usdt_erc20 ")

    assert gateway.process_payment(payment.id) is True
    assert address_calls[0]["currency"] == "USDT_ERC20"


def test_a_refusal_names_the_field_to_set(gateway: PaymentGateway) -> None:
    """An operator reading the log needs to know what to fix."""
    payment = Payment(amount=10.0, method=PaymentMethod.CRYPTO, user_id="u-6")

    with pytest.raises(ValueError, match="currency"):
        gateway._process_crypto(payment)


# ── the gateway's own contract, previously untested ──────────────────────────


def test_a_failed_payment_is_never_marked_successful(gateway: PaymentGateway, address_calls: list) -> None:
    payment = gateway.create_payment(amount=50.0, method=PaymentMethod.CRYPTO, user_id="u-7")

    gateway.process_payment(payment.id)

    assert payment.status is PaymentStatus.FAILED
    assert payment.completed_at is None


def test_an_unknown_payment_id_is_refused(gateway: PaymentGateway) -> None:
    assert gateway.process_payment("no-such-payment") is False


def test_a_successful_payment_records_when_it_completed(gateway: PaymentGateway, address_calls: list) -> None:
    payment = gateway.create_payment(amount=50.0, method=PaymentMethod.CRYPTO, user_id="u-8", currency="BTC")

    assert gateway.process_payment(payment.id) is True
    assert payment.status is PaymentStatus.SUCCESS
    assert payment.completed_at is not None
