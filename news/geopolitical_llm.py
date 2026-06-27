# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
news/geopolitical_llm.py
========================
LLM-backed geopolitical risk extraction with a deterministic WORDMAP fallback.

The legacy NuclearWordMapScorer scores news by substring-matching ~150 hand-
weighted keywords. That misses paraphrase, negation and novel events ("a strike
on the enrichment facility" never says the word "nuclear"). This wrapper adds an
LLM event-extraction path that reads the text and emits a structured risk
assessment, while keeping the WORDMAP as the always-available fallback.

Design
------
* ``score_event(...)`` is the synchronous WORDMAP path — a byte-for-byte
  delegate to the wrapped scorer, so this class is a safe drop-in replacement
  anywhere the sync API is used.
* ``score_event_llm(...)`` is async and uses the LLM when enabled+available,
  falling back to the WORDMAP on any failure (no key, parse error, exception).
* Gated by ``GEOPOLITICAL_LLM_EXTRACTION`` (default OFF) because LLM calls cost
  money and need a provider key. With the flag off this class behaves exactly
  like NuclearWordMapScorer.

The LLM result is mapped onto the same (severity, action, score, meta) contract
the rest of the system already consumes, so callers need no other changes.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from news.nuclear_wordmap_scorer import _SEVERITY_ACTIONS, NuclearWordMapScorer

logger = logging.getLogger(__name__)

_PROMPT = """You are a geopolitical risk analyst for a gold (XAU/USD) trading desk.
Read the news text and return ONLY a compact JSON object (no prose) with keys:
  "severity": integer 0-10 (0=no risk, 10=imminent catastrophic event e.g. nuclear war),
  "category": one of ["nuclear","war","sanctions","central_bank","geopolitical","market_crisis","pandemic","gold_specific","none"],
  "gold_impact": one of ["bullish","bearish","neutral"] (safe-haven flows into gold = bullish),
  "confidence": float 0-1,
  "rationale": one short sentence.
Judge the actual event described, not just keywords. Negated or hypothetical
events ("talks to avoid war") are LOW severity.

NEWS:
{text}
"""


class LLMGeopoliticalScorer:
    """WORDMAP scorer augmented with an optional LLM extraction path."""

    def __init__(
        self,
        base_scorer: NuclearWordMapScorer | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._base = base_scorer or NuclearWordMapScorer()
        if enabled is None:
            enabled = os.getenv("GEOPOLITICAL_LLM_EXTRACTION", "false").lower() in ("1", "true", "yes")
        self._enabled = enabled
        self._agent: Any = None
        self._agent_attempted = False

    # ── Sync WORDMAP delegate (drop-in compatible) ──────────────────────────────

    def score_event(self, text: str, volatility: float = 1.0, sentiment: float = 0.0):
        """Synchronous WORDMAP scoring — identical to NuclearWordMapScorer."""
        return self._base.score_event(text, volatility, sentiment)

    def get_keyword_count(self) -> int:
        return self._base.get_keyword_count()

    def get_categories(self) -> list[str]:
        return self._base.get_categories()

    # ── LLM path ─────────────────────────────────────────────────────────────────

    def _ensure_agent(self) -> None:
        if self._agent_attempted:
            return
        self._agent_attempted = True
        try:
            from brain.llm_agent import LLMAgent

            self._agent = LLMAgent()
        except Exception as exc:
            logger.info("LLMGeopoliticalScorer: LLM agent unavailable (%s) — WORDMAP only", exc)
            self._agent = None

    @property
    def is_llm_available(self) -> bool:
        if not self._enabled:
            return False
        self._ensure_agent()
        return self._agent is not None

    async def score_event_llm(
        self, text: str, volatility: float = 1.0, sentiment: float = 0.0
    ) -> tuple[int, str, float, dict]:
        """LLM event extraction with WORDMAP fallback.

        Returns the same (severity, action, score, meta) contract as
        NuclearWordMapScorer.score_event. ``meta['source']`` is 'llm' when the
        LLM path produced the score, else 'wordmap'.
        """
        if not self.is_llm_available:
            return self._wordmap(text, volatility, sentiment)

        try:
            messages = [{"role": "user", "content": _PROMPT.format(text=text[:4000])}]
            content, err = await self._agent._call_llm_with_messages(messages)
            if err or not content:
                raise RuntimeError(err or "empty LLM response")
            parsed = self._parse(content)
            severity = int(max(0, min(10, round(float(parsed["severity"])))))
            action = _SEVERITY_ACTIONS.get(severity, "normal")
            meta = {
                "source": "llm",
                "category": parsed.get("category", "none"),
                "gold_impact": parsed.get("gold_impact", "neutral"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "rationale": parsed.get("rationale", ""),
                "vol_factor": float(volatility),
                "sentiment_factor": float(sentiment),
            }
            if severity >= 5:
                logger.info(
                    "LLMGeopoliticalScorer: severity=%d action=%s category=%s impact=%s",
                    severity,
                    action,
                    meta["category"],
                    meta["gold_impact"],
                )
            return severity, action, float(severity), meta
        except Exception as exc:
            logger.warning("LLMGeopoliticalScorer: LLM path failed (%s) — WORDMAP fallback", exc)
            return self._wordmap(text, volatility, sentiment)

    def _wordmap(self, text: str, volatility: float, sentiment: float) -> tuple[int, str, float, dict]:
        """WORDMAP scoring tagged with source='wordmap' for observability."""
        severity, action, score, meta = self._base.score_event(text, volatility, sentiment)
        meta = {**meta, "source": "wordmap"}
        return severity, action, score, meta

    @staticmethod
    def _parse(content: str) -> dict[str, Any]:
        """Extract the JSON object from an LLM response (tolerates code fences)."""
        text = content.strip()
        # Strip ```json fences if present.
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        # Grab the first {...} block.
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("no JSON object in LLM response")
        data = json.loads(match.group(0))
        if "severity" not in data:
            raise ValueError("LLM JSON missing 'severity'")
        return data
