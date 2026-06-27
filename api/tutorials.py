# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/tutorials.py
================
Video tutorial "Academy" catalogue and per-episode access.

The 15-episode series is fully specified in ``docs/VIDEO_TUTORIALS.md`` (scripts,
chapter markers, thumbnails and the per-episode subscription gate). This router
turns that spec into a product surface: a catalogue the Academy page renders and
a per-episode detail endpoint that enforces the documented plan gate before
returning the playable ``video_url``.

Routes
------
GET /api/tutorials            — full episode catalogue with a per-episode
                                ``locked`` flag computed from the caller's plan.
GET /api/tutorials/{episode}  — one episode. Returns ``video_url`` only when the
                                caller's plan satisfies the episode's gate;
                                otherwise HTTP 403 with the required plan.

Gating mirrors api/ml.py::_check_subscription_gate — admins/superadmins bypass,
plan resolved via monetization.subscription. Episodes whose plan is ``free`` are
the publicly-available onboarding episodes (1–3) and are never locked.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, Depends, HTTPException, status
    from pydantic import BaseModel

    from api.auth import TokenPayload, get_current_user

    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - import guard mirrors sibling routers
    _FASTAPI_AVAILABLE = False
    logger.warning("FastAPI not available — tutorials router disabled")


# ---------------------------------------------------------------------------
# Episode catalogue — single source of truth, mirrors docs/VIDEO_TUTORIALS.md
# `plan` is the minimum tier required to watch (free = public onboarding).
# `video_url` is None until the episode is published; the UI shows the script
# preview (chapters/topics) and a "Coming soon" state while it is None.
# ---------------------------------------------------------------------------

