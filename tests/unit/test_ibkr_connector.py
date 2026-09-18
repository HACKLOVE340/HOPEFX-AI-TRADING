# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`brokers/ibkr_connector.py` — the ib_insync production connector, exercised.

It measured 44%, and the missing 56% was everything that runs once a TWS
session exists: `connect`, `place_order`, `cancel_order`, `get_positions`,
`close_position`, `cancel_all_orders`, `get_account_info`, `get_market_data`,
`subscribe_ticks`, and the Cancel-on-Disconnect check. The covered part was the
branch that fires when the SDK is missing — the only branch CI can reach,
because `ib_insync` is not in `requirements-ci.txt`.

So the connector that would carry real orders to Interactive Brokers was
untested by construction, the same way `execution/fix_adapter.py` and
`brokers/ibkr_broker.py` were. These tests load the module a second time with
`ib_insync` stubbed.

The stub is hand-written, not a `MagicMock`. A specless mock accepts
`LimitOrder("BUY", 1)` with no price as readily as with one, so a suite built on
one cannot tell a valid order from an invalid one.
"""

from __future__ import annotations

import contextlib
import importlib.util
import itertools
import pathlib
import sys
import types
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MODULE_PATH = REPO / "brokers" / "ibkr_connector.py"

TWS_PAPER_PORT = 7497
TWS_LIVE_PORT = 7496
GATEWAY_LIVE_PORT = 4001
GATEWAY_PAPER_PORT = 4002


# ---------------------------------------------------------------------------
# ib_insync stand-in
# ---------------------------------------------------------------------------


class _Contract:
    def __init__(self, symbol: str = "", exchange: str = "", currency: str = "", **kwargs: Any) -> None:
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency
        self.conId = 0
        self.__dict__.update(kwargs)


def _contract_type(name: str) -> type:
    """Commodity/CFD/Stock all take (symbol, exchange, currency) positionally."""

    def __init__(self, symbol: str = "", exchange: str = "", currency: str = "", **kwargs: Any) -> None:  # noqa: N807
        _Contract.__init__(self, symbol, exchange, currency, **kwargs)
        self.secType = name

    return type(name, (_Contract,), {"__init__": __init__})


class _Future(_Contract):
    def __init__(self, symbol: str = "", exchange: str = "", currency: str = "", **kwargs: Any) -> None:
        _Contract.__init__(self, symbol, exchange, currency, **kwargs)
        self.secType = "FUT"


class _Forex(_Contract):
    def __init__(self, pair: str = "", baseCurrency: str = "", currency: str = "", **kwargs: Any) -> None:
        _Contract.__init__(self, pair, "IDEALPRO", currency, **kwargs)
        self.baseCurrency = baseCurrency
        self.secType = "CASH"


class _Order:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
        self.orderId = 0
        self.transmit = False


def _order_type(name: str, price_field: str | None) -> type:
    """A real ib_insync order class rejects a missing price; so does this one."""

    def __init__(self, action: str, totalQuantity: float, *args: Any, **kwargs: Any) -> None:  # noqa: N807
        if price_field is not None:
            if args:
                kwargs[price_field] = args[0]
            if kwargs.get(price_field) is None:
                raise TypeError(f"{name} requires {price_field}")
        _Order.__init__(self, action=action, totalQuantity=totalQuantity, **kwargs)
        self.orderType = name

    return type(name, (_Order,), {"__init__": __init__})


class _OrderStatus:
    def __init__(self, status: str = "PreSubmitted", filled: float = 0.0, avg: float = 0.0) -> None:
        self.status = status
        self.filled = filled
        self.avgFillPrice = avg


class _Trade:
    def __init__(self, contract: Any, order: Any, status: str = "Submitted") -> None:
        self.contract = contract
        self.order = order
        self.orderStatus = _OrderStatus(status)


class _AccountValue:
    def __init__(self, tag: str, value: str, currency: str = "USD") -> None:
        self.tag = tag
        self.value = value
        self.currency = currency


class _IBPosition:
    def __init__(self, symbol: str, position: float, avg_cost: float, con_id: int = 1) -> None:
        self.contract = _Contract(symbol=symbol)
        self.contract.conId = con_id
        self.position = position
        self.avgCost = avg_cost


class _Ticker:
    def __init__(self, price: Any = 0.0, bid: Any = 0.0, ask: Any = 0.0, last: Any = 0.0) -> None:
        self._price = price
        self.bid, self.ask, self.last = bid, ask, last
        self.contract = _Contract(symbol="XAUUSD")

    def marketPrice(self) -> Any:
        return self._price


class _Bar:
    def __init__(self, date: str, o: float, h: float, low: float, c: float, v: float) -> None:
        self.date, self.open, self.high, self.low, self.close, self.volume = date, o, h, low, c, v


class _Event(list):
    """ib_insync events support `+=` to add a handler."""

    def __iadd__(self, handler: Any) -> _Event:
        self.append(handler)
        return self

    def emit(self, *args: Any) -> None:
        for handler in list(self):
            handler(*args)


#: The session `time.monotonic` should follow. `connect()` builds a new `IB()`
#: on every attempt, so the fixture cannot capture one up front.
_current_session: list[Any] = [None]


class _FakeIB:
    """Records what the connector asked TWS to do, and nothing else."""

    def __init__(self) -> None:
        _current_session[0] = self
        self.connect_calls: list[dict[str, Any]] = []
        self.placed: list[tuple[Any, Any]] = []
        self.cancelled: list[Any] = []
        self.qualified: list[Any] = []
        self.global_cancels = 0
        self.disconnects = 0
        self.market_data: list[Any] = []
        self.historical_calls: list[dict[str, Any]] = []
        self.pendingTickersEvent = _Event()

        self.accounts: list[str] = ["DU1234567"]
        self.account_values: list[_AccountValue] = []
        self.positions_list: list[_IBPosition] = []
        self.trades_list: list[_Trade] = []
        self.bars: list[_Bar] = []
        self.ticker: Any = _Ticker(price=1950.0)

        self.connected_flag = False
        self.connect_error: BaseException | None = None
        self.place_error: BaseException | None = None
        self.positions_error: BaseException | None = None
        self.ticker_error: BaseException | None = None
        self.account_values_error: BaseException | None = None
        self._next_order_id = 100
        #: status each newly placed trade reports
        self.place_status = "Submitted"
        #: what `time.monotonic()` returns while this session is installed
        self.clock = 0.0

    # -- lifecycle --
    def connect(self, host: str, port: int, clientId: int, readonly: bool, timeout: float) -> None:
        self.connect_calls.append(
            {"host": host, "port": port, "clientId": clientId, "readonly": readonly, "timeout": timeout}
        )
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_flag = True

    def managedAccounts(self) -> list[str]:
        return self.accounts

    def isConnected(self) -> bool:
        return self.connected_flag

    def disconnect(self) -> None:
        self.disconnects += 1
        self.connected_flag = False

    def sleep(self, seconds: float) -> None:
        # `place_order` polls `ib.sleep(0.1)` against a `time.monotonic()`
        # deadline. Real sleeping would cost 30s per unacknowledged order, and
        # a no-op would spin for 30s of wall clock instead — the first version
        # of this file took 31s for one parametrised case. Advance a clock the
        # module reads, so the deadline is exact and instant.
        self.clock += seconds

    # -- contracts --
    def qualifyContracts(self, contract: Any) -> list[Any]:
        self.qualified.append(contract)
        return [contract]

    # -- orders --
    def placeOrder(self, contract: Any, order: Any) -> _Trade:
        if self.place_error is not None:
            raise self.place_error
        self._next_order_id += 1
        order.orderId = self._next_order_id
        trade = _Trade(contract, order, self.place_status)
        self.placed.append((contract, order))
        self.trades_list.append(trade)
        return trade

    def trades(self) -> list[_Trade]:
        return self.trades_list

    def cancelOrder(self, order: Any) -> None:
        self.cancelled.append(order)

    def reqGlobalCancel(self) -> None:
        self.global_cancels += 1

    # -- account and positions --
    def accountValues(self, account: str = "") -> list[_AccountValue]:
        if self.account_values_error is not None:
            raise self.account_values_error
        return self.account_values

    def positions(self, account: str = "") -> list[_IBPosition]:
        if self.positions_error is not None:
            raise self.positions_error
        return self.positions_list

    def reqTicker(self, contract: Any) -> Any:
        if self.ticker_error is not None:
            raise self.ticker_error
        return self.ticker

    # -- market data --
    def reqHistoricalData(self, contract: Any, **kwargs: Any) -> list[_Bar]:
        self.historical_calls.append({"contract": contract, **kwargs})
        return self.bars

    def reqMktData(self, contract: Any, *_args: Any) -> Any:
        self.market_data.append(contract)
        return self.ticker


def _make_stub() -> types.ModuleType:
    module = types.ModuleType("ib_insync")
    module.IB = _FakeIB  # type: ignore[attr-defined]
    module.Contract = _Contract  # type: ignore[attr-defined]
    module.Commodity = _contract_type("Commodity")  # type: ignore[attr-defined]
    module.CFD = _contract_type("CFD")  # type: ignore[attr-defined]
    module.Stock = _contract_type("Stock")  # type: ignore[attr-defined]
    module.Future = _Future  # type: ignore[attr-defined]
    module.Forex = _Forex  # type: ignore[attr-defined]
    module.Trade = _Trade  # type: ignore[attr-defined]
    module.MarketOrder = _order_type("MKT", None)  # type: ignore[attr-defined]
    module.LimitOrder = _order_type("LMT", "lmtPrice")  # type: ignore[attr-defined]
    module.StopOrder = _order_type("STP", "stopPrice")  # type: ignore[attr-defined]
    return module


@contextlib.contextmanager
def _sdk_installed() -> Any:
    """`_make_contract` imports Forex/Stock/Commodity at call time, so the stub
    has to stay in `sys.modules` for the whole test, not just the import."""
    previous = sys.modules.get("ib_insync")
    sys.modules["ib_insync"] = _make_stub()
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("ib_insync", None)
        else:
            sys.modules["ib_insync"] = previous


@pytest.fixture
def ibkr(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The connector module, loaded with the SDK present."""
    name = "_ibkr_connector_stubbed"
    with _sdk_installed():
        spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            assert module.IB_AVAILABLE is True, "the stub did not take"
            # Reconnect backoff sleeps up to 120s per attempt; never in a test.
            monkeypatch.setattr(module.time, "sleep", lambda _s: None)
            # `connect()` starts a daemon thread whose loop is `while running:
            # time.sleep(30)`. With sleep neutered above, that thread spins a
            # core for the rest of the session — the first version of this file
            # took 130s and tripped pytest-timeout for exactly that reason.
            # `TestHeartbeat` drives the loop directly instead.
            monkeypatch.setattr(module.IBKRConnector, "_start_heartbeat", lambda _self: None)

            # `time.monotonic` follows whichever fake session is current, so a
            # poll loop advances only when the connector actually waits.
            def _monotonic() -> float:
                session = _current_session[0]
                return 0.0 if session is None else session.clock

            monkeypatch.setattr(module.time, "monotonic", _monotonic)
            yield module
        finally:
            sys.modules.pop(name, None)


