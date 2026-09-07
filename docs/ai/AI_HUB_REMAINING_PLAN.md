# AI Hub — the remaining work, in the order it should be done

**Measured, not remembered.** Every number here comes from
`ai/hub/capabilities.py`'s own verifier (`python -c "from ai.hub.capabilities
import coverage; print(coverage())"`), which resolves each `live` claim by
importing the module or reading the file it names. A row is not built because
somebody said so.

At the time of writing: **216 capabilities · 161 live · 28 staged · 27 planned ·
189/189 evidence resolved · 0 discrepancies · 75% built.**

Sections finished (nothing planned or staged): §5, §6, §12, §13, §15, §16, §19.

---

## Why this is a phase plan and not 61 pre-written tasks

The `writing-plans` skill asks for bite-sized, no-placeholder tasks. That is the
right shape for handing one feature to an engineer who has not seen the
codebase. It is the wrong shape for sixty-one rows across eighteen sections,
for one honest reason: **the last six phases will be planned against code the
first six have not written yet**, and a task list written now would specify
function names and test bodies that the intervening work invalidates.

Pre-writing them would produce a document that looks more complete and is less
true. So each phase below carries what is knowable now — the exact rows, the
files, the dependency that fixes its position, and the one rule the phase must
not violate — and its tasks are written at the top of that phase, against the
tree as it then is.

## Ordering principle

Dependency, not size. An earlier draft of this list ordered by row count, which
put §18 (ambient awareness, 5 rows) first and the event bus eighth. The event
bus unblocks four sections; ambient awareness unblocks none. Row count is a
measure of effort, not of what is in the way.

---

## Phase A — §12 agent messaging: the event bus  ✅ DONE

**Unblocked:** §11 orchestrator, §14 event-triggered tasks, §24 event-bus row,
§12's own streaming partials. §12 now has nothing planned or staged.

| Row | Was | Now | Evidence |
|---|---|---|---|
| Publish/subscribe event bus | planned | live | `ai.bus.agent_bus:AgentBus` |
| Task graph rather than a sequential queue | planned | live | `ai.bus.graph:TaskGraph` |
| Typed message — ten fields | staged | live | `ai.bus.agent_bus:AgentBus` |
| Task lifecycle events | staged | live | `ai.bus.lifecycle:TaskLifecycle` |
| Streaming partial results | staged | live | `ai.bus.lifecycle:TaskLifecycle` |
| §24 Event bus — Redis streams or equivalent | planned | live | `core.event_bus:EventBus` |

**Built:** `ai/bus/agent_bus.py`, `ai/bus/graph.py`, `ai/bus/lifecycle.py`,
`core/startup_factories.py:init_ai_agent_bus` (registered, `deps=["event_bus"]`),
38 tests in `tests/unit/test_agent_bus_and_task_graph.py`.

**The rule held:** *a message bus is not an execution path.* Asserted by
parsing `ai/bus/*.py` — not grepping it, since those modules discuss the tool
bus at length — for any import of `ai.tools`, any use of the name `ToolBus`, or
any `.invoke`. A subscriber receives one frozen dataclass, positionally, with
no keyword context and no operator identity inside the envelope.

**The second rule held:** `TaskGraph.add()` walks the edge it is about to
create and raises `CycleRefused` naming the cycle. Detection at schedule time
would mean the first task in the cycle had already run.

### Three things this phase found

1. **`stack.event_bus` (§24) was never a gap.** `core/event_bus.py` is a
   Redis pub/sub bus with 49 importers, connected at startup by
   `init_event_bus`. The row said `planned` while it ran in production —
   a registry error of the same class as the `agents.system` double-count.

2. **A `subscribe_local` handler on that bus fires only when Redis is DOWN.**
   Local handlers are the degraded path; when Redis is healthy, `publish()`
   goes to Redis and local handlers hear nothing. A subscription registered
   there would pass every test (no Redis in CI → degraded → delivered) and
   fire never in production. That is `hopefx-dead-controls` exactly, and it is
   why `AgentBus` delivers in-process directly and treats Redis as additive
   fan-out rather than as its transport.

3. **Cross-worker RECEIVE is not live, and says so.** `AgentBus.consume` exists;
   no factory starts one. So `Delivery.fanout` always reports in words what
   happened on the other workers — "in-process only…", or "published to
   core.event_bus … a worker receives them only where AgentBus.consume is
   running". Silence there would read, to a caller, as having reached them.
   Starting a reader belongs to Phase B, where the orchestrator is the first
   thing that needs another worker's messages.

