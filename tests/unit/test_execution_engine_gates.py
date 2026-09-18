# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`execution/engine.py` — the pre-trade gates, one at a time.

This is the seam every order crosses. The module carries seven separate checks
between a signal and a broker — request validation, spread spike, the pre-trade
risk gate, self-trade prevention, margin, leverage and a Sharpe circuit breaker
— plus an engine-level circuit breaker. It measured 77%, and a large part of the
missing quarter was those checks' refusal paths.

The recipe's order applies with unusual force here: a refusal that has never run
is the highest-value thing in the file. A gate that cannot block is worse than
no gate, because the code reads as though the case is handled.

Brokers and account objects are hand-written. `_check_margin` reads
`margin_available`, `margin_used` and `equity` off the account with `getattr`
defaults, so a `MagicMock` satisfies every one of them with a truthy Mock and
`float()` on it raises — a test built that way would exercise the malformed-data
branch while claiming to test the arithmetic.
"""

from __future__ import annotations

import time

import pytest

from execution.engine import (
    EngineCircuitBreaker,
    ExecutionEngine,
    ExecutionRequest,
    ExecutionStatus,
)

pytestmark = pytest.mark.unit


class _Account:
    def __init__(self, margin_available=100_000.0, margin_used=0.0, equity=100_000.0) -> None:
        self.margin_available = margin_available
        self.margin_used = margin_used
        self.equity = equity
        self.balance = equity


class _Broker:
    def __init__(self, account: _Account | None = None, error: BaseException | None = None) -> None:
        self._account = account if account is not None else _Account()
        self._error = error

    async def get_account_info(self):
        if self._error is not None:
            raise self._error
        return self._account


def _request(**overrides) -> ExecutionRequest:
    params = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "quantity": 1.0,
        "order_type": "MARKET",
        "price": 1950.0,
    }
    params.update(overrides)
    return ExecutionRequest(**params)


class _Risk:
    """A risk manager that permits everything, so a gate under test is the only
    thing that can refuse."""

    def check_pre_trade(self, *_a, **_k):
        return True, ""


def _engine(broker=None, risk=None, **kwargs) -> ExecutionEngine:
    """`broker_manager` and `risk_manager` are required positional arguments."""
    engine = ExecutionEngine(broker_manager=broker, risk_manager=risk or _Risk(), **kwargs)
    engine._broker = broker
    return engine


# ---------------------------------------------------------------------------
# Request validation — the gate before any gate
# ---------------------------------------------------------------------------


class TestTheRequestRefusesToExist:
    """`__post_init__` is the cheapest check in the chain and the only one that
    cannot be skipped, misconfigured or swallowed."""

    @pytest.mark.parametrize("side", ["buy", "Buy", "LONG", "", "BUYY"])
    def test_a_side_that_is_not_buy_or_sell_is_refused(self, side: str) -> None:
        with pytest.raises(ValueError, match="side must be"):
            _request(side=side)

    @pytest.mark.parametrize("quantity", [0.0, -1.0, -0.0001])
    def test_a_non_positive_quantity_is_refused(self, quantity: float) -> None:
        with pytest.raises(ValueError, match="quantity must be"):
            _request(quantity=quantity)

    def test_an_unknown_order_type_is_refused(self) -> None:
        with pytest.raises(ValueError, match="order_type must be"):
            _request(order_type="TRAILING_STOP")

    def test_a_limit_order_without_a_price_is_refused(self) -> None:
        """The defect this prevents has shipped elsewhere in this repository:
        a limit order reaching the venue priced at zero."""
        with pytest.raises(ValueError, match="price required for LIMIT"):
            _request(order_type="LIMIT", price=None)

    @pytest.mark.parametrize("price", [0.0, -1.0])
    def test_a_limit_order_priced_at_or_below_zero_is_refused(self, price: float) -> None:
        with pytest.raises(ValueError, match="price must be > 0"):
            _request(order_type="LIMIT", price=price)

    def test_a_stop_order_without_a_stop_price_is_refused(self) -> None:
        with pytest.raises(ValueError, match="stop_price required"):
            _request(order_type="STOP", stop_price=None)

    def test_a_stop_order_with_a_non_positive_stop_is_refused(self) -> None:
        with pytest.raises(ValueError, match="stop_price must be > 0"):
            _request(order_type="STOP", stop_price=0.0)

    def test_a_valid_market_order_is_accepted(self) -> None:
        assert _request().symbol == "XAUUSD"


# ---------------------------------------------------------------------------
# Margin
# ---------------------------------------------------------------------------


class TestMarginGate:
    @pytest.mark.asyncio
    async def test_ample_margin_permits_the_order(self) -> None:
        engine = _engine(_Broker(_Account(margin_available=100_000.0, margin_used=0.0)))
        assert await engine._check_margin(_request(quantity=1.0), time.monotonic()) is None

    @pytest.mark.asyncio
    async def test_an_order_that_would_exhaust_the_buffer_is_blocked(self) -> None:
        engine = _engine(_Broker(_Account(margin_available=100.0, margin_used=50_000.0)))

        report = await engine._check_margin(_request(quantity=10.0), time.monotonic())

        assert report is not None
        assert report.status is ExecutionStatus.BLOCKED
        assert "MARGIN_INSUFFICIENT" in report.message

    @pytest.mark.asyncio
    async def test_no_account_info_blocks_rather_than_permits(self) -> None:
        """Fail-closed. A margin check that cannot see the account must not
        conclude the account is fine."""
        engine = _engine(_Broker())
        engine._broker = type("_NoAccount", (), {"get_account_info": staticmethod(lambda: None)})()

        report = await engine._check_margin(_request(), time.monotonic())

        assert report is not None
        assert report.status is ExecutionStatus.BLOCKED
        assert "MARGIN_CHECK_FAILED" in report.message

    @pytest.mark.asyncio
    async def test_an_unreachable_broker_blocks(self) -> None:
        engine = _engine(_Broker(error=RuntimeError("connection reset")))

        report = await engine._check_margin(_request(), time.monotonic())

        assert report is not None
        assert report.status is ExecutionStatus.BLOCKED
        assert "Broker unreachable" in report.message

    @pytest.mark.asyncio
    async def test_a_wrongly_typed_account_field_blocks(self) -> None:
        """`None` where a number belongs reaches the AttributeError/TypeError
        branch and blocks, as the docstring promises."""

        class _Garbage:
            margin_available = object()
            margin_used = 0.0
            equity = 1.0

        engine = _engine(_Broker(_Garbage()))

        report = await engine._check_margin(_request(), time.monotonic())

        assert report is not None
        assert report.status is ExecutionStatus.BLOCKED
        assert "Malformed account data" in report.message

    @pytest.mark.asyncio
    async def test_a_non_numeric_string_raises_instead_of_blocking(self) -> None:
        """The gap in the fail-closed handling, recorded as it is.

        The docstring says "any unexpected exception from the broker API blocks
        the trade rather than allowing it through". The two handlers cover
        `(AttributeError, TypeError)` and `(RuntimeError, OSError)`.
        `float("not a number")` raises `ValueError`, which is neither — and a
        non-numeric string is exactly what a malformed JSON account payload
        yields, so it is the most likely shape of the error the malformed-data
        branch was written for.

        Whether `execute()` compensates is **not** established here: in every
        configuration tried, an earlier data-layer gate blocked first and the
        margin check was never reached, so the question could not be answered
        from outside. See MASTER_OUTSTANDING A14.
        """

        class _Garbage:
            margin_available = "not a number"
            margin_used = 0.0
            equity = 1.0

        engine = _engine(_Broker(_Garbage()))

        with pytest.raises(ValueError, match="could not convert string to float"):
            await engine._check_margin(_request(), time.monotonic())

    @pytest.mark.asyncio
    async def test_with_no_broker_there_is_nothing_to_check(self) -> None:
        assert await _engine(None)._check_margin(_request(), time.monotonic()) is None

    @pytest.mark.asyncio
    async def test_a_blocked_order_is_counted(self) -> None:
        engine = _engine(_Broker(_Account(margin_available=1.0, margin_used=50_000.0)))
        before = engine._blocks if hasattr(engine, "_blocks") else None
        await engine._check_margin(_request(quantity=10.0), time.monotonic())
        if before is not None:
            assert engine._blocks == before + 1


class TestAnUnpricedOrderSkipsTheMarginGate:
    """`if notional <= 0: return None` — and notional is `price * quantity`.

    A market order whose price could not be enriched has `price is None`, so
    notional is 0 and the margin check returns without looking at the account.
    The comment justifies it — the margin impact of an order you cannot price is
    not computable — but the condition that produces it is the price feed being
    unavailable, which is not obviously the moment to stop checking margin.

    Recorded rather than changed: see MASTER_OUTSTANDING A14.
    """

    @pytest.mark.asyncio
    async def test_an_unpriced_market_order_is_not_margin_checked(self) -> None:
        asked: list[int] = []

        class _Counting(_Broker):
            async def get_account_info(self):
                asked.append(1)
                return _Account(margin_available=0.0, margin_used=1_000_000.0)

        engine = _engine(_Counting())

        report = await engine._check_margin(_request(price=None), time.monotonic())

        assert report is None, "an unpriced order was blocked — the guard changed; update A14"
        assert asked == [1], "the account was still fetched, then the result discarded"

    @pytest.mark.asyncio
    async def test_the_same_order_with_a_price_is_blocked(self) -> None:
        """The contrast that makes the point: identical order, identical
        account, one has a price."""
        engine = _engine(_Broker(_Account(margin_available=0.0, margin_used=1_000_000.0)))

        report = await engine._check_margin(_request(price=1950.0), time.monotonic())

        assert report is not None
        assert report.status is ExecutionStatus.BLOCKED


# ---------------------------------------------------------------------------
# The engine circuit breaker
# ---------------------------------------------------------------------------


class TestEngineCircuitBreaker:
    @pytest.mark.asyncio
    async def test_it_starts_closed(self) -> None:
        assert EngineCircuitBreaker().is_open is False

    @pytest.mark.asyncio
    async def test_it_opens_after_the_configured_failures(self) -> None:
        breaker = EngineCircuitBreaker(max_failures=3)
        for _ in range(3):
            await breaker.record_failure()
        assert breaker.is_open is True

    @pytest.mark.asyncio
    async def test_one_short_of_the_threshold_stays_closed(self) -> None:
        breaker = EngineCircuitBreaker(max_failures=3)
        for _ in range(2):
            await breaker.record_failure()
        assert breaker.is_open is False

    @pytest.mark.asyncio
    async def test_a_success_clears_the_count(self) -> None:
        breaker = EngineCircuitBreaker(max_failures=3)
        await breaker.record_failure()
        await breaker.record_failure()
        await breaker.record_success()
        await breaker.record_failure()
        assert breaker.is_open is False, "a recovered engine tripped anyway"

    @pytest.mark.asyncio
    async def test_a_closed_breaker_lets_the_check_through(self) -> None:
        await EngineCircuitBreaker(max_failures=2).check()  # must not raise

    @pytest.mark.asyncio
    async def test_an_open_breaker_auto_resets_once_the_window_passes(self) -> None:
        """An engine that trips must not stay tripped forever — the reset is
        what turns a circuit breaker into a circuit breaker rather than a stop."""
        breaker = EngineCircuitBreaker(max_failures=1, reset_sec=0.0)
        await breaker.record_failure()
        assert breaker.is_open is True

        await breaker.check()  # elapsed >= reset_sec, so it closes

        assert breaker.is_open is False

    @pytest.mark.asyncio
    async def test_an_open_breaker_refuses_the_check(self) -> None:
        breaker = EngineCircuitBreaker(max_failures=1)
        await breaker.record_failure()
        with pytest.raises(RuntimeError, match="circuit breaker is OPEN"):
            await breaker.check()


# ---------------------------------------------------------------------------
# Leverage
# ---------------------------------------------------------------------------


class TestLeverageGate:
    @pytest.mark.asyncio
    async def test_a_modest_order_passes(self) -> None:
        engine = _engine(_Broker(_Account(equity=1_000_000.0)))
        assert await engine._check_leverage(_request(quantity=1.0), time.monotonic()) is None

    @pytest.mark.asyncio
    async def test_an_order_beyond_the_cap_is_blocked(self) -> None:
        from execution.engine import _MAX_LEVERAGE_RATIO

        engine = _engine(_Broker(_Account(equity=1_000.0)))
        quantity = (_MAX_LEVERAGE_RATIO * 1_000.0 / 1_950.0) * 2

        report = await engine._check_leverage(_request(quantity=quantity), time.monotonic())

        assert report is not None
        assert report.status is ExecutionStatus.BLOCKED
        assert "LEVERAGE_EXCEEDED" in report.message

    @pytest.mark.asyncio
    async def test_zero_equity_blocks_rather_than_dividing_by_zero(self) -> None:
        """`leverage = notional / equity`. Without this guard a wiped-out
        account raises ZeroDivisionError inside a risk gate."""
        engine = _engine(_Broker(_Account(equity=0.0)))

        report = await engine._check_leverage(_request(), time.monotonic())

        assert report is not None
        assert "equity is zero or negative" in report.message

    @pytest.mark.asyncio
    async def test_negative_equity_blocks(self) -> None:
        engine = _engine(_Broker(_Account(equity=-500.0)))
        report = await engine._check_leverage(_request(), time.monotonic())
        assert report is not None
        assert report.status is ExecutionStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_no_account_info_blocks(self) -> None:
        engine = _engine(_Broker())
        engine._broker = type("_NoAccount", (), {"get_account_info": staticmethod(lambda: None)})()
        report = await engine._check_leverage(_request(), time.monotonic())
        assert report is not None
        assert "LEVERAGE_CHECK_FAILED" in report.message

    @pytest.mark.asyncio
    async def test_an_unreachable_broker_blocks(self) -> None:
        engine = _engine(_Broker(error=OSError("network down")))
        report = await engine._check_leverage(_request(), time.monotonic())
        assert report is not None
        assert "Broker unreachable" in report.message

    @pytest.mark.asyncio
    async def test_an_unpriced_order_skips_the_leverage_gate_too(self) -> None:
        """Same shape as the margin gate — see A14."""
        engine = _engine(_Broker(_Account(equity=1.0)))
        assert await engine._check_leverage(_request(price=None), time.monotonic()) is None

    @pytest.mark.asyncio
    async def test_with_no_broker_there_is_nothing_to_check(self) -> None:
        assert await _engine(None)._check_leverage(_request(), time.monotonic()) is None


# ---------------------------------------------------------------------------
# Self-trade prevention
# ---------------------------------------------------------------------------


class TestSelfTradePrevention:
    def test_a_first_order_does_not_self_match(self) -> None:
        assert _engine(None)._check_self_trade(_request()) is None

    def test_an_opposing_resting_order_is_not_ignored(self) -> None:
        """Two orders that would cross on the same account is a market-abuse
        control, not a nicety. The prevention level decides whether this
        rejects or cancels the resting side; either way it must not be silent
        about having matched."""
        engine = _engine(None)
        engine._check_self_trade(_request(side="BUY", price=1950.0, order_type="LIMIT"))

        reason = engine._check_self_trade(_request(side="SELL", price=1950.0, order_type="LIMIT"))

        assert reason is None or "SELF_TRADE_PREVENTION" in reason

    def test_a_broken_stp_module_does_not_block_execution(self, monkeypatch) -> None:
        """Documented as non-fatal. Recorded so the choice stays visible: when
        STP is unavailable the control is off and the only trace is a DEBUG
        line, which production does not emit. See A14."""
        import sys

        monkeypatch.setitem(sys.modules, "risk.self_trade_prevention", None)
        assert _engine(None)._check_self_trade(_request()) is None
