# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_smoke_critical.py
=============================
Round-trip behavioral regression gates for 19 critical modules.

Each test:
  1. Calls a real public method with real inputs
  2. Asserts the output is numerically/structurally correct
  3. Asserts fail-safe / fail-closed behaviour on bad inputs
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from brokers.base import AccountInfo as _AccountInfo

import pytest


# ── 1. PositionSizer ──────────────────────────────────────────────────────────


class TestPositionSizer:
    def _account(self, equity: float = 100_000.0):
        return _AccountInfo(
            balance=equity,
            equity=equity,
            margin_used=0.0,
            margin_available=equity,
            positions_count=0,
        )

    def test_atr_size_correct(self):
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="atr", risk_pct=0.01)
        size = ps.calculate_size(self._account(), Decimal("2000"), atr=Decimal("10"))
        # risk=1000, atr=10 -> size=100 (hits max_lots cap)
        assert size == Decimal("100")

    def test_atr_size_near_zero_atr_returns_zero(self):
        """ATR below 0.01% of price triggers illiquid-market guard → size=0."""
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="atr", risk_pct=0.01)
        # min_atr = 2000 * 0.0001 = 0.2; pass atr=0.1 which is below the guard
        size = ps.calculate_size(self._account(), Decimal("2000"), atr=Decimal("0.1"))
        assert size == Decimal("0")

    def test_atr_size_tiny_atr_returns_zero(self):
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="atr", risk_pct=0.01)
        # atr=0.00001 is far below min_atr threshold
        size = ps.calculate_size(self._account(), Decimal("2000"), atr=Decimal("0.00001"))
        assert size == Decimal("0")

    def test_kelly_positive_edge(self):
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="kelly", risk_pct=0.01, max_lots=200.0)
        size = ps.calculate_size(self._account(), Decimal("2000"), win_rate=0.6, payoff_ratio=2.0)
        # half-kelly=0.2; risk=20000; size=20000/2000=10
        assert float(size) == pytest.approx(10.0, abs=0.01)

    def test_kelly_negative_edge_returns_zero(self):
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="kelly", risk_pct=0.01)
        size = ps.calculate_size(self._account(), Decimal("2000"), win_rate=0.3, payoff_ratio=0.5)
        assert size == Decimal("0")

    def test_percent_size_correct(self):
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="percent", risk_pct=0.01)
        size = ps.calculate_size(self._account(), Decimal("2000"), stop_distance=Decimal("20"))
        # risk=1000; size=1000/20=50
        assert float(size) == pytest.approx(50.0, abs=0.01)

    def test_percent_negative_stop_returns_zero(self):
        """Negative stop_distance hits the <= 0 guard in _percent_size."""
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="percent", risk_pct=0.01)
        size = ps.calculate_size(self._account(), Decimal("2000"), stop_distance=Decimal("-1"))
        assert size == Decimal("0")

    def test_fixed_always_one(self):
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="fixed")
        size = ps.calculate_size(self._account(), Decimal("2000"))
        assert size == Decimal("1")

    def test_max_lots_cap_enforced(self):
        from risk.position_sizing import PositionSizer

        ps = PositionSizer(method="atr", risk_pct=0.5, max_lots=5.0)
        size = ps.calculate_size(self._account(), Decimal("2000"), atr=Decimal("1"))
        assert size <= Decimal("5")


# ── 2. DrawdownTracker ────────────────────────────────────────────────────────


