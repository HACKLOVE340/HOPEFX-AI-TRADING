# Build workflow

Use this after a validated foundation, when resuming a repository, or as the second half of End to end mode.

This route owns proof-first implementation, root-cause repair, safe delegation, migration recovery, proof capture, and evidence gating. Rebuild `BUILD_STATE.json` from repository truth using Gate 4 in `references/verification.md`. Never let a manually edited state file override the working tree, migration ledger, test output, or runtime evidence.

## Migration recovery

Use before resuming persistent work when the repository, migration ledger, or environment may be partially applied.

1. Stop writers and identify the exact database and environment.
2. Compare tracked migration files and hashes with the real ledger and schema.
3. Inspect required seed records. Treat build logs as supporting evidence only.
4. Identify the database-specific transaction, locking, online-schema-change, replication, and rollback model. Account for non-transactional DDL, partially committed work, and replication lag.
5. If an applied migration hash changed, restore it only from a verified canonical source such as the applied release artifact or immutable repository revision, then create a forward migration. Never reconstruct it from memory.
6. Determine whether a partial failure rolled back before replaying anything. Choose rollback or forward-fix from database-specific evidence, not convenience.
7. Create a recoverable backup before destructive repair and pass a restore test in an isolated target. A backup file without a successful restore test is unverified.
8. Run bootstrap twice in isolation, then run wrong-role, cross-object, and cross-tenant checks.
9. Regenerate machine-readable migration and build state from current commands.

Stop when the environment is ambiguous, writers cannot be safely controlled, repair may lose data, a checksum changed after application without a canonical source, database-specific behavior is unknown, or no verified restorable backup exists. Use the database vendor's current operational runbook when recovery depends on engine-specific behavior.

## Bootstrap a blank repository

When no runnable repository exists:

1. Record the chosen stack, pinned tool versions, exact scaffold command, package manager, target platforms, and why they fit the foundation.
2. Run the scaffold command. Commit the dependency lockfile and preserve the generated platform structure.
3. Add `.env.example`, deterministic fixtures, local adapters, versioned migrations or schema, seed data, and an idempotent bootstrap command.
4. Add format, lint, typecheck or analyze, test, build, secret scan, and dependency audit commands to CI.
5. Add health checks, structured redacted logs, error correlation, and the preview or sandbox deployment path.
6. Build one thin client-to-persistence vertical slice, including authorization as real caller roles. Prove it locally before splitting into independent flows.
7. Verify a clean checkout can bootstrap, start, test, and build without production credentials.

The scaffold is not complete if architecture exists only in Markdown.

## Orient once

1. Read root instructions and repository rules.
2. Read `AGENTS.md`, decision register, context glossary, security model, backend setup, design identity when applicable, flow map, and all contracts.
3. Read `PROJECT_BIBLE.md` when present and inspect only the affected product, interaction, architecture, API, state, role, and permission sections.
4. Inspect the code and commit history to determine what is already real.
5. Run the existing setup, lint, typecheck, build, and test commands before changing code.
6. If the baseline is broken, reproduce it, isolate the smallest failing path, form testable hypotheses, gather evidence, identify the root cause, add a regression test, and repair it.

Create shared foundations before feature flows: tokens, error model, auth/session handling, storage and network interfaces, observability, motion and accessibility primitives where applicable, and one real verification command.

Use proportional assurance. Low-risk local presentation changes need focused tests and one reviewer. Cross-flow state, authentication, persistence, money, sensitive data, or release changes require the full per-flow loop and independent adversarial review. Record the risk tier instead of applying maximum ceremony to every edit.

Use `references/orchestration.md` to select mode, depth, specialist budget, capability adapters, and progressive output. Do not dispatch temporary agents as a ritual. Use them only when their independent perspective can change the implementation.

## Refactor contract

A behavior-preserving refactor does not invent a new failing product behavior. Before changing structure, define a behavior-equivalence boundary and capture it with a characterization test, differential test, snapshot, trace comparison, contract suite, or performance-equivalence check that fits the system. Record callers, inputs, outputs, side effects, errors, ordering, timing budgets, and observable state that must remain stable.

First prove the characterization fails when the preserved contract is deliberately perturbed, or show that it detects a known historical deviation. Then refactor in small steps, rerun focused equivalence checks after each step, and finish with the relevant broad suite and real pathway proof. If no meaningful equivalence oracle can be built, raise risk, narrow the change, or stop and request the missing product decision.

## API extension contract

