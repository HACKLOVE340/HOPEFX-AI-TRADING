# AI Hub — decisions of record

Decisions taken against **AI Hub Institutional Master Architecture &
Implementation Specification v1.0**. Recorded here rather than left in chat,
because §30 requires each phase to report what was decided and why, and a
decision nobody can find is a decision that gets re-litigated.

Add to this file; do not rewrite it. A superseded decision keeps its entry and
gains a note.

---

## D1 — The five capabilities §3 says exist but do not

**Decided: build them. There is no second prototype to merge.**

§3 lists these as existing and therefore to be preserved: particle field,
cognitive stream, neural engine, sleep monitor, GPU monitoring. An audit of the
whole repository — not only the frontend — found none of them.

What *does* exist, and is preserved rather than rebuilt: the holographic stage
(`frontend/src/index.css:230-239` — two counter-rotating orbital rings, a
scan-line overlay, a projection glow, a 3D perspective and a reduced-motion
guard), the aggregating console (`useAICommandCenter.ts`, nine live sources
with per-source degraded tracking — counted, not remembered; it was described
here as six, and as *multi-display*, which it is not: nothing spans a second
physical screen), the camera (`VisualIntelligenceWorkspaces.tsx`),
voice (`hooks/useVoice.ts`), and real model/spend/drift telemetry.

The five absent capabilities are registered in `ai/hub/capabilities.py` with a
note recording the discrepancy, so they cannot be silently dropped:

| Capability id | Lands in |
|---|---|
| `presence.particle_field` | Phase 1 |
| `legacy.cognitive_stream` | Phase 2 |
| `legacy.neural_engine` | Phase 4 |
| `legacy.sleep_monitor` | Phase 4 |
| `telemetry.host` | Phase 4 |

---

## D2 — Where the Hub lives

**Revised. Superseded the same day, by the owner, before anything shipped.**

The first reading of §4 built a separate `/hub` route that login landed on. The
owner's correction: *"Did you build a new one? Let's use the existing page."*
That is right, and the first attempt was wrong in a way worth recording — it
produced a second AI screen beside the AI screen, which satisfies §4 on paper
and defeats it in practice.

**Decided: the presence is the AI Core page's first tab.** Not a new route.

* `AICore` opens on `Presence` when `VITE_HUB_ENABLED=true`.
* Its six existing tabs — Workbench, Overview, Model chain, Spend, Calls,
  Governance — are untouched and one click away.
* With the flag off it opens on Overview, exactly as it always did.
* No route was added, moved or removed. `pages/Hub.tsx` and the `/hub` route
  were deleted before they shipped.

A comment in `AICore.tsx` used to say that promoting a different tab "changes
what this page IS" and was the owner's call rather than one to slip in with a
feature. It was, and it has been made.

### Superseded: a new route the login lands on

The original entry read: *"a new route the login lands on. The 85 existing
routes stay."*

§4 forbids a permanent dashboard as the primary interface. The minimum change
that satisfies it without deleting anything is to move the front door, not to
remove the rooms behind it.

* The Hub becomes the post-login destination.
* Every existing route stays reachable and unchanged.
* Existing pages become *surfaces the Hub can summon* (§8) as well as routes.
* The change ships behind a feature flag, per §30-I, so the previous landing
  page is one flag away for the life of the rollout.

Nothing is deleted. `AICore` in particular is preserved as the governance and
observability surface — §29 requires that agent workflows be auditable, and that
page is where an operator reads the audit.

---

## D3 — Voice

**Decided: the AI gets its own consistent voice. Local synthesis first,
a hosted provider as the upgrade.**

The high-quality path already exists and is wired: `api/voice.py` serves
`POST /api/voice/tts` and `/stt` behind auth and a quota, with ElevenLabs or
OpenAI for synthesis and Whisper for recognition, and `useVoice.ts` already
probes `/voice/status` and falls back to Web Speech when no key is configured.
So this is a configuration decision, not a build.

The reason for choosing is **identity, not fidelity**. Web Speech uses whatever
voice the operating system provides, so the AI currently sounds like a different
person on every machine and has no voice of its own. A single synthesis source
gives it one.

The second reason is **privacy**. This assistant reads balances, positions and
risk limits aloud. Local synthesis means those sentences never leave the host.

