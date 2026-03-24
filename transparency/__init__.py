"""
transparency — Execution Transparency Engine

Records every order execution with full audit trail: fill quality,
slippage, latency, and broker comparison. Provides public-facing
reports to demonstrate best-execution compliance.

Submodules:
    models — ExecutionQuality, ExecutionRecord, ExecutionReport
    engine — ExecutionTransparencyEngine: record, analyse, report
    router — FastAPI router (/api/transparency/*)
"""

from transparency.models import (
    ExecutionQuality,
    ExecutionRecord,
    ExecutionReport,
)
from transparency.engine import ExecutionTransparencyEngine
from transparency.router import create_transparency_router

__all__ = [
    "ExecutionTransparencyEngine",
    "ExecutionQuality",
    "ExecutionRecord",
    "ExecutionReport",
    "create_transparency_router",
]
