"""F222 (TODO item 5) — `monetization/access_codes.py` grants paid access untested.

282 lines, named by no test file. It mints the codes that turn into paid
subscriptions, so the properties that matter are the ones an attacker or a
careless caller would probe: can a code be used twice, can a revoked or expired
one still be redeemed, and is the random part actually random.

The audit's earlier triage found no fabricated value here — the SHA-256 is used
as a typo checksum over public parts, with `secrets.choice` for the entropy,
which is the right split. So this file is coverage rather than a fix, and it is
written to fail if any of that changes.

One thing it deliberately does **not** assert: that the checksum is compared in
constant time. It is derived deterministically from the two public halves of the
code, so an attacker can compute it themselves; the secret is the random part,
which is looked up rather than compared. A `compare_digest` here would be
security theatre.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest


def _module():
    """The module object, not the re-exported singleton."""
    import monetization.access_codes  # noqa: F401

    return sys.modules["monetization.access_codes"]


_MOD = _module()
AccessCodeGenerator = _MOD.AccessCodeGenerator
AccessCodeStatus = _MOD.AccessCodeStatus

SubscriptionTier = _MOD.SubscriptionTier


@pytest.fixture
def generator():
    return AccessCodeGenerator()


# ── a code is worth one subscription, not two ────────────────────────────────


def test_a_code_cannot_be_redeemed_twice(generator) -> None:
    """The whole value of a code is that it is spent once."""
    code = generator.generate_code(SubscriptionTier.PROFESSIONAL, duration_days=30)

    assert generator.activate_code(code.code, "user-1", "sub-1") is True
    assert generator.activate_code(code.code, "user-2", "sub-2") is False

    assert code.status is AccessCodeStatus.USED
    assert code.user_id == "user-1", "a second redemption reassigned the code"
    assert code.subscription_id == "sub-1"


def test_a_revoked_code_cannot_be_redeemed(generator) -> None:
    code = generator.generate_code(SubscriptionTier.PROFESSIONAL)
    generator.revoke_code(code.code)

    assert generator.activate_code(code.code, "user-1", "sub-1") is False
    assert code.status is AccessCodeStatus.REVOKED
    assert code.user_id is None


def test_an_expired_code_cannot_be_redeemed(generator) -> None:
    code = generator.generate_code(SubscriptionTier.PROFESSIONAL, duration_days=30)
    code.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    assert generator.activate_code(code.code, "user-1", "sub-1") is False
    assert code.status is AccessCodeStatus.EXPIRED


def test_a_code_expiring_in_the_future_is_still_valid(generator) -> None:
    code = generator.generate_code(SubscriptionTier.PROFESSIONAL, duration_days=1)
    assert code.is_valid() is True


# ── forged and malformed codes ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "forged",
    [
        "HOPEFX-PRO-AAAAAAAA-0000",  # right shape, wrong checksum
        "HOPEFX-PRO-AAAAAAAA",  # too few parts
        "HOPEFX-PRO-AAAAAAAA-0000-EXTRA",  # too many
        "NOTHOPEFX-PRO-AAAAAAAA-0000",  # wrong prefix
        "",
        "----",
    ],
)
def test_a_forged_code_does_not_validate(generator, forged: str) -> None:
    assert generator.validate_code(forged) is False
    assert generator.activate_code(forged, "user-1", "sub-1") is False


def test_a_well_formed_code_that_was_never_issued_is_refused(generator) -> None:
    """Passing the checksum is not the same as existing.

    The checksum is computed from the code's own public halves, so anyone can
    produce one that validates. Redemption has to require issuance.
    """
    issued = generator.generate_code(SubscriptionTier.PROFESSIONAL)
    tier_prefix, random_part = issued.code.split("-")[1:3]
    forged_random = "B" * len(random_part)
    checksum = generator._calculate_checksum(tier_prefix, forged_random)
    forged = f"HOPEFX-{tier_prefix}-{forged_random}-{checksum}"

    assert generator.validate_code(forged) is True, "the forged code should pass the checksum"
    assert generator.get_code(forged) is None
    assert generator.activate_code(forged, "user-1", "sub-1") is False, (
        "a code nobody issued was redeemed because it passed a public checksum"
    )


def test_an_issued_code_validates(generator) -> None:
    code = generator.generate_code(SubscriptionTier.PROFESSIONAL)
    assert generator.validate_code(code.code) is True


# ── the entropy is real ──────────────────────────────────────────────────────


def test_generated_codes_do_not_repeat(generator) -> None:
    codes = {generator.generate_code(SubscriptionTier.PROFESSIONAL).code for _ in range(200)}
    assert len(codes) == 200, "generated codes collided"


def test_the_random_part_uses_the_csprng() -> None:
    """`random` would make issued codes predictable from one leaked sample."""
    import inspect

    source = inspect.getsource(AccessCodeGenerator._generate_random_string)
    assert "secrets." in source
    assert "random." not in source.replace("_generate_random_string", "")


def test_the_random_part_is_long_enough_to_not_be_guessed(generator) -> None:
    code = generator.generate_code(SubscriptionTier.PROFESSIONAL)
    random_part = code.code.split("-")[2]
    assert len(random_part) >= 8, "36^8 is the floor for a code worth a subscription"


# ── batches and bookkeeping ──────────────────────────────────────────────────


def test_a_batch_issues_the_requested_number_of_distinct_codes(generator) -> None:
    batch = generator.generate_batch_codes(SubscriptionTier.PROFESSIONAL, count=25, duration_days=7)

    assert len(batch) == 25
    assert len({item.code for item in batch}) == 25
    assert all(item.duration_days == 7 for item in batch)


def test_the_stats_count_each_code_once(generator) -> None:
    active = generator.generate_code(SubscriptionTier.PROFESSIONAL)
    used = generator.generate_code(SubscriptionTier.PROFESSIONAL)
    generator.activate_code(used.code, "user-1", "sub-1")

    stats = generator.get_code_stats()

    assert stats["total_codes"] == 2
    assert stats["active_codes"] == 1
    assert stats["used_codes"] == 1
    breakdown = stats["tier_breakdown"][SubscriptionTier.PROFESSIONAL.value]
    assert breakdown["total"] == 2
    assert (breakdown["active"], breakdown["used"]) == (1, 1)
    assert active.status is AccessCodeStatus.ACTIVE


def test_redeeming_records_who_and_when(generator) -> None:
    """A grant of paid access with no record of who took it is not auditable."""
    code = generator.generate_code(SubscriptionTier.PROFESSIONAL)

    generator.activate_code(code.code, "user-1", "sub-1")

    assert code.user_id == "user-1"
    assert code.subscription_id == "sub-1"
    assert code.activated_at is not None
    assert code.used_at is not None
