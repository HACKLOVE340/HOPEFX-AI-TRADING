# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monetization/activation.py
==========================
The bridge between "a payment completed" and "the customer has what they bought".

Before this module existed there was no such bridge. Three providers were wired
up; each recorded the payment, marked it complete, told the customer their
subscription was active, and left the account on Free. Nothing in the codebase
watched for completion. Revenue reconciled, so nothing looked wrong.

Two functions, deliberately provider-agnostic, so a fourth provider cannot ship
with a fourth subtly different copy:

    resolve_plan_price_usd(plan_id)  — what a plan costs. Never trust the client.
    activate_paid_plan(...)          — grant it, durably.

Storage note
------------
There is no subscriptions table. Two stores exist and they disagree:

  * ``User.plan`` (database/user_models.py) — a durable, indexed column, read by
    the superadmin users API and the billing layer.
  * ``subscription_manager`` (monetization/subscription.py) — a module-level dict
    with no database behind it, read by ``require_plan()`` and all plan gating.

Neither is correct alone: a superadmin plan change is durable but invisible to
gating, while a Stripe activation gates correctly and evaporates on the next
restart. ``activate_paid_plan`` writes **both**, durable first — if the in-memory
step fails the customer still holds what they paid for after a restart. The
reverse order loses it.

That is a correct patch for the payment path, not a fix for the architecture.
Making ``User.plan`` the single source of truth (or adding a real subscriptions
table, which is what trials and renewals actually need) is still outstanding.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from .pricing import SubscriptionTier, pricing_manager

logger = logging.getLogger(__name__)


class UnknownPlanError(ValueError):
    """Raised when a plan id is not in the catalogue, or is not purchasable.

    A domain error rather than an HTTPException: this module is imported by the
    API layer, not the other way round, and the caller decides the status code.
    """


def resolve_plan_price_usd(plan_id: str) -> float:
    """Return the authoritative monthly USD price for `plan_id`.

    The price of a subscription must never come from the request body. Both the
    crypto and Flutterwave checkouts previously accepted a client-supplied
    amount while carrying a `plan_id` that was stored and never used to check it,
    so `{plan_id: "elite", amount_usd: 1}` was a valid request.

    `pricing_manager` is the same catalogue behind `GET /api/billing/plans`, so
    the quote the customer saw and the amount charged cannot diverge.

    Raises UnknownPlanError for an unknown plan, or for a plan with no price
    (Free is not something you can check out).
    """
    tier = pricing_manager.get_tier_by_name(plan_id or "")
    if tier is None:
        raise UnknownPlanError(f"Unknown plan: {plan_id!r}")

    price = Decimal(tier.monthly_price)
    if price <= 0:
        raise UnknownPlanError(f"Plan {plan_id!r} is not purchasable")
    return float(price)


def _get_db_session():
    """Return a SQLAlchemy session from app_state, falling back to SessionLocal."""
    try:
        from core.app_state import app_state

        if app_state and app_state.db_session_factory:
            return app_state.db_session_factory()  # pylint: disable=not-callable
    except Exception as exc:
        logger.warning("activation: app_state db_session_factory unavailable: %s", exc)
    try:
        from database.connection import SessionLocal

        return SessionLocal()
    except Exception as exc:
        logger.warning("activation: SessionLocal fallback failed: %s", exc)
    return None


