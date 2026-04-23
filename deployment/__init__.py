# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
deployment — Helm chart generation and challenge launch automation.

Public API
----------
    HelmChartGenerator    Generates Kubernetes Helm charts for HOPEFX deployments.
    ChallengeLauncher     Automates prop firm challenge account setup and launch.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from deployment.helm_chart import HelmChartGenerator
except Exception as _exc:
    logger.debug("deployment.helm_chart unavailable: %s", _exc)

try:
    from deployment.challenge_launch import ChallengeLauncher
except Exception as _exc:
    logger.debug("deployment.challenge_launch unavailable: %s", _exc)

__all__ = ["ChallengeLauncher", "HelmChartGenerator"]
