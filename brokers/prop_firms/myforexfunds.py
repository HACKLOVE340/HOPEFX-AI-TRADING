"""
MyForexFunds Connector

MyForexFunds is a prop trading firm offering forex funded accounts.
"""

from typing import Dict, Any
import logging

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

    MFF_SERVERS = [
        'MyForexFunds-Demo',
        'MyForexFunds-Live',
        'MyForexFunds-Server',
    ]

    def __init__(self, config: Dict[str, Any]):
        """Initialize MyForexFunds connector."""
        if 'server' not in config:
            config['server'] = self.MFF_SERVERS[0]
            logger.info(f"Auto-selected MyForexFunds server: {config['server']}")

        super().__init__(config)

        self.account_size = config.get('account_size', 100000)

        logger.info(f"MyForexFunds Connector initialized for ${self.account_size} account")

    def get_myforexfunds_rules(self) -> Dict[str, Any]:
        """Get MyForexFunds rules and limits."""
        rules = {
            'max_daily_loss': '5%',
            'max_total_loss': '10%',
            'profit_target': '8% for evaluation',
            'profit_split': 'up to 85%',
            'scaling': 'up to $2.56M',
            'evaluation_days': 'unlimited',
            'payouts': 'on-demand',
        }

        return rules