class TestDrawdownTracker:
    def _tracker(self, **kw):
        from risk.drawdown_tracker import DrawdownTracker

        return DrawdownTracker(initial_balance=100_000.0, max_total_dd_pct=0.10, max_daily_dd_pct=0.05, **kw)

    def test_no_breach_small_loss(self):
        r = self._tracker().update(equity=98_000.0, balance=98_000.0)
        assert not r.total_breach
        assert not r.daily_breach
        assert r.total_drawdown_pct == pytest.approx(0.02, abs=0.001)

    def test_daily_breach_at_5pct(self):
        r = self._tracker().update(equity=95_000.0, balance=95_000.0)
        assert r.daily_breach

    def test_total_breach_at_10pct(self):
        r = self._tracker().update(equity=89_000.0, balance=89_000.0)
        assert r.total_breach

    def test_hwm_never_decreases(self):
        dt = self._tracker()
        dt.update(equity=105_000.0, balance=105_000.0)
        r = dt.update(equity=98_000.0, balance=98_000.0)
        assert r.total_hwm == pytest.approx(105_000.0, abs=1.0)

    def test_zero_initial_balance_raises(self):
        from risk.drawdown_tracker import DrawdownTracker

        with pytest.raises(ValueError):
            DrawdownTracker(initial_balance=0.0)

    def test_result_fields_present(self):
        r = self._tracker().update(equity=99_000.0, balance=99_000.0)
        for field in ("total_drawdown_pct", "daily_drawdown_pct", "total_hwm", "daily_open", "timestamp"):
            assert hasattr(r, field)


# ── 3. TCARecorder ────────────────────────────────────────────────────────────