| Route | Cost | Identity | Where the text goes |
|---|---|---|---|
| Local neural TTS on the VPS | free after setup | one voice, consistent everywhere | nowhere |
| ElevenLabs (`ELEVENLABS_API_KEY`) | metered | a chosen or cloned voice id | the vendor |
| OpenAI (`OPENAI_API_KEY`) | metered, cheaper | six presets | the vendor |

Local first; the hosted providers stay one environment variable away and the
code path is already written. Neither blocks Phase 0, and both land in Phase 1.

Open: whether the VPS can run a neural TTS model at acceptable latency.
`scripts/vps_capability_report.py` answers that and has not been run against the
production host.

---

## D4 — Sync or async: the AI into the app, or the app into the AI?

**Decided: both, asymmetrically. Reading is total and synchronous.
Writing is narrow and asynchronous.**

The question was posed as a choice between two directions. It is not one — the
two directions have different risk profiles, and giving them the same design is
what produces either a blind assistant or a dangerous one.

### App → AI (what the AI can see): total, synchronous, derived

The AI sees the platform **whole**, and sees it by construction rather than by
what somebody remembered to wire. `ai/hub/app_surface.py` derives the catalogue
from the live route table on every call:

| Measured | |
|---|---:|
| Capabilities visible | **2,234** |
| Product areas | **88** |
| Reads / writes | 1,266 / 968 |
| Invokable from the AI | **0** |
| Tools registered on the bus | 17 |

A hand-maintained list of those would be wrong within a day, and wrong in the
direction nobody notices: nothing fails, the AI is simply ignorant of a feature
that shipped last week. Adding a router tomorrow makes it visible with nobody
editing anything.

This is synchronous because it is a read of an in-process data structure —
22 ms, no I/O, no vendor. Making it async would add a failure mode to something
that cannot fail.

**One detail is load-bearing.** The walk uses
`core.router_registry.iter_api_routes`, never `app.routes`. Starlette no longer
flattens an included router's routes onto `app.routes` at `include_router()`
time, so the naive read finds 1,105 routes where the real table has 2,249 —
**half the platform, missing silently**. A catalogue that reported half the
product and said nothing would be worse than none.

### AI → App (what the AI can do): narrow, asynchronous, gated

Everything the AI can actually *do* stays behind `ai/tools/bus.py` — 17 tools,
each with a fail-closed permission gate, shadow mode for writes, and a live-mode
switch that is off by default.

**Discovery is not capability.** Knowing that `POST /api/orders/advanced/oco`
exists must not mean the AI can submit one. So `summary()` reports `visible` and
`invokable` as two separate numbers and never one: merging them is exactly how a
map becomes a menu. Today every one of the 968 writes is visible and
unreachable, and that is the correct state, not a gap.

The `invokable` flag is decided by **object identity** — a route is reachable
only when its endpoint function *is* a registered bus handler. Name-matching
would be a guess ( `place_order` the route vs. `markets_execution.shadow_place_order`
the action are unrelated objects sharing a word), and a guess in this direction
marks a write callable that is not.

### Why the catalogue reaches the planner and not just an endpoint

Derived correctly, exposed on `GET /api/ai-core/capabilities/app`, and read by
nothing that makes a decision — that is a control nobody runs, which is defect
class F176 in this repository. So `LoopContext.platform_context` carries what
the platform can do *about the current goal* into `ai/agent/loop.py`.

It is a **separate field from `permitted`**, deliberately. `permitted` is what
the planner may choose; `platform_context` is what exists. A planner that treats
a line it saw as callable is refused by the allowlist before anything reaches
the bus — asserted in `test_seeing_a_route_is_not_permission_to_call_it`.

It is also **bounded to 12 rows**, because 2,234 do not fit in a prompt and a
truncated prefix would hide whole areas silently. The search that picks those 12
drops stopwords: scoring every word of three letters or more made "check the
current drawdown against risk limits" match **850 of 2,234 routes**, since
"current" appears in a third of the docstrings here. A result set that large is
the same as no result set. This repository shipped that exact defect once
already, in `Scene.resolve`, where "nothing like this" matched a panel titled
"gold price **this** session".

