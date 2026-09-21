# Foundation workflow

This workflow creates the product foundation. In End to end mode, validation is a checkpoint, not the finish line. Continue into `build.md` without waiting for a second request.

## Choose the paradigm

| Paradigm | Surfaces | Design identity | Typical proof |
|---|---|---|---|
| Web | Routes, modals, sheets, jobs | Required | Browser walkthrough, screenshots, network and accessibility evidence |
| Mobile | Screens, stacks, tabs, gestures, background work | Required | Simulator or device pathways, lifecycle and accessibility evidence |
| App | Shared product language across web and mobile | Required | Platform-specific proof for every shared flow |
| Automation | Schedules, watched folders, queues, approvals, CLI | Only for a human surface | Fixtures, transitions, idempotency, audit log, external effect |
| API | Endpoints, webhooks, jobs, callbacks, events | Only for a supplied console | Contract and auth tests, failure injection, observable effects |

Web and mobile share product language but use platform-native navigation, input, feedback, lifecycle, storage, and accessibility behavior. For APIs and automations, replace screen language with triggers, state transitions, approvals, responses, logs, retries, and recovery. Human operational clarity is still user experience.

## Phase 0: Inspect and classify

1. Read the brief, transcripts, current docs, brand assets, screenshots, and any existing code or runnable artifact.
2. Select mode, paradigm, target platforms, target users, and proof environment.
3. Build `00_Source_Inventory.md` from `templates/foundation-pack.md`. Hash and classify every supplied item as `AUTHORITATIVE`, `DIRECTIONAL`, `BEHAVIOR_ONLY`, `CONTENT_ONLY`, or `SUPERSEDED`.
4. Use the artifact-appropriate inspection method. Extract text from PDFs, create labeled contact sheets for large screen sets, inspect archives, and mine routes, manifests, API clues, permissions, and behavior from supplied apps or binaries. Treat extraction as evidence, not permission to reuse code.
5. Record contradictions and precedence. Link recovered evidence IDs into later design, flow, route, and backend decisions.
6. Create the applicable artifact tree from `templates/foundation-pack.md` only after the target workspace is known.
7. Log missing inputs as named gaps. Do not silently invent them.

For human-facing products, create or update `PROJECT_BIBLE.md` from `templates/foundation-pack.md`. It is the compact source map for product intent, navigation, components, tokens, interaction grammar, motion, haptics, architecture, state, APIs, roles, permissions, and durable decisions. Link to authoritative project documents instead of duplicating them. Do not create it for a Micro Task unless the project already has one or the task establishes a reusable product rule.

Write `00_Brief_Analysis.md` with:

- One-sentence north star
- Exact declaration `Persistent data: yes` or `Persistent data: no`
- Exact declaration `Sensitive categories: none` or a named list
- Actors and their measurable goals
- Scope and non-goals
- The one or two signature moments the product lives or dies on
- Supplied materials and their paths
- Platform, integration, compliance, budget, and delivery constraints
- Decision register with `LOCKED`, `APPROVED`, or `ASSUMED`
- Open questions, each with a recommended reversible default

Use `templates/foundation-pack.md` so the validator and build route share one schema.

Write `CLIENT_QUESTIONS.md` from `templates/foundation-pack.md`. Ask one batch with at most 7 true unblockers for a typical product or 10 for a complex or regulated product. Explain each question in plain language and recommend an answer. Deduplicate questions across flows. Continue under reversible `ASSUMED` defaults unless correctness, authority, authentication, sensitive data, secrets, cost, public behavior, or destructive action requires a stop.

## Phase 1: Asset checkpoint and visual direction

For a human-facing product, inspect brand and reference assets before detailed flow work. Ask only for missing assets that materially change the result.

If authoritative designs exist, derive the design system from them and verify fidelity. Do not force a redesign exercise. If no authoritative direction exists, create 3 structurally different directions on the same representative surfaces and obtain a selection. When the user delegates visual choice, mark it `ASSUMED`, not `APPROVED`.

Measure colors, fonts, spacing, radii, icon bounds, viewports, and aspect ratios with appropriate tools. For APK or app bundles, inventory manifests, densities, fonts, icons, localization, permissions, and route clues. Treat decompiled code as behavioral evidence unless reuse rights are explicit.

