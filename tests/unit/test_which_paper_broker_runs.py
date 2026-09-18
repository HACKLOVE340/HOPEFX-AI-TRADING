# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Which paper-trading engine does the platform actually run?

`brokers/__init__.py` defines a 623-line `PaperTradingBroker` at lines 280-902
and then rebinds the name at line 1274:

    try:
        from brokers.paper_trading import PaperTradingBroker as _PTB
        PaperTradingBroker = _PTB
    except Exception as _exc:
        logger.warning("PaperTradingBroker import failed: %s", _exc)

So the local class is unreachable in normal operation — and is a silent
fallback when that import fails. Two engines with different fill simulation,
slippage, commission accounting and persistence, chosen by whether an import
succeeded, announced once at WARNING.

**These tests are a tripwire, not an endorsement.** They record which engine
runs today so that changing it is a decision somebody made rather than
something that drifted. MASTER_OUTSTANDING §A6 is where the decision belongs;
when it is taken, these come back and say what was chosen instead.
"""

from __future__ import annotations

import builtins
import importlib
import sys

import pytest

pytestmark = pytest.mark.unit


def _reimport_brokers_without(module_name: str):
    """Load `brokers` with one import forced to fail, then restore."""
    real_import = builtins.__import__

    def _blocked(name: str, *args, **kwargs):
        if name == module_name or name.endswith("." + module_name.rsplit(".", 1)[-1]):
            raise ImportError(f"simulated: {module_name} is broken")
        return real_import(name, *args, **kwargs)

    saved = {k: v for k, v in sys.modules.items() if k == "brokers" or k.startswith("brokers.")}
    for key in saved:
        del sys.modules[key]
    builtins.__import__ = _blocked
    try:
        return importlib.import_module("brokers")
    finally:
        builtins.__import__ = real_import
        for key in [k for k in sys.modules if k == "brokers" or k.startswith("brokers.")]:
            del sys.modules[key]
        sys.modules.update(saved)


class TestNormally:
    def test_the_name_resolves_to_the_standalone_module(self) -> None:
        import brokers

        assert brokers.PaperTradingBroker.__module__ == "brokers.paper_trading"

    def test_the_factory_builds_that_one(self) -> None:
        import brokers

        broker = brokers.create_broker("paper", {"initial_balance": 50_000})
        assert type(broker).__module__ == "brokers.paper_trading"

    def test_nothing_in_the_package_still_points_at_the_local_class(self) -> None:
        """If this ever fails, the two engines are both reachable by name and
        callers can no longer be reasoned about from the factory alone."""
        import inspect

        import brokers

        local = [
            name
            for name, value in vars(brokers).items()
            if inspect.isclass(value) and value.__module__ == "brokers" and value.__qualname__ == "PaperTradingBroker"
        ]
        assert local == []


class TestWhenTheStandaloneModuleCannotBeImported:
    def test_a_different_engine_runs_and_the_only_notice_is_a_log_line(self) -> None:
        """The finding, executed. Not a requirement — see the module docstring."""
        brokers = _reimport_brokers_without("brokers.paper_trading")

        assert brokers.PaperTradingBroker.__module__ == "brokers"
        broker = brokers.create_broker("paper", {"initial_balance": 50_000})
        assert type(broker).__module__ == "brokers"
        # It does start and it does hold the balance, which is what makes the
        # substitution quiet rather than obvious.
        assert broker.balance == 50_000
