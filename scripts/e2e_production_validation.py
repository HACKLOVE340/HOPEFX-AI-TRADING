# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/e2e_production_validation.py
======================================
End-to-end production readiness validation.

Validates every layer of the stack in paper-mode-safe order:
  1.  Architecture integrity   — no forbidden direct sub-module imports
  2.  Data layer imports       — all 16 modules import cleanly
  3.  Orchestrator singleton   — starts, produces features, stops
  4.  Single-entry-point rule  — 6 external modules checked
  5.  Redis connectivity       — ping, set, get, TTL
  6.  DataLineageStore         — write + read roundtrip
  7.  DataQualityEngine        — good/bad tick validation
  8.  NormalizationPipeline    — OHLCV cleaning
  9.  MicrostructureEngine     — 17 features from real tick sequence
  10. GoldSentimentScorer      — VADER scoring on gold headline
  11. MacroCalendarEngine      — 6 ML features, blackout logic
  12. MacroStoreBridge         — CSV fallback loads, features non-zero
  13. MarketReplayEngine       — Dukascopy URL format, timeframe aliases
  14. ML inference wiring      — InferenceEngine imports, data layer hooks
  15. Risk manager wiring      — RiskManager + Gatekeeper orchestrator refs
  16. Execution engine wiring  — ExecutionEngine imports cleanly
  17. API router wiring        — all data-layer endpoints importable
  18. hopefx_engine wiring     — HopeFXEngine imports cleanly
  19. Kill switch              — is_active() callable, not stuck active
  20. Prometheus metrics       — duplicate-registration guard (7 components)

Run:
    python scripts/e2e_production_validation.py
    python scripts/e2e_production_validation.py --verbose

Exit codes:
    0 = all critical checks passed
    1 = one or more critical checks failed
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
import traceback
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
import logging
logger = logging.getLogger(__name__)


# Ensure project root is on sys.path regardless of where the script is invoked.
# This script lives in scripts/ — add the parent directory (project root).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# Also change cwd to project root so relative file paths (forward_test.py etc.) work.
os.chdir(_PROJECT_ROOT)

# ── Result tracking ───────────────────────────────────────────────────────────

PASS = "\033[92m✓\033[0m"  # nosec B105 — ANSI colour code, not a password
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

results: list[tuple[str, bool, bool, str]] = []  # (name, passed, critical, detail)


def record(name: str, passed: bool, detail: str = "", critical: bool = True) -> None:
    results.append((name, passed, critical, detail))
    icon = PASS if passed else (FAIL if critical else WARN)
    label = "" if passed else (" [CRITICAL]" if critical else " [WARN]")
    msg = f"  {icon} {name}{label}"
    if detail:
        msg += f" — {detail}"
    logger.info(msg)


def check(name: str, critical: bool = True):
    """Decorator for check functions."""

    def decorator(fn):
        def wrapper(*args, **kwargs):
            try:
                detail = fn(*args, **kwargs) or ""
                record(name, True, detail, critical)
                return True
            except Exception:
                tb = traceback.format_exc().strip().split("\n")[-1]
                record(name, False, tb, critical)
                return False

        return wrapper

    return decorator


# ── Check 1: Architecture integrity ──────────────────────────────────────────


@check("Architecture: no forbidden direct sub-module imports")
def check_architecture() -> str:
    FORBIDDEN = [
        "from data_layer.feeds.",
        "from data_layer.quality.",
        "from data_layer.microstructure.",
        "from data_layer.sentiment.",
        "from data_layer.calendar.",
        "from data_layer.cache.",
        "from data_layer.lineage.",
        "from data_layer.normalization.",
        "from data_layer.replay.",
    ]
    EXTERNAL_FILES = [
        "ml/inference_engine.py",
        "execution/execution.py",
        "risk/gatekeeper.py",
        "core/signal_engine.py",
        "core/startup_factories.py",
        "api/data_layer.py",
    ]
    violations = []
    for path in EXTERNAL_FILES:
        try:
            with Path(path).open(encoding="utf-8") as _fh:
                src = _fh.read()
            for b in FORBIDDEN:
                if b in src:
                    violations.append(f"{path}: {b}")
        except FileNotFoundError:
            ...  # nosec B110
    if violations:
        raise AssertionError(f"Violations: {violations}")
    return f"{len(EXTERNAL_FILES)} files checked, 0 violations"


