"""F222 (TODO item 5) — `payments/fintech/paystack.py` charged real customers untested.

318 lines, named by no test file. It initialises Paystack transactions, moves
payouts to bank accounts, and verifies webhook signatures.

Two defects on the charging path, both found by writing this file.

**A hard-coded FX rate decided what a customer pays.**

    _NGN_PER_USD = Decimal("775.00")  # approximate; update via FX feed in production

A USD price was multiplied by that constant to produce the naira amount actually
charged. The comment admits it is approximate, and nothing updated it. The naira
has moved a long way from 775: at a true rate near 1,600 the platform bills
roughly half of what it invoiced, silently, on every USD transaction. A constant
standing in for a measurement, with a comment conceding the fact, is this
audit's signature defect.

It is not fixed by writing a newer number — that is the same defect with a later
date. The client now refuses to convert unless a rate is configured.

**Kobo amounts were truncated.** `int(ngn_amount * 100)` turns 1,199.999 NGN
into 119,999 kobo rather than 120,000. Money rounds half-up to the minor unit.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


def _module():
    """The module object, not the re-exported singleton."""
    import payments.fintech.paystack  # noqa: F401

    return sys.modules["payments.fintech.paystack"]


_MOD = _module()
PaystackClient = _MOD.PaystackClient
PaystackError = _MOD.PaystackError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> PaystackClient:
    monkeypatch.delenv("PAYSTACK_NGN_PER_USD", raising=False)
    return PaystackClient(secret_key="sk_test_paystack")  # pragma: allowlist secret


def _stub_initialize(client: PaystackClient) -> MagicMock:
    """Capture the payload without making a request."""
    post = MagicMock(
        return_value={
            "reference": "ref-1",
            "authorization_url": "https://checkout.paystack.com/x",
            "access_code": "ac-1",
        }
    )
    client._post_dict = post  # type: ignore[method-assign]
    return post


# ── the FX rate is not a constant ─────────────────────────────────────────────


def test_a_usd_charge_is_refused_without_a_configured_rate(client: PaystackClient) -> None:
    """Refusing beats charging at a rate nobody checked."""
    _stub_initialize(client)

    with pytest.raises(PaystackError, match="PAYSTACK_NGN_PER_USD"):
        client.initialize_payment(user_id="u-1", amount=Decimal("10.00"), currency="USD")


def test_the_refusal_names_what_to_set(client: PaystackClient) -> None:
    _stub_initialize(client)

    with pytest.raises(PaystackError) as raised:
        client.initialize_payment(user_id="u-1", amount=Decimal("10.00"), currency="USD")

    message = str(raised.value)
    assert "rate" in message.lower()
    assert "775" not in message, "the refusal must not suggest the stale constant"


def test_a_configured_rate_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYSTACK_NGN_PER_USD", "1600.00")
    client = PaystackClient(secret_key="sk_test_paystack")  # pragma: allowlist secret
    post = _stub_initialize(client)

    client.initialize_payment(user_id="u-1", amount=Decimal("10.00"), currency="USD")

    # 10 USD * 1600 NGN = 16,000 NGN = 1,600,000 kobo
    assert post.call_args[0][1]["amount"] == 1_600_000


def test_a_rate_passed_to_the_constructor_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYSTACK_NGN_PER_USD", "1600.00")
    client = PaystackClient(
        secret_key="sk_test_paystack",  # pragma: allowlist secret
        ngn_per_usd=Decimal("1500.00"),
    )
    post = _stub_initialize(client)

    client.initialize_payment(user_id="u-1", amount=Decimal("10.00"), currency="USD")

    assert post.call_args[0][1]["amount"] == 1_500_000


@pytest.mark.parametrize("bad", ["0", "-1", "not a number", ""])
def test_an_unusable_configured_rate_is_refused(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    """A zero or negative rate would charge zero, or a negative amount."""
    monkeypatch.setenv("PAYSTACK_NGN_PER_USD", bad)
    client = PaystackClient(secret_key="sk_test_paystack")  # pragma: allowlist secret
    _stub_initialize(client)

    with pytest.raises(PaystackError):
        client.initialize_payment(user_id="u-1", amount=Decimal("10.00"), currency="USD")


def test_the_stale_constant_is_gone() -> None:
    """A newer number would be the same defect with a later date."""
    assert not hasattr(PaystackClient, "_NGN_PER_USD"), "the hard-coded USD->NGN rate is still a class constant"


# ── naira charges do not need a rate at all ──────────────────────────────────


def test_a_naira_charge_needs_no_rate(client: PaystackClient) -> None:
    post = _stub_initialize(client)

    result = client.initialize_payment(user_id="u-1", amount=Decimal("5000.00"), currency="NGN")

    assert post.call_args[0][1]["amount"] == 500_000
    assert result["reference"] == "ref-1"


# ── kobo rounds, it does not truncate ────────────────────────────────────────


@pytest.mark.parametrize(
    ("naira", "expected_kobo"),
    [
        (Decimal("5000.00"), 500_000),
        (Decimal("0.01"), 1),
        (Decimal("1199.999"), 120_000),  # truncation gave 119,999
        (Decimal("0.005"), 1),  # half rounds up, not to even
        (Decimal("1199.994"), 119_999),  # rounds down, correctly
    ],
)
def test_kobo_rounds_half_up(client: PaystackClient, naira: Decimal, expected_kobo: int) -> None:
    post = _stub_initialize(client)

    client.initialize_payment(user_id="u-1", amount=naira, currency="NGN")

    assert post.call_args[0][1]["amount"] == expected_kobo


# ── the parts that were already right, now covered ───────────────────────────


def test_a_valid_webhook_signature_is_accepted(client: PaystackClient) -> None:
    import hashlib
    import hmac

    payload = b'{"event":"charge.success"}'
    signature = hmac.new(b"sk_test_paystack", payload, hashlib.sha512).hexdigest()

    assert client.verify_webhook(payload, signature) is True


def test_a_forged_webhook_signature_is_rejected(client: PaystackClient) -> None:
    assert client.verify_webhook(b'{"event":"charge.success"}', "0" * 128) is False


def test_a_tampered_payload_is_rejected(client: PaystackClient) -> None:
    import hashlib
    import hmac

    signature = hmac.new(b"sk_test_paystack", b'{"amount":100}', hashlib.sha512).hexdigest()

    assert client.verify_webhook(b'{"amount":1000000}', signature) is False


def test_a_client_without_a_key_refuses_to_construct() -> None:
    with pytest.raises(ValueError, match="secret key"):
        PaystackClient(secret_key=None)


def test_the_secret_key_is_not_in_the_repr(client: PaystackClient) -> None:
    assert "sk_test_paystack" not in repr(client)


def test_an_api_failure_raises_rather_than_returning_a_partial_result(client: PaystackClient) -> None:
    """A caller that gets a dict back assumes the charge was initialised."""
    response = MagicMock()
    response.json.return_value = {"status": False, "message": "Invalid key"}
    response.raise_for_status.return_value = None

    with patch.object(client._session, "post", return_value=response):
        with pytest.raises(PaystackError, match="Invalid key"):
            client.initialize_payment(user_id="u-1", amount=Decimal("100.00"), currency="NGN")


def test_a_payout_is_rounded_not_truncated(client: PaystackClient) -> None:
    """On a payout, truncation under-pays the recipient and the platform keeps it."""
    posts: list[tuple[str, dict]] = []

    def _post(path: str, payload: dict) -> dict:
        posts.append((path, payload))
        return {"recipient_code": "RCP_1", "transfer_code": "TRF_1", "reference": "ref-1", "status": "pending"}

    client._post_dict = _post  # type: ignore[method-assign]

    client.initiate_transfer(
        user_id="u-1",
        amount=Decimal("1199.999"),
        bank_code="058",
        account_number="0123456789",
        account_name="A Recipient",
    )

    transfer = next(payload for path, payload in posts if "transfer" in path and "amount" in payload)
    assert transfer["amount"] == 120_000, "the recipient was short-paid by truncation"
