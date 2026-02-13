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

logger = logging.getLogger(__name__)


class BrokerFactory:
    """
    Factory for creating broker connector instances.
    
    Supports:
        - paper: Paper trading simulator
        - oanda: OANDA forex trading
        - binance: Binance cryptocurrency trading
        - alpaca: Alpaca US stock trading
    """
    
    _brokers = {
        'paper': PaperTradingBroker,
        'oanda': OANDAConnector,
        'binance': BinanceConnector,
        'alpaca': AlpacaConnector,
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
        
        Example:
            >>> config = {
            ...     'api_key': 'your-key',
            ...     'api_secret': 'your-secret',
            ...     'environment': 'practice'
            ... }
            >>> broker = BrokerFactory.create_broker('oanda', config)
            >>> broker.connect()
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
