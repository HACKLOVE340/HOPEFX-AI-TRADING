# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for OANDA paper trading clock:
- _stamp_oanda_paper_start() creates the stamp file on first call
- Subsequent calls do NOT overwrite the existing stamp
- paper_trading_status() clock logic returns correct elapsed/remaining days
- init_broker falls back to paper when OANDA creds are absent

These tests are isolated from FastAPI and broker dependencies.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_stamp(data_dir: pathlib.Path, started_utc: datetime, days: int = 30) -> pathlib.Path:
    stamp = data_dir / "oanda_paper_start.json"
    stamp.write_text(
        json.dumps(
            {
                "account_id": "12345678\u2026",
                "environment": "practice",
                "started_utc": started_utc.isoformat(),
                "target_days": days,
                "note": "test",
            }
        )
    )
    return stamp


def _compute_clock_status(stamp_path: pathlib.Path, oanda_key: str = "") -> dict:
    """
    Pure-Python replica of the paper_trading_status() logic in api/status.py.
    Used to test the clock arithmetic without importing FastAPI.
    """
    if not stamp_path.exists():
        if oanda_key:
            note = (
                "OANDA credentials are set but the broker has not connected yet. "
                "Start the server with BROKER_TYPE=oanda to begin the 30-day run."
            )
        else:
            note = (
                "Clock not started. Set BROKER_OANDA_TOKEN (or OANDA_API_KEY) "
                "and BROKER_OANDA_ACCOUNT, then restart with BROKER_TYPE=oanda."
            )
        return {
            "started": False,
            "started_utc": None,
            "elapsed_days": 0.0,
            "remaining_days": 30.0,
            "target_days": 30,
            "complete": False,
            "environment": None,
            "account_id": None,
            "note": note,
        }

    data = json.loads(stamp_path.read_text())
    started_dt = datetime.fromisoformat(data["started_utc"])
    now = datetime.now(UTC)
    elapsed = (now - started_dt).total_seconds() / 86400.0
    target = float(data.get("target_days", 30))
    remaining = max(0.0, target - elapsed)
    complete = elapsed >= target
    note = (
        f"Run complete \u2014 {elapsed:.1f} days elapsed."
        if complete
        else f"{elapsed:.1f} days elapsed, {remaining:.1f} days remaining."
    )
    return {
        "started": True,
        "started_utc": data["started_utc"],
        "elapsed_days": round(elapsed, 2),
        "remaining_days": round(remaining, 2),
        "target_days": int(target),
        "complete": complete,
        "environment": data.get("environment"),
        "account_id": data.get("account_id"),
        "note": note,
    }


# ---------------------------------------------------------------------------
# _stamp_oanda_paper_start
# ---------------------------------------------------------------------------


