# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Integration test: the pre-trade invariant gate is actually wired into
RiskManager.size_order() — proving the enforcement facade reaches the money path.

In MONITOR mode (default) a corrupt signal still sizes (no behaviour change); in
ENFORCE mode the same signal is refused (quantity == 0).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_rm(tmp_path):
    from risk.manager import RiskManager

    return RiskManager(halt_state_file=tmp_path / "halt_state.json")


def _signal(**kw):
    s = MagicMock()
    s.confidence = kw.get("confidence", 0.75)
    s.probability = kw.get("probability", 0.55)
    s.direction = kw.get("direction", "long")
    s.symbol = kw.get("symbol", "XAU_USD")
    s.tick_mid = kw.get("tick_mid", 1950.0)
    s.tick_spread = kw.get("tick_spread", 1.0)
    s.data_quality = kw.get("data_quality", 1.0)
    s.features = kw.get("features", {})
    return s


def test_good_signal_sizes_in_enforce_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    rm = _make_rm(tmp_path)
    assert rm.size_order(_signal()).quantity > 0


def test_corrupt_signal_blocked_in_enforce_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    rm = _make_rm(tmp_path)
    # NaN confidence is a non-finite (No Silent Failure) violation → refused.
    result = rm.size_order(_signal(confidence=float("nan")))
    assert result.quantity == pytest.approx(0.0)


def test_monitor_mode_does_not_block_a_good_signal(monkeypatch, tmp_path):
    """Monitor mode must not refuse orders — that is what distinguishes it."""
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    rm = _make_rm(tmp_path)
    result = rm.size_order(_signal())
    assert result.quantity > 0
    assert "invariant" not in (result.reason or "")


def test_corrupt_signal_sizes_zero_even_in_monitor_mode(monkeypatch, tmp_path):
    """A NaN confidence must not produce a tradable position.

    This previously asserted ``quantity > 0`` — a signal whose confidence was
    NaN still opened a real position in monitor mode. That was only reachable
    because ``size_order`` floored the notional with
    ``max(equity * _MIN_POSITION_PCT, ...)`` *after* the scaling factors, so a
    degenerate notional was lifted back to a tradable size (audit finding
    S1-07). With the floor applied as a refusal rather than a lift, corrupt
    input now sizes zero.

    Monitor mode's contract is unchanged and still asserted above: the
    *invariant* does not block. What changed is that arithmetic on a non-finite
    confidence no longer yields a tradable quantity — which is the correct
    outcome for a money-moving system, and the reason S1-07 was a defect rather
    than a tuning choice.
    """
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    rm = _make_rm(tmp_path)
    result = rm.size_order(_signal(confidence=float("nan")))
    assert result.quantity == pytest.approx(0.0)
    # And no approval token is issued for an order that was never really sized.
    assert not result.risk_approval_token
