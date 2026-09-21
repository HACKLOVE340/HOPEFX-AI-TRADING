# 0009. Ship the hand-landmark model, fetched at deploy time

- Status: accepted
- Date: 2026-09-09

## Context

Supersedes 0007, whose decision rested on one claim: "there is no camera in the
environment this was built in." The reasoning was sound and the premise was
never re-checked, across two phases of work that touched the files either side
of it.

**Chromium serves a video file as a webcam.**
`--use-fake-device-for-media-stream` with `--use-file-for-fake-video-capture`
has existed for years. What was missing was the idea, not the hardware.

## Options considered

- **Keep 0007** and leave the rows staged. Costs: two capability rows blocked on
  a premise now known to be false, and a registry that says "unverifiable" about
  something a command verifies in ninety seconds.
- **Commit the model** alongside the other artefacts, per 0002. Costs: 7.8 MB
  against a 500 KB `check-added-large-files` cap, and a vendor binary with a
  published checksum is not something this repository authors — the reasoning in
  0002 does not transfer.
- **Fetch it at deploy time** into this origin, sha256-verified, and load the
  runtime through a dynamic import. Costs: a deploy step that can be skipped.

## Decision

Fetch at deploy time (`scripts/fetch_hand_model.py`). Its absence is a *state* —
`landmarkStatus` reports `unconfigured` and says pointer gestures still work —
rather than a break, which is what makes the deploy step safe to skip.

## Consequences

Makes the two `vision.*` rows live, and §4's derived presence roll-up with them:
233/233. Makes the model a deployment artifact that must be fetched per
environment. Costs nothing to an operator who never enables camera gestures —
the runtime is a separate lazy chunk and the main bundle is byte-identical.

## Evidence

`npm run prove:hands` — phase 1 reads 21 landmarks from MediaPipe's own
photograph of a hand through the production `HandDetector`, model served from
this origin; phase 2 drives getUserMedia to `recogniseGesture` off a fake camera
and gets a mirrored `swipe_left`. Recorded in MASTER_OUTSTANDING §E21.
