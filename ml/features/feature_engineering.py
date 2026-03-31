# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/features/feature_engineering.py
====================================
Backward-compatibility re-export shim.

All implementation lives in advanced_features.py.  This module exists
so that any code importing from ml.features.feature_engineering continues
to work without modification.
"""

from ml.features.advanced_features import AdvancedFeatureEngineer  # noqa: F401

__all__ = ["AdvancedFeatureEngineer"]
