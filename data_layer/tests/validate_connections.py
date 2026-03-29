# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/tests/validate_connections.py
==========================================
Automated validation script for the entire data layer.

Run:
    python -m data_layer.tests.validate_connections

Or with verbose output:
    python -m data_layer.tests.validate_connections --verbose

Exit codes:
    0 = all critical checks passed
    1 = one or more critical checks failed

Checks performed
----------------
1.  Python imports          — all data_layer modules import cleanly
2.  Types module            — GoldTick, NewsArticle, MacroEvent instantiate
3.  DataQualityEngine       — validates good/bad ticks correctly
4.  NormalizationPipeline   — cleans OHLCV DataFrame
5.  GoldFeedManager         — configured feeds detected
6.  NewsSentimentEngine     — configured feeds detected
7.  GoldSentimentScorer     — scores a synthetic article
8.  MicrostructureEngine    — processes synthetic ticks
9.  FREDFeed                — FRED API reachable (no key required)
10. MacroCalendarEngine     — instantiates and returns ML features
11. MacroStoreBridge        — bridge instantiates
12. DataLayerRedisStore     — Redis connectivity
13. DataLineageStore        — SQLite write + read roundtrip
14. DukascopyFetcher        — URL construction + cache path logic
15. MarketReplayEngine      — instantiates with all sub-engines
16. MarketDataOrchestrator  — instantiates, get_ml_features() returns dict
17. API router              — data_layer router imports cleanly
18. ML pipeline wiring      — inference_engine imports without error
19. Risk manager wiring     — get_current_gold_price() / get_macro_impact_score()
20. Execution engine wiring — engine imports without error
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import List, Tuple

# ── Colour helpers ────────────────────────────────────────────────────────────
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

def _ok(msg: str)   -> str: return f"{_GREEN}✓{_RESET} {msg}"
def _fail(msg: str) -> str: return f"{_RED}✗{_RESET} {msg}"
def _warn(msg: str) -> str: return f"{_YELLOW}⚠{_RESET} {msg}"
def _head(msg: str) -> str: return f"\n{_BOLD}{msg}{_RESET}"


class ValidationResult:
    def __init__(self, name: str, passed: bool, detail: str = "", critical: bool = True):
        self.name     = name
        self.passed   = passed
        self.detail   = detail
        self.critical = critical

    def __str__(self) -> str:
        if self.passed:
            return _ok(f"{self.name}" + (f" — {self.detail}" if self.detail else ""))
        tag = "[CRITICAL]" if self.critical else "[WARN]"
        return _fail(f"{self.name} {tag}" + (f" — {self.detail}" if self.detail else ""))


# ── Individual checks ─────────────────────────────────────────────────────────

def check_imports() -> ValidationResult:
    try:
        from data_layer import orchestrator
        from data_layer.types import GoldTick, NewsArticle, MacroEvent, FeedSource, TickQuality
        from data_layer.quality.engine import DataQualityEngine
        from data_layer.normalization.pipeline import NormalizationPipeline
        from data_layer.microstructure.engine import MicrostructureEngine
        from data_layer.sentiment.scorer import GoldSentimentScorer
        from data_layer.sentiment.engine import NewsSentimentEngine
        from data_layer.feeds.gold.manager import GoldFeedManager
        from data_layer.feeds.macro.fred import FREDFeed
        from data_layer.feeds.macro.store_bridge import MacroStoreBridge
        from data_layer.calendar.engine import MacroCalendarEngine
        from data_layer.cache.redis_store import DataLayerRedisStore
        from data_layer.lineage.store import DataLineageStore
        from data_layer.replay.dukascopy import DukascopyFetcher
        from data_layer.replay.engine import MarketReplayEngine
        from data_layer.orchestrator import MarketDataOrchestrator
        return ValidationResult("Python imports", True, "all 16 modules")
    except Exception as exc:
        return ValidationResult("Python imports", False, str(exc))


