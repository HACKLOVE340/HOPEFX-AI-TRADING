# Master Platform Engineering, Operations, Infrastructure and Governance Specification

**Document Group:** 2 of 4 · **Status:** Living Architecture Specification
**Relationship rule:** additive. This document does not replace, rewrite or invalidate
Group 0 (AI Hub Master Architecture) or Group 1 (Advanced Intelligence). Where a
capability belongs to another group, this document **references** the relationship
rather than duplicating the content.

---

## How to read this document

Every chapter carries a measured status. This is not a wish-list: the platform
already contains 5,582 lines of invariant code, 10,088 lines of security code, 19
CI workflows, full Kubernetes and Helm manifests, chaos engineering, tracing and
compliance packages. A specification that ignored that would send engineers to
rebuild what exists.

| Marker | Meaning |
|---|---|
| **AVAILABLE** | Implemented. Named here with its location so nobody re-specifies it. The chapter documents the contract and any hardening. |
| **PARTIAL** | Exists and under-reaches. The gap is stated precisely, never rounded up. |
| **NEW** | Nothing implements it. Full specification given. |

Each chapter follows one structure: purpose and why it exists · architecture and
components · data and control flow · interaction with the platform · security and
governance · failure modes and resilience · human oversight · KPIs · priority and
dependencies · risks and mitigations · evolution · **why this design**.

---

## 0. The governing rules of this document

Four rules bind every chapter. They are stated once here rather than repeated
thirty times.

### Rule 1 — A control that cannot fail is not a control

This is the rule the platform earned the hard way, and it is placed first because
it is the one most easily lost.

During the delivery of Group 0, **five separate checks were found that could not
fail**: three tests that asserted something a second code path also satisfied, one
concurrency test that never reached the race it existed to catch, and a dead-code
sweep that confidently reported 154 findings while examining nothing at all. Every
one was found by deliberately breaking the code and watching. None was found by
reading.

Therefore: **every gate, guard, probe, alert, invariant, evaluation and health
check specified in this document ships with evidence that it is capable of
returning a negative result.** Not evidence that it passed — evidence that it can
fail. The accepted method is defect injection: introduce the fault the control
exists to catch, confirm by inspection that the injection actually applied, run
the control, and record that it fired.

A control with no such record is treated as absent. This applies with double force
to Group 1, where the system evaluates itself: **a self-evaluating system whose
evaluations cannot fail is worse than no evaluation, because it manufactures
confidence instead of silence.**

#### The rule is now enforced rather than remembered — Phase R2

`docs/GATE_EVIDENCE.toml` records, per gate, whether its ability to fail has been
demonstrated, by what injection, and where that injection lives as a re-runnable
test. `scripts/gate_evidence.py --check` runs in pre-commit.

Gates are **discovered**, never hand-listed — from `scripts/ci/gate_*.py` and from
the pre-commit hooks that run this repository's own scripts. A list would go stale
the first time somebody added a gate, and the omission would be indistinguishable
from compliance. The ledger proved that immediately: it blocked **its own hook**
for arriving without evidence.

| Measured 2026-09-08 | |
|---|---:|
| Gates discovered | 23 |
| Proven able to fail, by a test that injects | 13 |
| Unproven — the ratcheted baseline | 10 |

**Phase R3 turned it from 13 to 10, and injecting found two more defects.** Gate M
exited **0** when its A/B dataset was missing, so a rename or deletion turned the
ML edge guard off and left CI green — it fails closed now. And `check_secrets.sh`
matched its placeholder allowlist against the whole line, so a genuine credential
containing `xxx`, `none`, `null` or `tbd` anywhere in it was skipped; the match is
now anchored to the parsed value.

That is **eight** controls found unable to fail in this repository, every one
found by breaking it rather than reading it.

The count may only fall. A new gate with no evidence blocks; evidence that stops
existing blocks; a proven gate downgraded blocks. All three were verified by
performing them.

**What this ledger does not cover, said plainly.** The 339 `verify_*` /
`catastrophic_*` predicates under `invariants/` are controls too and are **not**
in it. They are a different shape — pure functions returning violations rather
than processes that exit non-zero — and need their own mechanism. Recording that
is better than a ledger that silently implies they are covered.

### Rule 2 — An unmeasured value is absent, never zero

A metric that was not collected, a screen count that could not be read, a
dependency whose version could not be resolved: each of these is *unknown*, and
rendering it as `0` invents a fact. Every measurement surface in this document
distinguishes "measured as zero" from "not measured", and says which.

### Rule 3 — Fail closed on anything that spends, trades or exposes

Where a control cannot determine whether an action is safe, it refuses. This
covers the kill switch, the invariant enforcer, the budget ceiling, the delegation
bound, the consent gate and the secret boundary. An unreadable kill switch stops
the system; it does not report "no halt found".

### Rule 4 — Evidence that resolves is not evidence that runs

The Group 0 capability registry verifies that each row's evidence locator
resolves. It has **no opinion about whether anything calls it** — which is how an
isolated-worker runtime was marked live while imported by nothing outside its own
tests. Every registry in this document carries a **caller check** alongside the
resolution check.

---

# PART I — FOUNDATIONS

## Chapter 1 — Platform Engineering Architecture

**Status: PARTIAL.** The platform has an architecture; it does not have an
enforced statement of one. `ARCHITECTURE.md` is the canonical map and
`CLAUDE.md`/`AGENTS.md` carry the conventions, but the boundary between
`data/`, `data_layer/` and `market_data/` is explicitly undocumented (recorded as
F217), and 70+ top-level packages have no stated ownership.

### Purpose and why it exists

Platform engineering is the discipline that makes the *other* disciplines
possible. Its object is not the trading system or the AI; it is the surface every
engineer and every agent touches when they build, test, deploy, observe and
recover. Without it, each capability invents its own conventions and the platform
becomes a federation of dialects.

The problems it solves here are concrete and already visible:

* **Canonical-versus-legacy confusion.** `backtesting/` is canonical and
  `backtest/` is a re-export shim; `strategies/` is canonical and `strategy/` is
  the live ML engine. New code added to the wrong one is invisible to the tooling
  that governs the right one.
* **Undocumented boundaries.** Three packages hold market data with no agreed rule
  for which gets new work. The current guidance — extend the package a module
  already lives in, and say which you chose — is a holding position, not a design.
* **Shadowing hazards.** A top-level `websocket/` package once shadowed the
  `websocket-client` library for the entire process and silently disabled a REST
  fallback. That class of failure is a naming-policy failure.

### Architecture and components

Four artefacts, three of which exist:

| Artefact | Role | Status |
|---|---|---|
| `ARCHITECTURE.md` | Canonical module map, entry points, env flags | AVAILABLE |
| `CLAUDE.md` / `AGENTS.md` | Conventions and the high-signal subset | AVAILABLE |
| `.claude/skills/` (61 skills) | Encoded classes of mistake already made here | AVAILABLE |
| **Package ownership register** | Owner, tier, stability, deprecation state per top-level package | **NEW** |

The ownership register is the missing piece. Each of the ~70 top-level packages
declares: owning domain, canonical-or-shim status, stability tier (`core`,
`supporting`, `experimental`, `deprecated`), the packages it may import, and the
packages forbidden to import it.

### Data and control flow

The register is declarative data, checked at CI time by a structural test that
parses imports with the AST rather than grepping — because grepping for import
statements matches the strings inside docstrings that *discuss* the rule, a defect
already made and fixed once in this repository.

```
package_register.toml
        │
        ▼
  AST import walk over the repo
        │
        ├── import crosses a forbidden edge  → CI failure naming both packages
        ├── new top-level package unregistered → CI failure
        └── shim imported by new code         → CI failure naming the canonical
```

### Interaction with the rest of the platform

Group 1's §22 Autonomous Standards Guardian and §56 Continuous Architecture Review
**consume this register**; they do not define it. That is the group boundary
working: the register is a platform-engineering artefact, and the intelligence
that watches it for drift is Group 1.

### Security and governance

The register is a vault-protected path. An AI-proposed change may *report* that a
boundary should move; it may not move one. Boundary changes require the same
two-human approval as any vault path.

### Failure modes and resilience

The realistic failure is not the register being wrong — it is the register being
**unenforced**, drifting into decoration while imports do as they please. Rule 1
applies: the CI check ships with a deliberately-introduced forbidden import,
proving it fails.

### Human oversight

The register is authored by humans and changed by humans. This is deliberate:
architecture boundaries are the one place where the cost of a wrong automated
decision is paid by everyone, for years.

### KPIs

| KPI | Definition | Target |
|---|---|---|
| Register coverage | Top-level packages with an entry | 100% |
| Forbidden-edge violations | CI failures on the boundary check | 0 sustained |
| Shim leakage | New code importing a shim | 0 |
| Undocumented-boundary count | Boundaries flagged as unagreed (currently 1: `data/` ÷ `data_layer/`) | 0 |

### Priority and dependencies

**Priority: high, and first.** It depends on nothing and several later chapters
depend on it — dependency management (Ch 22), technical debt (Ch 23), and the
standards guardian in Group 1 all read the register.

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| The register becomes a rubber stamp nobody updates | The unregistered-package check fails CI, so it cannot be ignored silently |
| Enforcement is so strict it blocks legitimate work | Stability tiers: `experimental` packages have loose edges by design |
| The `data/` ÷ `data_layer/` boundary is decided badly under time pressure | It is a named open question with a written holding position, resolved deliberately |

### Evolution

Phase 1: register plus unregistered-package check. Phase 2: forbidden-edge
enforcement. Phase 3: the register gains a stability *history*, so a package's
drift from `experimental` to load-bearing is visible before it is load-bearing.

### Why this design

Because the alternative — architecture as prose in a document — is what the
platform already has, and it produced a package that shadowed a library for the
whole process. Prose does not fail CI. **A boundary that is not machine-checked is
a boundary that exists only while everyone remembers it.**

---

## Chapter 2 — Software Development and Architecture Standards

**Status: AVAILABLE, with one gap.** `ruff` (lint and format), `bandit`,
`detect-secrets`, `check-merge-conflict` and a per-module coverage gate all run in
`pre-commit` and in CI. Python 3.12 is the production target; CI tests 3.11 and
3.12. The gap is that the standards live in three documents and are enforced by a
fourth, with no single index.

### Purpose and why it exists

Standards exist so that reading unfamiliar code costs a minute rather than an
hour, and so that a defect class is fixed once rather than per-author. The
enforced ones here are already strong; the risk is that the *unenforced* ones —
naming, docstring content, error-message style — drift because nothing checks them.

