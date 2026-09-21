# Audit and extension mode

Use this mode when the product already exists. The goal is to discover reality, prove each flow, repair defects, and produce the same portable foundation used for greenfield work.

Scale the audit to the request. A Micro Task inspects only the containing flow and adjacent regression risk. A feature maps every affected flow and seam. A Full Project Audit reverse-maps the whole product.

## Truth hierarchy

Different sources answer different questions:

1. Current user instruction defines the desired outcome.
2. Security, data ownership, and business rules define what is allowed.
3. The live runtime shows what users experience now.
4. Deployed code and tests explain that behavior.
5. Current design assets define the intended product language.
6. Stale documents are historical evidence only.

Runtime behavior is evidence, not proof that the behavior is correct. Record conflicts with competing claims, evidence, risk, and the selected resolution.

When resuming, do not trust a progress log or `BUILD_STATE.json` by itself. Reconstruct state in this order: repository revision and working tree, tracked migrations versus the real ledger and schema, executable test and build results, fresh runtime evidence, then narrative logs. If persistence may be dirty, run the Migration recovery section in `references/build.md` before implementation.

## Reverse-map the product

Run independent read-only discovery tracks where possible:

- Runtime: drive visible routes, deep links, notifications, empty states, errors, recovery, and role-specific actions.
- Code: enumerate routes, screens, commands, endpoints, jobs, events, guards, feature flags, data models, and integrations.
- Documents: extract terminology, decisions, design rules, and outdated assumptions.

Produce:

- `00_Source_Inventory.md` with authority and provenance classifications
- `00_Surface_Coverage.md` with exact-once primary flow ownership
- Route-by-role matrix
- UI-action-to-function matrix, or trigger-to-handler matrix for non-UI systems
- Current design identity extracted from real assets and rendered screens
- Current interaction grammar: page, inline, popover, modal, drawer, sheet, navigation, motion, feedback, haptics, and accessibility behavior
- `00_Flow_Map.md` grouped by actor goal
- `00_Flow_Contracts.md` based on the data and events actually passed
- Per-flow evidence and confidence level

Every discovered route, command, endpoint, job, and permission branch must belong to a flow or be classified as dead, duplicate, internal, or out of scope.

Create or refresh the affected sections of `PROJECT_BIBLE.md` when the product understanding changes. Existing project documents remain authoritative and should be linked, not copied. Build a Regression impact map naming every screen, route, API, state store, role, platform, and recovery path that must be retested because of the request.

When many screens or pages are supplied, create labeled contact sheets or an equivalent index. When apps, binaries, or archives are supplied, record extraction method, hashes, routes, permissions, API clues, and the boundary between behavioral evidence and reusable code.

## Prove each flow

Drive the real system using safe accounts and disposable data. For each pathway record:

- Environment, deployed revision, actor, role, tenant, and preconditions
- `WORKS`, `PARTIAL`, `BROKEN`, or `UNVERIFIED`
- Exact failure step and expected result
- Screenshots or transcript
- Short recording for UI flows
- Network, log, state, or database evidence
- Security, accessibility, and design drift findings

Use production read-only when mutation risk is unclear. Use staging or disposable records for destructive actions. Never turn unavailable roles or credentials into guessed behavior. Mark the gap and continue with the accessible surface.

## Fix and re-prove

For every real defect:

1. Reproduce it and capture baseline evidence.
2. Trace the root cause through UI, network, handler, authorization, and persistence.
3. Write a failing regression test.
4. Implement the smallest coherent fix.
5. Run the affected test suite and security checks.
6. Deploy to the user-approved preview or test surface.
7. Drive the full pathway and adjacent states again.
8. Capture fresh proof.

A code diff or test result alone does not turn a flow green.

For every major UI/UX repair or extension, prove the interaction shape in `flow-prototype` and obtain approval before production implementation. Existing precedent may reduce prototype scope but never bypass prototype review or approval. The prototype must expose material states, transitions, interruption, feedback, reduced motion, and platform-specific haptic guidance.

## Extend to another platform

Extract the stable product language from the proven implementation: domain terms, information architecture, tokens, voice, feedback patterns, permissions, and contracts. Keep product outcomes and contracts stable while translating navigation and input into the target platform's native grammar.

Start with one representative golden flow. Compare it with the source platform using the fidelity process. Once it passes, build the remaining flows in dependency order using `references/build.md`.
