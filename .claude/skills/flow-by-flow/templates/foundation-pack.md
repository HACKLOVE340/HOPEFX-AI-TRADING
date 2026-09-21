# Foundation pack templates

This is the only Markdown template reference. Generate only artifacts that apply to the selected paradigm. Do not copy this file into the product.

## Output tree

```text
product-root/
  AGENTS.md
  CONTEXT.md
  PROJECT_BIBLE.md              # human-facing products
  00_Brief_Analysis.md
  00_Source_Inventory.md
  00_Surface_Coverage.md        # human-facing only
  00_Flow_Map.md
  00_Flow_Contracts.md
  CLIENT_QUESTIONS.md
  SECURITY.md
  BACKEND_SETUP.md
  BUILD_AGENT.md
  BUILD_PROMPT.txt
  .env.example                  # when configuration exists
  assets/{brand,references}/
  Design_Identity/              # human-facing only
  flows/Flow_01_<name>.md
  Sub_Interactions/             # human-facing only
  backend/{migrations,seed}/    # persistent products only
  scripts/bootstrap             # stack-specific
  scripts/auth_smoke            # persistent products only
  verification/commands.json    # persistent products only
  evidence/{design,reviews,flows}/
```

`AGENTS.md` is the constitution. Source inventory owns provenance. Surface coverage owns exact source assignment. Flow map owns decomposition and dependency order. Flow contracts own coupling. Individual flow files own behavior inside their boundary. Evidence proves claims but never overrides requirements.

## PROJECT_BIBLE.md

Use for human-facing products. Update only the sections affected by the task. Link to authoritative design, architecture, API, and security documents instead of copying them.

```markdown
# Project Bible

## Product intent
<audience, business goal, product promise, constraints>

## Navigation and surfaces
<route and screen hierarchy, page/modal/drawer/sheet/popover/inline conventions>

## Components and tokens
<component system, typography, spacing, colors, shape, elevation>

## Interaction grammar
<tap, click, focus, gesture, loading, validation, feedback, interruption, recovery>

## Motion and haptics
<duration, easing, continuity, reduced motion, semantic haptic mapping>

## Architecture and state
<system boundaries, state owners, persistence, offline and synchronization rules>

## APIs and events
<contracts, events, errors, retries, idempotency, observability>

## Roles and permissions
<actor-role-action-object matrix and enforcement boundary>

## Decision log
<LOCKED, APPROVED, or ASSUMED durable decisions with evidence and affected flows>
```

## 00_Brief_Analysis.md

```markdown
# Brief analysis

- North star: <one sentence>
- Paradigm: app, web, mobile, automation, or api
- Target platforms: <list>
- Persistent data: yes or no
- Sensitive categories: none or named categories
- Proof environment: local, preview, sandbox, simulator, device, or deployed target

## Actors and measurable goals
## Scope and non-goals
## Signature moments
## Supplied materials
## Constraints
## Decision register
## Open questions
```

Every decision is `LOCKED`, `APPROVED`, or reversible `ASSUMED`, with an owner and affected flows. Authentication, money, sensitive data, deletion, and public behavior cannot remain silently assumed.

## 00_Source_Inventory.md

```markdown
| ID | Source | SHA-256 | Kind | Authority | Coverage | Inspection method | Status and findings |
|---|---|---|---|---|---|---|---|
| REF-001 | <path> | <hash> | screen, PDF, app, code, audio, brand, data | AUTHORITATIVE, DIRECTIONAL, BEHAVIOR_ONLY, CONTENT_ONLY, SUPERSEDED | required or contextual | visual, extraction, runtime, static, metadata | <finding> |
```

Every supplied file appears once. Required screens, routes, commands, events, and states must later receive one primary flow owner. Preserve originals. Treat extracted application code as behavioral evidence unless reuse rights are explicit.

## CLIENT_QUESTIONS.md

```markdown
# Client questions

## Decisions that unblock correctness
<7 questions maximum, or 10 for a complex or regulated product>

## Confirm or correct
<grouped reversible ASSUMED defaults>

## Deferred or discoverable
<questions deliberately not sent and why>
```

Each question gives a recommended answer, short explanation, affected flows, decision owner, and reversibility.

## 00_Flow_Map.md

