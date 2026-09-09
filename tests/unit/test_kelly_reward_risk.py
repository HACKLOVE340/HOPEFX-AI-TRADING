# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_kelly_reward_risk.py
====================================
Round 3 audit, Slice 1 (docs/HARDENING_BACKLOG.md S1-12).

``RiskManager._kelly`` derived the Kelly payoff term from model *confidence*:

    b = max(0.5, confidence * 3.0)
    kelly = (p * b - q) / b

In the Kelly criterion ``b`` is the **reward-to-risk ratio of the trade** — how
much is won per unit risked. Confidence is a different quantity, so break-even
moved with the model's certainty rather than with the trade's actual stop and
target: at ``confidence=0.7`` (``b=2.1``) any win probability above **0.323**
counted as positive edge, on the strength of 2.1:1 odds nothing verified.

The caller has the real numbers. These tests pin that ``b`` now comes from the
stop and target when they are known, and that the classic sanity check holds: a
1:1 trade must require ``p > 0.5`` before it sizes at all.

These tests build a ``RiskManager`` with no orchestrator, so they pass
``data_quality=1.0`` explicitly. That value used to arrive by itself: the gate
in ``size_order`` read ``getattr(signal, "data_quality", 1.0)`` and
``_MinimalSignal`` hardcoded ``1.0``, so an unmeasured feed scored perfect and
the gate could not fire. Both are fixed (MASTER_OUTSTANDING §E12), and the
assumption these tests were always making now has to be stated out loud.
"""

from __future__ import annotations

import pytest


def _rm():
    from risk.manager import RiskManager

    return RiskManager()


# ── the payoff term ───────────────────────────────────────────────────────────


def test_even_money_trade_needs_better_than_a_coin_flip():
    """The textbook property the confidence proxy destroyed.

    At 1:1 odds Kelly is (p*1 - q)/1 = 2p - 1, so anything at or below p=0.5
    must size zero. Under the old formula a p=0.45 signal at confidence 0.7
    sized positive, because b=2.1 was assumed rather than measured.
    """
    rm = _rm()
    assert rm._kelly(0.50, confidence=0.7, reward_risk=1.0) == pytest.approx(0.0)
    assert rm._kelly(0.45, confidence=0.7, reward_risk=1.0) == pytest.approx(0.0)
    assert rm._kelly(0.60, confidence=0.7, reward_risk=1.0) > 0.0


def test_payoff_term_is_read_from_the_trade_not_the_model():
    """Same probability, different stops — different size."""
    rm = _rm()
    p = 0.55
    tight = rm._kelly(p, confidence=0.7, reward_risk=1.0)
    wide = rm._kelly(p, confidence=0.7, reward_risk=3.0)
    assert wide > tight, (
        "a 3:1 trade must size larger than a 1:1 trade at the same win "
        "probability — the payoff term is not reaching the formula"
    )


def test_confidence_no_longer_moves_the_payoff_term():
    """The S1-12 defect itself: b must not track confidence."""
    rm = _rm()
    low = rm._kelly(0.55, confidence=0.30, reward_risk=2.0)
    high = rm._kelly(0.55, confidence=0.95, reward_risk=2.0)
    assert low == pytest.approx(high), (
        "changing confidence changed the Kelly fraction at a fixed reward:risk — "
        "confidence is still being used as the payoff term"
    )


def test_falls_back_to_the_confidence_proxy_when_no_ratio_is_known():
    """Callers without stops keep the old behaviour rather than breaking."""
    rm = _rm()
    legacy = rm._kelly(0.55, confidence=0.7)
    assert legacy == pytest.approx(rm._kelly(0.55, confidence=0.7, reward_risk=None))
    assert legacy > 0.0


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_a_nonsense_ratio_does_not_produce_a_nonsense_size(bad):
    """A zero or non-finite ratio must not divide by zero or size infinitely."""
    rm = _rm()
    out = rm._kelly(0.60, confidence=0.7, reward_risk=bad)
    assert 0.0 <= out <= 0.5


def test_kelly_stays_bounded():
    rm = _rm()
    assert rm._kelly(0.99, confidence=0.99, reward_risk=10.0) <= 0.5
    assert rm._kelly(0.01, confidence=0.01, reward_risk=10.0) >= 0.0


# ── the ratio must reach _kelly from the caller ───────────────────────────────


def test_default_ratio_matches_the_stops_the_manager_actually_sets():
    """`b` must agree with `_compute_stop_take`, not be a second constant.

    `_compute_stop_take` places the stop at 1x ATR and the target at 2x, so the
    default payoff is 2.0. Deriving it from the same multiples keeps the two
    from drifting apart — the duplication failure mode from S13-01.
    """
    from risk.manager import _DEFAULT_REWARD_RISK

    rm = _rm()
    mid, atr = 2350.0, 10.0
    sl, tp = rm._compute_stop_take("long", mid, atr)
    assert abs(tp - mid) / abs(mid - sl) == pytest.approx(_DEFAULT_REWARD_RISK)

    sl_s, tp_s = rm._compute_stop_take("short", mid, atr)
    assert abs(mid - tp_s) / abs(sl_s - mid) == pytest.approx(_DEFAULT_REWARD_RISK)


@pytest.mark.parametrize(
    ("direction", "entry", "sl", "tp", "expected"),
    [
        ("long", 2350.0, 2340.0, 2370.0, 2.0),
        ("long", 2350.0, 2340.0, 2360.0, 1.0),
        ("short", 2350.0, 2360.0, 2320.0, 3.0),
    ],
)
def test_reward_risk_is_derived_from_supplied_stops(direction, entry, sl, tp, expected):
    rm = _rm()
    got = rm._reward_risk_from_prices(entry_price=entry, stop_loss=sl, take_profit=tp)
    assert got == pytest.approx(expected)


def test_reward_risk_is_none_when_the_stop_is_missing_or_degenerate():
    """No stop means no measurable risk — fall back rather than invent one."""
    rm = _rm()
    assert rm._reward_risk_from_prices(2350.0, None, 2370.0) is None
    assert rm._reward_risk_from_prices(2350.0, 2340.0, None) is None
    # Stop at the entry: risk is zero, ratio undefined.
    assert rm._reward_risk_from_prices(2350.0, 2350.0, 2370.0) is None


def test_supplied_stops_reach_sizing_end_to_end():
    """A 1:1 trade at p=0.5 must size nothing, through the public API."""
    rm = _rm()
    rm.update_equity(100_000.0)

    even_money = rm.calculate_position_size(
        symbol="XAUUSD",
        entry_price=2350.0,
        account_equity=100_000.0,
        direction="long",
        probability=0.50,
        confidence=0.70,
        stop_loss_price=2340.0,
        take_profit_price=2360.0,  # 1:1
        data_quality=1.0,
    )
    assert even_money.quantity == pytest.approx(0.0), (
        "a coin-flip trade at 1:1 odds was sized — the supplied stops are not reaching the Kelly payoff term"
    )

    # Control: the same probability with a 3:1 target is a real edge.
    favourable = rm.calculate_position_size(
        symbol="XAUUSD",
        entry_price=2350.0,
        account_equity=100_000.0,
        direction="long",
        probability=0.50,
        confidence=0.70,
        stop_loss_price=2340.0,
        take_profit_price=2380.0,  # 3:1
        data_quality=1.0,
    )
    assert favourable.quantity > 0.0


def test_callers_without_stops_keep_their_existing_size():
    """Scoping guard: this fix must not silently resize every legacy caller.

    `confidence` feeds nothing in `size_order` except `_kelly`. If a
    reward:risk ratio were always supplied, confidence would drop out of sizing
    entirely and size would stop responding to signal quality — a bigger change
    than S1-12 asks for. Callers that pass no stops must be untouched.
    """
    rm = _rm()
    rm.update_equity(100_000.0)

    def _kelly_f(conf):
        # Assert on kelly_f, not notional: notional is clamped by
        # _MAX_POSITION_PCT (5% of equity), which hides the difference at this
        # account size.
        return rm.calculate_position_size(
            symbol="XAUUSD",
            entry_price=2350.0,
            account_equity=100_000.0,
            direction="long",
            probability=0.58,
            confidence=conf,
            data_quality=1.0,
        ).kelly_f

    low, high = _kelly_f(0.40), _kelly_f(0.95)
    assert high > low, (
        "confidence no longer affects the Kelly fraction of a stop-less order — "
        "the reward:risk ratio is being applied where it was not measured"
    )


def test_only_real_numbers_may_set_the_payoff_term():
    """`float()` is too permissive to gate a money decision on.

    Anything implementing ``__float__`` satisfies ``float(x)`` — a Mock returns
    1.0. That turned a signal carrying no stops into a fabricated 1:1 ratio and
    sized a trade that should have been refused (caught by
    test_pre_trade_invariant_gate, whose signal is a MagicMock). Only a genuine
    int/float may set ``b``.
    """
    from unittest.mock import MagicMock

    rm = _rm()
    assert rm._reward_risk_from_prices(1950.0, MagicMock(), MagicMock()) is None
    assert rm._reward_risk_from_prices(MagicMock(), 2340.0, 2370.0) is None
    assert rm._reward_risk_from_prices(1950.0, "2340", "2370") is None
    assert rm._reward_risk_from_prices(1950.0, True, 2370.0) is None
    assert rm._reward_risk_from_prices(1950.0, float("nan"), 2370.0) is None
    # ...and a real pair still works.
    assert rm._reward_risk_from_prices(2350.0, 2340.0, 2370.0) == pytest.approx(2.0)


def test_a_corrupt_signal_still_sizes_zero():
    """Regression guard for the interaction above, at the sizing level."""
    from unittest.mock import MagicMock

    rm = _rm()
    rm.update_equity(100_000.0)

    sig = MagicMock()
    sig.confidence = float("nan")
    sig.probability = 0.55
    sig.direction = "long"
    sig.symbol = "XAU_USD"
    sig.tick_mid = 1950.0
    sig.tick_spread = 1.0
    sig.data_quality = 1.0
    sig.features = {}

    assert rm.size_order(sig).quantity == pytest.approx(0.0), (
        "a signal with non-finite confidence sized a real position — the "
        "reward:risk helper accepted fabricated Mock stops"
    )
