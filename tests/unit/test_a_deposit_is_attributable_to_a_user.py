# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A confirmed deposit must be attributable to the user who made it.

`POST /payments/deposit` authenticates the caller — `user: TokenPayload =
Depends(get_current_user)` — and then calls `_fiat_deposit_impl(req)`, dropping
that identity on the floor. The Stripe PaymentIntent it creates carries
`metadata={"reference": reference}` and nothing that names the depositor.

The consequence is in the endpoint's own docstring: "The customer is told where
to send money and the system will not recognise it arriving." When
`payment_intent.succeeded` returns through
`api/billing.py::stripe_webhook`, the payload carries the Stripe CUSTOMER id and
our locally generated reference — neither of which this platform can resolve to
a `user_id`. So there is no wallet to credit, and no way to discover which one
it should have been.

That is the missing prerequisite for WALLET-DEAD: the ledger cannot record a
deposit it cannot attribute. These tests pin the link at the only point where
the identity is still in hand — the moment the intent is created.

Docs: docs/audit/plans/2026-09-18-wallet-becomes-the-ledger.md
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any

import pytest


def _fake_stripe(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install a Stripe stub and return the dict its create() call is recorded in."""
    calls: dict[str, Any] = {}

    class _FakeIntent:
        @staticmethod
        def create(**kwargs):
            calls.update(kwargs)
            return SimpleNamespace(client_secret="not-a-secret")  # pragma: allowlist secret

    monkeypatch.setitem(
        sys.modules,
        "stripe",
        SimpleNamespace(api_key="", PaymentIntent=_FakeIntent),
    )
    monkeypatch.setenv("FIAT_PROVIDER", "stripe")
    return calls


def _deposit(monkeypatch: pytest.MonkeyPatch, *, sub: str = "user-abc-123", amount: float = 25.00):
    calls = _fake_stripe(monkeypatch)
    from api.payments import FiatDepositRequest, _fiat_deposit_impl

    user = SimpleNamespace(sub=sub)
    result = asyncio.run(_fiat_deposit_impl(FiatDepositRequest(amount=amount, method="card"), user))
    assert calls, "Stripe was never called; the test never reached the conversion"
    return calls, result


def test_the_payment_intent_names_the_depositing_user(monkeypatch):
    """Without this, a succeeded payment cannot be credited to anybody."""
    calls, _ = _deposit(monkeypatch, sub="user-abc-123")

    metadata = calls.get("metadata") or {}
    assert metadata.get("user_id") == "user-abc-123", (
        "the PaymentIntent carries no user_id, so payment_intent.succeeded cannot be "
        f"attributed to a wallet — metadata was {metadata!r}"
    )


def test_the_reference_is_still_carried(monkeypatch):
    """A control. Adding the user must not displace what was already there."""
    calls, result = _deposit(monkeypatch)

    metadata = calls.get("metadata") or {}
    assert metadata.get("reference"), "the deposit reference was dropped from the metadata"
    assert metadata["reference"] == result["reference"], (
        "the metadata reference and the one returned to the caller disagree, so the "
        "webhook could not match them up"
    )


def test_two_users_depositing_are_not_confused(monkeypatch):
    """The identity must come from the caller, not from module state.

    A module-level or default user would satisfy the first test and still credit
    every deposit to one wallet — the same shape as the shared LLMAgent that put
    one user's account number into another user's prompt (CHAT-SHARED-HISTORY).
    """
    first, _ = _deposit(monkeypatch, sub="user-one")
    second, _ = _deposit(monkeypatch, sub="user-two")

    assert first["metadata"]["user_id"] == "user-one"
    assert second["metadata"]["user_id"] == "user-two"


def test_the_route_hands_the_authenticated_user_through(monkeypatch):
    """The identity exists at the route; the defect was that it stopped there.

    Asserted against the signature rather than the body, because a route that
    accepts `user` and never passes it on is exactly what this closes.
    """
    import inspect

    from api import payments

    impl_params = set(inspect.signature(payments._fiat_deposit_impl).parameters)
    assert "user" in impl_params, (
        "_fiat_deposit_impl still takes only the request, so the authenticated "
        "identity cannot reach the PaymentIntent"
    )

    route_src = inspect.getsource(payments.fiat_deposit)
    assert "_fiat_deposit_impl(req, user)" in route_src or "user=user" in route_src, (
        "the route authenticates a user and then calls the implementation without it"
    )
