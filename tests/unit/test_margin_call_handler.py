# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for risk/margin_call_handler.py

Coverage:
- MarginCallHandler.handle(): resolve via position closure
- MarginCallHandler.handle(): resolve via equity injection
- MarginCallHandler.handle(): suspend when unresolvable
- Alert callbacks are invoked on handle()
- broker_close_fn receives (symbol, qty) — not notional USD
- MarginCallHandler.history() returns serialisable list
- register_alert_callback() appends callback
- MarginCallEvent dataclass defaults
- MarginCallHandler with no positions / no broker_close_fn
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from risk.margin_call_handler import (
    MarginCallAction,
    MarginCallEvent,
    MarginCallHandler,
    MarginCallResponse,
    margin_call_handler,
)

UTC = timezone.utc


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_event(
    broker_name: str = "TestBroker",
    deficit: float = 1000.0,
    equity: float = 5000.0,
    maintenance: float = 2000.0,
) -> MarginCallEvent:
    return MarginCallEvent(
        broker_name=broker_name,
        account_id="ACC-001",
        margin_deficit_usd=deficit,
        equity_usd=equity,
        maintenance_margin_usd=maintenance,
    )


def _make_positions() -> list[dict]:
    return [
        {
            "symbol": "XAUUSD",
            "notional_usd": 50_000.0,
            "pnl_usd": -300.0,
            "leverage": 10.0,
            "qty": 1.0,
            "margin_pct": 0.02,
        },
        {
            "symbol": "EURUSD",
            "notional_usd": 20_000.0,
            "pnl_usd": 50.0,
            "leverage": 5.0,
            "qty": 0.5,
            "margin_pct": 0.02,
        },
    ]


# ── MarginCallEvent ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarginCallEvent:
    def test_timestamp_defaults_to_utc_now(self):
        event = _make_event()
        assert event.timestamp.tzinfo is not None
        assert abs((datetime.now(UTC) - event.timestamp).total_seconds()) < 2

    def test_metadata_defaults_to_empty_dict(self):
        event = _make_event()
        assert event.metadata == {}

    def test_fields_set_correctly(self):
        event = _make_event(broker_name="Oanda", deficit=2000.0)
        assert event.broker_name == "Oanda"
        assert event.margin_deficit_usd == 2000.0
        assert event.equity_usd == 5000.0


# ── MarginCallHandler — basic resolution ─────────────────────────────────────

@pytest.mark.unit
class TestMarginCallHandlerResolution:
    def test_resolve_via_position_closure(self):
        """Closing one high-leverage position should resolve the deficit."""
        handler = MarginCallHandler(auto_close_enabled=True)
        event = _make_event(deficit=800.0)
        positions = _make_positions()

        close_calls = []

        def fake_close(symbol: str, qty: float) -> bool:
            close_calls.append((symbol, qty))
            return True

        response = handler.handle(event, open_positions=positions, broker_close_fn=fake_close)

        assert response.resolved is True
        assert response.suspended is False
        assert response.final_status == MarginCallAction.RESOLVED.value
        assert len(response.positions_closed) >= 1

    def test_broker_close_fn_receives_qty_not_notional(self):
        """broker_close_fn must be called with native qty, not notional_usd."""
        handler = MarginCallHandler(auto_close_enabled=True)
        event = _make_event(deficit=100.0)
        positions = [
            {
                "symbol": "XAUUSD",
                "notional_usd": 50_000.0,
                "pnl_usd": -100.0,
                "leverage": 20.0,
                "qty": 2.5,
                "margin_pct": 0.02,
            }
        ]

        received_args = []

        def fake_close(symbol: str, qty: float) -> bool:
            received_args.append((symbol, qty))
            return True

        handler.handle(event, open_positions=positions, broker_close_fn=fake_close)

        assert len(received_args) == 1
        sym, qty = received_args[0]
        assert sym == "XAUUSD"
        assert qty == 2.5  # native qty, NOT 50_000 notional

    def test_resolve_via_equity_injection(self):
        """When positions cover only part of the deficit, injection resolves the rest."""
        handler = MarginCallHandler(
            auto_close_enabled=False,  # no position closure
            max_equity_injection_usd=2000.0,
        )
        event = _make_event(deficit=1500.0)
        response = handler.handle(event, open_positions=[], broker_close_fn=None)

        assert response.resolved is True
        assert response.equity_injected_usd > 0

    def test_suspend_when_unresolvable(self):
        """When neither closure nor injection covers the deficit, trading is suspended."""
        handler = MarginCallHandler(
            auto_close_enabled=False,
            max_equity_injection_usd=0.0,
        )
        event = _make_event(deficit=5000.0)
        response = handler.handle(event, open_positions=[], broker_close_fn=None)

        assert response.resolved is False
        assert response.suspended is True
        assert response.final_status == MarginCallAction.SUSPENDED.value

    def test_no_positions_no_close_fn(self):
        """Handler must cope gracefully with empty positions and no close function."""
        handler = MarginCallHandler(auto_close_enabled=True)
        event = _make_event(deficit=500.0)
        response = handler.handle(event, open_positions=None, broker_close_fn=None)
        # Without closure or injection, should suspend
        assert isinstance(response, MarginCallResponse)

    def test_broker_close_fn_exception_is_handled(self):
        """Exception from broker_close_fn must not bubble out of handle()."""
        handler = MarginCallHandler(auto_close_enabled=True)
        event = _make_event(deficit=100.0)
        positions = _make_positions()

        def bad_close(symbol: str, qty: float) -> bool:
            raise RuntimeError("broker offline")

        # Should not raise
        response = handler.handle(event, open_positions=positions, broker_close_fn=bad_close)
        assert isinstance(response, MarginCallResponse)

    def test_positions_sorted_by_leverage_descending(self):
        """Highest-leverage position must be closed first."""
        handler = MarginCallHandler(auto_close_enabled=True)
        event = _make_event(deficit=100.0)
        positions = [
            {"symbol": "A", "notional_usd": 1000, "pnl_usd": 0, "leverage": 2.0,  "qty": 1.0, "margin_pct": 0.5},
            {"symbol": "B", "notional_usd": 1000, "pnl_usd": 0, "leverage": 20.0, "qty": 1.0, "margin_pct": 0.5},
        ]
        closed_order = []

        def fake_close(sym: str, qty: float) -> bool:
            closed_order.append(sym)
            return True

        handler.handle(event, open_positions=positions, broker_close_fn=fake_close)
        assert closed_order[0] == "B"  # highest leverage closed first


