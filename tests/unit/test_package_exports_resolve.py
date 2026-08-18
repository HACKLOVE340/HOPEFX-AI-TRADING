# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_package_exports_resolve.py
==========================================
Package `__init__` files advertised names that resolve to ``None`` — or to
nothing at all — while still listing them in ``__all__``.

The shape, repeated across seven packages:

    try:
        from market_data.ibkr_feed import IBKRFeed      # class is
    except Exception as _exc:                           # IBKRMarketDataFeed
        logger.debug("market_data.ibkr_feed unavailable: %s", _exc)
        IBKRFeed = None

    __all__ = [..., "IBKRFeed", ...]

The name in the `try` never existed, so the import raised on every interpreter
start, the handler logged at DEBUG (invisible in normal runs) and bound the
name to ``None``. ``from market_data import IBKRFeed`` then hands back ``None``
and the caller fails later, somewhere else, with an unrelated-looking
``TypeError``. The docstring above each import advertised the name as public
API the whole time.

Measured before the fix:

    compliance.AMLEngine              UNBOUND  (listed in __all__)
    compliance.ComplianceAuditor      UNBOUND  (listed in __all__)
    deployment.HelmChartGenerator     UNBOUND  (listed in __all__)
    infrastructure.Summary            UNBOUND  (listed in __all__)
    infrastructure.StructuredLogger   None
    market_data.IBKRFeed              None
    visualization.EquityCurve         None
    events.DomainEvent                None
    data_layer.feeds.news.NewsBaseFeed / FinnhubNewsFeed / FMPNewsFeed   None

`infrastructure` showed the compounding case. Its metrics import listed six
names ending in `Summary`, which does not exist — CPython binds each name in
turn and raises on that one, so `MetricsRegistry` imported fine and was then
overwritten with ``None`` by the handler, and `get_metrics_registry` was never
reached. One nonexistent name took down the package's documented entry point:

    from infrastructure import get_metrics_registry, Counter   # -> None, <class>

Nothing consumed any of these — every real caller imports from the submodule
(`from infrastructure.metrics import get_metrics_registry`), which is why this
survived. That makes it false advertising rather than a live outage, and the
fix is to export the real names instead of inventing aliases for them.

This test pins the general rule rather than the nine instances: a name a
package promises in ``__all__`` must resolve, and must not be ``None``.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit

# Packages whose __init__ re-exports submodule symbols behind try/except.
# Every one of these had at least one broken export.
_SHIM_PACKAGES = [
    "compliance",
    "data_layer.feeds.news",
    "deployment",
    "events",
    "infrastructure",
    "market_data",
    "visualization",
]


@pytest.mark.parametrize("package", _SHIM_PACKAGES)
def test_every_advertised_export_resolves(package: str):
    """A name in __all__ must exist on the package."""
    module = importlib.import_module(package)
    declared = getattr(module, "__all__", [])
    assert declared, f"{package} has no __all__ — this test would silently pass"

    missing = [name for name in declared if not hasattr(module, name)]
    assert not missing, (
        f"{package}.__all__ promises {missing}, which the package does not "
        f"define. The import in its __init__ names a symbol that does not "
        f"exist in the target module, so the except handler swallowed an "
        f"ImportError at startup."
    )


@pytest.mark.parametrize("package", _SHIM_PACKAGES)
def test_no_advertised_export_is_none(package: str):
    """A name in __all__ must not be the None left behind by a failed import."""
    module = importlib.import_module(package)
    declared = getattr(module, "__all__", [])

    nulled = [name for name in declared if getattr(module, name, object()) is None]
    assert not nulled, (
        f"{package}.__all__ promises {nulled}, which resolve to None. A caller "
        f"doing `from {package} import {nulled[0] if nulled else 'X'}` gets None "
        f"and fails later with an unrelated TypeError."
    )


def test_infrastructure_metrics_entry_point_is_callable():
    """The package docstring's own usage example must work.

    Pinned separately because this is the case where one bad name in a
    multi-name import nulled a working symbol beside it.
    """
    from infrastructure import Counter, get_metrics_registry

    assert get_metrics_registry is not None, (
        "infrastructure.get_metrics_registry is None — the metrics import block "
        "failed on a sibling name and the handler nulled the entry point"
    )
    assert callable(get_metrics_registry)
    assert isinstance(Counter, type)
