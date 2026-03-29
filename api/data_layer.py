# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/data_layer.py
==================
REST endpoints for the data layer orchestrator.

Routes
------
GET  /api/data-layer/health          — full orchestrator health snapshot
GET  /api/data-layer/tick            — latest validated XAU/USD tick
GET  /api/data-layer/sentiment       — current news sentiment signal
GET  /api/data-layer/macro           — current macro features + calendar
GET  /api/data-layer/microstructure  — current microstructure snapshot
GET  /api/data-layer/quality         — data quality report
GET  /api/data-layer/lineage         — recent lineage records (audit trail)
GET  /api/data-layer/feeds           — per-feed health and configuration status
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-layer", tags=["Data Layer"])


def _get_orchestrator():
    try:
        from data_layer.orchestrator import orchestrator
        return orchestrator
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Data layer unavailable: {exc}")


@router.get("/health")
async def data_layer_health() -> Dict[str, Any]:
    """Full orchestrator health snapshot."""
    orch = _get_orchestrator()
    return orch.health()


@router.get("/tick")
async def get_latest_tick(symbol: str = Query("XAU_USD")) -> Dict[str, Any]:
    """Latest validated consensus tick."""
    orch = _get_orchestrator()
    tick = orch.get_latest_tick(symbol)
    if tick is None:
        raise HTTPException(status_code=503, detail="No live tick available")
    return {
        "symbol":     tick.symbol,
        "timestamp":  tick.timestamp.isoformat(),
        "bid":        tick.bid,
        "ask":        tick.ask,
        "mid":        tick.mid,
        "spread":     tick.spread,
        "source":     tick.source.value,
        "quality":    tick.quality.value,
        "confidence": tick.confidence,
        "lineage_id": tick.lineage_id,
    }


@router.get("/sentiment")
async def get_sentiment() -> Dict[str, Any]:
    """Current news sentiment signal for gold."""
    try:
        from data_layer.sentiment.engine import news_sentiment_engine
        signal = news_sentiment_engine.get_ml_features()
        articles = news_sentiment_engine.get_recent_articles(limit=10)
        return {
            "signal": signal,
            "recent_articles": [
                {
                    "headline":       a.headline[:120],
                    "source":         a.source.value,
                    "published_at":   a.published_at.isoformat(),
                    "sentiment_score": a.sentiment_score,
                    "sentiment_label": a.sentiment_label,
                    "gold_relevance": a.gold_relevance,
                    "impact_score":   a.impact_score,
                }
                for a in articles
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/macro")
async def get_macro() -> Dict[str, Any]:
    """Current macro features and economic calendar."""
    try:
        from data_layer.calendar.engine import macro_calendar_engine
        from data_layer.feeds.macro.store_bridge import macro_store_bridge

        calendar_features = macro_calendar_engine.get_ml_features()
        macro_features    = macro_store_bridge.get_ml_features()
        upcoming          = macro_calendar_engine.get_upcoming_events(hours_ahead=24)

        return {
            "calendar_features": calendar_features,
            "macro_features":    macro_features,
            "is_blackout":       macro_calendar_engine.is_blackout_window(),
            "impact_score":      macro_calendar_engine.get_current_impact_score(),
            "upcoming_events": [
                {
                    "name":             e.name,
                    "country":          e.country,
                    "scheduled_at":     e.scheduled_at.isoformat(),
                    "impact":           e.impact.value,
                    "gold_impact_score": e.gold_impact_score,
                    "forecast":         e.forecast,
                    "actual":           e.actual,
                    "surprise_pct":     e.surprise_pct,
                }
                for e in upcoming
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/microstructure")
async def get_microstructure(symbol: str = Query("XAU_USD")) -> Dict[str, Any]:
    """Current microstructure snapshot."""
    try:
        from data_layer.microstructure.engine import microstructure_engine
        snap = microstructure_engine.get_snapshot()
        features = microstructure_engine.get_ml_features()
        if snap is None:
            return {"snapshot": None, "features": features}
        return {
            "snapshot": {
                "timestamp":           snap.timestamp.isoformat(),
                "bid":                 snap.bid,
                "ask":                 snap.ask,
                "spread":              snap.spread,
                "spread_pct":          snap.spread_pct,
                "volume_delta":        snap.volume_delta,
                "cumulative_delta":    snap.cumulative_delta,
                "buy_pressure":        snap.buy_pressure,
                "sell_pressure":       snap.sell_pressure,
                "order_flow_imbalance": snap.order_flow_imbalance,
                "trade_pressure":      snap.trade_pressure,
                "vwap":                snap.vwap,
                "tick_count":          snap.tick_count,
            },
            "features": features,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/quality")
async def get_quality_report(symbol: str = Query("XAU_USD")) -> Dict[str, Any]:
    """Data quality report for the given symbol."""
    try:
        from data_layer.quality.engine import dqe
        report = dqe.generate_report(symbol)
        return {
            "timestamp":       report.timestamp.isoformat(),
            "symbol":          report.symbol,
            "ticks_received":  report.ticks_received,
            "ticks_accepted":  report.ticks_accepted,
            "ticks_rejected":  report.ticks_rejected,
            "stale_count":     report.stale_count,
            "jump_count":      report.jump_count,
            "active_sources":  report.active_sources,
            "primary_source":  report.primary_source,
            "consensus_price": report.consensus_price,
            "price_spread_across_sources": report.price_spread_across_sources,
            "source_health":   dqe.get_source_health(),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/lineage")
async def get_lineage(
    record_type: Optional[str] = Query(None),
    symbol: Optional[str] = Query("XAU_USD"),
    limit: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Recent lineage records (immutable audit trail)."""
    try:
        from data_layer.lineage.store import lineage_store
        records = lineage_store.query(
            record_type=record_type,
            symbol=symbol,
            limit=limit,
        )
        stats = lineage_store.stats()
        return {"records": records, "stats": stats}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/feeds")
async def get_feed_health() -> Dict[str, Any]:
    """Per-feed health and configuration status."""
    try:
        from data_layer.feeds.gold.manager import GoldFeedManager
        from data_layer.orchestrator import orchestrator
        health = orchestrator.health()
        return {
            "gold_feeds":  health.get("gold_feeds", {}),
            "news_feeds":  health.get("news", {}).get("feed_health", {}),
            "macro_bridge": health.get("macro_bridge", {}),
            "cache_stats": health.get("cache", {}),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/ml-features")
async def get_ml_features(symbol: str = Query("XAU_USD")) -> Dict[str, Any]:
    """Complete ML feature set from all data layer components."""
    orch = _get_orchestrator()
    features = orch.get_ml_features(symbol=symbol)
    return {
        "symbol":   symbol,
        "features": features,
        "count":    len(features),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