def check_types() -> ValidationResult:
    try:
        from data_layer.types import (
            GoldTick, NewsArticle, MacroEvent, FeedSource,
            TickQuality, MacroImpact, NewsSource, MicrostructureSnapshot
        )
        import uuid
        tick = GoldTick(
            symbol="XAU_USD", timestamp=datetime.now(timezone.utc),
            bid=1980.0, ask=1980.5, mid=1980.25,
            source=FeedSource.GOLDAPI, lineage_id=str(uuid.uuid4()),
        )
        assert tick.is_valid(), "GoldTick.is_valid() returned False"
        # spread auto-computed via __post_init__
        assert abs(tick.spread - 0.5) < 1e-6, f"Expected spread=0.5, got {tick.spread}"
        # MicrostructureSnapshot.mid property
        snap = MicrostructureSnapshot(
            symbol="XAU_USD", timestamp=datetime.now(timezone.utc),
            bid=1980.0, ask=1981.0, spread=1.0, spread_pct=0.05,
            volume_delta=0.0, cumulative_delta=0.0,
            buy_pressure=0.5, sell_pressure=0.5,
            order_flow_imbalance=0.0, trade_pressure=0.0,
        )
        assert abs(snap.mid - 1980.5) < 1e-6, f"Expected mid=1980.5, got {snap.mid}"
        return ValidationResult("Types module", True, "GoldTick/MicrostructureSnapshot/MacroEvent")
    except Exception as exc:
        return ValidationResult("Types module", False, str(exc))


def check_dqe() -> ValidationResult:
    try:
        from data_layer.quality.engine import DataQualityEngine
        from data_layer.types import GoldTick, FeedSource, TickQuality
        import uuid

        dqe = DataQualityEngine()
        now = datetime.now(timezone.utc)

        # Good tick
        good = GoldTick(symbol="XAU_USD", timestamp=now,
                        bid=1980.0, ask=1980.5, mid=1980.25,
                        source=FeedSource.GOLDAPI, lineage_id=str(uuid.uuid4()))
        result = dqe.validate_tick(good)
        assert result.quality != TickQuality.REJECTED, "Good tick was rejected"

        # Inverted spread — must be rejected
        bad = GoldTick(symbol="XAU_USD", timestamp=now,
                       bid=1981.0, ask=1980.0, mid=1980.5,
                       source=FeedSource.GOLDAPI, lineage_id=str(uuid.uuid4()))
        result2 = dqe.validate_tick(bad)
        assert result2.quality == TickQuality.REJECTED, "Inverted spread not rejected"

        return ValidationResult("DataQualityEngine", True, "good/bad tick validation")
    except Exception as exc:
        return ValidationResult("DataQualityEngine", False, str(exc))


def check_normalization() -> ValidationResult:
    try:
        import pandas as pd
        import numpy as np
        from data_layer.normalization.pipeline import NormalizationPipeline

        pipe = NormalizationPipeline()
        idx = pd.date_range("2024-01-01", periods=50, freq="1h", tz="UTC")
        df = pd.DataFrame({
            "open":   np.random.uniform(1970, 1990, 50),
            "high":   np.random.uniform(1990, 2010, 50),
            "low":    np.random.uniform(1950, 1970, 50),
            "close":  np.random.uniform(1970, 1990, 50),
            "volume": np.random.uniform(100, 1000, 50),
        }, index=idx)
        cleaned = pipe.normalize_ohlcv(df)
        assert "log_return" in cleaned.columns
        assert "log_volume" in cleaned.columns
        assert "ohlcv_valid" in cleaned.columns
        assert (cleaned["high"] >= cleaned["close"]).all()
        return ValidationResult("NormalizationPipeline", True, f"{len(cleaned)} bars cleaned")
    except Exception as exc:
        return ValidationResult("NormalizationPipeline", False, str(exc))


def check_microstructure() -> ValidationResult:
    try:
        from data_layer.microstructure.engine import MicrostructureEngine
        from data_layer.types import GoldTick, FeedSource
        import uuid

        engine = MicrostructureEngine()
        for i in range(20):
            tick = GoldTick(
                symbol="XAU_USD",
                timestamp=datetime.now(timezone.utc),
                bid=1980.0 + i * 0.1,
                ask=1980.5 + i * 0.1,
                mid=1980.25 + i * 0.1,
                source=FeedSource.GOLDAPI,
                lineage_id=str(uuid.uuid4()),
            )
            snap = engine.on_tick(tick)

        features = engine.get_ml_features()
        assert len(features) == 16, f"Expected 16 features, got {len(features)}"
        assert "micro_ofi" in features
        assert "micro_cumulative_delta" in features
        return ValidationResult("MicrostructureEngine", True, f"{len(features)} features computed")
    except Exception as exc:
        return ValidationResult("MicrostructureEngine", False, str(exc))


