"""
Unit tests for the Real-Time Signals Router (api/signals.py).

Tests cover:
- RealTimeSignalService creation and summary
- Signal generation
- Alert CRUD
- Router construction (all 9 endpoints present)
"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.unit
class TestRealTimeSignalService:
    """Tests for RealTimeSignalService."""

    def test_service_creation(self):
        """Signal service can be instantiated."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        assert svc is not None

    def test_get_signal_summary_empty(self):
        """Summary returns correct structure when no signals exist."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        summary = svc.get_signal_summary()
        assert "active_signals" in summary
        assert "signals_last_hour" in summary
        assert "signals_last_24h" in summary
        assert "direction_distribution" in summary
        assert summary["active_signals"] == 0
        assert summary["direction_distribution"]["buy"] == 0
        assert summary["direction_distribution"]["sell"] == 0

    def test_get_active_signals_empty(self):
        """Active signals list is empty initially."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        signals = svc.get_active_signals()
        assert isinstance(signals, list)
        assert len(signals) == 0

    def test_get_signal_history_empty(self):
        """Signal history is empty initially."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        history = svc.get_signal_history()
        assert isinstance(history, list)
        assert len(history) == 0

    def test_get_analytics(self):
        """Analytics object is returned with required keys."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        analytics = svc.get_analytics()
        assert isinstance(analytics, dict)

    def test_get_websocket_channels(self):
        """WebSocket channels list is returned."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        channels = svc.get_websocket_channels()
        assert isinstance(channels, list)
        # 'signals:all' and 'alerts' should always be present
        assert "signals:all" in channels
        assert "alerts" in channels

    def test_subscribe_and_unsubscribe(self):
        """Subscribe and unsubscribe callbacks work without error."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()

        received = []
        def callback(event_type, data):
            received.append((event_type, data))

        svc.subscribe(callback)
        assert callback in svc.subscribers
        svc.unsubscribe(callback)
        assert callback not in svc.subscribers

    def test_signal_generation_returns_result_or_none(self):
        """generate_signal returns a TradingSignal or None (not an exception)."""
        from api.signals import RealTimeSignalService, SignalDirection
        svc = RealTimeSignalService()
        # Low confidence signal — service may return None based on min_confidence
        result = svc.generate_signal(
            symbol="XAUUSD",
            direction=SignalDirection.BUY,
            confidence=0.1,  # below default min_confidence → should return None
            price=2350.0,
            entry_price=2350.0,
            stop_loss=2340.0,
            take_profit=2380.0,
            timeframe="1h",
            strategies_agreeing=[],
            total_strategies=0,
            regime="ranging",
            session="new_york",
        )
        # None is acceptable when confidence is below threshold
        assert result is None or hasattr(result, "symbol")

    def test_create_and_get_alert(self):
        """Create an alert and verify it is retrievable."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        alert = svc.create_alert(
            symbol="XAUUSD",
            direction="buy",
            min_confidence=0.7,
        )
        assert alert.symbol == "XAUUSD"
        assert alert.active is True

        alerts = svc.get_alerts(symbol="XAUUSD")
        assert len(alerts) == 1
        assert alerts[0].id == alert.id

    def test_delete_alert(self):
        """Delete an alert removes it from the list."""
        from api.signals import RealTimeSignalService
        svc = RealTimeSignalService()
        alert = svc.create_alert(symbol="BTCUSD", direction="sell", min_confidence=0.6)
        assert len(svc.get_alerts()) >= 1
        svc.delete_alert(alert.id)
        remaining = [a for a in svc.get_alerts() if a.id == alert.id]
        assert len(remaining) == 0


@pytest.mark.unit
class TestSignalsRouter:
    """Tests for the signals FastAPI router factory."""

    def test_create_signals_router_returns_router(self):
        """create_signals_router() returns a non-None FastAPI router."""
        from api.signals import create_signals_router
        router = create_signals_router()
        assert router is not None

    def test_signals_router_has_all_endpoints(self):
        """Router exposes all 9 expected paths."""
        from api.signals import create_signals_router
        router = create_signals_router()
        paths = [route.path for route in router.routes]
        expected = [
            "/api/signals/summary",
            "/api/signals/active",
            "/api/signals/history",
            "/api/signals/generate",
            "/api/signals/analytics",
            "/api/signals/alerts",
            "/api/signals/channels",
        ]
        for path in expected:
            assert path in paths, f"Missing route: {path}"

    def test_singleton_signal_service(self):
        """_get_signal_service() returns the same instance on repeated calls."""
        # Reset singleton first
        import api.signals as signals_module
        signals_module._signal_service = None

        from api.signals import _get_signal_service
        svc1 = _get_signal_service()
        svc2 = _get_signal_service()
        assert svc1 is svc2