## Phase B — §14 task orchestration

**Depends on:** Phase A's graph and bus, both now built. Sequenced after
Track S at the owner's direction (2026-09-07).

| Row | State |
|---|---|
| Event-triggered tasks | planned |
| Long-running research jobs | planned |
| Concurrency limits and priority queues | staged |
| §11 Orchestrator — decompose, allocate, track, merge, resolve | staged |

**Files:** `ai/jobs/runner.py` (priority queue), `ai/agent/orchestrator.py`
(new), `ai/bus/triggers.py` (new — an event pattern that starts a task graph),
`ai/bus/agent_bus.py` (start a `consume` reader, closing Phase A's third
finding).

**Second rule:** the orchestrator decomposes into a `TaskGraph` and executes
it; it does not re-implement ordering. A second scheduler beside the graph is
how the graph stops being the thing that decides what runs.

**Rule:** a priority queue must not starve. A low-priority job that never runs
because high-priority work keeps arriving is a job that silently never happens,
and the operator sees `queued` for ever. Ageing, and a test that asserts a
low-priority job eventually runs under sustained high-priority load.

---

## Phase C — §22 telemetry honesty

**Unblocks:** §23 resource-aware rendering, §26 pause-under-load.

| Row | State |
|---|---|
| GPU, CPU and memory telemetry | planned |
| Agent health | planned |
| Security events | planned |
| Neural engine indicator bound to real model state | planned |
| No fake live values in production | staged |

**Files:** `ai/telemetry/` (new), `api/ai_core.py` (read surface only).

**Rule — the one this whole section is named for:** *an unmeasured metric is
absent, never zero.* A CPU gauge reading 0% because `psutil` is not installed is
the exact defect §22 exists to forbid, and it is worse than no gauge because it
reads as an idle machine. Every metric is `None` with a reason or a real
reading. The "neural engine" indicator must be bound to actual model state —
§3 claims it exists; it does not, and a decorative one would be the same lie.

---

## Phase D — §23 component architecture

**Depends on:** Phase C's telemetry for resource-aware rendering.

| Row | State |
|---|---|
| Scene graph for spatial awareness | planned |
| State store for workspace sessions | planned |
| Virtualisation for high-density displays | planned |
| Resource-aware rendering and frame-rate protection | planned |
| Cognitive stream — user-facing explanation distinct from internal trace | planned |
| Schema-driven panel generation | staged |
| Layout engine independent of content | staged |
| Accessibility and reduced-motion support (for generated panels) | staged |

**Also closes:** §8 surface types + priority tiers, §9 scene model + panel
registry, §21 representation selection, §10 multi-display console.

**Files:** `frontend/src/hub/sceneGraph.ts`, `workspaceStore.ts`,
`SurfaceView.tsx`, `layout.ts`.

**Rule:** the cognitive stream is what the AI tells the operator; the internal
trace is what it tells itself. Merging them either floods the operator with
tool-call noise or hides the reasoning. They are separate structures, and a
test asserts the user-facing stream contains no tool names or raw payloads.

---

## Phase E — §18 ambient awareness

| Row | State |
|---|---|
| Gesture recognition | planned |
| Pointing and object reference | planned |
| Optional attention-aware interaction | planned |
| Screen and camera source selection | planned |
| Local processing where feasible | planned |

**Also closes:** §25 privacy controls for memory/microphone/camera, §7 attention
states.

**Rule:** every ambient capability is **off by default and revocable in one
action.** A camera or microphone that turns itself on is the worst thing in this
plan, and "optional" in the spec's own wording is a requirement, not a hint.
Local processing is preferred *and stated* — the operator must be able to see
whether a frame left the machine.

---

## Phase F — §17 real-time conversation

| Row | State |
|---|---|
| Wake word where privacy-appropriate | planned |
| Pronunciation dictionary for names and financial terms | planned |
| Adjustable speech speed and voice preference | planned |
| Low-latency streaming speech recognition | staged |
| Push-to-talk and optional continuous conversation | staged |
| Turn detection | staged |

**Rule:** a wake word means an always-listening microphone. It ships off, it
says so on screen while it is on, and "privacy-appropriate" is decided by the
operator rather than by a default.

---

## Phase G — §27 accessibility

