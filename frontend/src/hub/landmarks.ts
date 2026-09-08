/**
 * hub/landmarks.ts — §18's camera half, as far as it can honestly be taken.
 *
 * The two `vision.` rows were staged with one thing genuinely missing: a source
 * of hand landmarks. That is still true, and this module is deliberately not a
 * landmark detector. It is everything on either side of one.
 *
 * ## Why the model is not vendored here
 *
 * The dependency is one `npm install` away and the registry is reachable, so
 * this is a judgement rather than a blocker: **there is no camera in the
 * environment this was built in.** Adding a two-megabyte runtime plus an
 * eight-megabyte model to a platform that moves money, and never executing it
 * once, is committing code on faith — which is the thing this repository's
 * rules exist to stop. `AI_HUB_DECISIONS.md` records the call.
 *
 * What is here instead is the whole pipeline around the gap, proven against
 * synthetic landmarks, so that installing a detector is a configuration change
 * rather than a code change.
 *
 * ## Landmarks are a SOURCE, not a second pipeline
 *
 * Phase I3 wired pointer input to `recogniseGesture` and `pointingAt`. A hand
 * is another way of producing the same `TrackPoint`s. Building a parallel
 * camera pipeline would give the console two ways to decide what a swipe is,
 * and they would eventually disagree — so a hand becomes a track, and
 * everything downstream is the code that already ships.
 *
 * ## Four states, because three of them are not "off"
 *
 *   `unconfigured`  no model has been deployed; nobody asked for this
 *   `unsupported`   a model is named and this browser cannot run it
 *   `unpermitted`   it could run and the operator has not consented
 *   `measured`      landmarks are arriving
 *
 * Collapsing these is §22's rule broken in the place it matters most. An
 * operator whose camera gesture does nothing needs to know WHICH of those four
 * it is; "not working" sends them to look for a fault that is not there.
 *
 * ## A model is loaded from this origin or not at all
 *
 * `resolveModelUrl` refuses anything that is not same-origin. The usual way to
 * ship this is a `storage.googleapis.com` URL in a constructor, and that would
 * make a trading console call a third-party CDN on the operator's behalf —
 * telling someone else's server when this desk opens its console, and putting a
 * runtime dependency on a host nobody here controls in front of a feature.
 * Self-hosted or absent.
 */

import { appendPoint, type TrackPoint } from './gestures';

export const LANDMARK_STATES = ['unconfigured', 'unsupported', 'unpermitted', 'measured'] as const;
export type LandmarkState = (typeof LANDMARK_STATES)[number];

/** One landmark, normalised 0..1 across the frame. The MediaPipe convention. */
export interface Landmark {
  x: number;
  y: number;
  z?: number;
}

/**
 * The index fingertip in the hand-landmark topology.
 *
 * Named rather than inlined because `landmarks[8]` at a call site is a magic
 * number that reads as correct while pointing at the wrong knuckle.
 */
export const INDEX_FINGERTIP = 8;
export const WRIST = 0;

/** Landmarks must be a full hand. A partial hand is a detection, not a hand. */
export const HAND_LANDMARK_COUNT = 21;

export interface HandFrame {
  landmarks: readonly Landmark[];
  /** Milliseconds, on the same clock the pointer track uses. */
  at: number;
}

export interface LandmarkStatus {
  state: LandmarkState;
  /** Empty when measured. Says which absence this is otherwise. */
  reason: string;
}

export interface StatusInput {
  /** A same-origin model URL, or empty when none is deployed. */
  modelUrl?: string;
  /** Whether this browser can run the detector at all. */
  runtimeAvailable?: boolean;
  /** §25's camera consent. Undefined is NOT consent. */
  consented?: boolean;
  /** Whether landmarks are actually arriving. */
  receiving?: boolean;
}

export function landmarkStatus(input: StatusInput = {}): LandmarkStatus {
  if (!input.modelUrl) {
    return {
      state: 'unconfigured',
      reason:
        'no hand-landmark model is deployed, so the camera cannot be asked what your hand is doing; ' +
        'pointer gestures work regardless',
    };
  }
  if (input.runtimeAvailable !== true) {
    // Not `!== false`. An unmeasured runtime is absent, never present.
    return {
      state: 'unsupported',
      reason: 'a model is deployed and this browser cannot run it',
    };
  }
  if (input.consented !== true) {
    // Undefined is not consent. §25 holds the same rule, and it is the one
    // place in this file where unreadable means refuse rather than report.
    return {
      state: 'unpermitted',
      reason: 'the camera has not been permitted for this, and opening the app is not permission',
    };
  }
  if (input.receiving !== true) {
    return {
      state: 'unpermitted',
      reason: 'the camera is permitted and no landmarks have arrived yet',
    };
  }
  return { state: 'measured', reason: '' };
}

