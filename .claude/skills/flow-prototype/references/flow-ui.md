# Complete flow UI reference

Use this reference after product discovery and before implementation. It turns a user goal into a traversable interaction model.

## Design direction brief

Adapt these layers to the existing product before creating the state map. Existing product language, authoritative screens, and established design-system behavior remain the source of truth unless redesign is explicit.

### System fit

- Identify product type, platform, stack, audience, primary goal, density, and accessibility constraints.
- Inspect `PROJECT_BIBLE.md` when present, routes, components, tokens, navigation shell, and authoritative screens.
- Reuse semantic colors, type roles, spacing, radii, depth, controls, and copy patterns.
- Preserve safe areas, touch targets, contrast, focus, keyboard, screen reader, responsiveness, and reduced motion.
- Treat loading, empty, validation, permission, offline, unavailable, error, retry, cancellation, interruption, expiry, success, and exits as designed states.

### Product thesis

- Name the person, complete goal, entry context, and feeling the flow should create.
- Ground structure, copy, motion, feedback, and one signature element in the actual product world.
- Let hierarchy reveal sequence, consequence, progress, and recovery.
- Take one justified aesthetic risk. Keep everything else disciplined.
- Reject generic gradients, interchangeable card grids, decorative metrics, and fashionable patterns that have no domain reason.

### Product craft

- Give every step one focal task and a clear next action or exit.
- Choose density deliberately and keep navigation context visible when it aids recovery.
- Use accessible primitives from the host system rather than hand-built substitutes.
- Make feedback immediate and proportional. Delight should clarify causality or completion.
- Avoid dark patterns, fake urgency, forced continuity, hidden cancellation, and noisy stimulation.

## Compact working brief

Write no more than eight lines before implementation:

```text
Goal: [complete user outcome]
Human and feel: [specific role and desired quality]
Entry and exit: [where the flow starts and returns]
System: [host, density, token and depth direction]
Signature: [one product-specific interaction or visual element]
Feedback: [motion and haptic character]
Rejecting: [two generic or harmful defaults]
Variants: [role or platform differences that matter]
```

Hold this brief steady across every state. If the user explicitly requests a redesign, name which system rules may change and which product truths remain fixed.

## State and transition map

Create one compact matrix before coding:

| From | Trigger | Guard or input | To | Container | Feedback | Recovery or exit |
| --- | --- | --- | --- | --- | --- | --- |
| Entry | Primary action | Valid input | Loading | Page or inline | Progress, no haptic | Cancel |
| Loading | Response | Success | Success | Page or sheet | Success haptic | Continue or exit |
| Loading | Response | Error | Error | Inline or page | Warning haptic | Retry or cancel |

Model every requested state and transition that applies:

- entry and each supported deep link;
- happy path and success;
- loading and progress;
- empty and first-use guidance;
- validation, disabled, and corrective feedback;
- permission request, denial, restricted, and recovery;
- offline, unavailable, timeout, and stale data;
- error, retry, exhausted retry, and escalation;
- cancellation, back, close, and destructive confirmation;
- interruption, backgrounding, resume, and abandoned work;
- expiry for sessions, links, codes, reservations, or offers;
- exits to the originating context and logical next task;
- role variants and platform variants where capability or convention differs.

Mark a state `N/A: reason` when it cannot apply. Do not create fake states merely to fill the matrix.

## Interaction container architecture

Choose the smallest container that preserves comprehension and recovery:

| Container | Prefer when | Avoid when |
| --- | --- | --- |
| Page | Complex, durable, linkable, or multi-step work needs full focus | The task is a quick reversible adjustment |
| Inline | Feedback or editing belongs beside its source | Expansion would overwhelm the surrounding layout |
| Popover | A short contextual choice needs its anchor visible | Mobile space, long content, or critical confirmation is involved |
| Modal | A brief blocking decision must interrupt the current task | The task is exploratory, multi-step, or frequently referenced |
| Drawer | Secondary detail or tools must retain broad page context | Narrow mobile space or strict focus is required |
| Sheet | Mobile-first choices, confirmations, or short forms need thumb reach | Dense, long, or deeply nested work is involved |

Evaluate each decision against context retention, task complexity, interruption cost, reversibility, and platform conventions. Also specify dismissal, back behavior, focus entry, focus restoration, escape handling, outside-click behavior, and whether work survives closure.

## Motion specification

For every meaningful transition, record:

`Trigger | Target | Duration | Easing | Enter | Exit | Interruption | Reduced motion`

- Trigger: the user action or state change.
- Target: the element or region that changes.
- Duration and easing: explicit values that match distance, hierarchy, and platform convention.
- Enter and exit: opacity, transform, size, or shared-element behavior without layout surprise.
- Interruption: cancel, reverse, finish, or retarget when input arrives mid-motion.
- Reduced motion: replace spatial travel with immediate state change or short opacity feedback while preserving meaning.

Motion must explain continuity, hierarchy, causality, or completion. Decorative loops, motion on every tap, and animation that delays control are noise.

## Semantic haptics

Annotate meaningful events with one semantic intent:

| Intent | Use |
| --- | --- |
| none | Navigation, ordinary taps, repeated controls, or visual feedback that is already sufficient |
| selection | A discrete picker, segmented control, or snapped selection change |
| light | A small completed action or subtle boundary |
| medium | A deliberate commitment with moderate consequence |
| warning | Validation risk, destructive boundary, or action requiring attention |
| success | Confirmed completion of a meaningful user goal |

Translate intent to the native platform APIs during production implementation, such as iOS feedback generators or Android haptic constants. Never vibrate every tap. Browser vibration may simulate an annotation on supported devices, but never claim browser vibration proves native haptics. Label all haptic behavior unverified until tested in the native runtime on hardware.

## Deterministic review controls

A major prototype needs a developer review layer with:

- deterministic state controls for every state and role;
- pathway navigation that shows current location, prior step, and reachable branches;
- transition annotations for container choice, state mutation, motion, and feedback;
- feedback and haptic guidance that distinguishes simulation from production intent;
- responsive viewports for the supported phone, tablet, and desktop targets;
- keyboard mode, screen reader notes, focus order, and reduced motion toggle;
- a decision and approval surface with approve, revise, reject, and free-form notes.

Keep controls outside the product chrome or behind a clear review toggle. Use fixed mock seeds and manual time controls so retry, expiry, interruption, and success are reproducible.

## Safety and proof boundary

The prototype is throwaway and always read-only. Use local state and mock adapters. Never trigger a real mutation or external side effect, including paid mutations. All writes, messages, uploads, analytics, and backend changes use deterministic local mocks.

Clearly label mocks, simulated network behavior, browser-only effects, unverified native behavior, and unverified backend behavior. A web prototype proves interaction intent, not native haptics, native navigation, platform permission behavior, backend correctness, or production performance.

After approval, record the winner and decision rationale. Delete or absorb the prototype as part of production implementation, including review controls, mock adapters, and abandoned pathways.

If no approver is reachable, halt before production UI. Questions forbidden is not approval. No post-hoc approval.
