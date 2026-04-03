# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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

from transparency.engine import (
    FOREX_PIP_MULTIPLIER,
    METAL_PIP_MULTIPLIER,
    ExecutionTransparencyEngine,
)
from transparency.models import (
    ExecutionQuality,
    ExecutionRecord,
    ExecutionReport,
)
from transparency.router import create_transparency_router

__all__ = [
    "FOREX_PIP_MULTIPLIER",
    "METAL_PIP_MULTIPLIER",
    "ExecutionQuality",
    "ExecutionRecord",
    "ExecutionReport",
    "ExecutionTransparencyEngine",
    "create_transparency_router",
]
