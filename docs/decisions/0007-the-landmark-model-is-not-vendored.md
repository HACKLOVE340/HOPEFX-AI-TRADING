# 0007. Ship everything except the hand-landmark model

- Status: superseded by 0009
- Date: 2026-09-07

## Context

§18's `vision.gesture` and `vision.pointing` need hand landmarks. The pipeline
either side of a detector was built and proven against synthetic landmarks.
Back-filled from `AI_HUB_DECISIONS.md` Phase I5.

An earlier framing called this a supply-chain decision for the owner. Checked,
that was half an excuse: npm is reachable and `@mediapipe/tasks-vision` is one
install away.

## Options considered

- **Vendor the runtime and model now.** Costs: a two-megabyte runtime and an
  eight-megabyte model enter a platform that moves money, having never executed
  once. That is the thing `verification-before-completion` exists to stop.
- **Ship everything except the model**, leaving the gap one line of deployment
  configuration wide and named in both registry notes.

## Decision

Ship everything except the model. The rows stay staged.

## Consequences

Makes installing a detector a configuration change rather than a code change.
Leaves two capability rows staged on something that reads as unverifiable.

## Evidence

There was no camera in the environment this was built in.

> Superseded by 0009. The premise was false — Chromium serves a video file as a
> webcam — and nobody re-checked it for two phases.
