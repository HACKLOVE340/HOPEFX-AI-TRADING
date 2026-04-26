# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/multi_source_feed.py
================================
MultiSourceTickFeed — production-grade multi-symbol tick ingestion engine.

Fallback chain per symbol (configurable via config/multi_source_feed.yaml):
  1. yFinance      — free, no key, ~1-2 s polling
  2. Alpha Vantage — free tier 25 req/day; ALPHA_VANTAGE_KEY required
  3. Twelve Data   — free tier 800 credits/day; TWELVE_API_KEY required

Architecture
------------
* One asyncio polling loop per symbol runs concurrently.
* Each loop walks the fallback chain until a valid price is obtained.
* Per-source circuit breakers open after N consecutive failures and
  re-close after a configurable cooldown.
* Validated ticks are:
    - Written to Redis as  tick:SYMBOL  (SET with TTL)
    - Published to Redis pub/sub channel  hopefx:tick:SYMBOL
    - Also published to the legacy  hopefx:tick  channel (CH_TICK)
    - Also appended to the legacy  price_queue  list (NuclearStreamer compat)
    - Broadcast to all in-process subscribers via on_new_price(price)
* Prometheus gauges track last price, latency, and source per symbol.
* A health-monitor coroutine rotates the active source when data goes stale.

Usage
-----
    feed = MultiSourceTickFeed()
    feed.subscribe(brain)           # any object with on_new_price(price)
    await feed.start()              # non-blocking background tasks
    ...
    await feed.stop()

    # Or use the module-level singleton:
    from data_feed.multi_source_feed import get_multi_source_feed
    feed = get_multi_source_feed()
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
import yaml

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Optional: Prometheus ──────────────────────────────────────────────────────
try:
    from prometheus_client import Gauge as _Gauge

    _PROM_AVAILABLE = True
    _PRICE_GAUGE = _Gauge(
        "msf_last_price",
        "MultiSourceFeed last validated price",
        ["symbol", "source"],
    )
    _LATENCY_GAUGE = _Gauge(
        "msf_fetch_latency_ms",
        "MultiSourceFeed fetch round-trip latency in ms",
        ["symbol", "source"],
    )
    _SOURCE_GAUGE = _Gauge(
        "msf_active_source",
        "MultiSourceFeed active source index (0=yfinance,1=av,2=td)",
        ["symbol"],
    )
except Exception:
    _PROM_AVAILABLE = False
    _PRICE_GAUGE = _LATENCY_GAUGE = _SOURCE_GAUGE = None  # type: ignore

# ── Optional: Redis ───────────────────────────────────────────────────────────
try:
    import redis.asyncio as _aioredis  # type: ignore

    _REDIS_AVAILABLE = True
except ImportError:
    _aioredis = None  # type: ignore
    _REDIS_AVAILABLE = False
    logger.warning("redis package not installed — Redis publishing disabled. pip install redis")

_CONFIG_PATH = Path("config/multi_source_feed.yaml")
_FALLBACK_ORDER = ["yfinance", "alpha_vantage", "twelve_data"]


def _resolve_env(value: Any) -> str:
    """Expand ${ENV_VAR:default} placeholders in YAML string values."""
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        # Handle nested placeholders like ${A:${B:}}
        if inner.startswith("${"):
            inner = inner[2:-1]
        var, _, default = inner.partition(":")
        # Recursively resolve nested default
        resolved_default = _resolve_env(default) if default.startswith("${") else default
        return os.environ.get(var.strip(), resolved_default)
    return value


def _load_config(path: Path = _CONFIG_PATH) -> dict:
    if not path.exists():
        logger.warning("multi_source_feed.yaml not found at %s — using defaults", path)
        return {}

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


