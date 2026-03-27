# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
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

from transparency.models import (
    ExecutionQuality,
    ExecutionRecord,
    ExecutionReport,
)
from transparency.engine import (
    ExecutionTransparencyEngine,
    FOREX_PIP_MULTIPLIER,
    METAL_PIP_MULTIPLIER,
)
from transparency.router import create_transparency_router

__all__ = [
    "ExecutionTransparencyEngine",
    "ExecutionQuality",
    "ExecutionRecord",
    "ExecutionReport",
    "create_transparency_router",
    "FOREX_PIP_MULTIPLIER",
    "METAL_PIP_MULTIPLIER",
]