### Architecture and components

| Layer | Mechanism | Status |
|---|---|---|
| Formatting and lint | `ruff check` / `ruff format` | AVAILABLE |
| Security static analysis | `bandit`, CodeQL, Fortify, Codacy, Trivy | AVAILABLE |
| Secret detection | `detect-secrets` | AVAILABLE |
| Coverage floor | Per-module gate ≥ 80% | AVAILABLE |
| Merge-conflict markers | `check-merge-conflict` | AVAILABLE |
| Type checking | `typecheck` job in `ci.yml`; frontend `tsc --noEmit` | AVAILABLE |
| **Standards index** | One document listing every rule and where it is enforced | **NEW** |

### Governance: the non-negotiables

Four rules already carry the weight of policy and are restated here because they
are the ones skipped under time pressure:

1. `ruff check` clean and touched files compile.
2. **`pre-commit run --all-files` actually run** — never `--no-verify`. That flag
   is precisely how merge-conflict markers and lint regressions reach `main`.
3. No conflict markers.
4. No secrets, ever. `prop_firm_mode.json` and `.env.example` carry placeholders
   only, and `prop_firm_mode.json` is deliberately *tracked* so CI has a config to
   load — which makes putting a real credential in it a live hazard rather than a
   theoretical one.

Two further rules come from hard experience and are elevated to standard here:

5. **Every fix ships with a test confirmed failing on the pre-fix tree.** Not
   written against it — *run* against it, and watched to fail.
6. **Prove by execution, not by reading.** Reproduce the defect by running it
   before fixing, and re-run the same reproduction after. Nine defects found in
   this repository read as correct.

### KPIs

| KPI | Target |
|---|---|
| `--no-verify` commits reaching `main` | 0 |
| Fixes shipped without a confirmed-failing test | 0 |
| Modules below the coverage floor | 0 |
| Mean time from lint regression introduced to caught | < 1 commit |

### Why this design

Because rules 5 and 6 are the ones that catch what the automated gates cannot. A
linter proves style; only a failing test proves a fix. **The gates catch what
tools can see, and the two disciplines catch what only running the code reveals.**

---
# PART II — INFRASTRUCTURE AND DELIVERY

## Chapter 3 — Infrastructure Architecture: Cloud, Hybrid, Local and Private

**Status: AVAILABLE.** The platform ships Kubernetes manifests (13), a Helm chart,
Docker Compose in five variants (default, low-latency, sentinel, smoke, Caddy,
Hostinger), an ArgoCD application, an nginx and a Caddy edge, a Redis cluster
manifest, and VPS bootstrap and reset scripts. `infrastructure/` carries 2,463
lines of Python.

### Purpose and why it exists

A money-moving platform must be able to run in more than one place, for two
different reasons that are often confused. The first is **resilience** — a
provider outage must not be an outage. The second is **sovereignty** — some
processing must never leave infrastructure the owner controls, which is Group 1
§23's Human Sovereignty Zone expressed as infrastructure rather than as policy.

### Architecture: three deployment topologies

| Topology | Where | Purpose | Status |
|---|---|---|---|
| **Managed cluster** | Kubernetes + Helm + ArgoCD | Primary production | AVAILABLE |
| **Single host** | Docker Compose + Caddy/nginx on a VPS | Low-cost, low-latency, and the disaster fallback | AVAILABLE |
| **Private/local** | Local models (`ollama`), local agents | Sovereignty: work that must not reach an external provider | PARTIAL |

The private topology is the gap. `ai/local_model.py` and the `ollama` provider
exist, so a local model can be *called*; what does not exist is an enforced
guarantee that specified classes of data are only ever processed there. That
guarantee is Chapter 13's data-egress boundary, and Group 1 §24 depends on it.

### Data and control flow

```
                       ┌──────────────── ArgoCD ◄── git (declared state)
                       ▼
   ingress (nginx/Caddy) ──► API pods ──► Redis ──► Postgres
            │                   │
            │                   ├──► broker adapters (OANDA, IBKR FIX)
            │                   └──► AI gateway ──► external providers
            │                                  └──► local models (sovereign path)
            ▼
      k8s NetworkPolicy  ── egress restricted by manifest
```

`k8s/network-policy.yaml` is the control point where the sovereign path is
enforceable at the network layer rather than only in code — which matters,
because a code-level boundary is bypassed by any new call site and a network
policy is not.

### Security and governance

* `k8s/k8s-secrets.yaml` and `k8s/secrets.example.yaml` separate the shape of
  secrets from their values; the example file is the one that is tracked.
* `k8s/kill-switch-configmap.yaml` and `kill-switch-rbac.yaml` mean the kill
  switch is operable **without a deploy** and with its own RBAC — the correct
  design, because a kill switch that needs a deploy is not a kill switch.
* `pdb.yaml` (PodDisruptionBudget) protects against voluntary disruption taking
  the trading path down during a routine node drain.

### Failure modes and resilience

| Failure | Response | Status |
|---|---|---|
| Node loss | PDB + replica count; pods rescheduled | AVAILABLE |
| Cluster loss | Fall back to single-host Compose on the VPS | AVAILABLE, **rehearsal not evidenced** |
| Redis loss | `redis-cluster.yaml`; budget and job state degrade to in-memory with `durable=false` reported | AVAILABLE |
| External AI provider loss | Per-vendor circuit breakers and chain fall-through | AVAILABLE (`ai/gateway/breakers.py`, `chain.py`) |
| Egress blocked | Local model path | PARTIAL |

The cluster-loss row is the honest weak point: the fallback **exists as scripts**
and there is no recorded evidence of it having been exercised. Chapter 10 makes
that a scheduled drill rather than a hope.

### Human oversight

Infrastructure changes are declared in git and applied by ArgoCD, so the review
surface is a pull request rather than a console. This is the correct default and
should not be weakened for speed: a console change is a change with no reviewer
and no history.

### KPIs

| KPI | Definition | Target |
|---|---|---|
| Declared-state drift | Resources differing from git | 0 |
| Fallback rehearsal age | Days since single-host fallback last exercised | ≤ 90 |
| Sovereign-path leakage | Classified payloads reaching an external provider | 0, enforced |
| Egress policy coverage | Pods with an explicit NetworkPolicy | 100% |

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| The VPS fallback has rotted and nobody knows | Scheduled drill with recorded evidence (Ch 10) |
| A new call site bypasses the sovereign boundary in code | Enforce at NetworkPolicy as well as in code — two independent layers |
| Secrets drift between k8s, Compose and `.env` | Single generator (`deployments/gen_env.sh`) and an env-consistency CI job, which already exists in `tests.yml` |

### Why this design

Because the two reasons for multi-topology are different and must not be
collapsed. Resilience wants *any* second place to run. Sovereignty wants a
*specific* place, with an enforced boundary. A design that satisfies only the
first will quietly send confidential analysis to a third party during a failover —
which is why the failover path and the sovereign path are specified separately.

---

## Chapter 4 — Environment and Configuration Management

**Status: AVAILABLE.** `config/` carries 2,857 lines, `scripts/bootstrap_dev.py`
generates a dev `.env` and seeds users, `deployments/gen_env.sh` generates
deployment env, and `tests.yml` runs an `env-consistency` job.

### Purpose and why it exists

Configuration is where "it works on my machine" is decided. The specific hazards
here are already known: `WORDMAP.json` is gitignored and copied from an example;
`prop_firm_mode.json` is deliberately tracked with placeholders **and ships
`enabled: true` with the FTMO ruleset**, so a fresh deployment starts with those
prop-firm limits active. That is a configuration fact with direct trading
consequences, and it belongs in a specification rather than in a comment.

### Architecture

Three tiers, resolved in order, most specific winning:

1. **Defaults in code** — safe, restrictive, and never containing a credential.
2. **Environment files** — per-environment, generated rather than hand-edited.
3. **Runtime overrides** — feature flags and kill switches in Redis/ConfigMap,
   changeable without a deploy.

Tier 3 exists because tiers 1 and 2 both require a deploy to change, and some
things must change faster than a deploy.

### Governance

* Defaults fail closed. An unset AI improvement-cycle interval means *off*; an
  unparseable one also means off, because a typo read as "run continuously" is the
  worst available reading of a mistake.
* No credential has a default. A missing credential is a startup failure, not a
  fallback to an empty string.
* Every runtime override is auditable: who set it, when, and why.

### Failure modes

| Failure | Correct behaviour |
|---|---|
| Config file missing | Named startup failure, not silent defaults |
| Value unparseable | Fail closed for anything that spends, trades or exposes; otherwise use the default and **log that the default was used** |
| Runtime override store unreachable | For a kill switch: **halt**. For a feature flag: last-known value, and report staleness |

The asymmetry in the last row is deliberate and is Rule 3. An unreadable kill
switch that answers "no halt found" has turned itself into a suggestion.

### KPIs

Config-related startup failures (target: 0 in production, non-zero in CI is
healthy), drift between environments (0), and mean age of the last override audit
entry.

### Why this design

Because the three tiers map onto three different change *speeds* — release, deploy,
immediate — and collapsing them forces every urgent change through a slow path.
The kill switch is the proof: it lives in tier 3 precisely so that stopping the
platform never waits for a build.

---

## Chapter 5 — Deployment Architecture, Release Management and CI/CD

**Status: AVAILABLE and unusually strong.** Nineteen workflows. `ci.yml`
(pre-commit, dependency-scan, typecheck, test, C++ shim build, frontend),
`tests.yml` (test, auth-coverage, env-consistency, docker-smoke-structural,
model-accuracy, dead-file-detection, coverage-gate, gate-a-auth-coverage),
`security-scan.yml` (bandit, safety, trivy, secrets), plus CodeQL, Fortify,
Codacy, load-test, lockfile, release, deploy, and retrain workflows.

### Purpose and why it exists

The pipeline is the only thing standing between an idea and production. Its job is
not to be fast; it is to be **impossible to bypass**. Every gate that can be
skipped will be skipped on the day it matters most.

### Architecture: the gate ladder

```
commit
  │
  ├─ pre-commit (local)      ruff · bandit · detect-secrets · merge-conflict
  ▼
pull request
  │
  ├─ ci.yml                  pre-commit · dependency-scan · typecheck · test · frontend
  ├─ tests.yml               coverage-gate · auth-coverage · env-consistency
  │                          docker-smoke · model-accuracy · dead-file-detection
  ├─ security-scan.yml       bandit · safety · trivy · secrets
  ├─ codeql / fortify / codacy
  ▼
merge
  │
  ├─ release.yml             artefact build and tag
  ▼
deploy.yml → ArgoCD → cluster
```

