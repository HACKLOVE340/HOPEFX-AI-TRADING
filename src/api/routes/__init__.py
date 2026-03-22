"""
API route handlers.
"""

from src.api.routes.health import router as health_router
from src.api.routes.trading import router as trading_router
from src.api.routes.backtest import router as backtest_router

__all__ = ["health_router", "trading_router", "backtest_router"]
