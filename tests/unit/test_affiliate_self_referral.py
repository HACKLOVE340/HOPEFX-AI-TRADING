# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_affiliate_self_referral.py
==========================================
Regression: create_referral must reject self-referral (an affiliate earning
commission on their own subscription).
"""

from __future__ import annotations

from monetization.affiliate import AffiliateManager


def test_self_referral_rejected():
    mgr = AffiliateManager()
    aff = mgr.create_affiliate(user_id="user-1")
    aff.approve()

    # Same user referring themselves via their own code → rejected.
    out = mgr.create_referral(affiliate_code=aff.code, referred_user_id="user-1")
    assert out is None


def test_legitimate_referral_allowed():
    mgr = AffiliateManager()
    aff = mgr.create_affiliate(user_id="user-1")
    aff.approve()

    out = mgr.create_referral(affiliate_code=aff.code, referred_user_id="user-2")
    assert out is not None
    assert out.referred_user_id == "user-2"