/** The status in a sentence, for an operator. Never claims what it does not know. */
export function describeLandmarks(status: LandmarkStatus): string {
  if (status.state === 'measured') return 'Reading hand position from the camera.';
  return `Hand gestures are off — ${status.reason}.`;
}

export class ModelUrlRefused extends Error {}

/**
 * Accept a model URL only if it is served from this origin.
 *
 * The default way to ship a MediaPipe task is a URL on a public CDN. That
 * would have a trading console fetch from a third party on the operator's
 * behalf: a runtime dependency on a host nobody here controls, in front of a
 * feature, and a signal to that host every time this desk opens its console.
 *
 * Refused loudly rather than silently ignored: a model that quietly did not
 * load would present as `unsupported`, and somebody would go looking for a
 * browser problem.
 */
export function resolveModelUrl(raw: string | undefined, origin: string): string {
  if (!raw || !raw.trim()) return '';
  const value = raw.trim();

  if (value.startsWith('/') && !value.startsWith('//')) return value;

  let parsed: URL;
  try {
    parsed = new URL(value, origin);
  } catch {
    throw new ModelUrlRefused(`the landmark model URL "${value}" could not be read as a URL`);
  }
  if (parsed.origin !== new URL(origin).origin) {
    throw new ModelUrlRefused(
      `the landmark model must be served from this origin; ${parsed.origin} is somewhere else, and a ` +
        'trading console does not fetch a model from a third party on an operator behalf',
    );
  }
  return parsed.toString();
}

/**
 * Whether a frame is a whole hand worth trusting.
 *
 * A detector under a bad light returns a few points with low confidence, and
 * treating those as a hand is how a gesture happens that nobody made.
 */
export function isUsableHand(frame: HandFrame | null | undefined): boolean {
  if (!frame || !Array.isArray(frame.landmarks)) return false;
  if (frame.landmarks.length !== HAND_LANDMARK_COUNT) return false;
  return frame.landmarks.every(
    (p) =>
      typeof p?.x === 'number' &&
      typeof p?.y === 'number' &&
      Number.isFinite(p.x) &&
      Number.isFinite(p.y) &&
      p.x >= 0 &&
      p.x <= 1 &&
      p.y >= 0 &&
      p.y <= 1,
  );
}

export interface Viewport {
  width: number;
  height: number;
}

/**
 * Where on the screen a hand is pointing, in the pixels `pointingAt` expects.
 *
 * The index fingertip, because that is what a person means by pointing. Null
 * for anything that is not a whole hand: "I cannot see your hand" is an answer,
 * and the nearest guess is not.
 *
 * MIRRORED, because a front camera shows the operator their own reflection.
 * Moving a hand right moves the reflection left, and a console that followed
 * the raw coordinate would move focus the opposite way from the gesture.
 */
export function pointingPoint(frame: HandFrame, viewport: Viewport, mirrored = true): TrackPoint | null {
  if (!isUsableHand(frame)) return null;
  const tip = frame.landmarks[INDEX_FINGERTIP];
  if (!tip) return null;
  const x = mirrored ? 1 - tip.x : tip.x;
  return { x: x * viewport.width, y: tip.y * viewport.height, t: frame.at };
}

/**
 * Turn a run of hand frames into the track `recogniseGesture` already reads.
 *
 * This is the whole point of the module: a hand is a SOURCE for the pipeline
 * Phase I3 wired, not a second pipeline. Frames that are not a usable hand are
 * dropped rather than interpolated — a gap in the detection is a gap, and
 * inventing the missing points is inventing the gesture that spans them.
 *
 * Times are made relative to the first kept frame, because `recogniseGesture`
 * reads elapsed milliseconds and an absolute clock would make every gesture
 * look like a very long press.
 */
export function trackFromHands(
  frames: readonly HandFrame[],
  viewport: Viewport,
  mirrored = true,
): TrackPoint[] {
  const track: TrackPoint[] = [];
  let origin: number | null = null;
  for (const frame of frames) {
    const point = pointingPoint(frame, viewport, mirrored);
    if (point === null) continue;
    if (origin === null) origin = point.t;
    const relative = { x: point.x, y: point.y, t: point.t - origin };
    if (track.length === 0) track.push(relative);
    else appendPoint(track, relative);
  }
  return track;
}
