# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`brokers/manager.py` — the refusals, the failover, and the flatten.

The manager is the seam every order passes through on its way to a broker. It
measured 78%, and the uncovered part was the machinery that runs when something
goes wrong: the kill-switch block, the not-connected refusal, the consecutive-
failure counter and the auto-failover chain it drives, and `close_all_positions`.

Brokers here are hand-written stands-in, not `MagicMock`. The manager calls
`is_connected()`, `get_positions()` and `close_position(symbol)` with exact
signatures, and a specless mock accepts every one of them regardless — which is
how F242 and F248 shipped green.
"""

from __future__ import annotations

import pytest

from brokers.base import AccountInfo, BrokerConnector, Order, OrderSide, OrderType, Position
from brokers.manager import _MAX_CONSECUTIVE_FAILURES, BrokerManager

pytestmark = pytest.mark.unit


class _Broker(BrokerConnector):
    """A broker that does what it is told and records what it was asked."""

    def __init__(self, name: str = "b", connected: bool = True) -> None:
        super().__init__({"name": name})
        self.name = name
        self.connected = connected
        self.closed: list[str] = []
        self.positions_list: list[Position] = []
        self.place_error: BaseException | None = None
        self.close_error: BaseException | None = None

    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> bool:
        self.connected = False
        return True

    def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **kwargs):
        if self.place_error is not None:
            raise self.place_error
        return Order(id="1", symbol=symbol, side=side, type=order_type, quantity=quantity, price=price)

    def cancel_order(self, order_id: str) -> bool:
        return True

    def get_order(self, order_id: str):
        return None

    def get_positions(self) -> list[Position]:
        return list(self.positions_list)

    def close_position(self, symbol: str) -> bool:
        if self.close_error is not None:
            raise self.close_error
        self.closed.append(symbol)
        return True

    def get_account_info(self) -> AccountInfo:
        return AccountInfo(balance=1.0, equity=1.0, margin_used=0.0, margin_available=1.0, positions_count=0)

    def get_market_data(self, symbol, timeframe="1h", limit=100):
        return []


class _KillSwitch:
    def __init__(self, active: bool, reason: str = "daily loss limit") -> None:
        self._active = active
        self._reason = reason

    def is_active(self) -> bool:
        return self._active


def _position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        side="LONG",
        quantity=1.0,
        entry_price=1900.0,
        current_price=1950.0,
        unrealized_pnl=50.0,
    )


def _manager(brokers: dict[str, _Broker] | None = None, **kwargs) -> BrokerManager:
    manager = BrokerManager(**kwargs)
    for name, broker in (brokers or {}).items():
        manager.register(name, broker)
    if brokers:
        manager.set_active(next(iter(brokers)))
    return manager


class TestTheKillSwitchBlocksEveryMutation:
    @pytest.mark.parametrize(
        ("operation", "call"),
        [
            ("place_order", lambda m: m.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)),
            ("cancel_order", lambda m: m.cancel_order("1")),
            ("close_position", lambda m: m.close_position("XAUUSD")),
            ("close_all_positions", lambda m: m.close_all_positions()),
        ],
    )
    def test_it_refuses_and_names_the_operation(self, operation: str, call) -> None:
        manager = _manager({"live": _Broker("live")}, kill_switch=_KillSwitch(active=True))
        with pytest.raises(RuntimeError, match=operation):
            call(manager)

    def test_an_inactive_switch_lets_the_order_through(self) -> None:
        broker = _Broker("live")
        manager = _manager({"live": broker}, kill_switch=_KillSwitch(active=False))
        order = manager.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.quantity == 1.0

    def test_no_kill_switch_at_all_is_not_a_block(self) -> None:
        manager = _manager({"live": _Broker("live")})
        assert manager.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0) is not None

    def test_the_reason_reaches_the_operator(self) -> None:
        manager = _manager({"live": _Broker("live")}, kill_switch=_KillSwitch(True, "drawdown exceeded"))
        with pytest.raises(RuntimeError, match="drawdown exceeded"):
            manager.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)


class TestItRefusesWithoutAConnectedBroker:
    def test_no_broker_registered(self) -> None:
        with pytest.raises(RuntimeError, match="no active broker"):
            BrokerManager().place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_a_registered_but_disconnected_broker(self) -> None:
        manager = _manager({"live": _Broker("live", connected=False)})
        with pytest.raises(RuntimeError, match="not connected"):
            manager.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_is_connected_reports_the_active_broker(self) -> None:
        broker = _Broker("live")
        manager = _manager({"live": broker})
        assert manager.is_connected() is True
        broker.connected = False
        assert manager.is_connected() is False

    def test_with_nothing_registered_it_is_not_connected(self) -> None:
        assert BrokerManager().is_connected() is False
        assert BrokerManager().get_active_broker_name() is None


class TestTheFailoverChain:
    """Paper is always last. Failing straight to paper means live orders stop
    reaching a live venue, so a live secondary must be tried first."""

    def test_paper_is_last_even_when_registered_first(self) -> None:
        manager = BrokerManager(primary_broker_name="ibkr")
        for name in ("paper", "oanda", "ibkr"):
            manager.register(name, _Broker(name))

        chain = manager._build_failover_chain()

        assert chain[0] == "ibkr"
        assert chain[-1] == "paper"
        assert "oanda" in chain[1:-1]

    def test_a_chain_without_paper_is_still_ordered_primary_first(self) -> None:
        manager = BrokerManager(primary_broker_name="ibkr")
        manager.register("oanda", _Broker("oanda"))
        manager.register("ibkr", _Broker("ibkr"))
        assert manager._build_failover_chain()[0] == "ibkr"


class TestAutoFailover:
    def _manager_with_chain(self) -> BrokerManager:
        manager = BrokerManager(primary_broker_name="ibkr")
        for name in ("ibkr", "oanda", "paper"):
            manager.register(name, _Broker(name))
        manager.set_active("ibkr")
        return manager

    def test_one_failure_does_not_move_the_active_broker(self) -> None:
        manager = self._manager_with_chain()
        manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "ibkr"

    def test_it_fails_over_to_the_live_secondary_not_to_paper(self) -> None:
        manager = self._manager_with_chain()
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "oanda"

    def test_the_new_broker_starts_with_a_clean_counter(self) -> None:
        """Otherwise the target inherits its own earlier failures and fails
        over again on its first error.

        The counter is seeded here on purpose. `register()` already sets every
        broker to 0, so asserting "oanda is 0" after a failover passes whether
        or not the reset ran — the first version of this test did exactly that
        and survived a mutation removing the line it was written to protect.
        Starting oanda at 4 means only the reset can explain a 0.
        """
        manager = self._manager_with_chain()
        manager._consecutive_failures["oanda"] = _MAX_CONSECUTIVE_FAILURES - 1

        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            manager._record_failure(RuntimeError("timeout"))

        assert manager.get_active_broker_name() == "oanda"
        assert manager._consecutive_failures["oanda"] == 0

    def test_a_failed_over_broker_gets_its_full_allowance(self) -> None:
        """The consequence of the reset, stated as behaviour: after failing
        over, oanda must take another `_MAX_CONSECUTIVE_FAILURES` errors before
        it in turn hands off to paper."""
        manager = self._manager_with_chain()
        manager._consecutive_failures["oanda"] = _MAX_CONSECUTIVE_FAILURES - 1

        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "oanda"

        for _ in range(_MAX_CONSECUTIVE_FAILURES - 1):
            manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "oanda", "oanda handed off early"

        manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "paper"

    def test_a_second_exhaustion_reaches_paper(self) -> None:
        manager = self._manager_with_chain()
        for _ in range(_MAX_CONSECUTIVE_FAILURES * 2):
            manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "paper"

    def test_the_last_broker_in_the_chain_stays_active(self, caplog: pytest.LogCaptureFixture) -> None:
        """There is nowhere left to go. It must say so rather than silently
        switching to nothing."""
        manager = self._manager_with_chain()
        manager.set_active("paper")
        with caplog.at_level("CRITICAL"):
            for _ in range(_MAX_CONSECUTIVE_FAILURES):
                manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "paper"
        assert any("no further" in r.getMessage() for r in caplog.records)

    def test_a_success_clears_the_counter(self) -> None:
        manager = self._manager_with_chain()
        for _ in range(_MAX_CONSECUTIVE_FAILURES - 1):
            manager._record_failure(RuntimeError("timeout"))
        manager._reset_failures()
        manager._record_failure(RuntimeError("timeout"))
        assert manager.get_active_broker_name() == "ibkr", "a recovered broker failed over anyway"


class TestCloseAllPositions:
    def test_every_open_symbol_is_closed(self) -> None:
        broker = _Broker("live")
        broker.positions_list = [_position("XAUUSD"), _position("XAGUSD")]
        manager = _manager({"live": broker})

        results = manager.close_all_positions()

        assert results == {"XAUUSD": True, "XAGUSD": True}
        assert broker.closed == ["XAUUSD", "XAGUSD"]

    def test_an_empty_book_is_an_empty_result(self) -> None:
        assert _manager({"live": _Broker("live")}).close_all_positions() == {}

    def test_one_failure_does_not_abandon_the_rest(self) -> None:
        """A flatten that stops at the first error leaves the remaining
        positions open while reporting partial success."""
        broker = _Broker("live")
        broker.positions_list = [_position("XAUUSD"), _position("XAGUSD")]
        original = broker.close_position

        def _fail_first(symbol: str) -> bool:
            if symbol == "XAUUSD":
                raise RuntimeError("venue rejected")
            return original(symbol)

        broker.close_position = _fail_first
        manager = _manager({"live": broker})

        results = manager.close_all_positions()

        assert results == {"XAUUSD": False, "XAGUSD": True}

    def test_a_failing_position_fetch_reports_nothing_closed(self) -> None:
        """An empty dict here must mean "closed nothing", never "nothing to
        close" — the caller cannot tell the difference, so the log must."""
        broker = _Broker("live")

        def _boom() -> list[Position]:
            raise RuntimeError("broker unreachable")

        broker.get_positions = _boom
        assert _manager({"live": broker}).close_all_positions() == {}


