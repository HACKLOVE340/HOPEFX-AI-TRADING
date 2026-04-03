# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/test_connect_to_life.py
==============================
Unit tests for connect_to_life.py supervisor logic.

All tests run fully offline — no OANDA connection, no Telegram, no Redis.
HopeFXEngine is mocked so the supervisor logic is tested in isolation.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
UTC = timezone.utc
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the supervisor components directly
from connect_to_life import (
    DD_HARD_STOP_PCT,
    POLL_INTERVAL,
    DailyReporter,
    LifeSupervisor,
    _telegram,
)

# ─────────────────────────────────────────────────────────────────────────────
# Telegram helper
# ─────────────────────────────────────────────────────────────────────────────


class TestTelegramHelper:
    """_telegram silently swallows errors and skips when no token/chat."""

    @pytest.mark.asyncio
    async def test_no_op_when_token_empty(self):
        """No network call when token is empty."""
        # Should not raise even with no aiohttp available
        await _telegram("", "123", "hello")

    @pytest.mark.asyncio
    async def test_no_op_when_chat_empty(self):
        await _telegram("token", "", "hello")

    @pytest.mark.asyncio
    async def test_swallows_network_error(self):
        """aiohttp errors must not propagate."""
        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(side_effect=OSError("network down"))
            # Should not raise
            await _telegram("tok", "chat", "msg")


# ─────────────────────────────────────────────────────────────────────────────
# DailyReporter
# ─────────────────────────────────────────────────────────────────────────────


class TestDailyReporter:
    """DailyReporter sends at most one message per calendar day."""

    @pytest.mark.asyncio
    async def test_does_not_send_outside_midnight_hour(self):
        reporter = DailyReporter("tok", "chat")
        sent = []

        async def fake_telegram(token, chat, text):
            sent.append(text)

        # Simulate hour != 0
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        with patch("connect_to_life.datetime") as mock_dt, patch("connect_to_life._telegram", fake_telegram):
            mock_dt.now.return_value = now
            await reporter.maybe_send({"equity": 100_000})

        assert sent == []

    @pytest.mark.asyncio
    async def test_sends_once_at_midnight(self):
        reporter = DailyReporter("tok", "chat")
        sent = []

        async def fake_telegram(token, chat, text):
            sent.append(text)

        now = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        with patch("connect_to_life.datetime") as mock_dt, patch("connect_to_life._telegram", fake_telegram):
            mock_dt.now.return_value = now
            await reporter.maybe_send(
                {
                    "equity": 100_000,
                    "balance": 100_000,
                    "daily_pnl": 250.0,
                    "drawdown_pct": 0.5,
                    "fill_count": 3,
                    "broker": "oanda",
                }
            )

        assert len(sent) == 1
        assert "Daily Report" in sent[0]
        assert "250" in sent[0]

    @pytest.mark.asyncio
    async def test_does_not_send_twice_same_day(self):
        reporter = DailyReporter("tok", "chat")
        sent = []

        async def fake_telegram(token, chat, text):
            sent.append(text)

        now = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        with patch("connect_to_life.datetime") as mock_dt, patch("connect_to_life._telegram", fake_telegram):
            mock_dt.now.return_value = now
            await reporter.maybe_send({"equity": 100_000})
            await reporter.maybe_send({"equity": 100_000})  # second call same day

        assert len(sent) == 1


# ─────────────────────────────────────────────────────────────────────────────
# LifeSupervisor._read_status
# ─────────────────────────────────────────────────────────────────────────────


class TestReadStatus:
    """_read_status returns safe defaults when engine is not ready."""

    def _make_supervisor(self) -> LifeSupervisor:
        with patch.dict(
            os.environ,
            {
                "OANDA_API_KEY": "test",
                "OANDA_ACCOUNT_ID": "test",
                "INITIAL_BALANCE": "50000",
            },
        ):
            return LifeSupervisor()

    def test_returns_defaults_when_engine_none(self):
        sup = self._make_supervisor()
        sup._engine = None
        status = sup._read_status()
        assert status["equity"] == 50_000.0
        assert status["drawdown_pct"] == 0.0
        assert status["fill_count"] == 0

    def test_returns_defaults_when_get_status_raises(self):
        sup = self._make_supervisor()
        mock_engine = MagicMock()
        mock_engine._get_status.side_effect = RuntimeError("engine not ready")
        sup._engine = mock_engine
        status = sup._read_status()
        assert status["equity"] == 50_000.0

    def test_merges_fill_count_from_trade_logger(self):
        sup = self._make_supervisor()
        mock_engine = MagicMock()
        mock_engine._get_status.return_value = {
            "equity": 102_000.0,
            "balance": 100_000.0,
            "daily_pnl": 2_000.0,
            "drawdown_pct": 0.0,
            "open_positions": 1,
            "broker": "oanda",
        }
        mock_tl = MagicMock()
        mock_tl.stats = {"fill_count": 7}
        mock_engine._trade_logger = mock_tl
        sup._engine = mock_engine

        status = sup._read_status()
        assert status["equity"] == 102_000.0
        assert status["fill_count"] == 7

    def test_returns_engine_status_when_healthy(self):
        sup = self._make_supervisor()
        mock_engine = MagicMock()
        mock_engine._get_status.return_value = {
            "equity": 98_000.0,
            "balance": 100_000.0,
            "daily_pnl": -2_000.0,
            "drawdown_pct": 2.0,
            "open_positions": 0,
            "broker": "paper",
        }
        mock_engine._trade_logger = None
        sup._engine = mock_engine

        status = sup._read_status()
        assert status["drawdown_pct"] == 2.0
        assert status["broker"] == "paper"


