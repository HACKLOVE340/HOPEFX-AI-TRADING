# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Structured reasoning, opposing perspectives, and refusing to fake agreement.

§15 asks that a consequential answer state its thesis, its counter-thesis, its
evidence, its assumptions, what it does not know, a calibrated confidence, what
would change the conclusion, and the risks and alternatives. §13 asks that
opposing perspectives be invoked for high-value decisions, that competing claims
and their evidence be recorded, that evidence be weighted by quality and
freshness — and, the one that does the most work, that **artificial consensus
not be forced**.

That last rule is why this is a package rather than a prompt. A model asked to
"consider both sides" will happily produce a paragraph of both-sides language
and then a confident recommendation, and the structure of the output gives an
operator no way to tell whether the disagreement was real. Here the parts are
fields, the absence of a counter-thesis is a construction error, and an
unresolved debate is a distinct result rather than a weaker recommendation.
"""

from ai.debate.correlation import Correlation, PriceMove, Signal, correlate
from ai.debate.evidence import Evidence, EvidenceQuality, weigh
from ai.debate.reasoning import Reasoning, ReasoningIncomplete
from ai.debate.session import Position, DebateResult, debate
from ai.debate.trade import TradeAnalysis, analyse_trade

__all__ = [
    "Correlation",
    "DebateResult",
    "Evidence",
    "EvidenceQuality",
    "Position",
    "PriceMove",
    "Reasoning",
    "ReasoningIncomplete",
    "Signal",
    "TradeAnalysis",
    "analyse_trade",
    "correlate",
    "debate",
    "weigh",
]
