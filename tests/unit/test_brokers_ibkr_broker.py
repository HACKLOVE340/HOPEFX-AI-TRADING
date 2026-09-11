# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`brokers/ibkr_broker.py` — the Interactive Brokers adapter, exercised.

It measured 38%, and the missing 62% was every line that runs once a session
exists: `connect`, `place_order`, `cancel_order`, `close_position`, `get_tick`,
`get_order`, `reconnect`. The covered part was the branch that fires when the
SDK is absent — which is the only branch CI can reach, because `ib_insync` is
not installed and `_IB_AVAILABLE` is False.

So the adapter that would carry real orders was untested by construction, the
same way `execution/fix_adapter.py` was. These tests load the module a second
time with `ib_insync` stubbed.

The stub is hand-written, not a `MagicMock`. A specless mock accepts
`MarketOrder(action=..., totalQuantity=...)` and every other signature equally,
so a test suite built on one cannot tell a market order from a limit order with
no price. `_FakeIB` records what it was asked to do and nothing else.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import pathlib
import sys
import types
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MODULE_PATH = REPO / "brokers" / "ibkr_broker.py"

PAPER_PORT = 7497
LIVE_PORT = 7496


# ---------------------------------------------------------------------------
# ib_insync stand-in
# ---------------------------------------------------------------------------