# ─────────────────────────────────────────────────────────────────────────────
# LifeSupervisor._breach_shutdown
# ─────────────────────────────────────────────────────────────────────────────


class TestBreachShutdown:
    """_breach_shutdown sets exit_code=1, fires Telegram, sets shutdown event."""

    def _make_supervisor(self) -> LifeSupervisor:
        with patch.dict(
            os.environ,
            {
                "OANDA_API_KEY": "test",
                "OANDA_ACCOUNT_ID": "test",
            },
        ):
            return LifeSupervisor()

    @pytest.mark.asyncio
    async def test_sets_exit_code_1(self):
        sup = self._make_supervisor()
        with patch("connect_to_life._telegram", AsyncMock()):
            await sup._breach_shutdown(0.04)
        assert sup._exit_code == 1

    @pytest.mark.asyncio
    async def test_sets_shutdown_event(self):
        sup = self._make_supervisor()
        with patch("connect_to_life._telegram", AsyncMock()):
            await sup._breach_shutdown(0.04)
        assert sup._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_sends_telegram_alert(self):
        sup = self._make_supervisor()
        sent = []

        async def fake_tg(token, chat, text):
            sent.append(text)

        with patch("connect_to_life._telegram", fake_tg):
            await sup._breach_shutdown(0.035)

        assert len(sent) == 1
        assert "AUTO-STOP" in sent[0]
        assert "3.50%" in sent[0]


# ─────────────────────────────────────────────────────────────────────────────
# LifeSupervisor._checkpoint
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckpoint:
    """_checkpoint writes valid JSON to CHECKPOINT_FILE."""

    def _make_supervisor(self) -> LifeSupervisor:
        with patch.dict(
            os.environ,
            {
                "OANDA_API_KEY": "test",
                "OANDA_ACCOUNT_ID": "test",
                "INITIAL_BALANCE": "100000",
            },
        ):
            return LifeSupervisor()

    @pytest.mark.asyncio
    async def test_writes_json_file(self, tmp_path):
        sup = self._make_supervisor()
        sup._engine = None  # no engine — uses defaults

        checkpoint_path = tmp_path / "state" / "connect_to_life_checkpoint.json"
        with patch("connect_to_life.CHECKPOINT_FILE", str(checkpoint_path)):
            await sup._checkpoint()

        assert checkpoint_path.exists()
        data = json.loads(checkpoint_path.read_text())
        assert "timestamp" in data
        assert "equity" in data
        assert "exit_code" in data

    @pytest.mark.asyncio
    async def test_checkpoint_contains_correct_exit_code(self, tmp_path):
        sup = self._make_supervisor()
        sup._exit_code = 1
        sup._engine = None

        checkpoint_path = tmp_path / "state" / "ctl_checkpoint.json"
        with patch("connect_to_life.CHECKPOINT_FILE", str(checkpoint_path)):
            await sup._checkpoint()

        data = json.loads(checkpoint_path.read_text())
        assert data["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_checkpoint_survives_write_error(self, tmp_path):
        """OSError during write must not propagate."""
        sup = self._make_supervisor()
        sup._engine = None

        with patch("builtins.open", side_effect=OSError("disk full")):
            # Should not raise
            await sup._checkpoint()


# ─────────────────────────────────────────────────────────────────────────────
# LifeSupervisor._on_engine_done
# ─────────────────────────────────────────────────────────────────────────────


class TestOnEngineDone:
    """_on_engine_done sets shutdown event and exit code correctly."""

    def _make_supervisor(self) -> LifeSupervisor:
        with patch.dict(
            os.environ,
            {
                "OANDA_API_KEY": "test",
                "OANDA_ACCOUNT_ID": "test",
            },
        ):
            return LifeSupervisor()

    def test_cancelled_task_does_not_set_exit_code_1(self):
        sup = self._make_supervisor()
        task = MagicMock()
        task.cancelled.return_value = True
        task.exception.side_effect = asyncio.CancelledError()
        sup._on_engine_done(task)
        assert sup._exit_code == 0

    def test_exception_task_sets_exit_code_1_and_shutdown(self):
        sup = self._make_supervisor()
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = RuntimeError("broker disconnected")
        sup._on_engine_done(task)
        assert sup._exit_code == 1
        assert sup._shutdown_event.is_set()

    def test_normal_completion_sets_shutdown(self):
        sup = self._make_supervisor()
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None
        sup._on_engine_done(task)
        assert sup._shutdown_event.is_set()
        assert sup._exit_code == 0


# ─────────────────────────────────────────────────────────────────────────────
# DD_HARD_STOP_PCT constant
# ─────────────────────────────────────────────────────────────────────────────


class TestConstants:
    def test_default_dd_hard_stop_is_3_percent(self):
        # Default must be 3% — changing this affects live risk management
        assert pytest.approx(0.03) == DD_HARD_STOP_PCT

    def test_poll_interval_is_positive(self):
        assert POLL_INTERVAL > 0