### What this costs

The catalogue carries path, method, mode, area, auth and the first line of the
docstring — no request bodies, no parameter schemas, no examples. A catalogue
that quoted request models would eventually quote one with a credential field
name and a sample value. The defence is structural: `AppCapability` has exactly
eight fields, and a test fails if a ninth appears.

---

## Phase I3 — wiring a pointer is not shipping a camera

### The decision: pointer input gets its own rows, `vision.*` stays staged

§18's `vision.gesture` and `vision.pointing` had notes splitting them honestly
into a built half and a camera half. The built halves — `recogniseGesture` and
`pointingAt` — turned out to be imported by **nothing outside their own tests**.
Dead controls, in my own work, in the file whose docstring warns about exactly
that.

Wiring them raised the tempting question: does that make the two `vision.` rows
live? No. Every other row in §18 is camera-derived — scene understanding,
capture indication, frame retention, source selection — and `vision.` means
vision. A pointer swipe is not vision.

Marking those rows live for pointer input would be **renaming the capability to
fit what was built**. That is precisely the move that had `agents.system`
pointing at `platform_engineering`, and left §11 reporting twelve agents with
eleven present. The registry only means something if the id constrains the
evidence rather than the other way round.

So: two new ids, `input.pointer_gestures` and `input.pointing_resolves`, and the
`vision.` rows keep their staged state with only the camera half named. Their
notes now point at the new ids, so "staged" cannot be misread as "nothing here
works".

### What is NOT being decided here

The camera halves need a hand/body landmark model this repository does not
carry. Adding one is a **supply-chain decision for the owner** — a new
dependency, pulled into a money-moving platform, shipping a model. That belongs
to the owner, not to a phase that happened to be nearby.

### Only reversible actions are bound to a gesture

`gestures.ts` argues in its own docstring that on a trading screen a wrongly
recognised swipe moves a panel somebody was reading. The answer is that no
gesture removes anything: a swipe moves FOCUS, a long press PINS. Both are
reversible and both are already reachable by other means. Nothing closes a
panel, leaves the plane, or touches an order — and a source-scanning test holds
that, so a later edit cannot add one quietly.

The recogniser's own refusal is what makes this safe, and it is re-asserted at
the call site: a movement that is not clearly anything returns null and does
nothing at all. It never wraps, on the same grounds as `resolveReference` — a
reference that wrapped would move an operator's attention to the far side of
the plane, which is the opposite of what they asked for.

### The bound belongs where the recogniser is, not where the events are

A pointer held down emits a move per frame, so an unbounded track is a
user-driven allocation with no ceiling. `appendPoint` caps it, and lives in
`gestures.ts` because that is where the code that says *what is actually read*
lives — the recogniser reads only the first point and the last one.

Which point to drop is the real decision. A ring buffer dropping the **oldest**
is the obvious implementation and is wrong here: the first point is what a swipe
is measured from and what `pointingAt` hit-tests against, so dropping it
silently changes which panel a gesture meant. Injected, it does not degrade
gracefully — recognition fails outright. The cap therefore replaces the
**newest** point once full, keeping both ends exact.

### One focus, read by everything

Adding gesture focus without repointing `place()` gave the plane two notions of
focus at once: the ring followed the swipe while the layout went on enlarging
the operator's original selection. `shownFocus` is now declared above the
placement memo and feeds it, so there is one answer to "which surface is
focused" and everything downstream reads it.

---

## Phase I4 — a bound that is three bounds, and a limit of the registry

### Depth alone is not the bound

Three failure modes, enforced separately because each is invisible to the
others: **depth** (A→B→C for ever), **fan-out** (500 children, all at depth 1,
every one inside the depth limit), and **total descendants** (depth 4 by
fan-out 8 exceeds neither and is 4,680 nodes). Each of the three tests satisfies
the other two bounds comfortably — the only way to show a bound is doing work
rather than riding behind a stricter neighbour.

### Where the bound lives, and what it does when it fires

At **creation**, on `TaskGraph.add()`'s own argument: creation is the last moment
at which nothing has happened yet. After it, the model call is paid for.

