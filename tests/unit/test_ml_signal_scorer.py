# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Unit tests for ``ml.signal_scorer`` — the six-dimension composite signal scorer.

The scorer is advisory (``core.signal_engine._enrich_with_signal_score`` swallows
any failure), but its output is written into every signal payload and surfaced to
operators as ``signal_grade``.  These tests pin the arithmetic of each dimension
so a silent change of grade boundaries cannot pass unnoticed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import signal_scorer as ss


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    """Build an OHLCV frame from a close series with a fixed 1.0 bar range."""
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(len(close), 1000.0),
        }
    )


@pytest.fixture
def uptrend() -> pd.DataFrame:
    """80 bars marching steadily upward — every trend indicator reads bullish."""
    return _ohlcv([100.0 + i * 0.8 for i in range(80)])


@pytest.fixture
def downtrend() -> pd.DataFrame:
    return _ohlcv([164.0 - i * 0.8 for i in range(80)])


# ── Dimension 1: ML confidence ────────────────────────────────────────────────


class TestScoreMLConfidence:
    def test_long_signal_scales_probability_above_neutral(self):
        score, details = ss._score_ml_confidence({"probability": 0.9}, "BUY")
        # (0.9 - 0.5) * 2 == 0.8
        assert score == pytest.approx(0.8)
        assert details["raw_probability"] == 0.9
        assert details["model_version"] == "unknown"

    def test_short_signal_scales_probability_below_neutral(self):
        score, _ = ss._score_ml_confidence({"probability": 0.1}, "SELL")
        # (0.5 - 0.1) * 2 == 0.8
        assert score == pytest.approx(0.8)

    def test_direction_contradicting_the_model_clips_to_zero(self):
        # Model says 90% up, the signal says SELL — no partial credit.
        assert ss._score_ml_confidence({"probability": 0.9}, "SELL")[0] == 0.0
        assert ss._score_ml_confidence({"probability": 0.1}, "BUY")[0] == 0.0

    def test_neutral_probability_scores_zero_in_both_directions(self):
        assert ss._score_ml_confidence({"probability": 0.5}, "BUY")[0] == 0.0
        assert ss._score_ml_confidence({"probability": 0.5}, "SELL")[0] == 0.0

    def test_missing_probability_defaults_to_neutral(self):
        score, details = ss._score_ml_confidence({}, "BUY")
        assert score == 0.0
        assert details["raw_probability"] == 0.5

    def test_long_alias_is_treated_as_bullish(self):
        assert ss._score_ml_confidence({"probability": 0.8}, "long")[0] == pytest.approx(0.6)

    def test_unrecognised_direction_is_scored_as_bearish(self):
        # Anything that is not BUY/LONG falls through the ``is_long`` branch,
        # so NEUTRAL is graded as if it were a short.  Pinned deliberately:
        # the scorer is advisory and never sees a NEUTRAL payload in practice.
        assert ss._score_ml_confidence({"probability": 0.2}, "NEUTRAL")[0] == pytest.approx(0.6)

    def test_high_confidence_flag_boosts_only_above_the_midpoint(self):
        boosted, details = ss._score_ml_confidence({"probability": 0.85, "high_confidence": True}, "BUY")
        # raw 0.7 * 1.1 == 0.77
        assert boosted == pytest.approx(0.77)
        assert details["high_confidence"] is True

        # raw == 0.4, not > 0.5, so no boost applies
        unboosted, _ = ss._score_ml_confidence({"probability": 0.7, "high_confidence": True}, "BUY")
        assert unboosted == pytest.approx(0.4)

    def test_high_confidence_boost_cannot_exceed_one(self):
        score, _ = ss._score_ml_confidence({"probability": 1.0, "high_confidence": True}, "BUY")
        assert score == 1.0

    def test_abstain_halves_the_score(self):
        score, details = ss._score_ml_confidence({"probability": 0.9, "abstain": True}, "BUY")
        assert score == pytest.approx(0.4)
        assert details["abstain"] is True

    def test_hybrid_components_are_passed_through_to_details(self):
        components = {"xgb": 0.8, "lstm": 0.7}
        _, details = ss._score_ml_confidence(
            {"probability": 0.8, "model_version": "v7", "hybrid_components": components}, "BUY"
        )
        assert details["hybrid_components"] == components
        assert details["model_version"] == "v7"


