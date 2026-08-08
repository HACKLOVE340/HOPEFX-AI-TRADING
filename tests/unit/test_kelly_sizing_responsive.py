"""Regression tests: position size must respond to signal quality.

Round 3 audit finding S1-06 (docs/HARDENING_BACKLOG.md).

Three defects compounded so that every trade was sized identically regardless
of what the model said:

1. **``probability`` was never passed.** ``HOPEFXDecisionEngine`` omits it, so
   ``calculate_position_size``'s default of ``0.55`` was used on every trade.
2. **Confidence was floored at 0.7.** ``effective_confidence =
   max(confidence, signal_strength)`` with ``confidence`` defaulting to ``0.7``
   discarded any ML confidence below that — and the ML gate admits signals from
   ``0.52`` upward.
3. **Kelly saturated.** ``_kelly()`` clamped its result with
   ``_MAX_POSITION_PCT`` (0.05) — capping a *bankroll fraction* with a
   *position-size* percentage. With ``p=0.55, conf=0.7`` the raw Kelly is
   ``0.336``, so the clamp bound for any ``p > 0.356``.

Net effect: ``base_notional = equity × 0.05 × 0.25`` — exactly 1.25% of equity
on every single trade, whether the model returned 0.53 or 0.95.
"""

import pytest


@pytest.mark.unit
class TestKellyRespondsToInputs:
    def test_kelly_is_not_saturated_at_the_position_cap(self):
        """A bankroll fraction must not be clamped by a position-size cap."""
        from risk.manager import RiskManager

        low = RiskManager._kelly(probability=0.52, confidence=0.55)
        high = RiskManager._kelly(probability=0.75, confidence=0.90)

        assert high > low, (
            f"Kelly returned {high} for a strong signal and {low} for a marginal "
            "one — it is saturating, so signal quality cannot affect size (S1-06)."
        )

    def test_kelly_is_monotonic_in_probability(self):
        """More edge must never mean less size."""
        from risk.manager import RiskManager

        values = [RiskManager._kelly(probability=p, confidence=0.7) for p in (0.50, 0.55, 0.60, 0.70, 0.80)]
        assert values == sorted(values), f"Kelly not monotonic in probability: {values}"
        assert values[0] < values[-1]

    def test_kelly_is_zero_without_edge(self):
        """Below break-even the Kelly fraction must be zero.

        Break-even here is ``p <= 1/(1+b)`` where ``b = max(0.5, confidence*3)``
        is the payoff term. With ``confidence=0.7`` → ``b=2.1`` → the threshold
        is ``p <= 0.323``.

        Note ``b`` is derived from *confidence*, not from the trade's actual
        reward:risk ratio, so this function treats a 50% win rate as edge on the
        assumption of 2.1:1 odds. That assumption is recorded as a separate
        finding (S1-12) rather than changed here — it is a modelling decision,
        not the unit-confusion bug S1-06 addresses.
        """
        from risk.manager import RiskManager

        assert RiskManager._kelly(probability=0.30, confidence=0.7) == 0.0
        assert RiskManager._kelly(probability=0.10, confidence=0.7) == 0.0
        # Just above the threshold, edge appears.
        assert RiskManager._kelly(probability=0.40, confidence=0.7) > 0.0

    def test_kelly_stays_bounded(self):
        """Even a near-certain signal must not size the whole account."""
        from risk import manager as mod
        from risk.manager import RiskManager

        assert RiskManager._kelly(probability=0.99, confidence=1.0) <= mod._MAX_KELLY_FRACTION


@pytest.mark.unit
class TestSizingRespondsToConfidence:
    def test_confidence_is_not_floored(self):
        """A low-confidence signal must not be sized as if it were 0.7.

        Signals are chosen below the ``_MAX_POSITION_PCT`` cap so this measures
        responsiveness rather than the cap. Above the cap, sizing is
        deliberately flat — that is the position limit doing its job.
        """
        from risk.manager import RiskManager

        rm = RiskManager()
        rm.update_equity(100_000.0)

        weak = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.50,
            probability=0.42,
        )
        strong = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.75,
            probability=0.42,
        )

        assert strong.quantity > weak.quantity, (
            f"weak signal sized {weak.quantity}, strong sized {strong.quantity} — "
            "sizing is not responding to signal quality (S1-06)."
        )

    def test_probability_reaches_sizing(self):
        """The caller's probability must not be silently replaced by a default."""
        from risk.manager import RiskManager

        rm = RiskManager()
        rm.update_equity(100_000.0)

        low_p = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.70,
            probability=0.35,
        )
        high_p = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.70,
            probability=0.45,
        )

        assert high_p.quantity > low_p.quantity, (
            "probability had no effect on size — it is being defaulted away (S1-06)."
        )

    def test_decision_engine_passes_probability(self):
        """The live path must forward the ML probability into sizing."""
        import inspect

        from core.decision import HOPEFXDecisionEngine as mod

        src = inspect.getsource(mod)
        assert "probability=" in src, (
            "HOPEFXDecisionEngine must pass probability= to calculate_position_size, "
            "or Kelly runs on a hardcoded 0.55 for every trade (S1-06)."
        )


@pytest.mark.unit
class TestRiskFactorsCanReachZero:
    def test_scaling_factors_can_block_a_trade(self):
        """S1-07: the minimum-position floor must not resurrect a zeroed size.

        Every risk-reducing factor (data quality, sentiment, macro impact,
        drawdown) multiplies into the notional *before* the floor was applied,
        so a size driven to zero was lifted back to _MIN_POSITION_PCT of equity
        and the trade still opened.
        """
        from risk.manager import RiskManager

        rm = RiskManager()
        rm.update_equity(100_000.0)

        # No edge → Kelly 0 → notional 0. Must stay 0, not be floored back up.
        # With confidence 0.5 the payoff term b is 1.5, so break-even is
        # p <= 1/(1+b) = 0.4; 0.30 is comfortably below it.
        sizing = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.5,
            probability=0.30,
            confidence=0.5,
        )
        assert sizing.quantity == 0.0, (
            f"zero-edge signal sized {sizing.quantity} — the position floor is overriding the risk factors (S1-07)."
        )
        assert not sizing.risk_approval_token, "a refused order must not carry an approval token"
