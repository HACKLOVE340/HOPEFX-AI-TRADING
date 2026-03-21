"""Versioned model registry with signature checks."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
import structlog

try:
    from configs.settings import get_settings
except ImportError:
    from src.core.config import get_settings

logger = structlog.get_logger()


class ModelRegistry:
    """Model versioning and artifact management."""
    
    def __init__(self) -> None:
        self.base_path = get_settings().ml.model_path
        self.manifest_path = self.base_path / "manifest.json"
        self._manifest: dict[str, Any] = {}
    
    async def _load_manifest(self) -> None:
        """Load manifest."""
        if self.manifest_path.exists():
            async with aiofiles.open(self.manifest_path, "r") as f:
                content = await f.read()
                self._manifest = json.loads(content)
    
    async def _save_manifest(self) -> None:
        """Save manifest."""
        async with aiofiles.open(self.manifest_path, "w") as f:
            await f.write(json.dumps(self._manifest, indent=2))
    
    def _compute_signature(self, file_path: Path) -> str:
        """Compute SHA256 signature."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()[:16]
    
    async def register(
        self,
        xgb_model: Any,
        rf_model: Any,
        scaler: Any,
        feature_names: list[str],
    ) -> str:
        """Register new model version."""
        await self._load_manifest()
        
        # Generate version
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        version = f"v{len(self._manifest.get('models', [])) + 1}.{timestamp}"
        version_path = self.base_path / version
        version_path.mkdir(exist_ok=True)
        
        # Save artifacts
        paths = {}
        
        # XGBoost
        xgb_path = version_path / "xgb.json"
        xgb_model.save_model(str(xgb_path))
        paths["xgb"] = str(xgb_path)
        
        # Random Forest
        import pickle
        rf_path = version_path / "rf.pkl"
        with open(rf_path, "wb") as f:
            pickle.dump(rf_model, f)
        paths["rf"] = str(rf_path)
        
        # Scaler
        scaler_path = version_path / "scaler.pkl"
        with open(scaler_path, "wb") as f:
            pickle.dump(scaler, f)
        paths["scaler"] = str(scaler_path)
        
        # Metadata
        metadata = {
            "feature_names": feature_names,
            "created_at": datetime.utcnow().isoformat(),
            "signatures": {
                k: self._compute_signature(Path(v)) 
                for k, v in paths.items()
            }
        }
        
        meta_path = version_path / "metadata.json"
        async with aiofiles.open(meta_path, "w") as f:
            await f.write(json.dumps(metadata, indent=2))
        paths["metadata"] = str(meta_path)
        
        # Update manifest
        if "models" not in self._manifest:
            self._manifest["models"] = []
        
        self._manifest["models"].append({
            "version": version,
            "paths": paths,
            "metadata": metadata,
            "active": True,
        })
        
        # Deactivate old versions
        for model in self._manifest["models"][:-1]:
            model["active"] = False
        
        await self._save_manifest()
        logger.info(f"Registered model version {version}")
        
        return version
    
    async def get_latest(self, model_name: str) -> dict[str, Any] | None:
        """Get latest active model."""
        await self._load_manifest()
        
        for model in reversed(self._manifest.get("models", [])):
            if model.get("active"):
                # Verify signatures
                for key, path in model["paths"].items():
                    if key == "metadata":
                        continue
                    current_sig = self._compute_signature(Path(path))
                    stored_sig = model["metadata"]["signatures"].get(key)
                    if current_sig != stored_sig:
                        logger.error(f"Signature mismatch for {key}")
                        return None
                return model
        
        return None
    
    async def list_versions(self) -> list[dict[str, Any]]:
        """List all versions."""
        await self._load_manifest()
        return self._manifest.get("models", [])
    
    async def rollback(self, version: str) -> bool:
        """Rollback to specific version."""
        await self._load_manifest()
        
        for model in self._manifest.get("models", []):
            model["active"] = (model["version"] == version)
        
        await self._save_manifest()
        logger.info(f"Rolled back to version {version}")
        return True