class _KillSwitch:
    def __init__(self, active: bool = False, reason: str = "daily loss limit") -> None:
        self._active = active
        self.reason = reason

    def is_active(self) -> bool:
        return self._active


def _connected(ibkr: Any, **kwargs: Any) -> Any:
    """A connector with a live fake session."""
    connector = ibkr.IBKRConnector(**kwargs)
    assert connector.connect() is True
    return connector


# ---------------------------------------------------------------------------
# The kill switch and its own escape hatch
# ---------------------------------------------------------------------------


class TestTheKillSwitchCanStillFlatten:
    """`place_order` refuses while the kill switch is active — and the kill
    switch's own emergency flattening places orders.

    `risk/circuit_breakers.py::_execute_kill_switch` closes every open position
    by calling `broker.close_position`, and `IBKRConnector.close_position`
    reaches TWS through `self.place_order`. `brokers/manager.py:194` hands the
    connector the same kill-switch object the circuit breaker trips. So the
    question is not academic: does the guard that exists to stop new risk also
    stop the one action that removes existing risk?

    Read, it looks right. This runs it.
    """

    def test_a_market_close_is_refused_while_the_switch_is_active(self, ibkr: Any) -> None:
        connector = _connected(ibkr, kill_switch=_KillSwitch(active=True))

        with pytest.raises(RuntimeError, match="kill switch"):
            connector.place_order(
                symbol="XAUUSD",
                side=ibkr.OrderSide.SELL,
                order_type=ibkr.OrderType.MARKET,
                quantity=1.0,
            )

    def test_close_position_sends_nothing_once_the_switch_is_active(self, ibkr: Any) -> None:
        switch = _KillSwitch(active=False)
        connector = _connected(ibkr, kill_switch=switch)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=2.0, avg_cost=1900.0)]

        switch._active = True
        closed = connector.close_position("XAUUSD")

        # The outcome, not the log: was an order sent to the broker?
        assert connector._ib.placed == [], "an order reached TWS after all"
        assert closed is False

    @pytest.mark.asyncio
    async def test_cancel_all_orders_leaves_the_position_open(self, ibkr: Any) -> None:
        """The escalation path, end to end."""
        switch = _KillSwitch(active=True, reason="daily loss limit")
        connector = _connected(ibkr, kill_switch=switch)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=2.0, avg_cost=1900.0)]

        flattened = await connector.cancel_all_orders()

        # reqGlobalCancel reached the broker: resting orders are gone.
        assert connector._ib.global_cancels == 1
        # The open position is what is left, and it is the one carrying risk.
        assert connector._ib.placed == []
        assert flattened == []


