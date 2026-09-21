# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
`TradeExecutor` exercised against connectors that reject what a venue rejects.

F106: *"TradeExecutor is tested against MagicMock brokers only. A mock with no
spec agrees with every call, so the signature mismatch that F61 describes
survives the whole suite."* The testing gap is real and this file closes it.

**The signature mismatch is not real, and this file says so on purpose.**

The register claimed `execution/trade_executor.py` calls
`self.broker.place_market_order(...)` while connectors implement `place_order`,
so every live broker would raise `AttributeError` at the first order. Measuring
it the obvious way agrees: `grep -c "def place_market_order" brokers/*.py`
returns 1 — only `paper_trading.py`.

That measurement is wrong, and wrong in the direction that invents a defect.
`BrokerConnector.place_market_order` is a **concrete base-class method**
(`brokers/base.py:558`): a uniform adapter that converts the `(symbol, side,
quantity)` router contract onto each connector's `place_order`, handles sync and
async bodies, and normalises the result to `MarketOrderResult`. Every connector
inherits it. A per-file grep cannot see an inherited method, so it counted the
one class that *overrides* it and reported the other fourteen as broken.

A fix was written against that phantom before these tests caught it: an adapter
in the executor with a `place_order` fallback branch that `getattr` can never
reach, because the base method always answers. A guard that can never open, added
while closing a finding about guards that can never open.

So the assertions below are deliberately shaped to fail if either belief drifts:

* `test_the_market_order_contract_lives_on_the_base_class` fails if the base
  method is removed — the moment the register's original claim would become true;
* the parametrised autospec test fails if any connector's inherited surface stops
  accepting the call the executor makes;
* `test_a_spec_less_mock_agrees_with_anything` is the positive control, and
  demonstrates in four lines why the pre-existing tests could not have caught
  either outcome.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

pytestmark = pytest.mark.unit

from brokers.base import BrokerConnector, OrderSide
from execution.trade_executor import TradeExecutor


def _concrete_connectors() -> list[type]:
    """Every importable concrete BrokerConnector subclass in `brokers/`."""
    import importlib
    import pkgutil

    import brokers

    found: list[type] = []
    for mod in pkgutil.iter_modules(brokers.__path__):
        try:
            module = importlib.import_module(f"brokers.{mod.name}")
        except Exception:
            continue  # an optional SDK is missing; not this test's subject
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BrokerConnector)
                and obj is not BrokerConnector
                and not inspect.isabstract(obj)
                and obj not in found
            ):
                found.append(obj)
    return found


def test_the_scan_finds_real_connectors():
    """A scan that matches nothing agrees with every assertion below (F255)."""
    connectors = _concrete_connectors()
    assert len(connectors) >= 4, f"only {len(connectors)} concrete connectors found — the scan is wrong"


def test_the_market_order_contract_lives_on_the_base_class():
    """The measurement the register got wrong, pinned so it cannot recur.

    If this fails, `BrokerConnector.place_market_order` has been removed and the
    executor's call really does need an adapter — which is what F106 and F61
    described, and what a per-file grep made it look like all along.
    """
    base_method = getattr(BrokerConnector, "place_market_order", None)
    assert base_method is not None, (
        "BrokerConnector no longer provides place_market_order — "
        "execution/trade_executor.py's call now needs an adapter onto place_order"
    )
    assert not getattr(base_method, "__isabstractmethod__", False), (
        "place_market_order became abstract — connectors must now implement it individually"
    )

    # And the inheritance is what makes it available, not per-connector code.
    inheriting = [c.__name__ for c in _concrete_connectors() if "place_market_order" not in vars(c)]
    assert inheriting, "every connector now overrides place_market_order; the base adapter is dead code"


@pytest.mark.parametrize("connector", _concrete_connectors(), ids=lambda c: c.__name__)
def test_each_connector_accepts_the_call_the_executor_makes(connector):
    """The F106 fix: a double that refuses what the real class would refuse.

    `spec_set=True` is what makes this a test rather than a restatement. Against
    a bare `MagicMock` — which is what the executor's other tests pass — this
    assertion holds no matter what the connector looks like.
    """
    broker = create_autospec(connector, spec_set=True, instance=True)

    # The exact call at execution/trade_executor.py, by keyword.
    broker.place_market_order(symbol="XAUUSD", side="buy", quantity=1.0, client_order_id="hopefx-test")

    assert broker.place_market_order.call_count == 1
    kwargs = broker.place_market_order.call_args.kwargs
    assert set(kwargs) == {"symbol", "side", "quantity", "client_order_id"}


@pytest.mark.parametrize("connector", _concrete_connectors(), ids=lambda c: c.__name__)
def test_no_connector_narrows_the_market_order_signature(connector):
    """An override may extend the contract; it may not shrink it.

    `paper_trading.PaperTradingBroker` overrides the base method. An override
    that dropped `client_order_id` would break the executor's call at that one
    broker while every other connector kept working — the kind of divergence
    that only shows up in the broker you did not test against.
    """
    signature = inspect.signature(connector.place_market_order)
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    for required in ("symbol", "side", "quantity"):
        assert required in signature.parameters, f"{connector.__name__} does not accept {required!r}"
    assert "client_order_id" in signature.parameters or accepts_kwargs, (
        f"{connector.__name__}.place_market_order accepts neither client_order_id nor **kwargs — "
        f"the executor passes it on every order, and the write-ahead journal is keyed by it"
    )


def test_the_base_adapter_refuses_a_side_it_does_not_recognise():
    """On the money path an unrecognised value must stop the order.

    `OrderSide(str(side).upper())` raises rather than defaulting, which is the
    right shape: the paper broker's own override reads
    `BUY if side in ("buy", "long") else SELL`, so there a typo, an empty string
    or a None opens a SHORT. Both producers of `signal["action"]` emit only
    "buy"/"sell" today (`pullback_strategy.py:234`,
    `HOPEFXDecisionEngine.py:598`), so nothing reaches the divergence — this
    pins the base's refusal so it stays the safe one.
    """
    for bad in ("sideways", "", "long", "short"):
        with pytest.raises(ValueError):
            OrderSide(bad.upper())

    assert OrderSide("BUY") is OrderSide.BUY
    assert OrderSide("SELL") is OrderSide.SELL


def test_the_executor_holds_the_broker_it_was_given():
    """A minimal construction check, so the tests above are about the real class."""
    broker = create_autospec(BrokerConnector, spec_set=True, instance=True)
    executor = TradeExecutor(
        broker=broker,
        risk_manager=MagicMock(),
        position_tracker=MagicMock(),
        state_store=None,
    )
    assert executor.broker is broker


def test_a_spec_less_mock_agrees_with_anything():
    """The positive control, and the reason this file exists.

    This is the shape of the executor's pre-existing tests. It passes against a
    connector surface that does not exist, which is why neither the real
    contract nor the phantom mismatch was ever visible from the suite.
    """
    broker = MagicMock()
    broker.method_that_does_not_exist = AsyncMock(return_value="fine")
    assert broker.place_market_order(symbol="XAUUSD", side="tuesday") is not None
    assert broker.utterly_invented_call() is not None
