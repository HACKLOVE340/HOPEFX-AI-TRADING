# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_health_result_cache.py
======================================
`api/settings_new_endpoints.get_performance_metrics` reported no component
latencies, because it read a cache that was never written.

    from health_check_service import _last_health_result   # never existed

`health_check_service` computes health on demand — `_run_all_checks()` gathers
the seven component checks, `detailed_health()` returns them, and the result was
thrown away. So the import raised `ImportError` on every call, the surrounding
`except Exception` swallowed it, and the endpoint's `components` block was
always absent. The admin performance page has therefore never shown a component
latency.

`get_performance_metrics` is a **sync** route, so it cannot await the checks
itself; a cache is the right shape rather than making the route async and
paying for seven live probes on every page load.

`_run_all_checks()` now stores its result, so every path that checks health —
`/health/detailed` and the readiness probe alike — refreshes it. The cached
entries carry `name` and `critical`, which are not fields on `ComponentStatus`:
the consumer reads exactly that shape, so the cache matches the reader rather
than the model.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts from the un-run state."""
    import health_check_service as h

    original = h._last_health_result
    h._last_health_result = None
    yield
    h._last_health_result = original


def test_the_cache_name_exists():
    """The import the consumer makes must resolve."""
    from health_check_service import _last_health_result  # noqa: F401


def test_cache_is_none_before_any_check_runs():
    import health_check_service as h

    assert h._last_health_result is None


def test_running_the_checks_populates_the_cache():
    import health_check_service as h

    asyncio.run(h._run_all_checks())

    assert h._last_health_result is not None, "_run_all_checks did not record its result"
    assert h._last_health_result["components"], "cache recorded no components"


def test_cached_entries_match_the_shape_the_consumer_reads():
    """api/settings_new_endpoints reads name/status/latency_ms/critical."""
    import health_check_service as h

    asyncio.run(h._run_all_checks())

    for entry in h._last_health_result["components"]:
        assert set(entry) == {"name", "status", "latency_ms", "critical"}, (
            f"cache entry {entry} does not match what get_performance_metrics reads"
        )
        assert isinstance(entry["name"], str)
        assert isinstance(entry["latency_ms"], (int, float))
        assert isinstance(entry["critical"], bool)


def test_critical_components_are_flagged_from_the_real_constant():
    """`critical` must track _CRITICAL_CHECKS, not a hand-copied list."""
    import health_check_service as h

    asyncio.run(h._run_all_checks())

    flagged = {e["name"] for e in h._last_health_result["components"] if e["critical"]}
    assert flagged == h._CRITICAL_CHECKS


def test_every_checked_component_is_cached():
    import health_check_service as h

    components = asyncio.run(h._run_all_checks())

    cached = {e["name"] for e in h._last_health_result["components"]}
    assert cached == set(components)


def test_performance_endpoint_no_longer_suppresses_the_import():
    """Regression: the consumer should read a name that exists.

    The `# type: ignore[attr-defined]` marked an import known to be broken.
    Its removal is the signal that the name is real now.
    """
    import inspect

    from api import settings_new_endpoints

    source = inspect.getsource(settings_new_endpoints.get_performance_metrics)
    assert "from health_check_service import _last_health_result" in source
    assert "type: ignore[attr-defined]" not in source
