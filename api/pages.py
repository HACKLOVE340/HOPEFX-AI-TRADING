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
  GET /login              — React SPA (Login.tsx handles the route)
  GET /register           — React SPA (Register.tsx handles the route)
  GET /forgot-password    — React SPA
  GET /reset-password     — React SPA
  GET /security           — React SPA (SecurityDashboard.tsx)
  GET /marketplace        — React SPA (Marketplace.tsx)
  GET /affiliate          — React SPA (Affiliate.tsx)
  GET /privacy            — React SPA (PrivacyPolicy.tsx)
  GET /terms              — React SPA (TermsAndRiskDisclosure.tsx)
  GET /auth.js            — legacy shared JS helpers (kept for backward compat)
  GET /docs/FAQ.md        — FAQ documentation (template)
  GET /docs/API.md        — API reference documentation (template)
  GET /docs/MOBILE_GUIDE.md — mobile usage guide (template)

NOTE: /login, /register, and all other SPA routes are served by the React
SPA (static/index.html). React Router handles the path client-side.
The old template-based login/register pages are no longer used — the React
SPA provides a full-featured auth UI with CSRF, TOTP, and role-based routing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pages"])

_TEMPLATES = Path(__file__).parent.parent / "templates"
_STATIC    = Path(__file__).parent.parent / "static"
_SPA_INDEX = _STATIC / "index.html"


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


def _spa() -> FileResponse | HTMLResponse:
    """Serve the React SPA index.html, falling back to a minimal redirect."""
    if _SPA_INDEX.exists():
        return FileResponse(str(_SPA_INDEX))
    # SPA not built yet — redirect to API docs as a fallback
    return HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=/docs"></head>'
                '<body>Redirecting to API docs…</body></html>',
        status_code=200,
    )


# ── Shared JS assets ─────────────────────────────────────────────────────────
# Kept for backward compatibility with any bookmarked or cached pages that
# still reference /auth.js. New code uses the React SPA exclusively.

@router.get("/auth.js", include_in_schema=False)
async def auth_js():
    """Legacy shared auth helpers — served for backward compatibility."""
    js_path = _TEMPLATES / "auth.js"
    if js_path.exists():
        return FileResponse(str(js_path), media_type="application/javascript")
    return HTMLResponse(content="// auth.js not found", media_type="application/javascript")


# ── Auth pages → React SPA ────────────────────────────────────────────────────
# These routes previously served Jinja2 templates. They now serve the React
# SPA so React Router can handle the path with the full-featured Login.tsx /
# Register.tsx components (CSRF, TOTP, role-based redirect, etc.).

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page():
    """Login — served by the React SPA (Login.tsx)."""
    return _spa()


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page():
    """Registration — served by the React SPA (Register.tsx)."""
    return _spa()


@router.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
async def forgot_password_page():
    """Forgot password — served by the React SPA (ForgotPassword.tsx)."""
    return _spa()


@router.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_page():
    """Reset password — served by the React SPA (ResetPassword.tsx)."""
    return _spa()


# ── Info / community pages → React SPA ───────────────────────────────────────

@router.get("/security", response_class=HTMLResponse, include_in_schema=False)
async def security_page():
    """Security dashboard — served by the React SPA (SecurityDashboard.tsx)."""
    return _spa()


@router.get("/marketplace", response_class=HTMLResponse, include_in_schema=False)
async def marketplace_page():
    """Strategy marketplace — served by the React SPA (Marketplace.tsx)."""
    return _spa()


@router.get("/affiliate", response_class=HTMLResponse, include_in_schema=False)
async def affiliate_page():
    """Affiliate programme — served by the React SPA (Affiliate.tsx)."""
    return _spa()


# ── Legal pages → React SPA ───────────────────────────────────────────────────

@router.get("/about", response_class=HTMLResponse, include_in_schema=False)
async def about_page():
    """About HOPEFX — served by the React SPA."""
    return _spa()


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_page():
    """Privacy Policy — served by the React SPA (PrivacyPolicy.tsx)."""
    return _spa()


@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms_page():
    """Terms of Service — served by the React SPA (TermsAndRiskDisclosure.tsx)."""
    return _spa()


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
