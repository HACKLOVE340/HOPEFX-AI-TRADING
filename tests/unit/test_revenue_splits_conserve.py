# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""A revenue split must add back up to the amount actually charged.

Found by counting the other places with the same shape after fixing the
sub-account transfer endpoint, which computed each side of a movement with its
own ``round(x, 2)`` and therefore did not conserve. Two marketplaces split a
purchase the same way:

    social/marketplace.py:92-93
        platform_fee   = round(price * PLATFORM_FEE_PCT, 2)
        creator_payout = round(price - platform_fee, 2)

    monetization/marketplace.py:1029-1030
        platform_fee   = round(price * 0.20, 2)
        creator_payout = round(price * 0.80, 2)

Both are exact when the price is already at cent precision, and both break when
it is not — measured at half a cent per purchase, created or destroyed
depending on the tie-break that ``round``'s banker's rounding happens to pick:

    price=10.025  ->  social 10.030 (+0.005)   monetization 10.030 (+0.005)
    price=12.575  ->  social 12.570 (-0.005)   monetization 12.580 (+0.005)
    price= 4.995  ->  social  5.000 (+0.005)   monetization  5.000 (+0.005)

A sub-cent price is reachable: both listing models declare ``price: float = 0.0``
with no cent constraint, exactly as the transfer endpoint's ``initial_balance``
did. The exposure is smaller than the transfer's — a purchase is one movement
rather than a compounding loop — but the defect is the same one, and the money
lands in a creator's payout.

The fix in both is the same shape as the transfer's: quantise once, then derive
the other side by subtraction so the split conserves by construction rather than
by luck.

What it conserves against is the *charged* amount, not the listed price — see
``_charged`` below, and the first assertion this file got wrong.
"""

from __future__ import annotations

import pytest

# Prices chosen to sit on and around the sub-cent boundary. The cent-precision
# ones must keep passing — they always did, and a fix that changed them would
# be restating existing receipts.
PRICES = [9.99, 19.99, 0.05, 33.33, 100.0, 10.025, 12.575, 4.995, 0.015, 7.335]


def _approx(value: float) -> pytest.approx:
    return pytest.approx(value, abs=1e-9)


def _charged(price: float) -> float:
    """What a sub-cent listing actually bills.

    The first version of this file asserted ``fee + payout == price`` and failed
    on every sub-cent case against a correct implementation. That was the test
    being wrong: 10.025 cannot be charged to a card, so the split has nothing to
    conserve it against. What must hold is that the split adds up to the amount
    actually billed, and that the billed amount is the listed price rounded to
    the nearest cent — never more than half a cent away from it.

    This differs from the transfer endpoint deliberately. There the sub-cent
    values are *stored balances*, which are real and must not be restated on a
    read, so the transfer conserves against the raw totals. Here the sub-cent
    value is a *price*, which has to become a chargeable amount before anyone
    can split it.
    """
    from decimal import ROUND_HALF_UP, Decimal

    return float(Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class TestSocialMarketplaceSplit:
    @pytest.mark.parametrize("price", PRICES)
    def test_fee_plus_payout_equals_the_charged_amount(self, price: float):
        from social.marketplace import StrategyMarketplace

        market = StrategyMarketplace()
        fee, payout = market.split_revenue(price)
        assert fee + payout == _approx(_charged(price)), f"price {price} split into {fee} + {payout} = {fee + payout}"

    @pytest.mark.parametrize("price", PRICES)
    def test_the_charged_amount_stays_within_half_a_cent_of_the_listing(self, price: float):
        from social.marketplace import StrategyMarketplace

        fee, payout = StrategyMarketplace().split_revenue(price)
        assert abs((fee + payout) - price) <= 0.005 + 1e-9

    @pytest.mark.parametrize("price", PRICES)
    def test_neither_side_is_negative(self, price: float):
        from social.marketplace import StrategyMarketplace

        fee, payout = StrategyMarketplace().split_revenue(price)
        assert fee >= 0 and payout >= 0

    def test_the_platform_takes_its_stated_cut_at_cent_prices(self):
        """The fix must not quietly change the commercial terms."""
        from social.marketplace import StrategyMarketplace

        market = StrategyMarketplace()
        fee, payout = market.split_revenue(100.0)
        assert fee == _approx(100.0 * market.PLATFORM_FEE_PCT)
        assert payout == _approx(80.0)


class TestMonetizationMarketplaceSplit:
    @pytest.mark.parametrize("price", PRICES)
    def test_fee_plus_payout_equals_the_charged_amount(self, price: float):
        from monetization.marketplace import split_revenue

        fee, payout = split_revenue(price)
        assert fee + payout == _approx(_charged(price)), f"price {price} split into {fee} + {payout} = {fee + payout}"

    @pytest.mark.parametrize("price", PRICES)
    def test_the_charged_amount_stays_within_half_a_cent_of_the_listing(self, price: float):
        from monetization.marketplace import split_revenue

        fee, payout = split_revenue(price)
        assert abs((fee + payout) - price) <= 0.005 + 1e-9

    def test_the_platform_takes_its_stated_cut_at_cent_prices(self):
        from monetization.marketplace import split_revenue

        fee, payout = split_revenue(100.0)
        assert fee == _approx(20.0)
        assert payout == _approx(80.0)


class TestBothMarketplacesAgree:
    """Two implementations of one commercial rule must not disagree.

    They already both take 20%. If one is fixed and the other is not, a creator's
    payout depends on which code path sold the strategy.
    """

    @pytest.mark.parametrize("price", PRICES)
    def test_same_price_yields_the_same_split(self, price: float):
        from monetization.marketplace import split_revenue as monetization_split
        from social.marketplace import StrategyMarketplace

        social_fee, social_payout = StrategyMarketplace().split_revenue(price)
        monet_fee, monet_payout = monetization_split(price)
        assert social_fee == _approx(monet_fee)
        assert social_payout == _approx(monet_payout)
