# AI Hub — the remaining work, in the order it should be done

**Measured, not remembered.** Every number here comes from
`ai/hub/capabilities.py`'s own verifier (`python -c "from ai.hub.capabilities
import coverage; print(coverage())"`), which resolves each `live` claim by
importing the module or reading the file it names. A row is not built because
somebody said so.

At the time of writing: **230 capabilities · 223 live · 7 staged · 0 planned ·
230/230 evidence resolved · 0 discrepancies · 97% built.**

That live count went **down** by one, and the percentage with it. §4's four
layer roll-ups stopped being typed and started being derived, and the
derivation found `arch.layer_c.workforce` claiming `live` with two of its
eighty-two rows staged. A headline number that falls when you start measuring
it was wrong before, not now.

Sections finished (nothing planned or staged): §5, §6, §7, §8, §11, §12, §13,
§14, §15, §16, §17, §19, §20, §22, §23, §25, §27, and both owner tracks — P and S.

**7 rows remain**, across four sections. The owner asked for everything I had
called blocking to be built, and re-examining the list found I was **wrong
about four of the six** — I had labelled work I declined to do as
infrastructure that did not exist:

| § | Row | What I claimed | What is true |
|---|---|---|---|
| 24 | Isolated agent workers | "no process boundary this deployment has" | **Wrong.** stdlib. ✅ built |
| 21 | 3D and scientific models | "only canvas2d implemented" | **Wrong as a blocker** — a renderer is code |
| 10 | Multi-display console | "no second physical screen" | **Wrong as a blocker.** browser API. ✅ built |
| 18 | Pointing and object reference | "no landmark source" | **Half wrong** — the built half has no caller |
| 18 | Gesture recognition | "no landmark source" | True for the camera half; needs a new dependency |
| 26 | Runaway recursive delegation | "does not exist to bound" | Genuinely circular — the bound belongs at §24's boundary |

The remaining three are §4's roll-ups, which are now **derived** and move on
their own as the rows above them close.

Phase H covers all of them. §4's two rows are roll-ups and land last by
construction: they become live when the layers beneath them are, so claiming
either early would be claiming work that has not happened.

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

**P2 — the overlay itself.  ✅ DONE — approved by the owner, 2026-09-07**

`PresenceAnywhere.tsx`, mounted in `App.tsx` behind `isAuth`. It introduces **no
new visual language**: `PresenceCore` already draws the presence, `presenceDock`
already places a floating element, `pageContext` and `pageCapabilities` already
decide what it knows and may do. That is why a whole-app overlay could be added
without a redesign.

The state coverage map `flow-prototype` asks for lives in the test file rather
than a throwaway route — a route would have to be deleted afterwards and would
prove nothing durable. 35 tests: idle · page problems · expanded · alerting ·
dismissed · narrow-viewport bar · reduced motion · unknown page · no-capability
page · surface-unavailable · absent on the page that is already a presence.
`N/A: haptics` — a browser vibration API is a simulation, and this repository's
rule is never to claim native behaviour from one.

**Four defects the checklists found in my own work, all fixed:**

- A **second polite live region**. `PresenceCore` already owns one; mine
  announced on every navigation and spoke over it. A screen reader saying two
  things at once is one nobody leaves on.
- **No focus rings.** The browser default is close to invisible on a near-black
  panel. Named once as `FOCUS_RING` so a new button cannot be added without it.
- **22px hit areas.** The dismiss control was a 14px icon in `p-1` — half the
  44px minimum, on the button an operator reaches for when the assistant is in
  their way.
- **`text-slate-500` at 4.21:1**, below the 4.5:1 floor. Measured, not
  eyeballed; `slate-400` is 7.81:1.

**Two rules it holds that are not cosmetic.** Dismissal persists across
navigation *except* for an alerting presence — dismissing an assistant is not
consent to be uninformed about a kill switch, which is §19's critical floor
arriving in the UI. And a capability surface it could not load is reported as
unloaded, never as an empty one: "nothing here is exposed to me" and "I could
not find out" are different sentences, and only one is true when the request
500s.

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

## Phase D — §23 component architecture  ✅ DONE

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

**§23 has nothing planned or staged.** D1 built the scene graph, workspace
store, virtualisation and frame budget. D2 closed the rest:

- **`panelSchema.ts`** — a `SurfaceRequest` becomes a descriptor nobody
  hand-wrote, and one that **cannot exist without an accessible label**.
  `describePanel` throws on an empty intent rather than emitting an unlabelled
  panel, because a panel that renders is a panel somebody ships. Generated
  panels are exactly where accessibility dies quietly: a hand-built panel gets
  a label because somebody typed one; a generated one gets whatever the
  generator remembered.
- **An empty table is renderable; an empty chart is not.** "No open positions"
  is an answer. "No series" is a missing input, and an empty frame is
  indistinguishable from a loading state that never resolves.
- **`layoutStrategy.ts`** — the engine had seven layouts and one geometry.
  `grid` expresses importance as width, `stack` expresses the same ordering as
  sequence. It sits *on top of* `place()` rather than inside it, because 2,231
  tests depend on that function and rewriting it to gain one strategy would
  risk all of them. An unknown strategy is refused, not silently gridded.
- **`cognitiveStream.ts`** — §3 listed this as existing and it did not.
  They are two streams and merging them is a **leak**: the trace carries
  prompts, tool names and raw tool output; the explanation is a sentence for
  somebody deciding whether to trust an answer. `forOperator()` returns a shape
  the trace is not reachable from — returning the object and letting the caller
  pick fields puts the trace one property access away from a render. A step
  with nothing to say reports "Working.", never the trace.

**Also closes:** §8 surface types + priority tiers, §9 scene model + panel
registry, §21 representation selection, §10 multi-display console.

**Files:** `frontend/src/hub/sceneGraph.ts`, `workspaceStore.ts`,
`SurfaceView.tsx`, `layout.ts`.

**Rule:** the cognitive stream is what the AI tells the operator; the internal
trace is what it tells itself. Merging them either floods the operator with
tool-call noise or hides the reasoning. They are separate structures, and a
test asserts the user-facing stream contains no tool names or raw payloads.

---

## Phase E — §18 ambient awareness, behind §25's consent gate

§18's five rows are gesture recognition, pointing, attention-aware
interaction, camera and screen source selection, and local processing. Every
one is **continuous observation of the person using the platform**.

So E splits, and the order is not a preference:

### E1 — §25 privacy: one place that decides  ✅ DONE

`ai/privacy/consent.py`. Built before §18 for the same reason the vault was
built before the code walker: a containment that arrives after the thing it
contains is not a containment, it is an apology.

**What "gated" turned out to mean.** The registry said the camera was gated,
and it was — `Depends(_admin)` plus a rate limit. That is *authorisation*: it
answers "may this ROLE call this endpoint". It never asks whether the person in
front of the camera agreed to be looked at. Those are different questions and
the second one had nowhere to live.

**Default denied.** "Permitted until somebody objects" means the first frame is
taken before anyone was asked, and there is no way to un-take it.

**Unreadable means refuse** — the one inversion of this codebase's usual rule.
Everywhere else an unmeasured thing is *reported* as absent rather than guessed
at. Here the question is not "what is true" but "was I permitted", and a system
that cannot read its permissions and proceeds anyway does not have any. The same
inversion `ai/improve/cycle.py`'s kill switch makes.

**A session grant really expires.** One that outlives the session is a permanent
grant with a reassuring label — worse than an honest permanent one, because the
operator believes something false about it.

**Revocation is recorded, not erased.** "Never consented" and "consented and
withdrew it" are different facts, and an audit that cannot tell them apart is
not one. `revoke_all` is the control an operator reaches for when they want it
to stop now.

