"""
FTMO Connector

FTMO is a prop trading firm that uses MT5 platform.
This connector is a specialized wrapper around MT5Connector for FTMO accounts.

FTMO Server Information:
- Demo: FTMO-Demo, FTMO-Demo2, FTMO-Demo3
- Live: FTMO-Server, FTMO-Server2, FTMO-Server3
"""

from typing import Dict, Any
import logging

from ..mt5 import MT5Connector

logger = logging.getLogger(__name__)


class FTMOConnector(MT5Connector):
    """
    FTMO Proprietary Trading Firm Connector.

    FTMO provides funded trading accounts after passing challenges.
    Uses MT5 platform with FTMO-specific servers.

    Configuration:
        login: FTMO account number
        password: FTMO account password
        server: FTMO server (auto-detected if not provided)
        challenge_type: 'demo' or 'live' (default: 'demo')

    Example:
        config = {
            'login': 12345678,
            'password': 'your_ftmo_password',
            'challenge_type': 'demo'  # or 'live'
        }
        ftmo = FTMOConnector(config)
        ftmo.connect()
    """

    # FTMO server list
    FTMO_SERVERS = {
        'demo': ['FTMO-Demo', 'FTMO-Demo2', 'FTMO-Demo3'],
        'live': ['FTMO-Server', 'FTMO-Server2', 'FTMO-Server3'],
    }

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize FTMO connector.

        Args:
            config: Configuration dict with login, password, challenge_type
        """
        # Auto-select server if not provided
        if 'server' not in config:
            challenge_type = config.get('challenge_type', 'demo').lower()
            config['server'] = self.FTMO_SERVERS[challenge_type][0]
            logger.info(f"Auto-selected FTMO server: {config['server']}")

        # Add FTMO-specific defaults
        config.setdefault('timeout', 60000)

        # Initialize MT5 connector
        super().__init__(config)

        self.challenge_type = config.get('challenge_type', 'demo')

        logger.info(f"FTMO Connector initialized for {self.challenge_type} account")

    def get_ftmo_rules(self) -> Dict[str, Any]:
        """
        Get FTMO trading rules and limits.

        Returns:
            Dict with FTMO rules
        """
        # FTMO standard rules (may vary by account size)
        rules = {
            'max_daily_loss': '5%',  # of initial balance
            'max_total_loss': '10%',  # of initial balance
            'profit_target': '10%',  # for challenge
            'min_trading_days': 4,
            'max_lot_size': 'varies',  # depends on account size
            'profit_split': '80%',  # trader gets 80% of profits
            'scaling': 'up to $2M',
            'trading_period': 'unlimited',
        }

        return rules

    def check_ftmo_compliance(self) -> Dict[str, Any]:
        """
        Check if trading complies with FTMO rules.

        Returns:
            Dict with compliance status
        """
        account = self.get_account_info()
        if not account:
            return {'compliant': False, 'error': 'Cannot get account info'}

        # Calculate metrics
        initial_balance = 100000  # This should be retrieved from account history
        current_equity = account.equity

        daily_loss_pct = 0  # Would need to calculate from today's trades
        total_loss_pct = ((initial_balance - current_equity) / initial_balance) * 100

        compliance = {
            'compliant': total_loss_pct < 10,
            'total_loss_percent': total_loss_pct,
            'max_loss_allowed': 10,
            'daily_loss_percent': daily_loss_pct,
            'max_daily_loss_allowed': 5,
            'equity': current_equity,
            'balance': account.balance,
        }

        return compliance