| Row | State |
|---|---|
| High contrast option | planned |
| Touch and mouse support | planned |
| Keyboard navigation | staged |
| Screen-reader semantics | staged |
| Reduced motion mode | staged |
| Responsive layouts | staged |
| Clear focus states | staged |

**Rule:** run the `ui-ux-pro-max` pre-delivery checklist against the whole hub,
not the new parts. Two defects it already found in this session (a removed focus
ring, muted text at 4.36:1) were in code that had passed review.

---

## Phase H — the remainder

| § | Row | State |
|---|---|---|
| 26 | Render large workspaces efficiently | planned |
| 26 | Pause or reduce animation under load | planned |
| 26 | Graceful offline and degraded states | staged |
| 26 | Prevent runaway recursive delegation | staged |
| 24 | Isolated agent workers with task contracts | staged |
| 11 | System agent — infrastructure, services, resources, failures | planned |
| 20 | Market war room generated on demand | planned |
| 4 | Presence layer / Environment layer | planned |
| 7 | Natural idle movement and attention states | staged |

§4's two rows are roll-ups: they become live when the layers beneath them are,
and are deliberately last so they cannot be claimed early.

---

---

# Track S — the AI that improves itself, inside a vault

**Owner request, 2026-09-07:** the AI should walk all the code in the app —
including its own — improve itself and the app, stay awake to do it, and be
locked away from attack so nobody can use it to change our code. Every
advancement gets approved.

That is four capabilities and one containment, and the containment has to be
built first. This track is sequenced accordingly: **S1 before S2, always.**

## What already exists (measured, not assumed)

| Control | Where | State |
|---|---|---|
| Integrity baseline, drift detection, quarantine, git rollback | `security/self_healer.py` | built |
| HMAC-signed patch queue; unsigned is REFUSED by default (F130) | `security/self_healer.py` | built |
| Fail-closed static validation of AI-proposed Python, in a disposable dir | `security/ai_repair_sandbox.py` | built |
| Approve/decline API over `fixes:queue` | `api/security/fixes.py` | built |
| Two distinct approvers, at least one superadmin; execution needs superadmin + 2FA | `ai/policy/roles.py` | built |
| Untrusted-input fencing and output secret scanning | `ai/guardrails/` | built |
| Tool layer with permission registry + 16 constitutional invariants | `ai/tools/bus.py` | built |

So "approved" and "sandboxed" are largely solved. What is not:

**`TRACKED_GLOBS` in `security/self_healer.py` includes `security/**/*.py`,
`risk/**/*.py`, `execution/**/*.py`, `core/**/*.py` and `api/**/*.py`.** A
signed, approved patch can therefore rewrite the self-healer that checks the
signature, the risk manager that sizes positions, and the OMS that sends
orders. Approval is a human reading a diff; a subtle change to a signature
check is exactly the diff a human does not catch. That is the hole the vault
closes, and it is why S1 comes first.

---

## Phase S1 — the vault: paths no AI-proposed change may touch  ✅ DONE

**Files:** `ai/vault/protected.py` (new), `ai/vault/__init__.py`,
`security/self_healer.py` (consult it before applying), and
`security/ai_repair_sandbox.py` (refuse at validation, so a protected-path
patch never even reaches the queue).

**What it is:** a path list, evaluated **before** content, that no
AI-originated change can modify no matter who approves it — the security
layer, the risk layer, the execution layer, the invariants, the permission
registry, the approval code itself, CI configuration, and the vault module and
its own tests.

**What it found, before it fixed anything.** `SelfHealer.apply_config`
replaced the protected list with `cfg.get("protected_paths", "")`, and
`HealingConfigBody.protected_paths` is a Pydantic field defaulting to `""`. So
the first save of the auto-healing config from the superadmin dashboard — with
that box left as it comes, empty — erased all thirty protected paths on the
live healer. Reproduced by execution before the fix:

```
>>> h = SelfHealer(); h._is_protected("risk/manager.py")
True
>>> h.apply_config({"aggressiveness": "high"})
>>> h._is_protected("risk/manager.py")
False
```

`risk/manager.py`, `execution/engine.py`, `kill_switch.py` and `auth/jwt.py`
were then auto-patchable by AI-generated code. And even at its default the old
list protected none of the controls that stop the AI: not the healer that
verifies patch signatures, not the two-approver policy, not the permission
registry, not the invariants, not the guardrails, not the tests, not CI.

**Four rules, each with a test:**

1. **Refusal is by path, before content.** No amount of clean-looking diff
   makes a protected path allowable. The content check runs only on paths that
   already passed.