`vision_interpret` consults it **before the frame is decoded** — refusing
afterwards means the image was already in memory, which is exactly what the
panel's "frames stay in memory" promise is about.

### E2 — §18 itself  ✅ DONE (three live, two honestly staged)

**The judgement this phase turned on.** §18's five rows are not equally
buildable, and pretending otherwise is how a registry starts lying. Three are
achievable now, locally, with **no camera, no new dependency and no consent
conversation at all** — and those are the ones to build first, because the
cheapest way to respect somebody's privacy is not to need their permission.

- **`attention.ts`** — visibility, window focus, time since input. *Unknown is
  not away*: a state derived from inputs nobody supplied means "nobody looked",
  and reporting it as "the operator has left" would have the presence go quiet
  on somebody sitting right in front of it. A visible but *unfocused* window
  reads as away, because attention is on whatever is on top.
- **`visionSource.ts`** — the half worth getting right is that **a screen share
  and a webcam are different consents**. A webcam shows a face; a screen share
  shows the whole desktop and every other application. Treating them as one
  permission quietly widens what the system may see. "Not checked" is reported
  distinctly from "no camera" — only one is a fact.
- **`frameTriage.ts`** — this is a *privacy* row, not a performance one. The
  feasible local processing on a video stream is not running a model in the
  browser; it is noticing that most frames need never leave. Identical, blank
  and too-frequent frames are dropped **on the machine that captured them**.
  Every drop is counted with a reason, because "the AI saw nothing" and "we
  sent nothing" are different facts. `keptLocal` is the number worth reading.

**Also closes §7** (`presence.idle_attention`), whose note said "no attention
tracking yet". It breathes when present, settles when genuinely away, and keeps
breathing on *unknown* — going still there would look broken rather than
tactful on any browser that does not report visibility.

**Two rows stay staged, and the note names the missing half.** Camera gesture
recognition and physical pointing both need hand or body landmarks, and this
repository has no landmark source. The pointer halves are real and are built —
swipes and long press, and a hit test answering the topmost panel under a point
— but building a camera recogniser that nothing feeds would be
`hopefx-dead-controls` wearing a camera. `recogniseGesture` returns **null**
rather than the nearest gesture: on a trading screen a wrong swipe moves a
panel somebody was reading.

---

## Phase F — §17 real-time conversation  ✅ DONE

All six rows. `listening.ts`, `pronunciation.ts`, `voicePrefs.ts`.

**Three failure modes shaped the design.**

**A microphone that stays open.** Push-to-talk is open while held and shut the
instant it is not, and *every* way of losing the key closes it — release, a
hidden tab, a blur, dispose. The one path that does not is the one that leaves
a trading desk being recorded. `dispose()` is final: nothing reopens the
microphone afterwards, so a navigation cannot race a keypress. Continuous mode
and the wake word both hold the mic open, so both need consent, both are off by
default, and both stop **the instant** consent is withdrawn — a revocation that
waits for the next mode change is not a revocation.

**A transcript claiming words nobody said.** An interim result is a *guess*.
Recognition revises as it hears more — "sell", "sell gold", "sell gold now" —
and appending those builds a transcript of half-heard phrases attributed to the
operator. An interim replaces the previous interim, only a final result commits,
and an interim still pending when the mic closes is **dropped**: a half-heard
phrase left on screen reads as something that was said.

**Endpointing that fires on nothing.** Silence alone is not the end of a turn —
an open microphone in a quiet room would fire one every second. It endpoints
only after something was heard and then stopped, and commits the pending interim
rather than losing it with the turn it belonged to.

**Pronunciation is not cosmetic.** The presence speaks unprompted in exactly one
situation — an alert — and `XAUUSD` read letter by letter is unintelligible
precisely when the operator needs to hear it without looking. Whole tokens only,
because a naive replace turns `PIPELINE` into `point-in-percentageELINE`.

**Preferences are about the bounds, not the adjustment.** Both ends of the range
lose the one message that had to arrive: a rate of 10 turns an alert into noise,
0.05 turns it into something the operator mutes. A non-number falls back to the
*default* rather than a bound, because `NaN` through a comparison yields
whichever branch operator precedence reaches first.

**One real bug the tests found.** Arming a wake word did not open the
microphone, so it could never fire — a control that exists, reads correctly and
never runs. Arming now opens it, and the snapshot reports the open mic from the
moment it is armed rather than from the moment somebody speaks.

**Two evidence locators the verifier rejected**: `Listening.heard` and
`Listening.endpointed` are not literal strings in the file, so they were pointed
at `Listening` with the method named in the note.

---

## Phase G — §27 accessibility  ✅ DONE

All seven rows, plus two the specification does not name.

| Row | Was | Now | Evidence |
|---|---|---|---|
| Keyboard navigation | staged | **live** | `hub/useRovingFocus.ts:useRovingFocus` |
| Screen-reader semantics | staged | **live** | `hub/a11yLiveRegion.ts:LiveRegionRegistry` |
| Reduced motion mode | staged | **live** | `hub/a11yMotion.ts:motionFor` |
| Responsive layouts | staged | **live** | `hub/a11yBreakpoints.ts:breakpointFor` |
| Clear focus states | staged | **live** | `hub/a11yFocus.ts:FOCUS_RING` |
| High contrast option | planned | **staged** | `hub/a11yContrast.ts:prefersHighContrast` |
| Touch and mouse support | planned | **staged** | `hub/a11yPointer.ts:affordanceVisibility` |
| *Contrast computed, never asserted* | — | **live** | `hub/a11yContrast.ts:contrastRatio` |
| *The contract is enforced across the directory* | — | **live** | `test/hub_a11y_guard.test.ts` |

### The design premise: fixed once is not unrepeatable

Four accessibility defects were found in this session's own work, all of them by
reading a diff after the code was written: no focus ring on the presence
overlay, a 22px dismiss control, `text-slate-500` on a surface where it does not
clear 4.5:1, and a second polite live region competing with `PresenceCore`'s.

Each was fixed at its site. That fixes nothing about the *next* button, the next
muted grey, or the next component that wants to announce something — and reading
a diff is not a mechanism. So this phase is a contract plus a scanner:

* `a11yFocus.ts` holds the ring and the two hit-area floors, declared once;
* `a11yContrast.ts` computes ratios from the WCAG definition and re-measures the
  whole palette on every test run;
* `a11yLiveRegion.ts` grants each politeness level to one named owner;
* `a11yBreakpoints.ts` is the single definition of every viewport step;
* `a11yPointer.ts` and `a11yMotion.ts` hold the two policies that decide by
  input rather than by device;
* `hub_a11y_guard.test.ts` reads the whole directory and fails the five shapes.

### Every guard rule was verified by reintroducing its defect

Not by reading it. Each was put back into the tree and watched to fail:

| Defect reintroduced | Rule that caught it |
|---|---|
| a classed button with no ring and no hit area | *every classed button carries both* |
| a second `aria-live="polite"` | *one polite live region in the whole hub* |
| `const NARROW = 640` back in `layoutStrategy.ts` | *no other module holds a viewport literal* |
| `text-slate-500` on the overlay | *the refused colours stay refused* |
| a 22px shared icon-button style | *every pixel dimension a button receives clears the floor* |
| `focus()` removed from `useRovingFocus` | *moves the caret, not only the tab index* |

The hit-target rule is the one worth recording. Its first version read only the
`<button>` opening tag, passed, and was wrong: `SurfaceView`'s icon buttons take
their size from a `const iconBtn` at the top of the file, and every dimension in
the hub that could plausibly be too small is written that way. A rule that sees
only the inline case reports clean on exactly the files most likely to be at
fault — `hopefx-dead-controls`, in a test rather than in production. It now
follows the spread to the declaration.

### Two numbers, not one, for hit targets