### Notable existing decisions worth preserving

* **`e2e` and `slow` are always skipped in CI.** This is a deliberate trade, and
  it has a cost: the isolated-worker tests are `slow`, so the process-boundary
  guarantees are *not* exercised by CI. Named here so the trade is visible.
* **Model artefacts are committed** under `ml/saved_models/` and `ml/rl_models/`,
  whitelisted in `.gitignore` and checksum-verified in CI. `dashboard/dist/` is
  committed so the server can serve the UI with no build step. These are
  deliberate and must not be "cleaned up".
* **Retrain workflows pin Python 3.12**, matching the Dockerfile, so pickled model
  artefacts are produced on the interpreter that loads them. If the Dockerfile's
  Python changes, the retrain workflows change in the same commit.

### Gaps

| Gap | Consequence | Priority |
|---|---|---|
| No progressive delivery (canary/blue-green) | A bad release reaches 100% of traffic at once | High |
| No automated rollback trigger | Rollback is a human noticing | High |
| `slow`-marked guarantees never run in CI | Process isolation is specified and unexercised | Medium |
| No deployment freeze window tied to market hours | A deploy can land mid-session | Medium |

### Human oversight

Deployment to production requires a human. This is not negotiable on a platform
that moves money, and it is the point at which Group 1's authority tiers stop:
the AI may propose, plan and prepare a release; **Tier 5 execution remains human**.

### KPIs

| KPI | Target |
|---|---|
| Change failure rate | < 10% |
| Mean time to restore | < 30 min |
| Deploys requiring manual rollback | trending to 0 |
| Pipeline bypass events (`--no-verify`, force-merge) | 0 |
| Gate-can-fail evidence coverage (Rule 1) | 100% of gates |

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| The pipeline becomes so slow it is routed around | Split fast gates from slow ones; keep the required set under 15 minutes |
| A green pipeline is mistaken for a safe release | Progressive delivery: green means *ready to expose to 5%*, not *ready for everyone* |
| A gate silently stops testing anything | Rule 1 — every gate carries injection evidence |

### Why this design

Because the existing pipeline is already comprehensive, and the marginal value of
a twentieth check is far lower than the marginal value of **knowing the nineteen
can fail**. The `dead-file-detection` job is instructive: it is exactly the kind of
check that can quietly stop examining anything, and under Rule 1 it now must prove
it still bites.

---

## Chapter 6 — Change, Release and Lifecycle Management

**Status: PARTIAL.** Versioning and release workflows exist. What is missing is the
*record*: which change went out when, what it touched, and what it was expected to
do.

### Purpose

Change management answers three questions after the fact: what changed, who
approved it, and what happened next. The third is the one usually missing, and it
is the one that turns a deployment history into Group 1's §32 Outcome Memory.

### Architecture

A **change record** per release, generated rather than written:

| Field | Source |
|---|---|
| Change ID, timestamp, actor | CI |
| Commits and diff surface | git |
| Packages touched | package register (Ch 1) |
| Risk tier | derived from packages touched — trading path, AI path, or presentation |
| Approvals | PR reviews |
| Expected effect | author-stated, required for `core`-tier changes |
| Observed effect | telemetry window after deploy |
| Rollback | whether one occurred, and why |

The *expected effect* field is what makes the record useful: without a prediction,
the observed telemetry has nothing to be compared against, and correlation is
guesswork.

### Interaction with the platform

This record is the primary input to Group 1's §16 operational correlation engine —
"what deployed just before latency rose" is unanswerable without it — and to §21
technical-debt forecasting, which needs modification frequency per package.

### KPIs

Change records with a stated expected effect (target 100% of `core`-tier), mean
time from deploy to first observed effect, and the proportion of incidents whose
cause was a change recorded here.

### Why this design

Because a deployment log records that something happened, and a change record
records what it was *for*. Only the second can be evaluated. **A history without
predictions cannot teach anything**, which is precisely why Group 1's outcome
memory needs this chapter to exist first.

---

## Chapter 7 — Scalability, Elasticity, Capacity Planning and Resource Management

**Status: PARTIAL.** Bounded concurrency, an ageing priority queue, per-vendor
circuit breakers, budget ceilings, a delegation bound and frame budgets all exist.
Horizontal autoscaling and forward capacity planning do not.

### Purpose

Two different problems share this chapter and must not be confused. **Scalability**
is whether the system can handle more. **Capacity planning** is whether it will be
able to next quarter. The first is an architecture property; the second is a
forecasting practice.

### What exists

| Control | Location | What it bounds |
|---|---|---|
| Job concurrency | `ai/jobs/runner.py` | Simultaneous AI jobs |
| Ageing priority queue | `ai/jobs/priority.py` | Starvation of low-tier work |
| Circuit breakers | `ai/gateway/breakers.py` | Cascading provider failure |
| Budget ceiling | `ai/gateway/budget.py`, `budget_store.py` | Model spend, per operator |
| Delegation bound | `ai/jobs/lineage.py` | Runaway agent trees — depth, fan-out, total descendants |
| Frame budget | `frontend/src/hub/frameBudget.ts` | Client render cost |
| Rate limiting | `rate_limiting/` (839 LOC) | Request rate |

This is a strong set, and it shares one design property worth naming: **each bound
refuses rather than degrades silently**, and says which bound it hit.

### Gaps

* **No horizontal autoscaling.** Replica counts are static in the manifests.
* **No capacity forecast.** Nothing projects when Redis memory, Postgres storage or
  the model budget will be exhausted. (Redis currently reports `maxmemory` as
  unlimited — an unbounded store on a bounded host.)
* **No load-shedding policy.** At saturation the behaviour is queueing, not a
  stated decision about what to drop first.

### Failure modes and resilience

The dangerous saturation mode on this platform is not slowness — it is a queue
that grows until the trading path is starved behind AI work. The correct response
is a **priority floor**: risk and execution work is never queued behind analysis,
regardless of arrival order. The ageing queue prevents starvation *within* AI work;
it does not currently express this cross-domain floor.

### KPIs

Headroom on each bounded resource (measured, and absent where unmeasured — Rule
2), time-to-exhaustion forecast per resource, load-shed events with the reason,
and the proportion of saturation events where the trading path was unaffected
(target: 100%).

### Why this design

Because bounding is cheap and forecasting is not, and the platform has done the
cheap half. Every bound above prevents a specific runaway that has a name. What
none of them does is tell you the month before Redis fills — and that is a
different discipline, which is why it is specified separately rather than folded
into "scalability".

---
# PART III — RELIABILITY AND CONTINUITY

## Chapter 8 — High Availability, Fault Tolerance and Resilience Engineering

**Status: AVAILABLE and strong.** `resilience/` carries 2,378 lines and `chaos/`
carries 1,277 — the platform already practises deliberate failure injection, which
is Rule 1 applied to infrastructure rather than to tests.

### Purpose and why it exists

Three words often used interchangeably mean different things, and the distinction
decides the design:

* **High availability** — the system stays up when a component dies. Redundancy.
* **Fault tolerance** — the system produces correct results despite a fault.
  Correctness, not uptime.
* **Resilience** — the system recovers to a good state after being pushed out of
  one. A time-domain property.

A trading platform needs all three and needs them ranked: **correct-and-down beats
wrong-and-up.** A system that keeps trading on stale prices is worse than one that
halts.

### Architecture

| Layer | Mechanism | Status |
|---|---|---|
| Process | Isolated workers with timeout, memory cap and real termination (`ai/jobs/isolation.py`) | AVAILABLE |
| Service | Circuit breakers per vendor; chain fall-through | AVAILABLE |
| Data | Staleness and drift gating on inference (`ml/inference_engine.py`) | AVAILABLE |
| Trading | Pre-trade gate, VaR/CVaR, Kelly sizing, kill switch (`risk/manager.py`) | AVAILABLE |
| Invariants | 5,582 LOC of `verify_*` / `catastrophic_*` predicates with fail-closed enforcement | AVAILABLE |
| Cluster | PDB, replicas, NetworkPolicy | AVAILABLE |
| Chaos | Deliberate fault injection | AVAILABLE |

### The rule that governs all of them

**Never weaken a risk gate, kill switch, or staleness/drift check without explicit
instruction.** This is stated in the platform's own contributor contract and is
elevated here to a governance rule of this document. It has a corollary that is
easy to miss: *a change that makes a gate stop firing is a weakening,* even when
no gate code was edited. That is the dead-control failure, and it is why Rule 1
demands injection evidence rather than a passing run.

### Failure modes and resilience requirements

| Failure | Required behaviour | Evidence needed |
|---|---|---|
| Broker connection lost mid-order | No duplicate order on reconnect; sequence integrity | FIX sequence tests |
| Price feed stale | Inference refuses; no trade on stale data | Staleness gate injection |
| Model drift beyond threshold | Inference refuses and reports | Drift gate injection |
| Redis unavailable | Budget and job state degrade with `durable=false` **reported**, never silently | Existing, tested |
| An isolated worker segfaults | Parent survives; failure reported as itself | Existing, tested (`slow`) |
| Kill switch store unreadable | **Halt** | Rule 3 |

### Human oversight

The kill switch is the boundary. It is operable without a deploy, has its own
RBAC, and is the one control whose *unreadability* means stop. No automation may
re-enable trading after a kill-switch halt.

### KPIs

Uptime by component; correctness-under-fault (proportion of injected faults where
output was correct or refused, never wrong); mean time to detect; mean time to
recover; chaos-experiment coverage of the failure table above; and the count of
gates lacking injection evidence (target 0).

### Why this design

Because the ranking is the whole design. Once *correct-and-down beats wrong-and-up*
is accepted, every ambiguous case resolves the same way: refuse. That is why the
staleness gate, the drift gate, the invariant enforcer and the kill switch all
fail closed, and why an unreadable control counts as a failed one.

---

## Chapter 9 — Disaster Recovery and Business Continuity

**Status: PARTIAL.** The *means* exist — VPS bootstrap and reset scripts, Compose
fallback, database migrations, committed model artefacts. The *plan* and the
*rehearsal* do not.

### Purpose

Disaster recovery is a technical capability; business continuity is a decision
about what the business does while recovery happens. They are different documents
in most institutions and different sections here.

