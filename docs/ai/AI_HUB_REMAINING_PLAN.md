# AI Hub — the remaining work, in the order it should be done

**Measured, not remembered.** Every number here comes from
`ai/hub/capabilities.py`'s own verifier (`python -c "from ai.hub.capabilities
import coverage; print(coverage())"`), which resolves each `live` claim by
importing the module or reading the file it names. A row is not built because
somebody said so.

At the time of writing: **228 capabilities · 184 live · 26 staged · 18 planned ·
210/210 evidence resolved · 0 discrepancies · 81% built.**

Sections finished (nothing planned or staged): §5, §6, §12, §13, §15, §16, §19,
and all of Track S.

**55 rows remain**, across seventeen sections:

| § | left | § | left | § | left |
|---|---:|---|---:|---|---:|
| 4 | 2 | 11 | 4 | 22 | 5 |
| 7 | 1 | 14 | 3 | 23 | 8 |
| 8 | 2 | 17 | 6 | 24 | 1 |
| 9 | 2 | 18 | 5 | 25 | 1 |
| 10 | 1 | 20 | 1 | 26 | 4 |
| 21 | 2 | 27 | 7 | | |

Seven phases (B through H) cover all of them. §4's two rows are roll-ups and
land last by construction.

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

## Phase B — §14 task orchestration  ✅ DONE

**Depends on:** Phase A's graph and bus, both now built. Sequenced after
Track S at the owner's direction (2026-09-07).

| Row | State |
|---|---|
| Event-triggered tasks | planned |
| Long-running research jobs | planned |
| Concurrency limits and priority queues | staged |
| §11 Orchestrator — decompose, allocate, track, merge, resolve | staged |

**Built:** `ai/jobs/priority.py`, `ai/bus/triggers.py`,
`ai/agent/orchestrator.py`, plus admission wiring in `ai/jobs/runner.py`.

**Rule held — a priority queue must not starve.** Rank is priority *minus* how
long an item has waited, so a `background` item overtakes a just-arrived
`critical` one after exactly the tier gap in ageing periods. Bounded and
stated, rather than absent and hoped for. A plain priority queue answers
"critical" for ever under sustained load, and the starved job shows `queued` on
the operator's screen — indistinguishable from one about to start.

**Priority engages only under contention.** `ThreadPoolExecutor` is the live
path for every AI Core panel and is strictly FIFO; replacing it would put a
scheduler in front of code that works. The queue sits in front of *admission*
and is consulted only when the pool is saturated, so uncontended submission is
byte-for-byte unchanged — which is what the existing job tests exercise, and
they still pass.

**Second rule held — the orchestrator executes a graph.** A test parses
`ai/agent/orchestrator.py` for any sorting of its own. Decomposition is
*declared*: turning a question into steps is a planner's paid model call, and
keeping it out makes the graph deterministic. Allocation **names** what it
could not place — unknown department, unimplemented action, or one that is not
read-only — because a step dropped from the plan reads exactly like a step that
ran and returned nothing. A conflict goes to `ai/debate/session.py` and is
never averaged: an average cannot express UNRESOLVED.

**A trigger enqueues and never executes.** Running the task inside the
subscriber callback would make the bus an execution path, which is the one
thing §12 was built not to be. Every triggered item carries a depth one higher
than the message that caused it, because a task that publishes the event that
triggers it is a loop that eats the queue.

**`parallel.long_running` is staged, not live** — the honest half-verdict. The
*scheduling* half is built: a job can carry any deadline at `background`
priority without starving interactive work and, because the queue ages, without
being starved by it. The *durability* half is not: `JobRunner` holds jobs in an
in-process dict, so an hour-long research job dies with the process and its
result is unrecoverable. Calling it live would promise something a restart
disproves.

**Three tests my own arithmetic got wrong**, fixed against the code rather than
the other way round: a "just arrived" critical item is one enqueued at the
moment of comparison (a waiting one is ageing too); `shadow_place_order` is
READ_ONLY because shadow mode does not place anything; and a single stance
comes back UNRESOLVED with a reason rather than raising — which is the better
behaviour and was already built.

---

## Phase S5 — the patch generator, as its own decision  ✅ DONE

**Owner decision, 2026-09-07.** S4 deliberately shipped without one: *"turning
the schedule on and letting a model author code unattended are two different
decisions, and they should be made separately."* This is the second decision,
taken separately, as asked.

**Files:** `ai/improve/patcher.py` (new), wiring into `ai/improve/cycle.py`'s
`patcher` parameter and `core/startup_factories.py`.

**What it is:** a callable that takes a `Finding` and returns candidate source
for the file it names. It runs through `ai/gateway`, so it is budgeted,
audited, rate-limited and circuit-broken like every other model call in this
system.