```markdown
# Flow map

## Product outcome

## Flow registry
| ID | Flow | Primary actor | Goal | Trigger | Success outcome | Entry flows | Exit flows | Depends on | Proof |
|---|---|---|---|---|---|---|---|---|---|
| 01 | <name> | <actor> | <goal> | <trigger> | <measurable result> | <ids> | <ids> | shared-foundation | <runtime evidence> |

## Dependency order
| Batch | Kind | Includes | Depends on |
|---|---|---|---|
| shared-foundation | shared | identity/session, errors, observability, notifications, analytics | none |
| flow-01 | flow | Flow_01 | shared-foundation |

## Surface and function coverage
## Cross-flow edges
```

Every flow appears once. Shared infrastructure belongs to `shared-foundation`, not whichever feature touches it first.

## 00_Surface_Coverage.md

Use for human-facing products.

```markdown
| Source ID | Flow | Surface or role | Primary owner | Status | Evidence or rationale |
|---|---|---|---|---|---|
| REF-001 | Flow_01 | Welcome screen | yes | assigned | <source path> |
```

Required source IDs must have exactly one primary owner. Shared use is secondary, never a second primary assignment.

## 00_Flow_Contracts.md

```markdown
# Flow contracts

## Global contracts
| ID | Applies | Owner | Contract | Verification |
|---|---|---|---|---|
| identity-session | all flows | shared-foundation | <rules> | <test> |
| error-taxonomy | all flows | shared-foundation | <codes and language> | <test> |
| observability | all flows | shared-foundation | <correlation and redaction> | <test> |
| notifications | named flows | shared-foundation | <events and deep links> | <test> |
| analytics | named flows | shared-foundation | <schema and consent> | <test> |

## <Flow A> -> <Flow B>
- Trigger and entry point
- Required data, types, and source of truth
- Preconditions and enforcing layer
- Actor, role, tenant, session, and token assumptions
- Shared service owner
- Events, notifications, analytics, or callbacks
- Success signal and return path
- Cancellation and failure handoff
- Idempotency, retry, concurrency, migration, and rollback
- Contract tests and runtime proof
```

A contract change updates this file, both neighboring flows, tests, and cross-flow review.

## Flow_XX_<name>.md

```markdown
# Flow_XX: <Name>

## Goal
<actor, measurable goal, trigger, success, boundary, neighbors>

## References and coverage
<source IDs, authority, assigned surfaces, preserved or changed behavior>

## Entries, sequence, and exits
<happy path, re-entry, cancellation, screens, commands, events, jobs, endpoints>

## States and feedback
<processing, loading, empty, validation, permission, unavailable, offline, rate-limited, expired, conflict, retry, cancelled, partial success, success>

## Interaction surface and transitions
<page, inline, popover, modal, drawer, or sheet decision; entry, exit, interruption, focus, motion, reduced motion, feedback, semantic haptics>

## Actions and functions
<actor, trigger, function or endpoint, inputs, validation, authorization, side effects, idempotency, outputs, retry, concurrency, rollback, observability>

## Data and integrations
- Persistent data: yes or no
<reads, writes, storage, queues, external services, environment keys, retention, deletion, cache, offline behavior>

## Security and abuse cases
## Accessibility
## Platform behavior
## Contracts
## Verification
## Open decisions
## Build seed
```

Under Verification, map every requirement, action, state, and contract to its implementation symbol, automated test, runtime proof, evidence path, and status. No empty signatures or `TBD`.

## Sub_Interactions/Flow_XX_sub_interactions.md

Use for human-facing flows.

```markdown
# Flow_XX interaction sweep
## Interaction map
## Surface decisions
## Spawned surfaces
## Hidden states
## Edge cases
## Micro-interactions
## Motion and interruption
## Feedback and semantic haptics
## Gaps found
```

Cover every visible or focusable element, page, inline state, popover, modal, drawer, sheet, menu, system prompt, dismissal, double-submit, interrupted request, backgrounding, stale session, retry, haptic, announcement, focus move, and reduced-motion behavior that applies. Explain why each spawned surface is the correct container. Specify motion trigger, target, duration, easing, entrance, exit, interruption, and reduced-motion alternative. Use semantic haptics and never vibrate every tap.

## Design_Identity

Write concrete values, not adjectives.

```markdown
# Design identity

## Evidence header
- Approved direction: <path or decision>
- Reference alignment score: <0-100 or n/a>
- Transmission score: <0-100>
- Target viewports and devices: <list>
- Compared artifacts: <paths>

## Product character
## Color tokens
## Typography roles
## Spacing, shape, and elevation
## Components and states
## Motion and feedback
## Screen anatomy
## Platform deltas
```

Each token name appears once. Specify exact values, roles, allowed surfaces, contrast pairings, typography metrics, component anatomy and states, motion interruption, reduced motion, and responsive behavior.