# ---------------------------------------------------------------------------
# Configuration — the refusals that happen before anything connects
# ---------------------------------------------------------------------------


class TestConfigRefusesAnUnknownPort:
    """`IBKRConfig.__post_init__` is the only thing standing between a typo in
    `IBKR_PORT` and an order sent to the wrong side of the account."""

    @pytest.mark.parametrize("port", [TWS_PAPER_PORT, TWS_LIVE_PORT, GATEWAY_LIVE_PORT, GATEWAY_PAPER_PORT])
    def test_the_four_real_ports_are_accepted(self, ibkr: Any, port: int) -> None:
        assert ibkr.IBKRConfig(port=port).port == port

    @pytest.mark.parametrize("port", [0, 80, 7498, 4000, 8000, -1])
    def test_anything_else_is_refused_at_construction(self, ibkr: Any, port: int) -> None:
        with pytest.raises(ValueError, match="not a recognised"):
            ibkr.IBKRConfig(port=port)

    def test_paper_and_live_are_decided_by_the_port(self, ibkr: Any) -> None:
        assert ibkr.IBKRConfig(port=TWS_PAPER_PORT).is_paper is True
        assert ibkr.IBKRConfig(port=GATEWAY_PAPER_PORT).is_paper is True
        assert ibkr.IBKRConfig(port=TWS_LIVE_PORT).is_paper is False
        assert ibkr.IBKRConfig(port=GATEWAY_LIVE_PORT).is_paper is False

    def test_the_mode_label_follows_the_port_and_not_a_flag(self, ibkr: Any) -> None:
        assert ibkr.IBKRConfig(port=TWS_PAPER_PORT).mode_label == "PAPER"
        assert ibkr.IBKRConfig(port=TWS_LIVE_PORT).mode_label == "LIVE"

    def test_the_environment_supplies_the_defaults(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IBKR_HOST", "10.0.0.9")
        monkeypatch.setenv("IBKR_PORT", str(GATEWAY_LIVE_PORT))
        monkeypatch.setenv("IBKR_CLIENT_ID", "42")
        monkeypatch.setenv("IBKR_ACCOUNT", "U7654321")
        cfg = ibkr.IBKRConfig()
        assert (cfg.host, cfg.port, cfg.client_id, cfg.account) == ("10.0.0.9", GATEWAY_LIVE_PORT, 42, "U7654321")
        assert cfg.is_paper is False

    def test_a_dict_config_goes_through_the_same_validation(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector(config={"host": "h", "port": TWS_LIVE_PORT, "client_id": 3})
        assert connector._cfg.port == TWS_LIVE_PORT
        assert connector._cfg.is_paper is False
        with pytest.raises(ValueError, match="not a recognised"):
            ibkr.IBKRConnector(config={"port": 9999})


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnect:
    def test_a_connection_carries_the_configured_session_parameters(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector(
            config=ibkr.IBKRConfig(host="1.2.3.4", port=GATEWAY_PAPER_PORT, client_id=7, readonly=True)
        )
        assert connector.connect() is True

        assert connector._ib.connect_calls == [
            {"host": "1.2.3.4", "port": GATEWAY_PAPER_PORT, "clientId": 7, "readonly": True, "timeout": 20.0}
        ]
        assert connector.connected is True

    def test_the_first_managed_account_is_adopted_when_none_is_configured(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector()
        connector.connect()
        assert connector._account_id == "DU1234567"

    def test_a_configured_account_absent_from_tws_is_refused(self, ibkr: Any) -> None:
        """Trading the wrong account is worse than not trading."""
        connector = ibkr.IBKRConnector(config=ibkr.IBKRConfig(account="U0000001"))
        assert connector.connect() is False
        assert connector.connected is False

    def test_no_managed_accounts_is_refused(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector()
        original = ibkr.IB

        class _NoAccounts(_FakeIB):
            def managedAccounts(self) -> list[str]:
                return []

        ibkr.IB = _NoAccounts
        try:
            assert connector.connect() is False
        finally:
            ibkr.IB = original

    def test_it_gives_up_after_ten_attempts(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(ibkr.time, "sleep", slept.append)

        connector = ibkr.IBKRConnector()
        original = ibkr.IB

        class _Refuses(_FakeIB):
            def connect(self, **kwargs: Any) -> None:
                raise ConnectionRefusedError("TWS is not running")

        ibkr.IB = _Refuses
        try:
            assert connector.connect() is False
        finally:
            ibkr.IB = original

        # Ten attempts, nine waits between them.
        assert len(slept) == ibkr._MAX_RECONNECT_ATTEMPTS - 1

    def test_the_backoff_doubles_and_is_capped(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A retry loop with no ceiling is how a reconnect becomes an outage."""
        slept: list[float] = []
        monkeypatch.setattr(ibkr.time, "sleep", slept.append)

        connector = ibkr.IBKRConnector()
        original = ibkr.IB

        class _Refuses(_FakeIB):
            def connect(self, **kwargs: Any) -> None:
                raise OSError("no route to host")

        ibkr.IB = _Refuses
        try:
            connector.connect()
        finally:
            ibkr.IB = original

        assert slept[0] == ibkr._RECONNECT_INITIAL_DELAY
        for earlier, later in itertools.pairwise(slept):
            assert later == min(earlier * ibkr._RECONNECT_MULTIPLIER, ibkr._RECONNECT_MAX_DELAY)
        assert max(slept) <= ibkr._RECONNECT_MAX_DELAY

    def test_a_successful_connect_resets_the_backoff(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector()
        connector._reconnect_delay = 64.0
        connector._reconnect_attempts = 5
        connector.connect()
        assert connector._reconnect_delay == ibkr._RECONNECT_INITIAL_DELAY
        assert connector._reconnect_attempts == 0


class TestDisconnect:
    def test_it_closes_the_session_and_stops_the_heartbeat(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        assert connector.disconnect() is True
        assert connector._ib.disconnects == 1
        assert connector.connected is False
        assert connector._running is False

    def test_a_disconnect_that_raises_reports_failure(self, ibkr: Any) -> None:
        connector = _connected(ibkr)

        def _boom() -> None:
            raise OSError("socket already closed")

        connector._ib.disconnect = _boom
        assert connector.disconnect() is False

    def test_disconnecting_without_a_session_is_not_an_error(self, ibkr: Any) -> None:
        assert ibkr.IBKRConnector().disconnect() is True

    def test_reconnect_closes_before_it_opens(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        # `connect()` builds a fresh `IB()`, so hold the old session to see
        # whether it was actually closed rather than merely abandoned.
        first_session = connector._ib

        assert connector.reconnect() is True

        assert first_session.disconnects == 1
        assert connector._ib is not first_session
        assert connector.connected is True


# ---------------------------------------------------------------------------
# Cancel-on-Disconnect — the safety net that survives this process dying
# ---------------------------------------------------------------------------


class TestCancelOnDisconnectCheck:
    """CoD tells TWS to pull every resting order if the API link drops. It is
    the only protection that still works when this process is the thing that
    died, so the check that reports it off has to be able to fire."""

    def _connect_with_cod(self, ibkr: Any, value: str | None) -> Any:
        connector = ibkr.IBKRConnector()
        original = ibkr.IB

        class _WithCoD(_FakeIB):
            def __init__(self) -> None:
                super().__init__()
                if value is not None:
                    self.account_values = [_AccountValue("CancelOrdersOnDisconnect", value)]

        ibkr.IB = _WithCoD
        try:
            connector.connect()
        finally:
            ibkr.IB = original
        return connector

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "NO"])
    def test_cod_disabled_is_critical_and_reaches_sentry(
        self, ibkr: Any, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        captured: list[BaseException] = []
        monkeypatch.setattr(ibkr.IBKRConnector, "_capture_sentry", staticmethod(captured.append))

        with caplog.at_level("CRITICAL"):
            self._connect_with_cod(ibkr, value)

        assert [r for r in caplog.records if r.levelname == "CRITICAL"], "no CRITICAL record"
        assert len(captured) == 1, "operators were not paged"

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
    def test_cod_enabled_pages_nobody(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        captured: list[BaseException] = []
        monkeypatch.setattr(ibkr.IBKRConnector, "_capture_sentry", staticmethod(captured.append))
        self._connect_with_cod(ibkr, value)
        assert captured == []

    def test_an_absent_tag_warns_rather_than_claiming_either_way(
        self, ibkr: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Old TWS does not return the tag. "I could not tell" is not "enabled"."""
        with caplog.at_level("WARNING"):
            self._connect_with_cod(ibkr, None)
        assert any("not available" in r.message for r in caplog.records)
        assert not [r for r in caplog.records if r.levelname == "CRITICAL"]

    def test_a_failing_check_never_blocks_the_connection(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector()
        original = ibkr.IB

        class _Raises(_FakeIB):
            def accountValues(self, account: str = "") -> list[_AccountValue]:
                raise RuntimeError("TWS busy")

        ibkr.IB = _Raises
        try:
            assert connector.connect() is True
        finally:
            ibkr.IB = original

    def test_a_readonly_session_skips_the_check(self, ibkr: Any) -> None:
        """Read-only cannot place orders, so it has none to cancel."""
        connector = ibkr.IBKRConnector(config=ibkr.IBKRConfig(readonly=True))
        connector.connect()
        connector._ib.account_values_error = RuntimeError("should never be asked")
        connector._check_cancel_on_disconnect()  # must not raise


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------


class TestPlaceOrderRefusals:
    def test_an_unconnected_connector_refuses(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector()
        with pytest.raises(RuntimeError, match="not connected"):
            connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)

    def test_a_limit_order_without_a_price_is_refused(self, ibkr: Any) -> None:
        """The defect this prevents shipped elsewhere in this repository: a
        limit order with no price reaching the broker at 0."""
        connector = _connected(ibkr)
        with pytest.raises(ValueError, match="price is required"):
            connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.LIMIT, 1.0, price=None)
        assert connector._ib.placed == []

    def test_a_stop_order_without_a_stop_price_is_refused(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        with pytest.raises(ValueError, match="stop_price is required"):
            connector.place_order("XAUUSD", ibkr.OrderSide.SELL, ibkr.OrderType.STOP, 1.0, stop_price=None)
        assert connector._ib.placed == []

    def test_an_order_type_with_no_ib_equivalent_is_refused(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        with pytest.raises(ValueError, match="Unsupported order type"):
            connector.place_order("XAUUSD", ibkr.OrderSide.BUY, "TRAILING_STOP", 1.0)
        assert connector._ib.placed == []

    def test_a_broker_rejection_is_raised_and_not_reported_as_placed(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.place_error = RuntimeError("order rejected: insufficient margin")
        with pytest.raises(RuntimeError, match="insufficient margin"):
            connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)


class TestPlaceOrderBuildsTheRightOrder:
    def test_a_market_order_carries_side_and_quantity(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        order = connector.place_order("XAUUSD", ibkr.OrderSide.SELL, ibkr.OrderType.MARKET, 2.5)

        _contract, ib_order = connector._ib.placed[0]
        assert (ib_order.orderType, ib_order.action, ib_order.totalQuantity) == ("MKT", "SELL", 2.5)
        assert ib_order.transmit is True, "an untransmitted order sits in TWS unsent"
        assert order.quantity == 2.5
        assert order.side is ibkr.OrderSide.SELL

    def test_a_limit_order_carries_its_price(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.LIMIT, 1.0, price=1899.5)
        _contract, ib_order = connector._ib.placed[0]
        assert ib_order.orderType == "LMT"
        assert ib_order.lmtPrice == 1899.5

    def test_a_stop_order_carries_its_stop(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector.place_order("XAUUSD", ibkr.OrderSide.SELL, ibkr.OrderType.STOP, 1.0, stop_price=1875.25)
        _contract, ib_order = connector._ib.placed[0]
        assert ib_order.orderType == "STP"
        assert ib_order.stopPrice == 1875.25

    def test_the_returned_order_reports_what_tws_said(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.place_status = "Filled"
        order = connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)
        assert order.status is ibkr.OrderStatus.FILLED
        assert order.metadata["ib_status"] == "Filled"
        assert order.metadata["mode"] == "PAPER"


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class TestGetPositions:
    def test_an_unconnected_connector_returns_nothing_rather_than_raising(self, ibkr: Any) -> None:
        assert ibkr.IBKRConnector().get_positions() == []

    def test_a_long_position_is_priced_from_cost_basis_and_market(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        # IBKR reports avgCost as the total, so entry = 3800 / 2 = 1900.
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=2.0, avg_cost=3800.0, con_id=55)]
        connector._ib.ticker = _Ticker(price=1950.0)

        (position,) = connector.get_positions()

        # `Position.__post_init__` normalises the connector's "LONG" to an
        # enum; `side_str` is the documented way back. Asserting the string
        # here would repeat the defect this suite found in `close_position`.
        assert position.side is ibkr.OrderSide.BUY
        assert position.side_str == "LONG"
        assert position.quantity == 2.0
        assert position.entry_price == 1900.0
        assert position.current_price == 1950.0
        assert position.unrealized_pnl == pytest.approx(100.0)
        assert position.id == "55"

    def test_a_short_position_profits_when_the_price_falls(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=-2.0, avg_cost=3800.0)]
        connector._ib.ticker = _Ticker(price=1850.0)

        (position,) = connector.get_positions()

        assert position.side is ibkr.OrderSide.SELL
        assert position.side_str == "SHORT"
        assert position.quantity == 2.0
        assert position.unrealized_pnl == pytest.approx(100.0)

    def test_a_flat_line_is_not_a_position(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=0.0, avg_cost=0.0)]
        assert connector.get_positions() == []

    def test_an_unpriceable_position_falls_back_to_its_cost_basis(self, ibkr: Any) -> None:
        """No market price means unknown P&L, and zero is a claim. Cost basis
        gives 0.0 unrealised — "I cannot tell you yet" — rather than valuing the
        position at nothing and reporting a total loss."""
        connector = _connected(ibkr)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=1.0, avg_cost=1900.0)]
        connector._ib.ticker_error = RuntimeError("no market data subscription")

        (position,) = connector.get_positions()

        assert position.current_price == 1900.0
        assert position.unrealized_pnl == 0.0

    def test_a_failing_positions_call_returns_empty_rather_than_partial(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_error = RuntimeError("TWS disconnected mid-query")
        assert connector.get_positions() == []


class TestClosePosition:
    def test_an_unconnected_connector_refuses(self, ibkr: Any) -> None:
        assert ibkr.IBKRConnector().close_position("XAUUSD") is False

    def test_closing_nothing_reports_false(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        assert connector.close_position("XAUUSD") is False
        assert connector._ib.placed == []

    def test_a_long_is_closed_by_selling_the_same_quantity(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=3.0, avg_cost=5700.0)]

        assert connector.close_position("XAUUSD") is True

        _contract, ib_order = connector._ib.placed[0]
        assert (ib_order.action, ib_order.totalQuantity, ib_order.orderType) == ("SELL", 3.0, "MKT")

    def test_a_short_is_closed_by_buying(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=-3.0, avg_cost=5700.0)]

        assert connector.close_position("XAUUSD") is True

        _contract, ib_order = connector._ib.placed[0]
        assert ib_order.action == "BUY"

    def test_only_the_named_symbol_is_closed(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_list = [
            _IBPosition("XAUUSD", position=1.0, avg_cost=1900.0),
            _IBPosition("XAGUSD", position=5.0, avg_cost=115.0),
        ]

        connector.close_position("XAGUSD")

        assert [o.totalQuantity for _c, o in connector._ib.placed] == [5.0]


class TestCancelAllOrders:
    @pytest.mark.asyncio
    async def test_an_unconnected_connector_closes_nothing(self, ibkr: Any) -> None:
        assert await ibkr.IBKRConnector().cancel_all_orders() == []

    @pytest.mark.asyncio
    async def test_it_reaches_the_broker_before_it_reaches_the_positions(self, ibkr: Any) -> None:
        """reqGlobalCancel is broker-side: it survives this process dying."""
        connector = _connected(ibkr)
        connector._ib.positions_list = [_IBPosition("XAUUSD", position=1.0, avg_cost=1900.0)]

        flattened = await connector.cancel_all_orders()

        assert connector._ib.global_cancels == 1
        assert flattened == ["XAUUSD"]
        assert [o.action for _c, o in connector._ib.placed] == ["SELL"]

    @pytest.mark.asyncio
    async def test_one_symbol_failing_does_not_abandon_the_others(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_list = [
            _IBPosition("XAUUSD", position=1.0, avg_cost=1900.0),
            _IBPosition("XAGUSD", position=1.0, avg_cost=23.0),
        ]
        original_close = connector.close_position

        def _fail_first(symbol: str) -> bool:
            if symbol == "XAUUSD":
                raise RuntimeError("TWS rejected the close")
            return original_close(symbol)

        connector.close_position = _fail_first

        assert await connector.cancel_all_orders() == ["XAGUSD"]

    @pytest.mark.asyncio
    async def test_a_global_cancel_that_raises_returns_what_was_done(self, ibkr: Any) -> None:
        connector = _connected(ibkr)

        def _boom() -> None:
            raise RuntimeError("not permitted")

        connector._ib.reqGlobalCancel = _boom
        assert await connector.cancel_all_orders() == []


# ---------------------------------------------------------------------------
# Contract routing — the wrong contract is the wrong instrument
# ---------------------------------------------------------------------------


class TestContractRouting:
    """A symbol that routes to the wrong asset class trades a different thing
    at a different size. XAUUSD as a Stock is not XAUUSD."""

    @pytest.mark.parametrize("symbol", ["XAUUSD", "xauusd", "GOLD", "XAU", "XAU/USD", "XAU_USD"])
    def test_every_spelling_of_gold_reaches_the_commodity(self, ibkr: Any, symbol: str) -> None:
        connector = _connected(ibkr)
        contract = connector._make_contract(symbol)
        assert contract.secType == "Commodity"
        assert contract.symbol == "XAUUSD"
        assert contract.exchange == "SMART"

    def test_gold_as_a_cfd(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        contract = connector._make_contract("XAUUSD", instrument="cfd")
        assert contract.secType == "CFD"

    def test_gold_as_a_future_is_comex_gc_not_a_spot_symbol(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        contract = connector._make_contract("XAUUSD", instrument="future")
        assert contract.secType == "FUT"
        assert contract.symbol == "GC"

    def test_a_forex_pair_is_split_into_base_and_quote(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        contract = connector._make_contract("GBPJPY")
        assert contract.secType == "CASH"
        assert (contract.baseCurrency, contract.currency) == ("GBP", "JPY")

    def test_silver_reaches_a_commodity_and_not_an_equity(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        for symbol in ("XAGUSD", "SILVER", "XAG"):
            contract = connector._make_contract(symbol)
            assert contract.secType == "Commodity"
            assert contract.symbol == "XAGUSD"

    def test_an_unknown_symbol_falls_through_to_an_equity(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        contract = connector._make_contract("AAPL")
        assert contract.secType == "Stock"
        assert contract.symbol == "AAPL"

    def test_every_contract_is_qualified_before_use(self, ibkr: Any) -> None:
        """An unqualified contract is ambiguous to TWS and can be filled on the
        wrong exchange."""
        connector = _connected(ibkr)
        for symbol in ("XAUUSD", "EURUSD", "XAGUSD", "AAPL"):
            connector._make_contract(symbol)
        assert len(connector._ib.qualified) == 4


# ---------------------------------------------------------------------------
# Order queries
# ---------------------------------------------------------------------------


class TestCancelOrder:
    def test_an_unconnected_connector_refuses(self, ibkr: Any) -> None:
        assert ibkr.IBKRConnector().cancel_order("1") is False

    def test_a_known_order_is_cancelled(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        order = connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.LIMIT, 1.0, price=1900.0)

        assert connector.cancel_order(order.id) is True
        assert [o.orderId for o in connector._ib.cancelled] == [int(order.id)]

    def test_an_unknown_order_reports_false_rather_than_success(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        assert connector.cancel_order("999999") is False
        assert connector._ib.cancelled == []

    def test_a_failing_cancel_reports_false(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        order = connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)

        def _boom(_order: Any) -> None:
            raise RuntimeError("order already filled")

        connector._ib.cancelOrder = _boom
        assert connector.cancel_order(order.id) is False


class TestGetOrder:
    def test_an_unconnected_connector_returns_none(self, ibkr: Any) -> None:
        assert ibkr.IBKRConnector().get_order("1") is None

    def test_a_known_order_comes_back_with_its_status(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.place_status = "Filled"
        placed = connector.place_order("XAUUSD", ibkr.OrderSide.SELL, ibkr.OrderType.MARKET, 2.0)

        found = connector.get_order(placed.id)

        assert found is not None
        assert found.id == placed.id
        assert found.status is ibkr.OrderStatus.FILLED
        assert found.side is ibkr.OrderSide.SELL

    def test_an_unknown_order_is_none_and_not_an_empty_order(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        assert connector.get_order("424242") is None

    def test_a_failing_lookup_returns_none(self, ibkr: Any) -> None:
        connector = _connected(ibkr)

        def _boom() -> list[Any]:
            raise RuntimeError("TWS busy")

        connector._ib.trades = _boom
        assert connector.get_order("1") is None


class TestTradeToOrderStatusMapping:
    @pytest.mark.parametrize(
        ("ib_status", "expected"),
        [
            ("PreSubmitted", "PENDING"),
            ("Submitted", "OPEN"),
            ("Filled", "FILLED"),
            ("PartiallyFilled", "PARTIAL"),
            ("Cancelled", "CANCELLED"),
            ("Inactive", "CANCELLED"),
            ("SomethingIBAddedLater", "PENDING"),
        ],
    )
    def test_every_tws_status_maps_to_one_of_ours(self, ibkr: Any, ib_status: str, expected: str) -> None:
        """An unknown status must not be read as filled."""
        connector = _connected(ibkr)
        connector._ib.place_status = ib_status
        order = connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)
        assert order.status is getattr(ibkr.OrderStatus, expected)

    def test_an_unfilled_order_reports_no_average_price(self, ibkr: Any) -> None:
        """Zero is a price. `None` is "it has not filled"."""
        connector = _connected(ibkr)
        order = connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)
        assert order.average_price is None
        assert order.filled_quantity == 0.0


class TestTheOrderAcknowledgementPoll:
    def test_it_stops_as_soon_as_tws_acknowledges(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.place_status = "Submitted"
        connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)
        # One poll, not thirty seconds of them.
        assert connector._ib.clock <= 0.2

    def test_it_gives_up_at_the_deadline_rather_than_waiting_forever(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.place_status = "PreSubmitted"

        order = connector.place_order("XAUUSD", ibkr.OrderSide.BUY, ibkr.OrderType.MARKET, 1.0)

        assert connector._ib.clock >= ibkr._ORDER_TIMEOUT_SEC
        # And it reports what it knows — pending — rather than a fill.
        assert order.status is ibkr.OrderStatus.PENDING


# ---------------------------------------------------------------------------
# Account info
# ---------------------------------------------------------------------------


class TestGetAccountInfo:
    def test_an_unconnected_connector_raises_rather_than_returning_zeros(self, ibkr: Any) -> None:
        """A zero balance is a number somebody will size a trade against."""
        with pytest.raises(RuntimeError, match="not connected"):
            ibkr.IBKRConnector().get_account_info()

    def test_the_tws_tags_are_mapped_to_our_fields(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.account_values = [
            _AccountValue("TotalCashValue", "25000.50"),
            _AccountValue("NetLiquidation", "31250.75"),
            _AccountValue("MaintMarginReq", "4000.00"),
            _AccountValue("AvailableFunds", "21000.25"),
        ]

        info = connector.get_account_info()

        assert info.balance == 25000.50
        assert info.equity == 31250.75
        assert info.margin_used == 4000.00
        assert info.margin_available == 21000.25

    def test_values_in_another_currency_are_ignored(self, ibkr: Any) -> None:
        """Summing a EUR line into a USD balance overstates the account."""
        connector = _connected(ibkr)
        connector._ib.account_values = [
            _AccountValue("NetLiquidation", "1000.00", currency="EUR"),
            _AccountValue("NetLiquidation", "31250.75", currency="USD"),
        ]
        assert connector.get_account_info().equity == 31250.75

    def test_an_unparseable_value_falls_back_rather_than_raising(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.account_values = [_AccountValue("NetLiquidation", "n/a")]
        assert connector.get_account_info().equity == 0.0

    def test_a_missing_tag_is_zero_and_not_an_exception(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.account_values = []
        info = connector.get_account_info()
        assert (info.balance, info.equity, info.margin_used, info.margin_available) == (0.0, 0.0, 0.0, 0.0)

    def test_open_positions_are_counted(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.positions_list = [
            _IBPosition("XAUUSD", position=1.0, avg_cost=1900.0),
            _IBPosition("XAGUSD", position=-2.0, avg_cost=46.0),
        ]
        assert connector.get_account_info().positions_count == 2

    def test_a_failing_query_is_raised_and_not_answered_with_zeros(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.account_values_error = RuntimeError("TWS disconnected")
        with pytest.raises(RuntimeError, match="TWS disconnected"):
            connector.get_account_info()


# ---------------------------------------------------------------------------
# Historical bars
# ---------------------------------------------------------------------------


class TestGetMarketData:
    def test_an_unconnected_connector_raises(self, ibkr: Any) -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            ibkr.IBKRConnector().get_market_data("XAUUSD")

    def test_bars_come_back_as_plain_ohlcv(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.bars = [_Bar("2026-09-11 10:00", 1900.0, 1910.0, 1895.0, 1905.0, 1234.0)]

        (bar,) = connector.get_market_data("XAUUSD")

        assert bar == {
            "time": "2026-09-11 10:00",
            "open": 1900.0,
            "high": 1910.0,
            "low": 1895.0,
            "close": 1905.0,
            "volume": 1234.0,
        }

    def test_no_bars_is_an_empty_list_and_not_an_error(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.bars = []
        assert connector.get_market_data("XAUUSD") == []

    @pytest.mark.parametrize(
        ("timeframe", "duration"),
        [("1 secs", "100 S"), ("5 secs", "500 S"), ("1 min", "100 D"), ("1 day", "100 D"), ("30 mins", "100 D")],
    )
    def test_the_timeframe_chooses_a_duration_string(self, ibkr: Any, timeframe: str, duration: str) -> None:
        connector = _connected(ibkr)
        connector.get_market_data("XAUUSD", timeframe=timeframe, limit=100)
        call = connector._ib.historical_calls[-1]
        assert call["durationStr"] == duration
        assert call["barSizeSetting"] == timeframe

    def test_a_short_duration_never_falls_below_the_ib_minimum(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector.get_market_data("XAUUSD", timeframe="1 secs", limit=1)
        assert connector._ib.historical_calls[-1]["durationStr"] == "60 S"

    def test_a_failing_request_is_raised_rather_than_answered_with_no_bars(self, ibkr: Any) -> None:
        """An empty list reads as "the market did not trade"."""
        connector = _connected(ibkr)

        def _boom(_contract: Any, **_kwargs: Any) -> list[Any]:
            raise RuntimeError("pacing violation")

        connector._ib.reqHistoricalData = _boom
        with pytest.raises(RuntimeError, match="pacing violation"):
            connector.get_market_data("XAUUSD")


# ---------------------------------------------------------------------------
# Tick subscription
# ---------------------------------------------------------------------------


class TestSubscribeTicks:
    def test_an_unconnected_connector_raises(self, ibkr: Any) -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            ibkr.IBKRConnector().subscribe_ticks("XAUUSD", lambda _t: None)

    def test_a_tick_for_the_subscribed_symbol_reaches_the_callback(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        seen: list[dict] = []
        connector.subscribe_ticks("XAUUSD", seen.append)

        connector._ib.pendingTickersEvent.emit([_Ticker(bid=1949.8, ask=1950.2, last=1950.0)])

        (tick,) = seen
        assert tick["symbol"] == "XAUUSD"
        assert (tick["bid"], tick["ask"], tick["last"]) == (1949.8, 1950.2, 1950.0)
        assert tick["source"] == "ibkr"

    def test_a_tick_for_another_symbol_is_not_delivered(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        seen: list[dict] = []
        connector.subscribe_ticks("XAUUSD", seen.append)

        other = _Ticker(bid=23.1, ask=23.2, last=23.15)
        other.contract = _Contract(symbol="XAGUSD")
        connector._ib.pendingTickersEvent.emit([other])

        assert seen == []

    def test_an_absent_side_is_reported_as_zero_and_not_as_none(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        seen: list[dict] = []
        connector.subscribe_ticks("XAUUSD", seen.append)

        connector._ib.pendingTickersEvent.emit([_Ticker(bid=None, ask=-1.0, last=0.0)])

        (tick,) = seen
        assert (tick["bid"], tick["ask"], tick["last"]) == (0.0, 0.0, 0.0)

    def test_a_callback_that_raises_does_not_break_the_feed(self, ibkr: Any) -> None:
        """One bad consumer must not stop ticks reaching the others."""
        connector = _connected(ibkr)
        survived: list[dict] = []

        def _explodes(_tick: dict) -> None:
            raise ValueError("consumer bug")

        connector.subscribe_ticks("XAUUSD", _explodes)
        connector.subscribe_ticks("XAUUSD", survived.append)

        connector._ib.pendingTickersEvent.emit([_Ticker(bid=1.0, ask=2.0, last=1.5)])

        assert len(survived) == 1

    def test_market_data_is_requested_for_the_contract(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector.subscribe_ticks("XAUUSD", lambda _t: None)
        assert [c.symbol for c in connector._ib.market_data] == ["XAUUSD"]

    def test_a_failing_subscription_is_raised(self, ibkr: Any) -> None:
        connector = _connected(ibkr)

        def _boom(_contract: Any, *_args: Any) -> Any:
            raise RuntimeError("no market data permissions")

        connector._ib.reqMktData = _boom
        with pytest.raises(RuntimeError, match="permissions"):
            connector.subscribe_ticks("XAUUSD", lambda _t: None)


# ---------------------------------------------------------------------------
# Heartbeat, import guard, context manager
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """The fixture stops `connect()` from starting the real thread, so these
    drive the loop directly rather than racing it."""

    def test_it_reconnects_when_the_session_has_dropped(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.connected_flag = False
        reconnects: list[int] = []
        connector.reconnect = lambda: (reconnects.append(1), connector.__setattr__("_running", False))[0] is None

        connector._heartbeat_loop()

        assert reconnects == [1]

    def test_a_live_session_is_left_alone(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._ib.connected_flag = True
        reconnects: list[int] = []

        def _never() -> bool:
            reconnects.append(1)
            return True

        connector.reconnect = _never
        # One pass, then stop.
        calls = [0]

        def _is_connected() -> bool:
            calls[0] += 1
            if calls[0] > 1:
                connector._running = False
            return True

        connector._ib.isConnected = _is_connected
        connector._heartbeat_loop()

        assert reconnects == []

    def test_a_raising_probe_does_not_kill_the_thread(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        calls = [0]

        def _boom() -> bool:
            calls[0] += 1
            if calls[0] >= 2:
                connector._running = False
            raise RuntimeError("socket error")

        connector._ib.isConnected = _boom
        connector._heartbeat_loop()  # must return, not propagate

        assert calls[0] == 2

    def test_a_stopped_connector_never_enters_the_loop(self, ibkr: Any) -> None:
        connector = _connected(ibkr)
        connector._running = False

        def _never() -> bool:
            raise AssertionError("the loop ran after being stopped")

        connector._ib.isConnected = _never
        connector._heartbeat_loop()

    def test_start_heartbeat_does_not_stack_threads(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A reconnect calls connect(), which calls this. One thread, not ten."""
        monkeypatch.undo()  # restore the real _start_heartbeat for this test
        connector = ibkr.IBKRConnector()
        connector._running = False  # the loop exits immediately

        connector._start_heartbeat()
        first = connector._heartbeat_thread
        connector._start_heartbeat()

        assert first is not None
        if first.is_alive():
            assert connector._heartbeat_thread is first
        for _ in range(50):
            if not first.is_alive():
                break
        first.join(timeout=2)


class TestWithoutTheSdk:
    """The branches CI could already reach — kept, because they are the ones
    that run on a machine where `ib_insync` was never installed."""

    def test_construction_refuses_rather_than_failing_later(self) -> None:
        import brokers.ibkr_connector as real

        if real.IB_AVAILABLE:  # pragma: no cover - ib_insync absent in CI
            pytest.skip("ib_insync is installed in this environment")
        with pytest.raises(ImportError, match="ib_insync is required"):
            real.IBKRConnector()

    def test_connect_reports_false_rather_than_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import brokers.ibkr_connector as real

        connector = object.__new__(real.IBKRConnector)
        connector._cfg = real.IBKRConfig()
        monkeypatch.setattr(real, "IB_AVAILABLE", False)
        assert real.IBKRConnector.connect(connector) is False


class TestContextManager:
    def test_entering_connects_and_leaving_disconnects(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector()
        with connector as entered:
            assert entered is connector
            assert connector.connected is True
            session = connector._ib
        assert connector.connected is False
        assert session.disconnects == 1

    def test_an_exception_inside_the_block_still_disconnects(self, ibkr: Any) -> None:
        connector = ibkr.IBKRConnector()
        with pytest.raises(ValueError), connector:
            session = connector._ib
            raise ValueError("something went wrong in the strategy")
        assert session.disconnects == 1


class TestSentryCapture:
    def test_nothing_is_sent_when_sentry_is_not_installed(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ibkr, "_SENTRY", False)
        ibkr.IBKRConnector._capture_sentry(RuntimeError("x"))  # must not raise

    def test_an_exception_is_forwarded_when_it_is(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: list[BaseException] = []
        monkeypatch.setattr(ibkr, "_SENTRY", True)
        monkeypatch.setattr(ibkr, "sentry_sdk", type("_S", (), {"capture_exception": staticmethod(sent.append)}))

        exc = RuntimeError("order rejected")
        ibkr.IBKRConnector._capture_sentry(exc)

        assert sent == [exc]

    def test_a_broken_sentry_never_masks_the_original_failure(self, ibkr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_exc: BaseException) -> None:
            raise RuntimeError("sentry is down")

        monkeypatch.setattr(ibkr, "_SENTRY", True)
        monkeypatch.setattr(ibkr, "sentry_sdk", type("_S", (), {"capture_exception": staticmethod(_boom)}))
        ibkr.IBKRConnector._capture_sentry(RuntimeError("the real problem"))  # must not raise