# ── Alert callbacks ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarginCallHandlerCallbacks:
    def test_alert_callback_is_called(self):
        cb = MagicMock()
        handler = MarginCallHandler(alert_callbacks=[cb])
        event = _make_event()
        handler.handle(event)
        cb.assert_called_once_with(event)

    def test_register_alert_callback(self):
        cb = MagicMock()
        handler = MarginCallHandler()
        handler.register_alert_callback(cb)
        event = _make_event()
        handler.handle(event)
        cb.assert_called_once_with(event)

    def test_multiple_callbacks_all_called(self):
        cb1, cb2 = MagicMock(), MagicMock()
        handler = MarginCallHandler(alert_callbacks=[cb1, cb2])
        event = _make_event()
        handler.handle(event)
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_failing_callback_does_not_abort_handling(self):
        def bad_cb(event):
            raise RuntimeError("notification service down")

        handler = MarginCallHandler(alert_callbacks=[bad_cb])
        event = _make_event(deficit=100.0)
        # Should not raise
        response = handler.handle(event)
        assert isinstance(response, MarginCallResponse)


# ── history() ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarginCallHandlerHistory:
    def test_history_returns_list(self):
        handler = MarginCallHandler()
        event = _make_event()
        handler.handle(event)
        history = handler.history()
        assert isinstance(history, list)
        assert len(history) == 1

    def test_history_entry_is_serialisable(self):
        """Every history entry must be JSON-serialisable."""
        import json
        handler = MarginCallHandler()
        handler.handle(_make_event())
        entry = handler.history()[0]
        # Must not raise
        json.dumps(entry)

    def test_history_grows_per_call(self):
        handler = MarginCallHandler()
        for _ in range(3):
            handler.handle(_make_event())
        assert len(handler.history()) == 3

    def test_history_entry_fields(self):
        handler = MarginCallHandler()
        event = _make_event(broker_name="Alpaca", deficit=250.0)
        handler.handle(event)
        entry = handler.history()[0]
        assert entry["broker"] == "Alpaca"
        assert entry["deficit_usd"] == 250.0
        assert "resolved" in entry
        assert "suspended" in entry
        assert isinstance(entry["actions_taken"], list)


# ── module-level singleton ────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarginCallHandlerSingleton:
    def test_singleton_exists(self):
        assert isinstance(margin_call_handler, MarginCallHandler)

    def test_singleton_history_method_callable(self):
        result = margin_call_handler.history()
        assert isinstance(result, list)
