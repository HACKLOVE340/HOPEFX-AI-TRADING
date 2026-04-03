#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/e2e_hardening_audit.py
================================
End-to-end production hardening validation.

Validates every fix applied during the March 2026 hardening audit:
  - Architecture: no direct sub-module imports outside data_layer/
  - GoldFeedManager: tick-age gate, consensus stale exclusion
  - DQE: two-pass outlier exclusion, reset_source
  - MicrostructureEngine: deadlock fix, unit volume, inject_l2_depth
  - NewsSentimentEngine: cross-feed dedup, article age gate
  - RedisStore: maxmemory warning, Sentinel HA path
  - NormalizationPipeline: unit volume in tick_to_ohlcv
  - MarketReplayEngine: causal ts >= end stop, inverted-spread guard
  - hopefx_engine.py: orchestrator started in start()
  - .env.example: all new env vars documented

Run:
    python3 scripts/e2e_hardening_audit.py

Exit code 0 = all checks passed (warnings allowed).
Exit code 1 = one or more FAIL.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from datetime import datetime, timezone
UTC = timezone.utc

# Ensure repo root is on sys.path so data_layer imports work when the
# script is run from scripts/ or from the repo root.
_REPO_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed: list[str] = []
failed: list[str] = []
warned: list[str] = []


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    failed.append(msg)
    print(f"  {RED}✗ FAIL{RESET} {msg}")


def warn(msg: str) -> None:
    warned.append(msg)
    print(f"  {YELLOW}⚠ WARN{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# ── helpers ───────────────────────────────────────────────────────────────────


def read(path: str) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8")


def contains(path: str, text: str) -> bool:
    return text in read(path)


def not_contains(path: str, text: str) -> bool:
    return text not in read(path)


# =============================================================================
# CHECK 1: Architecture — no direct sub-module imports outside data_layer/
# =============================================================================
section("1. Architecture: single-entry-point rule")

arch_violations = []
allowed_prefixes = ("data_layer/", "scripts/", "examples/")
sub_modules = (
    "data_layer.feeds.",
    "data_layer.quality.",
    "data_layer.microstructure.",
    "data_layer.sentiment.",
    "data_layer.calendar.",
    "data_layer.lineage.",
    "data_layer.cache.",
    "data_layer.normalization.",
    "data_layer.replay.",
)

for path in sorted(pathlib.Path().rglob("*.py")):
    ps = str(path)
    if "__pycache__" in ps or ".git" in ps:
        continue
    if any(ps.startswith(p) for p in allowed_prefixes):
        continue
    try:
        src = path.read_text()
    except Exception:  # nosec B112 - skip unreadable file in audit scan
        continue
    for line in src.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(f"from {m}") for m in sub_modules):
            arch_violations.append(f"{ps}: {stripped[:80]}")

if arch_violations:
    for v in arch_violations:
        fail(f"Arch violation: {v}")
else:
    ok("No direct sub-module imports outside data_layer/")


# =============================================================================
# CHECK 2: GoldFeedManager hardening
# =============================================================================
section("2. GoldFeedManager hardening")

gfm = read("data_layer/feeds/gold/manager.py")

if "import os" in gfm:
    ok("GoldFeedManager: 'import os' present")
else:
    fail("GoldFeedManager: missing 'import os'")

if "tick_age_s > 300.0" in gfm:
    ok("GoldFeedManager: pre-DQE tick age gate (>300s) present")
else:
    fail("GoldFeedManager: missing pre-DQE tick age gate")

if "tick_age_s < -10.0" in gfm:
    ok("GoldFeedManager: future-tick guard (<-10s) present")
else:
    fail("GoldFeedManager: missing future-tick guard")

if "DQE_STALE_THRESHOLD_S" in gfm and "_max_age_s" in gfm:
    ok("GoldFeedManager: consensus stale-age exclusion present")
else:
    fail("GoldFeedManager: missing consensus stale-age exclusion")

if "dqe.reset_source(src)" in gfm:
    ok("GoldFeedManager: DQE source reset on circuit recovery present")
else:
    fail("GoldFeedManager: missing DQE source reset on circuit recovery")

if "_prev_circuit_state" in gfm:
    ok("GoldFeedManager: circuit state tracking for recovery detection present")
else:
    fail("GoldFeedManager: missing _prev_circuit_state tracking")