_EPISODES: list[dict[str, Any]] = [
    {
        "episode": 1,
        "title": "Introduction to HOPEFX",
        "level": "Beginner",
        "duration_min": 15,
        "plan": "free",
        "status": "script_ready",
        "summary": "What HOPEFX is, the four-layer architecture, and a live demo of signals and the ML model.",
        "chapters": [
            "0:00 Introduction",
            "1:00 What is HOPEFX?",
            "4:00 Architecture overview",
            "8:00 Live demo",
            "12:00 What's next",
        ],
        "thumbnail_text": "HOPEFX AI Trading — 56.5% OOS Accuracy",
        "video_url": None,
    },
    {
        "episode": 2,
        "title": "Installation & Setup",
        "level": "Beginner",
        "duration_min": 20,
        "plan": "free",
        "status": "script_ready",
        "summary": "Clone, install, configure the .env secrets, run migrations and verify a green health check.",
        "chapters": [
            "0:00 Introduction",
            "2:00 Prerequisites check",
            "2:30 Clone and install",
            "8:00 Environment configuration",
            "13:00 Database setup and first run",
            "17:00 Verify the installation",
        ],
        "thumbnail_text": "Install HOPEFX in 5 minutes",
        "video_url": None,
    },
    {
        "episode": 3,
        "title": "Your First Backtest",
        "level": "Beginner",
        "duration_min": 25,
        "plan": "free",
        "status": "script_ready",
        "summary": "Smoke test, real 50-year gold backtest, running it via the API, and how to read the results honestly.",
        "chapters": [
            "0:00 Introduction",
            "3:00 What is backtesting?",
            "3:30 Smoke test (30 seconds)",
            "10:00 Real data backtest",
            "18:00 Backtest via the API",
            "22:00 Interpreting results",
        ],
        "thumbnail_text": "Backtest 50 Years of Gold Data",
        "video_url": None,
    },
    {
        "episode": 4,
        "title": "Interactive Charting",
        "level": "Beginner–Intermediate",
        "duration_min": 30,
        "plan": "starter",
        "status": "script_ready",
        "summary": "The chart engine, adding indicators, themes/export and live updates over the WebSocket feed.",
        "chapters": [
            "0:00 Introduction",
            "5:00 Creating a candlestick chart",
            "15:00 Adding indicators",
            "22:00 Themes and export",
            "22:30 Real-time chart via WebSocket",
        ],
        "thumbnail_text": "Professional Charts in Python",
        "video_url": None,
    },
    {
        "episode": 5,
        "title": "Technical Indicators Deep Dive",
        "level": "Intermediate",
        "duration_min": 45,
        "plan": "starter",
        "status": "script_ready",
        "summary": "Every built-in indicator explained: moving averages, oscillators, volatility, trend and volume.",
        "chapters": [
            "0:00 Introduction",
            "0:30 Moving averages",
            "10:00 Oscillators",
            "20:00 Volatility",
            "30:00 Trend",
            "38:00 Volume",
        ],
        "thumbnail_text": "All 20+ Indicators Explained",
        "video_url": None,
    },
    {
        "episode": 6,
        "title": "Building Your First Strategy",
        "level": "Intermediate",
        "duration_min": 45,
        "plan": "starter",
        "status": "script_ready",
        "summary": "Write a BaseStrategy subclass, generate signals, register it and backtest it end-to-end.",
        "chapters": [
            "0:00 Introduction",
            "8:00 Strategy structure (BaseStrategy)",
            "20:00 Signal generation logic",
            "30:00 Register and test",
            "30:30 Backtest the strategy",
        ],
        "thumbnail_text": "Build a Trading Strategy in Python",
        "video_url": None,
    },
    {
        "episode": 7,
        "title": "SMC/ICT Strategy",
        "level": "Advanced",
        "duration_min": 60,
        "plan": "enterprise",
        "status": "script_ready",
        "summary": "Smart Money Concepts: order blocks, fair value gaps, liquidity sweeps, the 8 optimal setups, and fusing SMC with ML.",
        "chapters": [
            "0:00 Introduction",
            "15:00 SMC theory",
            "15:30 Order blocks",
            "20:00 Fair value gaps",
            "25:00 Liquidity sweeps",
            "30:00 Built-in SMC strategy",
            "45:00 ITS-8-OS",
            "55:00 Combining SMC with ML",
        ],
        "thumbnail_text": "Smart Money Concepts in Python",
        "video_url": None,
    },
    {
        "episode": 8,
        "title": "ML Trading Introduction",
        "level": "Intermediate",
        "duration_min": 35,
        "plan": "professional",
        "status": "script_ready",
        "summary": "Why ML for trading, the production model, the feature categories, and the abstain mechanism.",
        "chapters": [
            "0:00 Introduction",
            "8:00 Why ML for trading?",
            "8:30 The production model",
            "18:00 Feature categories",
            "28:00 The abstain mechanism",
        ],
        "thumbnail_text": "56.5% OOS Accuracy — How It Works",
        "video_url": None,
    },
    {
        "episode": 9,
        "title": "Training the ML Model",
        "level": "Advanced",
        "duration_min": 50,
        "plan": "elite",
        "status": "script_ready",
        "summary": "When to retrain, the smoke test, a full production retrain, verifying the new model and fallback behaviour.",
        "chapters": [
            "0:00 Introduction",
            "5:00 When to retrain",
            "5:30 Smoke test first",
            "20:00 Full production retrain",
            "40:00 Verify the new model",
            "48:00 Fallback behaviour",
        ],
        "thumbnail_text": "Train Your Own AI Trading Model",
        "video_url": None,
    },
    {
        "episode": 10,
        "title": "Connecting OANDA",
        "level": "Beginner",
        "duration_min": 30,
        "plan": "starter",
        "status": "script_ready",
        "summary": "Create a practice account, configure credentials, validate connectivity and the 30-day paper-trading gate.",
        "chapters": [
            "0:00 Introduction",
            "5:00 Create a practice account",
            "12:00 Configure credentials",
            "20:00 Validate connectivity",
            "28:00 The 30-day paper trading gate",
        ],
        "thumbnail_text": "Connect OANDA in 10 Minutes",
        "video_url": None,
    },
    {
        "episode": 11,
        "title": "Risk Management Masterclass",
        "level": "All levels",
        "duration_min": 50,
        "plan": "starter",
        "status": "script_ready",
        "summary": "Kelly position sizing, daily loss/drawdown limits, the 8-step CVaR pre-trade gate, and the kill switch.",
        "chapters": [
            "0:00 Introduction",
            "10:00 Position sizing (Kelly)",
            "20:00 Daily loss & drawdown limits",
            "30:00 The 8-step pre-trade gate (CVaR)",
            "40:00 Kill switch",
            "40:30 VaR and CVaR explained",
        ],
        "thumbnail_text": "Never Blow Your Account Again",
        "video_url": None,
    },
    {
        "episode": 12,
        "title": "Deploying to Production",
        "level": "Advanced",
        "duration_min": 40,
        "plan": "professional",
        "status": "script_ready",
        "summary": "Pre-deployment checklist, Docker Compose, Nginx + TLS, and monitoring with Grafana/Prometheus.",
        "chapters": [
            "0:00 Introduction",
            "8:00 Pre-deployment checklist",
            "20:00 Docker Compose deployment",
            "30:00 Nginx + TLS",
            "30:30 Monitoring",
        ],
        "thumbnail_text": "Deploy HOPEFX to a VPS",
        "video_url": None,
    },
    {
        "episode": 13,
        "title": "Prop Firm Challenge Guide",
        "level": "Intermediate",
        "duration_min": 45,
        "plan": "professional",
        "status": "script_ready",
        "summary": "Prop firm rules (FTMO, MyFF, The5ers, TopStep), prop-firm mode config, monitoring progress and a passing strategy.",
        "chapters": [
            "0:00 Introduction",
            "10:00 Prop firm rules overview",
            "25:00 Configure prop firm mode",
            "40:00 Monitor challenge progress",
            "40:30 Strategy for passing",
        ],
        "thumbnail_text": "Pass Your Prop Firm Challenge with AI",
        "video_url": None,
    },
    {
        "episode": 14,
        "title": "Social Trading & Copy Trading",
        "level": "Intermediate",
        "duration_min": 30,
        "plan": "professional",
        "status": "script_ready",
        "summary": "Opt into the social feed, browse the leaderboard, follow traders and set up automatic copy trading.",
        "chapters": [
            "0:00 Introduction",
            "8:00 Opt in to the social feed",
            "18:00 Browse the leaderboard",
            "25:00 Follow a trader",
            "25:30 Auto copy trading setup",
        ],
        "thumbnail_text": "Copy the Best Traders Automatically",
        "video_url": None,
    },
    {
        "episode": 15,
        "title": "Monitoring with Grafana",
        "level": "Advanced",
        "duration_min": 35,
        "plan": "professional",
        "status": "script_ready",
        "summary": "Start Grafana/Prometheus, walk the trading/ML/health dashboards and wire up Telegram + email alerts.",
        "chapters": [
            "0:00 Introduction",
            "8:00 Start Grafana and Prometheus",
            "15:00 Trading Performance dashboard",
            "22:00 ML Model Metrics dashboard",
            "28:00 System Health dashboard",
            "30:00 Setting up alerts",
        ],
        "thumbnail_text": "Monitor Your Trading Bot 24/7",
        "video_url": None,
    },
]

