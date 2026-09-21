# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monetization/refund_policy.py
=============================
What happens to a creator's money when a sale is refunded after it has been paid
out.

Once a payout has settled a sale, the creator's share has left the platform. If
that sale is then refunded, the buyer's money has to come back from somewhere and
there are three defensible answers. Which one applies is an economic decision for
the operator, not something to hardcode, so it lives in ``core.config_store``
under ``monetization.refund_policy`` and is set from the superadmin financial
section.

Two properties matter more than the choice itself:

**Fail closed.** A value this module does not recognise resolves to the safe
default and is logged as an error. It never guesses at the nearest match and
never raises into a refund path. A money setting that silently accepts garbage is
worse than one that is missing.

**Stamp, do not re-read.** The policy in force must be recorded on the refund at
the moment it is applied. Re-deriving it later from the live setting means
flipping the setting rewrites the meaning of every historical refund, and the
ledger stops reconciling — the same defect shape as F207, where every payout
claimed every historical transaction. Callers use
:func:`resolve_refund_policy` once, act on it, and persist what they used.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

#: The config_store key. Also the audit-log subject when a superadmin changes it.
REFUND_POLICY_KEY = "monetization.refund_policy"


class RefundPolicy(StrEnum):
    """How a refund of an already-settled sale is recovered."""

    #: Withhold the refunded amount from the creator's next payout. The balance
    #: never goes below zero and the platform is made whole. Safe default.
    DEDUCT_NEXT_PAYOUT = "deduct_next_payout"

    #: Debit the creator's balance immediately, even into the negative. Recovers
    #: faster and shows the true position, at the cost of balances that read as
    #: a debt the creator may never clear.
    ALLOW_NEGATIVE_BALANCE = "allow_negative_balance"

    #: The platform eats the creator's share and refunds the buyer in full from
    #: platform funds. Best creator experience, and the platform carries the loss.
    PLATFORM_ABSORBS = "platform_absorbs"


#: Chosen because it is the only one of the three that both recovers the money
#: and cannot drive a creator balance negative.
DEFAULT_REFUND_POLICY = RefundPolicy.DEDUCT_NEXT_PAYOUT


def resolve_refund_policy(store: Any | None = None) -> RefundPolicy:
    """
    Return the refund policy currently in force.

    Reads ``core.config_store`` fresh on every call. That store is deliberately
    uncached so a change on one pod is visible to the others immediately;
    caching here would reintroduce the split brain it was written to avoid.

    Any failure — store unavailable, unset key, unrecognised value, wrong type —
    resolves to :data:`DEFAULT_REFUND_POLICY`. Anything other than "unset" is
    logged at ERROR, because a money setting the platform cannot read is an
    operational problem someone has to see.
    """
    if store is None:
        try:
            from core.config_store import config_store as store
        except Exception:
            logger.exception("Refund policy: config store unavailable — falling back to %s", DEFAULT_REFUND_POLICY)
            return DEFAULT_REFUND_POLICY

    try:
        raw = store.get(REFUND_POLICY_KEY, None)
    except Exception:
        logger.exception("Refund policy: read failed — falling back to %s", DEFAULT_REFUND_POLICY)
        return DEFAULT_REFUND_POLICY

    if raw is None:
        # Never configured. Not an error — the default is a real answer.
        return DEFAULT_REFUND_POLICY

    try:
        return RefundPolicy(raw)
    except (ValueError, TypeError):
        logger.error(
            "Refund policy: stored value %r is not one of %s — falling back to %s. "
            "A superadmin set this to something the platform cannot honour.",
            raw,
            [p.value for p in RefundPolicy],
            DEFAULT_REFUND_POLICY.value,
        )
        return DEFAULT_REFUND_POLICY


def describe_policies() -> list[dict[str, str]]:
    """The three options and what each one means, for the settings UI.

    Kept here rather than in the frontend so the wording that describes where
    money goes has exactly one source.
    """
    return [
        {
            "value": RefundPolicy.DEDUCT_NEXT_PAYOUT.value,
            "label": "Deduct from next payout",
            "description": (
                "Withhold the refunded amount from the creator's next payout. "
                "The platform is made whole and no balance goes below zero."
            ),
            "recommended": "true",
        },
        {
            "value": RefundPolicy.ALLOW_NEGATIVE_BALANCE.value,
            "label": "Debit immediately, allow negative",
            "description": (
                "Debit the creator's balance now, even into the negative. "
                "Recovers faster and shows the true position, but a creator can "
                "be left owing money they may never clear."
            ),
            "recommended": "false",
        },
        {
            "value": RefundPolicy.PLATFORM_ABSORBS.value,
            "label": "Platform absorbs the loss",
            "description": (
                "Refund the buyer in full from platform funds and leave the "
                "creator's earnings untouched. Best for creators; the platform "
                "carries the loss."
            ),
            "recommended": "false",
        },
    ]
