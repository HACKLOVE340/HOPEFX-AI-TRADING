# Institutional Readiness Map

An honest assessment of the institutional elements a truly active trading
platform needs — beyond invariants and technical rigor — mapped to what HOPEFX
**already enforces in code**, what is a **codeable gap**, and what is inherently
a **human / organizational process** (which software can *support* with artifacts
and checks, but cannot *be*).

Legend: 🟢 mechanism in code · 🟡 partial / supporting tooling exists · 🧑 human-led process (software-supported)

---

## The maturity model

| # | Element | Status | Mechanism in this codebase / what's needed |
|---|---------|--------|---------------------------------------------|
| 1 | Governance & Oversight | 🟡🧑 | **Code:** `invariants/governance.py` (segregation-of-duties, dual control, deployment gates, human supremacy), `ops_extended.py` (override logging/attribution/authorization, prod-change approval), the **Risk Appetite Framework** (`config/risk_appetite.json` — versioned + signed + reviewed, enforced by `enforce_policy_governance`). **Human:** a standing governance committee that owns the policy file, reviews violations, and approves changes. The *artifacts* (signed policy, audit chain, override records) are code; the *committee* is people. |
| 2 | Stress Testing & Scenario Planning | 🟢 | `scripts/stress_test.py` — runs flash-crash, liquidity-freeze, data-outage, exchange-outage, cascading-failure, chaos, cost-shock, leverage-spike scenarios through the invariant predicates and asserts each control responds as designed. Run weekly / pre-release. Guarded by `tests/unit/test_stress_test.py`. |
| 3 | Human-in-the-Loop | 🟡🧑 | **Code:** kill switch (human engage/deactivate with token), `enforce_order_authorization` (decision id + risk-approval token), `operations.verify_emergency_reversible`, override accountability in `ops_extended.py`. **Needed:** a manual-approval step in the order path for trades above a notional threshold (a `requires_human_approval` gate). **Human:** the reviewers. |
| 4 | Regulatory & Compliance Adaptation | 🟡🧑 | **Code:** `compliance.py` (jurisdiction, retention, restricted lists, surveillance), Risk Appetite Framework `allowed_jurisdictions` / `jurisdictions_blocked`, `enforce_risk_appetite` jurisdiction checks. **Needed:** a regulatory-feed watcher that updates the policy file when rules change. **Human:** compliance officers tracking rule changes. |
| 5 | Risk Appetite Framework | 🟢 | `risk/risk_appetite.py` + `config/risk_appetite.example.json` — formal, versioned, governance-approved policy-as-code (loss limits, off-limits symbols/jurisdictions, leverage, VaR). Enforced by `invariants.enforcement.enforce_risk_appetite`; the policy's own hygiene (signed, not overdue) by `enforce_policy_governance`. |
| 6 | Capital Efficiency Optimization | 🟡 | **Code:** `portfolio.verify_capital_efficiency`, `economic.py` (cost growth, equilibrium), risk-adjusted sizing (Kelly) in `risk/manager.py`. **Needed:** a ROI / risk-adjusted-return dashboard panel and an "idle capital" alert. |
| 7 | Behavioral Monitoring (AI + human) | 🟢 | **AI:** `multi_agent.py` (collusion, emergent behavior, conflict-rate, circular delegation), `ai_governance.py` (reward-hacking, shadow-objective, goal-alignment), `ai_quality.py` (trade clustering, signal concentration). **Human:** `assurance.py` (insider threat, anomalous-access block, least-privilege), `operations.py` (operator fatigue). |
| 8 | Culture of Continuous Improvement | 🧑 | **Software support:** mandatory postmortems (`ops_extended.verify_postmortem_complete`), the stress-test harness as a recurring "what could fail?" exercise, this living readiness map. **Human:** the team ritual of blameless review — not code. |
| 9 | Transparency to Clients | 🟡 | **Code:** `/health/invariants`, `/health/ledger` (capital-equation reconciliation), audit hash-chain, decision lineage (`ai_governance.verify_decision_lineage`), `economic.verify_report_accurate`. **Needed:** a client-facing report endpoint that bundles risk / AI-decision / attribution / allocation into one auditable statement. |
| 10 | Continuous Learning for AI | 🟡 | **Code:** `ml_pipeline.py` (online/offline parity, dataset completeness, training reproducibility, lineage/signing), `drift.py` + the live drift monitor (`/ml/status`, `/ml/models` — real drift score), `ai_quality.py` (calibration). **Needed:** the scheduled retrain pipeline itself (orchestration) — the *guards* are coded, the *cron* is ops. |
| 11 | Customer Support & Incident Management | 🟡🧑 | **Code:** `operations.py` (alert delivery/ack, incident timeline, monitoring coverage), `ops_extended.py` (escalation, root-cause, postmortem), Prometheus alerts (`monitoring/rules/alerts.yml`). **Human:** the on-call rotation and support desk. |
| 12 | Anticipating the Unthinkable | 🟢 | `scripts/stress_test.py` (assumption-breaking scenarios) + `meta.py` (`verify_observed_matches_actual`, anomaly-detector liveness, five master guarantees). Extend the scenario list as new "what ifs" are imagined. |
| 13 | Multi-Scale Risk Intelligence | 🟡 | **Code:** trade-level (`enforce_pre_trade`), portfolio-level (`enforce_exposure`/`enforce_var`/reconciliation), structural (`market_structure.py`, `market_lifecycle.py`, `drift.py` regime/policy drift). **Needed:** explicit short/medium/long horizon dashboards tying them together. |
| 14 | Psychological Resilience | 🧑 | Not software. Supported by: clear runbooks (`docs/INVARIANT_ROLLOUT.md`), fail-safe defaults (monitor mode, fail-open), and drills that build muscle memory — so people act calmly because the system is predictable. The resilience itself is the team's. |
| 15 | AI Alignment & Governance | 🟡🧑 | **Code:** `ai_governance.py` (goal-alignment, reward-hacking, shadow-objective, strategy-approval/identity, self-replication & autonomous-capital controls), `security.py` (prompt-injection, input-poisoning). **Human:** an AI ethics review board that sanctions strategies — the *checks* are coded, the *board* is people. |
| 16 | Resilience Drills | 🟢 | `scripts/stress_test.py` (chaos/outage scenarios) + `resilience.py` (backup recency/integrity, restore-tested, failover, recovery SLA, chaos survival) + the runtime checker's recovery-readiness probe. **Needed for full credit:** running the drills against the *live* deployment, not just predicates. |

