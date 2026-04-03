# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""ml.training package — re-exports from ml/training.py at parent level"""

import importlib.util as _ilu
import os as _os

_parent = _os.path.dirname(_Path(__file__).parent)
_spec = _ilu.spec_from_file_location(
    "_ml_training_module",
    _Path(_parent) / "training.py",
)
if _spec and _spec.loader:
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    train_ml_pipeline = getattr(_mod, "train_ml_pipeline", None)
    ModelTrainer = getattr(_mod, "ModelTrainer", None)
    TrainingConfig = getattr(_mod, "TrainingConfig", None)
    FeatureEngineer = getattr(_mod, "FeatureEngineer", None)
    XGBoostModel = getattr(_mod, "XGBoostModel", None)
    RandomForestModel = getattr(_mod, "RandomForestModel", None)
    LSTMModel = getattr(_mod, "LSTMModel", None)
else:

    def train_ml_pipeline(*a, **kw):
        raise ImportError("ml.training.train_ml_pipeline not available")