**What does not change, and this is the point.** The generated source still
passes S3's five gates — evidence resolves, the vault by path, it changes
something, under the ceiling, the sandbox accepts it — and still needs two
distinct approvers, one a superadmin, before it becomes a pull request a human
merges. The model gains the ability to *write a suggestion*. It gains nothing
else.

**Built:** `ai/improve/patcher.py`, wired through
`core/startup_factories.py:init_ai_improvement_cycle`. All five rules held:

1. **Input untrusted.** The whole file AND the snippet are fenced separately
   through `ai/guardrails/input.py` — the finding pointed at four lines and the
   model is shown all of them, so any line can carry an instruction. Our
   instruction comes first, the fenced blocks after: a fence placed before the
   instruction invites the model to read the instruction as part of the data.
2. **Output untrusted.** `scan_output` runs before the text is returned, not
   after the proposal is built. A refusal never logs the text — the whole point
   is that it may carry the secret.
3. **Never a protected file.** Checked here as well as in the cycle. A second
   door into the same room is how the first one stops mattering.
4. **A second switch.** `AI_IMPROVE_PATCHER`, off by default, and a typo fails
   towards *disabled*. A test asserts that turning the schedule on does not turn
   the generator on.
5. **Refusals are results.** Prose, unparseable code, an unchanged file, a
   gateway failure, a guardrail refusal — each recorded against its finding.

**A file too large is refused, never truncated.** Truncating asks a model to
rewrite a file it only half saw, and the answer would look complete.

**Two defects the tests caught in my own code:** `extract_source` was stripping
the file's final newline, which would have put a diff on the last line of every
file it ever touched; and my "file too large" test picked a vault-protected
path, so it was passing for the wrong reason — the size gate never ran.

**Nothing else changed.** A generated patch passes the same five gates in
`ai/improve/proposal.py` and needs the same two approvers, one a superadmin,
before it becomes a pull request a human merges. The model gained the ability
to write a suggestion. It gained nothing else.

---

## Phase C — §22 telemetry honesty  ✅ DONE

**Unblocks:** §23 resource-aware rendering, §26 pause-under-load.

| Row | State |
|---|---|
| GPU, CPU and memory telemetry | planned |
| Agent health | planned |
| Security events | planned |
| Neural engine indicator bound to real model state | planned |
| No fake live values in production | staged |

**Built:** `ai/telemetry/{reading,host,agents,security,neural}.py`, plus
`GET /api/ai-core/telemetry` and its `_VIEW` row in `ai/policy/roles.py`.
§22 now has nothing planned or staged.

**The defect is real here, and was measured before anything was written.**
`infrastructure/metrics.py:update_system_metrics` returns early when psutil is
unavailable, leaving the gauge unset — and an unset `Gauge` reads back its
default:

```
>>> m.PSUTIL_AVAILABLE = False
>>> reg.update_system_metrics()
>>> reg.get_collector("system_cpu_percent").get_value()
0.0
```

The same registry's `get_all_metrics()` reports `None` for that gauge, so its
two readers disagree about whether the machine is idle or unknown.

**The type refuses to express a fake value.** `Reading(value=None)` requires a
reason at construction; `Reading(value=12.0, reason=...)` is refused, because a
number and an excuse are two answers to one question. A genuine `0.0` stays
expressible — which is the part "return None everywhere" would have broken.

**"Cannot look" is not "there are none".** The GPU report separates them. A
dashboard showing 0 GPUs because pynvml is absent tells an operator their
inference is on CPU when it may not be.

**The neural-engine indicator is bound to three real facts** — which vendors
are reachable, which breakers are open, whether any call has succeeded — and
nothing else. §3 listed it as existing; it did not, and the tempting version is
a light that pulses whenever the page is open, which would say "thinking" on a
deployment with no credential configured.

**Two absences on the live endpoint are deliberate and annotated.**
`build_tool_bus()` constructs a fresh bus per caller, so there is no
process-wide audit trail to count — reporting a brand-new bus's empty audit as
"0 denials" would be this section's own defect, a reassuring number produced by
never having looked. It comes back unmeasured, with that reason.

**Runtime proof:** cpu 4.8%, memory 5.9%, disk 48.0% measured; gpu, awareness
and tool_denials each reported unmeasured with a reason; neural engine
`offline` because no provider is configured in this environment.

---

# Phase P — the AI present on every screen

**Owner request, 2026-09-07:** *"allow the AI hologram to be available and able
to appear in any screen in the app, including any dashboard... I should be able
to interact, diagnose the page, move around the page. The page should be able to
do anything in the page."*

Today the presence lives on the AI Core page. This makes it app-wide.

## It splits at the approval gate, and that split is not negotiable

`.claude/skills/flow-by-flow` is unambiguous: *"Every major UI/UX change
requires a `flow-prototype` review surface and explicit user approval before
production implementation. No post-hoc approval."* A presence overlay on every
screen in a money-moving platform is as major as UI changes get here — it sits
above the order ticket.

