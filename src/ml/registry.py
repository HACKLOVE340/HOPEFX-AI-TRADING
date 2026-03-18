"""
MLflow-based model registry with versioning.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

from src.core.config import settings
from src.core.logging_config import get_logger
from src.ml.models.base import BaseModel

logger = get_logger(__name__)


class ModelRegistry:
    """
    Production model registry with A/B testing support.
    """
    
    def __init__(self, tracking_uri: str | None = None):
        self.tracking_uri = tracking_uri or settings.ml.model_registry_uri
        mlflow.set_tracking_uri(self.tracking_uri)
        self.client = MlflowClient()
        self._experiment_name = "hopefx_trading_models"
    
    def register_model(
        self,
        model: BaseModel,
        metrics: dict[str, float],
        params: dict[str, Any],
        artifacts: dict[str, Path] | None = None,
        tags: dict[str, str] | None = None
    ) -> str:
        """
        Register new model version with full lineage.
        """
        # Set experiment
        mlflow.set_experiment(self._experiment_name)
        
        with mlflow.start_run():
            # Log parameters
            mlflow.log_params({
                "model_name": model.name,
                "model_version": model.version,
                **params
            })
            
            # Log metrics
            mlflow.log_metrics(metrics)
            
            # Log model
            model_path = Path(f"/tmp/{model.name}_{model.version}")
            model.save(model_path)
            mlflow.log_artifact(str(model_path))
            
            # Log additional artifacts
            if artifacts:
                for name, path in artifacts.items():
                    mlflow.log_artifact(str(path), artifact_path=name)
            
            # Set tags
            if tags:
                mlflow.set_tags(tags)
            
            # Register model
            model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"
            mv = mlflow.register_model(model_uri, model.name)
            
            logger.info(f"Registered {model.name} v{mv.version}")
            
            return mv.version
    
    def load_model(self, name: str, version: str | None = None, stage: str | None = None) -> BaseModel:
        """
        Load model by version or stage (Staging/Production).
        """
        if stage:
            model_uri = f"models:/{name}/{stage}"
        elif version:
            model_uri = f"models:/{name}/{version}"
        else:
            model_uri = f"models:/{name}/latest"
        
        # Download artifacts
        local_path = mlflow.artifacts.download_artifacts(model_uri)
        
        # Load based on model type
        from src.ml.models.xgboost_model import XGBoostModel
        from src.ml.models.lstm_model import LSTMModel
        
        # Determine model type from metadata
        meta_path = Path(local_path) / "model.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            
            if meta.get("model_type") == "xgboost":
                model = XGBoostModel()
            elif meta.get("model_type") == "lstm":
                model = LSTMModel()
            else:
                raise ValueError(f"Unknown model type: {meta.get('model_type')}")
            
            model.load(Path(local_path))
            return model
        
        raise FileNotFoundError(f"Model metadata not found at {meta_path}")
    
    def transition_stage(self, name: str, version: str, stage: str) -> None:
        """Move model to new stage."""
        self.client.transition_model_version_stage(
            name=name,
            version=version,
            stage=stage
        )
        logger.info(f"Transitioned {name} v{version} to {stage}")
    
    def get_production_model(self, name: str) -> BaseModel:
        """Get current production model."""
        return self.load_model(name, stage="Production")
    
    def compare_versions(
        self,
        name: str,
        version_a: str,
        version_b: str
    ) -> dict[str, Any]:
        """Compare two model versions."""
        run_a = self.client.get_model_version_download_uri(name, version_a)
        run_b = self.client.get_model_version_download_uri(name, version_b)
        
        # Load metrics
        metrics_a = self.client.get_run(run_a.split("/")[-3]).data.metrics
        metrics_b = self.client.get_run(run_b.split("/")[-3]).data.metrics
        
        return {
            "version_a": {"version": version_a, "metrics": metrics_a},
            "version_b": {"version": version_b, "metrics": metrics_b},
            "improvement": {
                k: metrics_b.get(k, 0) - metrics_a.get(k, 0)
                for k in set(metrics_a) & set(metrics_b)
            }
        }