Build one clickable golden flow. Give a fresh agent only the written design identity and ask it to reproduce the selected surfaces. Compare at the same viewports and patch the identity when a rule failed to transmit. Record inputs, scores, concrete deltas, rounds, and evidence paths. A clickable prototype is early review evidence, not native runtime proof.

For every major UI/UX change, use `flow-prototype` and obtain approval before production implementation. Prototype the representative journey, material states, page or inline or popover or modal or drawer or sheet decision, transitions, interruption, feedback, semantic haptics, responsive behavior, and reduced-motion alternative. Existing precedent may reduce prototype scope but never bypass prototype review or approval. Follow established product patterns automatically. If an interaction shape remains materially ambiguous, ask one concise batch with a recommendation.

Design for clear momentum and satisfying feedback without dark patterns, fake urgency, coercive loops, or noisy stimulation. Browser vibration is simulation only and never proves native mobile haptics.

Skip this phase for a headless API or automation. If an automation has a CLI or approval UI, specify only that human-facing surface.

## Phase 2: Domain grill

Prepare the load-bearing question batch after inspecting the workspace. Ask only decisions that change architecture, user outcome, safety, cost, or flow boundaries. Include a recommended answer and the consequence of choosing differently. Use concrete success, rejection, retry, cancellation, expiry, recovery, abuse, and deletion scenarios. Questions discoverable from files, code, assets, or runtime are inspection tasks, not user questions.

Cover:

- Actor, role, tenant, and ownership boundaries
- Domain terms and lifecycle states
- Success, rejection, cancellation, retry, expiry, and recovery
- Data retention, deletion, export, and audit requirements
- Integrations, external ownership, and failure behavior
- Business rules, compliance, abuse, and cost ceilings

Maintain `CONTEXT.md` as a glossary only. Create an ADR only for a hard-to-reverse, surprising decision with a real trade-off.

## Phase 3: Architecture and security model

Write `BACKEND_SETUP.md` and `SECURITY.md` before per-flow implementation instructions.

Architecture must name:

- Chosen stack and why it fits the constraints
- Domain model and lifecycle state machines
- Storage schema, ownership, retention, and migrations
- API, event, webhook, queue, and background-job contracts
- Shared components and services with exact interfaces
- Environment keys by name and purpose, never secret values
- Observability, cost controls, deployment, rollback, and recovery
- Relevant `PROJECT_BIBLE.md` architecture, state, API, role, and permission sections

For products with persistent data or external services, prose is not enough. Create stack-appropriate executable artifacts:

- Versioned schema or migrations
- Deterministic seed or fixture
- `.env.example` with names and purpose, never values
- Idempotent local bootstrap and start commands
- Auth and authorization smoke tests using real caller roles
- Reset and rollback safeguards

Create the product's `verification/commands.json` from the foundation-execution manifest schema in `templates/foundation-pack.md`. This is the foundation execution manifest exercised by Gate 2 in `references/verification.md`, not the later build-evidence manifest. It is an object keyed by `bootstrap`, `migration_replay`, and `auth_smoke`, each holding the product's own project-owned command (for example `["make", "bootstrap"]`).

Gate 2 runs `bootstrap` twice to prove idempotency, then runs migration replay and authorization smoke once. `auth_smoke` must use `FLOW_BY_FLOW_REPORT_DIR` and write `$FLOW_BY_FLOW_REPORT_DIR/authorization.json` proving `unauthenticated_denied`, `wrong_role_denied`, and `cross_object_denied`, in the report shape given in `templates/foundation-pack.md`. Each check must exercise the real caller role against the normal authorization boundary. A hard-coded report is not proof.

Run the local bootstrap before declaring the foundation build-ready. If credentials are unavailable, prove the local adapter and state exactly what remains unverified.

For regulated categories, create legal drafts under `legal/`, but do not label them approved. The validator requires the user or qualified reviewer to add `Approval status: APPROVED`, `Approved by: <name>`, and `Approved on: YYYY-MM-DD` before the foundation can pass its legal release gate.

Security pass 1 must name:

