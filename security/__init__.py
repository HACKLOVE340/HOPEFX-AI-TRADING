# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
security
========
Top-level package for HOPEFX security sub-systems.

Re-exports the most commonly used helpers so callers can do::

    from security import get_security_monitor, get_lockdown_manager
    from security.antivirus import get_av_engine
"""

import logging

logger = logging.getLogger(__name__)

try:
    from security.monitor import get_security_monitor  # noqa: F401
except Exception as _exc:
    logger.debug("security.monitor unavailable: %s", _exc)

try:
    from security.lockdown import get_lockdown_manager  # noqa: F401
except Exception as _exc:
    logger.debug("security.lockdown unavailable: %s", _exc)

try:
    from security.antivirus import get_av_engine  # noqa: F401
except Exception as _exc:
    logger.debug("security.antivirus unavailable: %s", _exc)