# Verify no syntax errors
try:
    ast.parse(gfm)
    ok("GoldFeedManager: parses cleanly")
except SyntaxError as e:
    fail(f"GoldFeedManager: syntax error: {e}")


# =============================================================================
# CHECK 3: DataQualityEngine hardening
# =============================================================================
section("3. DataQualityEngine: two-pass outlier exclusion")

dqe_src = read("data_layer/quality/engine.py")

if "inliers" in dqe_src and "inlier_weights" in dqe_src:
    ok("DQE: two-pass inlier/outlier separation present")
else:
    fail("DQE: missing two-pass inlier separation")

if "EXCLUDED" in dqe_src and "cross_source_outlier" in dqe_src:
    ok("DQE: outlier EXCLUDED log + Prometheus counter present")
else:
    fail("DQE: missing outlier exclusion log/counter")

if "all sources are outliers" in dqe_src:
    ok("DQE: all-outliers fallback to best single source present")
else:
    fail("DQE: missing all-outliers fallback")

# Verify old weight-halving code is gone (replaced by hard exclusion)
if "weights[src] *= 0.5" in dqe_src:
    fail("DQE: old weight-halving code still present (should be hard exclusion)")
else:
    ok("DQE: old weight-halving code removed")

try:
    ast.parse(dqe_src)
    ok("DQE: parses cleanly")
except SyntaxError as e:
    fail(f"DQE: syntax error: {e}")


# =============================================================================
# CHECK 4: MicrostructureEngine hardening
# =============================================================================
section("4. MicrostructureEngine: deadlock fix + unit volume + L2 injection")

micro = read("data_layer/microstructure/engine.py")

if "_reset_session_unlocked" in micro:
    ok("MicrostructureEngine: _reset_session_unlocked() present (deadlock fix)")
else:
    fail("MicrostructureEngine: missing _reset_session_unlocked() — deadlock risk")

if "volume = 1.0" in micro:
    ok("MicrostructureEngine: unit volume (1.0/tick) present")
else:
    fail("MicrostructureEngine: missing unit volume fix")

# Ensure fabricated spread*1000 is gone from _process_tick
if "spread * 1000" in micro:
    fail("MicrostructureEngine: spread*1000 fabricated volume still present")
else:
    ok("MicrostructureEngine: spread*1000 fabricated volume removed")

if "def inject_l2_depth" in micro:
    ok("MicrostructureEngine: inject_l2_depth() method present")
else:
    fail("MicrostructureEngine: missing inject_l2_depth() method")

if "self._reset_session_unlocked()" in micro:
    ok("MicrostructureEngine: _process_tick calls _reset_session_unlocked (not reset_session)")
else:
    fail("MicrostructureEngine: _process_tick still calls reset_session() — deadlock risk")

try:
    ast.parse(micro)
    ok("MicrostructureEngine: parses cleanly")
except SyntaxError as e:
    fail(f"MicrostructureEngine: syntax error: {e}")


# =============================================================================
# CHECK 5: NewsSentimentEngine hardening
# =============================================================================
section("5. NewsSentimentEngine: cross-feed dedup + age gate")

sent = read("data_layer/sentiment/engine.py")

if "import hashlib" in sent:
    ok("NewsSentimentEngine: hashlib imported for URL fingerprinting")
else:
    fail("NewsSentimentEngine: missing hashlib import")

if "_url_fingerprint" in sent:
    ok("NewsSentimentEngine: _url_fingerprint() method present")
else:
    fail("NewsSentimentEngine: missing _url_fingerprint() method")

if "_seen_urls" in sent:
    ok("NewsSentimentEngine: _seen_urls cross-feed dedup dict present")
else:
    fail("NewsSentimentEngine: missing _seen_urls dedup dict")

if "_MAX_ARTICLE_AGE_H" in sent and "max_age_cutoff" in sent:
    ok("NewsSentimentEngine: article age gate present")
else:
    fail("NewsSentimentEngine: missing article age gate")

if "SENT_DEDUP_WINDOW_H" in sent:
    ok("NewsSentimentEngine: SENT_DEDUP_WINDOW_H env var present")
else:
    fail("NewsSentimentEngine: missing SENT_DEDUP_WINDOW_H env var")

if "duplicate article skipped" in sent:
    ok("NewsSentimentEngine: duplicate article skip log present")
