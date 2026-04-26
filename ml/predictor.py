# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/predictor.py
===============
Public alias for ml.advanced_predictor.

Callers that import ``from ml.predictor import get_predictor`` receive the
same singleton as ``from ml.advanced_predictor import get_predictor``.
This module exists so legacy import paths continue to work without
duplicating any logic.
"""

from ml.advanced_predictor import (
    AdvancedPredictor,
    HybridEnsemblePredictor,
    get_predictor,
)

__all__ = [
    "AdvancedPredictor",
    "HybridEnsemblePredictor",
    "get_predictor",
]