So:

**P1 — architecture. No visual change, no gate.  ✅ DONE**

Pure logic in `frontend/src/hub/`, the same shape as everything else there: it
decides what the presence knows and what it may do, and draws nothing.

- `pageContext.ts` — derived from `NAV_ITEMS`, the app's own source of truth for
  routes. An unknown route reports `known: false` **with the path**, because
  falling back to the nearest page would have the AI confidently describing a
  screen the operator is not looking at. `inspected` is a separate field from
  `problems`, so a page with no landmarks reported cannot be read as a healthy
  one — §22's rule applied to a page rather than to a gauge.
- `presenceDock.ts` — tries each corner and takes the first that collides with
  nothing the operator is using. When every corner collides it **reports the
  overlap** rather than quietly sitting on a form somebody is filling in. Never
  a keyboard trap (`trapsFocus` is a field, so a test can assert it). Dismissal
  survives navigation — a presence that returns on the next route change was
  delayed, not dismissed. Narrow viewports get an edge bar, the only arrangement
  that cannot cover content. Transform and opacity only.
- `pageCapabilities.ts` — two fields and deliberately no combined one. A write
  with no registered tool is listed as `unavailable` **with the reason**, not
  filtered out: "the AI cannot do this" and "this does not exist" are different
  answers to an operator asking why nothing happened.

23 tests. `presence.overlay` stays `planned` and carries no evidence, which is
the registry's way of holding P2 open rather than letting it be forgotten.

**P2 — the overlay itself. Behind the gate.  ← NEXT, needs your approval**

A `flow-prototype` approval surface first, showing the presence on a real page
in every state — idle, listening, thinking, speaking, alerting, dismissed, and
reduced-motion — then production implementation only after explicit approval.

This is the one thing in this plan I will not ship unasked. It is a floating
element above every screen in a platform that places trades, and the repo's own
rule is explicit that post-hoc approval does not count.

## The rule P1 must not violate

**Observing a page is not acting on it.** The presence may read any page it is
on and describe what it sees. Anything that *changes* the page — submitting a
form, cancelling an order, toggling a setting — goes through `ai/tools/bus.py`
and its two gates exactly as it does today, with an operator identity and a
risk tier. "The page should be able to do anything in the page" is the
capability; the gate is what makes it safe to have, and there is no version of
this where a presence overlay becomes a second way to place a trade.

`pageCapabilities.ts` therefore returns two lists that are never merged: what
can be read here, and what can be requested here. `ai/agent/loop.py` already
holds this exact distinction between `permitted` and `platform_context`, for
the same reason, and P1 mirrors it.

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

**D1 is done** (scene graph, workspace store, virtualisation, frame budget).
D2 covers the remaining §23 rows: schema-driven panels, a second layout
strategy, accessibility for generated panels, and the cognitive stream.

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

## Phase S2 — the code-walking agent, read-only  ✅ DONE

**Depends on:** S1. Building a proposer before its containment is backwards in
a system that moves money.

**Files:** `ai/improve/walker.py` (new), `ai/improve/finding.py` (new).

**What it is:** an agent that walks every module in the repository — `ai/`
included, which is the part the owner asked for by name — and emits
**findings**, not patches. A finding carries a file, a line, a claim, and
evidence that resolves; the registry's own discipline, applied to code review.

**Rules held:** it imports nothing that can write (parsed, not trusted: no
`write_text`, `unlink`, `rmtree`, `open()` anywhere in the package). It cannot
reach `ai/tools/bus.py` — the same AST assertion `ai/bus` carries. A snippet
that goes on to reach a model is fenced through `ai/guardrails/input.py`
first, because a comment in a file it read can carry an instruction.

**A parser, not a model.** Seventeen hundred files on a loop that is meant to
stay awake is a bill rather than a capability, and model findings would not be
reproducible run to run. The paid step moves to S3, per finding, behind the
vault and the approval gate rather than in front of them. Full-tree walk: 1,778
files in 7.5 seconds.

**Two false-positive classes found by running it and removed:** `dead_control`
is now dropped on a partial walk and the report names the drop, because a
caller in a directory the walk never entered is not an absent caller; and a
decorated function is never a dead control, because a route handler is reached
through its decorator and has no by-name caller anywhere.

**Reachable:** `platform_engineering.walk_code`, `ToolRisk.READ_ONLY`. A walker
nobody can invoke is a module, not an agent.

**What the first real run found** (reported, not fixed — both are on
vault-protected paths, so `proposable` is False and no patch may follow):