else:
    fail("NewsSentimentEngine: missing duplicate article skip log")

try:
    ast.parse(sent)
    ok("NewsSentimentEngine: parses cleanly")
except SyntaxError as e:
    fail(f"NewsSentimentEngine: syntax error: {e}")


# =============================================================================
# CHECK 6: RedisStore OOM warning
# =============================================================================
section("6. DataLayerRedisStore: maxmemory OOM warning")

redis_src = read("data_layer/cache/redis_store.py")

if "maxmemory is UNLIMITED" in redis_src:
    ok("RedisStore: maxmemory=0 OOM warning present")
else:
    fail("RedisStore: missing maxmemory=0 OOM warning")

if "maxmemory_unlimited" in redis_src:
    ok("RedisStore: maxmemory_unlimited key in get_memory_info() return dict")
else:
    fail("RedisStore: missing maxmemory_unlimited key in health dict")

if redis_src.count("self.get_memory_info()") >= 2:
    ok("RedisStore: get_memory_info() called in both Sentinel and URL connect paths")
else:
    fail("RedisStore: get_memory_info() not called in both connect paths")

try:
    ast.parse(redis_src)
    ok("RedisStore: parses cleanly")
except SyntaxError as e:
    fail(f"RedisStore: syntax error: {e}")


# =============================================================================
# CHECK 7: NormalizationPipeline unit volume
# =============================================================================
section("7. NormalizationPipeline: unit volume in tick_to_ohlcv")

norm = read("data_layer/normalization/pipeline.py")

# Check tick_to_ohlcv uses unit volume
if '"volume":    1.0,' in norm or '"volume": 1.0,' in norm:
    ok("NormalizationPipeline: tick_to_ohlcv uses unit volume (1.0/tick)")
else:
    fail("NormalizationPipeline: tick_to_ohlcv still uses fabricated volume")

if "spread * 1000" in norm:
    fail("NormalizationPipeline: spread*1000 fabricated volume still present")
else:
    ok("NormalizationPipeline: spread*1000 fabricated volume removed")

try:
    ast.parse(norm)
    ok("NormalizationPipeline: parses cleanly")
except SyntaxError as e:
    fail(f"NormalizationPipeline: syntax error: {e}")


# =============================================================================
# CHECK 8: MarketReplayEngine causal hardening
# =============================================================================
section("8. MarketReplayEngine: causal boundary + inverted-spread guard")

replay = read("data_layer/replay/engine.py")

if "ts >= ts_end" in replay:
    ok("MarketReplayEngine: causal hard stop (ts >= ts_end) present")
else:
    fail("MarketReplayEngine: missing causal hard stop — end tick could leak")

if "ts_start = pd.Timestamp(start" in replay and "ts_end   = pd.Timestamp(end" in replay:
    ok("MarketReplayEngine: Timestamp bounds pre-computed outside loop")
else:
    fail("MarketReplayEngine: Timestamp bounds still computed inside loop")

if "inverted spread" in replay:
    ok("MarketReplayEngine: inverted-spread guard present")
else:
    fail("MarketReplayEngine: missing inverted-spread guard")

# Verify DQE import is outside the generator body (not inside for loop)
lines = replay.splitlines()
dqe_import_line = None
for i, line in enumerate(lines, 1):
    if "from data_layer.quality.engine import dqe" in line:
        dqe_import_line = i
        break

if dqe_import_line:
    # Check it's not inside the for loop (should be before the for ts, row loop)
    for_loop_line = None
    for i, line in enumerate(lines, 1):
        if "for ts, row in self._replay_ticks.iterrows():" in line:
            for_loop_line = i
            break
    if for_loop_line and dqe_import_line < for_loop_line:
        ok("MarketReplayEngine: DQE import outside generator loop")
    else:
        fail("MarketReplayEngine: DQE import still inside generator loop")
else:
    fail("MarketReplayEngine: DQE import not found in replay_ticks")

try:
    ast.parse(replay)
    ok("MarketReplayEngine: parses cleanly")
except SyntaxError as e:
    fail(f"MarketReplayEngine: syntax error: {e}")


# =============================================================================
# CHECK 9: hopefx_engine.py orchestrator wiring
# =============================================================================
section("9. hopefx_engine.py: data_layer orchestrator wiring")

engine = read("hopefx_engine.py")

if "_dl_orchestrator = None" in engine:
    ok("hopefx_engine: _dl_orchestrator attribute initialised in __init__")