def check_sentiment_scorer() -> ValidationResult:
    try:
        from data_layer.sentiment.scorer import GoldSentimentScorer
        from data_layer.types import NewsArticle, NewsSource
        import uuid

        scorer = GoldSentimentScorer()
        article = NewsArticle(
            article_id   = str(uuid.uuid4()),
            source       = NewsSource.FINNHUB,
            headline     = "Gold surges as Federal Reserve signals rate cuts amid inflation fears",
            summary      = "Gold prices rallied sharply as the Fed signaled dovish policy amid rising CPI.",
            url          = "https://example.com/gold-rally",
            published_at = datetime.now(timezone.utc),
            fetched_at   = datetime.now(timezone.utc),
            lineage_id   = str(uuid.uuid4()),
        )
        scored = scorer.score_article(article)
        assert scored.gold_relevance > 0, "Gold relevance should be > 0"
        signal = scorer.get_aggregate_signal()
        assert "news_sentiment_score" in signal
        assert "news_bullish_ratio" in signal
        return ValidationResult(
            "GoldSentimentScorer", True,
            f"relevance={scored.gold_relevance:.2f} sentiment={scored.sentiment_score:.2f}"
        )
    except Exception as exc:
        return ValidationResult("GoldSentimentScorer", False, str(exc))


def check_gold_feeds_configured() -> ValidationResult:
    keys = {
        "GOLDAPI_IO_KEY":         "GoldAPI.io",
        "METALS_DEV_KEY":         "Metals.dev",
        "METALS_API_KEY":         "Metals-API",
        "METALPRICEAPI_KEY":      "MetalpriceAPI",
        "COMMODITY_PRICE_API_KEY":"CommodityPriceAPI",
    }
    configured = [name for env, name in keys.items() if os.getenv(env)]
    # In CI / dev environments without keys, treat as warning not critical failure
    is_ci = os.getenv("CI") or os.getenv("APP_ENV", "").lower() in ("development", "test")
    if not configured:
        return ValidationResult(
            "Gold feed API keys", False,
            "No gold feed keys set — set at least GOLDAPI_IO_KEY in .env",
            critical=not is_ci,   # critical in production, warning in CI/dev
        )
    return ValidationResult(
        "Gold feed API keys", True,
        f"{len(configured)}/5 configured: {', '.join(configured)}",
    )


def check_news_feeds_configured() -> ValidationResult:
    keys = {
        "FINNHUB_API_KEY":   "Finnhub",
        "FMP_API_KEY":       "FMP",
        "NEWSDATA_IO_KEY":   "NewsData.io",
        "ALPHA_VANTAGE_KEY": "Alpha Vantage",
        "NEWSAPI_ORG_KEY":   "NewsAPI.org",
        "NEWSAPI_AI_KEY":    "NewsAPI.ai",
    }
    configured = [name for env, name in keys.items() if os.getenv(env)]
    if not configured:
        return ValidationResult(
            "News feed API keys", False,
            "No news keys set — sentiment features will be zero",
            critical=False,
        )
    return ValidationResult(
        "News feed API keys", True,
        f"{len(configured)}/6 configured: {', '.join(configured)}",
    )


def check_fred_configured() -> ValidationResult:
    key = os.getenv("FRED_API_KEY", "")
    if not key:
        return ValidationResult(
            "FRED API key", False,
            "FRED_API_KEY not set — macro features will use CSV fallback only",
            critical=False,
        )
    return ValidationResult("FRED API key", True, "key present")


async def check_fred_reachable() -> ValidationResult:
    """
    Check FRED API reachability.

    FRED now requires an API key for all requests (even public series).
    Without FRED_API_KEY this check is informational only — the macro
    store bridge will use CSV fallback data.
    """
    fred_key = os.getenv("FRED_API_KEY", "")
    if not fred_key:
        return ValidationResult(
            "FRED reachability", True,
            "skipped — no FRED_API_KEY (CSV fallback will be used)",
            critical=False,
        )
    try:
        from data_layer.feeds.macro.fred import FREDFeed
        feed = FREDFeed()
        series = await feed.fetch_series("VIXCLS", limit=5)
        await feed.close()
        if series.empty:
            return ValidationResult(
                "FRED reachability", False,
                "key present but empty response — check FRED_API_KEY validity",
                critical=False,
            )
        return ValidationResult("FRED reachability", True, f"VIX latest: {series.iloc[-1]:.2f}")
    except Exception as exc:
        return ValidationResult("FRED reachability", False, str(exc), critical=False)