Treat machine-to-machine callers, webhook senders, jobs, and SDK consumers as actors with measurable goals. Before implementation, define backward compatibility, versioning and deprecation, consumer compatibility, pagination, schema evolution, error stability, replay behavior, rate limits, observability, and ownership. Prefer additive changes. A breaking change requires explicit authority, a migration path, and coordinated consumer proof.

Use an established OpenAPI, protobuf, event schema, SDK contract, or equivalent source when present. If none exists, create the smallest project-native executable contract and test at least one old consumer expectation alongside the new behavior. Do not treat a handler test alone as end-to-end API proof.

## Automation reliability contract

Before implementation, lock the retry taxonomy: retryable, terminal, human-review, and unknown failures. Define timeout, maximum attempts, backoff and jitter, dead-letter or escalation behavior, idempotency-key scope and retention, atomic claim or lease recovery, concurrency ownership, and the delivery contract, such as at-least-once or effectively-once.

Test duplicate delivery, concurrent delivery, lease expiry, partial failure, exhausted retries, and a crash between external effect and acknowledgement. Prove how reconciliation detects an effect that succeeded before local state recorded it. If the external system offers no idempotency or lookup mechanism, stop before claiming duplicate-safe automation and require an explicit compensating or manual-reconciliation design.

## Implementation order

Build in dependency order from `00_Flow_Map.md`. Parallelize research and review freely. Parallelize implementation only when flows have stable contracts, no shared writes, isolated workspaces, and a planned integration order. Otherwise, keep one flow in flight.

For subagent-driven work, give each implementer the full flow contract, seam contracts, relevant design and security rules, exact files in scope, expected tests, and required proof. Do not make the implementer rediscover the plan.

Delegate implementation only after contracts stabilize. Use isolated workspaces for concurrent changes. The orchestrator retains contract ownership. An implementer may propose a change but may not silently redefine a seam. Review spec compliance before code quality, integrate in dependency order, and rerun cross-flow tests after every merge.

## Per-flow loop

1. **Re-read the flow and seams.** Confirm inputs, preconditions, outputs, and failure handoff.
2. **Write a failing test.** Cover the next behavior, failure, or security rule before implementation.
3. **Build through interfaces.** Use deterministic local adapters and fixtures where external credentials are absent. Never invent secret values. Keep the real adapter behind the same contract.
4. **Implement every state.** Include loading or processing, empty, validation, permission, offline or unavailable, rate-limited, expired, conflict, retry, cancellation, and success where relevant.
5. **Wire every action.** Every visible control, CLI command, event, and endpoint either performs its documented action or is explicitly non-interactive.
6. **Create pathway proof for UI flows.** Refresh a locally openable clickable walkthrough and a pathway trace mapping `source element -> action -> state or destination -> implementation symbol -> test -> evidence`. It is an early review surface, not a substitute for native runtime proof.
7. **Run the interaction and product-character pass.** Confirm the chosen page, inline, popover, modal, drawer, or sheet matches the task and platform. Check responsiveness, signature moments, motion continuity, interruption, feedback channels, semantic haptics, emotional character, and reduced-motion behavior. Do not vibrate every tap or use manipulative engagement patterns.
8. **Run security pass 2.** Attack authz, object ownership, tenant isolation, input validation, secret handling, replay, duplicate submission, races, partial failure, rollback, session expiry, token revocation, account recovery, and account deletion.
9. **Run accessibility and platform checks.** Prove keyboard or switch completion, screen-reader names and announcements, large text, contrast, target sizes, focus restoration, and reduced motion where applicable.
10. **Verify.** Run format, lint, typecheck, focused tests, full relevant tests, build, secret scan, and dependency audit. Read the output and inner exit codes.
11. **Capture traceable proof.** Map every in-scope action, state, contract row, and security rule to implementation, automated test, runtime proof, and evidence path. Drive all critical-risk branches and verify external or persistent side effects.
12. **Review twice.** A fresh reviewer checks spec compliance first. After that passes, another checks code quality and maintainability.
13. **Integrate.** Update only the established project log or memory, report evidence, and commit if the repository workflow authorizes it.

When behavior surprises you, stop speculative patching. Reproduce it, separate baseline failures, trace the first incorrect state, test one hypothesis at a time, add a failing regression test, repair the root cause, then run focused and broad verification. If three hypotheses fail, restate the evidence and widen inspection.

After each flow, refresh `BUILD_STATE.json` from the current repository revision, verification commands, evidence paths, migration state, and open findings. For persistent products, the runtime-proof command must generate a `migration-state` JSON evidence file containing tracked migrations, applied migrations, a schema fingerprint, and open recovery findings. Narrative summaries may explain that state but may not create it.

