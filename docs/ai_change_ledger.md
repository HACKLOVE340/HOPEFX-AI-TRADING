# AI Capability Change Ledger

This ledger records additive AI-safety and intelligence changes. Existing brains, strategies, skills, execution paths, and safeguards remain supported unless a removal is explicitly approved.

| Change | Compatibility impact | Evidence | Rollback |
| --- | --- | --- | --- |
| Added `core.ai_contracts` lifecycle and provenance records | Additive; no existing callers changed | Deterministic contract tests | Revert the contract module and tests |
| Added `strategies.strategy_execution_boundary` | Additive; legacy strategy paths remain available | Research/paper/live boundary tests | Remove the guard from new AI-candidate callers |
| Added dynamic-registry candidate gating | AI candidates receive explicit promotion checks; existing non-candidate registrations retain compatibility | Dynamic registry trust-boundary tests | Revert the optional candidate arguments |
| Added inference evidence fields | Additive result metadata; existing prediction fields remain | Inference regression tests | Ignore or remove evidence fields |
| Added `ml.model_quality_gate` | Additive fail-closed calibration, drift, and data-quality evaluator | Model quality gate tests | Remove only new gate call sites |

## Review rules

- Do not delete or replace an existing AI component solely to simplify the architecture.
- Before any removal, identify direct and indirect callers, preserve a compatibility path, add regression coverage, and record operator approval here.
- Trading code should favor explicit branches, named intermediate values, reason codes, and append-only evidence over compressed refactors.
- Research candidates may be generated freely, but paper and live promotion require the lifecycle and evidence gates.
