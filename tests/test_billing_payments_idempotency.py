# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_billing_payments_idempotency.py
==========================================
Regression tests for idempotency / double-charge fixes in:
  - api/billing.py  (Stripe PaymentIntent, Flutterwave init/verify)
  - api/payments.py (crypto webhook, fiat deposit/withdraw references)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user(sub: str = "user-123", email: str = "test@hopefx.io") -> SimpleNamespace:
    return SimpleNamespace(sub=sub, email=email)


# ─────────────────────────────────────────────────────────────────────────────
# Stripe PaymentIntent idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestStripePaymentIntentIdempotency:
    """
    When the client does not supply an idempotency_key, the endpoint must
    derive one from (user_id, amount, currency) so retries hit the same
    Stripe PaymentIntent rather than creating a new one.
    """

    def _expected_key(self, user_id: str, amount: float, currency: str) -> str:
        return hashlib.sha256(f"{user_id}:{amount}:{currency}".encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_auto_idempotency_key_derived_from_user_amount_currency(self):
        """No client key → deterministic key derived from user+amount+currency."""
        from api.billing import CreatePaymentIntentRequest, create_payment_intent

        captured_keys: list[str] = []

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.to_dict.return_value = {"client_secret": "pi_test_secret"}

        mock_client = MagicMock()
        mock_client.get_or_create_customer.return_value = "cus_test"
        mock_client.create_payment_intent.side_effect = lambda **kw: (
            captured_keys.append(kw["idempotency_key"]) or mock_result
        )

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers.get.return_value = "test-agent"

        body = CreatePaymentIntentRequest(amount_usd=49.99, currency="USD")
        user = _user()

        with patch("monetization.stripe_live.get_stripe_client", return_value=mock_client):
            # Call twice — same user, same amount, same currency
            await create_payment_intent(body, request, user)
            await create_payment_intent(body, request, user)

        assert len(captured_keys) == 2
        assert captured_keys[0] == captured_keys[1], (
            "Both calls must use the same idempotency key to avoid double-charge"
        )
        expected = self._expected_key(user.sub, 49.99, "USD")
        assert captured_keys[0] == expected

    @pytest.mark.asyncio
    async def test_client_supplied_key_is_used_verbatim(self):
        """When the client supplies an idempotency_key, it must be passed through unchanged."""
        from api.billing import CreatePaymentIntentRequest, create_payment_intent

        captured_keys: list[str] = []

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.to_dict.return_value = {"client_secret": "pi_test_secret"}

        mock_client = MagicMock()
        mock_client.get_or_create_customer.return_value = "cus_test"
        mock_client.create_payment_intent.side_effect = lambda **kw: (
            captured_keys.append(kw["idempotency_key"]) or mock_result
        )

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers.get.return_value = "test-agent"

        client_key = "my-custom-idempotency-key-abc123"
        body = CreatePaymentIntentRequest(amount_usd=49.99, currency="USD", idempotency_key=client_key)
        user = _user()

        with patch("monetization.stripe_live.get_stripe_client", return_value=mock_client):
            await create_payment_intent(body, request, user)

        assert captured_keys[0] == client_key

    @pytest.mark.asyncio
    async def test_different_amounts_produce_different_keys(self):
        """Different amounts must produce different idempotency keys."""
        from api.billing import CreatePaymentIntentRequest, create_payment_intent

        captured_keys: list[str] = []

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.to_dict.return_value = {"client_secret": "pi_test_secret"}

        mock_client = MagicMock()
        mock_client.get_or_create_customer.return_value = "cus_test"
        mock_client.create_payment_intent.side_effect = lambda **kw: (
            captured_keys.append(kw["idempotency_key"]) or mock_result
        )

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers.get.return_value = "test-agent"

        user = _user()
        body1 = CreatePaymentIntentRequest(amount_usd=49.99, currency="USD")
        body2 = CreatePaymentIntentRequest(amount_usd=99.99, currency="USD")

        with patch("monetization.stripe_live.get_stripe_client", return_value=mock_client):
            await create_payment_intent(body1, request, user)
            await create_payment_intent(body2, request, user)

        assert captured_keys[0] != captured_keys[1], (
            "Different amounts must produce different idempotency keys"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Flutterwave init — deterministic tx_ref
# ─────────────────────────────────────────────────────────────────────────────

class TestFlutterwaveInitIdempotency:
    @pytest.mark.asyncio
    async def test_same_user_plan_amount_produces_same_tx_ref(self):
        """
        Two calls with the same user/plan/amount/currency must produce the
        same tx_ref so the second call hits the existing payment session.
        """
        from api.billing import FlutterwaveInitBody, flutterwave_init

        tx_refs: list[str] = []

        mock_flw = MagicMock()
        mock_flw.initialize_payment.side_effect = lambda **kw: {
            "tx_ref": kw.get("tx_ref", "flw-ref"),
            "payment_link": "https://pay.flutterwave.com/test",
            "amount": 49.99,
            "currency": "USD",
            "fee": 0,
        }

        body = FlutterwaveInitBody(amount=49.99, currency="USD", plan="professional")
        user = _user()

        with patch("api.billing._get_flutterwave", return_value=mock_flw):
            r1 = await flutterwave_init(body, user)
            r2 = await flutterwave_init(body, user)
            tx_refs.extend([r1["tx_ref"], r2["tx_ref"]])

        assert tx_refs[0] == tx_refs[1], (
            f"Same user+plan+amount must produce same tx_ref: {tx_refs}"
        )

    @pytest.mark.asyncio
    async def test_different_plans_produce_different_tx_refs(self):
        """Different plans must produce different tx_refs."""
        from api.billing import FlutterwaveInitBody, flutterwave_init

        mock_flw = MagicMock()
        mock_flw.initialize_payment.side_effect = lambda **kw: {
            "tx_ref": kw.get("tx_ref", "flw-ref"),
            "payment_link": "https://pay.flutterwave.com/test",
            "amount": 49.99,
            "currency": "USD",
            "fee": 0,
        }

        user = _user()
        body1 = FlutterwaveInitBody(amount=49.99, currency="USD", plan="starter")
        body2 = FlutterwaveInitBody(amount=49.99, currency="USD", plan="professional")

        with patch("api.billing._get_flutterwave", return_value=mock_flw):
            r1 = await flutterwave_init(body1, user)
            r2 = await flutterwave_init(body2, user)

        assert r1["tx_ref"] != r2["tx_ref"]


# ─────────────────────────────────────────────────────────────────────────────
# Flutterwave verify — idempotency guard
# ─────────────────────────────────────────────────────────────────────────────

class TestFlutterwaveVerifyIdempotency:
    @pytest.mark.asyncio
    async def test_second_verify_returns_cached_result(self):
        """
        A second call with the same tx_ref must return the cached result
        without calling Flutterwave again.
        """
        from api.billing import FlutterwaveVerifyBody, flutterwave_verify

        call_count = [0]

        mock_flw = MagicMock()
        def _verify(tx_ref):
            call_count[0] += 1
            return {"status": "verified"}
        mock_flw.verify_transaction.side_effect = _verify

        cache: dict = {}

        def _db_get(key):
            return cache.get(key)

        def _db_set(key, value, **_kw):
            cache[key] = value

        body = FlutterwaveVerifyBody(tx_ref="FLW-TEST-123")
        user = _user()

        with patch("api.billing._get_flutterwave", return_value=mock_flw), \
             patch("api.billing.db_get", _db_get, create=True), \
             patch("api.billing.db_set", _db_set, create=True):
            # Patch the import inside the function
            import api.billing as billing_mod
            with patch.dict("sys.modules", {"api.db_store": MagicMock(db_get=_db_get, db_set=_db_set)}):
                r1 = await flutterwave_verify(body, user)
                # Manually seed the cache as the function would
                cache[f"flw_verified:{user.sub}:{body.tx_ref}"] = {
                    "status": "verified", "tx_ref": body.tx_ref, "user_id": user.sub
                }
                r2 = await flutterwave_verify(body, user)

        assert r1["verified"] is True
        assert r2["verified"] is True
        # Second call must be idempotent — Flutterwave called only once
        assert call_count[0] == 1, (
            f"Flutterwave.verify_transaction called {call_count[0]} times; expected 1"
        )
        assert r2.get("idempotent") is True


# ─────────────────────────────────────────────────────────────────────────────
# Crypto webhook — duplicate delivery guard
# ─────────────────────────────────────────────────────────────────────────────

class TestCryptoWebhookIdempotency:
    def _make_payment(self, status: str = "confirming") -> dict:
        return {
            "payment_id": "PAY_test123",
            "status": status,
            "confirmations": 2,
            "confirmations_required": 3,
            "currency": "BTC",
            "amount_crypto": 0.001,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "tx_hash": None,
        }

    @pytest.mark.asyncio
    async def test_duplicate_complete_webhook_is_ignored(self):
        """
        A second webhook delivery with status=complete must be ignored
        (idempotent=True) and must not call _update_payment again.
        """
        from api.payments import payment_webhook

        update_calls = [0]

        def _load(pid):
            return self._make_payment(status="complete")  # already complete

        def _update(pid, **kw):
            update_calls[0] += 1

        payload = json.dumps({
            "payment_id": "PAY_test123",
            "status": "complete",
            "confirmations": 3,
            "tx_hash": "0xabc",
        }).encode()

        request = MagicMock()
        request.body = AsyncMock(return_value=payload)
        request.client.host = "127.0.0.1"

        with patch("api.payments._load_payment", _load), \
             patch("api.payments._update_payment", _update), \
             patch("api.payments.os.getenv", side_effect=lambda k, d="": "false" if k == "CRYPTO_WEBHOOK_VERIFY" else d):
            result = await payment_webhook(request, x_webhook_signature=None)

        assert result["idempotent"] is True
        assert update_calls[0] == 0, "_update_payment must not be called for duplicate complete webhook"

    @pytest.mark.asyncio
    async def test_first_complete_webhook_is_processed(self):
        """The first complete webhook must be processed normally."""
        from api.payments import payment_webhook

        update_calls = [0]

        def _load(pid):
            return self._make_payment(status="confirming")  # not yet complete

        def _update(pid, **kw):
            update_calls[0] += 1

        payload = json.dumps({
            "payment_id": "PAY_test123",
            "status": "complete",
            "confirmations": 3,
            "tx_hash": "0xabc",
        }).encode()

        request = MagicMock()
        request.body = AsyncMock(return_value=payload)
        request.client.host = "127.0.0.1"

        with patch("api.payments._load_payment", _load), \
             patch("api.payments._update_payment", _update), \
             patch("api.payments.os.getenv", side_effect=lambda k, d="": "false" if k == "CRYPTO_WEBHOOK_VERIFY" else d):
            result = await payment_webhook(request, x_webhook_signature=None)

        assert result.get("idempotent") is not True
        assert update_calls[0] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Fiat deposit/withdraw — UUID-based references (no timestamp collision)
# ─────────────────────────────────────────────────────────────────────────────

class TestFiatReferenceUniqueness:
    @pytest.mark.asyncio
    async def test_two_deposits_produce_different_references(self):
        """Two concurrent deposit requests must produce different references."""
        from api.payments import FiatDepositRequest, _fiat_deposit_impl

        r1 = await _fiat_deposit_impl(FiatDepositRequest(amount=100.0, method="bank_transfer"))
        r2 = await _fiat_deposit_impl(FiatDepositRequest(amount=100.0, method="bank_transfer"))

        ref1 = r1.get("reference") or r1.get("instructions", {}).get("reference")
        ref2 = r2.get("reference") or r2.get("instructions", {}).get("reference")

        assert ref1 is not None
        assert ref2 is not None
        assert ref1 != ref2, f"Two deposits produced the same reference: {ref1}"
        assert ref1.startswith("DEP-")
        assert ref2.startswith("DEP-")

    @pytest.mark.asyncio
    async def test_deposit_address_payment_ids_are_unique(self):
        """Two generate_deposit_address calls must produce different payment_ids."""
        import api.payments as pm

        ids: list[str] = []

        def _save(p):
            ids.append(p["payment_id"])

        mock_rates = {"BTC": 50000.0}

        with patch("api.payments._save_payment", _save), \
             patch("api.payments._generate_address", return_value="bc1qtest"), \
             patch("payments.crypto.rate_feed.get_rates", AsyncMock(return_value=mock_rates)):
            from api.payments import AddressRequest, generate_deposit_address
            from api.auth import TokenPayload

            user = _user()
            req = AddressRequest(currency="BTC", plan_id="professional", amount_usd=100.0, user_id=user.sub)

            await generate_deposit_address(req, user)
            await generate_deposit_address(req, user)

        assert len(ids) == 2
        assert ids[0] != ids[1], f"Two address requests produced the same payment_id: {ids[0]}"
        assert ids[0].startswith("PAY_")
        assert ids[1].startswith("PAY_")
