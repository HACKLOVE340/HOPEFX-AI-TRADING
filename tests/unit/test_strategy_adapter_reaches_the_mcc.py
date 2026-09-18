# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_strategy_adapter_reaches_the_mcc.py
====================================================
"No need to rewrite your strategies!" — and the wrapper that says so cannot be
activated.

Coverage-floor programme, Task 6c. `strategies/base_enhanced.py` was recorded at
**0%** with one production importer, `core/mcc/master_control.py:29`, which is
the Master Control Core — the component that aggregates strategy signals, risk
checks them and routes them to execution.

`MasterControlCore.register_strategy` wraps anything that is not already an
`EnhancedStrategy`:

```python
if not isinstance(strategy, EnhancedStrategy):
    strategy = StrategyAdapter(strategy)
...
strategy.mcc_callback = self._on_strategy_signal
```

`StrategyAdapter` is **not** an `EnhancedStrategy` and implements none of the
interface the MCC then uses. Measured before anything was changed:

```
adapter is EnhancedStrategy? False
  has activate:            False
  has deactivate:          False
  has get_metrics:         False
  has on_trade_completed:  False
  has is_active:           False
on_price returned: BUY
callback fired?    []          <- mcc_callback was assigned and is never called
```

and end to end, through the real `MasterControlCore`:

```
registered: ['legacy-ma']
activate_strategy -> AttributeError 'StrategyAdapter' object has no attribute 'activate'
get_status        -> AttributeError 'StrategyAdapter' object has no attribute 'get_metrics'
```

Three separate failures in one wrapper:

1. **It cannot be activated.** `activate_strategy` raises, so an adapted
   strategy never enters `active_strategies` and `on_price_update` never reaches
   it.
2. **It never reports.** Its `on_price` builds a `StrategySignal`, returns it,
   and never calls `self.mcc_callback`. `on_price_update` discards the return
   value (`master_control.py:439` assigns nothing), so even a signal that was
   produced went nowhere — the second dead-control shape, work reported through
   a channel nobody reads.
3. **It breaks a surface it is not on.** `get_status()` builds
   `{name: strat.get_metrics() ...}` across *all* strategies, so one adapted
   strategy raises `AttributeError` for the whole status payload, not just its
   own row.

**Severity is bounded by a second fact, and the record says so:** nothing in
production calls `MasterControlCore.register_strategy`. The MCC is constructed
at `core/startup_factories.py:3682` and health-checked at `api/health.py:615`,
and it runs with **zero** registered strategies. So this is latent rather than
live — and it is the wall the first person to wire a strategy into the MCC walks
into. F278.

**Fixed** by making `StrategyAdapter` an `EnhancedStrategy`, which is what the
MCC's own `isinstance` check says the wrapper is for. The base class already
holds the price history, the `is_active` gate and the callback firing; the
adapter only has to say how a legacy `on_tick` becomes a `StrategySignal`.

These tests fail on the pre-fix tree at `5fe97c7e`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

UTC = timezone.utc


class _Legacy:
    """The shape `StrategyAdapter` exists to wrap: a bare `on_tick(price)`."""

    name = "legacy-ma"
    symbol = "XAUUSD"
    timeframe = "5m"

    def __init__(self, signal: str = "BUY", strength: float = 0.9) -> None:
        self._signal = signal
        self._strength = strength
        self.ticks: list = []

    def on_tick(self, price):
        self.ticks.append(price)
        return {"signal": self._signal, "strength": self._strength}


class _Mute:
    """A legacy strategy that has an `on_tick` and returns nothing from it."""

    name = "legacy-mute"

    def on_tick(self, price):
        return None


class _NoTick:
    """A legacy object with no `on_tick` at all."""

    name = "legacy-notick"


@pytest.fixture
def adapter():
    from strategies.base_enhanced import StrategyAdapter

    return StrategyAdapter(_Legacy())


# ─────────────────────────────────────────────────────────────────────────────
# The interface the MCC actually uses
# ─────────────────────────────────────────────────────────────────────────────


