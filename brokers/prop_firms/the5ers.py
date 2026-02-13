"""
The5ers Connector

The5ers is a prop trading firm offering funded forex accounts.
"""

from typing import Dict, Any
import logging

from ..mt5 import MT5Connector

logger = logging.getLogger(__name__)


class The5ersConnector(MT5Connector):
    """
    The5ers Proprietary Trading Firm Connector.

    The5ers provides forex funded accounts with various programs.

    Configuration:
        login: The5ers account number
        password: The5ers account password
        server: The5ers server
        program: 'boot_camp', 'high_stakes', or 'instant_funding'

    Example:
        config = {
            'login': 12345678,
            'password': 'your_password',
            'server': 'The5ers-Demo',
            'program': 'high_stakes'
        }
        the5ers = The5ersConnector(config)
        the5ers.connect()
    """

    THE5ERS_SERVERS = [
        'The5ers-Demo',
        'The5ers-Live',
        'The5ers-Server',
    ]

    def __init__(self, config: Dict[str, Any]):
        """Initialize The5ers connector."""
        if 'server' not in config:
            config['server'] = self.THE5ERS_SERVERS[0]
            logger.info(f"Auto-selected The5ers server: {config['server']}")

        super().__init__(config)

        self.program = config.get('program', 'high_stakes')

        logger.info(f"The5ers Connector initialized for {self.program} program")

    def get_the5ers_rules(self) -> Dict[str, Any]:
        """Get The5ers rules and limits."""
        rules = {
            'max_daily_loss': '4-5%',
            'max_total_loss': '10%',
            'profit_target': 'varies by program',
            'profit_split': 'up to 100%',
            'scaling': 'unlimited',
            'programs': {
                'boot_camp': 'Entry level, lower targets',
                'high_stakes': 'Standard program',
                'instant_funding': 'Immediate funded account',
            }
        }

        return rules
