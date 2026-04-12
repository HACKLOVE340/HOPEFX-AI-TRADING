# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for brokers/factory.py — YAML config path and type dispatch.

Covers get_broker_from_yaml(), _load_yaml_config(), register_broker(),
create_broker() edge cases, list_brokers(), and get_broker_info().
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fresh_factory():
    """Return BrokerFactory with a clean broker registry."""
    from brokers.factory import BrokerFactory

    BrokerFactory._brokers = {}
    return BrokerFactory


def _write_yaml(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "brokers.yaml"
    p.write_text(yaml.dump(content))
    return p


# ── _load_yaml_config ─────────────────────────────────────────────────────────


class TestLoadYamlConfig:
    def test_returns_none_when_file_missing(self, tmp_path):
        from brokers.factory import BrokerFactory

        result = BrokerFactory._load_yaml_config(str(tmp_path / "nonexistent.yaml"))
        assert result is None

    def test_returns_dict_when_file_exists(self, tmp_path):
        p = _write_yaml(tmp_path, {"brokers": {"default": "paper"}})
        from brokers.factory import BrokerFactory

        result = BrokerFactory._load_yaml_config(str(p))
        assert isinstance(result, dict)
        assert result["brokers"]["default"] == "paper"

    def test_handles_empty_yaml(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        from brokers.factory import BrokerFactory

        result = BrokerFactory._load_yaml_config(str(p))
        # yaml.safe_load("") returns None
        assert result is None


# ── get_broker_from_yaml — missing / bad config ───────────────────────────────


class TestGetBrokerFromYamlErrors:
    def test_returns_none_when_config_file_missing(self, tmp_path):
        from brokers.factory import BrokerFactory

        result = BrokerFactory.get_broker_from_yaml(
            name="any",
            config_path=str(tmp_path / "missing.yaml"),
        )
        assert result is None

    def test_returns_none_when_broker_name_not_in_yaml(self, tmp_path):
        p = _write_yaml(tmp_path, {"brokers": {"default": "paper"}})
        from brokers.factory import BrokerFactory

        result = BrokerFactory.get_broker_from_yaml(
            name="nonexistent_profile",
            config_path=str(p),
        )
        assert result is None

    def test_returns_none_for_unsupported_broker_type(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            {
                "brokers": {
                    "default": "exotic",
                    "exotic": {"type": "exotic_broker"},
                }
            },
        )
        from brokers.factory import BrokerFactory

        result = BrokerFactory.get_broker_from_yaml(
            name="exotic",
            config_path=str(p),
        )
        assert result is None

    def test_uses_env_broker_when_name_is_none(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            {
                "brokers": {
                    "default": "paper_profile",
                    "paper_profile": {"type": "unsupported_xyz"},
                }
            },
        )
        from brokers.factory import BrokerFactory

        with patch.dict(os.environ, {"BROKER": "paper_profile"}):
            result = BrokerFactory.get_broker_from_yaml(
                name=None,
                config_path=str(p),
            )
        # unsupported type → None, but the env var was used for resolution
        assert result is None

    def test_uses_yaml_default_when_name_and_env_absent(self, tmp_path):
        p = _write_yaml(
            tmp_path,
            {
                "brokers": {
                    "default": "my_default",
                    "my_default": {"type": "unsupported_xyz"},
                }
            },
        )
        from brokers.factory import BrokerFactory

        env = {k: v for k, v in os.environ.items() if k != "BROKER"}
        with patch.dict(os.environ, env, clear=True):
            result = BrokerFactory.get_broker_from_yaml(
                name=None,
                config_path=str(p),
            )
        assert result is None  # unsupported type, but default was resolved


# ── get_broker_from_yaml — type dispatch ──────────────────────────────────────


class TestGetBrokerFromYamlTypeDispatch:
    """Each broker type (mt5, oanda, ibkr) is dispatched to the right class."""

    def _yaml_with_type(self, tmp_path, broker_type):
        return _write_yaml(
            tmp_path,
            {
                "brokers": {
                    "default": "profile",
                    "profile": {"type": broker_type, "host": "localhost"},
                }
            },
        )

    def test_mt5_type_creates_mt5_broker(self, tmp_path):
        p = self._yaml_with_type(tmp_path, "mt5")
        mock_broker = MagicMock()
        mock_mt5_class = MagicMock(return_value=mock_broker)
        mock_module = MagicMock(MT5Broker=mock_mt5_class)

        from brokers.factory import BrokerFactory

        with patch.dict("sys.modules", {"brokers.mt5_broker": mock_module}):
            result = BrokerFactory.get_broker_from_yaml(name="profile", config_path=str(p))

        mock_mt5_class.assert_called_once()
        assert result is mock_broker

    def test_oanda_type_creates_oanda_broker(self, tmp_path):
        p = self._yaml_with_type(tmp_path, "oanda")
        mock_broker = MagicMock()
        mock_oanda_class = MagicMock(return_value=mock_broker)
        mock_module = MagicMock(OandaBroker=mock_oanda_class)

        from brokers.factory import BrokerFactory

        with patch.dict("sys.modules", {"brokers.oanda_broker": mock_module}):
            result = BrokerFactory.get_broker_from_yaml(name="profile", config_path=str(p))

        mock_oanda_class.assert_called_once()
        assert result is mock_broker

    def test_ibkr_type_creates_ibkr_broker(self, tmp_path):
        p = self._yaml_with_type(tmp_path, "ibkr")
        mock_broker = MagicMock()
        mock_ibkr_class = MagicMock(return_value=mock_broker)
        mock_module = MagicMock(IBKRBroker=mock_ibkr_class)

        from brokers.factory import BrokerFactory

        with patch.dict("sys.modules", {"brokers.ibkr_broker": mock_module}):
            result = BrokerFactory.get_broker_from_yaml(name="profile", config_path=str(p))

        mock_ibkr_class.assert_called_once()
        assert result is mock_broker

    def test_import_error_returns_none(self, tmp_path):
        p = self._yaml_with_type(tmp_path, "mt5")
        from brokers.factory import BrokerFactory

        # Simulate ImportError by making the module raise on import
        with patch.dict("sys.modules", {"brokers.mt5_broker": None}):
            result = BrokerFactory.get_broker_from_yaml(name="profile", config_path=str(p))

        assert result is None


# ── create_broker ─────────────────────────────────────────────────────────────


class TestCreateBroker:
    def _mock_broker_class(self):
        """Return a MagicMock that looks like a real class (has __name__)."""
        instance = MagicMock()
        cls = MagicMock(return_value=instance)
        cls.__name__ = "MockBroker"
        return cls, instance

    def test_create_broker_returns_none_for_unknown_name(self):
        factory = _fresh_factory()
        result = factory.create_broker(name="totally_unknown_xyz_broker")
        assert result is None

    def test_create_broker_uses_default_when_name_is_none(self):
        factory = _fresh_factory()
        mock_class, mock_instance = self._mock_broker_class()
        factory._brokers["paper"] = mock_class

        with patch.dict(os.environ, {"BROKER": "paper"}):
            result = factory.create_broker(name=None)

        assert result is mock_instance
        mock_class.assert_called_once()

    def test_create_broker_passes_config_to_class(self):
        factory = _fresh_factory()
        mock_class, _ = self._mock_broker_class()
        factory._brokers["testbroker"] = mock_class

        factory.create_broker(name="testbroker", config={"key": "val"})
        mock_class.assert_called_once_with({"key": "val"})

    def test_create_broker_passes_empty_config_when_none(self):
        factory = _fresh_factory()
        mock_class, _ = self._mock_broker_class()
        factory._brokers["testbroker"] = mock_class

        factory.create_broker(name="testbroker", config=None)
        mock_class.assert_called_once_with({})

    def test_create_broker_case_insensitive(self):
        factory = _fresh_factory()
        mock_class, mock_instance = self._mock_broker_class()
        factory._brokers["paper"] = mock_class

        result = factory.create_broker(name="PAPER")
        assert result is mock_instance


# ── register_broker ───────────────────────────────────────────────────────────


class TestRegisterBroker:
    def test_register_broker_stores_class(self):
        factory = _fresh_factory()

        class FakeBroker:
            pass

        # Bypass the BrokerConnector subclass check by mocking the import
        with patch.dict("sys.modules", {"brokers.base": MagicMock(BrokerConnector=object)}):
            factory.register_broker("fake", FakeBroker)

        assert "fake" in factory._brokers
        assert factory._brokers["fake"] is FakeBroker

    def test_register_broker_raises_for_non_subclass(self):
        factory = _fresh_factory()

        class NotABroker:
            pass

        mock_base = MagicMock()
        mock_base.BrokerConnector = type("BrokerConnector", (), {})

        with patch.dict("sys.modules", {"brokers.base": mock_base}):
            with pytest.raises(ValueError, match="not a BrokerConnector subclass"):
                factory.register_broker("bad", NotABroker)

    def test_register_broker_handles_import_error_gracefully(self):
        factory = _fresh_factory()

        class AnyClass:
            pass

        with patch.dict("sys.modules", {"brokers.base": None}):
            # Should not raise even when base import fails
            factory.register_broker("any", AnyClass)

        assert "any" in factory._brokers


# ── list_brokers / get_broker_info ────────────────────────────────────────────


class TestListAndInfo:
    def test_list_brokers_returns_list(self):
        factory = _fresh_factory()
        factory._brokers["alpha"] = MagicMock()
        factory._brokers["beta"] = MagicMock()
        # Prevent _ensure_registered from overwriting our manual entries
        with patch.object(factory, "_ensure_registered"):
            result = factory.list_brokers()
        assert "alpha" in result
        assert "beta" in result

    def test_get_broker_info_returns_empty_for_unknown(self):
        factory = _fresh_factory()
        with patch.object(factory, "_ensure_registered"):
            result = factory.get_broker_info("nonexistent")
        assert result == {}

    def test_get_broker_info_returns_name_and_class(self):
        factory = _fresh_factory()

        class MyBroker:
            pass

        factory._brokers["mybroker"] = MyBroker
        with patch.object(factory, "_ensure_registered"):
            result = factory.get_broker_info("mybroker")
        assert result["name"] == "mybroker"
        assert result["class"] == "MyBroker"


# ── _ensure_registered lazy loading ──────────────────────────────────────────


class TestEnsureRegistered:
    def test_ensure_registered_is_idempotent(self):
        factory = _fresh_factory()
        # Pre-populate so the guard short-circuits
        factory._brokers["paper"] = MagicMock()
        before = dict(factory._brokers)
        factory._ensure_registered()
        # Should not have changed anything
        assert factory._brokers == before

    def test_ensure_registered_handles_all_import_errors(self):
        factory = _fresh_factory()
        # All broker imports fail — should still complete without raising
        bad_modules = {
            "brokers.paper_trading": None,
            "brokers.alpaca": None,
            "brokers.binance": None,
            "brokers.oanda": None,
            "brokers.mt5": None,
            "brokers.ibkr_connector": None,
            "brokers.interactive_brokers": None,
            "brokers.bybit_connector": None,
            "brokers.prop_firms.ftmo": None,
            "brokers.prop_firms.topstep": None,
            "brokers.prop_firms.the5ers": None,
            "brokers.prop_firms.myforexfunds": None,
            "brokers.cme_comex": None,
            "brokers.cpp_shim_connector": None,
        }
        with patch.dict("sys.modules", bad_modules):
            factory._ensure_registered()
        # No exception raised — registry may be empty or partial