The distinction matters for a trading platform because the continuity answer is
often **flat and halted**, not "keep trading from the backup site". Recovering the
ability to trade with degraded data is not obviously better than not trading.

### Architecture: recovery tiers

| Tier | Scenario | Target RTO | Target RPO | Mechanism | Status |
|---|---|---|---|---|---|
| 1 | Pod/node loss | < 1 min | 0 | k8s reschedule | AVAILABLE |
| 2 | Cluster loss | < 1 hr | < 5 min | Compose on VPS | Scripts AVAILABLE, **unrehearsed** |
| 3 | Region/provider loss | < 4 hr | < 15 min | Second provider | **NEW** |
| 4 | Data corruption | < 4 hr | to last good backup | Verified restore from snapshot | **PARTIAL — Phase R1.** Backup and restore are now tested both ways; PITR is not built, and RPO is still 24 h by schedule, not by decision |
| 5 | Total loss | < 24 hr | < 1 hr | Rebuild from git + backups | PARTIAL |

**Tier 4 was the most serious gap in this document, and is now half closed.**
Corruption is the failure that redundancy makes *worse*, because a corrupt write
replicates faithfully to every replica.

**Phase R1 closed the tested-restore half.** `database/restore.py` verifies an
artefact before restoring it and refuses six distinct ways a backup arrives
worthless; the round trip is proven by executing it — SQLite in the fast suite,
and a real `pg_dump` restored into a real PostgreSQL 16.13 database with matching
checksums in `tests/integration/`. `docs/runbooks/database-restore.md` is the
3am procedure.

Building it found two live defects that a survey could not have:

* **A SQLite backup of a WAL database restored to nothing.**
  `database/connection.py` sets `journal_mode=WAL`, so committed rows sit in the
  `-wal` sidecar; the backup copied the main file alone. Reproduced: one
  committed row, and the restored copy had no such table. The scheduled job
  logged success every night. Backups written before 2026-09-08 are suspect and
  the runbook carries the sweep that finds them.
* **`pg_dump` was buffered entirely in memory** before a byte was written, so a
  production-sized database would have exhausted the worker — during an incident.

**What remains NEW:** point-in-time recovery, and an RPO that is a decision
rather than a side effect of a 24-hour schedule. Both are named in
`docs/ai/MASTER_OUTSTANDING.md` §A1 as the owner's call.

### The continuity decision

Before recovery begins, one question is answered by a human: **halt or continue?**
The default is halt. Continuing requires an affirmative decision by an authorised
human with a stated reason, recorded. This inverts the usual instinct, and it is
correct here: an unattended platform trading through a disaster it does not
understand is the scenario with unbounded downside.

### Failure modes of the recovery itself

* **The backup that was never restored.** A backup is a hypothesis until a restore
  proves it. Rule 1 applies: an unrestored backup is not a backup. **Closed in
  Phase R1** — `celery_app.database_backup` now verifies what it wrote and
  reports `unverified` rather than `ok` when it cannot, because the status an
  operator reads must never be more confident than the evidence behind it.
* **The runbook that assumes a working console.** Recovery procedures must not
  depend on the system being recovered.
* **The credential nobody can reach.** Break-glass credentials must be retrievable
  without the platform's own identity system.

### Human oversight

Recovery is human-led throughout. The AI may assemble evidence, correlate the
timeline and draft the sequence — Group 1 §50's Emergency Intelligence Mode — but
executes nothing at Tier 2 or above.

### KPIs

| KPI | Target |
|---|---|
| Days since last successful *restore* (not backup) | ≤ 90 |
| Days since last Tier-2 failover rehearsal | ≤ 90 |
| Runbook steps failing on rehearsal | 0 |
| Break-glass credential retrieval time | < 15 min, rehearsed |
| RTO/RPO achieved vs. target, per tier | measured, not estimated |

### Priority

**Tier 4 backup-and-restore was the highest-priority NEW item in this entire
document** — the only gap whose worst case is unrecoverable. Phase R1 delivered
the tested restore; **point-in-time recovery and a decided RPO remain**, and they
inherit the priority.

### Why this design

Because every other chapter here improves a system that exists, and this one is
about the case where it does not. The asymmetry justifies the priority: a slow
pipeline costs hours, an unenforced boundary costs a bad merge, and an untested
backup costs everything. **The default of halt-not-continue follows the same
asymmetry** — the downside of pausing is bounded and the downside of trading
blind is not.

---

# PART IV — SECURITY, IDENTITY AND SECRETS

## Chapter 10 — Identity, Access, Permissions and Human Approval

**Status: PARTIAL.** `auth/` exists with a dedicated `auth-coverage` CI gate;
`ai/policy/roles.py` defines VIEW / PROPOSE / APPROVE / EXECUTE with a superadmin
capability requiring 2FA; a two-human approval flow exists for AI-proposed
changes; operator scoping on AI jobs was hardened after a P0.

### Purpose

Access control answers *who may do what*. On this platform it must also answer
*what may an automated actor do* — a question ordinary IAM does not ask, and the
one that decides whether an AI platform is governable.

### Architecture: two intersecting models

**Model A — human roles.** Standard RBAC over the API surface, with superadmin
capabilities server-enforced (there is a dedicated test asserting this, because a
client-enforced capability is decoration).

**Model B — actor authority tiers.** Group 1 §59 specifies six tiers. The platform
implements four capabilities. The mapping, stated honestly:

| Group 1 tier | Meaning | Platform equivalent | Gap |
|---|---|---|---|
| Tier 0 | Observation only | — | **Missing.** No authority level that can read but not even recommend |
| Tier 1 | Analysis | ~ VIEW | Approximate |
| Tier 2 | Recommendation | PROPOSE | Present |
| Tier 3 | Plan generation | — | **Missing.** A plan is more than a recommendation and less than an execution |
| Tier 4 | Controlled execution | EXECUTE | Present |
| Tier 5 | Restricted high-impact | EXECUTE + superadmin + 2FA | Present |

Tier 0 and Tier 3 are the real gaps, and they are not cosmetic. Tier 0 is what a
continuously-observing intelligence should hold by default — Group 1's whole
premise is a system that watches without acting, and there is currently no
authority level that expresses "may see, may not suggest". Tier 3 is what an
autonomous planner needs so that producing a plan is not conflated with being
allowed to run it.

### Human approval

Two humans approve any AI-proposed change to a vault-protected path. This is
already implemented and is the single most important governance control in the
platform. Its properties worth preserving: approval is **per-change**, not a
standing grant; the approver cannot be the proposer; and the vault path list is
itself vault-protected.

### Security and governance requirements

* Every authority decision is logged with actor, tier, resource and outcome.
* Operator scoping is **keyed, not filtered** — the precedent is the P0 in the AI
  job runner where a filtered query leaked another operator's jobs. Scoping applied
  after retrieval is a leak waiting for a bug.
* No capability is granted to an automated actor that a human has not explicitly
  configured. Defaults are Tier 0.

### KPIs

Authority-decision audit coverage (100%), unscoped queries reaching production
(0), approvals where proposer equals approver (0, structurally impossible), and
mean age of privileged-access review.

### Why this design

Because the two models answer different questions and merging them loses one. Human
RBAC asks "is this person allowed?"; authority tiers ask "how far along the
observe→act spectrum is this actor permitted to travel?" **An AI platform without
the second model can only express trust as all-or-nothing**, and all-or-nothing is
how autonomous systems acquire permissions nobody decided to give them.

---

## Chapter 11 — Secrets and Credential Management

**Status: AVAILABLE.** `detect-secrets` runs in pre-commit and CI, a
`secrets` job runs in `security-scan.yml`, a "Block plaintext credentials" hook
runs locally, `ai/guardrails/` scans model output for secrets, and the AI gateway
holds API keys behind a boundary agents cannot cross.

### Purpose

A secret has one property: it must never appear where it can be read by something
that should not read it. That includes source control, logs, model prompts, model
*outputs*, error messages, and the context of an AI agent.

The last two are the ones ordinary secret management misses, and the platform
already handles both.

### Architecture: four boundaries

| Boundary | Threat | Control | Status |
|---|---|---|---|
| Source control | Committed credential | `detect-secrets`, plaintext-credential hook | AVAILABLE |
| Runtime config | Credential in a tracked file | Placeholders only in `prop_firm_mode.json`, `.env.example` | AVAILABLE |
| Agent context | Model receives a key | Agents request *capabilities*, never values | AVAILABLE |
| Model output | Model emits a key it inferred or was shown | Output secret scanner in `ai/guardrails/` | AVAILABLE |

The third boundary is the architecturally interesting one and is worth stating as
a principle, because it generalises: **an agent asks the gateway to make a call; it
never receives the credential that makes the call possible.** The blast radius of a
prompt injection is therefore bounded by what the gateway will do, not by what the
key can do.

### Gaps

* **No rotation policy.** Nothing forces or tracks credential age.
* **No break-glass path** distinct from ordinary access (see Ch 9).
* **No provenance record** of which credential was used for which spend, which
  Chapter 18's cost attribution would need.

### Failure modes

| Failure | Required behaviour |
|---|---|
| Secret detected in a commit | Block, and treat the secret as compromised — detection is not prevention |
| Secret store unreachable | Fail closed; do not fall back to an environment variable |
| Model output contains a secret pattern | Redact before the output leaves the process, and raise |

### KPIs

Secrets reaching source control (0), mean credential age vs. policy, output-scanner
true/false positive rates, and time from suspected compromise to full rotation.

### Why this design

Because the agent-context boundary is the one that makes an AI platform
*specifically* different from an ordinary one. Every other control here is standard
practice. **That one exists because a language model will repeat anything it is
shown**, and the only reliable defence is not showing it.

---

## Chapter 12 — DevSecOps, Static Analysis and Supply Chain

**Status: AVAILABLE and comprehensive.** Bandit, CodeQL, Fortify, Codacy, Trivy,
Safety, a dependency-scan job, and a lockfile workflow.

### Purpose

Security that runs at review time and not at release time is advice. This chapter
is about the controls that block.

### Architecture

| Stage | Tool | Catches |
|---|---|---|
| Pre-commit | bandit, detect-secrets | Insecure patterns, credentials, before they leave the machine |
| PR | CodeQL, Fortify, Codacy | Semantic vulnerabilities |
| PR | Safety, dependency-scan | Known-vulnerable dependencies |
| PR | Trivy | Container and OS-level CVEs |
| Release | lockfile workflow | Dependency drift between declared and installed |

### Gaps

