# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Feature Engineering

Feature engineering modules for ML models:
- TechnicalFeatureEngineer: Create technical indicators and derived features
"""

from .technical import TechnicalFeatureEngineer

__all__ = [
    "TechnicalFeatureEngineer",
]