- `auth/router.py:1069` `validate_csrf_token` has no caller anywhere, and the
  comment above it says the middleware calls it. `core/middleware.py` has its
  own CSRF implementation with its own cookie name and its own exempt list.
  CSRF *is* enforced — this is a dead duplicate plus a wrong comment, and two
  exempt lists that can drift apart.
- `brokers/prop_firms/ftmo.py:386` `check_ftmo_compliance` is called only from
  `tests/unit/test_broker_connectors.py`. `prop_firm_mode.json` ships
  `enabled: true` with the FTMO ruleset.

---

## Phase S3 — a finding becomes a proposal, and a proposal needs two humans  ✅ DONE

**Depends on:** S1 and S2.

**Files:** `ai/improve/proposal.py` (new), wiring into
`security/ai_repair_sandbox.py` and `fixes:queue`.

**What it is:** `ai/improve/proposal.py` — five gates in order, then a
`pending` record on `fixes:queue` and nothing further. The gates: the finding's
evidence resolves; the vault, by path, before any content is read; the patch
changes something; it is under the 64KB ceiling; the disposable-directory
sandbox accepts it. A refusal names the gate that refused it — a proposal that
vanished looks, from the queue, exactly like one that was never made.

**Two things the plan got wrong, found by running the code.**

*"Signed queue entry → `SelfHealer` applies it" was not a real path.* Nothing
in this repository ever signs a patch entry: `_sign_patch` has no production
caller, and all three writers of `fixes:approved` push unsigned records.
Measured:

```
HEAL_PATCH_SIGNING_KEY set    -> _patch_entry_is_trusted(...) False   (no _sig)
unset, no dev opt-out         -> False                                (fail closed)
```

So auto-apply is **inert in every configuration**, and the live route for an
approved fix is a GitHub pull request a human merges. This phase did not turn
auto-apply on. Making an AI able to write Python to disk is not a step toward
"every advancement approved" — it is the thing approval exists to prevent.

*"The existing two-approver gate" did not cover this queue.*
`ai/policy/roles.py` declared that a repair needs two distinct approvers, at
least one a superadmin, and `api/safe_agent_platform.py:decide_approval`
enforced exactly that — on a different queue. `api/security/fixes.py:approve_fix`,
the gate an AI-authored patch actually passes, required a **single admin**. The
rule now lives in `ai/policy/roles.py:quorum` and both callers use it; the
first approval is recorded on the queued record and the second completes it.

**Rule held:** the AI's own modules are proposals like any other. `ai/improve/`
is deliberately outside the vault floor — the AI improving itself is the point
— and gets no shorter path: the same five gates and the same two humans.

**Also fixed, found on the way:** `test_returns_error_when_no_token` patched
the environment variable while `GITHUB_TOKEN` is read into a module constant at
import time. It passed only while it happened to be the first test to import
the module; any earlier importer left the ambient token in place and
`publish()` made a **real outbound request to the GitHub API** from the unit
suite. Reproduced on the pre-fix tree. It now patches the constant.

---

## Phase S4 — always awake, and honest about what it did not do  ✅ DONE

**Depends on:** S1–S3, and Phase A's bus for reporting.

**Files:** `ai/improve/cycle.py` (new), a startup factory, a registry row.

**What it is:** a continuous improvement cycle — walk, find, propose, report —
on a schedule, with a spend ceiling, a rate limit, and a kill switch that stops
it without a deploy.

**Bounded four ways, each with tests:**

1. **Off by default.** `AI_IMPROVE_CYCLE_HOURS` unset, empty, zero, negative,
   infinite or unparseable all mean off. A typo read as "run continuously" is
   the worst available reading of a mistake.
2. **A kill switch needing no deploy** — `redis-cli set
   hopefx:ai:improve:halted 1`. And an **unreadable** switch also stops it: the
   one place in this package where unavailable means refuse rather than report,
   because a loop that spends money and answers "no halt found" to a connection
   error has turned its kill switch into a suggestion.
3. **The shared budget ceiling first**, against the cycle's own operator so the
   spend is attributable and does not come out of a person's share. No headroom
   → skipped, and it says it was skipped.
4. **Three proposals per cycle, highest severity first.** The walk finds ~1,300
   things; filing them all turns a two-person review queue into noise, and a
   queue nobody reads is a queue nobody approves from. A finding on a
   vault-protected path is still reported and never reaches the generator —
   paying a model to write a patch that cannot be applied is money for nothing.

**The report is the deliverable.** `reason` is populated whether or not the
cycle ran, and every refusal is named with its evidence. Measured on a real
run: 1,782 files walked, 1,305 findings, 0 proposed, reason *"proposed nothing
because no patch generator is installed"*.

**No patch generator is wired.** The factory starts the schedule; wiring a
model to write patches unattended is a separate decision from turning the
schedule on, and it should be made separately. Until one is installed the cycle
walks and reports, and says that is what it did rather than reading as a clean
bill.

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