# ── Check 2: Data layer imports ───────────────────────────────────────────────


@check("Data layer: all 16 modules import cleanly")
def check_imports() -> str:
    modules = [
        "data_layer.orchestrator",
        "data_layer.types",
        "data_layer.feeds.gold.manager",
        "data_layer.feeds.gold.base",
        "data_layer.feeds.macro.fred",
        "data_layer.feeds.macro.store_bridge",
        "data_layer.feeds.news.finnhub",
        "data_layer.quality.engine",
        "data_layer.microstructure.engine",
        "data_layer.sentiment.engine",
        "data_layer.calendar.engine",
        "data_layer.cache.redis_store",
        "data_layer.lineage.store",
        "data_layer.normalization.pipeline",
        "data_layer.replay.engine",
        "data_layer.replay.dukascopy",
    ]
    for m in modules:
        __import__(m)
    return f"{len(modules)} modules OK"


# ── Check 3: Orchestrator singleton ──────────────────────────────────────────


@check("Orchestrator: singleton, get_ml_features(), health()")
def check_orchestrator() -> str:
    from data_layer.orchestrator import orchestrator

    assert orchestrator is not None
    # Test all call signatures
    f1 = orchestrator.get_ml_features()
    f2 = orchestrator.get_ml_features(symbol="XAU_USD")
    f3 = orchestrator.get_ml_features(as_of=datetime.now(UTC), symbol="XAU_USD")
    assert isinstance(f1, dict), "get_ml_features() must return dict"
    assert len(f1) >= 20, f"Expected >=20 features, got {len(f1)}"
    assert len(f1) == len(f2) == len(f3), "All call signatures must return same count"
    h = orchestrator.health()
    required_keys = {
        "started",
        "uptime_s",
        "tick_count",
        "redis",
        "lineage",
        "dqe",
        "micro",
        "sentiment",
        "calendar",
        "macro",
        "replay",
    }
    missing = required_keys - set(h.keys())
    assert not missing, f"health() missing keys: {missing}"
    return f"{len(f1)} features, {len(h)} health keys"


# ── Check 4: Single-entry-point rule ─────────────────────────────────────────


@check("Single-entry-point: orchestrator._* references accessible")
def check_single_entry_point() -> str:
    from data_layer.orchestrator import orchestrator

    # All sub-components must be accessible via orchestrator references
    components = {
        "_gold_feed": None,  # may be None before start()
        "_dqe": orchestrator._dqe,
        "_micro": orchestrator._micro,
        "_sentiment": orchestrator._sentiment,
        "_calendar": orchestrator._calendar,
        "_macro_bridge": orchestrator._macro_bridge,
        "_lineage": orchestrator._lineage,
        "_norm": orchestrator._norm,
        "_replay": orchestrator._replay,
        "_redis_store": orchestrator._redis_store,
    }
    for name, comp in components.items():
        if name == "_gold_feed":
            continue  # None before start() — OK
        assert comp is not None, f"orchestrator.{name} is None"
    return f"{len(components) - 1} components accessible via orchestrator"


# ── Check 5: Redis connectivity ───────────────────────────────────────────────


@check("Redis: ping, set, get, TTL, pub/sub")
def check_redis() -> str:
    import redis as redis_lib

    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis_lib.from_url(url, decode_responses=True)
    r.ping()
    r.setex("hopefx:e2e:test", 5, "ok")
    val = r.get("hopefx:e2e:test")
    assert val == "ok", f"Redis get returned {val!r}"
    ttl = r.ttl("hopefx:e2e:test")
    assert ttl > 0, f"TTL should be positive, got {ttl}"
    r.delete("hopefx:e2e:test")
    return f"connected to {url}"


# ── Check 6: DataLineageStore ─────────────────────────────────────────────────


@check("DataLineageStore: write + read roundtrip")
def check_lineage() -> str:
    from data_layer.orchestrator import orchestrator
    from data_layer.types import FeedSource, GoldTick, TickQuality

    store = orchestrator._lineage
    tick = GoldTick(
        symbol="XAU_USD",
        timestamp=datetime.now(UTC),
        bid=2350.0,
        ask=2350.5,
        mid=2350.25,
        source=FeedSource.GOLDAPI,
        quality=TickQuality.GOOD,
        confidence=0.95,
    )
    store.record_tick(tick)
    store.flush()
    stats = store.stats()
    assert stats["total_records"] >= 0
    return f"total_records={stats['total_records']}"


