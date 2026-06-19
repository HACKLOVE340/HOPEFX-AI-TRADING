# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_news_feed_scoring.py
====================================
Regression tests for api/news_feed.py geopolitical scoring.

Previously the feed called a non-existent ``scorer.score_text`` method, so every
exception was swallowed and nuclear_score was always 0. These tests lock in the
fixed wiring: the scorer is the LLM-capable wrapper and _severity returns a real
0–10 value, and the /nuclear-score endpoint surfaces it.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.news_feed import _get_nuclear_scorer, _severity, router


def test_scorer_is_llm_wrapper() -> None:
    from news.geopolitical_llm import LLMGeopoliticalScorer

    assert isinstance(_get_nuclear_scorer(), LLMGeopoliticalScorer)


def test_severity_nonzero_for_crisis() -> None:
    scorer = _get_nuclear_scorer()
    high = asyncio.run(_severity(scorer, "Nuclear war fears as missiles launched, sanctions imposed"))
    low = asyncio.run(_severity(scorer, "Gold drifts in a quiet, low-volume session"))
    assert high >= 5
    assert low < 5
    assert high > low


def test_severity_handles_bad_scorer() -> None:
    class _Boom:
        async def score_event_llm(self, *_a, **_k):
            raise RuntimeError("boom")

    assert asyncio.run(_severity(_Boom(), "anything")) == 0


def test_nuclear_score_endpoint_smoke() -> None:
    # No news manager wired in a bare app → endpoint still responds cleanly.
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/api/news/nuclear-score?symbol=XAUUSD")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "XAUUSD"
    assert "score" in body and "alert" in body
