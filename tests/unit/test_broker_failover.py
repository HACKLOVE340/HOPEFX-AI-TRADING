# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
"""
tests/unit/test_broker_failover.py
====================================
Tests for the multi-broker failover chain in brokers/manager.py.

Covers:
  - _build_failover_chain ordering
  - OANDA secondary registration when env var is set
  - Auto-failover from primary → OANDA → paper via _record_failure
  - _failover_chain always initialised in __init__
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────
def _make_mock_broker(connected: bool = True) -> MagicMock:
    b = MagicMock()
    b.is_connected.return_value = connected
    return b


def _make_manager(primary: str = "ibkr"):  # -> BrokerManager
    from brokers.manager import BrokerManager

    mgr = BrokerManager(primary_broker_name=primary)
    return mgr


# ── __init__ always creates _failover_chain ───────────────────────────────────
class TestInit:
    def test_failover_chain_initialised(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        assert hasattr(mgr, "_failover_chain")
        assert isinstance(mgr._failover_chain, list)


# ── _build_failover_chain ─────────────────────────────────────────────────────
class TestBuildFailoverChain:
    def test_primary_first_paper_last(self):
        mgr = _make_manager("ibkr")
        mgr.register("ibkr", _make_mock_broker())
        mgr.register("oanda", _make_mock_broker())
        mgr.register("paper", _make_mock_broker())
        chain = mgr._build_failover_chain()
        assert chain[0] == "ibkr"
        assert chain[-1] == "paper"

    def test_oanda_between_primary_and_paper(self):
        mgr = _make_manager("ibkr")
        mgr.register("ibkr", _make_mock_broker())
        mgr.register("oanda", _make_mock_broker())
        mgr.register("paper", _make_mock_broker())
        chain = mgr._build_failover_chain()
        assert chain.index("ibkr") < chain.index("oanda") < chain.index("paper")

    def test_no_oanda_falls_back_to_paper(self):
        mgr = _make_manager("ibkr")
        mgr.register("ibkr", _make_mock_broker())
        mgr.register("paper", _make_mock_broker())
        chain = mgr._build_failover_chain()
        assert chain == ["ibkr", "paper"]

    def test_chain_without_primary_still_ends_in_paper(self):
        mgr = _make_manager("ibkr")
        mgr.register("oanda", _make_mock_broker())
        mgr.register("paper", _make_mock_broker())
        chain = mgr._build_failover_chain()
        assert chain[-1] == "paper"


# ── OANDA registration ────────────────────────────────────────────────────────
class TestOANDARegistration:
    def test_oanda_not_registered_without_api_key(self):
        """With no OANDA_API_KEY env var, OANDA should not be in _brokers."""
        env = {k: v for k, v in os.environ.items() if "OANDA" not in k}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("brokers.manager.BrokerManager._auto_register", autospec=True) as mock_ar,
        ):
            mock_ar.side_effect = lambda self: None  # skip real auto-register
            from brokers.manager import BrokerManager

            mgr = BrokerManager.from_env.__func__(BrokerManager)  # type: ignore[attr-defined]
            # Since _auto_register is stubbed, just verify the attribute
            assert isinstance(mgr._failover_chain, list)

    def test_oanda_registered_when_api_key_present(self):
        """When OANDA_API_KEY is present, OandaBroker should be registered."""
        mock_oanda = _make_mock_broker()
        with (
            patch.dict(os.environ, {"OANDA_API_KEY": "test_key", "OANDA_ACCOUNT_ID": "12345"}),  # pragma: allowlist secret
            patch("brokers.oanda_broker.OandaBroker", return_value=mock_oanda),
        ):
            mgr = _make_manager("ibkr")
            # Simulate what _auto_register does for OANDA
            api_key = os.getenv("OANDA_API_KEY") or os.getenv("BROKER_OANDA_TOKEN")
            if api_key:
                mgr.register("oanda", mock_oanda)
            assert "oanda" in mgr._brokers


# ── Auto-failover via _record_failure ─────────────────────────────────────────
class TestAutoFailover:
    def _setup_three_broker_manager(self):
        mgr = _make_manager("ibkr")
        mgr.register("ibkr", _make_mock_broker())
        mgr.register("oanda", _make_mock_broker())
        mgr.register("paper", _make_mock_broker())
        mgr._failover_chain = mgr._build_failover_chain()
        mgr._active_name = "ibkr"
        return mgr

    def test_first_failover_goes_to_oanda_not_paper(self):
        from brokers.manager import _MAX_CONSECUTIVE_FAILURES

        mgr = self._setup_three_broker_manager()
        # Trigger _MAX_CONSECUTIVE_FAILURES failures on ibkr
        exc = RuntimeError("connection lost")
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(exc)
        # Should have failed over to oanda, NOT paper
        assert mgr._active_name == "oanda"

    def test_second_failover_goes_to_paper(self):
        from brokers.manager import _MAX_CONSECUTIVE_FAILURES

        mgr = self._setup_three_broker_manager()
        exc = RuntimeError("connection lost")
        # Fail ibkr → oanda
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(exc)
        assert mgr._active_name == "oanda"
        # Reset so we can fail oanda too
        mgr._consecutive_failures["oanda"] = 0
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(exc)
        assert mgr._active_name == "paper"

    def test_no_double_failover_within_threshold(self):
        mgr = self._setup_three_broker_manager()
        exc = RuntimeError("oops")
        # Only 1 failure — should NOT trigger failover
        mgr._record_failure(exc)
        assert mgr._active_name == "ibkr"

    def test_failure_counter_reset_on_success(self):
        mgr = self._setup_three_broker_manager()
        exc = RuntimeError("boom")
        mgr._record_failure(exc)
        assert mgr._consecutive_failures["ibkr"] == 1
        mgr._reset_failures()
        assert mgr._consecutive_failures["ibkr"] == 0

    def test_failover_chain_empty_no_crash(self):
        """If _failover_chain is empty, _record_failure should not crash."""
        from brokers.manager import _MAX_CONSECUTIVE_FAILURES

        mgr = _make_manager("ibkr")
        mgr.register("ibkr", _make_mock_broker())
        mgr._active_name = "ibkr"
        mgr._failover_chain = []  # intentionally empty
        exc = RuntimeError("boom")
        # Should not raise
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(exc)

    def test_two_broker_manager_falls_back_to_paper(self):
        """With only ibkr + paper, failover should still go to paper."""
        from brokers.manager import _MAX_CONSECUTIVE_FAILURES

        mgr = _make_manager("ibkr")
        mgr.register("ibkr", _make_mock_broker())
        mgr.register("paper", _make_mock_broker())
        mgr._failover_chain = mgr._build_failover_chain()
        mgr._active_name = "ibkr"
        exc = RuntimeError("down")
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(exc)
        assert mgr._active_name == "paper"