---

## What is genuinely code vs. genuinely people

**Code can guarantee** the mechanical controls: limits enforced, policies signed
and obeyed, drills run, violations surfaced, audit tamper-evident, AI behavior
bounded. All of that is in place (this session) and tested.

**Code cannot be** the governance committee, the compliance officers tracking
rule changes, the ethics board, the on-call humans, or the team culture. For
those, software's job is to make the right thing easy and the wrong thing
visible — signed policy-as-code, mandatory postmortems, recurring drills, live
status endpoints. The judgment stays human.

> "It's not about never failing — it's about being able to respond quickly,
> confidently, and transparently when things go wrong." This platform now has
> the instrumentation for that response; the response itself is the team's.

---

## Operate these

| Cadence | Action |
|---------|--------|
| Per release & weekly | `python scripts/stress_test.py` (resilience drill) |
| Continuously | `scripts/invariant_soak.py` + Grafana `hopefx_invariant_*` + `monitoring/rules/alerts.yml` |
| On policy change | edit `config/risk_appetite.json`, bump `version`, re-sign `approved_by`, reset `review_due`; CI/`enforce_policy_governance` flags unsigned/overdue |
| Quarterly | governance committee reviews the risk-appetite policy + this readiness map |
| Per incident | postmortem (tracked by `ops_extended.verify_postmortem_complete`) |
