# HOPEFX-AI-TRADING
# Tests for brokers/advanced_orders, brokers/ohlcv_store,
# data_layer/sentiment/scorer, risk/post_trade_analyzer
from __future__ import annotations

import pytest


# ===========================================================================
# brokers/advanced_orders
# ===========================================================================

from brokers.advanced_orders import (
    AdvancedOrderManager,
    BracketOrder,
    OCOOrder,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TrailingStopOrder,
)


def _make_order(symbol="XAUUSD", side=OrderSide.BUY, qty=1.0, price=2000.0, otype=OrderType.LIMIT) -> Order:
    import uuid

    return Order(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        order_type=otype,
        quantity=qty,
        price=price,
    )


class TestAdvancedOrderDataclasses:
    def test_order_to_dict(self):
        o = _make_order()
        d = o.to_dict()
        for k in ("id", "symbol", "side", "order_type", "quantity", "status"):
            assert k in d

    def test_order_status_default_pending(self):
        o = _make_order()
        assert o.status == OrderStatus.PENDING

    def test_oco_to_dict(self):
        import uuid

        o1 = _make_order()
        o2 = _make_order(side=OrderSide.SELL, otype=OrderType.STOP)
        oco = OCOOrder(id=str(uuid.uuid4()), symbol="XAUUSD", order1=o1, order2=o2)
        d = oco.to_dict()
        assert "order1" in d
        assert "order2" in d
        assert d["status"] == "pending"

    def test_bracket_to_dict(self):
        import uuid

        entry = _make_order(otype=OrderType.MARKET)
        sl = _make_order(side=OrderSide.SELL, otype=OrderType.STOP, price=1950.0)
        tp = _make_order(side=OrderSide.SELL, otype=OrderType.LIMIT, price=2050.0)
        bracket = BracketOrder(
            id=str(uuid.uuid4()),
            symbol="XAUUSD",
            side=OrderSide.BUY,
            entry_order=entry,
            stop_loss_order=sl,
            take_profit_order=tp,
        )
        d = bracket.to_dict()
        assert "entry_order" in d
        assert "stop_loss_order" in d
        assert "take_profit_order" in d

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"

    def test_time_in_force_values(self):
        assert TimeInForce.GTC.value == "gtc"
        assert TimeInForce.DAY.value == "day"
        assert TimeInForce.IOC.value == "ioc"


class TestAdvancedOrderManager:
    def _make_manager(self):
        return AdvancedOrderManager(broker_callback=None)

    def test_create_order_returns_order(self):
        mgr = self._make_manager()
        order = mgr.create_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=2000.0,
        )
        assert order is not None
        assert order.symbol == "XAUUSD"

    def test_create_trailing_stop(self):
        mgr = self._make_manager()
        order = mgr.create_trailing_stop(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=1.0,
            trail_amount=10.0,
            activation_price=2010.0,
        )
        assert isinstance(order, TrailingStopOrder)
        assert order.trail_amount == pytest.approx(10.0)

    def test_create_oco_order(self):
        mgr = self._make_manager()
        oco = mgr.create_oco_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=1.0,
            limit_price=2050.0,
            stop_price=1950.0,
        )
        assert isinstance(oco, OCOOrder)

    def test_create_bracket_order(self):
        mgr = self._make_manager()
        bracket = mgr.create_bracket_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=1.0,
            entry_type=OrderType.LIMIT,
            entry_price=2000.0,
            stop_loss_price=1950.0,
            take_profit_price=2050.0,
        )
        assert isinstance(bracket, BracketOrder)

    def test_get_order_returns_none_for_unknown(self):
        mgr = self._make_manager()
        assert mgr.get_order("nonexistent") is None

    def test_get_open_orders_empty(self):
        mgr = self._make_manager()
        orders = mgr.get_open_orders()
        assert isinstance(orders, list)

    def test_cancel_order_unknown_returns_false(self):
        mgr = self._make_manager()
        assert mgr.cancel_order("nonexistent") is False

    def test_cancel_order_pending(self):
        mgr = self._make_manager()
        order = mgr.create_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=2000.0,
        )
        result = mgr.cancel_order(order.id)
        assert result is True

    def test_handle_order_fill(self):
        mgr = self._make_manager()
        order = mgr.create_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        mgr.handle_order_fill(order.id, fill_price=2001.0, fill_quantity=1.0)
        updated = mgr.get_order(order.id)
        assert updated is not None

    def test_update_trailing_stop(self):
        mgr = self._make_manager()
        order = mgr.create_trailing_stop(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=1.0,
            trail_amount=10.0,
        )
        mgr.update_trailing_stop(order.id, current_price=2020.0)
        # Should not raise