Do not start the next dependent flow while the current flow is red or its contract is violated.

For every major UI/UX change, production implementation remains blocked until the `flow-prototype` representative flow is selected or approved. Existing precedent may reduce prototype scope but never bypass prototype review or approval. Record the decision in `PROJECT_BIBLE.md` when it establishes a reusable product pattern, then remove or absorb the throwaway prototype.

## Proof packs

Save proof under the repository's established evidence location. If none exists, use `evidence/flows/Flow_XX/`.

For UI flows:

- Screenshots for happy, loading, empty, error, and permission states
- Short real-runtime recording of the happy path and one failure path
- Deployed revision and environment
- Test and build transcript
- Network or backend side-effect evidence
- Clickable walkthrough and pathway-to-code trace
- Accessibility evidence for applicable assistive modes
- Requirement-to-proof traceability matrix

For automation flows:

- Input fixture and immutable hash
- State-transition transcript
- Approval and retry behavior
- Idempotency and duplicate-prevention proof
- Retry taxonomy, attempt schedule, dead-letter or escalation proof
- Crash between external effect and acknowledgement, lease recovery, and reconciliation proof
- Audit log and resulting external side effect

For API flows:

- Contract tests
- Auth and role matrix tests
- Invalid-input and replay tests
- Backward compatibility, consumer compatibility, pagination, and schema evolution proof
- Observability trace and persistent side effect

## Backend activation

Missing credentials must not block local behavior, but a fake adapter does not prove production integration. Activate external systems only with real secrets, explicit environment selection, sandbox proof where available, and user approval for costly or destructive actions.

Always stop for App Store submission, production deployment, DNS changes, payment activation, legal acceptance, real-data deletion, paid external actions, and physical-device claims unless the user has explicitly authorized that exact action and target.

Verify authorization as real caller identities. Admin or owner SQL often bypasses policy enforcement and is not sufficient.

For persistent systems, rebuild the database from zero in CI or an isolated local environment. Prove deterministic migration replay, seed behavior, wrong-role rejection, cross-object and cross-tenant denial, idempotency, concurrency handling, and safe rollback or forward-fix behavior.

## Operations and release proof

Before production handoff, prove the environment contract, health and readiness checks, log redaction, metrics or traces, alert ownership, migration rollout, deployment smoke test, release promotion, rollback or forward-fix procedure, backup and restore procedure, and incident runbook. If deployment authority is absent, produce sandbox or preview proof and mark production activation unverified.

Measure the quality budgets named by the foundation, such as startup, interaction latency, frame time, memory, payload size, throughput, offline recovery, and accessibility. Qualitative claims do not satisfy numeric budgets.

## Final hardening

Run security pass 3 with a fresh adversarial reviewer across the full diff and all cross-flow contracts. Attack failure paths, wrong roles, cross-tenant access, retries, concurrency, resource failure, and partial success.

Run supply-chain gates: committed lockfiles, secret scanning, dependency advisory scanning, generated-code review where applicable, and CI enforcement. Apply paradigm controls such as CSRF, CORS, CSP, secure and same-site cookies, secure mobile storage, deep-link validation, backup exclusion, and permission handling when applicable.

The build is complete only when every in-scope flow has passing tests, real proof, satisfied contracts, no open blocking review findings, and a final report that distinguishes:

- Verified by automated test
- Verified by static or build check
- Verified by real runtime proof
- Not verified, with the exact reason

Create `BUILD_VERIFICATION.json` from the build-evidence manifest schema in `templates/foundation-pack.md` and the target product's actual test, build, security, and runtime-proof commands. Every command must name a non-empty, project-owned `definition_file`, such as `package.json`, `Makefile`, `pyproject.toml`, or the invoked script. The definition must match the invoked script or a recognized project manifest. Resolve common wrappers before inline evaluation and reject trivial executables. Inspect every declared argv and definition file before execution because project-owned commands remain a trust boundary. The runtime-proof command must generate every declared evidence file during the verification run.

Then perform Gate 3 (Build evidence) in `references/verification.md`. It captures `evidence/verification/command-transcript.json` with argv, definition files, exit codes, stdout, and stderr for review. Ensure project commands redact secrets before they print. A passing build-evidence gate proves only that project-linked commands passed and fresh declared evidence exists. It does not prove the commands are sufficient or the evidence is truthful. A separate reviewer must compare the implementation with the specification, inspect the transcript, and drive the runtime. Record `independent review` or `self-reviewed, lower assurance` in the final report.