## BUILD_AGENT.md and BUILD_PROMPT.txt

`BUILD_AGENT.md` contains mandate, required reading, conflict hierarchy, blank-repository bootstrap, dependency order, per-flow loop, backend activation, security, accessibility, performance, supply-chain checks, deployment, rollback, recovery, evidence, stop points, and definition of done.

Keep `BUILD_PROMPT.txt` at 60 lines and 4000 characters or fewer unless the target has a smaller limit:

```text
You are the <PRODUCT> build orchestrator. Read AGENTS.md and the complete
foundation. Inspect the repository and run baseline checks.

If no runnable repository exists, scaffold it with a lockfile, environment
example, migrations, fixtures, local bootstrap, CI, and one proven vertical slice.

Build in the dependency order in 00_Flow_Map.md. Per flow: write the failing test,
build every state and action, run security and accessibility checks, capture fresh
runtime proof, get spec review before code-quality review, and do not advance red.

Never invent secrets. Stop for App Store submission, production deployment,
payment activation, DNS changes, legal acceptance, destructive data actions,
physical-device claims, or any costly action without exact authority.

Before DONE, create BUILD_VERIFICATION.json from real commands and evidence,
link each command to its project-owned definition file, inspect every argv, run the
verifier, inspect its command transcript, then complete separate spec and runtime review.
List every unverified claim.
```

## Verification manifests

These two machine schemas were formerly shipped as standalone `.json` files. They are kept here as the canonical schema source. Generate the real file inside the product (not inside this skill) only when the paradigm requires it. Read `references/verification.md` for how each manifest is exercised.

### Foundation execution manifest — `verification/commands.json`

Create this in a persistent product's `verification/` directory. It drives the foundation execution gate. The object is keyed by `bootstrap`, `migration_replay`, and `auth_smoke`. Replace every placeholder with the product's real, project-owned commands.

```json
{
  "schema_version": 1,
  "commands": {
    "bootstrap": ["REPLACE_WITH_IDEMPOTENT_BOOTSTRAP_COMMAND"],
    "migration_replay": ["REPLACE_WITH_DETERMINISTIC_MIGRATION_REPLAY_COMMAND"],
    "auth_smoke": ["REPLACE_WITH_REAL_CALLER_AUTHORIZATION_SMOKE_COMMAND"]
  },
  "authorization_report_contract": {
    "written_by": "auth_smoke",
    "path": "$FLOW_BY_FLOW_REPORT_DIR/authorization.json",
    "checks": [
      {"id": "unauthenticated_denied", "passed": true},
      {"id": "wrong_role_denied", "passed": true},
      {"id": "cross_object_denied", "passed": true}
    ]
  }
}
```

The foundation execution gate runs `bootstrap` twice to prove idempotency, then runs `migration_replay` and `auth_smoke` once. `auth_smoke` must honor `FLOW_BY_FLOW_REPORT_DIR` and write `$FLOW_BY_FLOW_REPORT_DIR/authorization.json` in the shape above, with each check exercising the real caller role against the normal authorization boundary. A hard-coded report is not proof.

### Build-evidence manifest — `BUILD_VERIFICATION.json`

Create this at the product root before the build-evidence gate. Every command must name a non-empty, project-owned `definition_file` (such as `package.json`, `Makefile`, `pyproject.toml`, or the invoked script), and the runtime-proof command must generate every declared evidence file during the run.

```json
{
  "schema_version": 1,
  "persistent_data": false,
  "commands": [
    {
      "name": "tests",
      "argv": ["REPLACE_WITH_PROJECT_TEST_COMMAND"],
      "definition_file": "REPLACE_WITH_PROJECT_OWNED_FILE_THAT_DEFINES_TESTS"
    },
    {
      "name": "build",
      "argv": ["REPLACE_WITH_PROJECT_BUILD_COMMAND"],
      "definition_file": "REPLACE_WITH_PROJECT_OWNED_FILE_THAT_DEFINES_BUILD"
    },
    {
      "name": "runtime-proof",
      "argv": ["REPLACE_WITH_COMMAND_THAT_WRITES_THE_DECLARED_EVIDENCE"],
      "definition_file": "REPLACE_WITH_PROJECT_OWNED_FILE_THAT_DEFINES_RUNTIME_PROOF"
    }
  ],
  "evidence": [
    {
      "path": "evidence/flows/Flow_01/runtime-proof.txt",
      "produced_by": "runtime-proof",
      "kind": "runtime",
      "max_age_hours": 24
    }
  ]
}
```
