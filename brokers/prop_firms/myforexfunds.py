# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
MyForexFunds Connector

MyForexFunds is a prop trading firm offering forex funded accounts.
"""

import logging
from typing import Any, ClassVar

from ..mt5 import MT5Connector

logger = logging.getLogger(__name__)


class MyForexFundsConnector(MT5Connector):
    """
    MyForexFunds Proprietary Trading Firm Connector.

    MyForexFunds provides forex funded accounts with rapid evaluation.

    Configuration:
        login: MyForexFunds account number
        password: MyForexFunds account password
        server: MyForexFunds server
        account_size: Account size in dollars

    Example:
        config = {
            'login': 12345678,
            'password': 'your_password',
            'server': 'MyForexFunds-Demo',
            'account_size': 100000
        }
        mff = MyForexFundsConnector(config)
        mff.connect()
    """

    MFF_SERVERS: ClassVar[list] = [
        "MyForexFunds-Demo",
        "MyForexFunds-Live",
        "MyForexFunds-Server",
    ]

    def __init__(self, config: dict[str, Any]):
        """Initialize MyForexFunds connector."""
        if "server" not in config:
            config["server"] = self.MFF_SERVERS[0]
            logger.info("Auto-selected MyForexFunds server: %s", config['server'])


        super().__init__(config)

        self.account_size = config.get("account_size", 100000)

        logger.info("MyForexFunds Connector initialized for $%s account", self.account_size)

    def get_myforexfunds_rules(self) -> dict[str, Any]:
        """Get MyForexFunds rules and limits."""
        rules = {
            "max_daily_loss": "5%",
            "max_total_loss": "10%",
            "profit_target": "8% for evaluation",
            "profit_split": "up to 85%",
            "scaling": "up to $2.56M",
            "evaluation_days": "unlimited",
            "payouts": "on-demand",
        }

        return rules
