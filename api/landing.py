# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/landing.py
==============
Serves the marketing landing page at / and /landing.

Unauthenticated users visiting the root domain see the landing page
instead of being dropped directly into the app dashboard.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Landing"])

_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "landing.html"


def _read_landing() -> str:
    try:
        return _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("landing.html not found at %s", _TEMPLATE_PATH)
        return "<html><body><h1>HOPEFX</h1><p>Landing page not found.</p></body></html>"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/landing", response_class=HTMLResponse, include_in_schema=False)
async def landing_page():
    """
    Public marketing landing page.
    Served at / and /landing — no authentication required.
    Authenticated users are redirected to /dashboard by the frontend router.
    """
    return HTMLResponse(content=_read_landing())
