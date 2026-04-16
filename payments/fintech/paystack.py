# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Paystack Payment Integration

Handles payments via Paystack (Nigeria) — bank transfer, cards, USSD.
All HTTP calls go to the real Paystack API (https://api.paystack.co).
Credentials are read from PAYSTACK_SECRET_KEY environment variable.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import requests

UTC = timezone.utc
logger = logging.getLogger(__name__)

_PAYSTACK_BASE = "https://api.paystack.co"
_REQUEST_TIMEOUT = 30  # seconds


class PaystackError(Exception):
    """Raised when the Paystack API returns a non-success response."""


class PaystackClient:
    """
    Paystack payment client for Nigerian payments.

    All methods make real HTTP calls to https://api.paystack.co using the
    secret key supplied at construction time.  The secret key must be kept
    server-side and never exposed to clients.

    Supported flows
    ---------------
    - initialize_payment  -> returns authorization_url for redirect / inline
    - verify_transaction  -> confirms payment status after redirect callback
    - initiate_transfer   -> sends funds to a bank account (payouts)
    - verify_webhook      -> validates Paystack webhook HMAC signature
    - list_banks          -> returns supported banks for a country
    """

    FEE_PERCENT = Decimal("0.015")  # 1.5%
    FEE_CAP_NGN = Decimal("100.00")  # NGN 100 cap
    _NGN_PER_USD = Decimal("775.00")  # approximate; update via FX feed in production

    def __init__(self, secret_key: str | None = None) -> None:
        if not secret_key:
            raise ValueError("PaystackClient requires a secret key. Set the PAYSTACK_SECRET_KEY environment variable.")
        self._secret_key = secret_key
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._secret_key}",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize_payment(
        self,
        user_id: str,
        amount: Decimal,
        currency: str = "USD",
        email: str | None = None,
    ) -> dict[str, Any]:
        """
        Initialize a Paystack transaction.

        Calls POST /transaction/initialize and returns the authorization_url
        that the client should be redirected to (or loaded in an inline popup).

        Parameters
        ----------
        user_id:  Internal user identifier stored as Paystack metadata.
        amount:   Amount to charge (in the given currency).
        currency: "NGN" or "USD" (converted to NGN for Paystack).
        email:    Customer email required by Paystack; defaults to a
                  placeholder when not supplied.

        Returns
        -------
        dict with keys: reference, authorization_url, access_code, fee, status
        """
        # Paystack amounts are in kobo (NGN x 100)
        ngn_amount = amount * self._NGN_PER_USD if currency == "USD" else amount
        kobo_amount = int(ngn_amount * 100)

        fee_ngn = min(ngn_amount * self.FEE_PERCENT, self.FEE_CAP_NGN)
        fee_usd = fee_ngn / self._NGN_PER_USD if currency == "USD" else fee_ngn

        customer_email = email or f"user_{user_id}@hopefx.internal"

        payload = {
            "email": customer_email,
            "amount": kobo_amount,
            "currency": "NGN",
            "metadata": {
                "user_id": user_id,
                "original_currency": currency,
                "original_amount": str(amount),
            },
        }

        data = self._post_dict("/transaction/initialize", payload)

        reference = data["reference"]
        logger.info("Paystack payment initialized: ref=%s user=%s", reference, user_id)

        return {
            "reference": reference,
            "authorization_url": data["authorization_url"],
            "access_code": data["access_code"],
            "fee": float(fee_usd),
            "status": "initiated",
        }

    def verify_transaction(self, reference: str) -> dict[str, Any]:
        """
        Verify a Paystack transaction by reference.

        Calls GET /transaction/verify/:reference and returns the full
        transaction object.  Raises PaystackError on API failure.

        Parameters
        ----------
        reference: The transaction reference returned by initialize_payment.

        Returns
        -------
        dict with at minimum: status, amount (kobo), currency, reference,
        paid_at, customer, metadata.
        """
        data = self._get_dict(f"/transaction/verify/{reference}")
        logger.info(
            "Paystack transaction verified: ref=%s status=%s",
            reference,
            data.get("status"),
        )
        return data

    def initiate_transfer(
        self,
        user_id: str,
        amount: Decimal,
        bank_code: str,
        account_number: str,
        account_name: str = "",
        currency: str = "NGN",
        reason: str = "HOPEFX withdrawal",
    ) -> dict[str, Any]:
        """
        Initiate a bank transfer (payout) via Paystack.

        Flow
        ----
        1. Create a transfer recipient (POST /transferrecipient).
        2. Initiate the transfer (POST /transfer).

        Parameters
        ----------
        user_id:        Internal user identifier stored in transfer metadata.
        amount:         Amount to transfer (in NGN by default).
        bank_code:      Paystack bank code (e.g. "058" for GTBank).
        account_number: Recipient bank account number.
        account_name:   Account name for the recipient record.
        currency:       Transfer currency (default "NGN").
        reason:         Narration shown on the recipient's bank statement.

        Returns
        -------
        dict with keys: transfer_code, status, amount, bank_code,
        account_number, created_at.
        """
        # Step 1 — create recipient
        recipient_payload = {
            "type": "nuban",
            "name": account_name or f"user_{user_id}",
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        }
        recipient_data = self._post_dict("/transferrecipient", recipient_payload)
        recipient_code = recipient_data["recipient_code"]

        # Step 2 — initiate transfer (amount in kobo)
        kobo_amount = int(amount * 100)
        transfer_payload = {
            "source": "balance",
            "amount": kobo_amount,
            "recipient": recipient_code,
            "reason": reason,
            "metadata": {"user_id": user_id},
        }
        transfer_data = self._post_dict("/transfer", transfer_payload)

        logger.info(
            "Paystack transfer initiated: code=%s amount=%s status=%s",
            transfer_data.get("transfer_code"),
            amount,
            transfer_data.get("status"),
        )

        return {
            "transfer_code": transfer_data["transfer_code"],
            "status": transfer_data.get("status", "pending"),
            "amount": float(amount),
            "bank_code": bank_code,
            "account_number": account_number,
            "created_at": transfer_data.get("createdAt", datetime.now(UTC).isoformat()),
        }

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """
        Validate a Paystack webhook HMAC-SHA512 signature.

        Paystack signs every webhook with HMAC-SHA512 using the secret key.
        Always verify before processing webhook events.

        Parameters
        ----------
        payload:   Raw request body bytes.
        signature: Value of the X-Paystack-Signature header.

        Returns
        -------
        True if the signature is valid, False otherwise.
        """
        expected = hmac.new(
            self._secret_key.encode(),
            payload,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def list_banks(self, country: str = "nigeria") -> list[dict[str, Any]]:
        """
        Return the list of supported banks for the given country.

        Calls GET /bank and returns the data array.
        """
        return self._get_list(f"/bank?country={country}&perPage=100")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post_dict(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to Paystack and return the ``data`` field as a dict."""
        url = f"{_PAYSTACK_BASE}{path}"
        try:
            resp = self._session.post(url, json=payload, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PaystackError(f"Paystack POST {path} failed: {exc}") from exc

        body: dict[str, Any] = resp.json()
        if not body.get("status"):
            raise PaystackError(f"Paystack POST {path} returned status=false: {body.get('message', 'unknown error')}")
        data = body["data"]
        if not isinstance(data, dict):
            raise PaystackError(f"Paystack POST {path}: expected dict in data, got {type(data).__name__}")
        return data

    def _get_dict(self, path: str) -> dict[str, Any]:
        """GET from Paystack and return the ``data`` field as a dict."""
        url = f"{_PAYSTACK_BASE}{path}"
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PaystackError(f"Paystack GET {path} failed: {exc}") from exc

        body: dict[str, Any] = resp.json()
        if not body.get("status"):
            raise PaystackError(f"Paystack GET {path} returned status=false: {body.get('message', 'unknown error')}")
        data = body["data"]
        if not isinstance(data, dict):
            raise PaystackError(f"Paystack GET {path}: expected dict in data, got {type(data).__name__}")
        return data

    def _get_list(self, path: str) -> list[dict[str, Any]]:
        """GET from Paystack and return the ``data`` field as a list."""
        url = f"{_PAYSTACK_BASE}{path}"
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PaystackError(f"Paystack GET {path} failed: {exc}") from exc

        body: dict[str, Any] = resp.json()
        if not body.get("status"):
            raise PaystackError(f"Paystack GET {path} returned status=false: {body.get('message', 'unknown error')}")
        data = body["data"]
        if not isinstance(data, list):
            raise PaystackError(f"Paystack GET {path}: expected list in data, got {type(data).__name__}")
        return data


# Module-level singleton — only created when the env var is present so that
# importing this module in environments without payment credentials does not
# raise at import time.  Callers must check for None before using.
_paystack_secret = os.getenv("PAYSTACK_SECRET_KEY")
paystack_client: PaystackClient | None = PaystackClient(_paystack_secret) if _paystack_secret else None