When it fires it **refuses the child and keeps the tree**. Failing the whole
tree would discard finished work that was already paid for — wasting exactly the
spend the bound exists to protect. The refusal is recorded with the bound that
caused it, because a silently dropped child is a plan that ran differently from
the plan that was written.

### Fail-closed means an unknown parent is refused, not adopted

A node presenting a parent the ledger has no record of would, if admitted as a
fresh root, receive a whole new budget — which is precisely what a runaway
needs. `open_root()` is the only way a tree begins.

### A grant crosses the process boundary, because a ledger cannot

The child's ledger is empty, so it is handed a `grant` and seeded with exactly
that. The parent is charged `1 + grant` **in full**: charging only for the child
would let two siblings each be handed the remaining budget and each spend it.
The default grant is zero — delegation does not propagate unless somebody said
so in the call that created the child.

### What the capability registry cannot check

`run_isolated` was imported by nothing outside its own tests, and I marked
`stack.agent_runtime` **live** anyway — a dead control inside the work that
closed a row about isolation, written two commits after the Phase I3 note about
finding exactly this in my own work.

`verify()` resolves an evidence locator. It has no opinion about whether
anything imports it, so a row can be live, resolve cleanly, and point at code
nothing calls. That is a real limit of the anti-omission mechanism, and writing
it down here is the only thing that stops it being rediscovered a third time.
The registry answers *does the evidence exist*; it does not answer *does
anything run it*.

### A concurrency test that passed without the lock

Two versions of it did. `admit` runs so few bytecodes between reading the child
count and incrementing it that sixteen threads never landed in the window, even
with the switch interval at a microsecond — so the test passed whether or not
the lock was there, which is a test of nothing.

The fix was to widen the window where the race actually is, with a bounds
stand-in that releases the GIL inside the fan-out check. Under it the unlocked
ledger admits 15 children against a limit of 8. The lesson generalises: a
concurrency test that has never been run against the unsynchronised version is
not evidence that synchronisation is needed.

---

## Phase I5 — answering "does shipping the model spoil things"

### It does, and not for the reason I had been giving

I had recorded §18's camera halves as blocked on a **supply-chain decision for
the owner**. Asked to settle it, I checked, and that framing was half an excuse:
npm is reachable and `@mediapipe/tasks-vision` is one install away.

The real obstacle is smaller and harder. **There is no camera in the environment
this was built in.** Installing a two-megabyte runtime and an eight-megabyte
model into a platform that moves money, and never executing either once, is
committing code on faith. That is the thing `verification-before-completion` and
"prove by execution, not by reading" exist to stop, and it is not a rule to
suspend because a row is nearly closed.

So the decision is: **ship everything except the model.** The gap is now one line
of deployment configuration wide, and it is named in both registry notes rather
than described as a blocker.

> **Reversed 2026-09-09.** The reason above was a single falsifiable claim —
> "never executing either once" — and it was not re-checked before being written
> down. Chromium serves a video file as a webcam
> (`--use-file-for-fake-video-capture`), so a camera was available the whole
> time; what was missing was the idea, not the hardware. `npm run prove:hands`
> now runs the real detector against MediaPipe's own photograph of a hand and
> drives the full chain off a fake device. The model is fetched at deploy time
> rather than committed, which also answers the cost half nobody had costed:
> 7.8 MB does not enter the history, and the runtime is a dynamic import so it
> does not enter the main bundle either.
>
> A decision recorded as settled is the hardest kind to re-examine, which is
> exactly why this one sat for two phases. See MASTER_OUTSTANDING §E21.

### A hand is a source, not a second pipeline

`trackFromHands` produces the same `TrackPoint[]` that `recogniseGesture` has
read since Phase E2. Building a camera pipeline beside the pointer one would
give the console two ways to decide what a swipe is, and they would eventually
disagree — the same argument that put one `shownFocus` in `PresenceStage` rather
than two notions of focus.

### The model comes from this origin or not at all

The vendor's documentation hands you a `storage.googleapis.com` URL to paste
into a constructor. `resolveModelUrl` refuses it. A trading console fetching a
model from a third party on the operator's behalf is a runtime dependency on a
host nobody here controls, in front of a feature, and a signal to that host every
time this desk opens its console. Self-hosted or absent — and refused *loudly*,
because a model that silently failed to load would present as `unsupported` and
send somebody hunting a browser problem.

