# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Pattern Recognition Module

Includes chart patterns, candlestick patterns, and support/resistance detection.
"""

from analysis.patterns.candlestick import CandlestickPattern, CandlestickPatternDetector
from analysis.patterns.chart_patterns import ChartPattern, ChartPatternDetector
from analysis.patterns.support_resistance import PriceLevel, SupportResistanceDetector

__all__ = [
    "CandlestickPattern",
    "CandlestickPatternDetector",
    "ChartPattern",
    "ChartPatternDetector",
    "PriceLevel",
    "SupportResistanceDetector",
]