- Trust boundaries and data classification
- Authentication and authorization matrix by actor and action
- Tenant and object ownership enforcement
- Input and file validation
- Secret storage and log redaction
- Abuse, rate limits, replay, idempotency, and concurrency
- Destructive actions and recovery
- Category-specific threats likely to surface after launch

Use a fresh architecture critic and security critic when agents are available. They return findings only. The orchestrator reconciles the result.

## Phase 4: Decompose by actor goal

Write `00_Flow_Map.md` using `templates/foundation-pack.md`.

For human-facing products, write `00_Surface_Coverage.md` using `templates/foundation-pack.md`. Give every required supplied screen, route, modal, sheet, viewport, and system state exactly one primary flow. Shared elements may be referenced by multiple flows, but primary ownership remains unique and explicit.

A flow passes only if it has:

- One primary actor
- One measurable goal
- A clear trigger and success outcome
- A boundary that can be reasoned about independently
- Named entries, exits, and neighboring flows

Split a flow when the primary actor changes, the measurable goal changes, an irreversible handoff occurs, or the segment needs independent release and proof. Keep it together when screens or services are only steps toward the same actor goal. A login step belongs inside the goal it unlocks unless identity itself is the user's measurable goal. Notifications and analytics are shared systems, never standalone user flows.

Do not create frontend, backend, database, notification, or analytics flows. Those are concerns inside actor-goal flows.

## Phase 5: Deepen each flow

Research independent flows in parallel only when agents have bounded questions and no shared writes. Give each reviewer the brief, glossary, design identity, security model, flow map, exact flow schema, required output format, and prohibition on user contact. One orchestrator reconciles terminology, contracts, and final files.

Each agent returns:

- One `flows/Flow_XX_<name>.md` using `templates/foundation-pack.md`
- One `Sub_Interactions/Flow_XX_sub_interactions.md` for human-facing flows
- Proposed questions with recommended defaults
- Conflicts with shared contracts or terminology
- Evidence IDs and exact source surfaces assigned to the flow

The orchestrator resolves conflicts and writes the final files.

UI specialists also return the interaction container decision, transition contract, motion and reduced-motion behavior, feedback channel, semantic haptic guidance, and any material user decision. They do not invent a new product pattern when the existing application already has one.

## Phase 6: Contract the seams

Write the shared-foundation registry and one directed contract for every edge in the flow map using `templates/foundation-pack.md`. Give identity/session, errors, observability, notifications, and analytics one canonical owner. Then verify both neighboring flow documents agree with it.

A contract change is a cross-flow change. Update the contract and both consumers, then re-run cross-flow review.

## Phase 7: Constitution and build directive

Write root `AGENTS.md` as the build constitution. It includes product truth, locked decisions, document map, conflict hierarchy, build order, proof requirements, stop conditions, and repository rules. Keep tool-specific adapter files short and point them to `AGENTS.md`.

Use this conflict hierarchy unless the user's repository already defines a stricter one:

```text
user instruction > repository constitution > security and data rules > flow contracts > backend and design references > individual flow notes > builder judgment
```

Write both build directives from `templates/foundation-pack.md`:

- `BUILD_AGENT.md`: the full autonomous operating prompt with order, per-flow loop, backend activation, stop points, proof, and completion criteria.
- `BUILD_PROMPT.txt`: a compact adapter for constrained goal fields. Keep it at 60 lines and 4000 characters or fewer unless the target declares a smaller limit. Record the target and actual character count in `00_Brief_Analysis.md`.

## Phase 8: Review and validate

Run `references/review.md`. Fix all blocking and major findings. Then perform Gate 1 (Foundation structure) in `references/verification.md` for the chosen paradigm.

For persistent products, also perform Gate 2 (Foundation execution). A structural pass is planning assurance only. It is not permission to claim the product runs.

Before running Gate 2, inspect each argv in `verification/commands.json`. Do not confuse it with `BUILD_VERIFICATION.json`: the former proves foundation bootstrap, migrations, and authorization; the latter declares tests, build, runtime proof, and evidence for the build-evidence gate (Gate 3).

The foundation is ready only after Gate 1 passes and a fresh cold reader has zero blocking questions. In End to end mode, immediately continue with `references/build.md`.