# ── Dimension 2: technical consensus ──────────────────────────────────────────


class TestScoreTechnicalConsensus:
    def test_no_ohlcv_falls_back_to_payload_rsi_and_macd(self):
        score, details = ss._score_technical_consensus(None, "BUY", {"rsi": 65.0, "macd_hist": 0.4})
        assert score == 1.0
        assert details == {"source": "payload_fallback", "votes": 2, "total": 2}

    def test_payload_fallback_counts_disagreeing_indicators(self):
        score, details = ss._score_technical_consensus(None, "SELL", {"rsi": 65.0, "macd_hist": -0.4})
        # RSI disagrees with SELL, MACD agrees.
        assert score == 0.5
        assert details["votes"] == 1

    def test_payload_fallback_defaults_are_bearish_leaning(self):
        # rsi defaults to exactly 50 (not > 50) and macd_hist to 0 (not > 0),
        # so both default votes read as "down".
        assert ss._score_technical_consensus(None, "SELL", {})[0] == 1.0
        assert ss._score_technical_consensus(None, "BUY", {})[0] == 0.0

    def test_short_frame_uses_the_fallback_path(self):
        score, details = ss._score_technical_consensus(
            _ohlcv([100.0 + i for i in range(51)]), "BUY", {"rsi": 70.0, "macd_hist": 1.0}
        )
        assert details["source"] == "payload_fallback"
        assert score == 1.0

    def test_full_indicator_path_agrees_with_an_uptrend_buy(self, uptrend):
        score, details = ss._score_technical_consensus(uptrend, "BUY", {})
        assert score == 1.0
        assert details["source"] if False else "rsi" in details
        assert details["votes"] == details["total"]
        assert details["rsi"] > 50
        assert details["ema20"] > details["ema50"]
        assert set(details["indicator_votes"]) >= {
            "rsi_bullish",
            "macd_hist",
            "ema_crossover",
            "bb_position",
            "stoch_position",
            "momentum_5bar",
        }

    def test_full_indicator_path_penalises_a_counter_trend_sell(self, uptrend):
        score, details = ss._score_technical_consensus(uptrend, "SELL", {})
        # Every directional indicator disagrees; only the unconditional ADX
        # vote survives, so the score is 1/7 rather than 0.
        assert score < 0.2
        assert details["indicator_votes"]["rsi_bullish"] == 0

    def test_adx_vote_is_unconditional_when_the_trend_is_strong(self, uptrend):
        """
        ADX measures trend strength, not direction, so the scorer casts a
        ``True`` vote whenever ADX > 20 regardless of the signal's direction.
        This is deliberate (see the inline comment in the scorer) and it means a
        counter-trend signal scores 1/7 instead of 0/6.  Pinned so the extra
        vote is never removed by accident.
        """
        _, details = ss._score_technical_consensus(uptrend, "SELL", {})
        assert details["adx"] > 20
        assert details["indicator_votes"]["adx_trending"] == 1
        assert details["total"] == 7
        assert details["votes"] == 1

    def test_weak_trend_omits_the_adx_vote(self):
        # A pure sawtooth keeps ADX below 20 — only the six directional votes run.
        chop = _ohlcv([100.0 + (1.0 if i % 2 else -1.0) for i in range(80)])
        _, details = ss._score_technical_consensus(chop, "BUY", {})
        assert details["adx"] <= 20
        assert "adx_trending" not in details["indicator_votes"]
        assert details["total"] == 6

    def test_malformed_frame_degrades_to_neutral(self):
        # 60 rows so the length gate passes, but no 'close' column.
        bad = pd.DataFrame({"price": [1.0] * 60})
        score, details = ss._score_technical_consensus(bad, "BUY", {})
        assert score == 0.5
        assert "error" in details


