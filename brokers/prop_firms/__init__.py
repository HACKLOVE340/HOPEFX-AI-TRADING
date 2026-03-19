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

from .ftmo import FTMOConnector
from .topstep import TopstepTraderConnector
from .the5ers import The5ersConnector
from .myforexfunds import MyForexFundsConnector

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime, timedelta

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
    'FTMOConnector',
    'TopstepTraderConnector',
    'The5ersConnector',
    'MyForexFundsConnector',
    PropFirmTier',
    'FirmStatus',
    'PropFirmConfig',
]
