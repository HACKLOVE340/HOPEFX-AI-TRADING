# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A permanently-unknown regime must be visible, not silent.

``RegimeRouter.route()`` is never called anywhere in the repo, so
``_last_regime`` keeps its constructor value — ``"unknown"`` — for the life of
the process. That reaches position sizing:

    core/signal_engine.py:1470  regime_name = signal_payload.get("regime", "UNKNOWN")
    core/signal_engine.py:1471  regime_scalar = get_regime_position_scalar(regime_name)
    core/signal_engine.py:1472  if regime_scalar < 1.0: scaled_size = ... * regime_scalar

so **every** position on the platform is scaled by the UNKNOWN entry (F94).

**What is deliberately not changed here.** ``UNKNOWN: 0.5`` is an explicit key
in ``_DEFAULT_REGIME_SIZE_MAP``, overridable by the ``REGIME_SIZE_MAP`` env var.
It is a risk policy — "when you do not know the regime, take half a position" —
and the sizing code's own comment calls the overlay one that "never increases
size above the risk-manager-approved maximum, only reduces it in adverse
regimes". Raising it to 1.0 would double every position on the platform. That is
weakening a risk control, which CLAUDE.md forbids without explicit instruction,
and it is the dangerous direction to be wrong in.

The defect is not the number. It is that a conservative fallback became the
universal case and nothing said so. These tests pin the visibility.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_warning_state():
    """The warning is rate-limited by module state; each test starts fresh."""
    import core.signal_engine as se

    se._regime_unknown_warned = False
    yield
    se._regime_unknown_warned = False


def test_the_unknown_regime_scalar_is_unchanged():
    """The risk policy itself must survive this fix untouched."""
    from core.signal_engine import _REGIME_SIZE_MAP, get_regime_position_scalar

    assert get_regime_position_scalar("unknown") == _REGIME_SIZE_MAP["UNKNOWN"]


def test_an_unknown_regime_says_so(caplog):
    """Before this, every position on the platform was halved and the only
    trace was an INFO line that read like normal regime scaling."""
    from core.signal_engine import get_regime_position_scalar

    with caplog.at_level("WARNING"):
        get_regime_position_scalar("unknown")

    text = " ".join(r.message for r in caplog.records).lower()
    assert "regime" in text, "an undetected regime scaled the position silently"
    assert "route" in text, "the warning does not point at why the regime is missing"


def test_the_warning_does_not_repeat_on_every_signal(caplog):
    """This is on the per-signal sizing path. A warning per order would bury the
    log it is meant to make readable."""
    from core.signal_engine import get_regime_position_scalar

    with caplog.at_level("WARNING"):
        for _ in range(50):
            get_regime_position_scalar("unknown")

    regime_warnings = [r for r in caplog.records if "regime" in r.message.lower()]
    assert len(regime_warnings) == 1, f"warned {len(regime_warnings)} times on 50 signals"


def test_a_known_regime_warns_about_nothing(caplog):
    from core.signal_engine import get_regime_position_scalar

    with caplog.at_level("WARNING"):
        get_regime_position_scalar("TRENDING_UP")

    assert not [r for r in caplog.records if "regime" in r.message.lower()]


def test_a_regime_that_is_not_in_the_map_at_all_is_also_flagged(caplog):
    """Distinct from UNKNOWN: a name the map has never heard of means the
    detector and the size map disagree, which nobody would otherwise see."""
    from core.signal_engine import get_regime_position_scalar

    with caplog.at_level("WARNING"):
        scalar = get_regime_position_scalar("nonsense-regime")

    assert scalar == 0.5, "an unrecognised regime must stay on the conservative default"
    text = " ".join(r.message for r in caplog.records).lower()
    assert "nonsense-regime" in text


@pytest.mark.parametrize(
    "regime", ["TRENDING_UP", "TRENDING_DOWN", "MEAN_REVERTING", "RANGE_BOUND", "HIGH_VOL", "LOW_VOL"]
)
def test_a_known_regime_keeps_its_configured_scalar(regime):
    from core.signal_engine import _REGIME_SIZE_MAP, get_regime_position_scalar

    assert get_regime_position_scalar(regime) == _REGIME_SIZE_MAP[regime]


def test_every_configured_regime_is_reachable_case_insensitively():
    """The lookup upper-cases its argument and the caller passes whatever
    status() returned. A map entry that cannot be reached is a scalar nobody
    gets."""
    from core.signal_engine import _REGIME_SIZE_MAP, get_regime_position_scalar

    for name, expected in _REGIME_SIZE_MAP.items():
        assert get_regime_position_scalar(name.lower()) == expected
        assert get_regime_position_scalar(name.upper()) == expected