class _Order:
    """An ib_insync order: whatever was set on it, plus the ids TWS assigns."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
        self.orderId = 0
        self.permId = 0
        self.account = ""


def _order_type(name: str, price_field: str | None) -> type:
    def __init__(self, action: str, totalQuantity: float, **kwargs: Any) -> None:  # noqa: N807
        _Order.__init__(self, action=action, totalQuantity=totalQuantity, **kwargs)
        self.orderType = name
        if price_field is not None and price_field not in kwargs:
            raise TypeError(f"{name} requires {price_field}")

    return type(name, (_Order,), {"__init__": __init__})


class _Contract:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
        self.symbol = kwargs.get("symbol", "")


class _OrderStatus:
    def __init__(self, status: str = "PendingSubmit") -> None:
        self.status = status


class _Trade:
    def __init__(self, contract: Any, order: Any, status: str = "PendingSubmit") -> None:
        self.contract = contract
        self.order = order
        self.orderStatus = _OrderStatus(status)


class _Ticker:
    def __init__(self, bid: Any = None, ask: Any = None, last: Any = None) -> None:
        self.bid, self.ask, self.last = bid, ask, last


class _Position:
    def __init__(self, symbol: str, position: float) -> None:
        self.contract = _Contract(symbol=symbol)
        self.position = position


class _FakeIB:
    """Records what the adapter asked TWS to do."""

    def __init__(self) -> None:
        self.connect_calls: list[dict[str, Any]] = []
        self.placed: list[tuple[Any, Any]] = []
        self.cancelled: list[Any] = []
        self.disconnected = 0
        self.accounts: list[str] = ["DU1234567"]
        self.open_trades: list[_Trade] = []
        self.positions_list: list[_Position] = []
        self.ticker = _Ticker(bid=1950.0, ask=1950.4, last=1950.2)
        self.market_data_cancelled: list[Any] = []
        self.connect_error: BaseException | None = None
        self.place_error: BaseException | None = None
        self.cancel_error: BaseException | None = None
        self.tick_error: BaseException | None = None
        self._next_order_id = 100

    async def connectAsync(self, host: str, port: int, clientId: int, readonly: bool):
        self.connect_calls.append({"host": host, "port": port, "clientId": clientId, "readonly": readonly})
        if self.connect_error is not None:
            raise self.connect_error
        return True

    def managedAccounts(self) -> list[str]:
        return self.accounts

    def disconnect(self) -> None:
        self.disconnected += 1

    def placeOrder(self, contract: Any, order: Any) -> _Trade:
        if self.place_error is not None:
            raise self.place_error
        self._next_order_id += 1
        order.orderId = self._next_order_id
        order.permId = self._next_order_id * 10
        trade = _Trade(contract, order)
        self.placed.append((contract, order))
        return trade

    def openTrades(self) -> list[_Trade]:
        return self.open_trades

    def cancelOrder(self, order: Any) -> None:
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancelled.append(order)

    def positions(self, account: str = "") -> list[_Position]:
        return self.positions_list

    def reqMktData(self, contract: Any, generic: str, snapshot: bool, regulatory: bool) -> _Ticker:
        if self.tick_error is not None:
            raise self.tick_error
        return self.ticker

    def cancelMktData(self, contract: Any) -> None:
        self.market_data_cancelled.append(contract)


def _make_stub() -> types.ModuleType:
    module = types.ModuleType("ib_insync")
    module.IB = _FakeIB  # type: ignore[attr-defined]
    module.Contract = _Contract  # type: ignore[attr-defined]
    module.MarketOrder = _order_type("MKT", None)  # type: ignore[attr-defined]
    module.LimitOrder = _order_type("LMT", "lmtPrice")  # type: ignore[attr-defined]
    module.StopOrder = _order_type("STP", "stopPrice")  # type: ignore[attr-defined]
    return module


@contextlib.contextmanager
def _sdk_installed() -> Any:
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
def ibkr() -> Any:
    """The adapter loaded with the SDK present."""
    name = "_ibkr_broker_stubbed"
    with _sdk_installed():
        spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            assert module._IB_AVAILABLE is True, "the stub did not take"
            yield module
        finally:
            sys.modules.pop(name, None)


#: A non-placeholder login, so the placeholder warning stays out of the way
#: except in the tests that are about it. TWS uses session auth — these values
#: are informational and reach no credential store.
TEST_LOGIN = "real_user"
TEST_SECRET = "real_pass"  # pragma: allowlist secret


def _broker(ibkr: Any, **config: Any) -> Any:
    base = {"login": TEST_LOGIN, "password": TEST_SECRET, "server": "paper"}
    base.update(config)
    return ibkr.IBKRBroker(base)


async def _connected(ibkr: Any, **config: Any) -> Any:
    broker = _broker(ibkr, **config)
    assert await broker.connect() is True
    return broker


# ---------------------------------------------------------------------------
# Which port, and therefore whether real money moves
# ---------------------------------------------------------------------------


class TestPaperVersusLive:
    """One comparison decides it: `_PORT_PAPER if server_type == "paper" else
    _PORT_LIVE`. There is no second confirmation anywhere in this adapter, so
    the string that reaches that line is the whole safety margin."""

    def test_the_two_ports_are_the_documented_ones(self, ibkr: Any) -> None:
        assert ibkr._PORT_PAPER == PAPER_PORT
        assert ibkr._PORT_LIVE == LIVE_PORT

    def test_paper_connects_to_the_paper_port(self, ibkr: Any) -> None:
        broker = asyncio.run(_connected(ibkr, server="paper"))
        assert broker._port == PAPER_PORT
        assert broker._ib.connect_calls[0]["port"] == PAPER_PORT

    def test_live_connects_to_the_live_port(self, ibkr: Any) -> None:
        broker = asyncio.run(_connected(ibkr, server="live"))
        assert broker._port == LIVE_PORT

    @pytest.mark.parametrize("spelling", ["PAPER", "Paper", "pApEr"])
    def test_case_does_not_change_the_meaning(self, ibkr: Any, spelling: str) -> None:
        """`.lower()` is applied, so the obvious variants are safe."""
        broker = asyncio.run(_connected(ibkr, server=spelling))
        assert broker._port == PAPER_PORT

    @pytest.mark.parametrize("value", ["paper ", " paper", "papper", "demo", "sim", "test", ""])
    def test_anything_that_is_not_exactly_paper_goes_live(self, ibkr: Any, value: str) -> None:
        """A finding, pinned rather than changed.

        The comparison is `== "paper"` against a lower-cased but **unstripped**
        string, with `_PORT_LIVE` as the else. So a trailing space, a typo, a
        plausible synonym like "demo" or "sim", or an empty value all select
        the live port — and the adapter connects to it without a word.

        The shipped config is safe today: `config/brokers.yaml:53` reads
        `${IBKR_SERVER:paper}`, so an unset variable resolves to "paper". The
        exposure is an operator who sets the variable and gets it slightly
        wrong, which is the ordinary way this goes wrong.

        The safe shape is to refuse a value that is neither "paper" nor "live"
        — CRITICAL and no connection — rather than to pick a side. Left for the
        owner because changing it could send a deployment that relies on some
        other spelling to paper without warning, and finding that out from an
        unfilled order is its own kind of bad day.
        """
        broker = asyncio.run(_connected(ibkr, server=value))
        assert broker._port == LIVE_PORT

    def test_an_unset_environment_variable_still_means_paper(self, ibkr: Any, monkeypatch) -> None:
        """The config's own default is what stands between an unset variable
        and the live port."""
        monkeypatch.delenv("IBKR_SERVER", raising=False)
        broker = asyncio.run(_connected(ibkr, server="${IBKR_SERVER:paper}"))
        assert broker._port == PAPER_PORT

    def test_the_environment_variable_can_select_live(self, ibkr: Any, monkeypatch) -> None:
        monkeypatch.setenv("IBKR_SERVER", "live")
        broker = asyncio.run(_connected(ibkr, server="${IBKR_SERVER:paper}"))
        assert broker._port == LIVE_PORT

    def test_the_shipped_config_carries_the_safe_default(self) -> None:
        """Checked against the file, because that default is load-bearing."""
        config = (REPO / "config" / "brokers.yaml").read_text()
        assert 'server: "${IBKR_SERVER:paper}"' in config

    def test_status_reports_which_side_it_is_on(self, ibkr: Any) -> None:
        """The only place an operator can see it without reading a log line."""
        broker = asyncio.run(_connected(ibkr, server="live"))
        snapshot = broker.status()
        assert snapshot["server_type"] == "live"
        assert snapshot["port"] == LIVE_PORT


class TestResolvingConfigPlaceholders:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("plain", "plain"), ("", ""), ("${}", ""), ("not${a}placeholder", "not${a}placeholder")],
    )
    def test_a_literal_passes_through(self, ibkr: Any, raw: str, expected: str) -> None:
        assert ibkr._resolve_env(raw) == expected

    def test_an_unset_variable_falls_back_to_its_default(self, ibkr: Any, monkeypatch) -> None:
        monkeypatch.delenv("HOPEFX_TEST_VAR", raising=False)
        assert ibkr._resolve_env("${HOPEFX_TEST_VAR:fallback}") == "fallback"

    def test_a_set_variable_wins(self, ibkr: Any, monkeypatch) -> None:
        monkeypatch.setenv("HOPEFX_TEST_VAR", "from_env")
        assert ibkr._resolve_env("${HOPEFX_TEST_VAR:fallback}") == "from_env"

    def test_a_variable_with_no_default_resolves_to_empty(self, ibkr: Any, monkeypatch) -> None:
        """Which is exactly the value that sends `server` to the live port."""
        monkeypatch.delenv("HOPEFX_TEST_VAR", raising=False)
        assert ibkr._resolve_env("${HOPEFX_TEST_VAR}") == ""

    @pytest.mark.parametrize(("raw", "expected"), [(None, ""), (7497, "7497"), (True, "True"), (1.5, "1.5")])
    def test_non_strings_are_stringified(self, ibkr: Any, raw: Any, expected: str) -> None:
        assert ibkr._resolve_env(raw) == expected


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------


class TestConnecting:
    def test_no_sdk_means_no_connection_and_no_exception(self, caplog) -> None:
        """CI's situation. An adapter that raised here would take down startup
        for an optional broker nobody configured."""
        import brokers.ibkr_broker as real

        assert real._IB_AVAILABLE is False
        broker = real.IBKRBroker({"server": "paper"})
        with caplog.at_level(logging.ERROR, logger="brokers.ibkr_broker"):
            assert asyncio.run(broker.connect()) is False
        assert "ib_insync not installed" in caplog.text
        assert broker.connected is False

    def test_no_sdk_means_no_client_object_at_all(self) -> None:
        import brokers.ibkr_broker as real

        assert real.IBKRBroker({"server": "paper"})._ib is None

    def test_a_successful_connect_marks_the_broker_connected(self, ibkr: Any) -> None:
        broker = asyncio.run(_connected(ibkr))
        assert broker.connected is True

    def test_it_connects_read_write_not_readonly(self, ibkr: Any) -> None:
        """`readonly=True` would accept the session and silently refuse every
        order — a connected adapter that cannot trade."""
        broker = asyncio.run(_connected(ibkr))
        assert broker._ib.connect_calls[0]["readonly"] is False

    def test_the_client_id_is_the_configured_one(self, ibkr: Any) -> None:
        """TWS drops the older session when two connect with the same id."""
        broker = asyncio.run(_connected(ibkr, client_id=7))
        assert broker._ib.connect_calls[0]["clientId"] == 7

    def test_the_client_id_defaults_to_one(self, ibkr: Any) -> None:
        broker = asyncio.run(_connected(ibkr))
        assert broker._client_id == 1

    def test_a_string_client_id_is_coerced(self, ibkr: Any) -> None:
        broker = asyncio.run(_connected(ibkr, client_id="4"))
        assert broker._client_id == 4

    def test_the_host_defaults_to_loopback(self, ibkr: Any) -> None:
        """TWS listens locally. A default of anything else would send
        credentials off the box."""
        broker = asyncio.run(_connected(ibkr))
        assert broker._host == "127.0.0.1"

    def test_the_first_managed_account_is_captured(self, ibkr: Any) -> None:
        """Orders are tagged with it, so an adapter that connected without one
        would place orders against no account."""
        broker = asyncio.run(_connected(ibkr))
        assert broker._account == "DU1234567"

    def test_no_managed_accounts_leaves_it_unset_rather_than_guessing(self, ibkr: Any) -> None:
        broker = _broker(ibkr)
        broker._ib.accounts = []
        assert asyncio.run(broker.connect()) is True
        assert broker._account is None

    def test_a_placeholder_login_is_warned_about_but_not_fatal(self, ibkr: Any, caplog) -> None:
        """TWS uses session auth, so a placeholder username still connects —
        which is exactly why it needs saying out loud."""
        broker = _broker(ibkr, login="your_ibkr_username")
        with caplog.at_level(logging.WARNING, logger="brokers.ibkr_broker"):
            assert asyncio.run(broker.connect()) is True
        assert "placeholder" in caplog.text

    def test_an_empty_login_is_warned_about_too(self, ibkr: Any, caplog) -> None:
        broker = _broker(ibkr, login="")
        with caplog.at_level(logging.WARNING, logger="brokers.ibkr_broker"):
            asyncio.run(broker.connect())
        assert "placeholder" in caplog.text

    def test_a_real_login_is_not_warned_about(self, ibkr: Any, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="brokers.ibkr_broker"):
            asyncio.run(_connected(ibkr, login="hopefx_prod"))
        assert "placeholder" not in caplog.text

    def test_a_timeout_names_the_endpoint_it_could_not_reach(self, ibkr: Any, caplog) -> None:
        """ "Is TWS running?" is the first question, and the log answers it
        with the host and port actually tried."""
        broker = _broker(ibkr)
        broker._ib.connect_error = TimeoutError()
        with caplog.at_level(logging.ERROR, logger="brokers.ibkr_broker"):
            assert asyncio.run(broker.connect()) is False
        assert "7497" in caplog.text
        assert broker.connected is False

    @pytest.mark.parametrize(
        "failure", [ConnectionRefusedError("nothing listening"), OSError("network down"), RuntimeError("bad state")]
    )
    def test_any_connect_failure_returns_false_rather_than_raising(self, ibkr: Any, failure: Exception) -> None:
        broker = _broker(ibkr)
        broker._ib.connect_error = failure
        assert asyncio.run(broker.connect()) is False
        assert broker.connected is False

    def test_disconnecting_closes_the_session(self, ibkr: Any) -> None:
        broker = asyncio.run(_connected(ibkr))
        assert asyncio.run(broker.disconnect()) is True
        assert broker.connected is False
        assert broker._ib.disconnected == 1

    def test_disconnecting_when_never_connected_is_safe(self, ibkr: Any) -> None:
        broker = _broker(ibkr)
        assert asyncio.run(broker.disconnect()) is True
        assert broker._ib.disconnected == 0


class TestEveryCallRefusesBeforeConnect:
    """`_assert_connected` is the one guard between a half-built adapter and a
    call into a `None` session. Driven across every public method, because a
    guard on five of six is a crash on the sixth."""

    def test_the_guard_logs_which_method_was_called(self, ibkr: Any, caplog) -> None:
        broker = _broker(ibkr)
        with caplog.at_level(logging.ERROR, logger="brokers.ibkr_broker"):
            assert broker._assert_connected("place_order") is False
        assert "place_order called before connect()" in caplog.text

    def test_place_order_refuses(self, ibkr: Any) -> None:
        result = asyncio.run(_broker(ibkr).place_order({"symbol": "XAUUSD"}))
        assert result["success"] is False
        assert result["comment"] == "Not connected"

    def test_cancel_order_refuses(self, ibkr: Any) -> None:
        assert asyncio.run(_broker(ibkr).cancel_order(1))["success"] is False

    def test_close_position_refuses(self, ibkr: Any) -> None:
        assert asyncio.run(_broker(ibkr).close_position("XAUUSD"))["success"] is False

    def test_get_tick_refuses(self, ibkr: Any) -> None:
        assert asyncio.run(_broker(ibkr).get_tick("XAUUSD")) is None

    def test_get_order_refuses(self, ibkr: Any) -> None:
        assert asyncio.run(_broker(ibkr).get_order("1")) is None

    def test_get_account_info_refuses(self, ibkr: Any) -> None:
        assert asyncio.run(_broker(ibkr).get_account_info()) is None

    def test_get_positions_refuses(self, ibkr: Any) -> None:
        assert asyncio.run(_broker(ibkr).get_positions()) == []

    def test_get_orders_refuses(self, ibkr: Any) -> None:
        assert asyncio.run(_broker(ibkr).get_orders()) == []

    def test_a_lost_session_object_also_trips_the_guard(self, ibkr: Any) -> None:
        """`connected` can be True while `_ib` is gone. The guard checks both."""
        broker = asyncio.run(_connected(ibkr))
        broker._ib = None
        assert broker._assert_connected("place_order") is False


# ---------------------------------------------------------------------------
# Placing an order
# ---------------------------------------------------------------------------


class TestPlacingAnOrder:
    @pytest.fixture
    def broker(self, ibkr: Any) -> Any:
        return asyncio.run(_connected(ibkr))

    def _place(self, broker: Any, **params: Any) -> dict:
        base = {"symbol": "XAUUSD", "action": "BUY", "quantity": 1.0}
        base.update(params)
        return asyncio.run(broker.place_order(base))

    def test_a_market_order_is_submitted(self, broker: Any) -> None:
        result = self._place(broker)
        assert result["success"] is True
        assert len(broker._ib.placed) == 1
        contract, order = broker._ib.placed[0]
        assert order.orderType == "MKT"
        assert order.action == "BUY"
        assert order.totalQuantity == 1.0

    def test_the_side_is_passed_through_not_inferred(self, broker: Any) -> None:
        """A transposed side opens the opposite position at full size."""
        self._place(broker, action="SELL")
        assert broker._ib.placed[0][1].action == "SELL"

    def test_a_lower_case_side_is_normalised(self, broker: Any) -> None:
        self._place(broker, action="sell")
        assert broker._ib.placed[0][1].action == "SELL"

    def test_a_limit_order_carries_its_price(self, broker: Any) -> None:
        self._place(broker, order_type="LMT", limit_price=1900.5)
        order = broker._ib.placed[0][1]
        assert order.orderType == "LMT"
        assert order.lmtPrice == 1900.5

    def test_a_stop_order_carries_its_stop_price(self, broker: Any) -> None:
        self._place(broker, order_type="STP", aux_price=1880.0)
        order = broker._ib.placed[0][1]
        assert order.orderType == "STP"
        assert order.stopPrice == 1880.0

    def test_a_limit_order_with_no_price_is_submitted_at_zero(self, broker: Any) -> None:
        """A finding, pinned rather than changed.

        `limit_price` defaults to `0.0`, so a limit order that forgets its
        price is not refused — it is sent with `lmtPrice=0`. IBKR rejects it,
        but the adapter has already reported `success: True`, and the rejection
        arrives asynchronously where this caller is not looking. Refusing it
        here would be a one-line guard; it is a behaviour change on the order
        path, so it is the owner's call.
        """
        result = self._place(broker, order_type="LMT")
        assert result["success"] is True
        assert broker._ib.placed[0][1].lmtPrice == 0.0

    def test_an_unsupported_order_type_is_refused_before_anything_is_sent(self, broker: Any) -> None:
        """The one input the adapter does validate. Nothing reaches TWS."""
        result = self._place(broker, order_type="TRAIL")
        assert result["success"] is False
        assert "Unsupported order_type: TRAIL" in result["comment"]
        assert broker._ib.placed == []

    def test_the_order_type_is_normalised_before_the_check(self, broker: Any) -> None:
        assert self._place(broker, order_type="mkt")["success"] is True

    def test_fx_defaults_to_the_fx_venue(self, broker: Any) -> None:
        """CASH on IDEALPRO is the FX route; SMART would route it as a stock."""
        self._place(broker)
        contract = broker._ib.placed[0][0]
        assert contract.secType == "CASH"
        assert contract.exchange == "IDEALPRO"

    def test_a_non_cash_instrument_routes_through_smart(self, broker: Any) -> None:
        self._place(broker, symbol="AAPL", sec_type="STK")
        assert broker._ib.placed[0][0].exchange == "SMART"

    @pytest.mark.parametrize("symbol", ["GC", "gc", "GC=F", "gc=f"])
    def test_gold_futures_are_auto_detected(self, broker: Any, symbol: str) -> None:
        """The docstring's reason: COMEX front-month is "the
        manipulation-resistant CLOB". Getting the symbol form wrong would route
        a futures order to the FX venue, where it does not exist."""
        self._place(broker, symbol=symbol)
        contract = broker._ib.placed[0][0]
        assert contract.symbol == "GC"
        assert contract.secType == "CONTFUT"
        assert contract.exchange == "NYMEX"

    def test_an_explicit_exchange_overrides_the_default(self, broker: Any) -> None:
        self._place(broker, exchange="IDEALPRO", sec_type="STK")
        assert broker._ib.placed[0][0].exchange == "IDEALPRO"

    def test_the_account_is_stamped_on_the_order(self, broker: Any) -> None:
        """Without it, a multi-account session places against whichever
        account TWS happens to consider current."""
        self._place(broker)
        assert broker._ib.placed[0][1].account == "DU1234567"

    def test_an_explicit_account_overrides_the_managed_one(self, broker: Any) -> None:
        self._place(broker, account="U7654321")
        assert broker._ib.placed[0][1].account == "U7654321"

    def test_the_returned_ids_come_from_the_trade(self, broker: Any) -> None:
        result = self._place(broker)
        order = broker._ib.placed[0][1]
        assert result["order_id"] == order.orderId
        assert result["perm_id"] == order.permId

    def test_success_means_queued_not_filled(self, broker: Any) -> None:
        """A finding, pinned because the word is misleading.

        `placeOrder` hands the order to the local TWS message queue and returns
        immediately — the module's own comment says so. `success: True`
        therefore means "submitted locally", and the `status` it returns is the
        pre-acknowledgement one. A caller reading `success` as "the broker has
        this order" is reading it wrong, and nothing in the returned dict says
        otherwise.
        """
        result = self._place(broker)
        assert result["success"] is True
        assert result["status"] == "PendingSubmit"

    def test_a_lost_connection_marks_the_adapter_disconnected(self, broker: Any) -> None:
        """So the next call trips `_assert_connected` instead of writing into a
        dead socket."""
        broker._ib.place_error = ConnectionError("TWS went away")
        result = self._place(broker)
        assert result["success"] is False
        assert result["error_type"] == "connection"
        assert broker.connected is False

    def test_a_bad_session_state_also_disconnects(self, broker: Any) -> None:
        broker._ib.place_error = AttributeError("'NoneType' has no attribute 'client'")
        result = self._place(broker)
        assert result["error_type"] == "session"
        assert broker.connected is False

    def test_invalid_parameters_do_not_disconnect(self, broker: Any) -> None:
        """A bad order is the caller's problem, not the session's. Dropping the
        connection would turn one rejected order into an outage."""
        broker._ib.place_error = ValueError("quantity must be positive")
        result = self._place(broker)
        assert result["error_type"] == "validation"
        assert broker.connected is True

    def test_an_unexpected_failure_is_reported_with_its_type(self, broker: Any) -> None:
        broker._ib.place_error = KeyError("201")
        result = self._place(broker)
        assert result["error_type"] == "unexpected"
        assert "KeyError" in result["comment"]
        assert broker.connected is True

    @pytest.mark.parametrize(
        "failure",
        [ConnectionError("x"), ValueError("x"), AttributeError("x"), RuntimeError("x")],
    )
    def test_no_failure_mode_reports_success(self, broker: Any, failure: Exception) -> None:
        """The property that matters most on this path: an order that did not
        reach TWS must never come back as `success: True`."""
        broker._ib.place_error = failure
        result = self._place(broker)
        assert result["success"] is False
        assert result["order_id"] == 0


# ---------------------------------------------------------------------------
# Cancelling, closing, reading
# ---------------------------------------------------------------------------


class TestCancelling:
    @pytest.fixture
    def broker(self, ibkr: Any) -> Any:
        broker = asyncio.run(_connected(ibkr))
        order = _Order(action="BUY", totalQuantity=1.0, orderType="LMT")
        order.orderId = 42
        broker._ib.open_trades = [_Trade(_Contract(symbol="XAUUSD"), order)]
        return broker

    def test_an_open_order_is_cancelled(self, broker: Any) -> None:
        result = asyncio.run(broker.cancel_order(42))
        assert result["success"] is True
        assert broker._ib.cancelled[0].orderId == 42

    def test_an_unknown_order_id_is_refused_without_cancelling_anything(self, broker: Any) -> None:
        """Cancelling the wrong order is worse than cancelling none."""
        result = asyncio.run(broker.cancel_order(999))
        assert result["success"] is False
        assert "not found in open trades" in result["comment"]
        assert broker._ib.cancelled == []

    def test_a_lost_connection_marks_the_adapter_disconnected(self, broker: Any) -> None:
        broker._ib.cancel_error = ConnectionError("gone")
        result = asyncio.run(broker.cancel_order(42))
        assert result["error_type"] == "connection"
        assert broker.connected is False

    def test_an_unexpected_failure_keeps_the_session(self, broker: Any) -> None:
        broker._ib.cancel_error = RuntimeError("already filled")
        result = asyncio.run(broker.cancel_order(42))
        assert result["success"] is False
        assert result["error_type"] == "unexpected"
        assert broker.connected is True


class TestClosingAPosition:
    @pytest.fixture
    def broker(self, ibkr: Any) -> Any:
        return asyncio.run(_connected(ibkr))

    def test_a_long_is_closed_by_selling(self, broker: Any) -> None:
        broker._ib.positions_list = [_Position("XAUUSD", 2.5)]
        result = asyncio.run(broker.close_position("XAUUSD"))
        assert result["success"] is True
        order = broker._ib.placed[0][1]
        assert order.action == "SELL"
        assert order.totalQuantity == 2.5

    def test_a_short_is_closed_by_buying(self, broker: Any) -> None:
        """The inversion is the whole method. Getting it backwards doubles the
        position instead of flattening it."""
        broker._ib.positions_list = [_Position("XAUUSD", -3.0)]
        asyncio.run(broker.close_position("XAUUSD"))
        order = broker._ib.placed[0][1]
        assert order.action == "BUY"
        assert order.totalQuantity == 3.0

    def test_the_closing_quantity_is_always_positive(self, broker: Any) -> None:
        broker._ib.positions_list = [_Position("XAUUSD", -1.75)]
        asyncio.run(broker.close_position("XAUUSD"))
        assert broker._ib.placed[0][1].totalQuantity == 1.75

    def test_it_closes_at_market_not_at_a_limit(self, broker: Any) -> None:
        """A limit order to flatten can sit unfilled while the position runs."""
        broker._ib.positions_list = [_Position("XAUUSD", 1.0)]
        asyncio.run(broker.close_position("XAUUSD"))
        assert broker._ib.placed[0][1].orderType == "MKT"

    def test_no_position_places_no_order(self, broker: Any) -> None:
        broker._ib.positions_list = []
        result = asyncio.run(broker.close_position("XAUUSD"))
        assert result["success"] is False
        assert "No open position for XAUUSD" in result["comment"]
        assert broker._ib.placed == []

    def test_another_symbols_position_is_not_closed(self, broker: Any) -> None:
        """Matching is by symbol. Flattening the wrong instrument would be an
        unrequested trade in something the caller never named."""
        broker._ib.positions_list = [_Position("EURUSD", 5.0)]
        result = asyncio.run(broker.close_position("XAUUSD"))
        assert result["success"] is False
        assert broker._ib.placed == []

    def test_a_zero_position_is_still_treated_as_a_position(self, broker: Any) -> None:
        """A finding, pinned rather than changed. IBKR can report a flat row.
        `position > 0` is False for zero, so it buys — quantity zero, which
        IBKR rejects, after the adapter reported success locally."""
        broker._ib.positions_list = [_Position("XAUUSD", 0.0)]
        asyncio.run(broker.close_position("XAUUSD"))
        order = broker._ib.placed[0][1]
        assert order.action == "BUY"
        assert order.totalQuantity == 0.0

    def test_the_instrument_details_are_carried_into_the_closing_order(self, broker: Any) -> None:
        broker._ib.positions_list = [_Position("GC", 1.0)]
        asyncio.run(broker.close_position("GC", sec_type="CONTFUT", exchange="NYMEX", currency="USD"))
        assert broker._ib.placed[0][0].exchange == "NYMEX"


class TestReadingATick:
    @pytest.fixture
    def broker(self, ibkr: Any) -> Any:
        return asyncio.run(_connected(ibkr))

    def test_a_populated_snapshot_returns_both_sides(self, broker: Any) -> None:
        tick = asyncio.run(broker.get_tick("XAUUSD"))
        assert tick["bid"] == 1950.0
        assert tick["ask"] == 1950.4
        assert tick["symbol"] == "XAUUSD"

    def test_the_mid_is_the_average_of_the_two_sides(self, broker: Any) -> None:
        assert asyncio.run(broker.get_tick("XAUUSD"))["mid"] == pytest.approx(1950.2)

    def test_the_subscription_is_always_cancelled(self, broker: Any) -> None:
        """IBKR caps concurrent market-data lines. Leaking one per call
        exhausts the allowance and the next request returns nothing."""
        asyncio.run(broker.get_tick("XAUUSD"))
        assert len(broker._ib.market_data_cancelled) == 1

    @pytest.mark.parametrize(("bid", "ask"), [(0, 1950.4), (1950.0, 0), (None, None), (0, 0), (-1.0, 1950.4)])
    def test_a_missing_side_reads_as_none_not_as_zero(self, broker: Any, bid: Any, ask: Any) -> None:
        """A zero bid is not a price. Passed through as a number it becomes a
        spread of 1950 and a mid of 975."""
        broker._ib.ticker = _Ticker(bid=bid, ask=ask, last=1950.2)
        tick = asyncio.run(broker.get_tick("XAUUSD"))
        assert tick["mid"] is None

    def test_an_empty_snapshot_still_returns_the_symbol(self, broker: Any) -> None:
        broker._ib.ticker = _Ticker()
        tick = asyncio.run(broker.get_tick("XAUUSD"))
        assert tick["symbol"] == "XAUUSD"
        assert tick["bid"] is None and tick["ask"] is None

    def test_a_failed_request_returns_none_rather_than_a_hollow_tick(self, broker: Any) -> None:
        """A dict of Nones would be indistinguishable from a real quote with
        no depth. None says "no answer"."""
        broker._ib.tick_error = RuntimeError("no market data permission")
        assert asyncio.run(broker.get_tick("XAUUSD")) is None

    def test_it_does_not_wait_the_full_window_when_data_arrives(self, broker: Any) -> None:
        """The loop exits on the first populated tick — the stated reason for
        polling at 50 ms instead of sleeping 500 ms."""
        import time

        started = time.monotonic()
        asyncio.run(broker.get_tick("XAUUSD"))
        assert time.monotonic() - started < 0.5


class TestReadingAnOrder:
    @pytest.fixture
    def broker(self, ibkr: Any) -> Any:
        broker = asyncio.run(_connected(ibkr))
        order = _Order(action="SELL", totalQuantity=2.0, orderType="LMT")
        order.orderId = 55
        broker._ib.open_trades = [_Trade(_Contract(symbol="XAUUSD"), order, status="Submitted")]
        return broker

    def test_a_known_order_maps_onto_the_platform_type(self, broker: Any) -> None:
        order = asyncio.run(broker.get_order("55"))
        assert order is not None
        assert order.id == "55"
        assert order.symbol == "XAUUSD"
        assert order.quantity == 2.0
        assert order.status == "Submitted"

    def test_the_side_is_carried_across_the_boundary(self, broker: Any, ibkr: Any) -> None:
        from brokers.base import OrderSide

        assert asyncio.run(broker.get_order("55")).side is OrderSide.SELL

    def test_an_unknown_order_id_returns_none(self, broker: Any) -> None:
        assert asyncio.run(broker.get_order("999")) is None

    @pytest.mark.parametrize("bad_id", ["abc", "", "12x", "-5", "5.5"])
    def test_a_non_numeric_id_matches_nothing_rather_than_raising(self, broker: Any, bad_id: str) -> None:
        """IBKR order ids are integers; the platform passes strings. A bare
        `int()` here would raise on a caller's typo."""
        assert asyncio.run(broker.get_order(bad_id)) is None