class TestTheAdapterSatisfiesWhatTheMccCalls:
    def test_it_is_an_enhanced_strategy(self, adapter):
        """The MCC's own `isinstance` check is the specification.

        `register_strategy` wraps whatever fails that check; a wrapper that
        still fails it is a wrapper that solved nothing.
        """
        from strategies.base_enhanced import EnhancedStrategy

        assert isinstance(adapter, EnhancedStrategy)

    @pytest.mark.parametrize(
        "attribute",
        ["activate", "deactivate", "get_metrics", "on_trade_completed", "mcc_callback", "is_active"],
    )
    def test_every_member_master_control_reaches_for_is_present(self, adapter, attribute):
        assert hasattr(adapter, attribute), f"MasterControlCore calls .{attribute} on registered strategies"

    def test_the_name_survives_the_wrapping(self, adapter):
        assert adapter.config.name == "legacy-ma"
        assert adapter.config.symbol == "XAUUSD"
        assert adapter.config.timeframe == "5m"

    def test_an_explicit_config_wins_over_a_bare_name_attribute(self):
        """The comment in `__init__` is about this: a caller that sets
        `strategy.config = StrategyConfig(name=...)` means the config."""
        from strategies.base_enhanced import StrategyAdapter, StrategyConfig

        legacy = _Legacy()
        legacy.config = StrategyConfig(name="from-config", symbol="EURUSD", timeframe="1h")
        adapter = StrategyAdapter(legacy)
        assert adapter.config.name == "from-config"
        assert adapter.config.symbol == "EURUSD"
        assert adapter.config.timeframe == "1h"

    def test_a_non_string_name_becomes_unknown_rather_than_a_dict_key_of_a_mock(self):
        """`MasterControlCore` keys `self.strategies` by `strategy.config.name`.

        A MagicMock name would key the registry by an object whose repr changes
        between runs, so `activate_strategy("...")` could never find it again.
        """
        from unittest.mock import MagicMock

        from strategies.base_enhanced import StrategyAdapter

        legacy = MagicMock()
        adapter = StrategyAdapter(legacy)
        assert adapter.config.name == "unknown"
        assert isinstance(adapter.config.name, str)

    def test_an_object_with_no_name_at_all_becomes_unknown(self):
        from strategies.base_enhanced import StrategyAdapter

        class _Anonymous:
            def on_tick(self, price):
                return None

        assert StrategyAdapter(_Anonymous()).config.name == "unknown"


class TestItReportsToTheCallbackRatherThanReturning:
    def test_an_active_adapter_fires_the_callback(self, adapter):
        seen: list[tuple[str, str]] = []
        adapter.mcc_callback = lambda name, signal: seen.append((name, signal.action))
        adapter.activate()

        adapter.on_price(datetime.now(UTC), Decimal("2400"))
        assert seen == [("legacy-ma", "BUY")], (
            "the signal was built and never handed to the MCC, which discards the return value"
        )

    def test_it_still_returns_the_signal_for_a_direct_caller(self, adapter):
        adapter.activate()
        signal = adapter.on_price(datetime.now(UTC), Decimal("2400"))
        assert signal is not None
        assert signal.action == "BUY"
        assert signal.strength == pytest.approx(0.9)

    def test_an_inactive_adapter_reports_nothing(self, adapter):
        seen: list = []
        adapter.mcc_callback = lambda name, signal: seen.append(signal)
        assert adapter.on_price(datetime.now(UTC), Decimal("2400")) is None
        assert seen == []

    def test_deactivating_stops_it(self, adapter):
        seen: list = []
        adapter.mcc_callback = lambda name, signal: seen.append(signal)
        adapter.activate()
        adapter.on_price(datetime.now(UTC), Decimal("2400"))
        adapter.deactivate()
        adapter.on_price(datetime.now(UTC), Decimal("2401"))
        assert len(seen) == 1

    def test_the_legacy_strategy_is_the_thing_being_asked(self, adapter):
        adapter.activate()
        adapter.on_price(datetime.now(UTC), Decimal("2400"))
        assert adapter.legacy.ticks == [Decimal("2400")]

    def test_a_legacy_strategy_that_says_nothing_produces_nothing(self):
        from strategies.base_enhanced import StrategyAdapter

        adapter = StrategyAdapter(_Mute())
        seen: list = []
        adapter.mcc_callback = lambda name, signal: seen.append(signal)
        adapter.activate()
        assert adapter.on_price(datetime.now(UTC), Decimal("2400")) is None
        assert seen == []

    def test_a_legacy_object_without_on_tick_produces_nothing_rather_than_raising(self):
        from strategies.base_enhanced import StrategyAdapter

        adapter = StrategyAdapter(_NoTick())
        adapter.activate()
        assert adapter.on_price(datetime.now(UTC), Decimal("2400")) is None

    def test_a_low_confidence_signal_is_not_reported(self):
        """`EnhancedStrategy.on_price` gates the callback on `signal.is_valid()`,
        which requires `confidence > 0.5`. Asserted so the gate stays visible:
        it is the reason a signal can be returned and not reported."""
        from strategies.base_enhanced import StrategyAdapter, StrategySignal

        adapter = StrategyAdapter(_Legacy())
        adapter.activate()
        seen: list = []
        adapter.mcc_callback = lambda name, signal: seen.append(signal)

        adapter.generate_signal = lambda *a, **kw: StrategySignal("BUY", confidence=0.4)  # type: ignore[assignment]
        returned = adapter.on_price(datetime.now(UTC), Decimal("2400"))

        assert returned is not None
        assert seen == []


