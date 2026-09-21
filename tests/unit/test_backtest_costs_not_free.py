"""Regression tests: the backtester must not be frictionless.

Round 3 audit findings S3-01, S3-03 and S3-04 (docs/HARDENING_BACKLOG.md).

S3-01 — three defaults compounded so that `run.py --mode backtest` reported
**zero** transaction costs:

  1. ``DataFrameDataHandler`` synthesised every bar with ``bid = ask = close``,
     so ``tick.spread`` was always ``0.0``.
  2. ``BacktestEngine.__init__`` fell back to ``TransactionCostModel(seed=seed)``
     when none was supplied.
  3. That model defaulted ``commission_per_lot``, ``commission_rate``,
     ``spread_pips`` and ``slippage_pips`` all to ``0.0``.

``backtesting/cli_runner.py`` — the path ``run.py --mode backtest`` uses —
passes no cost model, so every trade filled exactly at the bar close for free.
On 5-minute XAUUSD at two round trips a day, that is roughly $60-90k of costs
per year (100 oz/trade) missing from the equity curve, and any strategy whose
edge is smaller than the spread shows a positive Sharpe.

S3-03 — slippage converted pips with a hardcoded ``0.0001`` (the FX
4-decimal convention). Gold's pip is ``$0.10``, as this repo's own
``engine_config.py:433`` documents. An operator who *correctly* configured
``slippage_pips=3`` to model realistic gold slippage got ``$0.0003``.

S3-04 — commission divided quantity by ``100000`` (the FX standard lot). A
gold contract is **100 oz**, so a $7/lot commission on 100 oz booked as
``$0.007``.
"""

import pytest


def _tick(symbol="XAU/USD", bid=3300.0, ask=3300.30):
    from datetime import datetime, timezone

    from backtesting.engine import TickData

    return TickData(
        timestamp=datetime.now(timezone.utc),
        symbol=symbol,
        bid=bid,
        ask=ask,
        volume=1.0,
    )


def _order(side_buy=True, symbol="XAU/USD", quantity=100.0):
    from datetime import datetime, timezone

    from backtesting.engine import Order, OrderSide, OrderType

    return Order(
        order_id="o1",
        timestamp=datetime.now(timezone.utc),
        symbol=symbol,
        side=OrderSide.BUY if side_buy else OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=quantity,
    )


@pytest.mark.unit
class TestGoldPipConventions:
    def test_slippage_uses_gold_pip_not_fx_pip(self):
        """3 pips of gold slippage is $0.30, not $0.0003 (S3-03)."""
        from backtesting.engine import TransactionCostModel

        model = TransactionCostModel(slippage_model="fixed", slippage_pips=3.0)
        _fill, _comm, slippage = model.calculate_costs(_order(), _tick(), quantity=100.0)

        assert slippage == pytest.approx(0.30, rel=1e-6), (
            f"Gold pip is $0.10 — 3 pips must be $0.30, got ${slippage} "
            "(the FX 0.0001 convention understates gold slippage 1000x)."
        )

    def test_fx_symbols_still_use_the_fx_pip(self):
        """Don't fix gold by breaking FX: EUR/USD keeps the 0.0001 pip."""
        from backtesting.engine import TransactionCostModel

        model = TransactionCostModel(slippage_model="fixed", slippage_pips=3.0)
        _fill, _comm, slippage = model.calculate_costs(
            _order(symbol="EUR/USD"), _tick(symbol="EUR/USD", bid=1.0850, ask=1.0851), quantity=1000.0
        )

        assert slippage == pytest.approx(0.0003, rel=1e-6)

    def test_commission_uses_the_gold_contract_size(self):
        """$7/lot on 100 oz of gold is $7, not $0.007 (S3-04)."""
        from backtesting.engine import TransactionCostModel

        model = TransactionCostModel(commission_per_lot=7.0)
        _fill, commission, _slip = model.calculate_costs(_order(), _tick(), quantity=100.0)

        assert commission == pytest.approx(7.0, rel=1e-6), (
            f"A gold lot is 100 oz — $7/lot on 100 oz must be $7, got ${commission}."
        )

    def test_slippage_moves_price_against_the_order(self):
        """Slippage must always be a cost, on both sides."""
        from backtesting.engine import TransactionCostModel

        model = TransactionCostModel(slippage_model="fixed", slippage_pips=3.0)
        tick = _tick()

        buy_fill, _, _ = model.calculate_costs(_order(side_buy=True), tick, 100.0)
        sell_fill, _, _ = model.calculate_costs(_order(side_buy=False), tick, 100.0)

        assert buy_fill > tick.ask, "a buy must fill above the ask"
        assert sell_fill < tick.bid, "a sell must fill below the bid"


@pytest.mark.unit
class TestBacktestIsNotFree:
    def test_dataframe_handler_applies_a_spread(self):
        """bid == ask == close made every backtest frictionless (S3-01)."""
        import pandas as pd

        from backtesting.engine import DataFrameDataHandler

        idx = pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC")
        df = pd.DataFrame(
            {"open": 3300.0, "high": 3301.0, "low": 3299.0, "close": 3300.0, "volume": 1.0},
            index=idx,
        )
        handler = DataFrameDataHandler(df, "XAU/USD")
        ticks = list(handler.get_data(idx[0], idx[-1], ["XAU/USD"]))

        assert ticks, "handler yielded nothing"
        for _ts, _sym, tick in ticks:
            assert tick.ask > tick.bid, "synthetic ticks must carry a non-zero spread"
            assert tick.spread > 0.0
            # Mid must still be the bar close — the spread straddles it.
            assert (tick.bid + tick.ask) / 2 == pytest.approx(3300.0, rel=1e-9)

    def test_default_engine_is_not_zero_cost(self):
        """A BacktestEngine built with no cost model must still charge costs."""
        from backtesting.engine import BacktestEngine

        engine = BacktestEngine(initial_capital=100_000.0)
        model = engine.transaction_costs

        _fill, commission, slippage = model.calculate_costs(_order(), _tick(), quantity=100.0)
        assert (commission > 0.0) or (slippage > 0.0), (
            "The default backtest charged zero commission AND zero slippage — "
            "any strategy whose edge is under the spread would look profitable (S3-01)."
        )

    def test_cli_runner_wires_a_spread_and_costs(self):
        """The path `run.py --mode backtest` uses must not be frictionless.

        cli_runner builds its own BacktestEngine and DataFrameDataHandler with
        no cost model; this pins that those defaults now charge something.
        """
        import inspect

        import pandas as pd

        from backtesting import cli_runner
        from backtesting.engine import BacktestEngine, DataFrameDataHandler

        # The handler cli_runner constructs must produce a real spread.
        idx = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
        df = pd.DataFrame(
            {"open": 3300.0, "high": 3301.0, "low": 3299.0, "close": 3300.0, "volume": 1.0},
            index=idx,
        )
        _ts, _sym, tick = next(iter(DataFrameDataHandler(df, "XAU/USD").get_data(idx[0], idx[-1], ["XAU/USD"])))
        assert tick.spread > 0.0

        # And the engine it constructs must charge slippage.
        engine = BacktestEngine(initial_capital=100_000.0)
        _fill, _comm, slippage = engine.transaction_costs.calculate_costs(_order(), tick, 100.0)
        assert slippage > 0.0

        # Guard the wiring itself: cli_runner must not silently opt out.
        src = inspect.getsource(cli_runner.run_backtest)
        assert "spread_pips=0" not in src and "slippage_pips=0" not in src, (
            "cli_runner must not disable backtest costs (S3-01)."
        )
