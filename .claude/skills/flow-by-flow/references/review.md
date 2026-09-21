# Review gate

Use fresh reviewers when available. One reviewer attacks one dimension and returns findings, not rewritten product files. If only the builder is available, run the same passes sequentially and label the result `self-reviewed, lower assurance`.

## Review order

1. Source and specification coverage
2. Cross-flow contracts and domain consistency
3. Security, privacy, abuse, ownership, and destructive behavior
4. Accessibility, platform behavior, and visual fidelity
5. Interaction architecture, motion, feedback, haptics, interruption, and manipulation risk
6. Runtime failure paths, concurrency, retries, migration, and recovery
7. Code quality, duplication, dead code, and maintainability

Each finding contains severity, exact evidence, user impact, a concrete correction, and an objective verification step. Use `BLOCKER`, `MAJOR`, or `MINOR`. Fix blockers and majors, rerun the affected proof, and record accepted residual risk.

## Specialist packet

Give every reviewer the same source-of-truth packet and one bounded question. Reviewers may inspect shared artifacts but only the orchestrator edits them.

| Reviewer | Primary question | Required inputs |
|---|---|---|
| Design | Can the written identity reproduce the approved product language? | Design identity, approved direction, scorecard |
| Interaction | Is each page, inline state, popover, modal, drawer, or sheet justified, coherent, accessible, interruptible, and delightful without manipulation? | Flow prototype, `PROJECT_BIBLE.md`, state and transition contracts |
| Architecture | Are flow boundaries, schemas, interfaces, and deployment seams coherent? | Flow map, contracts, backend setup, flow files |
| Security | What breaks across auth, ownership, sensitive data, abuse, replay, and failure? | Security model, functions, data, contracts |
| Accessibility | Can each actor complete every applicable pathway? | States, flows, design identity, runtime evidence |
| Cross-flow | Do both sides of every seam agree? | All flows and contracts |
| Operations | Can the system deploy, recover, and run without hidden knowledge? | Environment contract, jobs, runbooks, evidence |

Reviewer prompt:

```text
You are the <DIMENSION> reviewer for <PRODUCT>. You did not write this work.
Attack only <DIMENSION>. Return:

SEVERITY | file:section | failure | user impact | concrete fix | verification

Do not praise or summarize. If no finding exists, say so. Inputs: <exact paths>.
```

## Cold-reader gate

Give a fresh agent only the foundation. Ask for:

1. The exact build order and dependency graph.
2. Every human decision required before work can continue.
3. Every contradiction and missing interface.
4. Every flow lacking sufficient acceptance evidence.
5. The first vertical slice and why it comes first.

Exit only when the cold reader has zero blocking questions and derives the same build order as the flow map. A correct guess still exposes a documentation failure if the foundation never stated the answer.

An implementer never approves its own work at independent-review assurance. Spec review passes before code-quality review. Any contract change triggers review of both neighboring flows.