2. **Fail closed on the unresolvable.** A traversal (`../`), an absolute path,
   a symlink pointing out of the tree, or anything that will not resolve to a
   file inside the repository is REFUSED, not allowed by default. Every
   path-allowlist defect is this one.
3. **No environment opt-out.** `HEAL_ALLOW_UNSIGNED_PATCHES` exists and is the
   right shape for a dev convenience; the vault has none, because an env var is
   precisely what an attacker who reached the host would set. Asserted: the
   module reads no environment variable at all.
4. **The vault protects the vault.** `ai/vault/**` and its tests are in the
   list. A containment an AI can propose to widen is not a containment.

**Registry:** three rows live (`improve.vault`, `improve.path_before_content`,
`improve.sandbox_target_check`) under a new section `S` — a letter, not §28,
because these are an owner request and the specification never named them.
Four more are `planned` and carry no evidence, which is what the rest of this
track will close. 20 tests, confirmed red on the pre-fix tree.

---

## Phase S2 — the code-walking agent, read-only  ← NEXT

**Depends on:** S1. Building a proposer before its containment is backwards in
a system that moves money.

**Files:** `ai/improve/walker.py` (new), `ai/improve/finding.py` (new).

**What it is:** an agent that walks every module in the repository — `ai/`
included, which is the part the owner asked for by name — and emits
**findings**, not patches. A finding carries a file, a line, a claim, and
evidence that resolves; the registry's own discipline, applied to code review.

**Rules:** it imports nothing that can write. It cannot reach `ai/tools/bus.py`
(same AST assertion `ai/bus` carries). Its input is repository text, which is
untrusted the moment a dependency or a comment can carry an instruction, so
every file it reads is fenced through `ai/guardrails/input.py` before it
reaches a model. A finding names what it measured; "looks fine" is not a
finding and neither is a count of files scanned.

---

## Phase S3 — a finding becomes a proposal, and a proposal needs two humans

**Depends on:** S1 and S2.

**Files:** `ai/improve/proposal.py` (new), wiring into
`security/ai_repair_sandbox.py` and `fixes:queue`.

**What it is:** the path from finding → candidate diff → vault check → sandbox
validation → signed queue entry → the existing two-approver, one-superadmin
gate → `SelfHealer` applies it, with quarantine and rollback as they already
are. Nothing new is invented for approval; the AI is a producer of proposals
and never an applier.

**Rule:** the AI's own modules are proposals like any other. A patch to
`ai/improve/` needs the same two approvers. An AI that could self-modify
without review is the failure mode this whole track is arranged against.

---

## Phase S4 — always awake, and honest about what it did not do

**Depends on:** S1–S3, and Phase A's bus for reporting.

**Files:** `ai/improve/cycle.py` (new), a startup factory, a registry row.

**What it is:** a continuous improvement cycle — walk, find, propose, report —
on a schedule, with a spend ceiling, a rate limit, and a kill switch that stops
it without a deploy.

**Rules:**
- **A cycle that proposed nothing says so, with the reason.** Silence from a
  self-improving system reads as "nothing is wrong". Every cycle reports what
  it walked, what it found, what it proposed, and what it refused to propose
  because the path was in the vault.
- **The budget is real.** Every walk is paid model calls. It runs under
  `ai/gateway/budget_store.py`'s shared ceiling, and a cycle that would exceed
  it is skipped and says it was skipped — never silently truncated.
- **Off by default, on by an owner decision.** A self-improvement loop that
  starts itself on first deployment is a change nobody chose.

---

## What every phase does, without exception

1. `flow-by-flow` first — mode, depth, risk floor, affected flows.
2. Failing tests before implementation, and **run them red**.
3. Wire it. A capability nothing calls is `staged`, not `live` — the
   `hopefx-dead-controls` rule, and the reason `agents.system` was wrong.
4. Update `ai/hub/capabilities.py` with evidence that **resolves**.
5. `pre-commit run --all-files`, the fast suite, and the frontend suite where
   touched. Exit codes read directly, never through `tail`.
6. One commit per phase, saying what was decided and why.

## How to check this plan is still true

```bash
.venv/bin/python -c "from ai.hub.capabilities import verify, coverage; \
  print(coverage()); print(verify().discrepancies)"
```

If `discrepancies` is not empty, a row claims to be built and cannot prove it.
That is the only number in this document worth trusting more than the prose.