### Four states, and undefined consent is refusal

`unconfigured`, `unsupported`, `unpermitted`, `measured`. Collapsing them is §22's
rule broken where it matters most: an operator whose camera gesture does nothing
needs to know which one, because "not working" sends them looking for a hardware
fault that is not there.

Consent is the inversion: undefined is **refusal**, never permission, per §25.

### Three phases, three of my own tests that could not fail

Worth recording as a pattern rather than three incidents:

* **I3** — three pointer tests each fired an event before asserting, so the
  initial `unknown` state was never checked and starting at `'mouse'` passed
  them all.
* **I4** — two versions of a concurrency test passed with the lock removed,
  because `admit` runs too few bytecodes between read and increment for threads
  to land in the window.
* **I5** — the consent test passed while consent was granted to everybody,
  because with `receiving` unset the *next* check returned the same state.

The shape is identical each time: **an assertion that a second code path can
also satisfy.** A test only proves the branch it can distinguish, and the only
way to find that out is to inject the defect and watch. Every one of these was
found by injection and none by reading.

---

## Phase I6 — 3D is not WebGL, and a third dimension has to earn its place

### Two things the old note confused

It said "only canvas2d is implemented", which describes what exists rather than
naming a blocker. **The dimension is in the data and the projection, not in the
API that rasterises the triangles.** A mesh painted back to front onto SVG
polygons is real 3D: painter's ordering *is* the depth buffer, which is exactly
why it needs no GPU and no dependency.

WebGL stays honestly unavailable in `projection.ts`, because no GPU-backed
context has been proven here. It is an **acceleration path**, and it no longer
holds the capability hostage.

### The spec clause is a constraint, so it is enforced

"Where they aid understanding" is in the spec text, and `warrants3D` refuses more
often than it accepts. On a trading screen a gratuitous third dimension costs
occlusion (a peak hides the trough behind it, and the hidden value is the one
somebody needed), foreshortening (equal magnitudes read as different), and the
shared baseline that comparison depends on. A 2D heatmap of the same grid has
none of those, so 3D has to buy them back.

It earns them for a genuine z = f(x, y) over two ordered, densely-sampled axes
where the shape *between* the samples is the information. It is refused for data
varying in one direction — a line repeated, whose depth is decoration.

### Orthographic, because z is a price

Perspective renders two equal values at different heights depending on where
they sit. On a screen where the vertical axis is a price, that is a chart
misstating its own numbers. Perspective is for photographs; measurement wants
parallel projection.

### A hole is never drawn across

The rule the module exists for, and the third time this repository has landed on
it. A volatility surface with no quote at a strike has a hole; a mesh drawn over
it renders a smooth surface where there is no market — a price a reader could
act on that nobody ever made. Every face touching a missing sample is omitted
and the caption says how many, so the bite out of the surface reads as absent
data rather than as a shape.

`NaN` is refused **separately** from `null`. A missing sample is `null` and says
so; `NaN` is a calculation that went wrong, and letting it read as "no quote"
hides a broken pricer behind a plausible gap.

That is the same rule `trackFromHands` holds for a lost camera frame and
`sceneFrom` holds for containment: **absent is absent, never inferred.**

### A colour ramp that made a trough look like a hole

Measured during review: at the lightness the ramp started at, the darkest faces
sat at **1.65:1** against the panel. A low region would have been
indistinguishable from a gap — contradicting the one claim the module is built
around, in the module that makes it.

The floor is now derived from `NON_TEXT_FLOOR` by a test rather than chosen, so
moving either the ramp or the palette fails loudly. This is the second time a
measured contrast check has overturned a number that looked fine: the first was
`slate-500` reading 3.67:1 where memory said 4.21.

### A fourth test that could not fail

A render test queried `document` and found the **previous** test's SVG, so the
"refuses to draw" case passed while looking at a drawn surface. Scoped to each
render's own container now.

Four phases, four of these, and the shape is the same every time: **an assertion
that something other than the code under test can also satisfy.** I3's pointer
tests fired an event first; I4's concurrency test never reached the race; I5's
consent test was satisfied by the next branch; I6's queried a shared DOM. None
was found by reading.
