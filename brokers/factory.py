"""
Broker Factory

Factory pattern for creating broker connectors.
"""

from typing import Dict, Any, Optional
import logging

from .base import BrokerConnector
from .paper_trading import PaperTradingBroker
from .oanda import OANDAConnector
from .binance import BinanceConnector
from .alpaca import AlpacaConnector
from .mt5 import MT5Connector
from .interactive_brokers import InteractiveBrokersConnector

# Import prop firms
from .prop_firms.ftmo import FTMOConnector
from .prop_firms.topstep import TopstepTraderConnector
from .prop_firms.the5ers import The5ersConnector
from .prop_firms.myforexfunds import MyForexFundsConnector

logger = logging.getLogger(__name__)


class BrokerFactory:
    """
    Factory for creating broker connector instances.
    
    Supports:
        - paper: Paper trading simulator
        - oanda: OANDA forex trading
        - binance: Binance cryptocurrency trading
        - alpaca: Alpaca US stock trading
        - mt5: MetaTrader 5 (any broker/prop firm)
        - ib: Interactive Brokers (all asset types)
        - ftmo: FTMO prop firm
        - topstep: TopstepTrader prop firm
        - the5ers: The5ers prop firm
        - myforexfunds: MyForexFunds prop firm
    """
    
    _brokers = {
        'paper': PaperTradingBroker,
        'oanda': OANDAConnector,
        'binance': BinanceConnector,
        'alpaca': AlpacaConnector,
        'mt5': MT5Connector,
        'ib': InteractiveBrokersConnector,
        'interactive_brokers': InteractiveBrokersConnector,
        # Prop firms
        'ftmo': FTMOConnector,
        'topstep': TopstepTraderConnector,
        'topsteptrader': TopstepTraderConnector,
        'the5ers': The5ersConnector,
        'myforexfunds': MyForexFundsConnector,
        'mff': MyForexFundsConnector,
    }
    
    @classmethod
    def create_broker(
        cls,
        broker_type: str,
        config: Dict[str, Any]
    ) -> Optional[BrokerConnector]:
        """
        Create a broker connector instance.
        
        Args:
            broker_type: Type of broker ('paper', 'oanda', 'binance', 'alpaca')
            config: Broker configuration dictionary
        
        Returns:
            BrokerConnector instance or None if invalid type
        
        Examples:
            # OANDA
            >>> config = {'api_key': 'key', 'account_id': 'id', 'environment': 'practice'}
            >>> broker = BrokerFactory.create_broker('oanda', config)
            
            # MT5 (any broker)
            >>> config = {'server': 'ICMarkets-Demo', 'login': 12345, 'password': 'pass'}
            >>> broker = BrokerFactory.create_broker('mt5', config)
            
            # FTMO prop firm
            >>> config = {'login': 12345, 'password': 'pass', 'challenge_type': 'demo'}
            >>> broker = BrokerFactory.create_broker('ftmo', config)
            
            # Interactive Brokers
            >>> config = {'host': '127.0.0.1', 'port': 7497, 'paper': True}
            >>> broker = BrokerFactory.create_broker('ib', config)
        """
        broker_type = broker_type.lower()
        
        if broker_type not in cls._brokers:
            logger.error(f"Unknown broker type: {broker_type}")
            logger.info(f"Available brokers: {list(cls._brokers.keys())}")
            return None
        
        try:
            broker_class = cls._brokers[broker_type]
            broker = broker_class(config)
            logger.info(f"Created broker: {broker_type}")
            return broker
        except Exception as e:
            logger.error(f"Failed to create broker {broker_type}: {e}")
            return None
    
    @classmethod
    def register_broker(cls, name: str, broker_class: type):
        """
        Register a custom broker connector.
        
        Args:
            name: Broker identifier
            broker_class: BrokerConnector subclass
        """
        if not issubclass(broker_class, BrokerConnector):
            raise ValueError(f"{broker_class} must be a subclass of BrokerConnector")
        
        cls._brokers[name.lower()] = broker_class
        logger.info(f"Registered broker: {name}")
    
    @classmethod
    def list_brokers(cls) -> list:
        """
        Get list of available broker types.
        
        Returns:
            List of broker type strings
        """
        return list(cls._brokers.keys())
