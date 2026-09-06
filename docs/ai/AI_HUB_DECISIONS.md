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
guard), the multi-display console (`useAICommandCenter.ts`, six live sources
with degraded-source tracking), the camera (`VisualIntelligenceWorkspaces.tsx`),
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
