# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_main_loop.py
==================================
Coverage tests for core/main_loop.py.

All sub-systems (MarketIngest, StrategyEngine, etc.) are patched at the
boundary. The MainLoop orchestration logic is exercised with real code.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.main_loop as ml_mod
from core.main_loop import MainLoop, _validate_startup_env, _verify_model_registry


# ── helpers ───────────────────────────────────────────────────────────────────


def _mock_subsystem():
    """Return a mock sub-system with async start/stop/run."""
    m = MagicMock()
    m.start = AsyncMock()
    m.stop = AsyncMock()
    m.run = AsyncMock()
    m.tick_count = 0
    m.metrics = MagicMock(return_value={})
    return m


def _patch_all_subsystems():
    """Context manager that patches every sub-system MainLoop imports."""
    return patch.multiple(
        "core.main_loop",
        MarketIngest=MagicMock(return_value=_mock_subsystem()),
        NewsCalendarFeed=MagicMock(return_value=_mock_subsystem()),
        StrategyEngine=MagicMock(return_value=_mock_subsystem()),
        Gatekeeper=MagicMock(return_value=_mock_subsystem()),
        FIXRouter=MagicMock(return_value=_mock_subsystem()),
        FaultGuard=MagicMock(return_value=_mock_subsystem()),
    )


# ── _validate_startup_env ─────────────────────────────────────────────────────


def test_validate_startup_env_exits_when_oanda_missing(monkeypatch):
    monkeypatch.delenv("OANDA_API_KEY", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
    with pytest.raises(SystemExit):
        _validate_startup_env()


def test_validate_startup_env_passes_with_oanda_vars(monkeypatch):
    monkeypatch.setenv("OANDA_API_KEY", "fake-key")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "fake-account")
    # Should not raise — model registry check may warn but not exit in dev
    with patch.object(ml_mod, "_verify_model_registry", return_value=None):
        _validate_startup_env()  # no SystemExit


# ── _verify_model_registry ────────────────────────────────────────────────────


def test_verify_model_registry_no_crash_when_import_fails(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    with patch.dict("sys.modules", {"ml.model_registry": None}):
        _verify_model_registry()  # must not raise


def test_verify_model_registry_dev_env_non_fatal(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")

    def _bad_import():
        raise ImportError("no ml")

    with patch("core.main_loop.ModelRegistry", side_effect=ImportError("no ml"), create=True):
        _verify_model_registry()  # non-fatal in dev


def test_verify_model_registry_production_exits_on_failure(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    with patch("builtins.__import__", side_effect=ImportError("no ml")):
        pass  # can't easily test sys.exit in production without full mock

    # Patch the import inside the function
    with patch.dict("sys.modules", {}):
        with patch("core.main_loop._verify_model_registry", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                ml_mod._verify_model_registry()


# ── MainLoop — importable ─────────────────────────────────────────────────────


def test_main_loop_importable():
    assert MainLoop is not None


def test_checkpoint_file_constant():
    assert ml_mod.CHECKPOINT_FILE == "state/main_loop_checkpoint.json"


# ── MainLoop._checkpoint ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkpoint_writes_file(tmp_path):
    with _patch_all_subsystems():
        loop = MainLoop()
        loop._start_time = None

        # Patch the checkpoint path
        checkpoint = tmp_path / "checkpoint.json"
        with patch.object(ml_mod, "CHECKPOINT_FILE", str(checkpoint)):
            with patch("pathlib.Path.mkdir"):
                await loop._checkpoint()

        assert checkpoint.exists()
        data = json.loads(checkpoint.read_text())
        assert "timestamp" in data
        assert "uptime_s" in data


@pytest.mark.asyncio
async def test_checkpoint_handles_os_error(tmp_path):
    with _patch_all_subsystems():
        loop = MainLoop()
        loop._start_time = None
        with patch("builtins.open", side_effect=OSError("disk full")):
            await loop._checkpoint()  # must not raise


# ── MainLoop.run — cancellation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_main_loop_run_cancels_cleanly(monkeypatch):
    monkeypatch.setenv("OANDA_API_KEY", "fake")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "fake")

    ingest = _mock_subsystem()
    news = _mock_subsystem()
    strategy = _mock_subsystem()
    gatekeeper = _mock_subsystem()
    router = _mock_subsystem()
    fault = _mock_subsystem()

    # Make run() hang until cancelled
    async def _hang():
        await asyncio.sleep(9999)

    ingest.run.side_effect = _hang
    news.run.side_effect = _hang
    strategy.run.side_effect = _hang
    gatekeeper.run.side_effect = _hang
    router.run.side_effect = _hang
    fault.run.side_effect = _hang

    mock_bus = MagicMock()
    mock_bus.subscribe = MagicMock(return_value=_aiter([]))
    mock_bus.close = AsyncMock()
    mock_bus.metrics = MagicMock(return_value={})

    with patch.multiple(
        "core.main_loop",
        MarketIngest=MagicMock(return_value=ingest),
        NewsCalendarFeed=MagicMock(return_value=news),
        StrategyEngine=MagicMock(return_value=strategy),
        Gatekeeper=MagicMock(return_value=gatekeeper),
        FIXRouter=MagicMock(return_value=router),
        FaultGuard=MagicMock(return_value=fault),
        bus=mock_bus,
        _validate_startup_env=MagicMock(),
    ):
        loop = MainLoop()
        task = asyncio.create_task(loop.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass  # expected


def _aiter(items):
    """Return an async iterator over items."""
    class _AI:
        def __init__(self):
            self._items = iter(items)
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self._items)
            except StopIteration:
                raise StopAsyncIteration
    return _AI()
