---
name: flow-by-flow
description: Use for any software development task, including applications, features, screens, bugs, refactors, UI or backend improvements, security reviews, automations, prototypes, and micro changes in new or existing codebases.
license: MIT
metadata:
  author: Benjamin Macaulay at Chasebig Limited
  compatibility: Codex, Claude Code, Claude Skills, and Agent Skills hosts. Markdown-only; no runtime dependencies.
  version: "2.0.1"
---

# Flow by Flow

## Identity

Think, analyse, orchestrate, build, debug, prototype, secure, and test software flow by flow. Every coding task starts with one question:

> Which user flows are affected?

A flow is one actor pursuing one measurable goal across product and system surfaces. Break the request into connected units instead of treating it as one large problem. One orchestrator owns user contact, shared contracts, specialist routing, integration, and final proof.

## Always start here

Read `references/orchestration.md` for every task. It is the compact core for modes, depth, risk, affected-flow discovery, questions, proof, and approval gates.

For Standard, Deep, or Full Project Audit work, also read `references/delivery.md`. For Quick work, read it only if security, permissions, persistence, integration, migration, major UI/UX, or another elevated risk forces deeper delivery controls.

Then load only the routes that apply:

| Need | Read completely |
|---|---|
| New application, incomplete brief, or missing foundation | `references/foundation.md` |
| Existing application, bug, refactor, extension, or audit | `references/audit.md` |
| Implementation or resume work | `references/build.md` |
| Independent review | `references/review.md` |
| Proof gates for a foundation, build, or install | `references/verification.md` |

End to end: for a new application, read `references/foundation.md`, then `references/build.md`. Continue until one runnable client-to-persistence vertical slice is proven, unless a stop condition requires human authority.

Use `web`, `mobile`, `app`, `automation`, or `api` as the product paradigm. Treat the existing application, repository rules, `PROJECT_BIBLE.md`, design system, architecture, and runtime as source evidence. Current user instructions and safety constraints remain higher authority.

## Flow contract

For each affected flow or unit, identify only what applies:

- Actor, goal, entry point, trigger, and exit
- UI surface and interaction container
- Frontend, backend, data, API, state, and permission behavior
- Success, failure, validation, interruption, retry, and transition states
- Dependencies, regression impact, tests, runtime proof, and unresolved risk

Quick tasks keep this contract in the conversation. Standard or deeper tasks update established project artifacts when the decision is durable. Never create a full foundation pack for a micro task.

## Orchestration rules

1. Inspect before asking. Questions discoverable from files, code, designs, or runtime are inspection work.
2. Preserve existing product language unless redesign is explicit.
3. Use installed specialist skills instead of recreating their workflows. Use the portable fallback when a named capability is unavailable.
4. Create temporary agents only when an independent perspective can change the outcome. Give each a bounded packet and no shared contract ownership.
5. Major UI/UX changes require a `flow-prototype` approval surface before production implementation. If no approver is reachable, halt before production UI. Questions forbidden is not approval. No post-hoc approval.
6. Build in dependency order with failing-first tests, security checks, accessibility checks, and fresh runtime evidence.
7. Report automated proof, static proof, runtime proof, and unverified claims separately.

## Durable artifacts

Use `templates/foundation-pack.md` for full foundations, including `PROJECT_BIBLE.md`. It also holds the two verification manifest schemas: the persistent foundation-execution manifest (`verification/commands.json`) and the build-evidence manifest (`BUILD_VERIFICATION.json`). Generate those manifests inside the product, not inside this skill. Update existing project documentation instead of duplicating it.

## Stop conditions

Stop for missing authority, credentials, spending, legal acceptance, production release, App Store submission, payment activation, DNS changes, destructive real-data actions, and physical-device claims. Never invent secrets, approve irreversible actions, or claim native haptic or device behavior from a browser prototype.

## Gates

Read `references/verification.md` and perform each applicable gate directly, since this bundle ships no executables:

1. Foundation structure — the foundation matches the `templates/foundation-pack.md` schema.
2. Foundation execution — for persistent products, bootstrap runs twice idempotently, migrations replay deterministically, and real-caller authorization is proven.
3. Build evidence — declared tests, build, and runtime-proof commands are project-owned, inspected, executed, and produce fresh evidence and a command transcript.
4. Build-state truth — `BUILD_STATE.json` is reconstructed from repository truth, never a hand-edited narrative.
5. Installation check — both skills are present, complete, and on the same version.

Run the gates proportionally, and report each as `PASS`, `FAIL`, or `UNVERIFIED` with its reason. A passing gate does not replace transcript, specification, UX approval, security, or real runtime review.