`MIN_HIT_AREA_PX = 44` is WCAG 2.5.5 (AAA) and both platform HIGs; every control
in the presence chrome is held to it. `MIN_TARGET_PX = 24` is WCAG 2.5.8 (AA)
and is what the directory-wide rule enforces.

Two, because one 44px rule applied to every button in `hub/` would be a redesign
of the dense panel chrome — a 26px icon in a 34px panel header cannot become
44px without the header growing — and a rule that cannot be followed gets
suppressed rather than obeyed. 24 is what the standard requires at AA, and it is
the number that mattered: the dismiss control that shipped failed even this.

### Two rows are staged, and the notes say why

`high_contrast` has a palette where every token clears 7:1 on all three
composited surfaces, re-measured each run, and reads `prefers-contrast: more`
and `forced-colors: active`. **Nothing renders it.** `touch_and_mouse` has a
tested policy — an unreadable pointer is treated as unable to hover, so an
affordance stays visible rather than vanishing on a tablet — and **no component
calls it**, because the hub has no hover-only affordance today. Adding one to
justify the row would be backwards.

Both are contracts. Calling them live would be the F176 defect: a claim whose
evidence resolves and whose behaviour never runs.

### The default that is deliberately inverted

`motionFor` treats an *unread* reduced-motion preference as "reduce", not as
"no preference" — the opposite of §22's "an unmeasured metric is absent, never
zero". Same inversion as the consent gate and the kill switches: where being
wrong harms somebody, unreadable means refuse. `prefersHighContrast` defaults
the other way and says so, because the standard palette already clears AA and
nobody is harmed by not being upgraded.

### One duplication removed rather than documented

`640` was declared privately in `layout.ts`, `layoutStrategy.ts` and
`presenceDock.ts`. They agreed by copy-paste. Changing one would have produced a
viewport width at which the panel grid collapsed to a single column while the
presence overlay still floated above it instead of docking to the edge bar — a
layout nobody designed, reachable only on a device nobody tested.

---

## Phase H1 — §9's scene model, given a producer and a consumer  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §9 Scene model | staged | **live** | `hub/sceneFrom.ts:sceneFrom` |
| §9 Semantic panel registry | staged | **live** | `hub/resolveReference.ts:resolveReference` |
| §8 Priority tiers | staged | **live** | `hub/layout.ts:SPAN_BY_PRIORITY` |
| §8 Surface types | staged | staged | `hub/SurfaceView.tsx:RENDERERS` (note corrected) |

### Two rows were dead controls, and two were understated

The four rows shared a note shape — "the model exists and nothing populates
it". Measured against the tree rather than against the note, they turned out to
be two different problems in opposite directions.

**Genuinely dead.** `sceneGraph.ts`, built in Phase D1, was constructed in
**zero** production modules; `gestures.ts` imports the type. Every method on it
throws for an id nobody placed, so the whole spatial API answered every question
with an exception. Meanwhile `PresenceStage` was reading each panel's
`getBoundingClientRect()` once a frame, reducing it to which ninth of the screen
it sits in, and discarding the rectangle — the producer was already running and
throwing away exactly what the scene needed.

**Understated.** `workspace.priority_tiers` claimed nothing ranks by the tiers.
`layout.ts:place()` sizes every panel from its tier and collapses only the
background and on-demand ones, and `PresenceStage` calls it on every render —
proven by execution in Phase G's own test, which renders eight surfaces and
drives the collapsed stack the tiers produce. The evidence pointed at the Python
constant, which is the half of the contract with no ranker behind it.

`workspace.surface_types` claimed "none render yet". Twelve of the eighteen
declared kinds render, and six of §8's own twelve do: chart, image, video,
table, terminal, news. It stays **staged** — six of §8's list genuinely do not
render — with a note naming which six, because a note that hides finished work
is the same defect as one that claims unfinished work.

### The defect the consumer fixed

`workspace.resolve` matches a phrase against what a panel MEANS. It returns
null for "the one on the right", and that null went straight into
`workspace.focus(null)` — so asking for a panel by its position **unfocused
everything and said nothing about it**. The operator got no panel, no error and
no reason. Reproduced by execution first: the rendering test failed on the
pre-fix tree with focus cleared, then passed.

`resolveReference` refuses in four distinguishable ways, because the operator's
next move differs for each: nothing matched, two panels matched (candidates
named), a relative phrase with no anchor, and nothing in that direction. One
`null` for all four is the shape that makes an assistant say "I did not
understand" to somebody who was perfectly clear.

**A direction with nothing in it never wraps.** `RovingFocus` wraps, because a
keyboard list that stops dead reads as broken. A spatial reference is the
opposite: "the one on the left" wrapping to the far right of the plane moves a
panel the operator was not looking at.

### Containment is declared, never inferred

The obvious inference — a rectangle inside another is inside it — is wrong twice
here: grid panels never contain each other, and two panels transiently overlap
during a layout change. Inferring would report "the gold chart is inside the
order ticket" for one frame, and answering "inside what" correctly is the whole
point of the row.

### One thing the scene refuses to place

A rectangle with no area. `getBoundingClientRect` returns all zeros for an
element that has not been laid out, and `spatial.positionOf` already refuses to
call that "top left". Placed in a scene it sits at the origin, so it wins "the
panel on the far left" — and the AI points an operator at a panel that is not on
their screen.

---

## Phase H2 — §26, two deciders that nobody asked  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| Render large workspaces efficiently | planned | **live** | `hub/VirtualList.tsx:VirtualList` |
| Pause or reduce animation under load | planned | **live** | `hub/useFrameBudget.ts:useFrameBudget` |
| Graceful offline and degraded states | staged | **live** | `hooks/useWebSocket.ts` |
| Prevent runaway recursive delegation | staged | staged | `ai.agent.loop` |

### Both deciders existed, passed their unit tests, and were never called

`virtualization.ts:windowFor` and `frameBudget.ts:nextFidelity` were built in
Phase D1. Measured at the start of this phase, each was imported by exactly
zero components. That is `hopefx-dead-controls` in its most convincing form: a
correct function, a green test, and no caller — the tests pass whether or not
the product does the thing.

So the work was the two halves neither had. A **consumer** for the window, and
the two **readings** the load sample needed.

### Five thousand rows were five thousand nodes

`SurfaceView` mapped over every row and every headline. A surface carrying the
whole position book put the whole book in the document. `VirtualList` renders a
window above a declared threshold and gets out of the way below it —
virtualising ten rows costs a scroll container and breaks find-in-page to save
nothing.

A window is a lie by omission, so the real length is stated in words and in
`aria-rowcount`. §27's rule that colour is never the only indicator has the
same shape here: a scrollbar is not an indicator everybody has.

### The load reading is where F176 would have come back

`GET /api/ai-core/telemetry` already existed and the frontend never called it.
It returns host CPU as a §22 `Reading` — a value, a `measured` flag, a reason.
Reading `value` and skipping `measured` is precisely the defect §22 was written
about: `infrastructure/metrics.py` leaves the gauge unset when psutil is
missing, an unset gauge reads back 0.0, and the machine reports itself idle
because nobody looked. `readHostCpu` treats `measured` as the authority,
refuses a number that sits beside `measured: false`, and carries the reason
with the null so a held fidelity can be explained.

Frame time is a **median over a burst**, not the last frame. One garbage
collection would drag a mean past the 50ms threshold and step fidelity down for
a machine that is fine, and the next sample would send it back — a screen
oscillating between two appearances is worse than one consistently reduced. An
interval spanning a hidden tab is dropped outright: `requestAnimationFrame`
stops in the background, so the first frame back is seconds long.

And the sampler runs in bursts with a rest between them. A frame-timing loop
that runs forever is itself a cost, paid on exactly the loaded machine it is
meant to help.