_EPISODES_BY_ID: dict[int, dict[str, Any]] = {e["episode"]: e for e in _EPISODES}

# Plan ordering for the "locked" computation when monetization is unavailable.
_PLAN_RANK = {"free": 0, "starter": 1, "professional": 2, "enterprise": 3, "elite": 4}


def _resolve_user_plan(user: Any) -> str:
    """Resolve the caller's active subscription tier, defaulting to 'free'.

    Mirrors api/ml.py::_check_subscription_gate so gating is consistent across
    the app. Any failure degrades safely to 'free' (most restrictive).
    """
    try:
        from monetization.subscription import subscription_manager

        sub = subscription_manager.get_user_subscription(getattr(user, "sub", ""))
        if sub and sub.is_active() and hasattr(sub.tier, "value"):
            return str(sub.tier.value)
    except ImportError:
        logger.debug("monetization.subscription unavailable — defaulting plan to free")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("plan resolution failed (%s) — defaulting to free", exc)
    return "free"


def _has_access(user: Any, required_plan: str) -> bool:
    """True if the caller may watch an episode gated at ``required_plan``."""
    if getattr(user, "role", "") in ("admin", "superadmin"):
        return True
    user_plan = _resolve_user_plan(user)
    try:
        from monetization.subscription import plan_gate

        return bool(plan_gate(required_plan, user_plan))
    except ImportError:
        return _PLAN_RANK.get(user_plan, 0) >= _PLAN_RANK.get(required_plan, 0)