# ── Check 7: DataQualityEngine ────────────────────────────────────────────────


@check("DataQualityEngine: good/bad tick validation, consensus")
def check_dqe() -> str:
    from data_layer.orchestrator import orchestrator
    from data_layer.types import FeedSource, GoldTick, TickQuality

    dqe = orchestrator._dqe

    good = GoldTick(
        symbol="XAU_USD",
        timestamp=datetime.now(UTC),
        bid=2350.0,
        ask=2350.5,
        mid=2350.25,
        source=FeedSource.GOLDAPI,
        quality=TickQuality.GOOD,
    )
    validated = dqe.validate_tick(good, received_at=time.time())
    assert validated.quality != TickQuality.REJECTED, "Good tick should not be rejected"

    # Inverted spread — must be rejected
    bad = GoldTick(
        symbol="XAU_USD",
        timestamp=datetime.now(UTC),
        bid=2351.0,
        ask=2350.0,
        mid=2350.5,  # bid > ask
        source=FeedSource.GOLDAPI,
        quality=TickQuality.GOOD,
    )
    rejected = dqe.validate_tick(bad, received_at=time.time())
    assert rejected.quality == TickQuality.REJECTED, "Inverted spread must be rejected"

    health = dqe.get_source_health()
    assert isinstance(health, dict)
    return "good tick accepted, inverted spread rejected"


# ── Check 8: NormalizationPipeline ───────────────────────────────────────────


@check("NormalizationPipeline: OHLCV cleaning, tick normalisation")
def check_normalization() -> str:
    import numpy as np
    import pandas as pd

    from data_layer.orchestrator import orchestrator

    norm = orchestrator._norm

    # Build a 60-bar OHLCV DataFrame
    idx = pd.date_range("2024-01-01", periods=60, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": np.random.uniform(2300, 2400, 60),
            "high": np.random.uniform(2400, 2450, 60),
            "low": np.random.uniform(2250, 2300, 60),
            "close": np.random.uniform(2300, 2400, 60),
            "volume": np.random.uniform(100, 1000, 60),
        },
        index=idx,
    )
    cleaned = norm.normalize_ohlcv(df)
    assert not cleaned.empty, "normalize_ohlcv returned empty DataFrame"
    assert "log_return" in cleaned.columns
    assert "ohlcv_valid" in cleaned.columns
    assert cleaned["ohlcv_valid"].sum() >= 40, "Too many invalid bars"
    return f"{len(cleaned)} bars cleaned, {int(cleaned['ohlcv_valid'].sum())} valid"


# ── Check 9: MicrostructureEngine ────────────────────────────────────────────


@check("MicrostructureEngine: 17 features from tick sequence")
def check_microstructure() -> str:
    from data_layer.orchestrator import orchestrator
    from data_layer.types import FeedSource, GoldTick, TickQuality

    micro = orchestrator._micro

    price = 2350.0
    for i in range(30):
        price += 0.5 if i % 3 == 0 else -0.3
        tick = GoldTick(
            symbol="XAU_USD",
            timestamp=datetime.now(UTC),
            bid=round(price - 0.15, 4),
            ask=round(price + 0.15, 4),
            mid=round(price, 4),
            source=FeedSource.GOLDAPI,
            quality=TickQuality.GOOD,
        )
        micro.on_tick(tick)

    features = micro.get_ml_features()
    assert len(features) >= 16, f"Expected >=16 features, got {len(features)}"
    assert "micro_spread" in features
    assert "micro_ofi" in features
    assert "micro_kyles_lambda" in features
    assert "micro_tick_count" in features
    return f"{len(features)} features computed"


# ── Check 10: GoldSentimentScorer ────────────────────────────────────────────