class TestRegistration:
    def test_setting_an_unregistered_broker_active_is_refused(self) -> None:
        with pytest.raises((KeyError, ValueError, RuntimeError)):
            BrokerManager().set_active("nope")

    def test_the_first_registered_broker_can_be_made_active(self) -> None:
        manager = _manager({"live": _Broker("live")})
        assert manager.get_active_broker_name() == "live"

    def test_disconnect_all_disconnects_every_broker(self) -> None:
        brokers = {"a": _Broker("a"), "b": _Broker("b")}
        manager = _manager(brokers)
        manager.disconnect_all()
        assert [b.connected for b in brokers.values()] == [False, False]

    def test_connect_all_reports_per_broker(self) -> None:
        brokers = {"a": _Broker("a", connected=False), "b": _Broker("b", connected=False)}
        manager = _manager(brokers)
        assert manager.connect_all() == {"a": True, "b": True}


class TestContextManager:
    def test_leaving_the_block_disconnects(self) -> None:
        broker = _Broker("live")
        manager = _manager({"live": broker})
        with manager as entered:
            assert entered is manager
        assert broker.connected is False


# ---------------------------------------------------------------------------
# Async brokers: the thread-and-timeout path
# ---------------------------------------------------------------------------


class _AsyncBroker(_Broker):
    """A broker whose read methods are coroutines.

    The manager resolves these in a dedicated thread with its own event loop,
    rather than `run_coroutine_threadsafe`, which would deadlock against a
    caller's loop that is already blocked waiting for this call. That machinery
    is three near-identical blocks in `get_positions`, `close_all_positions` and
    `get_account_info`, and none of it was covered.
    """

    def __init__(self, name: str = "async", blocker=None, raises: BaseException | None = None) -> None:
        super().__init__(name)
        self._blocker = blocker
        self._raises = raises

    async def get_positions(self):  # type: ignore[override]
        if self._blocker is not None:
            self._blocker.wait()
        if self._raises is not None:
            raise self._raises
        return list(self.positions_list)

    async def get_account_info(self):  # type: ignore[override]
        if self._blocker is not None:
            self._blocker.wait()
        if self._raises is not None:
            raise self._raises
        return AccountInfo(balance=5.0, equity=6.0, margin_used=1.0, margin_available=5.0, positions_count=0)