* **No SBOM.** Nothing produces a bill of materials, so "are we affected by CVE-X"
  is answered by searching rather than by querying.
* **No dependency-provenance check.** Nothing verifies that a package came from
  where it claims.
* **No policy on transitive additions.** A minor bump can add a new transitive
  dependency with no review.

### The supply-chain decision rule

New dependencies on a money-moving platform are governance events, not routine
choices. The rule adopted here, from a decision already taken in Group 1's
delivery: **a dependency that cannot be exercised in the environment adding it
must not be added there.** A model runtime added and never once executed is code
shipped on faith, and faith is not a control.

### KPIs

Critical CVEs open beyond SLA (0), mean time from advisory to patched, new
dependencies added without review (0), and SBOM coverage.

### Why this design

Because the tooling is already excellent and the gap is *inventory*. Six scanners
tell you what is wrong today; an SBOM tells you what you have, which is the
question asked at 3am when an advisory lands.

---

## Chapter 13 — Data Egress and the Sovereignty Boundary

**Status: NEW.** This chapter has no implementation and is the infrastructure
prerequisite for Group 1 §23 and §24.

### Purpose

Some information must never reach a third party — not because of a regulation, but
because it is the platform's strategy, its positions, its proprietary architecture
or its owner's confidential material. Today, whether such content reaches an
external model depends on whether a call site remembered to avoid it. That is a
convention, not a boundary.

### Architecture: classify, then route

```
content ──► classifier ──► class
                             │
     ┌───────────────────────┼───────────────────────┐
     ▼                       ▼                       ▼
  PUBLIC                 INTERNAL                SOVEREIGN
     │                       │                       │
 any provider        approved providers      local models only
                       + logged                + network-enforced
```

Three components:

1. **A classifier** with an explicit default of `INTERNAL` — never `PUBLIC`. An
   unclassified payload is not public; it is unknown, and Rule 2 says unknown is
   not the permissive value.
2. **A routing gate** in the AI gateway that refuses to send `SOVEREIGN` content to
   any external provider, and says which classification refused it.
3. **A network policy** that makes the same guarantee at a layer code cannot
   bypass, because a code-level check is defeated by the next new call site.

### Security and governance

The classifier's rules are vault-protected. An AI may propose a reclassification;
it may never apply one. Reclassifying content *downward* (SOVEREIGN → INTERNAL)
requires two humans, like any vault change.

### Failure modes

| Failure | Required behaviour |
|---|---|
| Classifier unavailable | Treat everything as SOVEREIGN — fail closed, refuse external calls |
| Content class ambiguous | Take the more restrictive class |
| Local model unavailable for SOVEREIGN work | Refuse and report. **Never fall back to an external provider** |

The last row is the entire point of the chapter. A fallback that silently sends
sovereign content to a third party during an outage is worse than the outage.

### KPIs

Sovereign payloads reaching an external provider (0, and the metric must be
*measurable* — if it cannot be measured it is not zero, it is unknown), classifier
coverage of outbound payloads (100%), and refusals by class.

### Why this design

Because a boundary enforced in one place is enforced until someone adds a second
call site. Two independent layers — code and network — means a mistake in either
is caught by the other, and the network layer holds even when the code is wrong.

---
# PART V — OBSERVABILITY AND OPERATIONS

## Chapter 14 — Observability: Logging, Metrics and Tracing

**Status: AVAILABLE.** `monitoring/` (1,093 LOC), `tracing/` (1,017 LOC),
`prometheus.yml`, `prometheus_alerts.yml`, a `grafana/` directory, and
`ai/telemetry/` with the measured-versus-absent discipline already enforced.

### Purpose and why it exists

Observability is the difference between knowing that something is wrong and knowing
what is wrong. The three pillars answer different questions and are not
substitutes: metrics say *something changed*, traces say *where*, logs say *what
exactly*.

### The rule this platform already got right

`ai/telemetry/` distinguishes a **measured zero** from an **unmeasured value**, and
carries the reason in the reading itself. This is Rule 2 and it is worth restating
why it matters operationally: a dashboard showing `0 errors` when the error
collector is down is not merely wrong, it is *reassuring* — the single worst
property a monitoring system can have.

### Architecture

| Pillar | Implementation | Status |
|---|---|---|
| Metrics | Prometheus, with alert rules | AVAILABLE |
| Dashboards | Grafana | AVAILABLE |
| Tracing | `tracing/` package | AVAILABLE |
| Logs | Structured logging | AVAILABLE |
| AI-specific telemetry | `ai/telemetry/` — host, agents, security, neural, reading | AVAILABLE |
| **Correlation across pillars** | one identifier joining a metric spike to its traces to its logs | **PARTIAL** |

### The gap that matters

The three pillars exist and are **not reliably joined**. A latency spike in Grafana
does not carry a link to the traces in that window, which do not carry the change
record from Chapter 6. Every investigation therefore starts by manually
reconstructing a timeline that the system already has the pieces of.

That reconstruction is exactly what Group 1's §16 operational correlation engine
automates — and it cannot be built until the pieces share a join key. **This
chapter is the prerequisite for that one.**

### Requirements

* One trace/correlation identifier propagated across HTTP, the job runner, the
  agent bus, and out to the broker adapters.
* Every log line in a request path carries it.
* Every metric that can be attributed to a request carries it as an exemplar.
* Change records (Ch 6) carry the deploy identifier that telemetry can be joined
  against.

### Failure modes

| Failure | Required behaviour |
|---|---|
| Metrics collector down | Dashboards show **unmeasured**, never zero |
| Trace sampling drops the interesting request | Sample errors and slow requests at 100%, not uniformly |
| Log volume overwhelms storage | Shed by level with the shedding **recorded**, never silently |

### KPIs

Pillar-join rate (proportion of incidents where metric → trace → log was
traversable without manual reconstruction; target > 90%), unmeasured-metric count
surfaced rather than hidden, and mean time to first correct hypothesis.

### Why this design

Because the platform's observability problem is not coverage — it is **joinability**.
Adding a fourth pillar would help less than making the existing three answer the
same question about the same request.

---

## Chapter 15 — Alerting, Incident Management and Root-Cause Analysis

**Status: PARTIAL.** Prometheus alert rules exist; `ai/notify/` (953 LOC)
implements severity, quiet hours, escalation, deduplication and an explanation of
why an interruption happened. Incident *process* — declaration, roles, timeline,
postmortem — is not evidenced.

### Purpose

An alert exists to cause a human action. An alert that does not is worse than
none, because it trains people to ignore the channel it arrives on.

### Architecture

| Stage | Mechanism | Status |
|---|---|---|
| Detection | Prometheus rules, invariant enforcement, watchers | AVAILABLE |
| Routing | `ai/notify/` — severity, quiet hours, escalation | AVAILABLE |
| Deduplication | `ai/notify/` router | AVAILABLE |
| Explanation | "why you were interrupted" is part of the payload | AVAILABLE |
| **Declaration** | A named incident with a state and an owner | **NEW** |
| **Timeline assembly** | Automatic, from telemetry + change records | **NEW** |
| **Postmortem** | Blameless, with linked actions | **NEW** |

### The alerting discipline

Three rules, because alert fatigue is the failure mode that disables the whole
chapter:

1. **Every alert names the action.** An alert with no runbook link is a
   notification, and notifications go to a different channel.
2. **Quiet hours are honoured except by severity.** Already implemented; the
   design is correct — the escalation path, not the sender, decides what wakes
   someone.
3. **A page that fires and is routinely ignored is a defect** and is reviewed as
   one. The metric is acknowledgement rate, not fire rate.

### Incident roles

Even for a single-operator platform, the roles are named because they are
*functions*, not people, and one person may hold several: **incident commander**
(decides), **investigator** (finds), **scribe** (records), **communicator**
(informs). The AI may assist every role and holds none.

### Interaction with Group 1

Group 1's §50 Emergency Intelligence Mode changes AI behaviour during an incident —
prioritising rapid understanding, containment and evidence preservation over
efficiency. That mode is triggered by the *declaration* specified here. Without
declaration, the mode has no trigger.

### KPIs

| KPI | Target |
|---|---|
| Alert acknowledgement rate | > 95% |
| Alerts with no runbook link | 0 |
| Mean time to declare | < 5 min from first signal |
| Incidents with a completed postmortem | 100% of Sev 1–2 |
| Postmortem actions completed within SLA | > 80% |
| Repeat incidents with the same root cause | trending to 0 |

### Why this design

Because the platform has built the hard half — routing, severity, deduplication,
and the unusual and admirable decision to *explain* an interruption — and skipped
the cheap half, which is declaring that an incident is happening. Declaration is
what turns a stream of alerts into a thing with a beginning, an owner and an end.

---

## Chapter 16 — AIOps: Operational Intelligence

**Status: PARTIAL, and the boundary with Group 1 is the open question this
document was asked to resolve.**

### The classification decision

Group 1's §16 (operational correlation), §20 (forecast intelligence), §21
(technical-debt forecasting) and §22 (standards guardian) are *intelligence*
applied to *operations*. The Group 1 rule places them in Group 1 by function; their
subject matter is Group 2's.

**Resolution:** they stay in **Group 1**, and Group 2 owns their inputs and their
enforcement points. The reasoning is the failure mode each choice invites. If
Group 2 owned them, four cognitive engines would be specified far from the
cognition core they share machinery with, and would drift into a second, weaker
reasoning stack. If Group 1 owned their inputs too, it would specify telemetry
schemas and change records that operations must actually produce — and Group 1
cannot enforce anything in the pipeline.

So the contract is explicit:

| Group 2 provides | Group 1 consumes |
|---|---|
| Joined telemetry with a correlation key (Ch 14) | §16 operational correlation |
| Change records with expected effect (Ch 6) | §16, §21 |
| Package register with modification history (Ch 1) | §21 technical-debt forecasting |
| Capacity measurements with headroom (Ch 7) | §20 forecast intelligence |
| Standards enforcement points (Ch 2) | §22 standards guardian |
| Incident declarations and timelines (Ch 15) | §50 emergency mode, §33 failure memory |

This table is the interface between the two documents and is the thing that
prevents both duplication and orphaned requirements.

### What Group 2 keeps

Deterministic operational automation that requires no reasoning: auto-restart on
liveness failure, auto-scale on a threshold, auto-rollback on an error-rate breach,
scheduled maintenance. These are **rules**, not intelligence, and putting them in
Group 1 would dress a threshold up as cognition.

### Why this design