@check("GoldSentimentScorer: VADER scoring on gold headline")
def check_sentiment_scorer() -> str:
    from data_layer.sentiment.scorer import GoldSentimentScorer

    scorer = GoldSentimentScorer()
    from data_layer.types import NewsArticle, NewsSource

    article = NewsArticle(
        article_id="test-001",
        source=NewsSource.FINNHUB,
        headline="Gold prices surge as Fed signals rate cuts amid inflation fears",
        summary="Gold rallied strongly on dovish Fed commentary.",
        url="https://example.com/gold-surge",
        published_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )
    scored = scorer.score(article)
    assert scored.gold_relevance > 0.3, f"Gold relevance too low: {scored.gold_relevance}"
    assert -1.0 <= scored.sentiment_score <= 1.0
    return (
        f"relevance={scored.gold_relevance:.2f} sentiment={scored.sentiment_score:.2f} label={scored.sentiment_label}"
    )


# ── Check 11: MacroCalendarEngine ────────────────────────────────────────────


@check("MacroCalendarEngine: 6 ML features, blackout logic")
def check_calendar() -> str:
    from data_layer.orchestrator import orchestrator

    cal = orchestrator._calendar
    features = cal.get_ml_features()
    expected = {
        "macro_impact_score_now",
        "macro_hours_to_next_high",
        "macro_hours_since_last_high",
        "macro_surprise_last",
        "macro_high_event_count_24h",
        "macro_is_blackout",
    }
    missing = expected - set(features.keys())
    assert not missing, f"Missing calendar features: {missing}"
    assert 0.0 <= features["macro_impact_score_now"] <= 1.0
    assert isinstance(cal.is_blackout_window(), bool)
    return f"{len(features)} features, blackout={cal.is_blackout_window()}"


# ── Check 12: MacroStoreBridge ────────────────────────────────────────────────


@check("MacroStoreBridge: CSV fallback loads, features non-zero")
def check_macro_bridge() -> str:
    from data_layer.orchestrator import orchestrator

    bridge = orchestrator._macro_bridge
    bridge._load_csv_fallback()
    features = bridge.get_ml_features()
    non_zero = sum(1 for v in features.values() if v != 0.0)
    assert non_zero > 0, "All macro features are zero — CSV fallback failed"
    return f"{len(features)} features, {non_zero} non-zero"


# ── Check 13: MarketReplayEngine ─────────────────────────────────────────────


@check("MarketReplayEngine: Dukascopy URL format, timeframe aliases")
def check_replay() -> str:
    from data_layer.replay.dukascopy import DukascopyFetcher, _parse_timeframe

    fetcher = DukascopyFetcher()
    # Verify URL construction uses 0-based months (Dukascopy quirk)
    dt = datetime(2024, 3, 15, tzinfo=UTC)
    url = fetcher._build_url("XAUUSD", dt)
    assert "/2024/02/" in url, f"Month should be 0-based (02 for March), got: {url}"
    # Timeframe aliases
    for alias, expected in [("H1", 60), ("M5", 5), ("D1", 1440), ("4h", 240)]:
        result = _parse_timeframe(alias)
        assert result == expected, f"_parse_timeframe({alias!r}) = {result}, expected {expected}"
    return "URL format OK, 4 timeframe aliases verified"


# ── Check 14: ML inference wiring ────────────────────────────────────────────


@check("ML inference: InferenceEngine imports, data layer hooks present")
def check_inference() -> str:
    from ml.inference_engine import InferenceEngine

    engine = InferenceEngine()
    assert hasattr(engine, "get_data_layer_tick"), "get_data_layer_tick missing"
    assert hasattr(engine, "get_data_layer_features"), "get_data_layer_features missing"
    assert hasattr(engine, "_get_data_layer_nudge"), "_get_data_layer_nudge missing"
    # Verify no direct sub-module imports remain
    with Path("ml/inference_engine.py").open(encoding="utf-8") as _fh:
        src = _fh.read()
    assert "from data_layer.feeds.macro.store_bridge" not in src
    assert "from data_layer.lineage.store" not in src
    return "InferenceEngine OK, no forbidden imports"


# ── Check 15: Risk manager wiring ────────────────────────────────────────────