# ===========================================================================
# brokers/ohlcv_store
# ===========================================================================

from brokers.ohlcv_store import OHLCVStore, get_ohlcv_store


class TestOHLCVStore:
    def _make_bar(self, ts_offset: int = 0) -> dict:
        import time

        return {
            "bar_open_ts": time.time() - ts_offset,
            "open": 2000.0,
            "high": 2005.0,
            "low": 1995.0,
            "close": 2002.0,
            "volume": 1000.0,
        }

    def test_push_and_get(self):
        store = OHLCVStore(timeframe="H1", max_bars=500)
        for i in range(10):
            store.push("XAUUSD", self._make_bar(i * 3600))
        df = store.get("XAUUSD", bars=10)
        assert df is not None
        assert len(df) == 10

    def test_get_empty_returns_none(self):
        store = OHLCVStore()
        result = store.get("UNKNOWN", bars=10)
        assert result is None

    def test_allow_partial_false_returns_none_when_insufficient(self):
        store = OHLCVStore(max_bars=500)
        # Force in-memory path by making _get_cache always return None
        store._get_cache = lambda: None
        store.push("TEST_PARTIAL_FALSE", self._make_bar())
        result = store.get("TEST_PARTIAL_FALSE", bars=100, allow_partial=False)
        assert result is None

    def test_allow_partial_true_returns_available(self):
        store = OHLCVStore(max_bars=500)
        store._get_cache = lambda: None
        store.push("TEST_PARTIAL_TRUE", self._make_bar())
        result = store.get("TEST_PARTIAL_TRUE", bars=100, allow_partial=True)
        assert result is not None
        assert len(result) == 1

    def test_buffer_size(self):
        store = OHLCVStore(max_bars=500)
        assert store.buffer_size("XAUUSD") == 0
        store.push("XAUUSD", self._make_bar())
        assert store.buffer_size("XAUUSD") == 1

    def test_symbols(self):
        store = OHLCVStore(max_bars=500)
        store.push("XAUUSD", self._make_bar())
        store.push("EURUSD", self._make_bar())
        assert "XAUUSD" in store.symbols()
        assert "EURUSD" in store.symbols()

    def test_health(self):
        store = OHLCVStore(max_bars=500)
        h = store.health()
        assert "redis_ok" in h
        assert "timeframe" in h
        assert "symbols" in h

    def test_max_bars_ring_buffer(self):
        store = OHLCVStore(max_bars=5)
        for i in range(10):
            store.push("XAUUSD", self._make_bar(i))
        assert store.buffer_size("XAUUSD") == 5

    def test_singleton(self):
        s1 = get_ohlcv_store()
        s2 = get_ohlcv_store()
        assert s1 is s2


# ===========================================================================
# data_layer/sentiment/scorer
# ===========================================================================

from data_layer.sentiment.scorer import GoldSentimentScorer
from data_layer.types import NewsArticle, NewsSource
from datetime import datetime, timezone as _tz


def _make_article(headline: str, summary: str = "", sentiment_score: float = 0.0) -> NewsArticle:
    now = datetime.now(_tz.utc)
    return NewsArticle(
        article_id="test-1",
        source=NewsSource.FINNHUB,
        headline=headline,
        summary=summary,
        url="https://example.com",
        published_at=now,
        fetched_at=now,
        sentiment_score=sentiment_score,
        sentiment_label="neutral",
        gold_relevance=0.0,
        impact_score=0.0,
    )


