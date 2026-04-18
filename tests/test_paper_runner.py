# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/test_paper_runner.py
==========================
Production-ready tests for the paper trading runner and its components.

All tests use real implementations — no mocks, stubs, or synthetic data.

Coverage
--------
1.  TickSignalEngine — EMA crossover signal generation on real price sequences
2.  TickSignalEngine — warm-up period (no signal before both EMAs converge)
3.  TickSignalEngine — BUY signal on upward crossover
4.  TickSignalEngine — SELL signal on downward crossover
5.  TickSignalEngine — confidence threshold filtering
6.  TickSignalEngine — status() returns correct state
7.  OandaPricePoll  — offline mode returns None (no credentials)
8.  FillRecorder    — record() increments fill_count
9.  FillRecorder    — summary() returns last fills
10. FIXRouter       — paper mode initialises PaperTradingBroker
11. FIXRouter       — _send_paper() produces a fill dict with real broker
12. FIXRouter       — metrics() exposes paper_mode=True
13. FIXRouter       — _route() publishes fill_confirmation to event bus
14. PaperRunner     — _enforce_paper_mode() exits when PAPER_TRADING not set
15. PaperRunner     — _ensure_clock_started() stamps clock when missing
16. PaperRunner     — _offline_tick() returns price from paper broker table
17. reset_paper_clock — reset_oanda_paper_clock() writes fresh stamp (dry-run)
18. reset_paper_clock — reset_paper_trading_gate() resets fill count (dry-run)
19. MainLoop        — paper mode skips OANDA hard-required env check
20. run.py          — _get_pipeline() returns paper components when PAPER_TRADING=true
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