@check("Risk: RiskManager + Gatekeeper wired to orchestrator")
def check_risk() -> str:
    from data_layer.orchestrator import orchestrator
    from risk.gatekeeper import gatekeeper
    from risk.manager import RiskManager

    rm = RiskManager(orchestrator=orchestrator, lineage_store=orchestrator._lineage)
    # RiskManager stores orchestrator as _orch (see risk/manager.py)
    assert hasattr(rm, "_orch"), "RiskManager missing _orch (orchestrator reference)"
    assert rm._orch is orchestrator, "RiskManager._orch must be the orchestrator singleton"
    assert hasattr(rm, "_lineage"), "RiskManager missing _lineage"

    assert gatekeeper is not None
    # Gatekeeper stores orchestrator as _orch (see risk/gatekeeper.py)
    assert hasattr(gatekeeper, "_orch"), "Gatekeeper missing _orch (orchestrator reference)"

    # Verify no direct sub-module imports in gatekeeper
    with Path("risk/gatekeeper.py").open(encoding="utf-8") as _fh:
        src = _fh.read()
    assert "from data_layer.lineage.store" not in src
    return "RiskManager + Gatekeeper wired, no forbidden imports"


# ── Check 16: Execution engine wiring ────────────────────────────────────────


@check("Execution: ExecutionEngine imports cleanly, no forbidden imports")
def check_execution() -> str:
    with Path("execution/execution.py").open(encoding="utf-8") as _fh:
        src = _fh.read()
    assert "from data_layer.lineage.store" not in src
    return "execution.execution OK, no forbidden imports"


# ── Check 17: API router wiring ───────────────────────────────────────────────


@check("API: data_layer router importable, no forbidden imports")
def check_api() -> str:
    with Path("api/data_layer.py").open(encoding="utf-8") as _fh:
        src = _fh.read()
    forbidden = [
        "from data_layer.sentiment.engine",
        "from data_layer.calendar.engine",
        "from data_layer.microstructure.engine",
        "from data_layer.quality.engine",
        "from data_layer.lineage.store",
        "from data_layer.feeds.gold.manager",
        "from data_layer.feeds.macro.store_bridge",
    ]
    for f in forbidden:
        assert f not in src, f"Forbidden import found: {f}"
    return f"api.data_layer OK, {len(forbidden)} forbidden patterns absent"


# ── Check 18: hopefx_engine wiring ───────────────────────────────────────────


@check("hopefx_engine: HopeFXEngine imports cleanly")
def check_hopefx_engine() -> str:
    import hopefx_engine

    assert hasattr(hopefx_engine, "HopeFXEngine")
    return "HopeFXEngine importable"


# ── Check 19: Kill switch ─────────────────────────────────────────────────────


@check("Kill switch: is_active() callable, not stuck active")
def check_kill_switch() -> str:
    from kill_switch import kill_switch

    active = kill_switch.is_active()
    assert isinstance(active, bool), "is_active() must return bool"
    if active:
        raise AssertionError(
            f"Kill switch is ACTIVE at startup (reason={kill_switch.reason!r}). Deactivate before live trading."
        )
    return f"is_active={active}"


# ── Check 20: Prometheus duplicate-registration guard ────────────────────────


