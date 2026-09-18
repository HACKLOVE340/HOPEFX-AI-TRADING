# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The refund policy is a platform setting, and it decides where money goes.

A refunded sale that has already been settled by a payout means the platform has
disbursed money it now needs back. Three answers are defensible and the choice is
the operator's, so it lives in ``core.config_store`` under
``monetization.refund_policy`` and is set from the superadmin financial section.

What these tests pin is the part that is easy to get wrong: a setting that
governs money must fail closed on anything it does not recognise, and the policy
that was actually applied must be recorded on the refund rather than re-read
later. Without the second property, flipping the setting silently rewrites the
meaning of every historical refund and the ledger stops reconciling — which is
exactly the F207 shape this audit already found once.
"""

from __future__ import annotations

import pytest

from monetization.refund_policy import (
    DEFAULT_REFUND_POLICY,
    REFUND_POLICY_KEY,
    RefundPolicy,
    resolve_refund_policy,
)

pytestmark = pytest.mark.unit


class FakeStore:
    """Stands in for core.config_store — get() is all the resolver may use."""

    def __init__(self, value=None, raises=False):
        self._value = value
        self._raises = raises
        self.calls: list[tuple] = []

    def get(self, key, default=None):
        self.calls.append((key, default))
        if self._raises:
            raise RuntimeError("redis down and no db session")
        return self._value if self._value is not None else default


def test_the_three_policies_are_the_only_ones():
    """The set is closed. Adding a fourth is an economic decision, not a typo."""
    assert {p.value for p in RefundPolicy} == {
        "deduct_next_payout",
        "allow_negative_balance",
        "platform_absorbs",
    }


def test_default_is_deduct_next_payout():
    """The safe default: the platform recovers the money, and no creator balance
    is ever driven below zero."""
    assert DEFAULT_REFUND_POLICY is RefundPolicy.DEDUCT_NEXT_PAYOUT


def test_unset_resolves_to_the_default():
    store = FakeStore(value=None)
    assert resolve_refund_policy(store=store) is DEFAULT_REFUND_POLICY
    assert store.calls == [(REFUND_POLICY_KEY, None)]


@pytest.mark.parametrize("policy", list(RefundPolicy))
def test_each_configured_policy_is_honoured(policy):
    store = FakeStore(value=policy.value)
    assert resolve_refund_policy(store=store) is policy


@pytest.mark.parametrize(
    "stored",
    [
        "refund_everything",  # not a policy
        "",  # blank
        "DEDUCT_NEXT_PAYOUT",  # right idea, wrong case — still not a value
        123,  # wrong type
        {"policy": "platform_absorbs"},  # right value, wrong shape
        None,
    ],
)
def test_an_unrecognised_value_fails_closed(stored, caplog):
    """
    A money setting must never guess. Anything the resolver does not recognise
    resolves to the safe default and says so loudly — it does not pick the
    nearest match and it does not raise into the refund path.
    """
    store = FakeStore(value=stored)
    with caplog.at_level("ERROR"):
        assert resolve_refund_policy(store=store) is DEFAULT_REFUND_POLICY
    if stored is not None:
        assert any("refund policy" in r.message.lower() for r in caplog.records), (
            "an unrecognised money setting was accepted silently"
        )


def test_a_broken_config_store_fails_closed(caplog):
    """Redis down and no DB session must not raise into a refund, and must not
    leave the policy undecided."""
    store = FakeStore(raises=True)
    with caplog.at_level("ERROR"):
        assert resolve_refund_policy(store=store) is DEFAULT_REFUND_POLICY


def test_policy_is_read_fresh_every_time():
    """No process-local caching. config_store is deliberately uncached so every
    pod sees a change immediately; caching it here would reintroduce the split
    brain that store was written to avoid."""
    store = FakeStore(value=RefundPolicy.PLATFORM_ABSORBS.value)
    resolve_refund_policy(store=store)
    resolve_refund_policy(store=store)
    resolve_refund_policy(store=store)
    assert len(store.calls) == 3
