# Verification gates

This reference preserves the proof gates that were previously enforced by packaged scripts. This bundle ships no executables, so the agent performs each gate directly, records the result honestly, and separates automated proof, static proof, runtime proof, and unverified claims. Run each gate proportionally to the selected depth and risk. A gate result never replaces transcript, specification, UX-approval, security, or real-runtime review.

Report every gate as one of: `PASS` (checked, evidence captured), `FAIL` (checked, defect found), or `UNVERIFIED` (could not check — state the exact reason). Never report a gate as passed without performing it.

## Gate 1 — Foundation structure

Run before declaring a foundation build-ready. Confirm the foundation matches the schema in `templates/foundation-pack.md`.

- Every required artifact for the paradigm exists: `00_Brief_Analysis.md`, `00_Source_Inventory.md`, `00_Flow_Map.md`, `00_Flow_Contracts.md`, `AGENTS.md`, `CONTEXT.md`, `SECURITY.md`, `BACKEND_SETUP.md`, `BUILD_AGENT.md`, `BUILD_PROMPT.txt`, `CLIENT_QUESTIONS.md`.
- Human-facing paradigms (`app`, `web`, `mobile`) also have `PROJECT_BIBLE.md`, `00_Surface_Coverage.md`, `Design_Identity/`, and `Sub_Interactions/`.
- Each required source in `00_Source_Inventory.md` has exactly one primary flow owner in `00_Surface_Coverage.md`.
- Every flow file carries the required headings and contains no empty signatures or `TBD`.
- `BUILD_PROMPT.txt` is within its declared character and line budget, and the actual count is recorded in `00_Brief_Analysis.md`.
- For regulated categories, any `legal/` draft carries `Approval status: APPROVED`, `Approved by`, and `Approved on` before the foundation may pass its legal-release gate. Do not self-approve legal text.

A structural pass is planning assurance only. It is not permission to claim the product runs.

## Gate 2 — Foundation execution (persistent products)

Run for products with persistent data or external services, using the `verification/commands.json` manifest defined in `templates/foundation-pack.md`.

- Run `bootstrap` twice in isolation and confirm the second run is idempotent.
- Run `migration_replay` once and confirm deterministic replay from zero.
- Run `auth_smoke` once. It must honor `FLOW_BY_FLOW_REPORT_DIR` and write `$FLOW_BY_FLOW_REPORT_DIR/authorization.json` proving `unauthenticated_denied`, `wrong_role_denied`, and `cross_object_denied`, each exercising the real caller role against the normal authorization boundary. A hard-coded report is not proof.
- Inspect every argv before running it; project-owned commands are a trust boundary.
- If credentials are unavailable, prove the local adapter and state exactly what remains unverified.

## Gate 3 — Build evidence

Run before calling a build complete, using the `BUILD_VERIFICATION.json` manifest defined in `templates/foundation-pack.md`.

- Every declared command (`tests`, `build`, `runtime-proof`) names a non-empty, project-owned `definition_file` that matches the invoked script or a recognized project manifest. Reject trivial executables and unlink-from-project commands.
- Inspect every argv and definition file before execution.
- Execute each command, read its exit code and inner exit codes, and capture argv, definition files, exit codes, stdout, and stderr into `evidence/verification/command-transcript.json`. Ensure project commands redact secrets before printing.
- The runtime-proof command must generate every declared evidence file fresh during this run, within its `max_age_hours`.
- A passing manifest proves only that project-linked commands passed and fresh declared evidence exists. It does not prove the commands are sufficient or the evidence truthful. A separate reviewer must compare implementation with specification, inspect the transcript, and drive the runtime. Record `independent review` or `self-reviewed, lower assurance`.

## Gate 4 — Build-state truth

Run when resuming a repository or after each flow. Reconstruct `BUILD_STATE.json` from repository truth, never from a hand-edited narrative.

- Rebuild from: current repository revision, working-tree status, the build-evidence result (Gate 3), verification commands, evidence paths, migration state, and open findings.
- For persistent products, the runtime-proof step must generate a `migration-state` evidence file containing tracked migrations, applied migrations, a schema fingerprint, and open recovery findings. Narrative summaries may explain that state but may not create it.
- Never let a manually edited state file override the working tree, migration ledger, test output, or runtime evidence.

## Gate 5 — Installation check

Run once after installing the package.

- Both skill folders are present: `flow-by-flow` and its required sibling `flow-prototype`.
- Each skill has its `SKILL.md` and every reference the `SKILL.md` names.
- Both skills declare the same release version in their frontmatter.
- `flow-by-flow` can reach `flow-prototype` for the major UI/UX approval surface. If the sibling is missing, incomplete, or on a different version, treat the installation as failed and reinstall both together.