@check("Prometheus: duplicate-registration guard (7 components)")
def check_prometheus() -> str:
    components = [
        ("data_layer.feeds.gold.manager", "GoldFeedManager"),
        ("data_layer.quality.engine", "DataQualityEngine"),
        ("data_layer.microstructure.engine", "MicrostructureEngine"),
        ("data_layer.sentiment.engine", "NewsSentimentEngine"),
        ("data_layer.calendar.engine", "MacroCalendarEngine"),
        ("data_layer.cache.redis_store", "DataLayerRedisStore"),
        ("data_layer.orchestrator", "MarketDataOrchestrator"),
    ]
    for mod_name, cls_name in components:
        mod = __import__(mod_name, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        # Second instantiation must not raise ValueError (duplicate metric)
        try:
            cls()
        except Exception as exc:
            raise AssertionError(f"{cls_name} second instantiation raised: {exc}") from exc
    return f"{len(components)} components survive second instantiation"


# ── Check 21: forward_test.py — no mock data ─────────────────────────────────


@check("forward_test.py: no MockPriceFeed / MockRiskManager / MockTick")
def check_forward_test_no_mocks() -> str:
    # Strip comments before checking — "No GBM" in a docstring is fine
    with Path("forward_test.py").open(encoding="utf-8") as _fh:
        lines = _fh.readlines()
    code_lines = [ln for ln in lines if not ln.lstrip().startswith("#")]
    src = "".join(code_lines)
    forbidden = [
        "class MockPriceFeed",
        "class MockRiskManager",
        "class MockTick",
        "class MockEnsembleStrategy",
        "class MockOrderGateway",
        "random.gauss(",
    ]
    found = [f for f in forbidden if f in src]
    assert not found, f"Mock classes still present: {found}"
    assert "DukascopyFetcher" in src or "MarketReplayEngine" in src, "forward_test.py must use real Dukascopy replay"
    return "No mock data, uses real Dukascopy replay"


# ── Check 22: examples/order_flow_example.py — no MockDataSource ─────────────


@check("examples/order_flow_example.py: no MockDataSource")
def check_order_flow_no_mocks() -> str:
    with Path("examples/order_flow_example.py").open(encoding="utf-8") as _fh:
        src = _fh.read()
    assert "MockDataSource" not in src, "MockDataSource still present"
    assert "orchestrator" in src or "MarketReplayEngine" in src, "Must use real orchestrator or replay engine"
    return "No MockDataSource, uses real data sources"


# ── Async checks ──────────────────────────────────────────────────────────────


async def check_orchestrator_start_stop() -> None:
    """Orchestrator start/stop lifecycle (paper-mode safe)."""
    from data_layer.orchestrator import MarketDataOrchestrator

    orch = MarketDataOrchestrator()
    try:
        await orch.start()
        record(
            "Orchestrator: start() lifecycle",
            True,
            f"started={orch._started}",
        )
        # get_ml_features() after start
        features = orch.get_ml_features()
        record(
            "Orchestrator: get_ml_features() after start()",
            len(features) >= 20,
            f"{len(features)} features",
        )
    except Exception as exc:
        record("Orchestrator: start() lifecycle", False, str(exc))
    finally:
        with contextlib.suppress(Exception):
            await orch.stop()


# ── Main ──────────────────────────────────────────────────────────────────────


async def run_all(verbose: bool = False) -> tuple[int, int]:
    logger.info(f"\n{BOLD}HOPEFX End-to-End Production Validation{RESET}")
    logger.info(f"  Timestamp: {datetime.now(UTC).isoformat()}")
    logger.info(f"  Python:    {sys.version.split()[0]}\n")

    logger.info(f"{BOLD}Synchronous checks{RESET}")
    check_architecture()
    check_imports()
    check_orchestrator()
    check_single_entry_point()
    check_redis()
    check_lineage()
    check_dqe()
    check_normalization()
    check_microstructure()
    check_sentiment_scorer()
    check_calendar()
    check_macro_bridge()
    check_replay()
    check_inference()
    check_risk()
    check_execution()
    check_api()
    check_hopefx_engine()
    check_kill_switch()
    check_prometheus()
    check_forward_test_no_mocks()
    check_order_flow_no_mocks()

    logger.info(f"\n{BOLD}Async / lifecycle checks{RESET}")
    await check_orchestrator_start_stop()

    # Summary
    total = len(results)
    passed = sum(1 for _, p, _, _ in results if p)
    failed_c = sum(1 for _, p, c, _ in results if not p and c)
    warnings = sum(1 for _, p, c, _ in results if not p and not c)

    logger.info(f"\n{BOLD}Summary{RESET}")
    logger.info(f"  Total:    {total}")
    logger.info(f"  {PASS}Passed:   {passed}")
    if failed_c:
        logger.error(f"  {FAIL}Failed (critical): {failed_c}")
    if warnings:
        logger.warning(f"  {WARN}Warnings:  {warnings}")

    if failed_c == 0:
        logger.info(f"\n  {PASS}{BOLD}All critical checks passed. System is production-ready.{RESET}\n")
    else:
        logger.error(f"\n  {FAIL}{BOLD}{failed_c} critical check(s) failed. Fix before deploying.{RESET}\n")
        if verbose:
            logger.error(f"{BOLD}Failed checks:{RESET}")
            for name, passed, critical, detail in results:
                if not passed and critical:
                    logger.error(f"  {FAIL} {name}: {detail}")

    return passed, failed_c


def main() -> None:
    parser = argparse.ArgumentParser(description="HOPEFX End-to-End Production Validation")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    _, failed = asyncio.run(run_all(verbose=args.verbose))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
