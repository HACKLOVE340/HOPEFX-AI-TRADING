# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
dashboard/app_fixed.py
======================
Lightweight FastAPI dashboard exposing real ML and trade data.

Routes
------
GET /healthcheck   — liveness probe
GET /data          — cumulative PnL equity curve from real trade history
GET /chart         — PNG equity curve chart from real trade history
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── App state (injected at startup by the main app) ───────────────────────────
app_state = None


def set_state(state) -> None:
    global app_state
    app_state = state


# ── Helpers ───────────────────────────────────────────────────────────────────


def _equity_curve() -> list[dict[str, Any]]:
    """
    Build an equity curve from real closed trade history.

    Returns a list of {x: trade_index, y: cumulative_pnl} dicts.
    Returns [] when no trade history is available.
    """
    try:
        broker = getattr(app_state, "broker", None) if app_state else None
        if broker is None:
            return []
        trades = broker.get_trade_history(limit=500) or []
        if not trades:
            return []
        cum = 0.0
        points: list[dict[str, Any]] = []
        for i, t in enumerate(trades):
            cum += float(t.get("pnl", 0))
            points.append({"x": i, "y": round(cum, 2)})
        return points
    except Exception as exc:
        logger.debug("equity_curve fetch failed: %s", exc)
        return []


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/healthcheck")
def read_healthcheck():
    logger.info("Health check endpoint called")
    return {"status": "healthy"}


@app.get("/data")
def read_data():
    """Return cumulative PnL equity curve from real trade history."""
    try:
        points = _equity_curve()
        logger.info("Dashboard /data: %d equity curve points", len(points))
        return points
    except Exception as exc:
        logger.error("Error retrieving data: %s", exc)
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc


@app.get("/chart", response_class=HTMLResponse)
def get_chart():
    """Render equity curve chart from real trade history as an inline PNG."""
    try:
        points = _equity_curve()
        if not points:
            return HTMLResponse(
                content="<p>No trade history available.</p>",
                status_code=200,
            )

        data = pd.DataFrame(points)
        fig, ax = plt.subplots()
        ax.plot(data["x"], data["y"], marker="o", markersize=3)
        ax.set_title("Equity Curve")
        ax.set_xlabel("Trade #")
        ax.set_ylabel("Cumulative PnL (USD)")
        ax.grid(True)

        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        logger.info("Dashboard /chart: rendered %d-point equity curve", len(points))
        return f"<img src='data:image/png;base64,{img_b64}' alt='Equity Curve'/>"
    except Exception as exc:
        logger.error("Error generating chart: %s", exc)
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc
