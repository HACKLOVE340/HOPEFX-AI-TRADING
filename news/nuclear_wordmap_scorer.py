#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
news/nuclear_wordmap_scorer.py
================================
WORDMAP-based semantic scorer for nuclear/geopolitical/macro events.

Combines three signals into a single severity score [0–10]:

  1. WORDMAP keyword matching — weighted term frequency across 8 risk
     categories (nuclear, war, sanctions, central_bank, etc.)
  2. Volatility fusion — amplifies severity when market vol is elevated
  3. Sentiment fusion — adjusts severity based on news sentiment polarity

The scorer is stateless and synchronous — safe to call from any async
context without blocking.

Severity scale
--------------
  0–4   : Normal — no action required
  5–6   : Elevated — consider pausing new entries
  7–8   : High — hedge / reduce exposure
  9–10  : Critical — full nuclear mode (liquidate + halt)

Usage
-----
    scorer = NuclearWordMapScorer()
    severity, action, score, meta = scorer.score_event(text, vol, sentiment)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── WORDMAP nuclear/risk keyword dictionary ───────────────────────────────────
# Loaded from WORDMAP.json if it contains a nuclear_risk section;
# otherwise the built-in dictionary below is used.

_BUILTIN_NUCLEAR_KEYWORDS: dict[str, dict[str, float]] = {
    # ── Nuclear / WMD ────────────────────────────────────────────────────────
    "nuclear": {
        "nuclear war": 10.0,
        "nuclear strike": 10.0,
        "nuclear attack": 10.0,
        "nuclear launch": 10.0,
        "nuclear detonation": 10.0,
        "nuclear explosion": 10.0,
        "nuclear weapon": 9.0,
        "nuclear warhead": 9.0,
        "nuclear missile": 9.0,
        "nuclear threat": 8.5,
        "nuclear escalation": 8.5,
        "nuclear alert": 8.0,
        "nuclear test": 8.0,
        "dirty bomb": 9.0,
        "radiological weapon": 9.0,
        "icbm launch": 9.5,
        "ballistic missile": 7.5,
        "hypersonic missile": 7.0,
        "wmd": 9.0,
        "weapons of mass destruction": 9.0,
    },
    # ── War / Armed conflict ─────────────────────────────────────────────────
    "war": {
        "world war": 9.5,
        "world war iii": 10.0,
        "wwiii": 10.0,
        "nato article 5": 9.0,
        "nato invoked": 9.0,
        "declaration of war": 9.0,
        "war declared": 9.0,
        "military invasion": 8.5,
        "ground invasion": 8.5,
        "air strikes": 7.5,
        "missile strike": 7.5,
        "military escalation": 7.5,
        "ceasefire collapsed": 7.0,
        "ceasefire broken": 7.0,
        "troops mobilized": 7.0,
        "troops deployed": 6.5,
        "military conflict": 6.5,
        "armed conflict": 6.5,
        "coup": 7.0,
        "coup d'état": 7.5,
        "assassination": 8.0,
        "president killed": 9.0,
        "prime minister killed": 9.0,
    },
    # ── Sanctions / Trade war ────────────────────────────────────────────────
    "sanctions": {
        "swift ban": 8.5,
        "swift disconnected": 8.5,
        "nuclear sanctions": 8.0,
        "oil embargo": 8.0,
        "trade war escalation": 7.5,
        "tariff escalation": 7.0,
        "sanctions imposed": 6.5,
        "sanctions expanded": 6.5,
        "export ban": 6.0,
        "import ban": 6.0,
        "trade restrictions": 5.5,
        "economic sanctions": 6.0,
    },
    # ── Central bank / Monetary shock ────────────────────────────────────────
    "central_bank": {
        "emergency rate cut": 8.0,
        "emergency rate hike": 8.0,
        "emergency meeting": 7.5,
        "fed emergency": 8.0,
        "ecb emergency": 8.0,
        "bank of england emergency": 8.0,
        "quantitative easing": 5.5,
        "quantitative tightening": 5.5,
        "rate cut 100": 7.0,
        "rate hike 100": 7.0,
        "rate cut 75": 6.5,
        "rate hike 75": 6.5,
        "currency intervention": 6.5,
        "currency peg broken": 7.5,
        "dollar collapse": 8.5,
        "hyperinflation": 8.0,
        "bank run": 8.0,
        "bank failure": 7.5,
        "systemic risk": 7.0,
        "financial contagion": 7.5,
        "credit crunch": 7.0,
    },
    # ── Geopolitical crisis ───────────────────────────────────────────────────
    "geopolitical": {
        "taiwan invasion": 9.5,
        "taiwan strait": 8.0,
        "south china sea": 7.0,
        "north korea launch": 8.5,
        "iran nuclear": 8.0,
        "iran attack": 8.0,
        "israel iran": 8.5,
        "middle east war": 8.5,
        "oil field attack": 7.5,
        "strait of hormuz": 8.0,
        "suez canal blocked": 7.0,
        "panama canal blocked": 6.5,
        "cyber attack infrastructure": 7.5,
        "power grid attack": 7.5,
        "pipeline explosion": 7.0,
        "nord stream": 7.0,
    },
    # ── Market / Financial crisis ─────────────────────────────────────────────
    "market_crisis": {
        "market crash": 8.0,
        "stock market crash": 8.0,
        "circuit breaker triggered": 7.5,
        "trading halted": 7.0,
        "exchange closed": 7.5,
        "flash crash": 7.0,
        "liquidity crisis": 7.5,
        "sovereign default": 8.0,
        "debt ceiling breach": 7.5,
        "government shutdown": 5.5,
        "recession confirmed": 6.5,
        "depression": 7.5,
        "imf bailout": 7.0,
        "imf emergency": 7.5,
    },
    # ── Pandemic / Natural disaster ───────────────────────────────────────────
    "pandemic": {
        "pandemic declared": 7.5,
        "who emergency": 7.0,
        "global health emergency": 7.0,
        "lockdown global": 7.5,
        "lockdown china": 6.5,
        "supply chain collapse": 7.0,
        "earthquake major": 6.0,
        "tsunami warning": 6.5,
        "hurricane category 5": 5.5,
    },
    # ── Gold-specific triggers ────────────────────────────────────────────────
    "gold_specific": {
        "gold confiscation": 8.5,
        "gold standard": 6.0,
        "gold reserve sold": 6.5,
        "imf gold sale": 6.5,
        "central bank gold": 5.5,
        "safe haven demand": 5.0,
        "flight to safety": 5.0,
        "risk off": 5.0,
        "risk-off": 5.0,
    },
}

# Severity → action mapping
_SEVERITY_ACTIONS: dict[int, str] = {
    0: "normal",
    1: "normal",
    2: "normal",
    3: "normal",
    4: "normal",
    5: "pause_new_entries",
    6: "pause_new_entries",
    7: "hedge_mode",
    8: "hedge_mode",
    9: "nuclear_mode",
    10: "nuclear_mode",
}


class NuclearWordMapScorer:
    """
    Score a news event for nuclear/geopolitical/macro risk.

    Parameters
    ----------
    wordmap_path : str | Path, optional
        Path to WORDMAP.json.  If the file contains a ``nuclear_risk``
        section, those keywords are merged with the built-in dictionary.
        Defaults to ``WORDMAP.json`` in the project root.
    vol_amplifier : float
        How much elevated volatility amplifies severity.
        At vol=2.0 (double normal), severity is multiplied by
        (1 + vol_amplifier * (vol - 1)).  Default 0.25.
    sentiment_weight : float
        How much negative sentiment adds to severity.
        Negative sentiment [-1, 0] adds up to sentiment_weight points.
        Default 0.5.
    """

    def __init__(
        self,
        wordmap_path: str | Path | None = None,
        vol_amplifier: float = 0.25,
        sentiment_weight: float = 0.5,
    ) -> None:
        self._vol_amplifier = vol_amplifier
        self._sentiment_weight = sentiment_weight
        self._keywords = self._load_keywords(wordmap_path)
        logger.info(
            "NuclearWordMapScorer loaded: %d categories, %d total keywords",
            len(self._keywords),
            sum(len(v) for v in self._keywords.values()),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def score_event(
        self,
        text: str,
        volatility: float = 1.0,
        sentiment: float = 0.0,
    ) -> tuple[int, str, float, dict]:
        """
        Score a news event.

        Parameters
        ----------
        text        : raw news text (headline + body)
        volatility  : current market volatility normalised to 1.0 = normal.
                      Values > 1.0 amplify severity.
        sentiment   : news sentiment in [-1, 1].  Negative values increase
                      severity (bad news = higher risk).

        Returns
        -------
        severity    : int [0–10]
        action      : str  one of normal | pause_new_entries | hedge_mode | nuclear_mode
        raw_score   : float  pre-clamp score before integer rounding
        meta        : dict  {matched_terms, category_scores, confidence, vol_factor, sentiment_factor}
        """
        text_lower = text.lower()
        text_lower = re.sub(r"[^\w\s]", " ", text_lower)

        # ── Step 1: WORDMAP keyword matching ─────────────────────────────────
        category_scores: dict[str, float] = {}
        matched_terms: list[dict] = []

        for category, terms in self._keywords.items():
            cat_score = 0.0
            for term, weight in terms.items():
                if term in text_lower:
                    # Count occurrences (capped at 3 to avoid spam amplification)
                    count = min(text_lower.count(term), 3)
                    contribution = weight * (1 + 0.2 * (count - 1))
                    cat_score = max(cat_score, contribution)
                    matched_terms.append(
                        {
                            "term": term,
                            "category": category,
                            "weight": weight,
                            "count": count,
                            "contribution": round(contribution, 3),
                        }
                    )
            if cat_score > 0:
                category_scores[category] = round(cat_score, 3)

        # Base score: max single-category score + 10% of second-highest
        sorted_scores = sorted(category_scores.values(), reverse=True)
        base_score = 0.0
        if sorted_scores:
            base_score = sorted_scores[0]
            if len(sorted_scores) > 1:
                base_score += 0.10 * sorted_scores[1]  # co-occurrence bonus

        # ── Step 2: Volatility fusion ─────────────────────────────────────────
        # vol=1.0 → factor=1.0 (no change)
        # vol=2.0 → factor=1.25 (25% amplification)
        vol_factor = 1.0 + self._vol_amplifier * max(0.0, volatility - 1.0)
        vol_adjusted = base_score * vol_factor

        # ── Step 3: Sentiment fusion ──────────────────────────────────────────
        # sentiment in [-1, 1]; negative = bearish/fearful = higher risk
        # Add up to sentiment_weight points for maximally negative sentiment
        sentiment_factor = self._sentiment_weight * max(0.0, -sentiment)
        final_score = vol_adjusted + sentiment_factor

        # ── Step 4: Confidence ────────────────────────────────────────────────
        # Confidence is higher when multiple categories match and score is high
        n_categories = len(category_scores)
        confidence = min(1.0, (n_categories / 3.0) * (final_score / 10.0))
        if matched_terms:
            confidence = max(confidence, 0.3)  # at least 30% if any term matched

        # ── Step 5: Clamp and round ───────────────────────────────────────────
        raw_score = final_score
        severity = int(min(10, max(0, round(final_score))))
        action = _SEVERITY_ACTIONS.get(severity, "normal")

        meta = {
            "matched_terms": matched_terms,
            "category_scores": category_scores,
            "base_score": round(base_score, 4),
            "vol_factor": round(vol_factor, 4),
            "sentiment_factor": round(sentiment_factor, 4),
            "confidence": round(confidence, 4),
            "n_categories_matched": n_categories,
        }

        if severity >= 5:  # noqa: PLR2004
            logger.warning(
                "NuclearWordMapScorer: severity=%d action=%s score=%.3f categories=%s vol=%.2f sentiment=%.2f",
                severity,
                action,
                raw_score,
                list(category_scores.keys()),
                volatility,
                sentiment,
            )

        return severity, action, round(raw_score, 4), meta

    def get_keyword_count(self) -> int:
        return sum(len(v) for v in self._keywords.values())

    def get_categories(self) -> list[str]:
        return list(self._keywords.keys())

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_keywords(self, wordmap_path: str | Path | None) -> dict[str, dict[str, float]]:
        """
        Load keywords from WORDMAP.json (nuclear_risk section) merged with
        the built-in dictionary.  Falls back to built-in only if file is
        missing or malformed.
        """
        keywords = {k: dict(v) for k, v in _BUILTIN_NUCLEAR_KEYWORDS.items()}

        path = Path(wordmap_path) if wordmap_path else Path("WORDMAP.json")
        if not path.exists():
            logger.debug("WORDMAP.json not found at %s — using built-in keywords", path)
            return keywords

        try:
            data = json.loads(path.read_text())
            nuclear_section = data.get("nuclear_risk", {})
            if nuclear_section:
                for category, terms in nuclear_section.items():
                    if category not in keywords:
                        keywords[category] = {}
                    if isinstance(terms, dict):
                        keywords[category].update(terms)
                    elif isinstance(terms, list):
                        # List of strings → assign default weight 7.0
                        for term in terms:
                            if isinstance(term, str):
                                keywords[category][term.lower()] = 7.0
                logger.info(
                    "Merged nuclear_risk section from WORDMAP.json (%d categories)",
                    len(nuclear_section),
                )
        except Exception as exc:
            logger.warning(
                "Could not load nuclear_risk from WORDMAP.json: %s — using built-in",
                exc,
            )

        return keywords
