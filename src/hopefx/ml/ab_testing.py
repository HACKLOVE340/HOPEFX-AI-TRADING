"""
A/B testing framework for ML model performance comparison.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class Variant:
    """A/B test variant."""
    name: str
    model_version: str
    traffic_percentage: float  # 0.0 to 1.0
    metrics: Dict[str, float]


class ABTestManager:
    """
    Route traffic between model variants for performance testing.
    """
    
    def __init__(self):
        self._variants: Dict[str, Variant] = {}
        self._active_test: Optional[str] = None
    
    def create_test(
        self,
        test_name: str,
        variants: List[Variant]
    ) -> None:
        """Create new A/B test."""
        # Validate percentages sum to 1.0
        total = sum(v.traffic_percentage for v in variants)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Variant percentages must sum to 1.0, got {total}")
        
        self._variants[test_name] = {v.name: v for v in variants}
        self._active_test = test_name
        
        logger.info(
            "ab_test_created",
            test_name=test_name,
            variants=[v.name for v in variants]
        )
    
    def get_variant_for_user(self, user_id: str) -> str:
        """
        Deterministic variant assignment based on user ID.
        """
        if not self._active_test:
            return "control"
        
        # Hash user ID for deterministic assignment
        hash_val = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        
        # Select variant based on traffic percentage
        bucket = (hash_val % 1000) / 1000.0
        
        cumulative = 0.0
        for name, variant in self._variants[self._active_test].items():
            cumulative += variant.traffic_percentage
            if bucket <= cumulative:
                return name
        
        return "control"
    
    def record_outcome(
        self,
        test_name: str,
        variant_name: str,
        metric_name: str,
        value: float
    ) -> None:
        """Record outcome for statistical analysis."""
        if test_name not in self._variants:
            return
        
        variant = self._variants[test_name].get(variant_name)
        if not variant:
            return
        
        # Update running statistics
        if metric_name not in variant.metrics:
            variant.metrics[metric_name] = 0.0
        
        # Simple running average (use proper statistical methods in production)
        n = variant.metrics.get(f"{metric_name}_count", 0) + 1
        old_avg = variant.metrics[metric_name]
        variant.metrics[metric_name] = (old_avg * (n - 1) + value) / n
        variant.metrics[f"{metric_name}_count"] = n
        
        logger.info(
            "ab_test_outcome_recorded",
            test_name=test_name,
            variant=variant_name,
            metric=metric_name,
            value=value
        )
    
    def get_test_results(self, test_name: str) -> Dict:
        """Get statistical results for test."""
        if test_name not in self._variants:
            return {}
        
        return {
            name: {
                "traffic_percentage": v.traffic_percentage,
                "metrics": {k: v for k, v in v.metrics.items() if not k.endswith("_count")}
            }
            for name, v in self._variants[test_name].items()
        }