def _instant_sleep(recorded: list[float]):
    """Replace `asyncio.sleep` without calling it — patching the module global
    and then awaiting it from the replacement recurses forever."""

    async def _sleep(delay: float) -> None:
        recorded.append(delay)

    return _sleep


class TestReconnecting:
    def test_it_gives_up_after_the_declared_number_of_attempts(self, ibkr: Any, monkeypatch) -> None:
        broker = _broker(ibkr)
        broker._ib.connect_error = ConnectionRefusedError("TWS down")
        attempts: list[float] = []
        monkeypatch.setattr(ibkr.asyncio, "sleep", _instant_sleep(attempts))
        assert asyncio.run(broker.reconnect()) is False
        assert len(attempts) == ibkr._MAX_RECONNECT_ATTEMPTS

    def test_the_backoff_doubles(self, ibkr: Any, monkeypatch) -> None:
        """Retrying at a fixed interval against a TWS that is restarting just
        burns the attempt budget before it is ready."""
        broker = _broker(ibkr)
        broker._ib.connect_error = ConnectionRefusedError("TWS down")
        delays: list[float] = []
        monkeypatch.setattr(ibkr.asyncio, "sleep", _instant_sleep(delays))
        asyncio.run(broker.reconnect())
        assert delays == [1.0, 2.0, 4.0]

    def test_the_delay_is_capped(self, ibkr: Any, monkeypatch) -> None:
        """The cap exists so raising the attempt count cannot produce a
        multi-minute wait."""
        broker = _broker(ibkr)
        broker._ib.connect_error = ConnectionRefusedError("TWS down")
        delays: list[float] = []
        monkeypatch.setattr(ibkr, "_MAX_RECONNECT_ATTEMPTS", 8)
        monkeypatch.setattr(ibkr.asyncio, "sleep", _instant_sleep(delays))
        asyncio.run(broker.reconnect())
        assert max(delays) == 30.0

    def test_it_stops_as_soon_as_it_succeeds(self, ibkr: Any, monkeypatch) -> None:
        broker = _broker(ibkr)
        delays: list[float] = []
        monkeypatch.setattr(ibkr.asyncio, "sleep", _instant_sleep(delays))
        assert asyncio.run(broker.reconnect()) is True
        assert len(delays) == 1
        assert broker.connected is True

    def test_it_closes_the_old_session_first(self, ibkr: Any, monkeypatch) -> None:
        """Reconnecting on the same client id without disconnecting is how TWS
        ends up dropping the new session instead of the stale one."""
        broker = asyncio.run(_connected(ibkr))
        monkeypatch.setattr(ibkr.asyncio, "sleep", _instant_sleep([]))
        asyncio.run(broker.reconnect())
        assert broker._ib.disconnected >= 1


class TestTheHealthSnapshot:
    def test_it_reports_the_session_before_connecting(self, ibkr: Any) -> None:
        snapshot = _broker(ibkr).status()
        assert snapshot["broker"] == "ibkr"
        assert snapshot["connected"] is False
        assert snapshot["sdk_available"] is True
        assert snapshot["port"] is None

    def test_it_reports_the_session_after_connecting(self, ibkr: Any) -> None:
        snapshot = asyncio.run(_connected(ibkr, client_id=3)).status()
        assert snapshot["connected"] is True
        assert snapshot["account"] == "DU1234567"
        assert snapshot["client_id"] == 3
        assert snapshot["host"] == "127.0.0.1"

    def test_it_admits_when_the_sdk_is_missing(self) -> None:
        """The difference between "not connected" and "cannot connect" is the
        first thing an operator needs."""
        import brokers.ibkr_broker as real

        assert real.IBKRBroker({"server": "paper"}).status()["sdk_available"] is False
