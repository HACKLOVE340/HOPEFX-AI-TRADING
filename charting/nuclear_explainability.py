# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
charting/nuclear_explainability.py
=====================================
SHAP-style rule-based explainability engine for nuclear AI decisions.

Produces structured explanations for every RL + WORDMAP decision so the
dashboard can render human-readable, actionable co-pilot summaries.

Key outputs
-----------
  ExplainResult.summary        — one-sentence decision summary
  ExplainResult.feature_scores — SHAP-style feature importance list
  ExplainResult.decision_trace — step-by-step reasoning chain
  ExplainResult.risk_narrative — plain-English risk assessment
  ExplainResult.action_advice  — what the operator should do now

Usage
-----
    from charting.nuclear_explainability import NuclearExplainabilityEngine

    engine = NuclearExplainabilityEngine()
    result = engine.explain(
        severity=9,
        action="nuclear_mode",
        rl_action=3,
        rl_loaded=True,
        meta={...},          # from NuclearWordMapScorer
        risk_data={...},     # from RiskOrchestrator
        price=2650.0,
    )
    print(result.summary)
    print(result.decision_trace)
"""

from __future__ import annotations

from dataclasses import dataclass


# ─── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class FeatureScore:
    """SHAP-style feature importance entry."""

    name: str
    value: float
    importance: float  # 0–1 normalised contribution to final score
    direction: str  # "bullish" | "bearish" | "neutral"
    description: str  # human-readable explanation of this feature


@dataclass
class ExplainResult:
    """Full explainability output for one nuclear decision."""

    summary: str  # one-sentence decision summary
    feature_scores: list[FeatureScore]  # SHAP-style importance list
    decision_trace: list[str]  # step-by-step reasoning chain
    risk_narrative: str  # plain-English risk assessment
    action_advice: str  # what the operator should do now
    confidence_breakdown: dict[str, float]  # sub-scores that built confidence
    severity: int
    action: str
    rl_action_label: str
    historical_analog: str | None


# ─── Historical analog database ───────────────────────────────────────────────

_ANALOGS: dict[int, tuple[str, str]] = {
    10: (
        "2022 Russia-Ukraine nuclear threat (Feb 24)",
        "Gold +12% in 48h, then -8% reversal. VIX +45%. USD safe-haven bid. "
        "Expected max drawdown if long: -28%. Recommended: full liquidation.",
    ),
    9: (
        "2003 Iraq War start (Mar 20)",
        "Gold +6% spike, high volatility for 72h. CVaR elevated 3×. "
        "Expected max drawdown if long: -18%. Recommended: liquidate + wait.",
    ),
    8: (
        "2019 Iran-US escalation (Jan 3)",
        "Gold +4%, USD safe-haven bid, oil +4%. Volatility elevated 48h. "
        "Expected max drawdown if long: -12%. Recommended: hedge + reduce size.",
    ),
    7: (
        "2022 Taiwan Strait tensions (Aug)",
        "Gold +2.5%, vol spike, risk-off across EM. Expected max drawdown if long: -8%. Recommended: hedge positions.",
    ),
    6: (
        "2023 Middle East flare-up (Oct 7)",
        "Gold +1.5%, short-term uncertainty. Normalised within 5 days. "
        "Expected max drawdown if long: -5%. Recommended: reduce size.",
    ),
    5: (
        "Elevated geopolitical noise (generic)",
        "Historical average: Gold +0.8% over 24h, then mean-reversion. "
        "Expected max drawdown if long: -3%. Recommended: monitor closely.",
    ),
}

# ─── Action advice templates ──────────────────────────────────────────────────

_ACTION_ADVICE: dict[str, str] = {
    "nuclear_mode": (
        "IMMEDIATE ACTION REQUIRED: All positions have been liquidated. "
        "Do NOT re-enter until nuclear level drops to 0 and trading is manually resumed. "
        "Monitor /api/nuclear/status. Resume via POST /api/nuclear/resume."
    ),
    "hedge_mode": (
        "Hedge mode active: max risk reduced to 15%, inverse hedges opened on XAU_USD. "
        "Avoid adding new long exposure. Monitor severity — if it rises to 9+, "
        "expect automatic escalation to nuclear mode."
    ),
    "pause_new_entries": (
        "New entries paused. Existing positions are held. "
        "Do not open new trades until severity drops below 5. "
        "Review matched keywords and monitor news feed."
    ),
    "normal": ("Normal trading conditions. No action required. Continue monitoring the geopolitical gauge."),
}


# ─── Engine ───────────────────────────────────────────────────────────────────


class NuclearExplainabilityEngine:
    """
    Produces structured, SHAP-style explanations for nuclear AI decisions.

    Stateless — safe to call from any async context.
    """

    def explain(
        self,
        severity: int,
        action: str,
        rl_action: int,
        rl_loaded: bool,
        meta: dict,
        risk_data: dict | None = None,
        price: float = 0.0,
    ) -> ExplainResult:
        """
        Build a full ExplainResult for a nuclear decision.

        Parameters
        ----------
        severity    : WORDMAP severity [0–10]
        action      : NuclearWordMapScorer action string
        rl_action   : RL agent action [0–3]
        rl_loaded   : whether the PPO RL model is loaded
        meta        : dict from NuclearWordMapScorer.score_event()
        risk_data   : dict from RiskOrchestrator.get_status()
        price       : current XAUUSD mid price
        """
        rl_labels = {0: "NORMAL", 1: "PAUSE", 2: "HEDGE", 3: "NUCLEAR"}
        rl_label = rl_labels.get(rl_action, "NORMAL")

        matched_terms = meta.get("matched_terms", [])
        category_scores = meta.get("category_scores", {})
        base_score = meta.get("base_score", 0.0)
        vol_factor = meta.get("vol_factor", 1.0)
        sentiment_factor = meta.get("sentiment_factor", 0.0)
        confidence = meta.get("confidence", 0.0)

        # ── Feature scores (SHAP-style) ───────────────────────────────────────
        feature_scores = self._build_feature_scores(
            severity,
            matched_terms,
            category_scores,
            base_score,
            vol_factor,
            sentiment_factor,
            risk_data or {},
        )

        # ── Decision trace ────────────────────────────────────────────────────
        trace = self._build_trace(
            severity,
            action,
            rl_action,
            rl_label,
            rl_loaded,
            matched_terms,
            category_scores,
            vol_factor,
            sentiment_factor,
            confidence,
            risk_data or {},
        )

        # ── Summary ───────────────────────────────────────────────────────────
        summary = self._build_summary(severity, rl_label, rl_loaded, action, confidence)

        # ── Risk narrative ────────────────────────────────────────────────────
        narrative = self._build_narrative(severity, action, risk_data or {}, price)

        # ── Historical analog ─────────────────────────────────────────────────
        analog = self._get_analog(severity)

        # ── Confidence breakdown ──────────────────────────────────────────────
        conf_breakdown = {
            "wordmap_keyword_score": round(base_score / 10.0, 4),
            "volatility_amplifier": round(vol_factor - 1.0, 4),
            "sentiment_penalty": round(sentiment_factor / 0.5, 4),
            "category_coverage": round(min(1.0, len(category_scores) / 4.0), 4),
            "overall_confidence": round(confidence, 4),
        }

        return ExplainResult(
            summary=summary,
            feature_scores=feature_scores,
            decision_trace=trace,
            risk_narrative=narrative,
            action_advice=_ACTION_ADVICE.get(action, ""),
            confidence_breakdown=conf_breakdown,
            severity=severity,
            action=action,
            rl_action_label=rl_label,
            historical_analog=analog,
        )

    # ── Feature scores ────────────────────────────────────────────────────────

    def _build_feature_scores(
        self,
        severity: int,
        matched_terms: list[dict],
        category_scores: dict[str, float],
        base_score: float,
        vol_factor: float,
        sentiment_factor: float,
        risk_data: dict,
    ) -> list[FeatureScore]:
        scores: list[FeatureScore] = []
        total = max(base_score * vol_factor + sentiment_factor, 0.001)

        # Top matched keywords
        top_terms = sorted(matched_terms, key=lambda x: x.get("contribution", 0), reverse=True)[:5]
        for t in top_terms:
            contrib = t.get("contribution", 0.0)
            scores.append(
                FeatureScore(
                    name=f'keyword: "{t["term"]}"',
                    value=round(contrib, 3),
                    importance=round(contrib / total, 4),
                    direction="bearish",
                    description=(
                        f'WORDMAP keyword "{t["term"]}" in category '
                        f'"{t["category"]}" matched {t.get("count", 1)}× '
                        f"(weight={t['weight']:.1f}, contribution={contrib:.2f})"
                    ),
                )
            )

        # Volatility amplifier
        vol_contrib = base_score * (vol_factor - 1.0)
        if vol_contrib > 0:
            scores.append(
                FeatureScore(
                    name="volatility_amplifier",
                    value=round(vol_contrib, 3),
                    importance=round(vol_contrib / total, 4),
                    direction="bearish",
                    description=(
                        f"Market volatility is {vol_factor:.2f}× normal. "
                        f"Elevated vol amplifies WORDMAP severity by {(vol_factor - 1) * 100:.0f}%."
                    ),
                )
            )

        # Sentiment penalty
        if sentiment_factor > 0:
            scores.append(
                FeatureScore(
                    name="sentiment_penalty",
                    value=round(sentiment_factor, 3),
                    importance=round(sentiment_factor / total, 4),
                    direction="bearish",
                    description=(
                        f"Negative news sentiment adds +{sentiment_factor:.2f} to severity score. "
                        f"Bearish/fearful news context increases geopolitical risk."
                    ),
                )
            )

        # Risk exposure
        exposure = risk_data.get("current_exposure", 0.0)
        if exposure > 0.3:
            scores.append(
                FeatureScore(
                    name="portfolio_exposure",
                    value=round(exposure, 3),
                    importance=round(min(0.2, exposure * 0.3), 4),
                    direction="bearish",
                    description=(
                        f"Current portfolio exposure is {exposure * 100:.1f}%. "
                        f"High exposure increases urgency of protective action."
                    ),
                )
            )

        # Sort by importance descending
        scores.sort(key=lambda x: x.importance, reverse=True)
        return scores

    # ── Decision trace ────────────────────────────────────────────────────────

    def _build_trace(
        self,
        severity: int,
        action: str,
        rl_action: int,
        rl_label: str,
        rl_loaded: bool,
        matched_terms: list[dict],
        category_scores: dict[str, float],
        vol_factor: float,
        sentiment_factor: float,
        confidence: float,
        risk_data: dict,
    ) -> list[str]:
        trace: list[str] = []

        # Step 1: WORDMAP scoring
        trace.append(
            f"[1] WORDMAP scan: {len(matched_terms)} keyword(s) matched across "
            f"{len(category_scores)} risk category(ies): "
            f"{', '.join(f'{k}={v:.1f}' for k, v in sorted(category_scores.items(), key=lambda x: -x[1])[:3])}."
        )

        # Step 2: Top keyword
        if matched_terms:
            top = max(matched_terms, key=lambda x: x.get("contribution", 0))
            trace.append(
                f'[2] Highest-weight keyword: "{top["term"]}" '
                f"(category={top['category']}, weight={top['weight']:.1f}, "
                f"contribution={top.get('contribution', 0):.2f})."
            )

        # Step 3: Amplifiers
        amp_parts = []
        if vol_factor > 1.05:
            amp_parts.append(f"volatility ×{vol_factor:.2f}")
        if sentiment_factor > 0.1:
            amp_parts.append(f"negative sentiment +{sentiment_factor:.2f}")
        if amp_parts:
            trace.append(f"[3] Score amplified by: {', '.join(amp_parts)}.")
        else:
            trace.append("[3] No amplifiers active (normal vol + neutral sentiment).")

        # Step 4: Severity determination
        trace.append(f"[4] Final severity score: {severity}/10 (confidence={confidence * 100:.0f}%).")

        # Step 5: RL decision
        agent_type = "PPO RL agent" if rl_loaded else "rule-based fallback"
        trace.append(f"[5] {agent_type} mapped severity={severity} → action={rl_label} (RL action index={rl_action}).")

        # Step 6: Risk gate
        exposure = risk_data.get("current_exposure", 0.0)
        max_risk = risk_data.get("max_risk_fraction", 1.0)
        trace.append(f"[6] Risk gate: exposure={exposure * 100:.1f}%, max_risk={max_risk * 100:.0f}%.")

        # Step 7: Final action
        action_desc = {
            "nuclear_mode": "Full liquidation + trading halt activated.",
            "hedge_mode": "Hedge mode activated: max risk → 15%, inverse hedges opened.",
            "pause_new_entries": "New entries paused. Existing positions held.",
            "normal": "No action taken. Normal trading continues.",
        }.get(action, action)
        trace.append(f"[7] DECISION: {action_desc}")

        return trace

    # ── Summary ───────────────────────────────────────────────────────────────

    def _build_summary(
        self,
        severity: int,
        rl_label: str,
        rl_loaded: bool,
        action: str,
        confidence: float,
    ) -> str:
        agent = "RL agent (PPO)" if rl_loaded else "rule-based system"
        action_str = action.replace("_", " ")
        return (
            f"{agent} triggered {rl_label} with {confidence * 100:.0f}% confidence "
            f"(severity {severity}/10) → {action_str}."
        )

    # ── Risk narrative ────────────────────────────────────────────────────────

    def _build_narrative(
        self,
        severity: int,
        action: str,
        risk_data: dict,
        price: float,
    ) -> str:
        cvar = risk_data.get("cvar_95", 0.0)
        exposure = risk_data.get("current_exposure", 0.0)
        drawdown = risk_data.get("drawdown_pct", 0.0)

        if severity >= 9:
            return (
                f"CRITICAL geopolitical event detected. At current exposure "
                f"({exposure * 100:.1f}%), CVaR-95 is {cvar * 100:.2f}%. "
                f"Historical gold moves of +8–15% in 48h are typical for this severity. "
                f"Full liquidation is the only risk-safe response."
            )
        elif severity >= 7:
            return (
                f"HIGH geopolitical risk. Exposure {exposure * 100:.1f}%, "
                f"CVaR-95 {cvar * 100:.2f}%. Hedge mode reduces max loss by ~60%. "
                f"Gold typically moves +2–6% in the first 24h at this severity."
            )
        elif severity >= 5:
            return (
                f"ELEVATED geopolitical noise. Exposure {exposure * 100:.1f}%. "
                f"Pausing new entries limits additional risk accumulation. "
                f"Current drawdown: {drawdown:.2f}%."
            )
        else:
            return (
                f"Normal conditions. Exposure {exposure * 100:.1f}%, "
                f"drawdown {drawdown:.2f}%. No protective action required."
            )

    # ── Historical analog ─────────────────────────────────────────────────────

    def _get_analog(self, severity: int) -> str | None:
        for thresh in sorted(_ANALOGS.keys(), reverse=True):
            if severity >= thresh:
                event, detail = _ANALOGS[thresh]
                return f"{event}: {detail}"
        return None

    # ── Serialise to dict (for JSON broadcast) ────────────────────────────────

    def explain_to_dict(self, *args, **kwargs) -> dict:
        result = self.explain(*args, **kwargs)
        return {
            "summary": result.summary,
            "feature_scores": [
                {
                    "name": f.name,
                    "value": f.value,
                    "importance": f.importance,
                    "direction": f.direction,
                    "description": f.description,
                }
                for f in result.feature_scores
            ],
            "decision_trace": result.decision_trace,
            "risk_narrative": result.risk_narrative,
            "action_advice": result.action_advice,
            "confidence_breakdown": result.confidence_breakdown,
            "severity": result.severity,
            "action": result.action,
            "rl_action_label": result.rl_action_label,
            "historical_analog": result.historical_analog,
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_explainer_instance: NuclearExplainabilityEngine | None = None


def get_explainer() -> NuclearExplainabilityEngine:
    global _explainer_instance
    if _explainer_instance is None:
        _explainer_instance = NuclearExplainabilityEngine()
    return _explainer_instance