### Degrading silently is the failure, not degrading

Anything below full fidelity stops the presence canvas **and** names the level
on screen, with the measured cause in its title. A plane that quietly gets less
animated teaches an operator that the app is just slow today, and then the
indicator that is meant to warn them is one they have learned to ignore.

That, with the stale feed `useWebSocket` already detects and the offline
presence `PresenceCore` already draws as a dead ring plus the word "Offline",
is three degraded states each named in words — which is what moved
`degraded_states` to live.

### One row stays staged, and the note was already right

`perf.no_runaway_delegation`: the agent loop is bounded, and recursive
delegation does not exist to bound. Grepped again this phase — no `delegate`,
no spawn path in `ai/agent/loop.py`. Building a limiter for a mechanism nobody
has written is a control that can never fire.

---

## Phase H3 — §11's last three agents  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| System agent | planned | **live** | `ai.departments.system_ops` |
| Vision agent | staged | **live** | `ai.departments.vision_ops` |
| Memory agent | staged | **live** | `ai.departments.memory_ops` |

§11 is closed. Both staged rows carried the same note shape — the capability
exists, "it is not yet an agent on the bus" — and Cluster B had already
established what an agent is here: a department in one table that drives the
directory, the permission registry and the bus registration together.

### Every action is READ_ONLY, and two of the refusals are the point

Cluster B's docstring already says it for voice and notification. Cluster C
turns on two sharper versions:

**The vision agent can be shown a picture and cannot go and take one.** A
camera opened mid-loop, by a model deciding a look would help, is a camera
opened on a trading desk by something nobody instructed. `describe_image` takes
the images as an argument, checks §25 consent **before** the pixels are read,
and has no path to a capture API at all. Both are asserted by parsing the
module, because a file that explains what it must not do contains the words it
must not call — the same technique `ai/bus/` and `ai/improve/` use.

**The memory agent reads and may not forget.** §16's right to be forgotten is
the operator's. An agent holding it is a memory hole with a permission tier: a
model deciding mid-loop that some history is no longer relevant, erasing it, and
leaving the person whose history it was with no way to know. `correct` is out
for the same reason plus one more — an agent that can edit a memory can edit
the memory of what it was told, and then the audit trail and the thing being
audited share a writer. `describe_retention` names the route to erasure and
does not take it.

Both guards were verified by reintroducing the defect: a `cv2.VideoCapture` in
the vision module and a `governance.forget` in the memory one. Three tests
failed, including the behavioural one that noticed the memory was actually
gone.

### The system agent passes readings through rather than summarising them

`ai/telemetry/` was built for §22 and served by an endpoint a dashboard polls.
What was missing was something `ai/agent/loop.py` could ask. The temptation
when wiring that is to flatten: `{"cpu": 7.0}` reads better and is exactly the
defect §22 exists about — `infrastructure/metrics.py` leaves the gauge unset
when psutil is missing, an unset gauge reads back 0.0, and the machine reports
itself idle. Every reading keeps its `measured` flag, and `unmeasured` is its
own key so a caller never infers absence by scanning for nulls.

There is no restart, scale, clear-cache or kill. Not because they are hard: a
struggling machine is precisely when an agent acting on its own initiative does
the most damage, and this one is reachable from a model's tool loop.

### Two existing tests fired, and both were right

`test_all_four_cluster_a_departments_are_declared` asserts the *full* set of
departments, so three new ones failed it. That is the rule working — the set
cannot grow quietly — and the fix was a human adding Cluster C to it.