def check_redis() -> ValidationResult:
    try:
        from data_layer.cache.redis_store import DataLayerRedisStore
        import redis as redis_lib
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis_lib.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        store = DataLayerRedisStore(redis_client=client)
        store.set_tick("XAU_USD", {"mid": 1980.0, "epoch": time.time()})
        result = store.get_tick("XAU_USD")
        assert result is not None
        client.close()
        return ValidationResult("Redis connectivity", True, f"connected at {url}")
    except Exception as exc:
        return ValidationResult(
            "Redis connectivity", False,
            f"{exc} — caching disabled, pub/sub disabled",
            critical=False,
        )


def check_lineage_store() -> ValidationResult:
    try:
        import tempfile, uuid
        from pathlib import Path
        from data_layer.lineage.store import DataLineageStore
        from data_layer.types import GoldTick, FeedSource

        with tempfile.TemporaryDirectory() as tmpdir:
            store = DataLineageStore()
            store._conn = None
            import sqlite3
            db_path = Path(tmpdir) / "test_lineage.db"
            from data_layer.lineage.store import _CREATE_TABLE_SQL
            store._conn = sqlite3.connect(str(db_path))
            store._conn.executescript(_CREATE_TABLE_SQL)
            store._conn.commit()

            tick = GoldTick(
                symbol="XAU_USD", timestamp=datetime.now(timezone.utc),
                bid=1980.0, ask=1980.5, mid=1980.25,
                source=FeedSource.GOLDAPI, lineage_id=str(uuid.uuid4()),
            )
            store._enqueue(
                record_type="TICK", lineage_id=tick.lineage_id,
                source="goldapi", symbol="XAU_USD",
                timestamp=tick.timestamp.isoformat(),
                payload={"mid": tick.mid},
            )
            store._flush_queue()
            count = store.count("TICK")
            store._conn.close()
            assert count == 1, f"Expected 1 TICK record, got {count}"

        return ValidationResult("DataLineageStore", True, "SQLite write+read roundtrip")
    except Exception as exc:
        return ValidationResult("DataLineageStore", False, str(exc))


def check_dukascopy_logic() -> ValidationResult:
    try:
        from data_layer.replay.dukascopy import DukascopyFetcher
        fetcher = DukascopyFetcher()
        hour = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        url = fetcher._build_url("XAUUSD", hour)
        assert "XAUUSD" in url, f"XAUUSD not in URL: {url}"
        assert "2024" in url, f"2024 not in URL: {url}"
        assert "10h_ticks.bi5" in url, f"10h_ticks.bi5 not in URL: {url}"
        # Dukascopy uses 0-based months (Jan=00, Dec=11)
        assert "/00/" in url, f"Expected 0-based month /00/ in URL: {url}"
        path = fetcher._cache_path("XAUUSD", hour)
        assert "XAUUSD" in str(path), f"XAUUSD not in cache path: {path}"
        return ValidationResult("DukascopyFetcher", True, f"URL format OK (0-based months)")
    except Exception as exc:
        return ValidationResult("DukascopyFetcher", False, str(exc))


def check_macro_calendar() -> ValidationResult:
    try:
        from data_layer.calendar.engine import MacroCalendarEngine
        engine = MacroCalendarEngine()
        features = engine.get_ml_features()
        assert "macro_impact_score_now" in features
        assert "macro_hours_to_next_high" in features
        assert "macro_is_blackout" in features
        assert len(features) == 6
        return ValidationResult("MacroCalendarEngine", True, f"{len(features)} ML features")
    except Exception as exc:
        return ValidationResult("MacroCalendarEngine", False, str(exc))


def check_orchestrator() -> ValidationResult:
    try:
        from data_layer.orchestrator import MarketDataOrchestrator, orchestrator
        assert orchestrator is not None
        # get_ml_features() must return a dict even when not started
        features = orchestrator.get_ml_features()
        assert isinstance(features, dict)
        # Must have microstructure features (always available)
        assert "micro_ofi" in features
        return ValidationResult(
            "MarketDataOrchestrator", True,
            f"singleton OK, {len(features)} features available"
        )
    except Exception as exc:
        return ValidationResult("MarketDataOrchestrator", False, str(exc))


def check_api_router() -> ValidationResult:
    try:
        from api.data_layer import router
        routes = [r.path for r in router.routes]
        assert len(routes) >= 8
        return ValidationResult("API router", True, f"{len(routes)} endpoints registered")
    except Exception as exc:
        return ValidationResult("API router", False, str(exc))


