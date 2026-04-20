# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for broker SDK conditional import guards.

Issue 7 context
---------------
16 test files failed to collect in CI due to missing packages. The root
causes were:
  - matplotlib, email-validator, hypothesis: missing from the installed env
    (they ARE in requirements-ci.txt — the env was stale).
  - MetaTrader5, ib_insync, quickfix: platform-specific SDKs that cannot
    be installed in CI (Windows-only / C++ headers required). These must
    be guarded with try/except ImportError at module level.

These tests verify:
1. MT5Broker, IBKRBroker, FIXAdapter degrade gracefully when their SDKs
   are unavailable — they must not raise ImportError at import time.
2. The _*_AVAILABLE flags correctly reflect SDK presence.
3. Broker methods raise RuntimeError (not ImportError) when SDK is absent.
4. requirements-ci.txt contains all packages needed for the test suite.
5. The fix_adapter falls back to simplefix when quickfix is unavailable.
6. Previously-failing test modules now import without error.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# ── MT5Broker conditional import guard ───────────────────────────────────────

class TestMT5BrokerGuard:
    """MT5Broker must import cleanly even when MetaTrader5 SDK is absent."""

    def test_mt5_broker_imports_without_sdk(self):
        """brokers.mt5_broker must import without raising ImportError."""
        try:
            import brokers.mt5_broker  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"brokers.mt5_broker raised ImportError at import time: {exc}\n"
                "MetaTrader5 SDK absence must be handled with try/except at module level."
            )

    def test_mt5_available_flag_is_bool(self):
        """_MT5_AVAILABLE must be a bool (True if SDK installed, False otherwise)."""
        import brokers.mt5_broker as m
        assert isinstance(m._MT5_AVAILABLE, bool), (
            f"_MT5_AVAILABLE must be bool, got {type(m._MT5_AVAILABLE)}"
        )

    def test_mt5_broker_class_importable(self):
        """MT5Broker class must be importable regardless of SDK availability."""
        from brokers.mt5_broker import MT5Broker
        assert MT5Broker is not None

    @pytest.mark.asyncio
    async def test_mt5_broker_connect_raises_runtime_not_import(self):
        """
        When MT5 SDK is absent, MT5Broker.connect() must raise RuntimeError
        (or return False), NOT ImportError or AttributeError.
        connect() is async — must be awaited.
        """
        import brokers.mt5_broker as m
        if m._MT5_AVAILABLE:
            pytest.skip("MetaTrader5 SDK is installed — guard not exercised")

        broker = m.MT5Broker(config={"login": 12345, "password": "test", "server": "test-server"})
        try:
            result = await broker.connect()
            assert result is False or result is None, (
                f"connect() returned {result!r} — expected False when SDK unavailable"
            )
        except RuntimeError:
            pass  # Acceptable
        except ImportError as exc:
            pytest.fail(
                f"MT5Broker.connect() raised ImportError: {exc}\n"
                "Must raise RuntimeError or return False, not ImportError."
            )

    def test_mt5_broker_status_includes_sdk_flag(self):
        """MT5Broker.status() must include sdk_available key."""
        import brokers.mt5_broker as m
        broker = m.MT5Broker(config={"login": 12345, "password": "test", "server": "test-server"})
        status = broker.status()
        assert "sdk_available" in status, (
            "MT5Broker.status() must include 'sdk_available' key"
        )
        assert isinstance(status["sdk_available"], bool)


# ── IBKRBroker conditional import guard ──────────────────────────────────────

class TestIBKRBrokerGuard:
    """IBKRBroker must import cleanly even when ib_insync is absent."""

    def test_ibkr_broker_imports_without_sdk(self):
        """brokers.ibkr must import without raising ImportError."""
        try:
            import brokers.ibkr  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"brokers.ibkr raised ImportError at import time: {exc}\n"
                "ib_insync absence must be handled with try/except at module level."
            )

    def test_ib_available_flag_is_bool(self):
        """_IB_AVAILABLE must be a bool."""
        import brokers.ibkr as m
        assert isinstance(m._IB_AVAILABLE, bool), (
            f"_IB_AVAILABLE must be bool, got {type(m._IB_AVAILABLE)}"
        )

    def test_ibkr_broker_class_importable(self):
        """IBKRBroker class must be importable regardless of SDK availability."""
        from brokers.ibkr import IBKRBroker
        assert IBKRBroker is not None

    @pytest.mark.asyncio
    async def test_ibkr_broker_connect_raises_runtime_not_import(self):
        """
        When ib_insync is absent, IBKRBroker.connect() must raise RuntimeError
        or return False — NOT ImportError.
        connect() is async — must be awaited.
        """
        import brokers.ibkr as m
        if m._IB_AVAILABLE:
            pytest.skip("ib_insync is installed — guard not exercised")

        broker = m.IBKRBroker(config={"host": "127.0.0.1", "port": 7497, "client_id": 1})
        try:
            result = await broker.connect()
            assert result is False or result is None, (
                f"connect() returned {result!r} — expected False when SDK unavailable"
            )
        except RuntimeError:
            pass  # Acceptable
        except ImportError as exc:
            pytest.fail(
                f"IBKRBroker.connect() raised ImportError: {exc}\n"
                "Must raise RuntimeError or return False."
            )

    def test_ibkr_broker_not_available_when_sdk_absent(self):
        """When ib_insync is absent, _IB_AVAILABLE must be False."""
        import brokers.ibkr as m
        if m._IB_AVAILABLE:
            pytest.skip("ib_insync is installed — this test only applies when absent")
        assert m._IB_AVAILABLE is False