class TestThroughTheRealMasterControlCore:
    """The end-to-end path, because the failure was in the seam and not in
    either class read on its own."""

    @pytest.fixture
    def mcc(self):
        from core.mcc.master_control import MasterControlCore

        return MasterControlCore()

    def test_a_legacy_strategy_can_be_registered_and_activated(self, mcc):
        mcc.register_strategy(_Legacy())
        mcc.activate_strategy("legacy-ma")
        assert mcc.active_strategies == ["legacy-ma"]

    def test_the_heatmap_payload_includes_it(self, mcc):
        """`get_heatmap_data`, not `get_status` — the first draft of this test
        named the wrong method and failed on a `KeyError` rather than on the
        defect. `master_control.py:593` is the line that calls `get_metrics`."""
        mcc.register_strategy(_Legacy())
        data = mcc.get_heatmap_data()
        assert "legacy-ma" in data["strategies"]
        assert data["strategies"]["legacy-ma"]["name"] == "legacy-ma"

    def test_one_adapted_strategy_does_not_break_the_heatmap_for_the_others(self, mcc):
        """`get_heatmap_data` builds a dict comprehension across every strategy,
        so an AttributeError on one row took the whole payload with it — not
        just the adapted strategy's own entry."""
        from strategies.base_enhanced import EnhancedStrategy, StrategyConfig, StrategySignal

        class _Native(EnhancedStrategy):
            def generate_signal(self, timestamp, price, bid=None, ask=None):
                return StrategySignal("HOLD")

        mcc.register_strategy(_Native(StrategyConfig(name="native")))
        mcc.register_strategy(_Legacy())
        assert set(mcc.get_heatmap_data()["strategies"]) == {"native", "legacy-ma"}

    def test_a_price_update_reaches_the_mccs_own_signal_handler(self, mcc):
        seen: list = []
        mcc._on_strategy_signal = lambda name, signal: seen.append((name, signal.action))  # type: ignore[assignment]
        mcc.register_strategy(_Legacy())
        mcc.activate_strategy("legacy-ma")

        mcc.on_price_update("XAUUSD", Decimal("2400"))
        assert seen == [("legacy-ma", "BUY")], (
            "on_price_update discards the return value, so the callback is the only route in"
        )

    def test_a_registered_but_inactive_strategy_is_not_asked(self, mcc):
        seen: list = []
        mcc._on_strategy_signal = lambda name, signal: seen.append(signal)  # type: ignore[assignment]
        mcc.register_strategy(_Legacy())
        mcc.on_price_update("XAUUSD", Decimal("2400"))
        assert seen == []


# ─────────────────────────────────────────────────────────────────────────────
# The rest of the module, previously at 0%
# ─────────────────────────────────────────────────────────────────────────────


class TestTheConfigDefaults:
    def test_regime_preference_defaults_to_any_rather_than_none(self):
        """`__post_init__` exists for this: a `None` list would fail the first
        membership test a regime filter makes."""
        from strategies.base_enhanced import StrategyConfig

        assert StrategyConfig(name="s").regime_preference == ["any"]

    def test_an_explicit_regime_preference_is_left_alone(self):
        from strategies.base_enhanced import StrategyConfig

        assert StrategyConfig(name="s", regime_preference=["trending"]).regime_preference == ["trending"]

    def test_the_monetary_defaults_are_decimal_not_float(self):
        """`hopefx-money-precision`: risk and position size are authoritative
        numbers and this module keeps them in Decimal. A float default here
        would put the drift back at the top of the chain."""
        from strategies.base_enhanced import StrategyConfig

        config = StrategyConfig(name="s")
        assert isinstance(config.risk_per_trade, Decimal)
        assert isinstance(config.max_position, Decimal)
        assert config.risk_per_trade == Decimal("0.01")

    def test_the_defaults_name_this_platforms_instrument(self):
        from strategies.base_enhanced import StrategyConfig

        config = StrategyConfig(name="s")
        assert config.symbol == "XAUUSD"
        assert config.enabled is True
        assert config.min_bars == 20


