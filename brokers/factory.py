# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Broker Factory — creates and registers broker instances by name.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class BrokerFactory:
    """Factory for creating broker instances."""

    _brokers: Dict[str, type] = {}

    @classmethod
    def _ensure_registered(cls) -> None:
        """Lazy-register all built-in brokers on first use."""
        if cls._brokers:
            return
        # Each broker is optional — missing SDK or credentials are expected in CI.
        # Log at debug so the absence is traceable without polluting startup logs.
        try:
            from brokers.paper_trading import PaperTradingBroker

            cls._brokers["paper"] = PaperTradingBroker
        except Exception as exc:
            logger.debug("paper broker unavailable: %s", exc)
        try:
            from brokers.alpaca import AlpacaConnector

            cls._brokers["alpaca"] = AlpacaConnector
        except Exception as exc:
            logger.debug("alpaca broker unavailable: %s", exc)
        try:
            from brokers.binance import BinanceConnector

            cls._brokers["binance"] = BinanceConnector
        except Exception as exc:
            logger.debug("binance broker unavailable: %s", exc)
        try:
            from brokers.oanda import OANDAConnector

            cls._brokers["oanda"] = OANDAConnector
        except Exception as exc:
            logger.debug("oanda broker unavailable: %s", exc)
        try:
            from brokers.mt5 import MT5Connector

            cls._brokers["mt5"] = MT5Connector
        except Exception as exc:
            logger.debug("mt5 broker unavailable: %s", exc)
        try:
            from brokers.ibkr_connector import IBKRConnector

            cls._brokers["ibkr"] = IBKRConnector
            cls._brokers["ib"] = IBKRConnector
            cls._brokers["interactive_brokers"] = IBKRConnector
        except Exception as exc:
            logger.debug("IBKRConnector unavailable: %s", exc)
            # Legacy fallback
            try:
                from brokers.interactive_brokers import InteractiveBrokersConnector

                cls._brokers["ib"] = InteractiveBrokersConnector
                cls._brokers["interactive_brokers"] = InteractiveBrokersConnector
            except Exception as exc2:
                logger.debug(
                    "interactive_brokers legacy connector unavailable: %s", exc2
                )
        try:
            from brokers.prop_firms.ftmo import FTMOConnector

            cls._brokers["ftmo"] = FTMOConnector
        except Exception as exc:
            logger.debug("ftmo broker unavailable: %s", exc)
        try:
            from brokers.prop_firms.topstep import TopstepTraderConnector

            cls._brokers["topstep"] = TopstepTraderConnector
            cls._brokers["topsteptrader"] = TopstepTraderConnector
        except Exception as exc:
            logger.debug("topstep broker unavailable: %s", exc)
        try:
            from brokers.prop_firms.the5ers import The5ersConnector

            cls._brokers["the5ers"] = The5ersConnector
        except Exception as exc:
            logger.debug("the5ers broker unavailable: %s", exc)
        try:
            from brokers.prop_firms.myforexfunds import MyForexFundsConnector

            cls._brokers["myforexfunds"] = MyForexFundsConnector
            cls._brokers["mff"] = MyForexFundsConnector
        except Exception as exc:
            logger.debug("myforexfunds broker unavailable: %s", exc)

    @classmethod
    def register_broker(cls, name: str, broker_class: type) -> None:
        """Register a broker class. Raises ValueError if not a BrokerConnector subclass."""
        try:
            from brokers.base import BrokerConnector

            if not (
                isinstance(broker_class, type)
                and issubclass(broker_class, BrokerConnector)
            ):
                raise ValueError(f"{broker_class} is not a BrokerConnector subclass")
        except ImportError as exc:
            logger.debug(
                "BrokerConnector base class unavailable during registration: %s",
                exc,
            )
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