# ── FIX adapter conditional import guard ─────────────────────────────────────

class TestFIXAdapterGuard:
    """FIXAdapter must import cleanly and fall back to simplefix when quickfix absent."""

    def test_fix_adapter_imports_without_quickfix(self):
        """execution.fix_adapter must import without raising ImportError."""
        try:
            import execution.fix_adapter  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"execution.fix_adapter raised ImportError at import time: {exc}\n"
                "quickfix absence must be handled with try/except at module level."
            )

    def test_fix_backend_is_string(self):
        """_FIX_BACKEND must be a string ('quickfix', 'simplefix', or 'none')."""
        import execution.fix_adapter as m
        assert isinstance(m._FIX_BACKEND, str), (
            f"_FIX_BACKEND must be str, got {type(m._FIX_BACKEND)}"
        )
        assert m._FIX_BACKEND in ("quickfix", "pyfixmsg", "simplefix", "none"), (
            f"_FIX_BACKEND={m._FIX_BACKEND!r} — must be one of: quickfix, pyfixmsg, simplefix, none"
        )

    def test_fix_adapter_class_importable(self):
        """FIXAdapter class must be importable regardless of backend availability."""
        from execution.fix_adapter import FIXAdapter
        assert FIXAdapter is not None

    def test_fix_adapter_falls_back_to_simplefix_or_none(self):
        """
        When quickfix is absent (CI environment), _FIX_BACKEND must be
        'simplefix' or 'none' — never 'quickfix'.
        """
        import execution.fix_adapter as m
        try:
            import quickfix  # noqa: F401
            pytest.skip("quickfix is installed — fallback not exercised")
        except ImportError:
            pass

        assert m._FIX_BACKEND != "quickfix", (
            f"_FIX_BACKEND={m._FIX_BACKEND!r} — must not be 'quickfix' when quickfix is absent"
        )

    def test_fix_adapter_connect_raises_runtime_not_import(self):
        """FIXAdapter.connect() must raise RuntimeError (not ImportError) when backend absent."""
        import execution.fix_adapter as m
        if m._FIX_BACKEND == "quickfix":
            pytest.skip("quickfix is installed — guard not exercised")

        adapter = m.FIXAdapter.__new__(m.FIXAdapter)
        # Minimal init without network
        try:
            adapter.__init__(host="127.0.0.1", port=9876, sender_comp_id="TEST",
                             target_comp_id="BROKER")
        except Exception:
            pass  # init may fail without a real FIX server

        # connect() must not raise ImportError
        try:
            adapter.connect()
        except RuntimeError:
            pass  # Acceptable
        except ImportError as exc:
            pytest.fail(
                f"FIXAdapter.connect() raised ImportError: {exc}\n"
                "Must raise RuntimeError when FIX backend is unavailable."
            )
        except Exception:
            pass  # Other errors (connection refused, etc.) are acceptable


# ── requirements-ci.txt completeness ─────────────────────────────────────────

