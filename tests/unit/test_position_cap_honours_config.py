# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_position_cap_honours_config.py
==============================================
Round 3 audit, Slice 1 (docs/HARDENING_BACKLOG.md S1-13, S1-14).

Two defects surfaced by running `tests/unit/test_property_based.py`, which had
never executed in this environment because `hypothesis` was not installed:

**S1-13 — the configured position cap was ignored.** `size_order` and
`calculate_position_size` clamped notional with the *module global*
``_MAX_POSITION_PCT`` (``RISK_MAX_POSITION_PCT``, default 0.05) and never
consulted ``self._config.max_position_size_pct``. A caller constructing
``RiskManager(config=RiskConfig(max_position_size_pct=0.02))`` got 5% applied,
not the 2% it asked for — a risk limit accepted, stored, reported back through
``get_limits()``, and silently not enforced.

**S1-14 — nothing capped risk at the stop.** The manager caps *notional*
(exposure), which is not the same quantity as *loss if the stop is hit*. With a
wide stop a position inside the notional cap can still risk multiples of the
configured limit.

Both predate this round, but both were **masked** by S1-06: Kelly was bounded by
``_MAX_POSITION_PCT`` rather than by a bankroll cap, so it saturated at 0.05 for
every signal and sizing came out small enough that neither cap was ever reached.
Fixing S1-06 (and then S1-12) made Kelly responsive, and the property test that
had been passing for the wrong reason started failing:

    Dollar risk 215.00 exceeds max 200.00 (equity=10000 size=5.0 sl_dist=43.00)

That is the honest sequence: the earlier fix did not introduce the breach, it
removed the accident that was hiding it.
"""

from __future__ import annotations

import pytest


def _rm(max_position_size_pct: float = 0.02):
    from risk.manager import RiskConfig, RiskManager

    return RiskManager(
        config=RiskConfig(
            max_position_size_pct=max_position_size_pct,
            max_drawdown_pct=0.10,
            daily_loss_limit_pct=0.05,
        )
    )


def _size(rm, **kw):
    params = {
        "symbol": "XAUUSD",
        "entry_price": 100.0,
        "account_equity": 10_000.0,
        "direction": "long",
        "signal_strength": 1.0,
        "volatility": 0.15,
        "existing_positions": [],
    }
    params.update(kw)
    return rm.calculate_position_size(**params)


# ── S1-13: the configured cap must be the one enforced ────────────────────────


def test_configured_position_cap_is_enforced_not_the_env_default():
    """A tighter RiskConfig must actually bind."""
    rm = _rm(max_position_size_pct=0.02)
    result = _size(rm, stop_loss_price=57.0, take_profit_price=186.0)

    assert result.notional_usd <= 10_000.0 * 0.02 + 1e-6, (
        f"notional {result.notional_usd} exceeds the configured 2% cap ($200) — "
        f"the module global _MAX_POSITION_PCT (5%) was applied instead of "
        f"config.max_position_size_pct (S1-13)"
    )


def test_the_tighter_of_config_and_env_wins():
    """Config may tighten the env ceiling; it must never loosen it."""
    from risk.manager import _MAX_POSITION_PCT

    loose = _rm(max_position_size_pct=0.99)
    result = _size(loose, stop_loss_price=57.0, take_profit_price=186.0)

    assert result.notional_usd <= 10_000.0 * _MAX_POSITION_PCT + 1e-6, (
        "a permissive RiskConfig raised the position cap above the environment "
        "ceiling — config must only be able to tighten it"
    )


def test_a_looser_config_does_not_shrink_below_what_it_asks_for():
    """Guard against over-correcting into "always use the smallest number"."""
    tight = _size(_rm(0.01), stop_loss_price=99.0, take_profit_price=102.0)
    looser = _size(_rm(0.04), stop_loss_price=99.0, take_profit_price=102.0)
    assert looser.notional_usd >= tight.notional_usd


# ── S1-14: risk at the stop, not just exposure ────────────────────────────────


@pytest.mark.parametrize("sl_offset", [1.0, 5.0, 20.0, 43.0])
def test_loss_at_the_stop_never_exceeds_the_configured_limit(sl_offset):
    """Notional is exposure; this is the number that actually leaves the account.

    A wide stop inside the notional cap can still risk multiples of the limit.
    This is the property `test_property_based.py` asserts.
    """
    rm = _rm(max_position_size_pct=0.02)
    entry, equity = 100.0, 10_000.0
    sl = entry - sl_offset

    result = _size(
        rm,
        entry_price=entry,
        account_equity=equity,
        stop_loss_price=sl,
        take_profit_price=entry + sl_offset * 2.0,
    )

    size = getattr(result, "recommended_size", None) or result.quantity
    if size <= 0:
        return  # refusing to size is always an acceptable outcome

    dollar_risk = size * sl_offset
    max_risk = equity * 0.02
    assert dollar_risk <= max_risk * 1.05, (
        f"a stop hit would lose ${dollar_risk:.2f} against a configured limit of "
        f"${max_risk:.2f} (size={size:.4f} sl_distance={sl_offset}) — the "
        f"manager caps notional but not risk at the stop (S1-14)"
    )


def test_when_the_risk_cap_actually_binds():
    """Documents the narrow case where the risk-at-stop cap does work.

    Worth stating precisely, because it is easy to overclaim. The cap binds only
    when ``stop_distance > entry_price``:

        loss = (notional / entry) * stop_distance <= equity * cap
        and notional is already <= equity * cap
        => it only tightens further when stop_distance / entry > 1

    For a **long** that is impossible — the stop sits below entry, so the
    notional cap already implies the risk cap. It is reachable for a **short**,
    whose stop is above entry and can exceed it. Here the cap pulls notional
    below the minimum position size and the trade is refused outright, which is
    the correct outcome for a trade that cannot be sized within its risk limit.
    """
    rm = _rm(max_position_size_pct=0.02)
    result = _size(
        rm,
        direction="short",
        entry_price=100.0,
        stop_loss_price=250.0,  # 150 away, i.e. further than the entry price
        take_profit_price=40.0,
    )
    size = getattr(result, "recommended_size", None) or result.quantity
    assert size * 150.0 <= 10_000.0 * 0.02 * 1.05, f"a stop hit would lose ${size * 150.0:.2f} against a $200 limit"


def test_long_sizing_is_bounded_by_the_notional_cap_alone():
    """The corollary, asserted so the claim above cannot rot.

    If this ever fails, a long has become able to breach its risk limit and the
    risk-at-stop cap has become load-bearing for longs too.
    """
    rm = _rm(max_position_size_pct=0.02)
    for sl_offset in (1.0, 10.0, 43.0, 90.0):
        result = _size(
            rm,
            stop_loss_price=100.0 - sl_offset,
            take_profit_price=100.0 + sl_offset * 2,
        )
        size = getattr(result, "recommended_size", None) or result.quantity
        assert size * sl_offset <= 10_000.0 * 0.02 * 1.05, (
            f"long with a {sl_offset}-point stop risks ${size * sl_offset:.2f} against a $200 limit"
        )


def test_sizing_without_stops_is_unaffected():
    """Scoping guard: callers that supply no stop keep the notional-only cap."""
    rm = _rm(max_position_size_pct=0.02)
    result = _size(rm)
    assert result.notional_usd <= 10_000.0 * 0.02 + 1e-6
    assert result.quantity >= 0.0