class TestAnAsyncBrokerIsResolvedOffTheCallersLoop:
    def test_positions_come_back(self) -> None:
        broker = _AsyncBroker()
        broker.positions_list = [_position("XAUUSD")]
        manager = _manager({"live": broker})

        (position,) = manager.get_positions()

        assert position.symbol == "XAUUSD"

    def test_account_info_comes_back(self) -> None:
        manager = _manager({"live": _AsyncBroker()})
        assert manager.get_account_info().equity == 6.0

    def test_close_all_positions_resolves_the_coroutine_first(self) -> None:
        broker = _AsyncBroker()
        broker.positions_list = [_position("XAUUSD"), _position("XAGUSD")]
        manager = _manager({"live": broker})

        assert manager.close_all_positions() == {"XAUUSD": True, "XAGUSD": True}

    def test_an_exception_inside_the_coroutine_reaches_the_caller(self) -> None:
        """It is raised in another thread and has to be carried back across;
        losing it would report an empty book as success."""
        manager = _manager({"live": _AsyncBroker(raises=RuntimeError("venue rejected the query"))})
        with pytest.raises(RuntimeError, match="venue rejected the query"):
            manager.get_positions()

    def test_an_exception_inside_the_coroutine_counts_as_a_failure(self) -> None:
        manager = _manager({"live": _AsyncBroker(raises=RuntimeError("down"))})
        with pytest.raises(RuntimeError):
            manager.get_positions()
        assert manager._consecutive_failures["live"] == 1

    def test_a_successful_async_read_clears_the_failure_counter(self) -> None:
        manager = _manager({"live": _AsyncBroker()})
        manager._consecutive_failures["live"] = 3
        manager.get_positions()
        assert manager._consecutive_failures["live"] == 0


