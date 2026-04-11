# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""portfolio package — portfolio management and optimisation."""

import logging as _log

try:
    from portfolio.manager import Portfolio, PortfolioManager  # noqa: F401
except Exception as _e:
    _log.getLogger(__name__).debug("Portfolio/PortfolioManager unavailable: %s", _e)

try:
    from portfolio.rebalancer import DynamicRebalancer  # noqa: F401
except Exception as _e:
    _log.getLogger(__name__).debug("DynamicRebalancer unavailable: %s", _e)

try:
    from portfolio.pms import PortfolioManager as PMS, PortfolioOptimizer  # noqa: F401
except Exception as _e:
    _log.getLogger(__name__).debug("PMS unavailable: %s", _e)
