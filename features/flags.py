# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
features/flags.py — thin compatibility shim.

The canonical feature-flag registry lives in ``config.feature_flags``.
This module re-exports the singleton ``flags`` object and the
``FeatureFlags`` / ``FeatureStatus`` classes so that any legacy import
path (``from features.flags import flags``) continues to work without
change.

Do not add new flag definitions here.  Add them to
``config/feature_flags.py`` instead.
"""

from config.feature_flags import FeatureFlags, FeatureStatus, flags  # noqa: F401

__all__ = ["FeatureFlags", "FeatureStatus", "flags"]