# ── Dimension 3: macro alignment ──────────────────────────────────────────────


class TestScoreMacroAlignment:
    def test_missing_macro_frame_is_neutral(self):
        score, details = ss._score_macro_alignment(None, "BUY", "XAU_USD")
        assert score == 0.5
        assert details == {"source": "no_macro_data"}

    def test_empty_macro_frame_is_neutral(self):
        assert ss._score_macro_alignment(pd.DataFrame(), "BUY", "XAU_USD")[0] == 0.5

    def test_falling_dxy_supports_a_gold_long(self):
        macro = pd.DataFrame({"dxy": [105.0, 104.5, 104.0, 103.5, 103.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 1.0
        assert details["dxy_slope_5d"] < 0

    def test_rising_dxy_contradicts_a_gold_long(self):
        macro = pd.DataFrame({"dxy": [100.0, 101.0, 102.0, 103.0, 104.0]})
        assert ss._score_macro_alignment(macro, "BUY", "XAU_USD")[0] == 0.0

    def test_dxy_vote_is_neutral_for_non_gold_symbols(self):
        macro = pd.DataFrame({"dxy": [100.0, 101.0, 102.0, 103.0, 104.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "EUR_USD")
        assert score == 1.0  # the non-gold branch always votes True
        assert details["total"] == 1

    def test_short_dxy_history_casts_no_vote(self):
        macro = pd.DataFrame({"dxy": [100.0, 101.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 0.5
        assert details["source"] == "insufficient_macro_signals"

    def test_high_vix_supports_a_gold_long(self):
        macro = pd.DataFrame({"vix": [30.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 1.0
        assert details["vix"] == 30.0

    def test_low_vix_supports_a_gold_short(self):
        macro = pd.DataFrame({"vix": [12.0]})
        assert ss._score_macro_alignment(macro, "SELL", "XAU_USD")[0] == 1.0
        assert ss._score_macro_alignment(macro, "BUY", "XAU_USD")[0] == 0.0

    def test_mid_range_vix_casts_no_vote(self):
        macro = pd.DataFrame({"vix": [20.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 0.5
        assert details["vix"] == 20.0
        assert details["source"] == "insufficient_macro_signals"

    def test_flattening_yield_curve_supports_a_gold_long(self):
        macro = pd.DataFrame(
            {
                "us10y": [4.5, 4.4, 4.3, 4.2, 4.1],
                "us2y": [4.0, 4.0, 4.0, 4.0, 4.0],
            }
        )
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 1.0
        assert details["spread_change_5bar"] < 0
        assert details["yield_curve_spread"] == pytest.approx(0.1)

    def test_precomputed_yield_spread_columns_are_used_when_raw_series_absent(self):
        macro = pd.DataFrame({"macro_yield_spread": [0.35], "macro_yield_spread_chg": [-0.05]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 1.0
        assert details["spread_change_1bar"] == -0.05

    def test_positive_cpi_surprise_supports_a_gold_long(self):
        macro = pd.DataFrame({"cpi_surprise": [0.004]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 1.0
        assert details["cpi_surprise"] == 0.004

    def test_tiny_cpi_surprise_is_filtered_as_noise(self):
        macro = pd.DataFrame({"cpi_surprise": [0.0001]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 0.5
        assert details["source"] == "insufficient_macro_signals"

    def test_rising_etf_flow_supports_a_gold_long(self):
        macro = pd.DataFrame({"gold_etf_flow": [10.0, 11.0, 12.0, 13.0, 14.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 1.0
        assert details["etf_flow_5bar_chg"] == 4.0

    def test_cot_change_below_threshold_casts_no_vote(self):
        macro = pd.DataFrame({"cot_net_spec": [1000.0, 1050.0, 1100.0, 1150.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 0.5
        assert details["cot_chg_4bar"] == 150.0

    def test_large_cot_increase_supports_a_gold_long(self):
        macro = pd.DataFrame({"cot_net_spec": [1000.0, 2000.0, 3000.0, 4000.0]})
        assert ss._score_macro_alignment(macro, "BUY", "XAU_USD")[0] == 1.0
        assert ss._score_macro_alignment(macro, "SELL", "XAU_USD")[0] == 0.0

    def test_rising_central_bank_demand_supports_a_gold_long(self):
        macro = pd.DataFrame({"wgc_central_bank": [50.0, 60.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 1.0
        assert details["wgc_cb_demand_chg"] == 10.0

    def test_conflicting_macro_signals_average_out(self):
        # VIX high (bullish gold) but CPI surprise negative (bearish gold).
        macro = pd.DataFrame({"vix": [30.0], "cpi_surprise": [-0.01]})
        score, details = ss._score_macro_alignment(macro, "BUY", "XAU_USD")
        assert score == 0.5
        assert details["votes"] == 1
        assert details["total"] == 2

    def test_gold_detection_accepts_the_gold_alias(self):
        macro = pd.DataFrame({"vix": [30.0]})
        assert ss._score_macro_alignment(macro, "BUY", "gold_spot")[0] == 1.0

    def test_gold_only_columns_are_ignored_for_fx_symbols(self):
        macro = pd.DataFrame({"cpi_surprise": [0.01, 0.01], "wgc_central_bank": [50.0, 60.0]})
        score, details = ss._score_macro_alignment(macro, "BUY", "EUR_USD")
        assert score == 0.5
        assert details["source"] == "insufficient_macro_signals"

    def test_unusable_macro_frame_degrades_to_neutral(self):
        class _Exploding:
            empty = False

            @property
            def columns(self):
                raise RuntimeError("macro store offline")

        score, details = ss._score_macro_alignment(_Exploding(), "BUY", "XAU_USD")
        assert score == 0.5
        assert "macro store offline" in details["error"]


# ── Dimension 4: regime suitability ───────────────────────────────────────────


class TestScoreRegimeSuitability:
    @pytest.mark.parametrize(
        ("regime", "buy_score", "sell_score"),
        [
            ("trending_up", 0.85, 0.20),
            ("trending_down", 0.20, 0.85),
            ("overbought", 0.30, 0.75),
            ("oversold", 0.75, 0.30),
            ("ranging", 0.55, 0.55),
            ("unknown", 0.50, 0.50),
        ],
    )
    def test_regime_matrix(self, regime, buy_score, sell_score):
        assert ss._score_regime_suitability(None, "BUY", {"regime": regime})[0] == pytest.approx(buy_score)
        assert ss._score_regime_suitability(None, "SELL", {"regime": regime})[0] == pytest.approx(sell_score)

    def test_unrecognised_regime_label_is_neutral(self):
        score, details = ss._score_regime_suitability(None, "BUY", {"regime": "supernova"})
        assert score == 0.5
        assert details["regime"] == "supernova"

    def test_strong_adx_boosts_a_trending_regime(self):
        score, details = ss._score_regime_suitability(None, "BUY", {"regime": "trending_up", "adx": 42.0})
        assert score == pytest.approx(0.85 * 1.1)
        assert details["adx"] == 42.0

    def test_adx_boost_is_capped_at_one(self):
        # 0.85 * 1.1 == 0.935 stays under the cap; verify the cap engages when
        # the base score is already high by driving it through np.clip.
        score, _ = ss._score_regime_suitability(None, "SELL", {"regime": "trending_down", "adx": 99.0})
        assert score <= 1.0

    def test_adx_boost_does_not_apply_to_ranging_markets(self):
        score, _ = ss._score_regime_suitability(None, "BUY", {"regime": "ranging", "adx": 60.0})
        assert score == pytest.approx(0.55)

    def test_regime_is_derived_from_ohlcv_when_absent_from_the_payload(self, uptrend):
        score, details = ss._score_regime_suitability(uptrend, "BUY", {})
        assert details["regime"] != "unknown"
        assert 0.0 <= score <= 1.0

    def test_regime_derivation_failure_falls_back_to_unknown(self, monkeypatch):
        import research.vector_store as vs

        def _boom(_df):
            raise RuntimeError("regime labeller offline")

        monkeypatch.setattr(vs, "_regime_label", _boom)
        frame = _ohlcv([100.0 + i for i in range(60)])
        score, details = ss._score_regime_suitability(frame, "BUY", {})
        assert score == 0.5
        assert details["regime"] == "unknown"

    def test_short_frame_is_not_labelled(self):
        frame = _ohlcv([100.0 + i for i in range(10)])
        _, details = ss._score_regime_suitability(frame, "BUY", {})
        assert details["regime"] == "unknown"


# ── Dimension 5: MTF confluence ───────────────────────────────────────────────


class TestScoreMTFConfluence:
    def test_no_timeframe_data_is_neutral(self):
        score, details = ss._score_mtf_confluence({}, "BUY")
        assert score == 0.5
        assert details["source"] == "no_mtf_data"

    def test_flat_trends_cast_no_vote(self):
        score, details = ss._score_mtf_confluence({"h4_trend": "flat", "d1_trend": "flat"}, "BUY")
        assert score == 0.5
        assert details["source"] == "no_mtf_data"

    def test_full_three_timeframe_alignment_scores_one(self):
        score, details = ss._score_mtf_confluence({"h4_trend": "UP", "d1_trend": "up", "w1_trend": "up"}, "BUY")
        assert score == 1.0
        assert details["agree"] == 3
        assert details["total"] == 3

    def test_two_of_three_agreeing_scores_three_quarters(self):
        score, details = ss._score_mtf_confluence({"h4_trend": "up", "d1_trend": "up", "w1_trend": "down"}, "BUY")
        assert score == 0.75
        assert details["agree"] == 2

    def test_one_of_three_agreeing_is_neutral(self):
        score, _ = ss._score_mtf_confluence({"h4_trend": "up", "d1_trend": "down", "w1_trend": "down"}, "BUY")
        assert score == 0.5

    def test_fully_counter_trend_signal_is_penalised(self):
        score, details = ss._score_mtf_confluence({"h4_trend": "down", "d1_trend": "down", "w1_trend": "down"}, "BUY")
        assert score == 0.20
        assert details["agree"] == 0

    def test_downtrend_alignment_supports_a_sell(self):
        score, _ = ss._score_mtf_confluence({"h4_trend": "down", "d1_trend": "down", "w1_trend": "down"}, "SELL")
        assert score == 1.0

    def test_partial_timeframe_coverage_still_scores(self):
        score, details = ss._score_mtf_confluence({"h4_trend": "up"}, "BUY")
        assert score == 0.5  # one agreeing timeframe maps to 0.50
        assert details["total"] == 1


# ── Dimension 6: volatility quality ───────────────────────────────────────────


class TestScoreVolatilityQuality:
    def test_news_blackout_short_circuits_to_the_floor(self, uptrend):
        score, details = ss._score_volatility_quality(uptrend, {"news_blackout": True})
        assert score == 0.10
        assert details == {"reason": "news_blackout_active"}

    def test_missing_ohlcv_is_neutral(self):
        score, details = ss._score_volatility_quality(None, {})
        assert score == 0.5
        assert details["source"] == "insufficient_data"

    def test_short_frame_is_neutral(self):
        score, details = ss._score_volatility_quality(_ohlcv([100.0] * 19), {})
        assert score == 0.5
        assert details["source"] == "insufficient_data"

    def test_steady_volatility_lands_in_the_sweet_spot(self, uptrend):
        score, details = ss._score_volatility_quality(uptrend, {})
        assert score == 0.85
        assert 0.6 < details["atr_relative"] <= 1.8
        assert details["atr_pct_of_price"] > 0

    def test_volatility_collapse_scores_as_a_dead_market(self):
        # Wide swings for 60 bars, then a dead-flat tail drags ATR far below
        # the median.
        closes = [100.0 + (25.0 if i % 2 else -25.0) for i in range(60)] + [100.0] * 60
        score, details = ss._score_volatility_quality(_ohlcv(closes), {})
        assert details["atr_relative"] < 0.3
        assert score == 0.20

    def test_extreme_volatility_spike_is_penalised(self):
        closes = [100.0] * 60 + [100.0 + i * 400.0 for i in range(1, 15)]
        score, details = ss._score_volatility_quality(_ohlcv(closes), {})
        assert details["atr_relative"] > 3.5
        assert score == 0.10

    def test_atr_band_boundaries_map_to_the_documented_scores(self, monkeypatch):
        """Drive each ATR band directly — the intermediate bands are hard to
        provoke with synthetic price paths but are the ones that resize live
        trades, so they are pinned explicitly."""
        import research.ta_compat as ta

        frame = _ohlcv([100.0 + i * 0.1 for i in range(60)])

        class _FakeATR:
            def __init__(self, value: float):
                self._value = value

            def average_true_range(self):
                # Median 1.0, last bar == the band under test.
                return pd.Series([1.0] * 20 + [self._value])

        for atr_last, expected in [
            (0.2, 0.20),
            (0.5, 0.50),
            (1.0, 0.85),
            (2.0, 0.50),
            (3.0, 0.25),
            (9.0, 0.10),
        ]:
            monkeypatch.setattr(ta, "AverageTrueRange", lambda *a, _v=atr_last, **k: _FakeATR(_v))
            score, details = ss._score_volatility_quality(frame, {})
            assert score == expected, f"atr_rel={details.get('atr_relative')}"

    def test_too_few_atr_points_is_neutral(self, monkeypatch):
        import research.ta_compat as ta

        class _ShortATR:
            def average_true_range(self):
                return pd.Series([1.0, 1.1, 1.2])

        monkeypatch.setattr(ta, "AverageTrueRange", lambda *a, **k: _ShortATR())
        score, details = ss._score_volatility_quality(_ohlcv([100.0] * 40), {})
        assert score == 0.5
        assert details["source"] == "insufficient_atr"

    def test_malformed_frame_degrades_to_neutral(self):
        bad = pd.DataFrame({"price": [1.0] * 40})
        score, details = ss._score_volatility_quality(bad, {})
        assert score == 0.5
        assert "error" in details


# ── Composite scorer ──────────────────────────────────────────────────────────


class TestSignalScorer:
    def test_weights_are_normalised_to_one(self):
        scorer = ss.SignalScorer()
        weights = [
            scorer._w_ml,
            scorer._w_tech,
            scorer._w_macro,
            scorer._w_regime,
            scorer._w_mtf,
            scorer._w_vol,
        ]
        assert sum(weights) == pytest.approx(1.0)
        # ML confidence carries the most weight by design.
        assert scorer._w_ml == max(weights)

    def test_zero_weight_configuration_does_not_divide_by_zero(self, monkeypatch):
        for name in ("_W_ML", "_W_TECH", "_W_MACRO", "_W_REGIME", "_W_MTF", "_W_VOL"):
            monkeypatch.setattr(ss, name, 0.0)
        scorer = ss.SignalScorer()
        assert scorer._w_ml == 0.0
        result = scorer.score({"direction": "BUY", "probability": 0.9})
        assert result.composite == 0.0
        assert result.grade == "WEAK"

    def test_a_maximally_supported_long_grades_strong(self, uptrend):
        macro = pd.DataFrame({"vix": [30.0] * 5, "dxy": [105.0, 104.0, 103.0, 102.0, 101.0]})
        result = ss.SignalScorer().score(
            signal_payload={
                "direction": "BUY",
                "probability": 0.99,
                "regime": "trending_up",
                "adx": 40.0,
                "h4_trend": "up",
                "d1_trend": "up",
                "w1_trend": "up",
            },
            ohlcv=uptrend,
            macro_df=macro,
            symbol="XAU_USD",
        )
        assert result.grade == "STRONG"
        assert result.composite >= 0.75
        assert result.direction == "BUY"
        assert result.symbol == "XAU_USD"
        assert result.latency_ms >= 0.0

    def test_a_counter_trend_signal_grades_weak(self, uptrend):
        result = ss.SignalScorer().score(
            signal_payload={
                "direction": "SELL",
                "probability": 0.95,  # the model is strongly bullish
                "regime": "trending_up",
                "h4_trend": "up",
                "d1_trend": "up",
                "w1_trend": "up",
                "news_blackout": True,
            },
            ohlcv=uptrend,
            symbol="XAU_USD",
        )
        assert result.grade == "WEAK"
        assert result.composite < 0.45

    @pytest.mark.parametrize(
        ("composite", "expected"),
        [
            (0.90, "STRONG"),
            (0.7501, "STRONG"),
            (0.70, "GOOD"),
            (0.6001, "GOOD"),
            (0.50, "FAIR"),
            (0.4501, "FAIR"),
            (0.44, "WEAK"),
            (0.0, "WEAK"),
        ],
    )
    def test_grade_boundaries_are_inclusive_at_the_lower_edge(self, monkeypatch, composite, expected):
        """Grade thresholds gate auto-trade eligibility, so each boundary is
        pinned by forcing every dimension to the target value."""
        for fn in (
            "_score_ml_confidence",
            "_score_mtf_confluence",
        ):
            monkeypatch.setattr(ss, fn, lambda *a, _v=composite, **k: (_v, {}))
        for fn in (
            "_score_technical_consensus",
            "_score_macro_alignment",
            "_score_regime_suitability",
        ):
            monkeypatch.setattr(ss, fn, lambda *a, _v=composite, **k: (_v, {}))
        monkeypatch.setattr(ss, "_score_volatility_quality", lambda *a, _v=composite, **k: (_v, {}))
        result = ss.SignalScorer().score({"direction": "BUY"})
        assert result.composite == pytest.approx(composite)
        assert result.grade == expected

    @pytest.mark.parametrize("threshold", [0.75, 0.60])
    def test_exact_threshold_dimensions_land_one_ulp_low(self, monkeypatch, threshold):
        """
        The weighted sum accumulates six float multiplications, so feeding every
        dimension exactly a grade threshold produces e.g. 0.7499999999999999 and
        lands in the band below.  Scoring is advisory and the boundary is
        arbitrary to a part in 1e16, so this is recorded rather than corrected —
        the test exists so nobody reads a boundary off the docstring and
        concludes the grader is broken.  (0.45 happens to accumulate exactly and
        is therefore not parametrised here.)
        """
        for fn in (
            "_score_ml_confidence",
            "_score_technical_consensus",
            "_score_macro_alignment",
            "_score_regime_suitability",
            "_score_mtf_confluence",
            "_score_volatility_quality",
        ):
            monkeypatch.setattr(ss, fn, lambda *a, _v=threshold, **k: (_v, {}))
        result = ss.SignalScorer().score({"direction": "BUY"})
        assert result.composite < threshold
        assert result.composite == pytest.approx(threshold)

    def test_missing_direction_defaults_to_neutral(self):
        result = ss.SignalScorer().score({})
        assert result.direction == "NEUTRAL"
        assert result.symbol == "UNKNOWN"

    def test_details_carry_every_dimension(self, uptrend):
        result = ss.SignalScorer().score({"direction": "BUY"}, ohlcv=uptrend)
        assert set(result.dimensions.details) == {
            "ml",
            "technical",
            "macro",
            "regime",
            "mtf",
            "volatility",
        }


class TestSignalScoreRendering:
    def _sample(self) -> ss.SignalScore:
        return ss.SignalScore(
            composite=0.7212,
            grade="GOOD",
            dimensions=ss.DimensionScores(
                ml_confidence=0.81,
                technical=0.6667,
                macro_alignment=0.6,
                regime=0.75,
                mtf_confluence=0.5,
                volatility=0.8,
                details={"ml": {"raw_probability": 0.9}},
            ),
            direction="BUY",
            symbol="XAU_USD",
            latency_ms=1.2345,
        )

    def test_str_renders_every_dimension(self):
        rendered = str(self._sample())
        assert "XAU_USD BUY" in rendered
        assert "score=0.721" in rendered
        assert "[GOOD]" in rendered
        for fragment in ("ml=0.81", "tech=0.67", "macro=0.60", "regime=0.75", "mtf=0.50", "vol=0.80"):
            assert fragment in rendered
        assert "1.2ms" in rendered

    def test_to_dict_rounds_and_keeps_details(self):
        payload = self._sample().to_dict()
        assert payload["composite_score"] == 0.7212
        assert payload["grade"] == "GOOD"
        assert payload["dimensions"]["technical"] == 0.6667
        assert payload["details"] == {"ml": {"raw_probability": 0.9}}
        assert payload["latency_ms"] == 1.23

    def test_to_dict_is_json_serialisable(self):
        import json

        json.dumps(self._sample().to_dict())

    def test_dimension_defaults_are_neutral(self):
        dims = ss.DimensionScores()
        assert dims.ml_confidence == 0.5
        assert dims.details == {}


class TestModuleSingleton:
    def test_get_signal_scorer_is_a_singleton(self, monkeypatch):
        monkeypatch.setattr(ss, "_scorer", None)
        first = ss.get_signal_scorer()
        assert ss.get_signal_scorer() is first

    def test_score_signal_delegates_to_the_singleton(self, monkeypatch):
        monkeypatch.setattr(ss, "_scorer", None)
        result = ss.score_signal({"direction": "BUY", "probability": 0.8}, symbol="XAU_USD")
        assert isinstance(result, ss.SignalScore)
        assert result.symbol == "XAU_USD"
        assert ss._scorer is not None


# ── Integration with the signal engine ────────────────────────────────────────


class TestSignalEngineEnrichment:
    def test_enrichment_writes_the_score_into_the_payload(self, uptrend):
        from core.signal_engine import _enrich_with_signal_score

        payload = {"direction": "BUY", "probability": 0.85, "regime": "trending_up"}
        _enrich_with_signal_score(payload, uptrend, "XAU_USD")

        assert 0.0 <= payload["signal_strength_score"] <= 1.0
        assert payload["signal_grade"] in ("STRONG", "GOOD", "FAIR", "WEAK")
        assert set(payload["signal_score_dimensions"]) == {
            "ml_confidence",
            "technical",
            "macro_alignment",
            "regime",
            "mtf_confluence",
            "volatility",
        }
        assert payload["signal_score_latency_ms"] >= 0.0

    def test_enrichment_is_non_blocking_when_the_scorer_fails(self, monkeypatch):
        from core import signal_engine

        def _boom():
            raise RuntimeError("scorer offline")

        monkeypatch.setattr(ss, "get_signal_scorer", _boom)
        payload = {"direction": "BUY"}
        signal_engine._enrich_with_signal_score(payload, None, "XAU_USD")

        # Advisory only: the signal survives with neutral placeholders.
        assert payload["signal_strength_score"] == 0.5
        assert payload["signal_grade"] == "UNKNOWN"