Because the distinction that matters is not "is it about operations" but **"does it
require a hypothesis?"** A threshold does not. A correlation between a deploy and a
latency change does. That line is stable, explainable, and puts each engine where
its machinery already lives.

---

## Chapter 17 — Performance Engineering

**Status: PARTIAL.** `load-test.yml`, `k6/` and `locust/` exist. Continuous
profiling and a latency budget do not.

### Purpose

On a trading platform, latency is not a comfort metric — it is a correctness input.
A signal acted on late is a different signal.

### Architecture

| Layer | Budget | Measured | Status |
|---|---|---|---|
| Tick ingest → decision | must be stated | yes | PARTIAL |
| Decision → order sent | must be stated | yes | PARTIAL |
| FIX round trip | breaker already trips on breach | yes | AVAILABLE |
| API p99 | must be stated | yes | PARTIAL |
| AI gateway call | recorded per call (`ai/gateway/audit.py`) | yes | AVAILABLE |
| Frontend frame | frame budget with burst-and-rest | yes | AVAILABLE |

The gap is stated budgets. Latency is measured throughout and compared against a
threshold in only one place. A measurement with no budget is a number, not a
control.

### Requirements

* An explicit budget per stage, with the trading path budgets treated as
  invariants rather than targets.
* Load tests run against those budgets in CI, failing when a budget regresses.
* Continuous profiling on the hot path, sampled, so a regression is attributable to
  a change rather than to a quarter.

### KPIs

Budget adherence per stage, regression detection lead time, and profile coverage of
the hot path.

### Why this design

Because the platform already measures nearly everything and enforces almost none of
it. **Adding budgets is cheaper than adding measurement**, and it converts an
existing dashboard into a gate.

---

## Chapter 18 — Cost, Compute Optimisation and Resource Economics

**Status: AVAILABLE for AI spend, NEW for infrastructure.**
`ai/gateway/budget.py` and `budget_store.py` enforce a shared ceiling per operator,
backed by Redis; `ai/jobs/lineage.py` bounds delegation trees three ways.

### Purpose

Two cost surfaces behave differently. **AI spend** is variable, fast-moving and
adversarial to bound — a runaway agent tree can spend a month's budget in an hour.
**Infrastructure spend** is slow and structural.

The platform has solved the dangerous one.

### What exists, and why it is the right shape

| Control | Property |
|---|---|
| Budget ceiling per operator | Spend is attributable; one operator cannot consume another's share |
| Redis-backed | Survives restart; not per-process |
| Delegation bound | Depth, fan-out **and** total descendants — three separate failure modes |
| Grant across process boundary | A subtree cannot exceed what it was granted |
| Circuit breakers | A failing vendor stops costing money |
| Refusal is local and recorded | A refused child does not fail the tree, and is never silent |

### Gaps

* **No infrastructure cost attribution** — spend per service, per environment.
* **No cost forecast** (belongs to Group 1 §20; the *measurement* belongs here).
* **No idle-resource reclamation.**

### The economic principle

Group 1 §61 states it and this chapter enforces it: **never confuse activity with
intelligence.** More agents and more model calls are costs until proven otherwise.
Every intelligence subsystem must therefore report cost alongside output, and any
subsystem whose cost is not attributable is treated as unbounded.

### KPIs

Spend per operator against ceiling, cost per resolved task (the only ratio that
tells you whether intelligence is paying for itself), refusals by bound, and
infrastructure cost per environment.

### Why this design

Because on this platform the cost control *is* a safety control. An unbounded
delegation tree is not merely expensive — it is an unbounded number of actions
taken by a system nobody is watching. Bounding spend bounds behaviour.

---

# PART VI — QUALITY, VERIFICATION AND GOVERNANCE

## Chapter 19 — Testing Infrastructure and Continuous Verification

**Status: AVAILABLE and exceptional.** 20,985 tests in the fast suite alone, plus
2,594 frontend tests, per-module coverage gates, auth-coverage gates, model-accuracy
checks, docker smoke tests, dead-file detection and marker-based selection
(`unit`, `integration`, `e2e`, `slow`, `requires_redis`, `asyncio`).

### Purpose

Testing infrastructure answers whether the platform still does what it did. On a
money-moving system it also answers whether the *refusals* still refuse, which is a
different and harder question.

### The three disciplines

Beyond the mechanics, three disciplines carry the weight, and all three are about
proving a test can fail:

1. **Every fix ships with a test confirmed failing on the pre-fix tree.** Stash the
   fix, run, watch it fail, restore. A test that has never failed proves nothing.
2. **Defect injection for every control.** Rule 1. Break the thing deliberately,
   confirm by inspection that the break applied, and watch the control fire.
3. **Confirm the injection applied.** This sounds pedantic and is not: an injection
   once failed to apply because of a whitespace mismatch after formatting, and the
   conclusion "this code does not matter" was nearly drawn from a test run that had
   tested the unmodified file.

### The catalogue of tests that could not fail

Kept here as a checklist, because these are the shapes to look for. Each is real,
each was found by injection, none by reading:

| Shape | Real instance |
|---|---|
| Assertion satisfied by a *second* code path | A consent check passed while consent was granted to everybody, because the next branch returned the same state |
| Precondition destroyed before the assertion | Pointer tests fired an event before asserting the initial state, so the initial state was never tested |
| A race the test cannot reach | A concurrency test passed with the lock removed — too few bytecodes between read and write for threads to interleave |
| Shared state leaking between cases | A "refuses to draw" test passed while looking at the previous test's output |
| A tool that examined nothing | A sweep reported 154 findings; ripgrep had been reading stdin, not the repository |

The generalisation: **an assertion that something other than the code under test can
also satisfy.** Every control review asks that question explicitly.

### Gaps

* `e2e` and `slow` never run in CI, so process isolation and end-to-end paths are
  specified and unexercised. A nightly job should run them.
* No mutation testing, which is Rule 1 automated.

### KPIs

Coverage per module against floor; **proportion of controls with injection
evidence (target 100%)**; mutation score once introduced; flake rate; and the count
of fixes shipped without a confirmed-failing test (target 0).

### Why this design

Because coverage measures which lines ran, and none of the five failures above
would have moved a coverage number. **Injection measures whether the test is
connected to the thing it names**, and that is the only property that matters in a
control.

---

## Chapter 20 — The Invariant System

**Status: AVAILABLE and substantial.** 5,582 lines across 37 files in
`invariants/`, with `verify_*` and `catastrophic_*` predicates, `enforce_*` call
sites, an `HOPEFX_INVARIANT_MODE` switch, fail-closed behaviour, and CI coverage
enforcement.

### Purpose

An invariant is a statement that must be true at a point in the code, regardless of
path. On this platform they are the last line before money moves.

### Architecture

Predicates (`verify_*`, `catastrophic_*`) are pure and testable in isolation.
Enforcement points (`enforce_*`) are where they run. **The two are separate because
the historical defect is not a wrong predicate — it is a correct predicate with no
call site.**

That is exactly the F176 defect this platform already recorded: a coverage script
certified components by counting hand-typed `True` literals. The lesson generalises
into Rule 4 and into this chapter's central requirement: **invariant coverage is
measured by call sites reached at runtime, never by declarations.**

### Governance

* Never weaken an invariant without explicit instruction.
* `HOPEFX_INVARIANT_MODE` may make enforcement stricter, never silently weaker.
* An invariant that cannot evaluate **refuses** — Rule 3.
* Every invariant carries injection evidence — Rule 1.

### KPIs

Invariant coverage by *reached call site*; refusals by invariant (a healthy nonzero
number — an invariant that never fires may be unreachable); and invariants without
injection evidence (0).

### Why this design

Because this platform has already been burned by a certification that counted
declarations. **The only trustworthy coverage number for a control is one derived
from execution**, and this chapter refuses to accept any other.

---

## Chapter 21 — API Governance, Integration Standards and External Providers

**Status: PARTIAL.** `api/server.py` aggregates routers, a route catalogue is
derived and exposed, `ai/gateway/` normalises AI providers behind one interface
with per-vendor breakers, and broker adapters are abstracted. Versioning and a
deprecation policy are missing.

### Purpose

Every integration is a dependency on someone else's decisions. Governance here is
about making those decisions absorbable rather than breaking.

### Architecture

| Surface | Standard | Status |
|---|---|---|
| Internal HTTP | FastAPI routers aggregated in `api/server.py` | AVAILABLE |
| Route catalogue | Derived, not hand-maintained; bounded when shown to a model | AVAILABLE |
| AI providers | Gateway normalises to one internal interface | AVAILABLE |
| Brokers | Adapter per broker; FIX bridge isolated | AVAILABLE |
| **Versioning** | No stated policy | **NEW** |
| **Deprecation** | No stated policy | **NEW** |

### One existing decision worth preserving

The route catalogue given to the planner is **bounded to 12 rows and separate from
the permission list**. Two properties, both hard-won: a truncated prefix of 2,234
routes would hide whole areas silently, and *seeing* a route is not permission to
call it — the allowlist refuses before anything reaches the bus. The search that
selects those 12 drops stopwords, because scoring every word of three letters or
more once matched 850 of 2,234 routes.

### Requirements for the gaps

* Explicit API versioning with a stated compatibility window.
* Deprecation: announce, warn in responses, then remove — never remove first.
* Provider changes absorbed at the gateway, never leaked into callers.

### KPIs

Breaking changes shipped without a deprecation period (0), provider outages causing
platform outages (0 — breakers should hold), and adapter coverage of provider
capabilities.

### Why this design

Because the gateway pattern has already proved itself: a provider failing is
absorbed rather than propagated. Extending the same discipline to versioning means
*our* changes are as absorbable to our callers as *their* changes are to us.

---

## Chapter 22 — Dependency Management and Technical Debt

**Status: PARTIAL.** Dependency scanning, a lockfile workflow, Safety and Trivy
exist. Debt measurement does not.

### Purpose

Dependencies and debt are the same phenomenon at different speeds: both are
obligations incurred earlier and paid later.

### Architecture

| Concern | Mechanism | Status |
|---|---|---|
| Known vulnerabilities | Safety, Trivy, dependency-scan | AVAILABLE |
| Version drift | lockfile workflow | AVAILABLE |
| Python version alignment | Dockerfile 3.12; CI 3.11 + 3.12; retrain workflows pinned 3.12 | AVAILABLE |
| **Debt measurement** | complexity, age, coverage, bug frequency, churn, incident history per package | **NEW** |
| **Debt budget** | an agreed ceiling, with paydown scheduled | **NEW** |