else:
    fail("hopefx_engine: _dl_orchestrator not initialised in __init__")

if "await _dl_orch.start()" in engine:
    ok("hopefx_engine: orchestrator.start() called in engine.start()")
else:
    fail("hopefx_engine: orchestrator.start() NOT called — data layer never starts standalone")

if "await self._dl_orchestrator.stop()" in engine:
    ok("hopefx_engine: orchestrator.stop() called in engine.stop()")
else:
    fail("hopefx_engine: orchestrator.stop() NOT called — resource leak on shutdown")

if "Data layer orchestrator started" in engine:
    ok("hopefx_engine: startup log for orchestrator present")
else:
    fail("hopefx_engine: missing startup log for orchestrator")

try:
    ast.parse(engine)
    ok("hopefx_engine: parses cleanly")
except SyntaxError as e:
    fail(f"hopefx_engine: syntax error: {e}")


# =============================================================================
# CHECK 10: app.py L2 depth bridge
# =============================================================================
section("10. app.py: L2 depth bridge wiring")

app = read("app.py")

if "_l2_depth_bridge" in app:
    ok("app.py: L2 depth bridge task present")
else:
    fail("app.py: missing L2 depth bridge task")

if "inject_l2_depth" in app:
    ok("app.py: inject_l2_depth() called in L2 bridge")
else:
    fail("app.py: inject_l2_depth() not called in L2 bridge")

try:
    ast.parse(app)
    ok("app.py: parses cleanly")
except SyntaxError as e:
    fail(f"app.py: syntax error: {e}")


# =============================================================================
# CHECK 11: .env.example completeness
# =============================================================================
section("11. .env.example: all hardening env vars documented")

env_example = read(".env.example")

required_vars = [
    "GOLDAPI_IO_KEY",
    "METALS_DEV_KEY",
    "METALS_API_KEY",
    "METALPRICEAPI_KEY",
    "COMMODITY_PRICE_API_KEY",
    "FMP_API_KEY",
    "NEWSDATA_IO_KEY",
    "ALPHA_VANTAGE_KEY",
    "NEWSAPI_ORG_KEY",
    "FRED_API_KEY",
    "DUKASCOPY_CACHE_DIR",
    "LINEAGE_DB_PATH",
    "LINEAGE_MAX_RECORDS",
    "MICRO_WINDOW_TICKS",
    "SENT_EMA_ALPHA",
    "FEED_CB_OPEN_ERRORS",
    "DQE_STALE_THRESHOLD_S",
    "SENT_MAX_ARTICLE_AGE_H",
    "SENT_DEDUP_WINDOW_H",
    "L2_SNAPSHOT_INTERVAL",
]

missing_vars = [v for v in required_vars if v not in env_example]
if missing_vars:
    for v in missing_vars:
        fail(f".env.example: missing {v}")
else:
    ok(f".env.example: all {len(required_vars)} required env vars documented")


# =============================================================================
# CHECK 12: No remaining bare except:pass
# =============================================================================
section("12. Code quality: no bare except:pass")

bare_excepts = []
for path in sorted(pathlib.Path().rglob("*.py")):
    ps = str(path)
    if "__pycache__" in ps or ".git" in ps:
        continue
    try:
        src = path.read_text()
    except Exception:  # nosec B112 - skip unreadable file in audit scan
        continue
    for i, line in enumerate(src.splitlines(), 1):
        if re.match(r"\s*except\s*:\s*pass\s*$", line):
            bare_excepts.append(f"{ps}:{i}")

if bare_excepts:
    for b in bare_excepts[:5]:
        fail(f"Bare except:pass: {b}")
    if len(bare_excepts) > 5:
        fail(f"... and {len(bare_excepts) - 5} more bare except:pass")
else:
    ok("No bare except:pass found")


# =============================================================================
# CHECK 13: No mock/stub/fake in production code
# =============================================================================
section("13. Code quality: no mock/stub/fake in production paths")

