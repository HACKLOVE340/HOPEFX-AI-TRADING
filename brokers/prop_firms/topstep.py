"""TopstepTrader Connector — futures prop firm via MT5."""

from typing import Dict, Any
import logging
from ..mt5 import MT5Connector

logger = logging.getLogger(__name__)


class TopstepTraderConnector(MT5Connector):
    """TopstepTrader prop firm connector (MT5-based)."""

    TOPSTEP_SERVERS = [
        "TopstepTrader-Server01",
        "TopstepTrader-Server02",
        "TopstepTrader-Demo",
    ]

    def __init__(self, config: Dict[str, Any]):
        if "server" not in config:
            config = dict(config)
            config["server"] = self.TOPSTEP_SERVERS[0]
        super().__init__(config)
        self.account_type = config.get("account_type", "combine")
        logger.info(f"TopstepTrader initialized: {self.account_type} account")

    def get_topstep_rules(self) -> Dict[str, Any]:
        return {
            "max_daily_loss": "$2,000-$3,000",
            "max_trailing_drawdown": "$3,000-$4,000",
            "profit_target": "$3,000-$6,000",
            "min_trading_days": 5,
            "max_contracts": "varies",
            "profit_split": "100% in combine, then 80/20",
            "scaling": "up to $300K",
        }
