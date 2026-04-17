# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
features — Feature flag registry.

The canonical feature-flag registry lives in config/feature_flags.py.
This package re-exports the singleton so callers can use either path.

Usage
-----
    from features.flags import flags
    from features import flags   # equivalent
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from features.flags import FeatureFlags, FeatureStatus, flags  # noqa: F401
except Exception as _exc:
    logger.debug("features.flags unavailable: %s", _exc)

__all__ = ["FeatureFlags", "FeatureStatus", "flags"]
