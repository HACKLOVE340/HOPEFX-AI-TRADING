# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/pages.py
============
HTML page routes for the frontend.

Routes served:
  GET /login              — login page
  GET /register           — registration page
  GET /security           — security & privacy page
  GET /marketplace        — strategy marketplace
  GET /affiliate          — affiliate programme
  GET /docs/FAQ.md        — FAQ documentation
  GET /docs/API.md        — API reference documentation
  GET /docs/MOBILE_GUIDE.md — mobile usage guide
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pages"])

_TEMPLATES = Path(__file__).parent.parent / "templates"


def _read(name: str) -> str:
    path = _TEMPLATES / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("Template not found: %s", path)
        return (
            f"<html><body><h1>HOPEFX</h1>"
            f"<p>Page template '{name}' not found.</p></body></html>"
        )


# ── Auth pages ────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page():
    """Login page — unauthenticated users are directed here."""
    return HTMLResponse(content=_read("login.html"))


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page():
    """Account registration page."""
    return HTMLResponse(content=_read("register.html"))


# ── Info pages ────────────────────────────────────────────────────────────────

@router.get("/security", response_class=HTMLResponse, include_in_schema=False)
async def security_page():
    """Security & privacy information page."""
    return HTMLResponse(content=_read("security.html"))


@router.get("/marketplace", response_class=HTMLResponse, include_in_schema=False)
async def marketplace_page():
    """Strategy marketplace — browse and deploy AI trading strategies."""
    return HTMLResponse(content=_read("marketplace.html"))


@router.get("/affiliate", response_class=HTMLResponse, include_in_schema=False)
async def affiliate_page():
    """Affiliate programme — earn commissions by referring traders."""
    return HTMLResponse(content=_read("affiliate.html"))


# ── Legal / company pages ─────────────────────────────────────────────────────

@router.get("/about", response_class=HTMLResponse, include_in_schema=False)
async def about_page():
    """About HOPEFX — mission, technology, and team."""
    return HTMLResponse(content=_read("about.html"))


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_page():
    """Privacy Policy — data collection, use, and user rights."""
    return HTMLResponse(content=_read("privacy.html"))


@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms_page():
    """Terms of Service — rules governing use of the platform."""
    return HTMLResponse(content=_read("terms.html"))


# ── Documentation pages ───────────────────────────────────────────────────────

@router.get("/docs/FAQ.md", response_class=HTMLResponse, include_in_schema=False)
async def docs_faq():
    """Frequently Asked Questions."""
    return HTMLResponse(content=_read("docs_faq.html"))


@router.get("/docs/API.md", response_class=HTMLResponse, include_in_schema=False)
async def docs_api():
    """API reference documentation."""
    return HTMLResponse(content=_read("docs_api.html"))


@router.get("/docs/MOBILE_GUIDE.md", response_class=HTMLResponse, include_in_schema=False)
async def docs_mobile():
    """Mobile usage guide."""
    return HTMLResponse(content=_read("docs_mobile.html"))