The debt inputs are the ones Group 1 §21 forecasts from. Again the pattern: Group 2
measures, Group 1 predicts.

### KPIs

Debt score per package trend, dependency age distribution, paydown as a proportion
of engineering time, and the count of packages above the debt ceiling.

### Why this design

Because measuring debt without a budget produces a number nobody acts on. The
budget is what converts a metric into a decision, and it is the part that requires
a human to set.

---

## Chapter 23 — Compliance, Auditability and Operational Risk

**Status: AVAILABLE.** `compliance/` (2,518 LOC), `audit/`, `forensics/`,
`evidence/`, `transparency/` (855 LOC), `explainability/` (763 LOC) and the AI
gateway's persisted audit trail.

### Purpose

Auditability answers "what happened and who decided it" after the fact, when the
people involved are unavailable and the logs are all that remain.

### What must be reconstructable

| Question | Source | Status |
|---|---|---|
| What trades were made and why | Trade thesis, explainability, audit | AVAILABLE |
| Which model produced which output, at what cost | Gateway audit trail | AVAILABLE |
| Who approved which change | PR + approval flow | AVAILABLE |
| What the system refused, and why | Invariant and guardrail refusals | AVAILABLE |
| What was deployed when | Change records (Ch 6) | PARTIAL |
| Which authority tier permitted an action | Authority log (Ch 10) | PARTIAL |

### The property that makes an audit trail trustworthy

**Refusals are recorded as prominently as actions.** A log containing only what
happened cannot distinguish a system that was never asked from one that refused —
and on a governed AI platform, the refusals are the evidence that governance
worked.

### KPIs

Reconstruction completeness on a sampled incident, audit gaps found in review (0),
and retention compliance.

### Why this design

Because the platform already records unusually well, and the two partial rows are
both about *decisions* rather than *events*. Events are easy to log; decisions have
to be designed to be loggable, which is why Chapters 6 and 10 specify their records
explicitly.

---
## Chapter 24 — Plugin, Extension and Workflow Automation Governance

**Status: PARTIAL.** `nocode/`, `events/` and the agent bus provide extension
points; `ai/departments/` registers capability providers with a versioned
permissions manifest. What is missing is a governance contract for third-party or
operator-authored extensions.

### Purpose

Every extension point is a place where code the platform did not write runs inside
the platform. The governance question is not whether to have them — they are how a
platform stays useful — but what an extension is *permitted* to be.

### Architecture: the extension contract

Any extension declares, before it runs:

| Field | Why it is required |
|---|---|
| Identity and owner | An extension with no owner cannot be revoked |
| Capabilities requested | Least privilege; denied by default |
| Data classes touched | Feeds Chapter 13's egress boundary |
| Authority tier | May it observe, recommend, plan, or execute? |
| Resource budget | Extensions consume the same bounded pools |
| Failure behaviour | What the platform does when it faults |

`ai/departments/` already implements the shape of this — a registered provider with
a declared permission set and a version string on the manifest — and is the model
the general contract should follow.

### Governance requirements

* **Denied by default.** An extension receives nothing it did not declare.
* **No extension reaches Tier 4 or 5** without explicit human configuration.
* An extension fault is isolated: it degrades its own function, never the platform.
* Extension activity appears in the same audit trail as everything else.

### KPIs

Extensions running with undeclared capabilities (0), extension-caused incidents (0),
and mean time to revoke.

### Why this design

Because the departments registry already demonstrates that a declared, versioned
permission manifest is workable here. Generalising a proven internal pattern is
lower-risk than inventing a plugin framework, and it keeps one audit surface rather
than two.

---

## Chapter 25 — Data Governance for Platform Operations

**Status: PARTIAL.** `data_layer/`, `data/`, `market_data/`, `database/`,
`alembic/` migrations and a data-quality discipline exist. Retention, lineage and
classification do not.

**Scope note:** this chapter covers data governance *only where it affects platform
operations*. Trading data semantics belong to the trading architecture; AI memory
governance belongs to Group 1 §16 and §31.

### What is in scope here

| Concern | Requirement | Status |
|---|---|---|
| Schema change | Migrations replay deterministically; forward-only in production | AVAILABLE (`alembic/`) |
| Retention | Stated per data class, enforced, and auditable | **NEW** |
| Classification | Feeds Chapter 13's egress boundary | **NEW** |
| Lineage | Which source produced which stored value | PARTIAL |
| Quality gates | Freshness and validity at ingest | AVAILABLE |
| Backup and restore | See Chapter 9 — highest priority gap | **NEW** |

### The undocumented boundary

`data/` (6,259 LOC, 20 production importers, live streaming and serving) and
`data_layer/` (19,610 LOC, 86 importers, market-data access) have **no documented
boundary**, and this is recorded rather than resolved. The current holding position
— extend the package a module already lives in, and state which you chose in the PR
— is honest but is not a design.

Resolving it is a Chapter 1 task (it is an architecture boundary), and it is listed
here because data work is where the ambiguity is felt.

### Why this design

Because the alternative is a data-governance chapter that quietly re-specifies the
trading data model, which belongs elsewhere. **Scoping a chapter narrowly is what
keeps the three groups from duplicating each other** — the failure Group 3 exists
to prevent.

---

# PART VII — EXPERIENCE AND MEASUREMENT

## Chapter 26 — Operator and Administrator Experience

**Status: PARTIAL.** The operator surface is strong — Group 0 delivered 233
capability rows covering presence, workspace, accessibility, voice and spatial
reference. The *administrator* surface is thin.

### Purpose

Two different people use this platform. The **operator** trades and asks the AI
questions. The **administrator** configures, approves, investigates and recovers.
Group 0 built for the first. This chapter is about the second.

### What an administrator needs and does not have

| Need | Status |
|---|---|
| See every authority grant and revoke one | **NEW** |
| See pending approvals and act on them | PARTIAL |
| See spend by operator against ceilings | PARTIAL — data exists, no surface |
| Operate the kill switch and see its state | AVAILABLE (ConfigMap + RBAC), no UI |
| See what the AI refused, and why | **NEW** — the data exists in guardrails and invariants |
| See platform health with unmeasured values marked | PARTIAL |
| Declare an incident | **NEW** (Ch 15) |

The fifth row is the one worth building first. The platform records its refusals
carefully and shows them nowhere, which means the evidence that governance is
working is invisible to the person accountable for it.

### Requirements

* Administrator surfaces obey the same accessibility contract as operator surfaces —
  Group 0's rules are not relaxed for internal tools.
* Every destructive administrator action is confirmed, logged, and reversible or
  explicitly marked irreversible.
* Unmeasured values are shown as unmeasured. Rule 2 applies to the admin console
  most of all, because it is where "everything is fine" is read.

### KPIs

Time to complete common administrative tasks, approvals waiting beyond SLA, and
administrator actions taken outside the console (target: 0 — a console people route
around is not a console).

### Why this design

Because governance controls that cannot be *seen* are governance controls nobody
can be accountable for. The platform refuses well and reports its refusals to no
one.

---

## Chapter 27 — Platform Analytics, Health Measurement and the KPI Framework

**Status: PARTIAL.** Extensive measurement exists; a consolidated framework does
not.

### Purpose

This chapter does not invent metrics. It states which of the metrics scattered
across the previous twenty-six chapters constitute *the* view of platform health,
and how they are allowed to be reported.

### The three reporting rules

1. **Measured and unmeasured are different.** Rule 2, applied to every number on
   every dashboard.
2. **Told and measured are different.** The Group 0 registry reports these
   separately, and that discipline extends here: a KPI derived from a declaration
   is labelled as such and never averaged with a measured one.
3. **A KPI with no owner is deleted.** An unowned metric is decoration that costs
   collection.

### The consolidated framework

| Domain | Leading indicator | Lagging indicator |
|---|---|---|
| Delivery | Pipeline duration, gate-fail rate | Change failure rate, MTTR |
| Reliability | Injected-fault correctness | Uptime, incident count |
| Security | Time-to-patch, scan coverage | Incidents, secrets leaked (0) |
| Cost | Spend against ceiling, cost per resolved task | Monthly total, cost trend |
| Quality | Injection-evidence coverage, coverage per module | Escaped defects |
| Governance | Approvals within SLA, audit completeness | Findings in review |
| Architecture | Forbidden-edge violations, debt score | Incidents attributable to debt |

### The single health number, and why there isn't one

Group 1 §39 proposes a Platform Intelligence Index. This chapter deliberately
declines to produce a platform *health* index, for a stated reason: a composite
that averages a security gap against a slow pipeline hides the security gap. Health
is reported as a **vector with a worst-element rule** — the platform is as healthy
as its worst red domain, and the red domain is named.

### Why this design

Because the temptation with twenty-seven chapters of metrics is to roll them into
one number, and one number is exactly what stops anyone looking at the seven.

---

# PART VIII — ACCELERATION ARCHITECTURE

*Absorbed from Group 4 Volume VIII under Option B. This was the one area no
existing document owned. Both Group 4 sources enumerate it — v1 as fifteen
chapter titles, v2 as ten sections with a statement each — and both are preserved
in `GROUP4_VOLUME_INDEX.md`, checked by `scripts/group4_preservation.py`. The
substance is specified here, where the platform's other engineering concerns
live.*

*The complete v2 source confirmed this Part rather than changing it: all ten of
its sections map onto Chapters 28–34 below. It added one concrete thing — **NPU**
to the list of execution targets — which is folded into Chapter 29.*

## Chapter 28 — The Acceleration Layer, and what it is not

**Status: PARTIAL.** Substantial pieces exist and were never framed as one layer:
`ai/jobs/isolation.py` (process isolation with `RLIMIT_AS` and real termination),
`ai/jobs/runner.py` (bounded concurrency), `ai/jobs/priority.py` (ageing queue),
`ai/gateway/chain.py` (model fall-through), `ai/cache/` and `cache/` (270 LOC plus
a Redis pool), `ai/local_model.py` (604 LOC), 78 concurrency call sites.

### Purpose

Acceleration is about **spending the least compute that still produces a correct
answer in time**. On a trading platform "in time" is a correctness property, not a
comfort one: a signal acted on late is a different signal.

### The distinction that governs this whole Part

**Acceleration must never change an answer.** Faster is a property of the path,
not of the result. A cache that returns a stale price, a routing decision that
silently picks a weaker model, a degraded mode that skips a risk check — each of
those is a *wrong answer delivered quickly*, which Group 2 Chapter 8 already ranks
below a correct answer delivered late.