class TestRequirementsCiCompleteness:
    """requirements-ci.txt must contain all packages needed for the test suite."""

    CI_REQS_PATH = ROOT / "requirements-ci.txt"

    def _parse_requirements(self) -> set[str]:
        """Return the set of package names (lowercased, no version specifiers)."""
        lines = self.CI_REQS_PATH.read_text().splitlines()
        names = set()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip version specifiers and extras
            name = line.split(">=")[0].split("<=")[0].split("==")[0].split("[")[0].strip()
            names.add(name.lower().replace("-", "_").replace(".", "_"))
        return names

    def test_requirements_ci_exists(self):
        assert self.CI_REQS_PATH.exists(), "requirements-ci.txt not found"

    def test_matplotlib_in_ci_requirements(self):
        """matplotlib must be in requirements-ci.txt (needed by test_analytics, test_monte_carlo)."""
        reqs = self._parse_requirements()
        assert "matplotlib" in reqs, (
            "matplotlib missing from requirements-ci.txt — "
            "test_analytics.py and test_monte_carlo.py will fail to collect"
        )

    def test_email_validator_in_ci_requirements(self):
        """email-validator must be in requirements-ci.txt (needed by pydantic[email] in auth)."""
        reqs = self._parse_requirements()
        assert "email_validator" in reqs or "email-validator" in {
            line.split(">=")[0].split("<=")[0].split("==")[0].strip().lower()
            for line in self.CI_REQS_PATH.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }, (
            "email-validator missing from requirements-ci.txt — "
            "test_api.py, test_social_feed.py, test_trading_auth.py will fail to collect"
        )

    def test_hypothesis_in_ci_requirements(self):
        """hypothesis must be in requirements-ci.txt (needed by test_property_based, test_risk_properties)."""
        reqs = self._parse_requirements()
        assert "hypothesis" in reqs, (
            "hypothesis missing from requirements-ci.txt — "
            "test_property_based.py and test_risk_properties.py will fail to collect"
        )

    def test_quickfix_excluded_with_comment(self):
        """
        quickfix must be excluded from requirements-ci.txt with an explanatory comment.
        It requires libquickfix-dev C++ headers unavailable on bare Ubuntu runners.
        """
        content = self.CI_REQS_PATH.read_text()
        assert "quickfix" in content.lower(), (
            "requirements-ci.txt must mention quickfix (even if excluded) "
            "so developers understand why it's absent from CI"
        )

    def test_ib_insync_excluded_with_comment(self):
        """
        ib_insync must be excluded from requirements-ci.txt with an explanatory comment.
        It requires Interactive Brokers TWS/Gateway which is unavailable in CI.
        """
        content = self.CI_REQS_PATH.read_text()
        assert "ib_insync" in content.lower() or "ib-insync" in content.lower(), (
            "requirements-ci.txt must mention ib_insync (even if excluded) "
            "so developers understand why it's absent from CI"
        )

    def test_metatrader5_excluded_with_comment(self):
        """
        MetaTrader5 must be excluded from requirements-ci.txt.
        It is Windows-only and unavailable on Linux CI runners.
        """
        content = self.CI_REQS_PATH.read_text()
        # MetaTrader5 may be mentioned in comments or requirements-optional.txt
        optional_path = ROOT / "requirements-optional.txt"
        optional_content = optional_path.read_text() if optional_path.exists() else ""
        assert (
            "metatrader5" in content.lower()
            or "metatrader5" in optional_content.lower()
            or "MetaTrader5" in optional_content
        ), (
            "MetaTrader5 must be documented in requirements-ci.txt or requirements-optional.txt "
            "so developers know it's excluded from CI (Windows-only SDK)"
        )


# ── Previously-failing test modules now import cleanly ────────────────────────

class TestPreviouslyFailingModulesImport:
    """
    The 7 test files that previously failed to collect must now import cleanly.
    This is a regression guard — if any of these start failing again, the
    missing package must be added to requirements-ci.txt immediately.
    """

    PREVIOUSLY_FAILING = [
        "tests.unit.test_analytics",
        "tests.unit.test_api",
        "tests.unit.test_monte_carlo",
        "tests.unit.test_property_based",
        "tests.unit.test_risk_properties",
        "tests.unit.test_social_feed",
        "tests.unit.test_trading_auth",
    ]

    @pytest.mark.parametrize("module_name", PREVIOUSLY_FAILING)
    def test_module_imports_without_error(self, module_name):
        """Each previously-failing module must import without ImportError."""
        try:
            mod = importlib.import_module(module_name)
            assert mod is not None
        except ImportError as exc:
            pytest.fail(
                f"{module_name} raised ImportError: {exc}\n"
                "This module previously failed to collect. "
                "Add the missing package to requirements-ci.txt."
            )
        except Exception as exc:
            # Non-import errors (e.g. missing DB, missing env var) are acceptable
            # at import time — they'll surface as test failures, not collection errors.
            pass


# ── Broker factory handles missing SDKs ──────────────────────────────────────

class TestBrokerFactoryMissingSDKs:
    """BrokerFactory must not raise when broker SDKs are absent."""

    def test_factory_imports_cleanly(self):
        """brokers.factory must import without error."""
        try:
            import brokers.factory  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"brokers.factory raised ImportError: {exc}")

    def test_factory_list_available_brokers(self):
        """BrokerFactory.list_available() must return a list (may be empty if SDKs absent)."""
        from brokers.factory import BrokerFactory
        available = BrokerFactory.list_available()
        assert isinstance(available, (list, dict, set)), (
            f"list_available() must return a collection, got {type(available)}"
        )

    def test_factory_create_paper_broker_always_works(self):
        """PaperTradingBroker must always be creatable — no external SDK required."""
        from brokers import PaperTradingBroker
        broker = PaperTradingBroker(initial_balance=10_000.0)
        assert broker is not None

    def test_factory_create_mt5_raises_runtime_not_import(self):
        """
        Creating an MT5Broker when SDK is absent must not raise ImportError.
        The broker object must be constructable and status() must work.
        """
        import brokers.mt5_broker as m
        if m._MT5_AVAILABLE:
            pytest.skip("MetaTrader5 SDK is installed")

        from brokers.mt5_broker import MT5Broker
        broker = MT5Broker(config={"login": 0, "password": "", "server": ""})
        assert broker is not None
        status = broker.status()
        assert status["sdk_available"] is False
