# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/data_layer.py
==================
REST endpoints for the data layer orchestrator.

Architecture rule (non-negotiable):
  ALL data is fetched through MarketDataOrchestrator — the single entry point.
  No endpoint may import directly from data_layer sub-modules (feeds/, quality/,
  microstructure/, sentiment/, calendar/, cache/, lineage/).

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
GET  /api/data-layer/ml-features     — complete ML feature set
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any, ClassVar

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-layer", tags=["Data Layer"])


def _get_orchestrator():
    """Return the MarketDataOrchestrator singleton — the ONLY data entry point."""
    try:
        from data_layer.orchestrator import orchestrator

        return orchestrator
    except Exception as exc:
        logger.error("Data layer unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Data layer unavailable — check server logs") from None


@router.get("/health")
async def data_layer_health(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """Full orchestrator health snapshot."""
    orch = _get_orchestrator()
    return orch.health()


@router.get("/tick")
async def get_latest_tick(
    symbol: str = Query("XAU_USD"), user: TokenPayload = Depends(get_current_user)
) -> dict[str, Any]:
    """Latest validated consensus tick.

    Returns the most recent tick from the live feed when available.
    When no live feed is running (e.g. dev environment without API keys),
    returns a 200 with ``available: false`` rather than a 503 so callers
    can distinguish "feed not started" from "service down".
    """
    orch = _get_orchestrator()
    tick = orch.get_latest_tick(symbol)
    if tick is None:
        # Try to get a price from yfinance as a fallback for dev environments
        fallback_price: float | None = None
        try:
            import yfinance as _yf

            _ticker = _yf.Ticker("GC=F" if symbol in ("XAU_USD", "XAUUSD") else symbol)
            _info = _ticker.fast_info
            fallback_price = float(_info.last_price) if hasattr(_info, "last_price") and _info.last_price else None
        except Exception:  # nosec B110
            pass

        if fallback_price is not None:
            return {
                "symbol": symbol,
                "timestamp": datetime.now(UTC).isoformat(),
                "bid": round(fallback_price - 0.10, 5),
                "ask": round(fallback_price + 0.10, 5),
                "mid": fallback_price,
                "spread": 0.20,
                "source": "yfinance_fallback",
                "quality": "low",
                "confidence": 0.5,
                "lineage_id": None,
                "available": True,
                "note": "Live feed not started — using yfinance fallback price",
            }
        return {
            "symbol": symbol,
            "available": False,
            "note": "Live feed not started. Start the orchestrator or configure GOLDAPI_KEY.",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    return {
        "symbol": tick.symbol,
        "timestamp": tick.timestamp.isoformat(),
        "bid": tick.bid,
        "ask": tick.ask,
        "mid": tick.mid,
        "spread": tick.spread,
        "source": tick.source.value,
        "quality": tick.quality.value,
        "confidence": tick.confidence,
        "lineage_id": tick.lineage_id,
        "available": True,
    }


@router.get("/sentiment")
async def get_sentiment(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """Current news sentiment signal for gold — via orchestrator."""
    orch = _get_orchestrator()
    try:
        features = orch.get_ml_features()
        sentiment_features = {k: v for k, v in features.items() if k.startswith("news_")}
        health = orch.health()
        sentiment_health = health.get("sentiment", {})

        recent_articles: ClassVar[list] = []
        try:
            articles = orch._sentiment.get_recent_articles(hours=1.0, min_relevance=0.1)
            recent_articles = [
                {
                    "headline": a.headline[:120],
                    "source": a.source.value,
                    "published_at": a.published_at.isoformat(),
                    "sentiment_score": a.sentiment_score,
                    "sentiment_label": a.sentiment_label,
                    "gold_relevance": a.gold_relevance,
                    "impact_score": a.impact_score,
                }
                for a in articles[:10]
            ]
        except Exception as exc:
            logger.debug("data_layer API: recent articles error: %s", exc)

        return {
            "signal": sentiment_features,
            "health": sentiment_health,
            "recent_articles": recent_articles,
        }
    except Exception as exc:
        logger.error("Data layer endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail="Data unavailable — check server logs") from None


@router.get("/macro")
async def get_macro(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """Current macro features and economic calendar — via orchestrator."""
    orch = _get_orchestrator()
    try:
        features = orch.get_ml_features()
        cal_features = {k: v for k, v in features.items() if k.startswith("macro_")}
        macro_impact = orch.get_macro_impact_score()
        is_blackout = orch.is_blackout_window()

        upcoming: ClassVar[list] = []
        try:
            events = orch._calendar.get_upcoming_events(hours_ahead=24)
            upcoming = [
                {
                    "name": e.name,
                    "country": e.country,
                    "scheduled_at": e.scheduled_at.isoformat(),
                    "impact": e.impact.value,
                    "gold_impact_score": e.gold_impact_score,
                    "forecast": e.forecast,
                    "actual": e.actual,
                    "surprise_pct": e.surprise_pct,
                }
                for e in events
            ]
        except Exception as exc:
            logger.debug("data_layer API: upcoming events error: %s", exc)

        macro_snapshot: ClassVar[dict] = {}
        try:
            macro_snapshot = orch._macro_bridge.snapshot()
        except Exception as exc:
            logger.debug("data_layer API: macro snapshot error: %s", exc)

        return {
            "calendar_features": cal_features,
            "macro_impact_score": macro_impact,
            "is_blackout": is_blackout,
            "upcoming_events": upcoming,
            "fred_snapshot": macro_snapshot,
        }
    except Exception as exc:
        logger.error("Data layer endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail="Data unavailable — check server logs") from None


@router.get("/microstructure")
async def get_microstructure(
    symbol: str = Query("XAU_USD"), user: TokenPayload = Depends(get_current_user)
) -> dict[str, Any]:
    """Current microstructure snapshot — via orchestrator."""
    orch = _get_orchestrator()
    try:
        features = orch.get_ml_features()
        micro_features = {k: v for k, v in features.items() if k.startswith("micro_")}

        snap = orch._micro.get_snapshot()
        snapshot_dict: dict[str, Any] | None = None
        if snap is not None:
            snapshot_dict = {
                "timestamp": snap.timestamp.isoformat(),
                "bid": snap.bid,
                "ask": snap.ask,
                "spread": snap.spread,
                "spread_pct": snap.spread_pct,
                "volume_delta": snap.volume_delta,
                "cumulative_delta": snap.cumulative_delta,
                "buy_pressure": snap.buy_pressure,
                "sell_pressure": snap.sell_pressure,
                "order_flow_imbalance": snap.order_flow_imbalance,
                "trade_pressure": snap.trade_pressure,
                "vwap": snap.vwap,
                "tick_count": snap.tick_count,
            }

        return {
            "symbol": symbol,
            "snapshot": snapshot_dict,
            "features": micro_features,
        }
    except Exception as exc:
        logger.error("Data layer endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail="Data unavailable — check server logs") from None


@router.get("/quality")
async def get_quality_report(
    symbol: str = Query("XAU_USD"), user: TokenPayload = Depends(get_current_user)
) -> dict[str, Any]:
    """Data quality report — via orchestrator."""
    orch = _get_orchestrator()
    try:
        report = orch.get_quality_report(symbol)
        if report is None:
            return {
                "symbol": symbol,
                "message": "No quality data yet — feed not started or no ticks received",
            }
        return {
            "timestamp": report.timestamp.isoformat(),
            "symbol": report.symbol,
            "ticks_received": report.ticks_received,
            "ticks_accepted": report.ticks_accepted,
            "ticks_rejected": report.ticks_rejected,
            "stale_count": report.stale_count,
            "jump_count": report.jump_count,
            "anomaly_count": report.anomaly_count,
            "active_sources": report.active_sources,
            "primary_source": report.primary_source,
            "consensus_price": report.consensus_price,
            "price_spread_across_sources": report.price_spread_across_sources,
            "source_health": orch._dqe.get_source_health(),
        }
    except Exception as exc:
        logger.error("Data layer endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail="Data unavailable — check server logs") from None


@router.get("/lineage")
async def get_lineage(
    record_type: str | None = Query(None),
    symbol: str | None = Query("XAU_USD"),
    limit: int = Query(50, ge=1, le=500),
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Recent lineage records (immutable audit trail) — via orchestrator."""
    orch = _get_orchestrator()
    try:
        records = orch._lineage.query(
            record_type=record_type,
            symbol=symbol,
            limit=limit,
        )
        stats = orch._lineage.stats()
        return {"records": records, "stats": stats}
    except Exception as exc:
        logger.error("Data layer endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail="Data unavailable — check server logs") from None


@router.get("/feeds")
async def get_feed_health(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """Per-feed health and configuration status — via orchestrator."""
    orch = _get_orchestrator()
    try:
        health = orch.health()
        # health() key is "gold_feed" (not "gold_feeds")
        return {
            "gold_feed": health.get("gold_feed", {}),
            "news_feeds": health.get("sentiment", {}).get("feed_health", {}),
            "macro_bridge": health.get("macro", {}),
            "cache_stats": health.get("redis", {}),
            "dqe_health": health.get("dqe", {}),
        }
    except Exception as exc:
        logger.error("Data layer endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail="Data unavailable — check server logs") from None


@router.get("/ml-features")
async def get_ml_features(
    symbol: str = Query("XAU_USD"), user: TokenPayload = Depends(get_current_user)
) -> dict[str, Any]:
    """Complete ML feature set from all data layer components — via orchestrator."""
    orch = _get_orchestrator()
    try:
        features = orch.get_ml_features()
        return {
            "symbol": symbol,
            "features": features,
            "count": len(features),
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:
        logger.error("Data layer endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail="Data unavailable — check server logs") from None