def _generated_video_url(episode: int) -> str | None:
    """Look up a generated video URL from the tutorials generation registry.

    The self-updating generator (tutorials/generator.py) writes a registry
    mapping episode → {status, video_url, ...}. When an episode has been rendered
    to a playable URL it surfaces here automatically; otherwise None (the script
    is still a storyboard/manifest awaiting render). Best-effort: any failure
    falls back to the hardcoded ``video_url`` (None).
    """
    try:
        from tutorials.generator import load_registry

        entry = load_registry().get(str(episode))
        if entry:
            return entry.get("video_url")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("tutorials registry lookup failed (%s)", exc)
    return None


def _public_view(ep: dict[str, Any], locked: bool) -> dict[str, Any]:
    """Catalogue projection — never leaks the video_url for a locked episode."""
    video_url = ep.get("video_url") or _generated_video_url(ep["episode"])
    return {
        "episode": ep["episode"],
        "title": ep["title"],
        "level": ep["level"],
        "duration_min": ep["duration_min"],
        "plan": ep["plan"],
        "status": ep["status"],
        "summary": ep["summary"],
        "chapters": ep["chapters"],
        "thumbnail_text": ep["thumbnail_text"],
        "locked": locked,
        # Published flag lets the UI distinguish "locked behind plan" from
        # "not filmed yet" without exposing the URL itself.
        "published": video_url is not None,
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if _FASTAPI_AVAILABLE:
    router = APIRouter(prefix="/api/tutorials", tags=["Tutorials"])

    class EpisodeSummary(BaseModel):
        episode: int
        title: str
        level: str
        duration_min: int
        plan: str
        status: str
        summary: str
        chapters: list[str]
        thumbnail_text: str
        locked: bool
        published: bool

    class CatalogueResponse(BaseModel):
        episodes: list[EpisodeSummary]
        total: int
        user_plan: str

    @router.get("", summary="List the tutorial catalogue with per-episode lock flags")
    async def list_tutorials(user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
        """Return the full episode catalogue.

        Each episode carries a ``locked`` flag computed from the caller's plan so
        the Academy page can render lock badges without a round-trip per card.
        The playable ``video_url`` is never included here.
        """
        episodes = [_public_view(ep, locked=not _has_access(user, ep["plan"])) for ep in _EPISODES]
        return {
            "episodes": episodes,
            "total": len(episodes),
            "user_plan": _resolve_user_plan(user),
        }

    @router.get("/{episode}", summary="Get one episode (video_url gated by plan)")
    async def get_tutorial(episode: int, user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
        """Return a single episode.

        ``video_url`` is returned only when the caller's plan satisfies the
        episode's gate. Otherwise HTTP 403 with the required plan so the UI can
        deep-link to the upgrade page.
        """
        ep = _EPISODES_BY_ID.get(episode)
        if ep is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")

        if not _has_access(user, ep["plan"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PLAN_LIMIT_EXCEEDED",
                    "required_plan": ep["plan"],
                    "current_plan": _resolve_user_plan(user),
                    "message": f"Episode {episode} requires a {ep['plan'].title()} subscription or above.",
                },
            )

        view = _public_view(ep, locked=False)
        # Prefer an explicitly-set URL, else the generated one from the registry.
        view["video_url"] = ep.get("video_url") or _generated_video_url(episode)
        return view