def activate_paid_plan(
    user_id: str,
    plan_id: str,
    *,
    source: str,
    reference: str | None = None,
    duration_days: int = 30,
) -> bool:
    """Grant `plan_id` to `user_id` after a payment for it completed.

    `source` and `reference` name the provider and its transaction id; they only
    appear in logs, and they are what makes a failure traceable back to a real
    payment.

    Returns True on success. **Never raises.** Callers are webhook and verify
    handlers guarded by idempotency records: if this raised and the handler
    returned 5xx, the provider would retry, the retry would hit the idempotency
    guard, and the grant would be skipped entirely — losing it silently. A
    failure is logged at critical instead, because it means money arrived and
    value did not.
    """
    if not user_id or not plan_id:
        logger.critical(
            "PAID BUT NOT ACTIVATED: missing identity — source=%s reference=%s user_id=%r plan_id=%r",
            source,
            reference,
            user_id,
            plan_id,
        )
        return False

    try:
        tier = SubscriptionTier(plan_id.lower())
    except ValueError:
        logger.critical(
            "PAID BUT NOT ACTIVATED: unknown plan — source=%s reference=%s user_id=%s plan_id=%r",
            source,
            reference,
            user_id,
            plan_id,
        )
        return False

    # (1) Durable write first. This is the record that survives a restart.
    if not _write_user_plan(user_id, tier, source=source, reference=reference):
        return False

    # (2) In-memory manager, so require_plan() sees it without waiting for a
    # restart. A failure here is recoverable — step 1 already succeeded — so it
    # is logged as an error rather than a critical.
    try:
        _write_subscription_manager(user_id, tier, duration_days=duration_days)
    except Exception as exc:
        logger.error(
            "Plan persisted but in-process gating not updated (recovers on restart): "
            "source=%s reference=%s user_id=%s tier=%s err=%s",
            source,
            reference,
            user_id,
            tier.value,
            exc,
            exc_info=True,
        )

    logger.info(
        "Subscription activated: source=%s reference=%s user_id=%s tier=%s",
        source,
        reference,
        user_id,
        tier.value,
    )
    return True


def _write_user_plan(user_id: str, tier: SubscriptionTier, *, source: str, reference: str | None) -> bool:
    """Persist the plan to the users table. Returns False if it could not be written."""
    session = _get_db_session()
    if session is None:
        logger.critical(
            "PAID BUT NOT PERSISTED: no database session — source=%s reference=%s user_id=%s tier=%s",
            source,
            reference,
            user_id,
            tier.value,
        )
        return False
    try:
        from database.user_models import User

        row = session.query(User).filter(User.id == user_id).first()
        if row is None:
            logger.critical(
                "PAID BUT NOT ACTIVATED: no user row — source=%s reference=%s user_id=%s tier=%s",
                source,
                reference,
                user_id,
                tier.value,
            )
            return False
        row.plan = tier.value
        session.commit()
        return True
    except Exception as exc:
        session.rollback()
        logger.critical(
            "PAID BUT NOT PERSISTED: source=%s reference=%s user_id=%s tier=%s err=%s",
            source,
            reference,
            user_id,
            tier.value,
            exc,
            exc_info=True,
        )
        return False
    finally:
        session.close()


def _write_subscription_manager(user_id: str, tier: SubscriptionTier, *, duration_days: int) -> None:
    """Update the in-memory manager so plan gating applies immediately.

    Two behaviours of `create_subscription` make the obvious call wrong:

    * paid tiers are created PENDING, and `is_active()` rejects PENDING, so a
      bare `create_subscription(user_id, tier)` grants nothing. The status must
      be flipped to ACTIVE — which is exactly what the Stripe webhook does.
    * it overwrites `_user_subscriptions[user_id]` unconditionally, orphaning any
      existing subscription. So an existing one is updated in place.

    An existing subscription also has its `end_date` extended. Without that, a
    lapsed customer who renews gets ACTIVE with an end date in the past, and
    `is_active()` — which checks `start <= now <= end` — still returns False.
    They would pay and stay gated.
    """
    from datetime import datetime, timedelta, timezone

    from .subscription import SubscriptionStatus, subscription_manager

    utc = timezone.utc
    now = datetime.now(utc)

    existing = subscription_manager.get_user_subscription(user_id)
    if existing is not None:
        existing.tier = tier
        existing.status = SubscriptionStatus.ACTIVE
        existing.start_date = min(existing.start_date, now)
        existing.end_date = now + timedelta(days=duration_days)
        existing.updated_at = now
        return

    sub = subscription_manager.create_subscription(user_id, tier, duration_days=duration_days)
    sub.status = SubscriptionStatus.ACTIVE
