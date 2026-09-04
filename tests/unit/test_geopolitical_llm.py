# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_geopolitical_llm.py
===================================
Tests news/geopolitical_llm.py — the LLM-backed geopolitical risk scorer with
WORDMAP fallback. The LLM provider isn't reachable in CI, so a fake agent is
injected to exercise the parse/map path; the fallback paths are tested directly.
"""

from __future__ import annotations

import pytest

from news.geopolitical_llm import LLMGeopoliticalScorer
from news.nuclear_wordmap_scorer import NuclearWordMapScorer, NuclearWordmapScorer


class _FakeAgent:
    """Stand-in for brain.llm_agent.LLMAgent."""

    def __init__(self, content: str = "", err: str | None = None):
        self._content = content
        self._err = err

    async def _call_llm_with_messages(self, _messages):
        return self._content, self._err


def _enabled_scorer(content: str = "", err: str | None = None) -> LLMGeopoliticalScorer:
    s = LLMGeopoliticalScorer(enabled=True)
    s._agent = _FakeAgent(content, err)
    s._agent_attempted = True
    return s


def test_backcompat_alias() -> None:
    assert NuclearWordmapScorer is NuclearWordMapScorer


def test_disabled_by_default_uses_wordmap() -> None:
    s = LLMGeopoliticalScorer()  # GEOPOLITICAL_LLM_EXTRACTION defaults off
    assert s.is_llm_available is False


def test_sync_score_event_matches_wordmap() -> None:
    base = NuclearWordMapScorer()
    s = LLMGeopoliticalScorer(base_scorer=base)
    text = "Missile strikes escalate the conflict near the border"
    assert s.score_event(text, 1.2, -0.3) == base.score_event(text, 1.2, -0.3)


@pytest.mark.asyncio
async def test_llm_path_parses_plain_json() -> None:
    content = (
        '{"severity": 8, "category": "nuclear", "gold_impact": "bullish", '
        '"confidence": 0.9, "rationale": "Direct strike on enrichment site."}'
    )
    s = _enabled_scorer(content)
    sev, action, score, meta = await s.score_event_llm("strike on the enrichment facility")

    # The parse is what this test is about, and it still holds: the model's own
    # number arrives intact in meta.
    assert meta["source"] == "llm"
    assert meta["llm_severity_raw"] == 8
    assert meta["category"] == "nuclear"
    assert meta["gold_impact"] == "bullish"

    # What changed: this used to assert `action == "hedge_mode"` — an LLM alone
    # placing a real short on XAU_USD off a headline the deterministic wordmap
    # scored at zero. Untrusted news may no longer raise severity into an action
    # tier the wordmap did not independently reach, so the effective severity is
    # capped and no order is triggered.
    assert meta["llm_capped"] is True
    assert sev <= meta["llm_severity_raw"]
    assert action != "hedge_mode"


@pytest.mark.asyncio
async def test_llm_path_parses_fenced_json() -> None:
    content = '```json\n{"severity": 3, "category": "geopolitical", "confidence": 0.6}\n```'
    s = _enabled_scorer(content)
    sev, action, _score, meta = await s.score_event_llm("diplomatic talks to ease tensions")
    assert sev == 3
    assert meta["source"] == "llm"


@pytest.mark.asyncio
async def test_llm_error_falls_back_to_wordmap() -> None:
    s = _enabled_scorer("", err="rate limited")
    sev, _action, _score, meta = await s.score_event_llm("nuclear war fears spike", 1.0, -0.5)
    assert meta["source"] == "wordmap"
    assert sev >= 5  # WORDMAP still catches the keyword


@pytest.mark.asyncio
async def test_llm_malformed_json_falls_back() -> None:
    s = _enabled_scorer("sorry, I cannot produce JSON today")
    _sev, _action, _score, meta = await s.score_event_llm("sanctions imposed on the central bank")
    assert meta["source"] == "wordmap"


@pytest.mark.asyncio
async def test_severity_out_of_range_is_rejected_not_clamped() -> None:
    """Was `test_severity_clamped`, asserting that severity 99 became 10 and
    tripped `nuclear_mode`.

    Two things were wrong with that. Coercing a nonsense value into the top of
    the scale invents a reading the model never gave; and it let an
    uncorroborated response halt the platform. A response outside the requested
    range is a failed extraction, so the deterministic wordmap answers instead.
    """
    s = _enabled_scorer('{"severity": 99}')
    sev, action, _score, meta = await s.score_event_llm("anything")

    assert meta["source"] == "wordmap"
    assert sev == 0
    assert action == "normal"
