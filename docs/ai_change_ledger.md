# AI Capability Change Ledger

This ledger records additive AI-safety and intelligence changes. Existing brains, strategies, skills, execution paths, and safeguards remain supported unless a removal is explicitly approved.

| Change | Compatibility impact | Evidence | Rollback |
| --- | --- | --- | --- |
| Added `core.ai_contracts` lifecycle and provenance records | Additive; no existing callers changed | Deterministic contract tests | Revert the contract module and tests |
| Added `strategies.strategy_execution_boundary` | Additive; legacy strategy paths remain available | Research/paper/live boundary tests | Remove the guard from new AI-candidate callers |
| Added dynamic-registry candidate gating | AI candidates receive explicit promotion checks; existing non-candidate registrations retain compatibility | Dynamic registry trust-boundary tests | Revert the optional candidate arguments |
| Added inference evidence fields | Additive result metadata; existing prediction fields remain | Inference regression tests | Ignore or remove evidence fields |
| Added `ml.model_quality_gate` | Additive fail-closed calibration, drift, and data-quality evaluator | Model quality gate tests | Remove only new gate call sites |
| Added `core.ai_operations` | Additive health observation, recovery decisions, repair proposals, and hashed audit events; no repair is applied automatically | AI operations contract tests | Remove new control-plane consumers; retain existing health and healing paths |
| Added `security.ai_repair_sandbox` | Candidate source is statically screened and compiled only in a disposable directory; repository and broker state are never mutated | Sandbox validation tests | Remove the optional validation boundary; existing self-healer remains unchanged |
| Added `HealthEngine.run_ai_observation` | Additive bridge from existing health reports to immutable AI evidence | AI operations contract tests | Stop calling the bridge; health probes remain unchanged |
| Added post-repair rollback guard and recovery audit events | Additive fail-closed comparison and append-only evidence binding; existing rollback remains the execution owner | AI operations rollback and audit tests | Remove only new guard/event consumers; preserve existing rollback controls |

## Review rules

- Do not delete or replace an existing AI component solely to simplify the architecture.
- Before any removal, identify direct and indirect callers, preserve a compatibility path, add regression coverage, and record operator approval here.
- Trading code should favor explicit branches, named intermediate values, reason codes, and append-only evidence over compressed refactors.
- Research candidates may be generated freely, but paper and live promotion require the lifecycle and evidence gates.
