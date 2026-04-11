# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""ml.training package — re-exports from ml/training.py at parent level"""

import importlib.util as _ilu
from pathlib import Path as _Path

_parent = str(_Path(__file__).parent.parent)
_spec = _ilu.spec_from_file_location(
    "_ml_training_module",
    _Path(_parent) / "training.py",
)
if _spec and _spec.loader:
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    train_ml_pipeline = getattr(_mod, "train_ml_pipeline", None)
    walk_forward_validate = getattr(_mod, "walk_forward_validate", None)
    ModelTrainer = getattr(_mod, "ModelTrainer", None)
    TrainingConfig = getattr(_mod, "TrainingConfig", None)
    FeatureEngineer = getattr(_mod, "FeatureEngineer", None)
    XGBoostModel = getattr(_mod, "XGBoostModel", None)
    RandomForestModel = getattr(_mod, "RandomForestModel", None)
    LSTMModel = getattr(_mod, "LSTMModel", None)
    HyperparameterTuner = getattr(_mod, "HyperparameterTuner", None)
    MLEvaluationReport = getattr(_mod, "MLEvaluationReport", None)
    EnsembleModel = getattr(_mod, "EnsembleModel", None)
else:

    def train_ml_pipeline(*a, **kw):
        raise ImportError("ml.training.train_ml_pipeline not available")

    def walk_forward_validate(*a, **kw):
        raise ImportError("ml.training.walk_forward_validate not available")

    class ModelTrainer:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise ImportError("ml.training.ModelTrainer not available")

    class TrainingConfig:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise ImportError("ml.training.TrainingConfig not available")


__all__ = [
    "EnsembleModel",
    "FeatureEngineer",
    "HyperparameterTuner",
    "LSTMModel",
    "MLEvaluationReport",
    "ModelTrainer",
    "RandomForestModel",
    "TrainingConfig",
    "XGBoostModel",
    "train_ml_pipeline",
    "walk_forward_validate",
]