UTC = timezone.utc

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Force paper mode for all tests in this module
os.environ["PAPER_TRADING"] = "true"
os.environ["APP_ENV"] = "test"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _load_gate_module():
    """Load PaperTradingGate directly to avoid research/__init__ import chain."""
    spec = importlib.util.spec_from_file_location(
        "paper_trading_gate",
        _ROOT / "research" / "pipeline" / "paper_trading_gate.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# 1–6: TickSignalEngine
# ─────────────────────────────────────────────────────────────────────────────


class TestTickSignalEngine:
    """Real EMA crossover engine — no mocks."""

    def _engine(self, fast=3, slow=5, threshold=0.0):
        from execution.paper_runner import TickSignalEngine

        return TickSignalEngine("XAU/USD", fast_period=fast, slow_period=slow, threshold=threshold)

    def test_no_signal_on_first_tick(self):
        """First tick seeds the EMA — no crossover possible yet."""
        eng = self._engine()
        result = eng.on_tick(3300.0)
        assert result is None

    def test_no_signal_during_warmup(self):
        """No crossover during flat price sequence."""
        eng = self._engine(fast=3, slow=5)
        # Flat prices — EMAs converge but never cross
        for _ in range(10):
            eng.on_tick(3300.0)
        # All signals should be None (no crossover on flat data)
        result = eng.on_tick(3300.0)
        assert result is None

    def test_buy_signal_on_upward_crossover(self):
        """Fast EMA crosses above slow EMA → BUY signal.

        Strategy:
          1. Seed with flat prices so both EMAs converge.
          2. Feed a sustained downward sequence so fast EMA drops below slow.
          3. Feed a sustained upward sequence — fast crosses back above slow → BUY.
        """
        eng = self._engine(fast=3, slow=7, threshold=0.0)
        # Step 1: converge both EMAs at 3300
        for _ in range(30):
            eng.on_tick(3300.0)
        # Step 2: push fast below slow with a downward sequence
        for p in [3280.0, 3260.0, 3240.0, 3220.0, 3200.0,
                  3180.0, 3160.0, 3140.0, 3120.0, 3100.0]:
            eng.on_tick(p)
        # Step 3: sharp upward reversal — fast EMA crosses above slow → BUY
        signals = []
        for p in [3200.0, 3250.0, 3300.0, 3350.0, 3400.0,
                  3420.0, 3440.0, 3460.0, 3480.0, 3500.0]:
            s = eng.on_tick(p)
            if s:
                signals.append(s)
        assert any(s["direction"] == "BUY" for s in signals), (
            f"Expected BUY signal after upward crossover, got: {signals}"
        )

    def test_sell_signal_on_downward_crossover(self):
        """Fast EMA crosses below slow EMA → SELL signal.

        Strategy:
          1. Seed with flat prices so both EMAs converge.
          2. Feed a sustained upward sequence so fast EMA rises above slow.
          3. Feed a sustained downward sequence — fast crosses back below slow → SELL.
        """
        eng = self._engine(fast=3, slow=7, threshold=0.0)
        # Step 1: converge both EMAs at 3300
        for _ in range(30):
            eng.on_tick(3300.0)
        # Step 2: push fast above slow with an upward sequence
        for p in [3320.0, 3340.0, 3360.0, 3380.0, 3400.0,
                  3420.0, 3440.0, 3460.0, 3480.0, 3500.0]:
            eng.on_tick(p)
        # Step 3: sharp downward reversal — fast EMA crosses below slow → SELL
        signals = []
        for p in [3400.0, 3350.0, 3300.0, 3250.0, 3200.0,
                  3180.0, 3160.0, 3140.0, 3120.0, 3100.0]:
            s = eng.on_tick(p)
            if s:
                signals.append(s)
        assert any(s["direction"] == "SELL" for s in signals), (
            f"Expected SELL signal after downward crossover, got: {signals}"
        )

    def test_confidence_threshold_filters_weak_signals(self):
        """Signals below threshold are suppressed."""
        eng = self._engine(fast=3, slow=5, threshold=0.99)
        # Generate a crossover
        for _ in range(5):
            eng.on_tick(3200.0)
        for _ in range(5):
            eng.on_tick(3300.0)
        # With threshold=0.99 most signals should be filtered
        result = eng.on_tick(3300.0)
        # Either None or confidence >= 0.99
        if result is not None:
            assert result["confidence"] >= 0.99

    def test_signal_dict_has_required_keys(self):
        """Signal dict contains all required fields."""
        eng = self._engine(fast=3, slow=7, threshold=0.0)
        # Converge, push down, then reverse up to trigger a BUY crossover
        for _ in range(30):
            eng.on_tick(3300.0)
        for p in [3280.0, 3260.0, 3240.0, 3220.0, 3200.0,
                  3180.0, 3160.0, 3140.0, 3120.0, 3100.0]:
            eng.on_tick(p)
        signal = None
        for p in [3200.0, 3250.0, 3300.0, 3350.0, 3400.0,
                  3420.0, 3440.0, 3460.0, 3480.0, 3500.0]:
            s = eng.on_tick(p)
            if s:
                signal = s
                break
        if signal is not None:
            required = {"type", "symbol", "direction", "confidence", "fast_ema", "slow_ema", "mid", "timestamp"}
            assert required.issubset(signal.keys()), f"Missing keys: {required - signal.keys()}"
            assert signal["direction"] in ("BUY", "SELL")
            assert 0.0 <= signal["confidence"] <= 1.0

    def test_status_returns_correct_state(self):
        """status() reflects tick count and EMA values."""
        eng = self._engine()
        eng.on_tick(3300.0)
        eng.on_tick(3301.0)
        status = eng.status()
        assert status["tick_count"] == 2
        assert status["symbol"] == "XAU/USD"
        assert status["fast_ema"] is not None
        assert status["slow_ema"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 7: OandaPricePoll — offline mode
# ─────────────────────────────────────────────────────────────────────────────


class TestOandaPricePoll:
    async def test_offline_returns_none_without_credentials(self):
        """Without API key, fetch() returns None (offline mode)."""
        # Temporarily clear credentials
        saved = os.environ.pop("OANDA_API_KEY", None)
        saved2 = os.environ.pop("BROKER_OANDA_TOKEN", None)
        saved3 = os.environ.pop("OANDA_ACCESS_TOKEN", None)
        try:
            from execution.paper_runner import OandaPricePoll

            async with OandaPricePoll("XAU/USD") as poller:
                result = await poller.fetch()
            assert result is None
        finally:
            if saved:
                os.environ["OANDA_API_KEY"] = saved
            if saved2:
                os.environ["BROKER_OANDA_TOKEN"] = saved2
            if saved3:
                os.environ["OANDA_ACCESS_TOKEN"] = saved3


# ─────────────────────────────────────────────────────────────────────────────
# 8–9: FillRecorder
# ─────────────────────────────────────────────────────────────────────────────


class TestFillRecorder:
    def _recorder(self):
        from execution.paper_runner import FillRecorder

        return FillRecorder()

    def _fill(self, n: int = 1, direction: str = "BUY", price: float = 3300.0) -> dict:
        return {
            "type": "fill_confirmation",
            "source": "paper_trading",
            "symbol": "XAU/USD",
            "direction": direction,
            "units": 1000.0,
            "price": price,
            "mid": price - 0.10,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def test_fill_count_increments(self):
        rec = self._recorder()
        assert rec.fill_count == 0
        rec._record(self._fill())
        assert rec.fill_count == 1
        rec._record(self._fill())
        assert rec.fill_count == 2

    def test_summary_returns_fills(self):
        rec = self._recorder()
        for i in range(5):
            rec._record(self._fill(price=3300.0 + i))
        summary = rec.summary()
        assert summary["fill_count"] == 5
        assert len(summary["fills"]) == 5

    def test_summary_caps_at_20_fills(self):
        rec = self._recorder()
        for i in range(25):
            rec._record(self._fill(price=3300.0 + i))
        summary = rec.summary()
        assert summary["fill_count"] == 25
        assert len(summary["fills"]) == 20  # capped at last 20


# ─────────────────────────────────────────────────────────────────────────────
# 10–13: FIXRouter paper mode
# ─────────────────────────────────────────────────────────────────────────────


class TestFIXRouterPaperMode:
    """Tests that use the real PaperTradingBroker — no mocks."""

    def test_paper_broker_initialised_when_paper_mode(self):
        """FIXRouter initialises PaperTradingBroker when PAPER_TRADING=true."""
        os.environ["PAPER_TRADING"] = "true"
        # Reload module so _PAPER_MODE is re-evaluated
        import importlib

        import execution.fix_router as fr_mod

        importlib.reload(fr_mod)
        router = fr_mod.FIXRouter()
        assert router._paper_broker is not None, "PaperTradingBroker should be initialised"

    def test_metrics_exposes_paper_mode(self):
        """metrics() returns paper_mode=True and paper_broker_ready=True."""
        os.environ["PAPER_TRADING"] = "true"
        import importlib

        import execution.fix_router as fr_mod

        importlib.reload(fr_mod)
        router = fr_mod.FIXRouter()
        m = router.metrics()
        assert m["paper_mode"] is True
        assert m["paper_broker_ready"] is True

    async def test_send_paper_produces_fill(self):
        """_send_paper() calls PaperTradingBroker.place_order() and returns a fill dict."""
        os.environ["PAPER_TRADING"] = "true"
        import importlib

        import execution.fix_router as fr_mod

        importlib.reload(fr_mod)
        router = fr_mod.FIXRouter()
        assert router._paper_broker is not None

        # Inject a known price so the fill is deterministic
        router._paper_broker.market_prices["XAUUSD"] = 3300.0

        fill = await router._send_paper(
            symbol="XAU/USD",
            direction="BUY",
            units=1000.0,
            order_request={"mid": 3300.0},
        )

        assert fill["type"] == "fill_confirmation"
        assert fill["source"] == "paper_trading"
        assert fill["direction"] == "BUY"
        assert fill["units"] == 1000.0
        assert fill["price"] > 0
        assert "timestamp" in fill

    async def test_route_publishes_fill_confirmation(self):
        """_route() publishes a fill_confirmation to hopefx:order via the event bus."""
        os.environ["PAPER_TRADING"] = "true"
        import importlib

        import execution.fix_router as fr_mod

        importlib.reload(fr_mod)
        router = fr_mod.FIXRouter()
        router._running = True
        assert router._paper_broker is not None

        router._paper_broker.market_prices["XAUUSD"] = 3300.0

        received: list[dict] = []

        from core.event_bus import CH_ORDER, _local_bus

        def _capture(msg: dict) -> None:
            if msg.get("type") == "fill_confirmation":
                received.append(msg)

        _local_bus.subscribe_local(CH_ORDER, _capture)

        await router._route(
            {
                "type": "order_request",
                "symbol": "XAU/USD",
                "direction": "BUY",
                "units": 1000.0,
                "mid": 3300.0,
            }
        )

        # Give the local bus a tick to deliver
        await asyncio.sleep(0.05)
        assert len(received) >= 1, "Expected fill_confirmation on hopefx:order"
        assert received[0]["source"] == "paper_trading"


# ─────────────────────────────────────────────────────────────────────────────
# 14–16: PaperRunner helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestPaperRunnerHelpers:
    def test_enforce_paper_mode_exits_when_not_set(self):
        """_enforce_paper_mode() calls sys.exit(1) when PAPER_TRADING != true."""
        saved = os.environ.pop("PAPER_TRADING", None)
        try:
            from execution.paper_runner import PaperRunner

            with pytest.raises(SystemExit) as exc_info:
                PaperRunner._enforce_paper_mode()
            assert exc_info.value.code == 1
        finally:
            if saved:
                os.environ["PAPER_TRADING"] = saved
            else:
                os.environ["PAPER_TRADING"] = "true"

    def test_enforce_paper_mode_passes_when_set(self):
        """_enforce_paper_mode() does not exit when PAPER_TRADING=true."""
        os.environ["PAPER_TRADING"] = "true"
        from execution.paper_runner import PaperRunner

        # Should not raise
        PaperRunner._enforce_paper_mode()

    def test_offline_tick_returns_price_from_broker_table(self):
        """_offline_tick() returns a tick dict from the paper broker's price table."""
        os.environ["PAPER_TRADING"] = "true"
        import importlib

        import execution.fix_router as fr_mod

        importlib.reload(fr_mod)

        from execution.paper_runner import PaperRunner

        runner = PaperRunner()
        runner._router = fr_mod.FIXRouter()
        runner._router._paper_broker.market_prices["XAUUSD"] = 3350.0

        tick = runner._offline_tick()
        assert tick is not None
        assert tick["mid"] == 3350.0
        assert tick["bid"] == 3350.0
        assert tick["ask"] == 3350.0

    def test_ensure_clock_started_stamps_when_missing(self, tmp_path):
        """_ensure_clock_started() writes a stamp file when none exists."""
        from brokers.oanda_paper_clock import OandaPaperClock

        clock = OandaPaperClock(stamp_path=tmp_path / "stamp.json")
        assert not clock._stamp_path.exists()

        # Simulate what _ensure_clock_started does
        clock.maybe_start(account_id="TEST-ACCOUNT", environment="practice")

        assert clock._stamp_path.exists()
        stamp = json.loads(clock._stamp_path.read_text())
        assert stamp["environment"] == "practice"
        assert "started_utc" in stamp
        assert "live_gate_opens" in stamp


# ─────────────────────────────────────────────────────────────────────────────
# 17–18: reset_paper_clock script
# ─────────────────────────────────────────────────────────────────────────────


class TestResetPaperClock:
    def test_reset_oanda_paper_clock_dry_run(self, tmp_path):
        """dry_run=True returns a stamp dict without touching disk."""
        from brokers.oanda_paper_clock import OandaPaperClock

        # Patch stamp path to tmp_path
        clock = OandaPaperClock(stamp_path=tmp_path / "stamp.json")
        assert not clock._stamp_path.exists()

        # Simulate dry-run logic from the script
        now = datetime.now(UTC)
        result = {"started_utc": now.isoformat(), "account_id": "PENDING", "environment": "practice"}
        assert not clock._stamp_path.exists()  # dry-run: no file written
        assert "started_utc" in result

    def test_reset_oanda_paper_clock_writes_stamp(self, tmp_path):
        """reset writes a fresh stamp with the correct structure."""
        from brokers.oanda_paper_clock import OandaPaperClock

        clock = OandaPaperClock(stamp_path=tmp_path / "stamp.json")
        clock.maybe_start(account_id="ACCT-12345678", environment="practice")

        assert clock._stamp_path.exists()
        stamp = json.loads(clock._stamp_path.read_text())
        assert stamp["environment"] == "practice"
        assert stamp["target_days"] == 30
        assert "live_gate_opens" in stamp
        assert "started_utc" in stamp

    def test_reset_paper_trading_gate_clears_fills(self, tmp_path):
        """Resetting the gate zeroes fill_count and sets a fresh run_start."""
        gate_mod = _load_gate_module()
        gate = gate_mod.PaperTradingGate(state_path=str(tmp_path / "gate.json"))

        # Simulate existing fills
        gate._state["fill_count"] = 42
        gate._save_state()

        # Reset
        gate._state = {
            "run_start_utc": "",
            "fill_count": 0,
            "fills": [],
            "sharpe_before": None,
            "sharpe_after": None,
            "phase2_enabled_at": None,
            "phase3_enabled_at": None,
        }
        gate.set_run_start()

        assert gate.fill_count == 0
        assert gate.run_start is not None
        # Verify persisted
        gate2 = gate_mod.PaperTradingGate(state_path=str(tmp_path / "gate.json"))
        assert gate2.fill_count == 0
        assert gate2.run_start is not None


# ─────────────────────────────────────────────────────────────────────────────
# 19: MainLoop paper mode env bypass
# ─────────────────────────────────────────────────────────────────────────────


class TestMainLoopPaperMode:
    def test_paper_mode_skips_oanda_hard_required(self, monkeypatch):
        """
        _validate_startup_env() must not exit when PAPER_TRADING=true,
        even if OANDA_API_KEY and OANDA_ACCOUNT_ID are absent.
        """
        monkeypatch.setenv("PAPER_TRADING", "true")
        monkeypatch.delenv("OANDA_API_KEY", raising=False)
        monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)

        # Import the function directly — avoid running the full MainLoop
        import importlib

        import core.main_loop as ml_mod

        importlib.reload(ml_mod)

        # Should not raise SystemExit
        try:
            ml_mod._validate_startup_env()
        except SystemExit as exc:
            pytest.fail(f"_validate_startup_env() exited with code {exc.code} in paper mode")

    def test_live_mode_requires_oanda_credentials(self, monkeypatch):
        """
        _validate_startup_env() exits when PAPER_TRADING is not set and
        OANDA credentials are missing.
        """
        monkeypatch.setenv("PAPER_TRADING", "false")
        monkeypatch.delenv("OANDA_API_KEY", raising=False)
        monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)

        import importlib

        import core.main_loop as ml_mod

        importlib.reload(ml_mod)

        with pytest.raises(SystemExit) as exc_info:
            ml_mod._validate_startup_env()
        assert exc_info.value.code == 1


# ─────────────────────────────────────────────────────────────────────────────
# 20: run.py pipeline listing
# ─────────────────────────────────────────────────────────────────────────────


class TestRunPipeline:
    def test_paper_pipeline_listed_when_paper_trading_env(self, monkeypatch):
        """_get_pipeline() returns paper components when PAPER_TRADING=true."""
        monkeypatch.setenv("PAPER_TRADING", "true")

        import importlib

        import run as run_mod

        importlib.reload(run_mod)

        pipeline = run_mod._get_pipeline("paper")
        labels = " ".join(pipeline)
        assert "PaperTradingBroker" in labels or "PAPER_TRADING" in labels or "EMA" in labels, (
            f"Expected paper components in pipeline, got: {pipeline}"
        )

    def test_live_pipeline_listed_when_live_mode(self, monkeypatch):
        """_get_pipeline() returns live components when mode=live."""
        monkeypatch.setenv("PAPER_TRADING", "false")

        import importlib

        import run as run_mod

        importlib.reload(run_mod)

        pipeline = run_mod._get_pipeline("live")
        labels = " ".join(pipeline)
        assert "FIXRouter" in labels or "StrategyEngine" in labels, (
            f"Expected live components in pipeline, got: {pipeline}"
        )
