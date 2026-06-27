# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/trust_scorer.py
==================
Runtime **AI subsystem trust scoring** (elite-architecture requirement #7).

The invariant layer already *validates* trust-weighted capital allocation
(`invariants.ai.verify_trust_score` / `verify_trust_floor` /
`verify_trust_weighted_allocation`, enforced by
`invariants.enforcement.enforce_trust_allocation`). This module *produces* the
trust scores those invariants check: each subsystem (e.g. the ML model, the LLM
brain, the rule engine, the anomaly filter) earns a trust score in **[0, 1]** from
its **rolling recent performance**, and capital is allocated **proportional to
trust** — distrusted subsystems (below a floor) get nothing.

Pure and dependency-free (EWMA over a correctness/accuracy signal), so it is
trivially testable and safe to call on the hot path.

Usage::

    scorer = TrustScorer(alpha=0.1, floor=0.4)
    scorer.record("ml_model", correct=True)      # a good call
    scorer.record("llm_brain", correct=False)    # a bad call
    alloc = scorer.allocate(capital=100_000, subsystems=["ml_model", "llm_brain"])
    # alloc == {"ml_model": {"trust": .., "capital": ..}, ...}  ← feed to enforce_trust_allocation
"""

from __future__ import annotations

import math
from typing import Any


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class TrustScorer:
    """EWMA trust scorer for AI subsystems.

    Parameters
    ----------
    alpha : EWMA weight for the newest observation (0 < alpha <= 1). Higher =
            more reactive to recent performance.
    prior : starting trust before any observations (default 0.5 — neutral).
    floor : trust below which a subsystem is *distrusted* and allocated **zero**
            capital (matches ``enforce_trust_allocation(floor=...)``).
    """

    def __init__(self, alpha: float = 0.1, prior: float = 0.5, floor: float = 0.0) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        if not 0.0 <= prior <= 1.0:
            raise ValueError("prior must be in [0, 1]")
        self.alpha = float(alpha)
        self.prior = float(prior)
        self.floor = float(floor)
        self._scores: dict[str, float] = {}
        self._counts: dict[str, int] = {}

    # ── updates ───────────────────────────────────────────────────────────────
    def record(self, name: str, *, correct: bool | None = None, signal: float | None = None) -> float:
        """Update a subsystem's trust from one outcome.

        Provide either ``correct`` (bool — was the call right?) or ``signal`` (a
        float already in [0, 1], e.g. a normalised PnL or calibration score).
        Returns the updated trust score.
        """
        if signal is None:
            if correct is None:
                raise ValueError("provide either correct= or signal=")
            obs = 1.0 if correct else 0.0
        else:
            if not _finite(signal):
                return self.score(name)  # ignore garbage, don't corrupt the EWMA
            obs = min(1.0, max(0.0, float(signal)))

        cur = self._scores.get(name, self.prior)
        updated = (1.0 - self.alpha) * cur + self.alpha * obs
        self._scores[name] = min(1.0, max(0.0, updated))
        self._counts[name] = self._counts.get(name, 0) + 1
        return self._scores[name]

    # ── reads ─────────────────────────────────────────────────────────────────
    def score(self, name: str) -> float:
        """Current trust for ``name`` (the prior if never recorded)."""
        return self._scores.get(name, self.prior)

    def scores(self) -> dict[str, float]:
        return dict(self._scores)

    def is_trusted(self, name: str) -> bool:
        return self.score(name) >= self.floor

    # ── allocation ──────────────────────────────────────────────────────────────
    def allocate(self, capital: float, subsystems: list[str]) -> dict[str, dict[str, float]]:
        """Split ``capital`` across ``subsystems`` proportional to trust.

        Distrusted subsystems (trust < ``floor``) receive **zero**. The result is
        shaped for :func:`invariants.enforcement.enforce_trust_allocation`:
        ``{name: {"trust": t, "capital": c}}`` — and is constructed so it never
        inverts trust (more trust ⇒ at least as much capital).
        """
        if not _finite(capital) or capital < 0:
            capital = 0.0
        trusts = {n: self.score(n) for n in subsystems}
        eligible = {n: t for n, t in trusts.items() if t >= self.floor}
        total = sum(eligible.values())
        out: dict[str, dict[str, float]] = {}
        for n in subsystems:
            t = trusts[n]
            c = (eligible.get(n, 0.0) / total) * capital if total > 0 else 0.0
            out[n] = {"trust": round(t, 6), "capital": round(c, 6)}
        return out
