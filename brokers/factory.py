"""
Broker Factory Pattern
- Unified broker interface
- Dynamic broker instantiation
"""

from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class BrokerFactory:
    """Factory for creating broker instances"""
    
    _brokers = {}
    
    @classmethod
    def register_broker(cls, name: str, broker_class):
        """Register broker class"""
        cls._brokers[name] = broker_class
        logger.info(f"Broker registered: {name}")
    
    @classmethod
    def create_broker(cls, name: str, config: Dict = None):
        """Create broker instance"""
        if name not in cls._brokers:
            raise ValueError(f"Unknown broker: {name}")
        
        broker_class = cls._brokers[name]
        return broker_class(config or {})
    
    @classmethod
    def list_brokers(cls) -> list:
        """List all registered brokers"""
        return list(cls._brokers.keys())
    
    @classmethod
    def get_broker_info(cls, name: str) -> Dict:
        """Get broker information"""
        if name not in cls._brokers:
            return {}
        
        broker_class = cls._brokers[name]
        return {
            'name': name,
            'class': broker_class.__name__,
            'supports_paper': hasattr(broker_class, 'paper_trading'),
            'supports_live': hasattr(broker_class, 'live_trading')
        }