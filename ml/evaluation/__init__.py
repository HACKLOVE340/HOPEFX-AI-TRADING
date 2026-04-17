# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/evaluation — Model evaluation artifacts and loader utilities.

This directory stores JSON evaluation reports, CSV prediction files, and
feature-importance PNGs produced by the ML training pipeline.

Public API
----------
    load_latest_evaluation(model_name)
        Load the most recent evaluation JSON for a given model name.
        Returns a dict with keys: model_name, timestamp, metrics, predictions_sample.
        Returns None if no evaluation file exists.

    list_evaluations(model_name)
        Return a sorted list of (timestamp_str, path) tuples for all
        evaluation JSON files matching *model_name*.

    EvaluationReport
        Dataclass wrapping a loaded evaluation JSON.

Usage
-----
    from ml.evaluation import load_latest_evaluation, EvaluationReport

    report = load_latest_evaluation("XGBoost")
    if report:
        print(report.metrics["accuracy"])
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EVAL_DIR = Path(__file__).parent
UTC = timezone.utc


@dataclass
class EvaluationReport:
    """Parsed model evaluation report."""

    model_name: str
    timestamp: str
    metrics: dict[str, Any] = field(default_factory=dict)
    predictions_sample: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""

    @property
    def accuracy(self) -> float:
        return float(self.metrics.get("accuracy", 0.0))

    @property
    def f1(self) -> float:
        return float(self.metrics.get("f1", 0.0))

    @property
    def precision(self) -> float:
        return float(self.metrics.get("precision", 0.0))

    @property
    def recall(self) -> float:
        return float(self.metrics.get("recall", 0.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "timestamp": self.timestamp,
            "metrics": self.metrics,
            "predictions_sample": self.predictions_sample,
            "source_file": self.source_file,
        }


def list_evaluations(model_name: str) -> list[tuple[str, Path]]:
    """
    Return all evaluation JSON files for *model_name*, sorted by timestamp ascending.

    Each entry is (timestamp_str, path) where timestamp_str is the
    YYYYMMDD_HHMMSS suffix extracted from the filename.
    """
    pattern = f"{model_name}_evaluation_*.json"
    results: list[tuple[str, Path]] = []
    for p in _EVAL_DIR.glob(pattern):
        # Filename: ModelName_evaluation_YYYYMMDD_HHMMSS.json
        parts = p.stem.split("_evaluation_")
        ts = parts[1] if len(parts) == 2 else "00000000_000000"
        results.append((ts, p))
    results.sort(key=lambda x: x[0])
    return results


def load_latest_evaluation(model_name: str) -> EvaluationReport | None:
    """
    Load the most recent evaluation JSON for *model_name*.

    Returns None if no evaluation file exists for the model.
    """
    evals = list_evaluations(model_name)
    if not evals:
        logger.debug("ml.evaluation: no evaluation files found for %s", model_name)
        return None

    ts, path = evals[-1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return EvaluationReport(
            model_name=data.get("model_name", model_name),
            timestamp=data.get("timestamp", ts),
            metrics=data.get("metrics", {}),
            predictions_sample=data.get("predictions_sample", {}),
            source_file=str(path),
        )
    except Exception as exc:
        logger.warning("ml.evaluation: failed to load %s: %s", path, exc)
        return None


def load_all_evaluations(model_name: str) -> list[EvaluationReport]:
    """Load all evaluation reports for *model_name*, oldest first."""
    reports = []
    for ts, path in list_evaluations(model_name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            reports.append(
                EvaluationReport(
                    model_name=data.get("model_name", model_name),
                    timestamp=data.get("timestamp", ts),
                    metrics=data.get("metrics", {}),
                    predictions_sample=data.get("predictions_sample", {}),
                    source_file=str(path),
                )
            )
        except Exception as exc:
            logger.warning("ml.evaluation: failed to load %s: %s", path, exc)
    return reports


__all__ = [
    "EvaluationReport",
    "list_evaluations",
    "load_all_evaluations",
    "load_latest_evaluation",
]
