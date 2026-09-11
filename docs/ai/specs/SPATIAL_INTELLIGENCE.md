# Spatial Intelligence & World Creation

**Owner:** hacklove340 · **Tier:** T1 · **Status:** active · **Opened:** 2026-09-11

A native capability of the AI OS, not a separate 3D feature. It extends the
AI Hub, the multi-agent fabric, the evidence architecture, the memory layer and
the holographic presence surface that already exist; it replaces none of them.

---

## The rule the whole thing hangs off

> **The AI must know what it does not know.**

A 3D system produces persuasive artifacts. A generated house looks built. A
generated car looks engineered. A solver returns a number to four decimals.
Every one of those is a value nothing verified, presented as though something
had — the defect class this repository has spent a programme removing, now with
the widest blast radius it has ever had, because the output is *beautiful* and
beauty reads as correctness.

So nothing here reports a bare result. Every claim carries its rung:

| Rung | Means |
|---|---|
| `NOT_ASSESSED` | Nobody looked. The default, and it appears in every report |
| `VISUALIZED` | It has been drawn. A claim about pixels, nothing more |
| `PROCEDURALLY_GENERATED` | A rule produced it. Self-consistent, unchecked |
| `ESTIMATED` | A heuristic produced a number |
| `SIMULATED` | A solver ran. True inside its own assumptions |
| `VALIDATED` | Checked against acceptance criteria inside this system |
| `EXTERNALLY_VERIFIED` | Confirmed outside it — measurement, standard, third party |
| `HUMAN_APPROVED` | A named person accepted responsibility |

**Four rules, all enforced in code today** (`ai/spatial/assurance.py`,
`invariants/spatial.py`):

1. A claim rises only on evidence that supports that rung — this is
   **AOS-EVID-028**, which the conformance register recorded as ABSENT and which
   this work closes.
2. A claim may always fall, and needs no evidence to. Learning something is
   worse must never require a permit.
3. **A composite is the MINIMUM of its parts.** Not the mean, not the best. A
   structural analysis that passed does not redeem a code-compliance box nobody
   ticked.
4. **Readiness is never inferred from assurance**, however high. Approval is a
   person, named, on every required aspect.

So the system never says *"this house is safe to build."* It says:

```
3D design                       PROCEDURALLY_GENERATED
Structural simulation           SIMULATED           (passed, inside its assumptions)
Building-code compliance        NOT_ASSESSED
Professional engineering review NOT_ASSESSED        required
--------------------------------------------------------------
Overall                         NOT_ASSESSED        (rule 3: the weakest part)
Construction readiness          NOT READY           blocking: code_compliance, review
```

---

## The sixteen capabilities

**The table below is a readable copy. `docs/ai/specs/SPATIAL_CAPABILITIES.toml`
is the authority**, and `python scripts/spatial_capabilities.py` resolves every
claim in it against the code — a module that imports, an attribute that exists, a
path on disk. A row here that disagrees with the register is stale prose; the
register is what a gate checks on every commit.

    16 spatial capabilities · 1 built · 9 partial · 6 planned


Ordered as the owner gave them. Status reflects what exists **today**, measured,
not intended — a roadmap that overstates itself is the same defect one layer up.

| # | Capability | Status | Notes |
|---|---|---|---|
| 0 | **Epistemic status ladder** | **built** | `ai/spatial/assurance.py` + `invariants/spatial.py`, every rule counterfactually proven |
| 1 | Universal 3D Builder | **partial** | `ai/spatial/world.py` — the component graph: typed components, typed connections, assembly order, removal impact, bill of materials. The *representation*, which every capability below needs; geometry, and generation from text/sketch/image/voice/CAD, attach to it and do not exist yet |
| 2 | AI Construction Brain | **partial** | Dependencies, assembly order and materials are answered by `world.py`. Constraints, dimensions and *why* it is built that way are not |
| 3 | Interactive World Model | **partial** | `world.py` answers "what is this connected to?" and "what happens if I remove it?" on the backend; `frontend/src/hub/sceneGraph.ts` answers "what is next to / inside / behind what" on the screen. Both refuse unknown ids rather than returning null |
| 4 | Simulation Laboratory | **partial** | `ai/spatial/simulation.py` — the selector and its refusals. Nine domains nameable; a solver registered per domain; no solver, a declining solver or a raising solver all yield `NOT_ASSESSED` with a reason, never a default. A solver's own claim is clamped to `SIMULATED`. **No solver is registered** — the lab is the honest frame, and the physics behind it does not exist |
| 5 | Construction Time Machine | **partial** | `ai/spatial/timeline.py` — step through the build, inspect any stage, branch from any point; a Construction snapshots its world, so recorded history cannot be rewritten by a later edit. `ai/spatial/playback.py` — pause, resume, seek and speed, as a pure state machine with no timers. Reaching the end clamps *and* reports `finished`. No UI animates it |
| 6 | AI Video Director | planned | Camera, animation, labels, narration, subtitles, exploded views, cinematic walkthrough — driven by the real construction history, not a re-enactment |
| 7 | Multi-Agent Design Studio | partial | Architect, Engineer, Materials, Simulation, Cost, Safety/QA, Visualization, Video Director. `ai/departments/` already holds eleven specialists that delegate to real code and return `available: False` rather than a number they did not get — the pattern to extend |
| 8 | What-If Laboratory | **partial** | `ai/spatial/compare.py` — component and bill-of-materials deltas between trunk and branch at `PROCEDURALLY_GENERATED`, and `better_on()`, which **refuses to rank** unless both sides carry a finding at `SIMULATED` or better. A side with no finding has not scored badly; it has not been measured. Re-simulation needs a solver, and none exists |
| 9 | Automatic Design Alternatives | planned | Cheapest / strongest / most efficient / most beautiful / best trade-off, compared in one workspace |
| 10 | Reality-to-3D | planned | Photograph, video or scan → editable spatial model. Reconstruction is `ESTIMATED` at best until measured |
| 11 | 3D-to-Reality Documentation | **partial** | `world.py` produces the assembly sequence and the bill of materials. Dimensions, diagrams, technical docs and maintenance instructions do not exist |
| 12 | Spatial Memory | planned | "Open the house we designed last month." Extends `ai/memory/` |
| 13 | Persistent Digital Twin | planned | A living representation compared against observed reality. Divergence is a first-class signal |
| 14 | AR/VR/Mixed Reality Layer | planned | Walk the model, or project it into the room |
| 15 | Spatial Voice Interaction | partial | "This beam carries the second floor." → "Show me." → highlight, load path, simulation. `frontend/src/hub/spatial.ts` already grounds deixis in a **measured** `DOMRect` — no rect, no position, never an invented corner |