class TestTheSignal:
    def test_strength_and_confidence_are_clamped_to_the_unit_interval(self):
        from strategies.base_enhanced import StrategySignal

        high = StrategySignal("BUY", strength=9.0, confidence=4.0)
        low = StrategySignal("BUY", strength=-3.0, confidence=-1.0)
        assert (high.strength, high.confidence) == (1.0, 1.0)
        assert (low.strength, low.confidence) == (0.0, 0.0)

    def test_a_valid_signal_needs_a_known_action_and_confidence_above_a_half(self):
        from strategies.base_enhanced import StrategySignal

        assert StrategySignal("BUY", confidence=0.51).is_valid() is True
        assert StrategySignal("HOLD", confidence=0.7).is_valid() is True
        assert StrategySignal("SELL", confidence=0.7).is_valid() is True

    def test_exactly_a_half_is_not_enough(self):
        """The boundary is `> 0.5`, not `>=`, and the default is 0.7."""
        from strategies.base_enhanced import StrategySignal

        assert StrategySignal("BUY", confidence=0.5).is_valid() is False

    def test_an_unknown_action_is_never_valid(self):
        from strategies.base_enhanced import StrategySignal

        assert StrategySignal("buy", confidence=0.9).is_valid() is False
        assert StrategySignal("CLOSE", confidence=0.9).is_valid() is False

    def test_it_stamps_itself_with_an_aware_timestamp(self):
        from strategies.base_enhanced import StrategySignal

        assert StrategySignal("BUY").timestamp.tzinfo is not None

    def test_metadata_defaults_to_an_empty_dict_not_none(self):
        from strategies.base_enhanced import StrategySignal

        assert StrategySignal("BUY").metadata == {}


class TestTheBaseClassBookkeeping:
    @pytest.fixture
    def strategy(self):
        from strategies.base_enhanced import EnhancedStrategy, StrategyConfig, StrategySignal

        class _Concrete(EnhancedStrategy):
            def generate_signal(self, timestamp, price, bid=None, ask=None):
                return StrategySignal("BUY", strength=0.8)

        return _Concrete(StrategyConfig(name="concrete"))

    def test_it_starts_inactive(self, strategy):
        assert strategy.is_active is False
        assert strategy.on_price(datetime.now(UTC), Decimal("2400")) is None

    def test_the_price_history_is_bounded(self, strategy):
        strategy.activate()
        strategy.max_history = 5
        for i in range(20):
            strategy.on_price(datetime.now(UTC), Decimal(2400 + i))
        assert len(strategy.price_history) == 5

    def test_the_oldest_prices_are_the_ones_dropped(self, strategy):
        strategy.activate()
        strategy.max_history = 3
        for i in range(6):
            strategy.on_price(datetime.now(UTC), Decimal(2400 + i))
        assert [p for _t, p in strategy.price_history] == [Decimal(2403), Decimal(2404), Decimal(2405)]

    def test_a_completed_trade_is_counted_as_a_win_or_a_loss(self, strategy):
        strategy.on_trade_completed(Decimal("120.50"))
        strategy.on_trade_completed(Decimal("-40.25"))
        assert strategy.performance["trades"] == 2
        assert strategy.performance["wins"] == 1
        assert strategy.performance["losses"] == 1

    def test_a_break_even_trade_counts_as_a_loss(self, strategy):
        """`if pnl > 0 ... else` — zero falls to the loss branch. Asserted
        rather than changed: it is a defensible convention, and a reader who
        assumes otherwise will mis-read the win rate."""
        strategy.on_trade_completed(Decimal("0"))
        assert strategy.performance["losses"] == 1

    def test_the_running_pnl_stays_decimal(self, strategy):
        """`hopefx-money-precision`: accumulated P&L is authoritative here, so
        the sum must not silently become a float."""
        strategy.on_trade_completed(Decimal("0.10"))
        strategy.on_trade_completed(Decimal("0.20"))
        total = strategy.performance["total_pnl"]
        assert isinstance(total, Decimal)
        assert total == Decimal("0.30"), "exact, which is the whole reason for Decimal here"

    def test_the_win_rate_is_zero_rather_than_a_division_by_zero(self, strategy):
        assert strategy.get_metrics()["win_rate"] == 0

    def test_the_metrics_leave_decimal_at_the_edge(self, strategy):
        """Converting on the way out to a dashboard is the conversion this
        codebase's rule allows — the value is leaving the process."""
        strategy.on_trade_completed(Decimal("50"))
        metrics = strategy.get_metrics()
        assert metrics == {
            "name": "concrete",
            "win_rate": 1.0,
            "total_pnl": 50.0,
            "current_drawdown": 0.0,
            "is_active": False,
        }
        assert isinstance(metrics["total_pnl"], float)
