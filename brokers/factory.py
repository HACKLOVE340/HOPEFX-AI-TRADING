# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Broker Factory — creates and registers broker instances by name.

Broker selection priority
-------------------------
1. Explicit name passed to create_broker(name)
2. BROKER env var (e.g. BROKER=mt5, BROKER=oanda, BROKER=paper)
3. Default: "paper" (safe fallback)

MT5 is a first-class broker. Set BROKER=mt5 to route the entire
tick → signal → risk → execute pipeline through MT5Bridge.
"""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Default broker from environment — allows `python run.py` to pick up BROKER=mt5
_DEFAULT_BROKER = os.getenv("BROKER", "paper").lower()


class BrokerFactory:
    """Factory for creating broker instances."""

    _brokers: dict[str, type] = {}

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
                logger.debug("interactive_brokers legacy connector unavailable: %s", exc2)
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

            if not (isinstance(broker_class, type) and issubclass(broker_class, BrokerConnector)):
                raise ValueError(f"{broker_class} is not a BrokerConnector subclass")
        except ImportError as exc:
            logger.debug(
                "BrokerConnector base class unavailable during registration: %s",
                exc,
            )
        cls._brokers[name.lower()] = broker_class
        logger.info("Broker registered: %s", name)


    @classmethod
    def create_broker(cls, name: str | None = None, config: dict | None = None):
        """
        Create a broker instance by name (case-insensitive).

        If name is None, uses the BROKER env var (default: "paper").
        Returns None for unknown brokers.

        MT5 special handling: when name="mt5", creates an MT5Bridge-backed
        connector that supports the full hot path including modify/cancel.
        """
        cls._ensure_registered()
        resolved = (name or _DEFAULT_BROKER).lower()
        broker_class = cls._brokers.get(resolved)
        if broker_class is None:
            logger.warning(
                "Unknown broker: %s (available: %s)",
                resolved,
                list(cls._brokers.keys()),
            )
            return None
        logger.info("Creating broker: %s (%s)", resolved, broker_class.__name__)
        return broker_class(config or {})

    @classmethod
    def list_brokers(cls) -> list:
        """Return list of registered broker names."""
        cls._ensure_registered()
        return list(cls._brokers.keys())

    @classmethod
    def get_broker_info(cls, name: str) -> dict:
        cls._ensure_registered()
        broker_class = cls._brokers.get(name.lower())
        if not broker_class:
            return {}
        return {
            "name": name,
            "class": broker_class.__name__,
        }

    # ── YAML-config-based factory ──────────────────────────────────────────────

    @classmethod
    def get_broker_from_yaml(
        cls,
        name: str | None = None,
        config_path: str = "config/brokers.yaml",
    ):
        """
        Instantiate a broker using credentials from ``config/brokers.yaml``.

        This is the preferred entry point for the new typed broker classes
        (MT5Broker, OandaBroker, IBKRBroker).  The existing ``create_broker``
        classmethod continues to work for the legacy connector registry.

        Parameters
        ----------
        name:
            Key in the ``brokers`` section of the YAML file (e.g. ``prop_mt5``).
            Falls back to the ``default`` key, then to the ``BROKER`` env var.
        config_path:
            Path to the YAML config file (relative to CWD or absolute).

        Returns
        -------
        MT5Broker | OandaBroker | IBKRBroker instance, or None on failure.
        """
        cfg = cls._load_yaml_config(config_path)
        if cfg is None:
            return None

        brokers_section: dict = cfg.get("brokers", {})
        resolved_name = name or os.getenv("BROKER") or brokers_section.get("default", "prop_mt5")

        broker_cfg = brokers_section.get(resolved_name)
        if broker_cfg is None:
            logger.error(
                "Broker '%s' not found in %s. Available: %s",
                resolved_name,
                config_path,
                [k for k in brokers_section if k != "default"],
            )
            return None

        broker_type: str = broker_cfg.get("type", "").lower()

        try:
            if broker_type == "mt5":
                from brokers.mt5_broker import MT5Broker

                logger.info("Creating MT5Broker for profile '%s'", resolved_name)
                return MT5Broker(broker_cfg)

            if broker_type == "oanda":
                from brokers.oanda_broker import OandaBroker

                logger.info("Creating OandaBroker for profile '%s'", resolved_name)
                return OandaBroker(broker_cfg)

            if broker_type == "ibkr":
                from brokers.ibkr_broker import IBKRBroker

                logger.info("Creating IBKRBroker for profile '%s'", resolved_name)
                return IBKRBroker(broker_cfg)

            logger.error(
                "Unsupported broker type '%s' for profile '%s'. Supported: mt5, oanda, ibkr",
                broker_type,
                resolved_name,
            )
            return None

        except ImportError as exc:
            logger.error(
                "Cannot import broker class for type '%s': %s. Ensure the required SDK is installed.",
                broker_type,
                exc,
            )
            return None

    @staticmethod
    def _load_yaml_config(path: str) -> dict | None:
        """Load and return the YAML config, or None if the file is missing."""
        config_path = Path(path)
        if not config_path.exists():
            logger.error("Broker config not found: %s", config_path.resolve())
            return None
        with config_path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
