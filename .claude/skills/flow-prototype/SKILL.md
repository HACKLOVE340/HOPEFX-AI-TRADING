---
name: flow-prototype
description: Use when prototyping a complete interactive UI/UX flow across screens, states, transitions, feedback, and exits, especially before implementation or approval. Do not use for a static screen, generic UI variation, isolated component, or logic-only experiment.
license: MIT
metadata:
  author: Benjamin Macaulay at Chasebig Limited
  compatibility: Codex, Claude Code, Claude Skills, and Agent Skills hosts.
  version: "2.0.1"
---

# Flow Prototype

Build one throwaway, interactive model of a complete user goal. Let a reviewer traverse every applicable pathway, inspect why each interaction behaves as it does, and approve or revise the flow before production implementation.

Prefer `humanizing-writing` for audience-facing prototype copy before delivery. If `humanizing-writing` is unavailable, use direct, concrete, audience-appropriate language, remove filler and invented claims, and label this as the portable writing fallback. Skip this pass for code, state labels, annotations, and developer controls.

## 1. Establish product truth

Before designing or coding:

1. Inspect the existing design system, `PROJECT_BIBLE.md` when present, routes, components, tokens, platform conventions, and authoritative screens.
2. Identify the user goal, entry points, roles, platforms, exits, constraints, and source-of-truth product language.
3. Treat existing product language and established behavior as truth unless the user explicitly requests a redesign.
4. Read [flow-ui.md](references/flow-ui.md), then write its compact design brief and state and transition map before choosing the runtime.

Ask one concise user question only when a materially ambiguous choice would produce different flows. Otherwise state the assumption and proceed.

## 2. Choose the adaptive runtime

Prefer a framework-native prototype embedded in an existing safe host route. Reuse the host's real shell, components, tokens, navigation context, and read-only data when this can be isolated from production behavior.

Otherwise create exactly one standalone, self-contained interactive HTML file with inline CSS and JavaScript. Use this fallback when no safe host exists, the repository is unavailable, the host cannot run, or embedding would risk production behavior. Do not add a framework or dependency just for the prototype.

In either runtime:

- Mark the route or file as a prototype and gate embedded controls to development.
- Keep state deterministic and local. Mock network, payment, permission, and destructive effects.
- Never trigger a real mutation or external side effect, including paid mutations. All writes, messages, uploads, analytics, and backend changes use deterministic local mocks.
- Label mocks, simulated delays, and unverified native or unverified backend behavior in the review UI.

## 3. Build the complete flow

Implement the applicable state and transition map, not a happy-path slideshow. Cover entry, happy path, loading, empty, validation, permission, offline and unavailable, error, retry, cancellation, interruption, expiry, success, and exits. Include role variants and platform variants when behavior differs. Mark non-applicable states with a reason rather than silently omitting them.

Make interaction architecture a first-class decision. Choose page, inline, popover, modal, drawer, or sheet using context retention, task complexity, interruption cost, reversibility, and platform conventions. Follow the decision guide in [flow-ui.md](references/flow-ui.md).

Specify motion and semantic haptics for meaningful transitions. Optimize for delightful, clear, satisfying feedback without dark patterns, fake urgency, coercion, or noisy stimulation.

## 4. Expose the review surface

For a major UI/UX prototype, include:

- deterministic state controls;
- pathway navigation across branches and exits;
- transition annotations explaining container, motion, and state change;
- feedback and haptic guidance with native implementation notes;
- responsive viewports for the supported breakpoints;
- keyboard, screen reader, focus, and reduced motion behavior;
- a decision and approval surface for approve, revise, reject, and notes.

Keep developer controls visually separate from the proposed product UI. Make every state reachable without timing luck, unavailable services, or hidden gestures.

## 5. Verify and hand off

Traverse every pathway at each relevant viewport. Verify keyboard order, accessible names, focus restoration, live announcements, interruption recovery, and reduced motion. Distinguish browser simulation from native runtime proof.

Deliver the run command or file path, known mocks, unverified behavior, the state coverage map, and the approval question. The prototype is always throwaway and read-only.

Once approved, record the winner and why in the existing issue, ADR, or implementation handoff. Then delete or absorb the prototype. No prototype route, control panel, mock adapter, or losing alternative may remain in production code.

If no approver is reachable, halt before production UI. Questions forbidden is not approval. No post-hoc approval.