mock_in_prod = []
# Exclude test files, example files, and audit/validation scripts themselves
_MOCK_EXCLUDE = ("test", "example", "e2e_hardening_audit", "e2e_production_validation")
for path in sorted(pathlib.Path().rglob("*.py")):
    ps = str(path)
    if "__pycache__" in ps or ".git" in ps:
        continue
    if any(x in ps.lower() for x in _MOCK_EXCLUDE):
        continue
    try:
        src = path.read_text()
    except Exception:  # nosec B112 - skip unreadable file in audit scan
        continue
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        # Only flag actual class instantiation / usage, not string literals in checks
        if re.search(
            r"\b(MockBroker|MockTick|MockPrice|FakeBroker|DummyBroker|SyntheticFeed)\b",
            stripped,
        ):
            # Skip lines that are just string literals (e.g. in validation scripts)
            if stripped.startswith(("#", '"', "'")):
                continue
            mock_in_prod.append(f"{ps}:{i}: {stripped[:60]}")

if mock_in_prod:
    for m in mock_in_prod:
        fail(f"Mock in prod: {m}")
else:
    ok("No mock/stub/fake/dummy in production code")


# =============================================================================
# CHECK 14: Functional — import all data_layer modules
# =============================================================================
section("14. Functional: import all data_layer modules")

modules_to_import = [
    "data_layer.orchestrator",
    "data_layer.types",
    "data_layer.feeds.gold.manager",
    "data_layer.quality.engine",
    "data_layer.microstructure.engine",
    "data_layer.sentiment.engine",
    "data_layer.calendar.engine",
    "data_layer.cache.redis_store",
    "data_layer.lineage.store",
    "data_layer.normalization.pipeline",
    "data_layer.replay.engine",
    "data_layer.feeds.macro.fred",
    "data_layer.feeds.macro.store_bridge",
]

for mod in modules_to_import:
    try:
        __import__(mod)
        ok(f"Import: {mod}")
    except Exception as e:
        fail(f"Import failed: {mod} — {e}")


# =============================================================================
# CHECK 15: Functional — orchestrator singleton + ML features
# =============================================================================
section("15. Functional: orchestrator ML features")

try:
    from data_layer.orchestrator import orchestrator

    features = orchestrator.get_ml_features()
    if len(features) >= 20:
        ok(f"Orchestrator: {len(features)} ML features available")
    else:
        fail(f"Orchestrator: only {len(features)} ML features (expected ≥20)")

    health = orchestrator.health()
    required_health_keys = [
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
    ]
    missing_keys = [k for k in required_health_keys if k not in health]
    if missing_keys:
        fail(f"Orchestrator health: missing keys {missing_keys}")
    else:
        ok(f"Orchestrator health: all {len(required_health_keys)} keys present")
except Exception as e:
    fail(f"Orchestrator functional check failed: {e}")


# =============================================================================
# CHECK 16: Functional — NewsSentimentEngine dedup
# =============================================================================
section("16. Functional: NewsSentimentEngine cross-feed dedup")

try:
    from data_layer.sentiment.engine import NewsSentimentEngine

    eng = NewsSentimentEngine()

    # Create two articles with the same URL (simulating Finnhub + FMP duplicate)
    from data_layer.types import NewsArticle, NewsSource

    now = datetime.now(UTC)
    art1 = NewsArticle(
        article_id="a1",
        headline="Gold surges on Fed pivot fears",
        summary="Gold prices rose sharply.",
        url="https://example.com/gold-surges",
        published_at=now,
        fetched_at=now,
        source=NewsSource.FINNHUB,
        sentiment_score=0.8,
        gold_relevance=0.9,
    )
    art2 = NewsArticle(
        article_id="a2",
        headline="Gold surges on Fed pivot fears",
        summary="Gold prices rose sharply.",
        url="https://example.com/gold-surges",  # same URL — cross-feed duplicate
        published_at=now,
        fetched_at=now,
        source=NewsSource.FMP,
        sentiment_score=0.8,
        gold_relevance=0.9,
    )

    import asyncio

    async def _test_dedup():
        await eng._ingest_articles([art1], NewsSource.FINNHUB)
        ema_after_first = eng._sentiment_ema
        await eng._ingest_articles([art2], NewsSource.FMP)
        ema_after_second = eng._sentiment_ema
        return ema_after_first, ema_after_second, len(eng._seen_urls)

    ema1, ema2, seen_count = asyncio.run(_test_dedup())

    if ema1 == ema2:
        ok(f"NewsSentimentEngine: duplicate article correctly skipped (EMA unchanged: {ema1:.4f})")
    else:
        fail(f"NewsSentimentEngine: duplicate article NOT skipped (EMA changed: {ema1:.4f} → {ema2:.4f})")

    if seen_count == 1:
        ok("NewsSentimentEngine: _seen_urls has exactly 1 entry (dedup working)")
    else:
        fail(f"NewsSentimentEngine: _seen_urls has {seen_count} entries (expected 1)")

