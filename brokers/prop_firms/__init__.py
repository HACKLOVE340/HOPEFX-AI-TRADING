# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Prop Firm Connectors
Proprietary Firm Trading Integration Module
Supports: FTMO, MyForexFunds, The5ers, TopStep
Enterprise-grade prop firm account management

Connectors for proprietary trading firms:
- FTMO
- TopstepTrader
- The5ers
- MyForexFunds
- And more...

All prop firms using MT5 can use the MT5Connector with appropriate server details.
"""

try:
    from .ftmo import FTMOBroker as FTMOConnector
except ImportError:
    FTMOConnector = None  # type: ignore

try:
    from .topstep import TopstepTraderConnector
except ImportError:
    TopstepTraderConnector = None  # type: ignore

try:
    from .the5ers import The5ersConnector
except ImportError:
    The5ersConnector = None  # type: ignore

try:
    from .myforexfunds import MyForexFundsConnector
except ImportError:
    MyForexFundsConnector = None  # type: ignore

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PropFirmTier(Enum):
    """Proprietary firm account tiers"""

    STARTER = "starter"
    PROFESSIONAL = "professional"
    ELITE = "elite"
    ENTERPRISE = "enterprise"


class FirmStatus(Enum):
    """Account status in prop firms"""

    EVALUATION = "evaluation"
    FUNDED = "funded"
    TRADING = "trading"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    PROFIT_SHARING = "profit_sharing"


@dataclass
class PropFirmConfig:
    """Configuration for prop firm integration"""

    firm_id: str
    api_key: str
    secret_key: str
    account_id: str
    tier: PropFirmTier
    base_url: str
    timeout: int = 30
    max_retries: int = 3
    enable_risk_limits: bool = True
    enable_audit_trail: bool = True


__all__ = [
    "FTMOConnector",
    "FirmStatus",
    "MyForexFundsConnector",
    "PropFirmConfig",
    "PropFirmTier",
    "The5ersConnector",
    "TopstepTraderConnector",
]
