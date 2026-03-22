"""
Broker Factory — creates and registers broker instances by name.
"""

import logging
from typing import Dict, Optional, Type

logger = logging.getLogger(__name__)


class BrokerFactory:
    """Factory for creating broker instances."""

    _brokers: Dict[str, type] = {}

    @classmethod
    def _ensure_registered(cls) -> None:
        """Lazy-register all built-in brokers on first use."""
        if cls._brokers:
            return
        try:
            from brokers.paper_trading import PaperTradingBroker
            cls._brokers["paper"] = PaperTradingBroker
        except Exception:
            pass
        try:
            from brokers.alpaca import AlpacaConnector
            cls._brokers["alpaca"] = AlpacaConnector
        except Exception:
            pass
        try:
            from brokers.binance import BinanceConnector
            cls._brokers["binance"] = BinanceConnector
        except Exception:
            pass
        try:
            from brokers.oanda import OANDAConnector
            cls._brokers["oanda"] = OANDAConnector
        except Exception:
            pass
        try:
            from brokers.mt5 import MT5Connector
            cls._brokers["mt5"] = MT5Connector
        except Exception:
            pass
        try:
            from brokers.interactive_brokers import InteractiveBrokersConnector
            cls._brokers["ib"] = InteractiveBrokersConnector
            cls._brokers["interactive_brokers"] = InteractiveBrokersConnector
        except Exception:
            pass
        try:
            from brokers.prop_firms.ftmo import FTMOConnector
            cls._brokers["ftmo"] = FTMOConnector
        except Exception:
            pass
        try:
            from brokers.prop_firms.topstep import TopstepTraderConnector
            cls._brokers["topstep"] = TopstepTraderConnector
            cls._brokers["topsteptrader"] = TopstepTraderConnector
        except Exception:
            pass
        try:
            from brokers.prop_firms.the5ers import The5ersConnector
            cls._brokers["the5ers"] = The5ersConnector
        except Exception:
            pass
        try:
            from brokers.prop_firms.myforexfunds import MyForexFundsConnector
            cls._brokers["myforexfunds"] = MyForexFundsConnector
            cls._brokers["mff"] = MyForexFundsConnector
        except Exception:
            pass

    @classmethod
    def register_broker(cls, name: str, broker_class: type) -> None:
        """Register a broker class. Raises ValueError if not a BrokerConnector subclass."""
        try:
            from brokers.base import BrokerConnector
            if not (isinstance(broker_class, type) and issubclass(broker_class, BrokerConnector)):
                raise ValueError(f"{broker_class} is not a BrokerConnector subclass")
        except ImportError:
            pass
        cls._brokers[name.lower()] = broker_class
        logger.info(f"Broker registered: {name}")

    @classmethod
    def create_broker(cls, name: str, config: Dict = None):
        """Create a broker instance by name (case-insensitive). Returns None for unknown brokers."""
        cls._ensure_registered()
        key = name.lower()
        broker_class = cls._brokers.get(key)
        if broker_class is None:
            logger.warning(f"Unknown broker: {name}")
            return None
        return broker_class(config or {})

    @classmethod
    def list_brokers(cls) -> list:
        """Return list of registered broker names."""
        cls._ensure_registered()
        return list(cls._brokers.keys())

    @classmethod
    def get_broker_info(cls, name: str) -> Dict:
        cls._ensure_registered()
        broker_class = cls._brokers.get(name.lower())
        if not broker_class:
            return {}
        return {
            "name": name,
            "class": broker_class.__name__,
        }