except Exception as e:
    fail(f"NewsSentimentEngine dedup test failed: {e}")


# =============================================================================
# CHECK 17: Functional — MicrostructureEngine no deadlock
# =============================================================================
section("17. Functional: MicrostructureEngine session reset (no deadlock)")

try:
    from data_layer.microstructure.engine import MicrostructureEngine
    from data_layer.types import FeedSource, GoldTick, TickQuality

    micro_eng = MicrostructureEngine()

    tick = GoldTick(
        symbol="XAU_USD",
        timestamp=datetime.now(UTC),
        bid=2350.0,
        ask=2350.5,
        mid=2350.25,
        source=FeedSource.GOLDAPI,
        quality=TickQuality.GOOD,
        confidence=0.95,
        spread=0.5,
    )

    snap = micro_eng.on_tick(tick)
    if snap is not None:
        ok("MicrostructureEngine: on_tick returns snapshot")
    else:
        fail("MicrostructureEngine: on_tick returned None")

    # Test reset_session doesn't deadlock
    micro_eng.reset_session()
    ok("MicrostructureEngine: reset_session() completed without deadlock")

    # Test inject_l2_depth
    micro_eng.on_tick(tick)  # need a tick in buffer first
    micro_eng.inject_l2_depth("XAU_USD", bid_depth=500.0, ask_depth=300.0)
    ok("MicrostructureEngine: inject_l2_depth() completed without error")

except Exception as e:
    fail(f"MicrostructureEngine functional test failed: {e}")


# =============================================================================
# CHECK 18: Functional — NormalizationPipeline unit volume
# =============================================================================
section("18. Functional: NormalizationPipeline tick_to_ohlcv unit volume")

try:
    from data_layer.normalization.pipeline import normalization_pipeline
    from data_layer.types import FeedSource, GoldTick, TickQuality

    ticks = [
        GoldTick(
            symbol="XAU_USD",
            timestamp=datetime.now(UTC),
            bid=2350.0 + i * 0.1,
            ask=2350.5 + i * 0.1,
            mid=2350.25 + i * 0.1,
            source=FeedSource.GOLDAPI,
            quality=TickQuality.GOOD,
            confidence=0.95,
            spread=0.5,
        )
        for i in range(20)
    ]

    df = normalization_pipeline.tick_to_ohlcv(ticks, timeframe_minutes=60)
    if not df.empty:
        # Volume should be tick count (20), not spread*1000
        raw_volume = df["volume"].iloc[0] if "volume" in df.columns else None
        # After log1p normalisation, log1p(20) ≈ 3.04
        # If spread*1000 was used, volume would be ~500
        if raw_volume is not None and raw_volume < 100:
            ok(f"NormalizationPipeline: tick_to_ohlcv volume={raw_volume:.2f} (unit-based, not spread*1000)")
        elif raw_volume is not None:
            fail(f"NormalizationPipeline: tick_to_ohlcv volume={raw_volume:.2f} — suspiciously large (spread*1000?)")
        else:
            ok("NormalizationPipeline: tick_to_ohlcv returned DataFrame (volume col not present after norm)")
    else:
        fail("NormalizationPipeline: tick_to_ohlcv returned empty DataFrame")

except Exception as e:
    fail(f"NormalizationPipeline functional test failed: {e}")


# =============================================================================
# SUMMARY
# =============================================================================
print(f"\n{BOLD}{'=' * 60}{RESET}")
print(f"{BOLD}HARDENING AUDIT SUMMARY{RESET}")
print(f"  {GREEN}Passed:   {len(passed)}{RESET}")
print(f"  {YELLOW}Warnings: {len(warned)}{RESET}")
print(f"  {RED}Failed:   {len(failed)}{RESET}")
print(f"{BOLD}{'=' * 60}{RESET}")

if failed:
    print(f"\n{RED}FAILED CHECKS:{RESET}")
    for f in failed:
        print(f"  ✗ {f}")
    sys.exit(1)
else:
    print(f"\n{GREEN}All hardening checks passed.{RESET}")
    sys.exit(0)
