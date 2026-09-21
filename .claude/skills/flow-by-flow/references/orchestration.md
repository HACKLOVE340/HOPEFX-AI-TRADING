# Daily orchestration

Use this compact core for every coding task. The purpose is proportional flow awareness, not paperwork.

## 1. Inspect project truth

Inspect the instruction, business goal, repository rules, working tree, architecture, tests, runtime, established product documents, routes, screens, components, design tokens, interaction patterns, APIs, state, roles, and permissions. Preserve existing product language unless redesign is explicit. Runtime is evidence, not permission to preserve a bug.

Resolve conflicts in this order:

```text
current user instruction > safety and authority > repository constitution > approved decisions > proven runtime and code > current design assets > stale prose > builder judgment
```

## 2. Choose mode

| Mode | Minimum action |
|---|---|
| Existing Project | Inspect implementation, affected flows, patterns, and regression surface |
| New Application | Use Foundation, then Build until a runnable slice exists |
| New Feature | Discover prior, primary, next, abandonment, retry, role, and platform paths |
| Micro Task | Inspect the containing flow and adjacent regression risk |
| Bug or Repair | Reproduce, trace the first incorrect state, test, repair, and re-prove |
| Refactor | Map callers, contracts, state, migration risk, and regression pathways |
| Flow Prototype | Use `flow-prototype` to decide journey and interaction shape |
| Security or Audit | Map roles, objects, data, boundaries, abuse, failure, and proof gaps |

Use product paradigm `web`, `mobile`, `app`, `automation`, or `api`.

## 3. Select depth

| Depth | Temporary agents | Use when | Visible output |
|---|---:|---|---|
| Quick | 0 | Local, reversible, low-risk micro task | Affected flow, change, preserved behavior, proof |
| Standard | 1-2 | Normal feature or change across a few surfaces | Flow map, work tracks, Regression impact map, tests |
| Deep | 3-5 | Cross-flow state, persistence, integration, major UX, or uncertainty | Multi-perspective analysis and findings |
| Full Project Audit | 4-8 | Whole product, release, migration, regulated system, or audit | Complete source, flow, architecture, UX, security, and proof map |

Agent counts are ceilings. Quick uses no agent unless high-risk security or permission work raises depth. If independent agents are unavailable, run the perspectives sequentially and label them `self-reviewed, lower assurance`.

Risk floors: R0 local copy or visual work is Quick. R1 one-flow state or function change is Standard. R2 cross-flow contracts, persistence, integrations, migrations, or major UI/UX are Deep. R3 authentication, payments, permissions, sensitive data, destructive actions, production, or releases are Deep with independent review. Raise depth for uncertainty, blast radius, irreversibility, or missing proof.

Migration recovery defaults to Deep. Use Full Project Audit only for whole-product or release-wide recovery, or when the blast radius cannot be bounded.

For Standard or deeper work, read `references/delivery.md` completely. Quick reads it only when elevated risk applies.

## 4. Identify the affected flow

Name the actor, measurable goal, entry, trigger, exit, before and after behavior, surface, data movement, applicable system layers, failure and retry, dependencies, permissions, Regression impact map, tests, and proof. Keep this internal for Quick work. Do not turn frontend, backend, database, analytics, or notifications into separate user flows.

## 5. Protect interaction quality

Design interaction architecture before styling. For human-facing work, choose page, inline, popover, modal, drawer, or sheet based on context, complexity, interruption, reversibility, platform convention, and existing patterns. Define applicable loading, empty, validation, success, failure, retry, cancellation, interruption, motion, focus, accessibility, feedback, haptic intent, and reduced motion.

Every major UI/UX change requires a `flow-prototype` review surface and explicit user approval before production implementation. If no approver is reachable, halt before production UI. Questions forbidden is not approval. No post-hoc approval. A read-only prototype may continue only when it causes no production mutation.

## 6. Ask only material questions

Inspect first. Ask one concise batch only when an answer cannot be derived and changes architecture, user outcome, interaction shape, safety, cost, authority, public behavior, or an irreversible decision. Recommend an answer and name the affected flows. Use `LOCKED`, `APPROVED`, or reversible `ASSUMED`, never `TBD`.

## 7. Execute proportionally

Use installed capabilities when present and portable inline equivalents otherwise. Stabilize shared contracts, write failing-first tests, implement the smallest coherent slice, inspect security and accessibility in proportion to risk, verify the Regression impact map, run real commands, exercise the pathway, and separate automated proof, static proof, runtime proof, and unverified claims.

Quick output states the affected flow, exact change, preserved behavior, and verification. Do not create planning artifacts or dispatch agents by default. Standard or deeper output follows `references/delivery.md`.

Stop for missing authority, credentials, spending, legal acceptance, production release, App Store submission, payment activation, DNS changes, destructive real-data actions, and physical-device claims. Never invent secrets, approve irreversible actions, or claim native behavior from a browser simulation.