`test_every_department_has_at_least_one_watcher` caught that all three declared
`awareness` triggers with nothing watching for them. Three real watchers were
written rather than the declarations dropped: host pressure (only a reading
that exists and is high fires — an unmeasured CPU is not a busy one), camera
consent withheld (`info`, because consent withheld is the gate working rather
than a fault), and memory not durable (tri-state, because "could not read the
backend" and "not durable" are different answers).

### A pre-existing inconsistency this phase found and did not widen into

Writing the stronger version of that test — *every declared trigger* has a
watcher, not one per department — surfaced that `awareness` means two things.
Cluster A declares prose ("broker disconnect detection"); Clusters B and C
declare trigger names ("feed_stale"). `Department.as_dict()` puts both on the
wire, so normalising Cluster A would change text an operator reads.

Out of scope for a phase about three new agents. Recorded in the tree instead:
`PROSE_AWARENESS` names the four departments, with the reason, and a second
test asserts the list is **exactly** the departments that still need it — so
closing the inconsistency means shrinking it, and leaving it stale fails.

---

## Phase H4 — the three rows my own notes said nothing consumed  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §27 High contrast option | staged | **live** | `hub/useContrastMode.ts:useContrastMode` |
| §27 Touch and mouse support | staged | **live** | `hub/SurfaceView.tsx:affordanceVisibility` |
| §8 Surface types | staged | **live** | `hub/SurfaceView.tsx:RENDERED_KINDS` |

Two of these were staged in Phase G with notes I wrote in capitals — "NOTHING
RENDERS IT YET", "NO COMPONENT CALLS IT YET". Refusing to claim them was right:
a contract whose evidence resolves and whose behaviour never runs is F176 with a
passing test. But a refusal recorded twice and never acted on is a slower
version of the same omission.

### §8 was never a missing renderer

Six of §8's twelve kinds did not draw, and the obvious reading was that six
renderers were missing. Measured, the blocker was one branch: `surfaceData`'s
`default` **discarded caller-supplied data entirely**, so an AI opening a
document surface *with the document in it* got "nothing is connected to a
document surface yet". The panel was real, the content had arrived, and the
screen said neither had happened.

Content is now passed through with **every shape checked** — `data` reaches
there from a model, and a string where rows belong would meet a renderer that
maps over it, taking the whole plane down from inside one panel.

`camera` draws its **consent state** rather than "this deployment cannot draw a
camera": §25 already knew the answer, and the panel was describing a missing
renderer instead of it. It never opens a stream — a panel that requested the
camera because it was rendered would make *opening a panel* the consent.

`map` and `simulation` stay unrendered, and `UNRENDERED_KINDS` asserts it so the
set cannot drift. There is no tile source and no simulator, and a map drawn from
nothing is read as a map.

### High contrast reaches every leaf, or it reaches none

The panel publishes the mode's palette as CSS custom properties. The
alternative was threading a palette through `Rows`, `Headlines`, `Prose`,
`Code` and six more — which works until somebody adds the eleventh and forgets,
and then one element stays at standard contrast in high-contrast mode and
nothing says so.

**The first version of the test passed while the feature was broken.** It
asserted `data-contrast="high"` on the panel, which proves the media query was
read and nothing else: pinning the palette to `standard` while still reporting
"high" passed it. Found by injecting exactly that defect. The test now asserts
the rendered custom properties carry the high tokens — measured, not told,
which is the distinction the whole registry is built on.

### The touch defect was the readout, not the tooltip

First attempt drew each heatmap cell's label inside the cell. Two things
killed it, and both are worth recording:

* the labels are prose ("0.8% peak move"), which does not fit a 26px mark and
  duplicated the readout that already sits below the grid;
* **no single ink clears 4.5:1 across the intensity ramp** — white measures
  8.10 on the darkest step and 1.79 on the lightest, and the dark ink is the
  reverse. A per-step ink function was written and measured, then deleted with
  the label it served, because an exported measured function nobody calls is
  the dead control this phase exists to remove.

The actual defect was simpler and worse: the readout is opened by `mouseenter`
or keyboard focus. `mouseenter` does not fire on touch, and iOS Safari does not
reliably focus a button on tap — so the accessible twin this file already
shipped was reachable by mouse and by keyboard and **by nothing a tablet
operator could do**. A tap now opens it.

The affordance still starts at `unknown`, which counts as unable to hover.
Guessing mouse is how a hover-only affordance ships: the guess is invisible and
the people it fails are the ones least able to work round it. A separate test
asserts the state **before any pointer event**, because all three of the others
fire one first and every one of them passed with the guess in place.

---

## Phase H5 — the war room, and choosing what to draw  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §20 Market war room generated on demand | planned | **live** | `hub/warRoom.ts:warRoomSurfaces` |
| §21 Choose the representation that suits the information | staged | **live** | `hub/representation.ts:representationFor` |

### The war room was a layout pretending to be a feature

`war_room` has existed since Phase 2.1 — `readLayout('war room')` returns it,
`suggestLayout` reaches for it at eight surfaces. So the phrase **rearranged**
whatever happened to be on the plane, and on an empty plane it rearranged
nothing and read as a broken command. §20 asks for one to be *generated*.

The obvious implementation opens all nine candidates. On a deployment with no
news feed and a flat book that is six panels reading "nothing is connected to
this yet" — a war room that looks like a dead platform, which is worse than not
opening one. So the set is filtered by what actually has data.

Silently dropping the empty ones has its own failure, though: an operator who
expected a news panel and does not see one cannot tell whether the feed is
silent or the war room forgot. So `omitted` names them and the panel says the
sentence aloud.

**Risk is declared `critical`, and that is load-bearing.** `layout.ts` folds
`background` and `on_demand` into the collapsed stack once the plane is
crowded, and a war room is crowded by definition. Risk turning into a chip at
exactly the moment somebody opened a war room is the one collapse that must not
happen.

### The representation row was not waiting for a model

The staged note said "a model does not choose it yet", which framed the row as
blocked on a model call. That framing was mine and it was wrong.

A numeric series is a chart. Pairs are a table. Timestamped events are a
timeline. Nodes with edges are a network. Those follow from the **shape of what
arrived**, and deciding them locally is better than deciding them in a model:
instant, free, deterministic, testable, and still working when every vendor is
unreachable. `intent.ts` already makes exactly this argument — *"this is the
reflex, the model is the thought"* — and it applies with more force to a
question whose answer is already in the data. The model is not cut out; it is
the fallback for what this cannot decide, which is what `null` means.

Two refusals worth recording. A **one-point series** returns null rather than a
chart: a line between one point is a dot, `surfaceData` already refuses to
chart a single price, and a chooser that reinstated it would undo a decision
made for a reason. And when two shapes are present the **richer** one wins —
cells with rows is a heatmap plus its accessible twin, not a table that happens
to carry cells.

### Both wirings verified by reverting them

Turning off the war-room assembly failed all four plane tests. Making the
assembly open every candidate regardless of data failed five, including the two
that check it says what it left out.

### §21's other row stays staged, honestly

`viz.scientific_3d`: the presence already takes schematic scientific forms and
the renderer abstraction names WebGL, WebXR and holographic output — but only
canvas2d is implemented, and `availableRenderers()` says so rather than
implying otherwise. Claiming it would be claiming three renderers that do not
exist.

---

## Phase H6 — a job that outlives the process that ran it  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §14 Long-running research jobs | staged | **live** | `ai.jobs.store:RedisJobStore` |
| §24 Isolated agent workers with task contracts | staged | staged | note sharpened |

The scheduling half landed in Phase B — any deadline at `background` priority,
an ageing queue so neither tier starves the other — and its note was honest
about what was left: `JobRunner` holds jobs in an in-process dict, so an
hour-long research job dies with the process and its result is not recoverable.

The precedent is `ai/gateway/budget_store.py`, and it is the same lesson twice.
Spend lived in a module global; every restart reset the month to zero, and at
`API_WORKERS=4` each worker kept its own dict, so the ceiling in the settings
form silently meant four times what it said.

### A job that was RUNNING did not survive, and must not claim to

Its thread is gone. Bringing it back as `running` is the worst available
answer: a job that says running for ever is one nobody can act on, and the
screen spins against a worker that does not exist. Every non-terminal state
recovers as `interrupted`, which is terminal and carries a reason.

`queued` lands there too, for a different reason. Nothing was lost — it never
started — but nothing is going to start it either, and leaving it queued
promises a worker that is not coming.

### The store is never the source of truth for a live job

It is written after each transition, so it is behind by design. `recover`
prefers what this process is actually running and consults the store only for
jobs it has never heard of.

**The first version of that test passed while the de-duplication was broken.**
Removing the "already live" check makes the operator see the job *twice* — once
succeeded from memory, once interrupted from the store — and the test found the
live one first and passed. Caught by injecting exactly that defect; it now
asserts the id appears exactly once.

### The operator is the key, not a filter

`ai/jobs/runner.py` is where a P0 leak was found: one operator's prompt and the
model's answer could reach another's screen, because the scoping was applied at
the read and anything that forgot it leaked everything. A record is stored
under its operator, so a recovery that forgets the operator addresses nothing
rather than addressing everybody. Verified by making the in-memory store read
across operators — one test failed, and it was the right one.

### Failing to record must never fail the work

A durability layer that failed a job it was only supposed to *write down* would
be worse than having none: the operator loses the answer **and** the record of
having asked. Every store failure is logged and swallowed, on both the write
and the read.

And with no Redis the runner reports `durable = False` with the reason, rather
than losing work quietly — the same choice `build_from_env` already makes for
the budget counter, ping included, so a store that cannot be reached declines
to install instead of installing and failing on every job.

### §24 stays staged, and its note now says why

The old note — "a bounded pool exists; isolated workers do not" — was true and
too vague to act on. The contract half is real and now durable: a job carries
an operator, a prompt, a priority tier, a timeout and a deadline, is admitted
through a bounded queue, and its outcome survives the process.

The isolation half is not, and no amount of code in this repository creates it.
`ThreadPoolExecutor` gives threads in one interpreter — agent work shares a
heap, a GIL, an import table and a filesystem with the API serving the screen,
so one runaway agent can starve or crash the process it runs in. That needs a
process or container boundary this deployment does not have, and claiming the
row would be claiming a blast radius that does not exist.

---

## Phase H7 — the roll-ups stop being claims  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §4 Presence layer | planned | **staged** (derived) | `ai.hub.capabilities:layer_state` |
| §4 Environment layer | planned | **staged** (derived) | `ai.hub.capabilities:layer_state` |
| §4 Intelligence layer | live (typed) | **live** (derived) | `ai.hub.capabilities:layer_state` |
| §4 Workforce layer | live (typed) | **staged** (derived) | `ai.hub.capabilities:layer_state` |
| §10 Multi-display console | staged | staged | note corrected |

### Keeping them last was a scheduling answer to a structural problem

The plan said §4's roll-ups land last "so they cannot be claimed early". That
works exactly as long as somebody remembers. A roll-up whose state is **typed**
is a claim about other claims with nothing measuring it — F176 one level up:
`scripts/invariant_coverage.py` certified components by counting hand-typed
`True` literals, so it could not print anything except full coverage while
three of them were provably unprotected.

Every capability already carried its layer. Nothing was reading it.

### What the derivation found

`arch.layer_c.workforce` was **live with two of its eighty-two rows staged**.
Written by hand, in good faith, by somebody who had just finished four of its
departments — which is how every one of these gets written.

Deriving it costs a live row and a percentage point. That is the correct
direction, and it is worth saying plainly: **a headline number that goes down
when you start measuring it was wrong before, not now.**

`planned` fell to zero at the same time, because the two remaining planned rows
were these roll-ups and their layers have plenty of live rows in them. Nothing
was completed to make that happen; a wrong state became a right one.

### A roll-up names what is outstanding

`Derived: 80 of 82 rows in layer C are live. Outstanding — stack.agent_runtime,
perf.no_runaway_delegation.` A roll-up reporting `staged` with no list is a
number somebody has to go and investigate, and an uninvestigated number is how
a stale claim survives — which is exactly how `agents.system` sat live on
another agent's module for as long as it did.

A layer with nothing started reports `planned`, not `staged`: a roll-up over
nothing begun must not read as partly done. No layer is in that state today,
which is why the rule is tested against injected rows rather than against the
registry.

### §10's note described what exists and never what was missing

"Six live sources with degraded-source tracking." Counted: **nine**. And the
sentence never said what was absent, which is the one note shape this registry
forbids — a note listing what exists reads as complete.

What is missing is the display half. "Multi-display" means spanning more than
one physical screen, and nothing calls `getScreenDetails` or places a window on
a second monitor. It is one console with nine sources, which is a different
claim. `docs/ai/AI_HUB_DECISIONS.md` carried the same stale "six" and the same
wrong word, and was corrected with it.

---

## Phase I1 — §24, the row I was wrong about  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §24 Isolated agent workers with task contracts | staged | **live** | `ai.jobs.isolation:run_isolated` |

I wrote the note that said this needed "a process or container boundary this
deployment does not have". `multiprocessing` with `spawn` and
`resource.setrlimit` are standard library. The boundary was **code nobody had
written**, and I had filed it as infrastructure nobody had bought — which is a
more comfortable sentence and a less true one.

### Why a task contract, and not simply a process pool

`JobRunner.submit` takes a closure, and a closure captures whatever the caller
had in scope. It is not picklable, so no amount of `ProcessPoolExecutor` makes
an arbitrary job isolated. The honest unit is a task that NAMES an importable
function and picklable arguments — which is what §24's phrase "task contracts"
has to mean if it means anything. The probes for the tests live in an
importable module for the same reason: a test that could pass with a lambda
would be testing something this design refuses.

Every refusal happens at construction, in the caller's process. A contract that
cannot be honoured must not become a mysterious dead child three layers away.

### One process per task, and spawn rather than fork

A pool cannot kill a running task — `Future.cancel` refuses once work has
started, and the only lever is shutting the pool down and taking every other
task with it. Isolated tasks are the rare heavy ones, so one process each buys
the `terminate()` that makes a timeout real instead of advisory.

`fork` copies the address space and exactly one thread. This process has
several — the job pool, the event loop — so a lock held by any other thread at
the moment of the fork is held for ever in the child: a deadlock that
reproduces once a week and never in a test.

### What the boundary buys, asserted against a real child

* `os._exit` — what a segfaulting native extension looks like — does not take
  the parent with it;
* `RLIMIT_AS` stops a 4GB allocation rather than the machine's limits;
* a spinning task is terminated and **verified gone by pid**, not merely
  abandoned to keep a core busy for the life of the deployment.

### One injected defect did not apply, and I nearly believed it

Removing `terminate()` appeared to leave every test passing. The injection had
silently not matched after a reformat. Checking the file rather than trusting
the run showed it, and with the removal actually applied the termination test
fails as it should. A defect injection that does not apply is a passing test
that proves nothing — the same shape as the control this whole phase is about.

### Isolation is opt-in

Every existing job still runs on the thread pool, and a test asserts it. On a
money-moving platform, silently moving live trading work across a process
boundary to close a registry row would change the failure modes of the thing
the row describes.

---

## Phase I2 — §10, the second screen I said we did not have  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §10 Multi-display console | staged | **live** | `hub/displays.ts:readDisplays` |

The note said this needed "a second physical screen this deployment does not
have". The Window Management API is a browser API. Not owning a monitor makes
the hardware path unverifiable; it does not make the code unwritable, and I had
used the first fact to excuse the second.

### Three states, because two of them look like the third

`unsupported` (no API), `unpermitted` (not granted), `measured` (real, and one
screen is a real answer). Collapsing them into "no extra screens" is §22's rule
broken in a new place — an unmeasured display count is **absent, never zero**.
An operator on a three-monitor desk told they have one screen goes looking for
a fault in their hardware, which is worse than being told the browser cannot
see them.

### Rendering never asks for permission

`getScreenDetails()` prompts. Calling it because a component mounted makes
*opening the app* the request — the same mistake the camera panel made before
§25, and a prompt nobody asked for is one people learn to dismiss, after which
the prompt they meant to accept is dismissed too. The automatic read is a
probe; only `request()` can prompt.

Both of those were verified by injecting them: treating the unsupported case as
one screen fails the state test, and removing the probe branch fails the
no-prompt test.

### Risk does not move to a monitor nobody is watching

When the plane spreads, critical and primary surfaces stay on the primary
screen. Same reasoning that made risk `critical` in the war room so a crowded
plane could not fold it into a chip.

The secondary split is round-robin rather than by area or by guessing where
somebody is looking. Both of those would be inventions; an even split is at
least a rule an operator can predict.

### What is proven, and what is not

**Automated (PASS):** 15 tests over the state machine, the degradations, the
malformed-answer and zero-area cases, and the placement rules.
**Runtime (UNVERIFIED):** placement across real monitors. This container has
one screen and no Window Management permission, so the hardware path has never
executed. The registry note says so rather than implying otherwise.

---

## Phase I3 — §18's built halves, given the callers they never had  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §18 Pointer gestures move the plane | *(new)* | **live** | `test/hub_pointer_input.test.tsx` |
| §18 What the operator is pointing at | *(new)* | **live** | `hub/PresenceStage.tsx:pointingAt` |
| §18 Gesture recognition | staged | staged | camera half named |
| §18 Pointing and object reference | staged | staged | camera half named |

`recogniseGesture` and `pointingAt` were written in Phase E2 and, measured now,
were imported by **nothing outside their own tests**. That is
`hopefx-dead-controls` — and it is mine: I wrote the module docstring
explaining why building a recogniser nothing feeds would be a dead control, and
then built one anyway on the input side.

`pointingAt` could not have been wired when it was written. The scene graph had
no producer until `sceneFrom` landed in `PresenceStage` in Phase H1. It has one
now.

### The naming question, settled before building

Wiring pointer input does **not** make `vision.gesture` and `vision.pointing`
live. Every other row in §18 is camera-derived — scene understanding, capture
indication, frame retention, source selection — and `vision.` means vision. A
pointer swipe is not vision. Marking those rows live because pointer input
works would be renaming the capability to fit what was built, which is exactly
how `agents.system` came to point at `platform_engineering` and §11 came to
report twelve agents with eleven present.

So the pointer work gets **its own two rows**, and the two `vision.` rows stay
staged with only the camera half named in the note. Their notes now say what is
built and wired, and point at the new ids, so a reader cannot mistake "staged"
for "nothing here works".

The camera halves need a hand/body landmark model this repository does not
carry. **Adding one is a supply-chain decision for the owner, not mine to make
unilaterally** — it is the one thing in this phase I am not deciding.

### Only reversible actions are bound

`gestures.ts` says in its own docstring that on a trading screen a wrongly
recognised swipe moves a panel somebody was reading. The answer is that no
gesture removes anything:

* **swipe** → moves FOCUS to the measured neighbour. Reversible, and already
  reachable by clicking.
* **long press** → PINS, which is a toggle with a button beside it.

Nothing closes a panel, leaves the plane, or touches an order. A
source-scanning test asserts the `onGesture` block contains neither
`onCloseSurface` nor `onExit`, so a later edit cannot add one quietly.

**It never wraps.** `resolveReference` holds the same rule: a reference that
wrapped would move an operator's attention to the far side of the plane, which
is the opposite of what they asked for.

### Three defects the wiring exposed, all mine

**The scene graph was built only for callers who asked about it.** The measure
effect returned early unless an `onPositions` or `onScene` callback was
supplied, so `sceneRef` was null on every standalone mount. Invisible while
nothing hit-tested against it. It now always measures.

**The track had no bound.** A pointer held down emits a move event per frame,
so appending on every one is a user-driven allocation with no ceiling — on the
heaviest screen this app draws. Worse, `recogniseGesture` reads only the first
point and the last, so every point in between was being kept for nothing. The
ceiling now lives in `appendPoint`, next to the recogniser that defines what is
actually read.

The interesting part is *which* point gets dropped. A ring buffer dropping the
OLDEST is what a reviewer reaches for first, and it is wrong here: the first
point is what a swipe is measured from and what `pointingAt` hit-tests, so
dropping it silently changes which panel a gesture meant. Injected, it does not
merely degrade — recognition fails outright.

**The plane had two notions of focus at once.** The focus ring followed the
gesture while `place()` went on reading the raw prop, so a focus layout kept
enlarging the panel the operator had selected while outlining the one they had
just swiped to. `shownFocus` now feeds the layout as well, and it is declared
above the placement memo so nothing downstream can reach past it.

### What is proven

**Automated (PASS):** 9 tests, and the whole frontend suite at 2,537. Proven by
four injections, each grepped to confirm it applied before the run was trusted
(the Phase I1 lesson, where an injection silently failed to apply and I nearly
concluded the code under test did not matter):

| Injection | Result |
|---|---|
| Unwire `onPointerUp` | all 3 behavioural tests fail, on assertions |
| Make the swipe wrap at the edge | exactly 1 fails — the no-wrap test |
| Remove the track bound | the cap test fails |
| Drop the oldest point, not the newest | cap test *and* recognition both fail |

The first version of the no-wrap test failed on a null `querySelector` rather
than an assertion, which is a test dying rather than a test proving. It now
asserts focus after every step. The first version of the layout test leaned on
a helper that did not exist; it now reads the rendered `gridColumn` spans, so
it asks the layout what it did rather than what it was told.

**Runtime (UNVERIFIED):** a real finger on a real touchscreen. jsdom fires
synthetic pointer events; it does not prove a trackpad or a panel of glass
behaves the same.

---

## Phase I4 — §26, the bound that had nothing to bound  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §26 Prevent runaway recursive delegation | staged | **live** | `ai.jobs.lineage:DelegationLedger` |
| §24 Isolated agent workers | live *(no caller)* | **live** | `JobRunner.submit_isolated` |
| §4 Workforce layer | staged | **live** | derived |

The note said "recursive delegation does not exist yet to bound". True, and
circular: nothing delegated, so there was nothing to bound, so the row stayed
staged for as long as it stayed staged. Phase I1's worker boundary gave it
somewhere to live.

### Three bounds, because there are three failure modes

Depth is the bound people reach for and it catches one of these:

| Failure mode | What it looks like | Caught by |
|---|---|---|
| depth | A delegates to B delegates to C, for ever | `max_depth` |
| fan-out | one node delegates to 500 children, all at depth 1 | `max_fanout` |
| total descendants | depth 4 by fan-out 8 — 4,680 nodes, neither bound exceeded | `max_descendants` |

Each of the three tests satisfies the **other two** bounds comfortably. That is
the only way to show a bound is doing work rather than riding behind a stricter
neighbour, and the first version of the depth test failed because it did not:
a flat grant of 50 per level exhausted the descendants budget at depth 2, so
the depth bound went untested. The test said so by failing.

### The bound is enforced where the child is CREATED

`TaskGraph.add()` already makes this argument for cycles: creation is the last
moment at which nothing has happened yet. Afterwards the model call is paid for,
and a bound that notices then is a bound that reports.

### A refusal is local, and is never silent

Refusing the child, not failing the tree — the work already done was paid for,
and discarding it wastes exactly the spend the bound protects. But every refusal
is recorded with the bound that caused it, because a quietly dropped child is a
plan that ran differently from the plan that was written.

### Fail-closed: an unknown parent is refused, not adopted

The whole security of the thing. A node presenting a parent this ledger has no
record of — a bug, a replay, a child restarting the count at zero — would, if
admitted as a fresh root, receive a **whole new budget**. `open_root()` is the
only way a tree begins, and `run_isolated` refuses a contract whose lineage its
process cannot vouch for.

### Across a process boundary, a grant travels instead of the ledger

A ledger is per-process; a child's is empty. So the child is handed a `grant` —
what it may spend beneath itself, in total — and seeds its ledger with exactly
that. The parent is charged `1 + grant`, in full, because that is the worst case
the child may spend; charging only for the child would let two siblings each be
handed the remaining budget and each spend it. The default grant is **zero**, so
delegation does not propagate unless somebody said so in the call that created
the child.

### A correction to Phase I1

`run_isolated` was imported by **nothing outside its own tests**, and I marked
`stack.agent_runtime` live anyway. That is `hopefx-dead-controls` inside the work
that closed a row about isolation — two commits after I wrote the Phase I3 note
about finding exactly this in my own work.

**The registry cannot catch this class.** `verify()` resolves an evidence
locator; it has no opinion about whether anything imports it. That is a real
limit of the anti-omission mechanism and it should be written down rather than
discovered again. `JobRunner.submit_isolated` is the caller now.

### What is proven

**Automated (PASS):** 21 tests, including four that run a **real child process**
and assert what it managed to delegate. Seven injections, each grepped to
confirm it applied:

| Injection | Result |
|---|---|
| No depth check | depth test + refusal-record test fail |
| No fan-out check | 4 tests fail, including the concurrency one |
| Charge 1 instead of 1+grant | both descendants tests fail |
| Unknown parent becomes a root | the fail-closed test fails |
| Remove the lock | **passed — twice.** See below |
| Lineage does not cross the boundary | the child admits 0 instead of 3 |
| Child adopts a full budget, not its grant | the child admits 8 instead of 3 and 0 |

**The lock injection is the one worth reading.** Two versions of the concurrency
test passed with the lock removed, which makes them tests of nothing: `admit`
runs so few bytecodes between reading `children` and incrementing it that
sixteen threads never landed in the window, even with the switch interval at a
microsecond. The third version widens the window where the race actually is — a
bounds stand-in that releases the GIL inside the fan-out *check* — and with it
the unlocked ledger admits 15 children against a limit of 8.

**Runtime (UNVERIFIED):** a delegation tree under real production load. Nothing
in the app delegates yet; `submit_isolated` is the path, and the first caller
that uses it will be the first time these bounds see traffic.

**Assurance:** self-reviewed, lower assurance — no independent reviewer ran on
this, and the risk floor (spend control, fail-closed invariant) would normally
call for one.

---

## Phase I5 — §18's camera half, and the question I was asked to settle  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §18 Landmark adapter | *(new)* | **live** | `test/hub_landmarks.test.ts` |
| §18 Gesture recognition | staged | staged | one missing thing, named |
| §18 Pointing and object reference | staged | staged | one missing thing, named |

The owner's answer to the supply-chain question was: **if shipping it does not
spoil things, ship it.** So it needed an actual answer rather than another
deferral.

### The answer: shipping the model would spoil something, and not the dependency

I checked. npm is reachable and `@mediapipe/tasks-vision` is one install away,
so "supply chain" was never the real obstacle and it would have been a
comfortable excuse.

The real obstacle is that **there is no camera in the environment this was built
in.** Installing a 2MB runtime and an 8MB model into a platform that moves money
and never executing it once is committing code on faith. "Prove by execution,
not by reading" is the rule that forbids exactly that, and it is not a rule to
suspend because a row is close to closing. Nine of the defects found in this
repository read as correct.

### So everything except the model shipped

The gap is now one line of deployment configuration wide. What is built and
proven against synthetic landmarks:

* **A hand is a SOURCE, not a second pipeline.** `trackFromHands` produces the
  same `TrackPoint[]` that `recogniseGesture` has read since Phase E2 and that
  Phase I3 wired. A parallel camera pipeline would give the console two ways to
  decide what a swipe is, and they would eventually disagree.
* **Four states, because three of them are not "off":** `unconfigured` (no model
  deployed), `unsupported` (deployed, browser cannot run it), `unpermitted`
  (could run, no consent), `measured`. An operator whose camera gesture does
  nothing needs to know which — "not working" sends them hunting a fault that is
  not there.
* **A model comes from this origin or not at all.** The vendor's documented
  `storage.googleapis.com` URL is refused. Shipping it would have a trading
  console fetch from a third party on the operator's behalf: a runtime
  dependency on a host nobody here controls, and a signal to that host every
  time this desk opens its console.
* **Mirrored**, because a front camera shows a reflection; following the raw
  coordinate moves focus the opposite way from the gesture.
* **A partial detection is not a hand** — a few points under bad light is how a
  gesture happens that nobody made. And a lost frame is dropped, never
  interpolated: inventing the missing points invents the gesture spanning them.

### The rows stay staged, and that is the point

`vision.gesture` and `vision.pointing` are **not** live. One thing is genuinely
missing and the hardware path has never executed. Their notes now name exactly
that one thing, so "staged" cannot be read as "nothing here works" — the same
treatment §10 got for a second monitor this deployment does not have.

### What is proven

**Automated (PASS):** 25 tests. Seven injections, each grepped before the run
was trusted:

| Injection | Result |
|---|---|
| Allow any origin for the model | 3 CDN-refusal tests fail |
| Undefined consent counts as consent | **passed at first.** See below |
| Do not mirror | 2 fail, including the end-to-end swipe |
| Use the wrist instead of the fingertip | 3 fail |
| Interpolate over lost frames | 2 fail |
| Accept a partial hand | 1 fails |
| Absolute clock instead of relative | 1 fails |

**The consent injection is the one worth reading**, because it is the privacy
gate. The first version of that test passed while consent was granted to
everybody — with `receiving` unset, the *next* check returned the same
`unpermitted` state, so the assertion could not tell which branch had refused.
Setting `receiving: true` is what makes the test able to fail. This is the third
time in three phases that a test of mine passed under the injection it existed
to catch.

**Runtime (UNVERIFIED):** everything involving an actual camera. No hand has
ever been in front of this code.

**Assurance:** self-reviewed, lower assurance.

---

## Phase I6 — §21, where 3D earns its place  ✅ DONE

| Row | Was | Now | Evidence |
|---|---|---|---|
| §21 3D and scientific models | staged | **live** | `hub/surface3d.ts:meshFaces` |
| §4 Environment layer | staged | **live** | derived |

The note said "only canvas2d is implemented". That describes what exists rather
than naming a blocker, and it confused two things.

### 3D is not WebGL

The dimension is in the **data and the projection**, not in the API that
rasterises the triangles. A mesh painted back to front onto SVG polygons is real
3D, with no GPU and no dependency — painter's ordering *is* the depth buffer.
WebGL stays honestly unavailable in `projection.ts` as an **acceleration path**,
and no longer holds the capability hostage.

### "Where they aid understanding" is enforced, not quoted

That clause is in the spec, so `warrants3D` refuses more often than it accepts.
On a trading screen a gratuitous third dimension costs three things that are not
cosmetic:

| Cost | What it does |
|---|---|
| occlusion | a peak hides the trough behind it — the hidden value is the one somebody needed |
| foreshortening | two equal values read as different because one is further away |
| no shared baseline | comparing heights across a receding plane is a task humans do badly and confidently |

A 2D heatmap of the same grid has none of those, so 3D has to buy them back. It
earns it for a genuine z = f(x, y) over two ordered, densely-sampled axes — a
volatility surface across strike and expiry. It is refused for data varying in
one direction, for a grid under 75% populated, and for any malformed grid.

### The projection is orthographic

Perspective makes two equal values render at different heights depending on
where they sit. On a screen where z is a **price**, that is a chart misstating
its own numbers. Perspective is for photographs; measurement wants parallel
projection.

### A hole is never drawn across

The rule this module exists for. A volatility surface with no quote at a strike
has a hole, and a mesh drawn straight over it renders a smooth surface where
there is no market — a price a reader could act on that nobody ever made. Every
face touching a missing sample is omitted, and the caption says how many. `NaN`
is refused *separately* from `null`, so a broken pricer cannot read as an absent
quote.

### What is proven

**Automated (PASS):** 32 tests, and the whole frontend suite at 2,594. Nine
injections, each grepped before the run was trusted:

| Injection | Result |
|---|---|
| Interpolate across holes | 2 fail, including the caption |
| Perspective on the height axis | the orthographic test fails |
| NaN counts as a hole | 1 fails |
| Allow a one-direction surface | 2 fail |
| Allow a sparse grid | 1 fails |
| No back-to-front sort | 1 fails |
| Axis-aligned camera | 1 fails |
| Do not clamp pitch | 1 fails |
| Ramp floor back to its first value | the contrast test fails |

**Two findings from my own review, both real:**

* **The ramp made a trough look like a hole.** Measured, the darkest faces sat
  at **1.65:1** against the panel — so a low region would have been
  indistinguishable from a gap, contradicting the one claim this module is built
  around. The floor is now derived from `NON_TEXT_FLOOR` in a test rather than
  chosen.
* **A render test leaked into the next one.** It queried `document` and found
  the *previous* test's SVG, so the "refuses to draw" case passed while looking
  at a drawn surface. Scoped to each render's own container.

**Runtime (UNVERIFIED):** a real operator turning a real surface. The maths and
the markup are proven; nobody has looked at one.

**Assurance:** self-reviewed, lower assurance.

Also removed a pre-existing unused `RAW` alias in `SurfaceView.tsx` — an eslint
warning, and the same dead shape: a constant with a docstring explaining why it
was needed, used nowhere.

---

## Phase H — the remainder

**Three rows, two sections.** Regenerated from the registry each time this
section is touched: an earlier version still listed §7 and §25 rows that Phases
E and F had made live, and a stale plan is one a reader trusts.

| § | Row | State |
|---|---|---|
| 4 | Presence layer — identity, voice, animation, spatial state | staged |
| 18 | Gesture recognition | staged |
| 18 | Pointing and object reference | staged |

### Every row I called blocked was buildable

Six claims, six corrections, one mistake repeated: treating *unverifiable on
this hardware* as *unbuildable*.

* **§24 agent runtime** — "no process boundary this deployment has". Wrong;
  `multiprocessing` is standard library. Phase I1.
* **§10 multi-display** — "no second physical screen". The Window Management
  API is a browser API. Phase I2.
* **§18's built halves** — the recogniser and hit test had **zero production
  callers**. Not blocked at all. Phase I3.
* **§26 delegation bound** — "does not exist to bound". Circular, not blocked.
  Phase I4.
* **§18's camera halves** — "a supply-chain decision for the owner". Half an
  excuse; npm is reachable. Everything but the model shipped in Phase I5.
* **§21 scientific 3D** — "only canvas2d implemented". 3D is not WebGL, and a
  renderer is code. Phase I6.

**Nothing is blocked on a decision.** What is left:

* §18's two `vision.*` rows need a deployed hand-landmark model **and a camera
  to verify it against**. The code either side of that gap ships and is proven;
  the gap is one line of deployment configuration wide, and it stays staged
  because nobody has held a hand in front of it.
* §4's `arch.layer_a.presence` is a **derived roll-up** — `layer_state()`
  computes it from its constituents, so it moves on its own and cannot be typed
  live early. The workforce and environment layers moved by themselves when §26
  and §21 closed, which is the mechanism working.

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
