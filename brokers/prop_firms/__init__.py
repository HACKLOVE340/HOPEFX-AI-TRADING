"""
Prop Firm Connectors

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

__all__ = [
    'FTMOConnector',
    'TopstepTraderConnector',
    'The5ersConnector',
    'MyForexFundsConnector',
]
