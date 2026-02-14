"""
TopstepTrader Connector

TopstepTrader is a futures prop trading firm.
Provides funded accounts for futures traders.
"""

from typing import Dict, Any
import logging

from ..mt5 import MT5Connector

logger = logging.getLogger(__name__)


class TopstepTraderConnector(MT5Connector):
    """
    TopstepTrader Proprietary Trading Firm Connector.

    TopstepTrader specializes in futures trading with funded accounts.

    Configuration:
        login: TopstepTrader account number
        password: TopstepTrader account password
        server: TopstepTrader server
        account_type: 'combine' or 'funded' (default: 'combine')

    Example:
        config = {
            'login': 12345678,
            'password': 'your_password',
            'server': 'TopstepTrader-Server01',
            'account_type': 'combine'
        }
        topstep = TopstepTraderConnector(config)
        topstep.connect()
    """

    # TopstepTrader servers
    TOPSTEP_SERVERS = [
        'TopstepTrader-Server01',
        'TopstepTrader-Server02',
        'TopstepTrader-Demo',
    ]

    def __init__(self, config: Dict[str, Any]):
        """Initialize TopstepTrader connector."""
        # Auto-select server if not provided
        if 'server' not in config:
            config['server'] = self.TOPSTEP_SERVERS[0]
            logger.info(f"Auto-selected TopstepTrader server: {config['server']}")

        super().__init__(config)

        self.account_type = config.get('account_type', 'combine')

        logger.info(f"TopstepTrader Connector initialized for {self.account_type} account")

    def get_topstep_rules(self) -> Dict[str, Any]:
        """
        Get TopstepTrader rules and limits.

        Returns:
            Dict with TopstepTrader rules
        """
        rules = {
            'max_daily_loss': '$2,000-$3,000',  # varies by account
            'max_trailing_drawdown': '$3,000-$4,000',
            'profit_target': '$3,000-$6,000',
            'min_trading_days': 5,
            'max_contracts': 'varies',
            'profit_split': '100% in combine, then 80/20',
            'scaling': 'up to $300K',
        }

        return rules