**Three are already partly real**, and their existing discipline is exactly what
this specification needs — which is why this extends them rather than starting
beside them:

* `hub/spatial.ts` — *"Position is measured or it is not claimed."*
* `hub/sceneGraph.ts` — refusals, not silent nothings; containment cycles refused at the edge.
* `hub/surface3d.ts` — *"A hole is never interpolated."* `warrants3D` refuses more often than it accepts, and WebGL stays honestly unavailable rather than claimed.

---

## A load path is a claim

`World.removal_impact` returns `PROCEDURALLY_GENERATED` and never more. The graph
knows a beam supports a floor because **somebody declared the connection** — an
assertion about a drawing, not a measurement of a building. Whether the structure
stands without it is a question for a solver that has not run.

That rung is enforced twice on purpose: the result carries it (so a finding
cannot travel without it), and `verify_structural_claim_requires_solver` refuses
a republished claim at `SIMULATED` or above with no solver run. A rule enforced
only at its source is a rule enforced by whoever remembers it, and "the model
says the floor stays up" becoming "the floor stays up" is the step that turns a
drawing into a demolition decision.

## The laboratory is a frame with nothing in it, deliberately

`ai/spatial/simulation.py` can name nine domains and refuse all nine. That is not
a placeholder — it is the useful half.

A laboratory that always returns a number is the most dangerous component here.
`removal_impact` is safe because it is labelled `PROCEDURALLY_GENERATED` and its
graph is visible; **a simulation result looks like physics**. Answer a structural
question with a thermal solver, or with a plausible default because nothing was
registered, and the answer is indistinguishable from one a finite-element run
produced — to the operator, to the report, and to whatever decides to build it.

So the refusals shipped first and the physics has not shipped at all:

| Situation | Result |
|---|---|
| No solver for the domain | `NOT_ASSESSED`, naming the domain |
| Solver declines this model | `NOT_ASSESSED` — never fall back to another domain |
| Solver raises | `NOT_ASSESSED`, carrying the failure, still naming the solver |
| Solver claims `VALIDATED` or above | clamped to `SIMULATED` |
| Solver claims `ESTIMATED` | kept — the clamp is a ceiling, not a floor |
| Two solvers for one domain | refused at registration |

When a real solver is adapted in, every one of those rules is already standing
between it and a build decision.

## Integration points — native, not bolted on

| Existing system | How spatial joins it |
|---|---|
| AI Hub capability registry (`ai/hub/capabilities.py`) | Spatial capabilities are registered rows. A capability absent from the registry does not exist; one present cannot be quietly forgotten |
| Multi-agent fabric (`ai/departments/`) | The Design Studio agents are departments, following the existing `available: False` honesty contract |
| Evidence / invariants (`invariants/`) | `invariants/spatial.py`, five predicates, discovered by the registry like every other |
| Memory (`ai/memory/`) | Spatial Memory is a memory surface |
| Holographic presence (`frontend/src/hub/`) | Presence stage, scene graph and spatial grounding already exist |
| Simulation | `backtesting/`, `chaos/`, `shadow/`, `replay/` are the existing precedent for "run it before believing it" |

---

## The target experience

> "Build me a sports car." → agents work in parallel, the car appears
> progressively, you walk around it. "Make it electric." → the model branches
> and re-simulates. "Compare with the previous one." → both appear side by side
> with performance, weight, cost, range and aerodynamic deltas. "Make a
> three-minute video of how we built it." → the Video Director uses the real
> construction history.

Every panel in that experience carries its rung. The comparison says which
figures are `SIMULATED` and which are `ESTIMATED`; the video says what it is
showing was generated, not measured; and nowhere in it does the system conclude
that the car can be manufactured.

---

## What is deliberately not claimed

No solver, renderer, reconstruction pipeline or video encoder exists yet. This
document describes one built capability and fourteen planned ones, and the
statuses above are measured from the tree rather than aspired to. When a
capability lands it moves here **with its evidence**, the way every other
capability in this repository does.