class TestGoldSentimentScorer:
    def test_score_gold_bullish(self):
        scorer = GoldSentimentScorer()
        article = _make_article("Gold price surges on Fed rate cut expectations")
        result = scorer.score(article)
        assert result.gold_relevance > 0
        assert result.sentiment_label in ("bullish", "neutral", "bearish")

    def test_score_irrelevant_article(self):
        scorer = GoldSentimentScorer()
        article = _make_article("Local sports team wins championship game")
        result = scorer.score(article)
        assert result.gold_relevance == 0.0
        assert result.sentiment_score == 0.0

    def test_score_article_alias(self):
        scorer = GoldSentimentScorer()
        article = _make_article("Gold futures rise amid inflation fears")
        r1 = scorer.score(article)
        r2 = scorer.score_article(article)
        assert r1.sentiment_score == r2.sentiment_score

    def test_pre_scored_article_used_directly(self):
        scorer = GoldSentimentScorer()
        article = _make_article("Gold rally continues", sentiment_score=0.8)
        result = scorer.score(article)
        # Pre-scored articles with gold relevance should preserve direction
        assert isinstance(result.sentiment_score, float)

    def test_get_aggregate_signal_no_articles(self):
        scorer = GoldSentimentScorer()
        signal = scorer.get_aggregate_signal(articles=None)
        assert isinstance(signal, dict)
        assert "news_sentiment_score" in signal

    def test_get_aggregate_signal_with_articles(self):
        scorer = GoldSentimentScorer()
        articles = [
            scorer.score(_make_article("Gold price rises on safe haven demand")),
            scorer.score(_make_article("XAU/USD climbs as dollar weakens")),
        ]
        signal = scorer.get_aggregate_signal(articles=articles)
        assert isinstance(signal, dict)
        assert "news_sentiment_score" in signal

    def test_score_returns_news_article(self):
        scorer = GoldSentimentScorer()
        article = _make_article("Gold bullion demand increases")
        result = scorer.score(article)
        assert isinstance(result, NewsArticle)

    def test_impact_score_bounded(self):
        scorer = GoldSentimentScorer()
        article = _make_article("Gold price surges to record high on inflation data")
        result = scorer.score(article)
        assert 0.0 <= result.impact_score <= 1.0


# ===========================================================================
# risk/post_trade_analyzer
# ===========================================================================

from risk.post_trade_analyzer import FillRecord, PostTradeAnalyzer


def _record_fill(analyzer: PostTradeAnalyzer, slippage_bps: float = 1.0) -> FillRecord:
    """Helper: record a fill with given slippage."""
    fill_price = 2000.0 * (1 + slippage_bps / 10_000)
    return analyzer.record_fill(
        trade_id="t1",
        symbol="XAUUSD",
        side="long",
        lots=1.0,
        decision_price=2000.0,
        fill_price=fill_price,
        mid_at_fill=2000.0,
        spread_at_fill=0.3,
        bar_open=1999.0,
        bar_high=2005.0,
        bar_low=1995.0,
        bar_close=2002.0,
    )


class TestPostTradeAnalyzer:
    def test_record_fill_returns_fill_record(self):
        analyzer = PostTradeAnalyzer()
        record = _record_fill(analyzer)
        assert isinstance(record, FillRecord)

    def test_slippage_bps_computed(self):
        analyzer = PostTradeAnalyzer()
        record = _record_fill(analyzer, slippage_bps=2.0)
        assert isinstance(record.slippage_bps, float)

    def test_rolling_stats_empty(self):
        analyzer = PostTradeAnalyzer()
        stats = analyzer.rolling_stats()
        assert isinstance(stats, dict)

    def test_rolling_stats_with_fills(self):
        analyzer = PostTradeAnalyzer()
        for _ in range(5):
            _record_fill(analyzer, slippage_bps=1.5)
        stats = analyzer.rolling_stats(window=5)
        assert isinstance(stats, dict)
        assert "mean_slippage_bps" in stats or len(stats) > 0

    def test_get_fills_returns_list(self):
        analyzer = PostTradeAnalyzer()
        _record_fill(analyzer)
        fills = analyzer.get_fills(limit=10)
        assert isinstance(fills, list)
        assert len(fills) == 1

    def test_fill_quality_bounded(self):
        analyzer = PostTradeAnalyzer()
        record = _record_fill(analyzer)
        assert 0.0 <= record.fill_quality <= 1.0

    def test_impl_shortfall_computed(self):
        analyzer = PostTradeAnalyzer()
        record = _record_fill(analyzer)
        assert isinstance(record.impl_shortfall_bps, float)

    def test_multiple_fills_tracked(self):
        analyzer = PostTradeAnalyzer()
        for i in range(3):
            _record_fill(analyzer, slippage_bps=float(i))
        fills = analyzer.get_fills(limit=10)
        assert len(fills) == 3