class TestStampOandaPaperStart:
    def test_creates_stamp_on_first_call(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()

        from core.startup_factories import _stamp_oanda_paper_start

        _stamp_oanda_paper_start("ACCT123456", practice=True)

        stamp = tmp_path / "data" / "oanda_paper_start.json"
        assert stamp.exists()
        data = json.loads(stamp.read_text())
        assert data["environment"] == "practice"
        assert "started_utc" in data
        assert data["target_days"] == 30

    def test_does_not_overwrite_existing_stamp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()

        original_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        stamp_path = tmp_path / "data" / "oanda_paper_start.json"
        stamp_path.write_text(
            json.dumps(
                {
                    "account_id": "ORIGINAL\u2026",
                    "environment": "practice",
                    "started_utc": original_time.isoformat(),
                    "target_days": 30,
                    "note": "original",
                }
            )
        )

        from core.startup_factories import _stamp_oanda_paper_start

        _stamp_oanda_paper_start("NEWACCOUNT", practice=True)

        data = json.loads(stamp_path.read_text())
        assert data["started_utc"] == original_time.isoformat()
        assert data["account_id"] == "ORIGINAL\u2026"

    def test_stamp_contains_masked_account_id(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()

        from core.startup_factories import _stamp_oanda_paper_start

        _stamp_oanda_paper_start("ABCDEFGHIJKLMNOP", practice=True)

        stamp = tmp_path / "data" / "oanda_paper_start.json"
        data = json.loads(stamp.read_text())
        assert data["account_id"].startswith("ABCDEFGH")
        assert "\u2026" in data["account_id"]

    def test_live_environment_recorded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()

        from core.startup_factories import _stamp_oanda_paper_start

        _stamp_oanda_paper_start("LIVEACCT1234", practice=False)

        stamp = tmp_path / "data" / "oanda_paper_start.json"
        data = json.loads(stamp.read_text())
        assert data["environment"] == "live"


# ---------------------------------------------------------------------------
# Clock arithmetic (pure logic, no FastAPI)
# ---------------------------------------------------------------------------


class TestPaperTradingClockLogic:
    def test_not_started_when_no_stamp(self, tmp_path):
        stamp = tmp_path / "oanda_paper_start.json"
        result = _compute_clock_status(stamp, oanda_key="")
        assert result["started"] is False
        assert result["elapsed_days"] == 0.0
        assert result["remaining_days"] == 30.0
        assert result["complete"] is False

    def test_creds_set_but_not_connected(self, tmp_path):
        stamp = tmp_path / "oanda_paper_start.json"
        result = _compute_clock_status(stamp, oanda_key="test-key")
        assert result["started"] is False
        assert "BROKER_TYPE=oanda" in result["note"]

    def test_elapsed_days_10(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        ten_days_ago = datetime.now(UTC) - timedelta(days=10)
        stamp = _write_stamp(data_dir, ten_days_ago)
        result = _compute_clock_status(stamp)
        assert result["started"] is True
        assert 9.9 <= result["elapsed_days"] <= 10.1
        assert 19.9 <= result["remaining_days"] <= 20.1
        assert result["complete"] is False

    def test_complete_after_31_days(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        thirty_one_days_ago = datetime.now(UTC) - timedelta(days=31)
        stamp = _write_stamp(data_dir, thirty_one_days_ago)
        result = _compute_clock_status(stamp)
        assert result["started"] is True
        assert result["complete"] is True
        assert result["remaining_days"] == 0.0
        assert result["elapsed_days"] >= 30.0

    def test_remaining_days_never_negative(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        old = datetime.now(UTC) - timedelta(days=100)
        stamp = _write_stamp(data_dir, old)
        result = _compute_clock_status(stamp)
        assert result["remaining_days"] == 0.0

    def test_environment_field_preserved(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        stamp = _write_stamp(data_dir, datetime.now(UTC) - timedelta(days=5))
        result = _compute_clock_status(stamp)
        assert result["environment"] == "practice"

    def test_elapsed_plus_remaining_equals_target(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fifteen_days_ago = datetime.now(UTC) - timedelta(days=15)
        stamp = _write_stamp(data_dir, fifteen_days_ago)
        result = _compute_clock_status(stamp)
        total = result["elapsed_days"] + result["remaining_days"]
        assert abs(total - 30.0) < 0.1  # within 2.4 hours tolerance


# ---------------------------------------------------------------------------
# init_broker selection logic
# ---------------------------------------------------------------------------


class TestInitBrokerSelection:
    """
    Test broker selection in init_broker() by patching lazy imports.
    Uses sys.modules patching to avoid needing fastapi/sqlalchemy installed.
    """

    @pytest.mark.asyncio
    async def test_falls_back_to_paper_when_no_oanda_creds(self, monkeypatch, tmp_path):
        """BROKER_TYPE=oanda but no token -> PaperTradingBroker."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        monkeypatch.setenv("BROKER_TYPE", "oanda")
        monkeypatch.delenv("BROKER_OANDA_TOKEN", raising=False)
        monkeypatch.delenv("OANDA_API_KEY", raising=False)

        mock_state = MagicMock()
        mock_state.db_session_factory = None

        mock_paper_instance = AsyncMock()
        mock_paper_instance.connect = AsyncMock(return_value=True)
        MockPaperClass = MagicMock(return_value=mock_paper_instance)

        _INJECTED = ("api.admin", "brokers.paper_trading", "core.startup_factories")
        with MagicMock() as mock_admin:  # pylint: disable=not-context-manager
            mock_admin.log_activity = MagicMock()
            # Snapshot only the keys we will mutate — never clear sys.modules
            # globally as that drops all cached modules and breaks subsequent tests.
            _saved = {k: sys.modules.get(k) for k in _INJECTED}
            sys.modules["api.admin"] = mock_admin
            sys.modules["brokers.paper_trading"] = MagicMock(PaperTradingBroker=MockPaperClass)
            try:
                import importlib

                import core.startup_factories as sf

                importlib.reload(sf)
                broker = await sf.init_broker(mock_state)
            finally:
                # Restore only the injected keys; leave everything else intact.
                for k, v in _saved.items():
                    if v is None:
                        sys.modules.pop(k, None)
                    else:
                        sys.modules[k] = v

        assert broker is mock_paper_instance

    @pytest.mark.asyncio
    async def test_uses_paper_broker_by_default(self, monkeypatch, tmp_path):
        """Default BROKER_TYPE=paper -> PaperTradingBroker."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        monkeypatch.setenv("BROKER_TYPE", "paper")

        mock_state = MagicMock()
        mock_state.db_session_factory = None

        mock_paper_instance = AsyncMock()
        mock_paper_instance.connect = AsyncMock(return_value=True)
        MockPaperClass = MagicMock(return_value=mock_paper_instance)

        _INJECTED = ("api.admin", "brokers.paper_trading", "core.startup_factories")
        with MagicMock() as mock_admin:  # pylint: disable=not-context-manager
            mock_admin.log_activity = MagicMock()
            _saved = {k: sys.modules.get(k) for k in _INJECTED}
            sys.modules["api.admin"] = mock_admin
            sys.modules["brokers.paper_trading"] = MagicMock(PaperTradingBroker=MockPaperClass)
            try:
                import importlib

                import core.startup_factories as sf

                importlib.reload(sf)
                broker = await sf.init_broker(mock_state)
            finally:
                for k, v in _saved.items():
                    if v is None:
                        sys.modules.pop(k, None)
                    else:
                        sys.modules[k] = v

        assert broker is mock_paper_instance
