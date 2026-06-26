"""e2e conftest — shared fixtures and event loop configuration."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test under tests/e2e/ with the ``e2e`` marker so CI's
    ``-m "not e2e"`` reliably excludes them — these need live broker/network and
    must not run (or fail) in the fast suite. Avoids per-file pytestmark drift."""
    for item in items:
        if "/tests/e2e/" in item.nodeid.replace("\\", "/") or item.nodeid.startswith("tests/e2e/"):
            item.add_marker(pytest.mark.e2e)
