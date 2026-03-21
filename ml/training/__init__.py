"""ml.training package — re-exports from ml/training.py at parent level"""
import importlib.util as _ilu
import os as _os

_parent = _os.path.dirname(_os.path.dirname(__file__))
_spec = _ilu.spec_from_file_location("_ml_training_module",
                                      _os.path.join(_parent, "training.py"))
if _spec and _spec.loader:
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    train_ml_pipeline = getattr(_mod, "train_ml_pipeline", None)
    ModelTrainer = getattr(_mod, "ModelTrainer", None)
    TrainingConfig = getattr(_mod, "TrainingConfig", None)
else:
    def train_ml_pipeline(*a, **kw):
        raise ImportError("ml.training.train_ml_pipeline not available")
