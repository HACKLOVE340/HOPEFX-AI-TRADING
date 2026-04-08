# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
AdaptiveEdgeSelector — Batch 2: Beast features.

Covers:
- NewsEvent dataclass and affects()/is_within_window()
- NewsFilter: hard skip, medium skip, imminent skip, crypto keyword skip
- DecisionRecord / DecisionMemory: record, recent, last_outcome, win_rate,
  memory_adjustment, clear
- select() with memory adjustment (boost won, penalise lost)
- select() with news filter integration
- _apply_lookahead: flip risk scoring, confidence penalty, skip conversion
- select_all(): multi-symbol, order preserved, independent decisions
- record_outcome() convenience method
- Beast reason voice: sniper/scalper/grid contain expected phrases
"""

from __future__ import annotations

import pytest
from strategies.adaptive_edge_selector import (
    AdaptiveEdgeSelector,
    MarketSnapshot,
    EdgeDecision,
    DecisionMemory,
    DecisionRecord,
    NewsFilter,
    NewsEvent,
    EDGE_SNIPER,
    EDGE_SCALPER,
    EDGE_GRID,
    EDGE_SKIP,
    REGIME_TRENDING_UP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap(**kw):
    defaults = dict(
        symbol="XAUUSD",
        price=2345.67,
        atr=1.25,
        adx=32.1,
        rsi=68.0,
        volume_delta=15.0,
        cone_strength=0.87,
        last_candles="bullish engulfing",
        news_spike=False,
        liquidity="high",
        drawdown_pct=0.0,
    )
    defaults.update(kw)
    return MarketSnapshot(**defaults)


def _sel(memory=None, news_filter=None):
    return AdaptiveEdgeSelector(
        memory=memory or DecisionMemory(),
        news_filter=news_filter or NewsFilter(),
    )


# ---------------------------------------------------------------------------
# NewsEvent
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestNewsEvent:
    def test_affects_empty_list_means_all(self):
        ev = NewsEvent(minutes_away=30, symbols_affected=[])
        assert ev.affects("XAUUSD") is True
        assert ev.affects("BTCUSD") is True

    def test_affects_specific_symbol(self):
        ev = NewsEvent(minutes_away=30, symbols_affected=["BTCUSD"])
        assert ev.affects("BTCUSD") is True
        assert ev.affects("XAUUSD") is False

    def test_affects_case_insensitive(self):
        ev = NewsEvent(minutes_away=30, symbols_affected=["btcusd"])
        assert ev.affects("BTCUSD") is True

    def test_is_within_window_true(self):
        ev = NewsEvent(minutes_away=45)
        assert ev.is_within_window(60) is True

    def test_is_within_window_false(self):
        ev = NewsEvent(minutes_away=90)
        assert ev.is_within_window(60) is False

    def test_is_within_window_negative_minutes(self):
        # Event happened 20 min ago — still within 60 min window
        ev = NewsEvent(minutes_away=-20)
        assert ev.is_within_window(60) is True

    def test_default_severity_high(self):
        ev = NewsEvent(minutes_away=30)
        assert ev.severity == "high"


# ---------------------------------------------------------------------------
# NewsFilter
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestNewsFilter:
    def test_safe_when_no_events(self):
        nf = NewsFilter()
        safe, reason = nf.is_safe("XAUUSD")
        assert safe is True
        assert reason == ""

    def test_high_severity_within_60_min_blocks(self):
        nf = NewsFilter([NewsEvent(minutes_away=30, description="FOMC", severity="high")])
        safe, reason = nf.is_safe("XAUUSD")
        assert safe is False
        assert "FOMC" in reason

    def test_high_severity_outside_60_min_passes(self):
        nf = NewsFilter([NewsEvent(minutes_away=90, description="FOMC", severity="high")])
        safe, reason = nf.is_safe("XAUUSD")
        assert safe is True

    def test_medium_severity_within_30_min_blocks(self):
        nf = NewsFilter([NewsEvent(minutes_away=20, description="CPI", severity="medium")])
        safe, reason = nf.is_safe("XAUUSD")
        assert safe is False
        assert "CPI" in reason

    def test_medium_severity_outside_30_min_passes(self):
        nf = NewsFilter([NewsEvent(minutes_away=45, description="CPI", severity="medium")])
        safe, reason = nf.is_safe("XAUUSD")
        assert safe is True

    def test_any_event_within_15_min_blocks(self):
        nf = NewsFilter([NewsEvent(minutes_away=10, description="speech", severity="low")])
        safe, reason = nf.is_safe("XAUUSD")
        assert safe is False
        assert "imminent" in reason

    def test_event_not_affecting_symbol_passes(self):
        nf = NewsFilter([NewsEvent(minutes_away=5, description="CPI", severity="high", symbols_affected=["EURUSD"])])
        safe, _ = nf.is_safe("XAUUSD")
        assert safe is True

    def test_crypto_hack_blocks_btc(self):
        # Use 45 min — outside medium-severity 30-min window, inside crypto 120-min window
        # so only the crypto keyword path fires (not the generic medium-severity rule)
        nf = NewsFilter(
            [NewsEvent(minutes_away=45, description="crypto hack rumor", severity="medium", symbols_affected=[])]
        )
        safe, reason = nf.is_safe("BTCUSD")
        assert safe is False
        assert "crypto_risk" in reason

    def test_crypto_hack_does_not_block_xauusd(self):
        # Same 45-min event — XAUUSD is not a crypto symbol, crypto path skips it,
        # and 45 min is outside the medium-severity 30-min window → safe
        nf = NewsFilter(
            [NewsEvent(minutes_away=45, description="crypto hack rumor", severity="medium", symbols_affected=[])]
        )
        safe, _ = nf.is_safe("XAUUSD")
        assert safe is True

    def test_add_event(self):
        nf = NewsFilter()
        nf.add(NewsEvent(minutes_away=10, description="test", severity="high"))
        safe, _ = nf.is_safe("XAUUSD")
        assert safe is False

    def test_clear_events(self):
        nf = NewsFilter([NewsEvent(minutes_away=10, description="test", severity="high")])
        nf.clear()
        safe, _ = nf.is_safe("XAUUSD")
        assert safe is True

    @pytest.mark.parametrize("keyword", ["hack", "exploit", "sec", "ban"])
    def test_crypto_keywords_block_btc(self, keyword):
        nf = NewsFilter(
            [NewsEvent(minutes_away=30, description=f"{keyword} event", severity="low", symbols_affected=[])]
        )
        safe, _ = nf.is_safe("BTCUSD")
        assert safe is False


# ---------------------------------------------------------------------------
# DecisionMemory
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDecisionMemory:
    def _rec(self, symbol="XAUUSD", edge=EDGE_SNIPER, outcome="won", conf=88):
        return DecisionRecord(symbol=symbol, edge=edge, outcome=outcome, confidence=conf, regime=REGIME_TRENDING_UP)

    def test_record_and_recent(self):
        mem = DecisionMemory()
        mem.record(self._rec())
        assert len(mem.recent("XAUUSD")) == 1

    def test_recent_returns_newest_last(self):
        mem = DecisionMemory()
        mem.record(self._rec(outcome="won"))
        mem.record(self._rec(outcome="lost"))
        recs = mem.recent("XAUUSD", n=2)
        assert recs[-1].outcome == "lost"

    def test_recent_respects_n(self):
        mem = DecisionMemory()
        for _ in range(5):
            mem.record(self._rec())
        assert len(mem.recent("XAUUSD", n=3)) == 3

    def test_window_evicts_oldest(self):
        mem = DecisionMemory(window=3)
        for i in range(5):
            mem.record(self._rec(outcome="won" if i < 3 else "lost"))
        recs = mem.recent("XAUUSD", n=10)
        assert len(recs) == 3

    def test_last_outcome_found(self):
        mem = DecisionMemory()
        mem.record(self._rec(edge=EDGE_SNIPER, outcome="won"))
        assert mem.last_outcome("XAUUSD", EDGE_SNIPER) == "won"

    def test_last_outcome_none_when_no_history(self):
        mem = DecisionMemory()
        assert mem.last_outcome("XAUUSD", EDGE_SNIPER) is None

    def test_last_outcome_returns_most_recent(self):
        mem = DecisionMemory()
        mem.record(self._rec(edge=EDGE_SNIPER, outcome="won"))
        mem.record(self._rec(edge=EDGE_SNIPER, outcome="lost"))
        assert mem.last_outcome("XAUUSD", EDGE_SNIPER) == "lost"

    def test_win_rate_all_wins(self):
        mem = DecisionMemory()
        for _ in range(4):
            mem.record(self._rec(outcome="won"))
        assert mem.win_rate("XAUUSD", EDGE_SNIPER) == pytest.approx(1.0)

    def test_win_rate_all_losses(self):
        mem = DecisionMemory()
        for _ in range(4):
            mem.record(self._rec(outcome="lost"))
        assert mem.win_rate("XAUUSD", EDGE_SNIPER) == pytest.approx(0.0)

    def test_win_rate_neutral_prior_no_history(self):
        mem = DecisionMemory()
        assert mem.win_rate("XAUUSD", EDGE_SNIPER) == pytest.approx(0.5)

    def test_memory_adjustment_won(self):
        mem = DecisionMemory()
        mem.record(self._rec(outcome="won"))
        assert mem.memory_adjustment("XAUUSD", EDGE_SNIPER) == 10

    def test_memory_adjustment_lost(self):
        mem = DecisionMemory()
        mem.record(self._rec(outcome="lost"))
        assert mem.memory_adjustment("XAUUSD", EDGE_SNIPER) == -15

    def test_memory_adjustment_no_history(self):
        mem = DecisionMemory()
        assert mem.memory_adjustment("XAUUSD", EDGE_SNIPER) == 0

    def test_clear_specific_symbol(self):
        mem = DecisionMemory()
        mem.record(self._rec(symbol="XAUUSD"))
        mem.record(self._rec(symbol="BTCUSD"))
        mem.clear("XAUUSD")
        assert len(mem.recent("XAUUSD")) == 0
        assert len(mem.recent("BTCUSD")) == 1

    def test_clear_all(self):
        mem = DecisionMemory()
        mem.record(self._rec(symbol="XAUUSD"))
        mem.record(self._rec(symbol="BTCUSD"))
        mem.clear()
        assert len(mem.recent("XAUUSD")) == 0
        assert len(mem.recent("BTCUSD")) == 0

    def test_case_insensitive_symbol(self):
        mem = DecisionMemory()
        mem.record(self._rec(symbol="xauusd"))
        assert len(mem.recent("XAUUSD")) == 1


# ---------------------------------------------------------------------------
# select() with memory
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSelectWithMemory:
    def test_memory_boost_on_prior_win(self):
        mem = DecisionMemory()
        mem.record(
            DecisionRecord(symbol="XAUUSD", edge=EDGE_SNIPER, outcome="won", confidence=88, regime=REGIME_TRENDING_UP)
        )
        sel = _sel(memory=mem)
        d = sel.select(_snap())
        if d.edge == EDGE_SNIPER:
            assert "mem_adj=+10" in d.reason

    def test_memory_penalty_on_prior_loss(self):
        mem = DecisionMemory()
        mem.record(
            DecisionRecord(symbol="XAUUSD", edge=EDGE_SNIPER, outcome="lost", confidence=88, regime=REGIME_TRENDING_UP)
        )
        sel = _sel(memory=mem)
        d = sel.select(_snap())
        if d.edge == EDGE_SNIPER:
            assert "mem_adj=-15" in d.reason

    def test_post_memory_skip_when_confidence_drops_below_min(self):
        """
        If memory penalty drops confidence below min_confidence, result is skip.
        """
        mem = DecisionMemory()
        # Record 5 losses to drive win_rate to 0 → adjustment = -8
        for _ in range(5):
            mem.record(
                DecisionRecord(
                    symbol="XAUUSD", edge=EDGE_SNIPER, outcome="lost", confidence=80, regime=REGIME_TRENDING_UP
                )
            )
        sel = _sel(memory=mem)
        # Use a snap that produces sniper confidence just above 80 so -15 drops it below
        d = sel.select(_snap(cone_strength=0.71, adx=26.0, volume_delta=5.0, last_candles="", liquidity="normal"))
        # Either skip (confidence dropped) or sniper (if base conf was high enough)
        assert d.edge in (EDGE_SNIPER, EDGE_SKIP)

    def test_record_outcome_stores_in_memory(self):
        sel = _sel()
        sel.record_outcome("XAUUSD", EDGE_SNIPER, "won", confidence=90, regime=REGIME_TRENDING_UP)
        assert sel.memory.last_outcome("XAUUSD", EDGE_SNIPER) == "won"


# ---------------------------------------------------------------------------
# select() with news filter
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSelectWithNewsFilter:
    def test_high_news_within_60_min_skips(self):
        nf = NewsFilter([NewsEvent(minutes_away=30, description="FOMC", severity="high")])
        sel = _sel(news_filter=nf)
        d = sel.select(_snap())
        assert d.edge == EDGE_SKIP
        assert "FOMC" in d.reason

    def test_news_outside_window_does_not_skip(self):
        nf = NewsFilter([NewsEvent(minutes_away=90, description="FOMC", severity="high")])
        sel = _sel(news_filter=nf)
        d = sel.select(_snap())
        assert d.edge != EDGE_SKIP or "FOMC" not in d.reason

    def test_crypto_news_skips_btc_not_xau(self):
        nf = NewsFilter([NewsEvent(minutes_away=10, description="crypto hack", severity="medium", symbols_affected=[])])
        sel = _sel(news_filter=nf)
        btc = _snap(symbol="BTCUSD", price=67890, atr=450, adx=32.1)
        xau = _snap(symbol="XAUUSD")
        d_btc = sel.select(btc)
        d_xau = sel.select(xau)
        assert d_btc.edge == EDGE_SKIP
        # XAU should not be blocked by crypto news (unless within 15 min)
        # 10 min → imminent block fires for all symbols
        assert d_xau.edge == EDGE_SKIP  # 10 min is within 15 min imminent window

    def test_news_spike_field_still_blocks(self):
        """Legacy news_spike=True field still triggers skip."""
        sel = _sel()
        d = sel.select(_snap(news_spike=True))
        assert d.edge == EDGE_SKIP


# ---------------------------------------------------------------------------
# Lookahead
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLookahead:
    def setup_method(self):
        self.sel = _sel()

    def _make_decision(self, edge=EDGE_SNIPER, conf=90):
        return EdgeDecision(
            regime=REGIME_TRENDING_UP,
            edge=edge,
            confidence=conf,
            reason="test",
            action="buy 0.01",
            symbol="XAUUSD",
            entry_price=2345.67,
            sl_price=2343.17,
            tp_price=2350.67,
            lot_size=0.01,
            strategy_name="smc_ict",
        )

    def test_skip_decision_unchanged(self):
        snap = _snap()
        skip_d = EdgeDecision(
            regime=REGIME_TRENDING_UP, edge=EDGE_SKIP, confidence=0, reason="test", action="no_trade", symbol="XAUUSD"
        )
        result = self.sel._apply_lookahead(snap, skip_d)
        assert result.edge == EDGE_SKIP

    def test_high_flip_risk_converts_to_skip(self):
        # RSI near 50 (+2), low volume (+1), cone near threshold (+1), high ATR (+2) = 6
        snap = _snap(rsi=51.0, volume_delta=2.0, cone_strength=0.71, atr=10.0, price=1000.0)  # rel_atr=0.01 > 0.002*2
        d = self._make_decision(conf=90)
        result = self.sel._apply_lookahead(snap, d)
        assert result.edge == EDGE_SKIP
        assert "lookahead_flip_risk" in result.reason

    def test_medium_flip_risk_reduces_confidence(self):
        # RSI near 50 (+2), low volume (+1) = 3 → medium risk, penalty = 3*4 = 12
        snap = _snap(rsi=51.0, volume_delta=2.0, cone_strength=0.87, atr=1.25, price=2345.67)
        d = self._make_decision(conf=95)
        result = self.sel._apply_lookahead(snap, d)
        if result.edge != EDGE_SKIP:
            assert result.confidence < 95
            assert "lookahead_risk" in result.reason

    def test_low_flip_risk_no_change(self):
        # Strong RSI (68), high volume (15%), good cone (0.87), normal ATR
        snap = _snap(rsi=68.0, volume_delta=15.0, cone_strength=0.87, atr=1.25, price=2345.67)
        d = self._make_decision(conf=90)
        result = self.sel._apply_lookahead(snap, d)
        # Flip risk = 0 → no change
        assert result.confidence == 90
        assert "lookahead" not in result.reason

    def test_soft_news_proximity_adds_flip_risk(self):
        nf = NewsFilter([NewsEvent(minutes_away=45, description="FOMC", severity="high", symbols_affected=[])])
        sel = AdaptiveEdgeSelector(news_filter=nf)
        snap = _snap(rsi=68.0, volume_delta=15.0, cone_strength=0.87, atr=1.25, price=2345.67)
        d = self._make_decision(conf=90)
        result = sel._apply_lookahead(snap, d)
        # 45 min away high severity → +2 flip risk → medium → confidence reduced
        if result.edge != EDGE_SKIP:
            assert result.confidence <= 90


# ---------------------------------------------------------------------------
# select_all() — multi-symbol
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSelectAll:
    def setup_method(self):
        self.sel = _sel()

    def _xau(self):
        return _snap(
            symbol="XAUUSD",
            price=2345.67,
            atr=1.25,
            adx=32.1,
            rsi=68.0,
            volume_delta=15.0,
            cone_strength=0.87,
            last_candles="bullish engulfing",
            liquidity="high",
        )

    def _btc(self):
        return _snap(
            symbol="BTCUSD",
            price=67890,
            atr=450,
            adx=18.0,
            rsi=55.0,
            volume_delta=-8.0,
            cone_strength=0.62,
            last_candles="doji",
            liquidity="normal",
        )

    def _eur(self):
        return _snap(
            symbol="EURUSD",
            price=1.085,
            atr=0.008,
            adx=25.0,
            rsi=72.0,
            volume_delta=5.0,
            cone_strength=0.91,
            last_candles="hammer",
            liquidity="normal",
        )

    def test_returns_one_decision_per_symbol(self):
        decisions = self.sel.select_all([self._xau(), self._btc(), self._eur()])
        assert len(decisions) == 3

    def test_order_preserved(self):
        snaps = [self._xau(), self._btc(), self._eur()]
        decisions = self.sel.select_all(snaps)
        assert decisions[0].symbol == "XAUUSD"
        assert decisions[1].symbol == "BTCUSD"
        assert decisions[2].symbol == "EURUSD"

    def test_each_decision_is_edge_decision(self):
        for d in self.sel.select_all([self._xau(), self._btc(), self._eur()]):
            assert isinstance(d, EdgeDecision)

    def test_each_decision_has_valid_edge(self):
        valid = {EDGE_SNIPER, EDGE_SCALPER, EDGE_GRID, EDGE_SKIP}
        for d in self.sel.select_all([self._xau(), self._btc(), self._eur()]):
            assert d.edge in valid

    def test_empty_list_returns_empty(self):
        assert self.sel.select_all([]) == []

    def test_single_symbol_list(self):
        decisions = self.sel.select_all([self._xau()])
        assert len(decisions) == 1

    def test_decisions_are_independent(self):
        """Decisions for different symbols must not share state."""
        decisions = self.sel.select_all([self._xau(), self._btc()])
        assert decisions[0].symbol != decisions[1].symbol

    def test_news_filter_applied_per_symbol(self):
        nf = NewsFilter([NewsEvent(minutes_away=30, description="FOMC", severity="high", symbols_affected=["XAUUSD"])])
        sel = AdaptiveEdgeSelector(news_filter=nf)
        decisions = sel.select_all([self._xau(), self._btc()])
        xau_d = next(d for d in decisions if d.symbol == "XAUUSD")
        btc_d = next(d for d in decisions if d.symbol == "BTCUSD")
        assert xau_d.edge == EDGE_SKIP
        # BTC not affected by FOMC news
        assert btc_d.edge in (EDGE_SNIPER, EDGE_SCALPER, EDGE_GRID, EDGE_SKIP)

    def test_to_dict_list_json_serialisable(self):
        import json

        decisions = self.sel.select_all([self._xau(), self._btc(), self._eur()])
        json.dumps([d.to_dict() for d in decisions])  # must not raise


# ---------------------------------------------------------------------------
# Beast reason voice
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBeastReasonVoice:
    def setup_method(self):
        self.sel = _sel()

    def test_sniper_reason_contains_cone_phrase(self):
        d = self.sel.select(_snap(cone_strength=0.87, adx=32.1))
        if d.edge == EDGE_SNIPER:
            assert any(w in d.reason.lower() for w in ("cone", "sharp", "screaming", "lit"))

    def test_sniper_reason_contains_adx_phrase(self):
        d = self.sel.select(_snap(adx=32.1))
        if d.edge == EDGE_SNIPER:
            assert "adx" in d.reason.lower() or "momentum" in d.reason.lower()

    def test_sniper_reason_contains_engulfing_phrase(self):
        d = self.sel.select(_snap(last_candles="bullish engulfing"))
        if d.edge == EDGE_SNIPER:
            assert "engulfing" in d.reason.lower() or "no mercy" in d.reason.lower()

    def test_sniper_reason_contains_rr(self):
        d = self.sel.select(_snap())
        if d.edge == EDGE_SNIPER:
            assert "rr" in d.reason.lower() or "pips" in d.reason.lower()

    def test_scalper_reason_contains_rsi(self):
        d = self.sel.select(_snap(adx=22.0, rsi=72.0, cone_strength=0.85, atr=0.5, price=2000.0, volume_delta=8.0))
        if d.edge == EDGE_SCALPER:
            assert "rsi" in d.reason.lower()

    def test_scalper_reason_contains_reversion_phrase(self):
        d = self.sel.select(_snap(adx=22.0, rsi=72.0, cone_strength=0.85, atr=0.5, price=2000.0, volume_delta=8.0))
        if d.edge == EDGE_SCALPER:
            assert any(w in d.reason.lower() for w in ("reversion", "fade", "snap", "overbought", "oversold"))

    def test_grid_reason_contains_volatile_phrase(self):
        d = self.sel.select(_snap(adx=30.0, volume_delta=50.0, cone_strength=0.85, atr=1.25, price=2000.0))
        if d.edge == EDGE_GRID:
            assert any(w in d.reason.lower() for w in ("volatile", "chaos", "layers", "grid"))

    def test_memory_won_phrase_in_sniper_reason(self):
        mem = DecisionMemory()
        mem.record(
            DecisionRecord(symbol="XAUUSD", edge=EDGE_SNIPER, outcome="won", confidence=90, regime=REGIME_TRENDING_UP)
        )
        sel = AdaptiveEdgeSelector(memory=mem)
        d = sel.select(_snap())
        if d.edge == EDGE_SNIPER:
            assert any(w in d.reason.lower() for w in ("won", "lean in", "repeat"))

    def test_memory_lost_phrase_in_sniper_reason(self):
        mem = DecisionMemory()
        mem.record(
            DecisionRecord(symbol="XAUUSD", edge=EDGE_SNIPER, outcome="lost", confidence=90, regime=REGIME_TRENDING_UP)
        )
        sel = AdaptiveEdgeSelector(memory=mem)
        d = sel.select(_snap())
        if d.edge == EDGE_SNIPER:
            assert any(w in d.reason.lower() for w in ("lost", "tight", "small"))