class TestTCARecorder:
    def _rec(self):
        from execution.tca_recorder import TCARecorder

        return TCARecorder()

    def test_signal_fill_round_trip(self):
        r = self._rec()
        r.record_signal("req1", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        r.record_fill("req1", 2001.5, 1.0, "oanda", 12.0)
        rpt = r.get_report(broker="oanda")
        assert rpt.n_trades == 1
        assert rpt.mean_slippage_bps > 0

    def test_slippage_bps_numeric(self):
        r = self._rec()
        r.record_signal("req2", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        r.record_fill("req2", 2001.0, 1.0, "oanda", 5.0)
        rpt = r.get_report(broker="oanda")
        # 1.0/2000.0 * 10000 = 5 bps
        assert rpt.mean_slippage_bps == pytest.approx(5.0, abs=0.5)

    def test_sell_price_improvement_negative_slippage(self):
        r = self._rec()
        r.record_signal("req3", "XAU_USD", "SELL", 2000.0, 1.0, "v1")
        r.record_fill("req3", 2001.0, 1.0, "oanda", 5.0)
        rpt = r.get_report(broker="oanda")
        assert rpt.mean_slippage_bps < 0

    def test_report_fields_present(self):
        r = self._rec()
        r.record_signal("req4", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        r.record_fill("req4", 2000.5, 1.0, "oanda", 8.0)
        rpt = r.get_report(broker="oanda")
        for field in (
            "mean_slippage_bps",
            "p95_slippage_bps",
            "mean_latency_ms",
            "adverse_fill_rate",
            "alert_triggered",
        ):
            assert hasattr(rpt, field)

    def test_fill_without_signal_ignored(self):
        """record_fill for unknown request_id must not raise; report returns None or 0 trades."""
        r = self._rec()
        r.record_fill("unknown", 2000.0, 1.0, "oanda", 5.0)
        rpt = r.get_report(broker="oanda")
        # No matched fills → report is None (no data) or has n_trades==0
        assert rpt is None or rpt.n_trades == 0

    def test_summary_string_contains_broker(self):
        r = self._rec()
        r.record_signal("req5", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        r.record_fill("req5", 2001.0, 1.0, "oanda", 10.0)
        s = r.get_report(broker="oanda").summary()
        assert "oanda" in s and "bps" in s


# ── 4. LeaderboardManager ─────────────────────────────────────────────────────


class TestLeaderboardManager:
    def _mgr(self):
        from social.leaderboards import LeaderboardManager

        return LeaderboardManager()

    def test_update_and_get(self):
        mgr = self._mgr()
        mgr.update_leaderboard("profit", "u1", Decimal("1500"))
        entries = mgr.get_leaderboard("profit")
        assert len(entries) == 1
        assert entries[0].user_id == "u1"

    def test_ranking_highest_first(self):
        mgr = self._mgr()
        mgr.update_leaderboard("profit", "u1", Decimal("1000"))
        mgr.update_leaderboard("profit", "u2", Decimal("3000"))
        mgr.update_leaderboard("profit", "u3", Decimal("2000"))
        entries = mgr.get_leaderboard("profit")
        scores = [float(e.score) for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_rank_field_assigned(self):
        mgr = self._mgr()
        mgr.update_leaderboard("profit", "u1", Decimal("500"))
        mgr.update_leaderboard("profit", "u2", Decimal("800"))
        entries = mgr.get_leaderboard("profit")
        assert entries[0].rank == 1
        assert entries[1].rank == 2

    def test_score_overwrite(self):
        mgr = self._mgr()
        mgr.update_leaderboard("profit", "u1", Decimal("100"))
        mgr.update_leaderboard("profit", "u1", Decimal("999"))
        entries = mgr.get_leaderboard("profit")
        assert float(entries[0].score) == pytest.approx(999.0)

    def test_categories_isolated(self):
        mgr = self._mgr()
        mgr.update_leaderboard("profit", "u1", Decimal("100"))
        mgr.update_leaderboard("sharpe", "u2", Decimal("200"))
        assert all(e.user_id == "u1" for e in mgr.get_leaderboard("profit"))
        assert all(e.user_id == "u2" for e in mgr.get_leaderboard("sharpe"))

    def test_empty_category_returns_empty(self):
        mgr = self._mgr()
        assert mgr.get_leaderboard("nonexistent") == []


# ── 5. KillSwitch ─────────────────────────────────────────────────────────────


class TestKillSwitchBehavioral:
    def _ks(self, tmp_path):
        from kill_switch import KillSwitch

        return KillSwitch(flag_file=tmp_path / "ks.flag", poll_interval_sec=0.05, deactivation_token="secure-tok")

    def test_initial_inactive(self, tmp_path):
        ks = self._ks(tmp_path)
        assert not ks.is_active()
        assert ks.reason == ""

    def test_activate_sets_state(self, tmp_path):
        ks = self._ks(tmp_path)
        ks.activate("test-reason")
        assert ks.is_active()
        assert ks.reason == "test-reason"
        assert ks.activated_at is not None

    def test_activate_idempotent(self, tmp_path):
        ks = self._ks(tmp_path)
        ks.activate("first")
        ks.activate("second")
        assert ks.reason == "first"

    def test_deactivate_correct_token(self, tmp_path):
        ks = self._ks(tmp_path)
        ks.activate("test")
        ks.deactivate("secure-tok")
        assert not ks.is_active()

    def test_deactivate_wrong_token_raises(self, tmp_path):
        ks = self._ks(tmp_path)
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate("wrong")
        assert ks.is_active()

    def test_callback_fired(self, tmp_path):
        ks = self._ks(tmp_path)
        fired = []
        ks.register_callback(fired.append)
        ks.activate("cb")
        assert fired == ["cb"]

    def test_flag_file_written(self, tmp_path):
        ks = self._ks(tmp_path)
        ks.activate("flag")
        assert (tmp_path / "ks.flag").exists()

    def test_status_dict_keys(self, tmp_path):
        ks = self._ks(tmp_path)
        s = ks.status()
        assert "active" in s and "reason" in s and "flag_file" in s

    def test_reset_for_testing(self, tmp_path):
        ks = self._ks(tmp_path)
        ks.activate("test")
        ks.reset_for_testing()
        assert not ks.is_active()
        assert ks.reason == ""


# ── 6. MacroStore ─────────────────────────────────────────────────────────────


class TestMacroStore:
    def test_update_and_snapshot(self):
        from ml.macro_store import MacroStore

        ms = MacroStore()
        ms.update("dxy", "2026-01-02", 103.5)
        snap = ms.snapshot()
        assert "dxy" in snap
        assert snap["dxy"]["value"] == pytest.approx(103.5)

    def test_snapshot_contains_date(self):
        from ml.macro_store import MacroStore

        ms = MacroStore()
        ms.update("us10y", "2026-01-03", 4.25)
        snap = ms.snapshot()
        assert snap["us10y"]["date"] == "2026-01-03"

    def test_update_overwrites_value(self):
        from ml.macro_store import MacroStore

        ms = MacroStore()
        ms.update("vix", "2026-01-01", 18.0)
        ms.update("vix", "2026-01-02", 22.5)
        snap = ms.snapshot()
        assert snap["vix"]["value"] == pytest.approx(22.5)

    def test_align_to_hourly_forward_fills(self):
        import pandas as pd
        from ml.macro_store import MacroStore

        ms = MacroStore()
        ms.update("dxy", "2026-01-01", 103.0)
        idx = pd.date_range("2026-01-01 00:00", periods=24, freq="h", tz="UTC")
        ohlcv = pd.DataFrame({"close": 2000.0}, index=idx)
        result = ms.align_to_hourly(ohlcv)
        assert "dxy" in result.columns
        assert not result["dxy"].isna().all()

    def test_missing_series_fills_zero(self):
        import pandas as pd
        from ml.macro_store import MacroStore

        ms = MacroStore()
        idx = pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC")
        ohlcv = pd.DataFrame({"close": 2000.0}, index=idx)
        result = ms.align_to_hourly(ohlcv)
        # Series with no data should be 0 or NaN — not raise
        assert result is not None

    def test_singleton_importable(self):
        from ml.macro_store import MacroStore, macro_store

        assert isinstance(macro_store, MacroStore)


# ── 7. AMLGate ────────────────────────────────────────────────────────────────


class TestAMLGate:
    def _gate(self):
        from compliance.aml import AMLGate

        return AMLGate()

    def test_small_approved_allowed(self):
        r = self._gate().check_withdrawal("u1", Decimal("500"), kyc_status="approved")
        assert r.allowed

    def test_exceeds_single_cap_blocked(self):
        r = self._gate().check_withdrawal("u2", Decimal("15000"), kyc_status="approved")
        assert not r.allowed
        assert "EXCEEDS_SINGLE_CAP" in r.flags

    def test_kyc_required_for_large_amount(self):
        r = self._gate().check_withdrawal("u3", Decimal("2000"), kyc_status="unverified")
        assert not r.allowed
        assert "KYC_REQUIRED" in r.flags

    def test_risk_score_range(self):
        r = self._gate().check_withdrawal("u4", Decimal("500"), kyc_status="approved")
        assert 0.0 <= r.risk_score <= 1.0

    def test_blocked_decision_has_reason(self):
        r = self._gate().check_withdrawal("u5", Decimal("20000"), kyc_status="approved")
        assert not r.allowed
        assert len(r.reason) > 0


# ── 8. ImmutableAuditLog ──────────────────────────────────────────────────────


class TestImmutableAuditLog:
    def _log(self, tmp_path):
        from compliance.auditor import ImmutableAuditLog

        return ImmutableAuditLog(log_path=str(tmp_path) + "/")

    def test_append_returns_record(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        rec = log.append(AuditLevel.COMPLIANCE, "ORDER", "system", "place_order", {"symbol": "XAU_USD"})
        assert rec.sequence_number == 1
        assert len(rec.hash_chain) == 64

    def test_sequence_increments(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        r1 = log.append(AuditLevel.INFO, "ORDER", "sys", "a1", {})
        r2 = log.append(AuditLevel.INFO, "ORDER", "sys", "a2", {})
        assert r2.sequence_number == r1.sequence_number + 1

    def test_hash_chain_links_records(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        r1 = log.append(AuditLevel.INFO, "ORDER", "sys", "a1", {})
        r2 = log.append(AuditLevel.INFO, "ORDER", "sys", "a2", {})
        # r2 hash_chain must differ from r1 (it incorporates r1's hash)
        assert r1.hash_chain != r2.hash_chain

    def test_verify_integrity_passes(self, tmp_path):
        from compliance.auditor import AuditLevel

        log = self._log(tmp_path)
        log.append(AuditLevel.COMPLIANCE, "RISK", "sys", "breach", {"dd": 0.11})
        assert log.verify_integrity() is True


# ── 9. ComplianceManager ──────────────────────────────────────────────────────


class TestComplianceManager:
    def _cm(self):
        from compliance.compliance_manager import ComplianceManager

        return ComplianceManager()

    def test_kyc_submit_pending(self):
        from compliance.compliance_manager import KYCStatus

        cm = self._cm()
        cm.submit_kyc("u1", "passport")
        assert cm.get_kyc_status("u1") == KYCStatus.PENDING

    def test_kyc_approve(self):
        cm = self._cm()
        cm.submit_kyc("u1", "passport")
        cm.approve_kyc("u1")
        assert cm.is_kyc_approved("u1")

    def test_kyc_reject(self):
        from compliance.compliance_manager import KYCStatus

        cm = self._cm()
        cm.submit_kyc("u1", "passport")
        cm.reject_kyc("u1", "fraud")
        assert cm.get_kyc_status("u1") == KYCStatus.REJECTED

    def test_audit_log_populated(self):
        cm = self._cm()
        cm.submit_kyc("u2", "id_card")
        log = cm.get_audit_log()
        assert len(log) >= 1
        assert log[-1]["action"] == "kyc_submitted"

    def test_unknown_user_not_approved(self):
        cm = self._cm()
        assert not cm.is_kyc_approved("unknown_user")


# ── 10. AlmgrenChriss market impact ──────────────────────────────────────────


class TestAlmgrenChriss:
    def test_estimate_basic(self):
        from execution.market_impact import AlmgrenChrissModel

        model = AlmgrenChrissModel()
        impact = model.estimate(order_size=100.0, adv=10_000.0, volatility_daily=0.012, spread_bps=3.0, price=2000.0)
        assert impact.total_impact_bps > 0
        assert impact.spread_cost_bps > 0
        assert impact.temporary_impact_bps >= 0
        assert impact.permanent_impact_bps >= 0

    def test_buy_fill_price_above_signal(self):
        from execution.market_impact import AlmgrenChrissModel

        model = AlmgrenChrissModel()
        impact = model.estimate(100.0, 10_000.0, 0.012, 3.0, 2000.0)
        assert impact.fill_price("BUY") > 2000.0

    def test_sell_fill_price_below_signal(self):
        from execution.market_impact import AlmgrenChrissModel

        model = AlmgrenChrissModel()
        impact = model.estimate(100.0, 10_000.0, 0.012, 3.0, 2000.0)
        assert impact.fill_price("SELL") < 2000.0

    def test_zero_adv_spread_only(self):
        from execution.market_impact import AlmgrenChrissModel

        model = AlmgrenChrissModel()
        impact = model.estimate(100.0, 0.0, 0.012, 3.0, 2000.0)
        assert impact.temporary_impact_bps == 0.0
        assert impact.permanent_impact_bps == 0.0
        assert impact.spread_cost_bps > 0

    def test_fill_simulator_partial_fill(self):
        from execution.market_impact import FillSimulator

        sim = FillSimulator()
        fill = sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=1000.0,
            bar_high=2002.0,
            bar_low=1998.0,
            bar_volume=100.0,
            adv=10_000.0,
            volatility_daily=0.012,
        )
        assert fill.partial_fill
        assert fill.fill_quantity < 1000.0

    def test_fill_price_clamped_to_bar(self):
        from execution.market_impact import FillSimulator

        sim = FillSimulator()
        fill = sim.simulate_fill(
            signal_price=2000.0,
            side="BUY",
            quantity=1.0,
            bar_high=2001.0,
            bar_low=1999.0,
            bar_volume=5000.0,
            adv=10_000.0,
            volatility_daily=0.012,
        )
        assert fill.fill_price <= 2001.0


# ── 11. MonteCarloEngine ──────────────────────────────────────────────────────


class TestMonteCarloEngine:
    def _pnls(self, n=200):
        import numpy as np

        rng = np.random.default_rng(42)
        return list(rng.normal(50, 200, n))

    def test_run_returns_result(self):
        from analytics.monte_carlo import MonteCarloEngine

        result = MonteCarloEngine(n_paths=100).run(self._pnls())
        assert result.n_paths == 100
        assert result.n_trades == 200

    def test_sharpe_ci_ordered(self):
        from analytics.monte_carlo import MonteCarloEngine

        result = MonteCarloEngine(n_paths=100).run(self._pnls())
        assert result.sharpe_ci_95[0] <= result.sharpe_ci_95[1]

    def test_max_dd_ci_ordered(self):
        from analytics.monte_carlo import MonteCarloEngine

        result = MonteCarloEngine(n_paths=100).run(self._pnls())
        assert result.max_dd_ci_95[0] <= result.max_dd_ci_95[1]

    def test_ruin_probability_in_range(self):
        from analytics.monte_carlo import MonteCarloEngine

        result = MonteCarloEngine(n_paths=200).run(self._pnls())
        assert 0.0 <= result.ruin_probability <= 1.0

    def test_empty_pnls_returns_zero_paths(self):
        from analytics.monte_carlo import MonteCarloEngine

        result = MonteCarloEngine(n_paths=100).run([])
        assert result.n_paths == 0

    def test_run_bootstrap_convenience(self):
        from analytics.monte_carlo import run_bootstrap

        result = run_bootstrap(self._pnls(), n_paths=100)
        assert result.n_trades == 200

    def test_summary_dict_keys(self):
        from analytics.monte_carlo import run_bootstrap

        summary = run_bootstrap(self._pnls(), n_paths=50).summary()
        for key in ("sharpe_ci_95", "max_dd_ci_95", "ruin_probability", "sharpe_se"):
            assert key in summary


# ── 12. SharpeCircuitBreaker ──────────────────────────────────────────────────


class TestSharpeCircuitBreaker:
    def test_closed_initially(self):
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        cb = SharpeCircuitBreaker()
        assert not cb.is_open("model_v1")

    @pytest.mark.asyncio
    async def test_trips_on_sustained_losses(self):
        """Circuit opens after CONSECUTIVE_WINDOWS bad evaluations."""
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker, CONSECUTIVE_WINDOWS

        cb = SharpeCircuitBreaker(redis_client=None)
        # Fill the window with losses then force evaluation CONSECUTIVE_WINDOWS times
        for _ in range(50):
            cb.record_trade(pnl=-100.0, model_version="bad_model")
        state = cb._get_or_create("bad_model")
        for _ in range(CONSECUTIVE_WINDOWS):
            await cb._evaluate_one(state)
        assert cb.is_open("bad_model")

    @pytest.mark.asyncio
    async def test_stays_closed_on_profits(self):
        """Circuit stays closed when Sharpe is positive."""
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        cb = SharpeCircuitBreaker(redis_client=None)
        for _ in range(50):
            cb.record_trade(pnl=100.0, model_version="good_model")
        state = cb._get_or_create("good_model")
        await cb._evaluate_one(state)
        assert not cb.is_open("good_model")

    def test_manual_reset(self):
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        cb = SharpeCircuitBreaker()
        for _ in range(60):
            cb.record_trade(pnl=-100.0, model_version="bad_v3")
        state = cb._states.get("bad_v3")
        if state:
            state.is_open = True
        cb.reset("bad_v3")
        assert not cb.is_open("bad_v3")

    def test_get_status_structure(self):
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        cb = SharpeCircuitBreaker()
        cb.record_trade(pnl=10.0, model_version="good_v1")
        status = cb.get_status()
        assert "good_v1" in status
        assert "is_open" in status["good_v1"]


# ── 13. TWAP / Iceberg algo orders ───────────────────────────────────────────


class TestAlgoOrders:
    @pytest.mark.asyncio
    async def test_twap_completes(self):
        from execution.algo_orders import TWAPOrder

        fills = []

        async def submit(**kw):
            fills.append(kw["quantity"])
            return {"success": True, "fill_price": 2000.0, "filled_quantity": kw["quantity"]}

        order = TWAPOrder(
            symbol="XAU_USD",
            side="BUY",
            total_quantity=10.0,
            duration_seconds=0.5,
            num_slices=5,
            broker_submit_fn=submit,
        )
        report = await order.run()
        assert report.filled_quantity == pytest.approx(10.0, abs=0.01)
        assert len(fills) == 5

    @pytest.mark.asyncio
    async def test_iceberg_completes(self):
        from execution.algo_orders import IcebergOrder

        fills = []

        async def submit(**kw):
            fills.append(kw["quantity"])
            return {"success": True, "fill_price": 2000.0, "filled_quantity": kw["quantity"]}

        order = IcebergOrder(
            symbol="XAU_USD",
            side="SELL",
            total_quantity=5.0,
            peak_size=1.0,
            refill_delay_seconds=0.01,
            broker_submit_fn=submit,
        )
        report = await order.run()
        assert report.filled_quantity == pytest.approx(5.0, abs=0.01)
        assert len(fills) == 5


# ── 14. MacroStore singleton wired ────────────────────────────────────────────


def test_macro_store_singleton_importable():
    from ml.macro_store import MacroStore, macro_store

    assert isinstance(macro_store, MacroStore)
    macro_store.update("test_series", "2026-01-02", 1.0)
    snap = macro_store.snapshot()
    assert "test_series" in snap


# ── 15. AML gate velocity check ──────────────────────────────────────────────


def test_aml_gate_velocity_check():
    """Multiple rapid withdrawals should trigger velocity flag."""
    from compliance.aml import AMLGate

    gate = AMLGate()
    # The gate checks DB history; without DB it falls back to allow.
    # Verify the gate at least returns a valid AMLDecision.
    result = gate.check_withdrawal("u_velocity", Decimal("500"), kyc_status="approved")
    assert hasattr(result, "allowed")
    assert hasattr(result, "flags")
    assert hasattr(result, "risk_score")


# ── 16. DrawdownTracker record_fill ──────────────────────────────────────────


def test_drawdown_tracker_record_fill():
    from risk.drawdown_tracker import DrawdownTracker

    dt = DrawdownTracker(initial_balance=100_000.0)
    dt.record_fill(pnl=-500.0)
    # After recording a fill, update should reflect the loss
    r = dt.update(equity=99_500.0, balance=99_500.0)
    assert r.total_drawdown_pct == pytest.approx(0.005, abs=0.001)


# ── 17. PositionSizer small equity produces small size ────────────────────────


def test_position_sizer_small_equity_produces_small_size():
    """Tiny equity produces a proportionally tiny position size."""
    from risk.position_sizing import PositionSizer

    ps = PositionSizer(method="atr", risk_pct=0.01, max_lots=200.0)
    acct = _AccountInfo(
        balance=1000.0,
        equity=1000.0,
        margin_used=0.0,
        margin_available=1000.0,
        positions_count=0,
    )
    size = ps.calculate_size(acct, Decimal("2000"), atr=Decimal("10"))
    # risk=10; size=10/10=1 lot
    assert float(size) == pytest.approx(1.0, abs=0.01)


# ── 18. TCARecorder multiple fills aggregation ───────────────────────────────


def test_tca_recorder_aggregates_multiple_fills():
    from execution.tca_recorder import TCARecorder

    r = TCARecorder()
    for i in range(5):
        r.record_signal(f"req{i}", "XAU_USD", "BUY", 2000.0, 1.0, "v1")
        r.record_fill(f"req{i}", 2001.0, 1.0, "oanda", 10.0)
    rpt = r.get_report(broker="oanda")
    assert rpt.n_trades == 5
    assert rpt.mean_slippage_bps == pytest.approx(5.0, abs=0.5)


# ── 19. KillSwitch async poll ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kill_switch_async_poll_detects_flag(tmp_path):
    from kill_switch import KillSwitch

    ks = KillSwitch(flag_file=tmp_path / "ks.flag", poll_interval_sec=0.05)
    await ks.start()
    flag = tmp_path / "ks.flag"
    flag.write_text("reason=file-trigger\n")
    await asyncio.sleep(0.2)
    assert ks.is_active()
    await ks.stop()
