# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`brokers/oanda_broker.py` — the kill switch's flatten, and the close paths.

CLAUDE.md: "paper trading active; live OANDA is the next milestone." So this is
the adapter about to carry real orders, and `cancel_all_orders` — the method its
own docstring says is "Called by the kill switch on activation" — was entirely
uncovered, along with `close_position`, `get_order` and `get_market_data`.

The HTTP session is a hand-written stand-in, not a `MagicMock`. The adapter uses
`async with session.put(url, json=body) as resp`, reads `resp.status`, and
awaits `resp.json()`; a specless mock satisfies all of that whatever the code
does with it, which is the trap `hopefx-dead-controls` names explicitly.

The sign convention matters here and is asserted rather than assumed. OANDA
reports short units as negative and `get_positions` passes the value through
unchanged, so `cancel_all_orders`' `short_units < 0` is the correct test. A
short position that never closed when the kill switch fired would be the worst
possible defect on this path.
"""

from __future__ import annotations

import pytest

from brokers.oanda_broker import OandaBroker

pytestmark = pytest.mark.unit


class _Response:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status = status
        self._payload = payload or {}

    async def json(self) -> dict:
        return self._payload

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None


class _Session:
    """Records every request and replies from a queue keyed by method."""

    def __init__(self) -> None:
        # `_assert_connected` reads `session.closed`. A `MagicMock` would have
        # answered that with a truthy Mock and the guard would have passed for
        # the wrong reason; the stub has to carry it.
        self.closed = False
        self.gets: list[str] = []
        self.get_params: list[dict] = []
        self.puts: list[tuple[str, dict]] = []
        self.deletes: list[str] = []
        self.get_replies: dict[str, _Response] = {}
        self.put_reply = _Response(200, {})
        self.delete_reply = _Response(200, {"orderCancelTransaction": {"id": "1"}})
        self.put_error: BaseException | None = None

    def get(self, url: str, params: dict | None = None, **_kwargs) -> _Response:
        self.gets.append(url)
        self.get_params.append(params or {})
        for fragment, reply in self.get_replies.items():
            if fragment in url:
                return reply
        return _Response(200, {})

    def put(self, url: str, json: dict | None = None, **_kwargs) -> _Response:
        if self.put_error is not None:
            raise self.put_error
        self.puts.append((url, json or {}))
        return self.put_reply

    def delete(self, url: str, **_kwargs) -> _Response:
        self.deletes.append(url)
        return self.delete_reply


def _broker(session: _Session | None = None) -> OandaBroker:
    """A broker in the state `connect()` leaves it in.

    `__init__` sets `_account_id`, `_token` and `_base_url` to None — only
    `connect()` fills them — so a helper that sets `_session` alone produces
    URLs beginning "None/v3/...". Setting them here is what makes the URL
    assertions below mean anything.
    """
    broker = OandaBroker({"api_key": "k", "account_id": "001-001-1", "environment": "practice"})
    broker._session = session
    broker._account_id = "001-001-1"
    broker._token = "k"
    broker._base_url = "https://api-fxpractice.oanda.com"
    broker.connected = session is not None
    return broker


def _positions(*rows: dict) -> _Response:
    return _Response(200, {"positions": list(rows)})


def _position(instrument: str, long_units: float = 0.0, short_units: float = 0.0) -> dict:
    return {
        "instrument": instrument,
        "long": {"units": str(long_units)},
        "short": {"units": str(short_units)},
        "unrealizedPL": "12.5",
        "pl": "3.0",
    }


class TestTheSignConventionSurvivesGetPositions:
    """OANDA reports short units negative. If `get_positions` ever normalised
    them to positive, `cancel_all_orders`' `short_units < 0` would stop being
    true and short positions would survive the kill switch."""

    @pytest.mark.asyncio
    async def test_a_short_position_keeps_its_negative_units(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", short_units=-50.0))

        (position,) = await _broker(session).get_positions()

        assert position["short_units"] == -50.0
        assert position["long_units"] == 0.0
        assert position["net_units"] == -50.0

    @pytest.mark.asyncio
    async def test_a_long_position_keeps_its_positive_units(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", long_units=30.0))

        (position,) = await _broker(session).get_positions()

        assert position["long_units"] == 30.0
        assert position["net_units"] == 30.0

    @pytest.mark.asyncio
    async def test_a_hedged_position_reports_both_sides(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", long_units=30.0, short_units=-10.0))

        (position,) = await _broker(session).get_positions()

        assert (position["long_units"], position["short_units"]) == (30.0, -10.0)
        assert position["net_units"] == 20.0


class TestCancelAllOrders:
    """The method the kill switch calls."""

    @pytest.mark.asyncio
    async def test_a_disconnected_broker_closes_nothing(self) -> None:
        assert await _broker(None).cancel_all_orders() == []

    @pytest.mark.asyncio
    async def test_a_long_position_is_closed_with_longunits_all(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", long_units=30.0))

        cancelled = await _broker(session).cancel_all_orders()

        (url, body) = session.puts[0]
        assert "positions/XAU_USD/close" in url
        assert body == {"longUnits": "ALL"}
        assert cancelled == ["XAU_USD"]

    @pytest.mark.asyncio
    async def test_a_short_position_is_closed_with_shortunits_all(self) -> None:
        """The case the sign convention decides."""
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", short_units=-50.0))

        cancelled = await _broker(session).cancel_all_orders()

        (_url, body) = session.puts[0]
        assert body == {"shortUnits": "ALL"}, "a short position was not closed"
        assert cancelled == ["XAU_USD"]

    @pytest.mark.asyncio
    async def test_a_hedged_position_closes_both_legs_in_one_request(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", long_units=30.0, short_units=-10.0))

        await _broker(session).cancel_all_orders()

        (_url, body) = session.puts[0]
        assert body == {"longUnits": "ALL", "shortUnits": "ALL"}

    @pytest.mark.asyncio
    async def test_a_flat_position_sends_no_request(self) -> None:
        """An empty close body would be rejected by OANDA and counted as a
        failure against a position that was never open."""
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD"))

        cancelled = await _broker(session).cancel_all_orders()

        assert session.puts == []
        assert cancelled == []

    @pytest.mark.asyncio
    async def test_a_position_with_no_instrument_is_skipped(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _Response(
            200, {"positions": [{"long": {"units": "10"}, "short": {"units": "0"}}]}
        )

        assert await _broker(session).cancel_all_orders() == []

    @pytest.mark.asyncio
    async def test_a_rejected_close_is_not_reported_as_cancelled(self) -> None:
        """Reporting a close that the venue refused is how a kill switch comes
        back "complete" with the position still open."""
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", long_units=30.0))
        session.put_reply = _Response(400, {"errorMessage": "CLOSEOUT_POSITION_REJECT"})

        assert await _broker(session).cancel_all_orders() == []

    @pytest.mark.asyncio
    async def test_one_position_raising_does_not_abandon_the_others(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _positions(
            _position("XAU_USD", long_units=30.0),
            _position("EUR_USD", long_units=10.0),
        )
        original_put = session.put

        def _fail_first(url: str, json: dict | None = None, **kwargs):
            if "XAU_USD" in url:
                raise RuntimeError("connection reset")
            return original_put(url, json=json, **kwargs)

        session.put = _fail_first

        assert await _broker(session).cancel_all_orders() == ["EUR_USD"]

    @pytest.mark.asyncio
    async def test_a_failing_position_fetch_still_cancels_pending_orders(self) -> None:
        """Two independent jobs. Losing the position book must not also skip
        the resting orders."""
        session = _Session()
        session.get_replies["openPositions"] = _Response(500, {})
        session.get_replies["pendingOrders"] = _Response(200, {"orders": [{"id": "77"}]})

        cancelled = await _broker(session).cancel_all_orders()

        assert "77" in cancelled

    @pytest.mark.asyncio
    async def test_pending_orders_are_cancelled_after_positions(self) -> None:
        session = _Session()
        session.get_replies["openPositions"] = _positions(_position("XAU_USD", long_units=1.0))
        session.get_replies["pendingOrders"] = _Response(200, {"orders": [{"id": "42"}]})

        cancelled = await _broker(session).cancel_all_orders()

        assert cancelled == ["XAU_USD", "42"]

    @pytest.mark.asyncio
    async def test_an_order_with_no_id_is_skipped(self) -> None:
        session = _Session()
        session.get_replies["pendingOrders"] = _Response(200, {"orders": [{}]})
        assert await _broker(session).cancel_all_orders() == []


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_a_disconnected_broker_refuses(self) -> None:
        assert await _broker(None).close_position("XAU_USD") is False

    @pytest.mark.asyncio
    async def test_it_closes_both_sides(self) -> None:
        session = _Session()
        assert await _broker(session).close_position("XAU_USD") is True
        (_url, body) = session.puts[0]
        assert body == {"longUnits": "ALL", "shortUnits": "ALL"}

    @pytest.mark.asyncio
    async def test_a_slash_symbol_is_translated_to_oandas_spelling(self) -> None:
        session = _Session()
        await _broker(session).close_position("xau/usd")
        assert "positions/XAU_USD/close" in session.puts[0][0]

    @pytest.mark.asyncio
    async def test_a_rejected_close_reports_false(self) -> None:
        session = _Session()
        session.put_reply = _Response(404, {"errorMessage": "NO_SUCH_POSITION"})
        assert await _broker(session).close_position("XAU_USD") is False


class TestMarketData:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("timeframe", "granularity"),
        [("1m", "M1"), ("5m", "M5"), ("1h", "H1"), ("4h", "H4"), ("1d", "D"), ("nonsense", "H1")],
    )
    async def test_the_timeframe_maps_to_an_oanda_granularity(self, timeframe: str, granularity: str) -> None:
        session = _Session()
        session.get_replies["candles"] = _Response(200, {"candles": []})
        broker = _broker(session)

        await broker.get_market_data("XAU/USD", timeframe=timeframe, limit=5)

        assert session.get_params[-1].get("granularity") == granularity

    @pytest.mark.asyncio
    async def test_the_symbol_is_translated(self) -> None:
        session = _Session()
        session.get_replies["candles"] = _Response(200, {"candles": []})
        await _broker(session).get_market_data("xau/usd")
        assert "XAU_USD" in session.gets[-1]


class TestStatus:
    def test_it_reports_the_environment_and_connection(self) -> None:
        status = _broker(_Session()).status()
        assert status["connected"] is True
        assert "practice" in str(status).lower() or status.get("environment") == "practice"

    def test_a_disconnected_broker_says_so(self) -> None:
        assert _broker(None).status()["connected"] is False