Every chapter below therefore carries the same test: **what does it do when it
cannot go faster safely?** The answer is always the slow correct path, never a
different result.

### Why this design

Because the failure mode of an acceleration layer is not slowness — it is
silence. A cache that never says it was stale, a router that never says it
downgraded, and a degradation policy that never says what it dropped will each
produce output indistinguishable from the full path. That is Rule 2 applied to
speed: **an unreported downgrade is an absent measurement, not a free win.**

## Chapter 29 — Hardware Abstraction and Future Accelerators

**Status: NEW.** No GPU or accelerator abstraction exists; the references found
are in `requirements-optional.txt`, `invariants/ml_pipeline.py` and `research/`.

Group 4 Chapter 7's rule governs: **architectural readiness, not speculation.** An
interface that admits a future backend is architecture; a claim about that backend
is marketing. The same test that let `viz.scientific_3d` ship without WebGL.

So: one execution-target interface (`cpu`, `gpu`, `npu`, `remote`,
`local-model`, `distributed`) — the set v2 names — a capability probe that
reports what is *actually* present, and — Rule 2 — a target that cannot be probed
is **absent, never assumed**. No chapter here claims GPU or NPU support until one
has run something.

## Chapter 30 — Workload Management and Dynamic Compute Routing

**Status: PARTIAL.** `ai/jobs/priority.py` ages priorities so the bottom tier is
not starved; `ai/gateway/chain.py` falls through providers. What is missing is a
route decision that considers *cost, latency and quality together* rather than
availability alone, and the **priority floor** Chapter 7 already named: risk and
execution work is never queued behind analysis, whatever the arrival order.

**Every routing decision is recorded with its reason.** A router that cannot say
why it chose a path cannot be debugged when it chooses badly.

## Chapter 31 — Parallel, Distributed and Isolated Execution

**Status: AVAILABLE for isolation, PARTIAL for the rest.** `ai/jobs/isolation.py`
gives real process isolation — `spawn` not `fork` because this process has
threads, memory capped by `RLIMIT_AS`, timeouts that actually terminate. Bounded
concurrency and the delegation bound (depth, fan-out, total descendants) are in
place. Distributed execution across hosts is NEW.

The delegation bound is the precedent for anything distributed: **three separate
limits, refusal recorded, and a grant that crosses the process boundary because a
ledger cannot.**

## Chapter 32 — Caching and Predictive Preloading

**Status: PARTIAL.** `ai/cache/store.py`, `cache/redis_*` and a market-data cache
exist without a stated coherence policy.

Three rules, each derived from a failure this platform can actually suffer:

1. **Every cached value carries its age**, and a consumer that cannot tolerate the
   age gets the slow path. A stale price is not a fast price.
2. **A cache miss is measured, not hidden.** Hit rate with no miss reason is a
   number that cannot be acted on.
3. **Preloading is speculative and must be free to be wrong.** It may never evict
   something a live request needs, and it never warms a value it would not have
   been allowed to compute.

## Chapter 33 — Adaptive Model Selection and Resource Intelligence

**Status: PARTIAL.** `ai/gateway/chain.py` has ordered chains and fall-through;
budget ceilings and circuit breakers bound spend. Selection by *measured
capability* needs Group 1 §7 (capability profiles) and §8 (rankings), which are
unbuilt — recorded as a dependency, not duplicated here.

**A downgrade is always visible.** If the router picks a cheaper model, the answer
says so. Silent downgrade is how a platform stops noticing it got worse.

## Chapter 34 — Performance Policy, Graceful Degradation and Capacity Intelligence

**Status: PARTIAL.** Article IX is already enforced in four places — kill switch,
budget ceiling, delegation bound, frame budget. What is missing is a single
**stated order of what degrades first**, and the capacity forecast Chapter 7
already lists as a gap (Redis currently reports `maxmemory` unlimited).

The degradation order is a governance artefact, not an engineering one: it says
what the platform is willing to lose. It is written by a human, reviewed like a
vault path, and the trading path is never in it.

### KPIs for this Part

| KPI | Target |
|---|---|
| Answers changed by an acceleration decision | **0** |
| Downgrades not reported to the caller | 0 |
| Cache values served without an age | 0 |
| Routing decisions with no recorded reason | 0 |
| Saturation events where the trading path was affected | 0 |
| Execution targets claimed but never probed | 0 |

---

# PART IX — EVOLUTION AND THE RANKED GAP LIST

## Chapter 35 — Evolution and Modernisation Strategy

**Status: NEW.**

### Purpose

Every chapter above describes a present state and a set of gaps. This one describes
how the platform is allowed to change, so that modernisation is a practice rather
than an occasional crisis.

### The principles

1. **Strangle, do not rewrite.** The platform already demonstrates this: `backtest/`
   is a re-export shim in front of canonical `backtesting/`. That pattern —
   canonical implementation, compatibility shim, gradual migration, shim removal —
   is the sanctioned route.
2. **A capability that cannot be measured cannot be retired**, because nobody can
   show it is unused. Retirement is a measurement problem before it is a deletion.
3. **Deprecate loudly, remove quietly.** The noise belongs at announcement, not at
   removal, by which time nothing should depend on it.
4. **Modernisation competes with features for the same budget**, and is scheduled
   explicitly rather than hoped for. Chapter 22's debt budget is the mechanism.

### The prioritised gap list

Every NEW and PARTIAL item in this document, ranked. This is the executable summary
of the whole specification.

| # | Gap | Chapter | Priority | Why this rank |
|---|---|---|---|---|
| ~~1~~ | ~~Tested backup and restore~~ | 9 | **DONE** — Phase R1 | `database/restore.py`; round trip proven against SQLite and a live PostgreSQL 16.13 with matching checksums. Found two defects by execution: a WAL database backed up file-only restored to nothing, and pg_dump was buffered entirely in memory |
| 2 | Rule 1 injection evidence across existing gates | 0, 19, 20 | **Critical** | **PARTIAL — Phases R2–R3.** Ledger built and ratcheting: 23 gates, **13 proven, 10 unproven**. Injecting found two further dead controls — gate M passed with no dataset, and the secret scanner skipped credentials containing `xxx` or `none` |
| 3 | Acceleration answer-invariance: cache age carried, downgrade always visible | 28, 32, 33 | High | A stale price or a silent model downgrade is a wrong answer delivered quickly |
| 4 | Data egress and sovereignty boundary | 13 | High | Blocks Group 1 §23/§24; currently convention, not control |
| 5 | Correlation key joining metrics, traces, logs, changes | 14 | High | Blocks Group 1 §16 |
| 6 | Change records with expected effect | 6 | High | Blocks Group 1 §16, §21, §32 |
| 7 | Authority Tiers 0 and 3 | 10 | High | Group 1's premise needs an observe-only tier |
| 8 | Stated degradation order, with the trading path excluded from it | 34 | High | Article IX is enforced in four places with no stated order of what is shed first |
| 9 | Progressive delivery + automated rollback | 5 | High | A bad release reaches everyone at once |
| 10 | Package ownership register with enforced edges | 1 | High | Depended on by 22, 23 and Group 1 §22/§56 |
| 11 | Incident declaration, timeline, postmortem | 15 | Medium | Triggers Group 1 §50 |
| 12 | Capacity forecasting and load-shed policy | 7, 34 | Medium | Redis is currently unbounded on a bounded host |
| 13 | Latency budgets per stage | 17 | Medium | Measurement exists; enforcement does not |
| 14 | Nightly `slow`/`e2e` run | 5, 19 | Medium | Process isolation is specified and unexercised |
| 15 | Routing decisions record the reason they chose a path | 30 | Medium | A router that cannot say why cannot be debugged when it chooses badly |
| 16 | SBOM and dependency provenance | 12 | Medium | Turns advisory response from search into query |
| 17 | Administrator console, starting with refusals | 26 | Medium | Governance evidence is invisible today |
| 18 | Debt measurement and budget | 22 | Medium | Feeds Group 1 §21 |
| 19 | Execution-target abstraction and capability probe | 29 | Medium | No target may be claimed until something has run on it |
| 20 | API versioning and deprecation policy | 21 | Low | No external consumers yet |
| 21 | Retention and classification policy | 25 | Low | Prerequisite for 3 at scale |
| 22 | `data/` ÷ `data_layer/` boundary decision | 1, 25 | Low | Holding position is workable; decide deliberately |

### Why this design

Because a specification that ends without a ranked list leaves the reader to
re-derive priority from thirty-five chapters, and they will derive a different
one each time. The ranking above follows a single rule — **worst case first, then
what unblocks the most** — and it is the rule, not the list, that should survive
revision.

---

## Appendix A — What this document deliberately does not cover

| Topic | Owning group |
|---|---|
| Cognition, reasoning, hypothesis, debate, curiosity | Group 1 |
| Operational *intelligence* (§16, §20, §21, §22) | Group 1 — inputs specified here, Ch 16 |
| Operator-facing AI surfaces, presence, workspace, accessibility | Group 0 |
| Trading strategy, risk model semantics, execution logic | Trading architecture |
| Documentation structure, backlog governance, decision records | Group 3 |

## Appendix B — Evidence base

Every AVAILABLE marker was measured on the working tree, not assumed:

* 19 GitHub Actions workflows
* `invariants/` 37 files, 5,582 LOC · `security/` 18 files, 10,088 LOC
* `compliance/` 2,518 LOC · `resilience/` 2,378 · `chaos/` 1,277
* `infrastructure/` 2,463 · `config/` 2,857 · `scripts/` 23,211
* `monitoring/` 1,093 · `tracing/` 1,017 · `rate_limiting/` 839
* `ai/` 23 packages including `gateway/` 3,283 and `hub/` 3,598
* 13 Kubernetes manifests, a Helm chart, 5 Compose variants, ArgoCD
* Test suites: 20,985 fast Python tests, 2,594 frontend tests

## Appendix C — Open questions

1. **`data/` ÷ `data_layer/` boundary.** Undocumented; holding position in force.
2. **Nightly `slow`/`e2e` cost.** Running them nightly costs CI minutes; not running
   them leaves process isolation unexercised. Decision needed, not a default.
3. **Whether Group 2 should own deterministic auto-remediation** that borders on
   inference (auto-rollback on an error-rate breach is a threshold; auto-rollback on
   an anomaly score is not). The line drawn in Chapter 16 is "does it require a
   hypothesis" and it will be tested by the first borderline case.
