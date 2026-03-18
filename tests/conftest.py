"""Pytest configuration."""
import asyncio
import pytest
import pytest_asyncio
from hypothesis import settings

# Register asyncio mode
pytest_plugins = ("pytest_asyncio",)

@settings(max_examples=20, deadline=None)
def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow")

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture
async def mock_broker():
    """Mock broker fixture."""
    from src.execution.brokers.paper import PaperBroker
    return PaperBroker()

@pytest_asyncio.fixture
async def clean_event_bus():
    """Clean event bus for tests."""
    from src.core.bus import EventBus
    bus = EventBus()
    yield bus
    await bus.stop()