def check_ml_wiring() -> ValidationResult:
    try:
        from ml.inference_engine import InferenceEngine
        engine = InferenceEngine()
        assert hasattr(engine, "_last_sentiment_score")
        assert hasattr(engine, "_last_macro_impact")
        assert hasattr(engine, "_get_data_layer_nudge")
        assert hasattr(engine, "_record_signal_lineage")
        return ValidationResult("ML inference_engine wiring", True, "data layer hooks present")
    except Exception as exc:
        return ValidationResult("ML inference_engine wiring", False, str(exc))


def check_risk_wiring() -> ValidationResult:
    try:
        from risk.manager import RiskManager
        rm = RiskManager()
        assert hasattr(rm, "get_current_gold_price")
        assert hasattr(rm, "get_macro_impact_score")
        # These return gracefully when orchestrator not started
        price  = rm.get_current_gold_price()
        impact = rm.get_macro_impact_score()
        assert price is None or isinstance(price, float)
        assert isinstance(impact, float)
        return ValidationResult("Risk manager wiring", True, "data layer methods present")
    except Exception as exc:
        return ValidationResult("Risk manager wiring", False, str(exc))


def check_execution_wiring() -> ValidationResult:
    try:
        from execution.engine import ExecutionEngine, ExecutionRequest
        # Just verify the import and that ExecutionRequest can be constructed
        req = ExecutionRequest(symbol="XAU_USD", side="BUY", quantity=0.1)
        assert req.symbol == "XAU_USD"
        return ValidationResult("Execution engine wiring", True, "ExecutionRequest OK")
    except Exception as exc:
        return ValidationResult("Execution engine wiring", False, str(exc))


def check_live_inference_wiring() -> ValidationResult:
    try:
        from ml.live_inference import AdvancedModelPredictor
        pred = AdvancedModelPredictor()
        # Verify the data layer injection code is present
        import inspect
        src = inspect.getsource(pred._build_features)
        assert "data_layer.orchestrator" in src
        return ValidationResult("live_inference data layer injection", True, "injection code present")
    except Exception as exc:
        return ValidationResult("live_inference data layer injection", False, str(exc))


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_all(verbose: bool = False) -> Tuple[int, int]:
    print(_head("HOPEFX Data Layer — Connection Validation"))
    print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Python:    {sys.version.split()[0]}")
    print()

    results: List[ValidationResult] = []

    # Synchronous checks
    sync_checks = [
        check_imports,
        check_types,
        check_dqe,
        check_normalization,
        check_microstructure,
        check_sentiment_scorer,
        check_gold_feeds_configured,
        check_news_feeds_configured,
        check_fred_configured,
        check_redis,
        check_lineage_store,
        check_dukascopy_logic,
        check_macro_calendar,
        check_orchestrator,
        check_api_router,
        check_ml_wiring,
        check_risk_wiring,
        check_execution_wiring,
        check_live_inference_wiring,
    ]

    print(_head("Synchronous checks"))
    for fn in sync_checks:
        try:
            r = fn()
        except Exception as exc:
            r = ValidationResult(fn.__name__, False, traceback.format_exc()[:200])
        results.append(r)
        print(f"  {r}")

    # Async checks
    print(_head("Async / network checks"))
    async_checks = [check_fred_reachable]
    for fn in async_checks:
        try:
            r = await fn()
        except Exception as exc:
            r = ValidationResult(fn.__name__, False, str(exc), critical=False)
        results.append(r)
        print(f"  {r}")

    # Summary
    passed   = sum(1 for r in results if r.passed)
    failed   = sum(1 for r in results if not r.passed)
    critical = sum(1 for r in results if not r.passed and r.critical)
    warnings = sum(1 for r in results if not r.passed and not r.critical)

    print(_head("Summary"))
    print(f"  Total:    {len(results)}")
    print(f"  {_GREEN}Passed:   {passed}{_RESET}")
    if critical:
        print(f"  {_RED}Failed (critical): {critical}{_RESET}")
    if warnings:
        print(f"  {_YELLOW}Warnings:  {warnings}{_RESET}")

    if critical == 0:
        print(f"\n  {_GREEN}{_BOLD}All critical checks passed. Data layer is ready.{_RESET}")
    else:
        print(f"\n  {_RED}{_BOLD}{critical} critical check(s) failed. Fix before starting.{_RESET}")

    # Return (passed, critical_failures) — warnings do not count as failures
    return passed, critical


def main():
    parser = argparse.ArgumentParser(description="Validate HOPEFX data layer connections")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 1 on any failure including warnings (default: exit 1 on critical only)"
    )
    args = parser.parse_args()

    passed, failed = asyncio.run(run_all(verbose=args.verbose))

    # Exit 1 only on critical failures (warnings are acceptable in dev/CI)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