class TestTheTenSecondCeiling:
    """A broker that never answers must not hold the caller forever.

    `join(timeout=10)` is the ceiling. These drive it without waiting ten
    seconds by making `join` return while the worker is still blocked, which is
    exactly the state the timeout exists to detect.
    """

    def test_a_broker_that_never_answers_raises_rather_than_hanging(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import threading

        gate = threading.Event()
        monkeypatch.setattr(threading.Thread, "join", lambda self, timeout=None: None)
        manager = _manager({"live": _AsyncBroker(blocker=gate)})
        try:
            with pytest.raises(TimeoutError, match="timed out after 10 seconds"):
                manager.get_positions()
        finally:
            gate.set()

    def test_the_timeout_is_recorded_as_a_broker_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Otherwise a broker that stops answering never trips the failover."""
        import threading

        gate = threading.Event()
        monkeypatch.setattr(threading.Thread, "join", lambda self, timeout=None: None)
        manager = _manager({"live": _AsyncBroker(blocker=gate)})
        try:
            with pytest.raises(TimeoutError):
                manager.get_positions()
            assert manager._consecutive_failures["live"] == 1
        finally:
            gate.set()

    def test_account_info_has_the_same_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import threading

        gate = threading.Event()
        monkeypatch.setattr(threading.Thread, "join", lambda self, timeout=None: None)
        manager = _manager({"live": _AsyncBroker(blocker=gate)})
        try:
            with pytest.raises(TimeoutError, match="get_account_info timed out"):
                manager.get_account_info()
        finally:
            gate.set()

    def test_close_all_positions_has_the_same_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Here the timeout is swallowed into an empty result, because the
        method reports per-symbol outcomes and has no symbol to report against.
        An empty dict from a flatten means "closed nothing"."""
        import threading

        gate = threading.Event()
        monkeypatch.setattr(threading.Thread, "join", lambda self, timeout=None: None)
        manager = _manager({"live": _AsyncBroker(blocker=gate)})
        try:
            assert manager.close_all_positions() == {}
        finally:
            gate.set()


class TestMarketData:
    def test_bars_pass_through(self) -> None:
        broker = _Broker("live")
        broker.get_market_data = lambda symbol, timeframe, limit, **kw: [{"close": 1950.0}]
        manager = _manager({"live": broker})
        assert manager.get_market_data("XAUUSD") == [{"close": 1950.0}]

    def test_a_failure_is_recorded_and_raised(self) -> None:
        broker = _Broker("live")

        def _boom(*_a, **_k):
            raise RuntimeError("no market data permissions")

        broker.get_market_data = _boom
        manager = _manager({"live": broker})

        with pytest.raises(RuntimeError, match="permissions"):
            manager.get_market_data("XAUUSD")
        assert manager._consecutive_failures["live"] == 1

    def test_it_refuses_without_a_connected_broker(self) -> None:
        manager = _manager({"live": _Broker("live", connected=False)})
        with pytest.raises(RuntimeError, match="not connected"):
            manager.get_market_data("XAUUSD")
