/**
 * Phase I5 — §18's camera half, as far as it can honestly be taken.
 *
 * The owner's answer to the supply-chain question was: if shipping it does not
 * spoil things, ship it. The honest reading of that, having checked:
 *
 * Adding the detector WOULD spoil something, and not because of the dependency
 * — npm is reachable and the package is one install away. It is that **there is
 * no camera in the environment this was built in**, so a two-megabyte runtime
 * and an eight-megabyte model would go into a money-moving platform having
 * never executed once. "Prove by execution, not by reading" is the rule that
 * forbids exactly that, and it is not a rule to suspend because a row is close
 * to closing.
 *
 * So everything AROUND the gap ships, proven against synthetic landmarks, and
 * installing a detector becomes configuration rather than code.
 *
 * ## A hand is a source, not a second pipeline
 *
 * Phase I3 wired `recogniseGesture` and `pointingAt`. A parallel camera
 * pipeline would give the console two ways to decide what a swipe is, and they
 * would eventually disagree. So a hand becomes a `TrackPoint[]` and everything
 * downstream is code that already ships and is already proven.
 */

import { describe, expect, it } from 'vitest';

import {
  HAND_LANDMARK_COUNT,
  INDEX_FINGERTIP,
  LANDMARK_STATES,
  ModelUrlRefused,
  describeLandmarks,
  isUsableHand,
  landmarkStatus,
  pointingPoint,
  resolveModelUrl,
  trackFromHands,
  type HandFrame,
  type Landmark,
} from '../hub/landmarks';
import { MAX_TRACK_POINTS, recogniseGesture } from '../hub/gestures';

const VIEWPORT = { width: 1600, height: 900 };

/** A whole hand with the fingertip placed where the test wants it. */
function hand(tipX: number, tipY: number, at = 0): HandFrame {
  const landmarks: Landmark[] = Array.from({ length: HAND_LANDMARK_COUNT }, () => ({ x: 0.5, y: 0.5 }));
  landmarks[INDEX_FINGERTIP] = { x: tipX, y: tipY };
  return { landmarks, at };
}

describe('§18 four states, because three of them are not "off"', () => {
  it('names all four rather than one boolean', () => {
    expect([...LANDMARK_STATES]).toEqual(['unconfigured', 'unsupported', 'unpermitted', 'measured']);
  });

  it('says unconfigured when no model is deployed, and says pointer input still works', () => {
    // The state this deployment is actually in. An operator whose camera
    // gesture does nothing needs to know it is not their hardware.
    const status = landmarkStatus({});
    expect(status.state).toBe('unconfigured');
    expect(status.reason).toMatch(/pointer/i);
  });

  it('distinguishes a browser that cannot run it from a model that is absent', () => {
    // Was `.toBe('unsupported')`, which asserted a defect: it reported a
    // runtime nobody had probed as one this browser cannot run. See
    // hub_landmark_states_are_measured.test.ts. `unsupported` now requires
    // `runtimeAvailable: false` — probed, and failed.
    expect(landmarkStatus({ modelUrl: '/m.task', runtimeAvailable: false, consented: true }).state).toBe(
      'unsupported',
    );
    expect(landmarkStatus({ modelUrl: '/m.task', runtimeAvailable: true }).state).toBe('unpermitted');
  });

  it('treats undefined consent as refusal, not as consent', () => {
    // §25's rule, and the one place in this module where unreadable means
    // refuse rather than report.
    //
    // `receiving: true` is what makes this test able to fail. Without it the
    // NEXT check also answers `unpermitted`, so the assertion passed whether
    // consent was read as refusal or as permission — which is how the first
    // version of this test survived an injection that granted consent to
    // everybody. The reason string is asserted for the same purpose: two
    // branches return the same state and only one of them is this one.
    const status = landmarkStatus({
      modelUrl: '/m.task',
      runtimeAvailable: true,
      consented: undefined,
      receiving: true,
    });
    expect(status.state).toBe('unpermitted');
    expect(status.reason).toMatch(/not been permitted/i);
  });

  it('does not start reading a camera merely because frames are available', () => {
    // The failure this guards is the worst one in the module: landmarks
    // arriving from a camera nobody agreed to open.
    for (const consented of [undefined, false]) {
      const status = landmarkStatus({
        modelUrl: '/m.task',
        runtimeAvailable: true,
        consented,
        receiving: true,
      });
      expect(status.state).not.toBe('measured');
    }
  });

  it('is measured only once landmarks are actually arriving', () => {
    const nearly = landmarkStatus({ modelUrl: '/m.task', runtimeAvailable: true, consented: true });
    expect(nearly.state).toBe('unpermitted');
    expect(nearly.reason).toMatch(/no landmarks/i);

    const real = landmarkStatus({
      modelUrl: '/m.task',
      runtimeAvailable: true,
      consented: true,
      receiving: true,
    });
    expect(real.state).toBe('measured');
    expect(real.reason).toBe('');
  });

  it('says which state it is in, every time, without leaking undefined', () => {
    for (const state of LANDMARK_STATES) {
      const said = describeLandmarks({ state, reason: 'because' });
      expect(said.length).toBeGreaterThan(0);
      expect(said).not.toMatch(/undefined|null/);
    }
  });
});

describe('§18 a model comes from this origin or not at all', () => {
  const ORIGIN = 'https://console.example.com';

  it('accepts a same-origin absolute path', () => {
    expect(resolveModelUrl('/models/hand.task', ORIGIN)).toBe('/models/hand.task');
  });

  it('accepts a full URL on this origin', () => {
    expect(resolveModelUrl(`${ORIGIN}/models/hand.task`, ORIGIN)).toBe(`${ORIGIN}/models/hand.task`);
  });

  it('refuses the CDN URL the vendor documentation hands you', () => {
    // The default way to ship this is a storage.googleapis.com URL in a
    // constructor. That has a trading console fetch from a third party on the
    // operator's behalf — a runtime dependency on a host nobody here controls,
    // and a signal to that host every time this desk opens its console.
    expect(() =>
      resolveModelUrl('https://storage.googleapis.com/mediapipe-models/hand_landmarker.task', ORIGIN),
    ).toThrow(ModelUrlRefused);
  });

  it('refuses a protocol-relative URL, which reads as a path and is not one', () => {
    expect(() => resolveModelUrl('//evil.example.com/hand.task', ORIGIN)).toThrow(ModelUrlRefused);
  });

  it('treats an unset value as unconfigured rather than throwing', () => {
    // Not deploying a model is the normal case, not an error.
    expect(resolveModelUrl(undefined, ORIGIN)).toBe('');
    expect(resolveModelUrl('   ', ORIGIN)).toBe('');
  });

  it('refuses loudly rather than falling back to no model', () => {
    // A misconfigured URL that silently became "unconfigured" would send
    // somebody looking for a deployment problem that had already been detected.
    let threw = false;
    try {
      resolveModelUrl('http://other.example.com/hand.task', ORIGIN);
    } catch (error) {
      threw = true;
      expect((error as Error).message).toMatch(/origin/i);
    }
    expect(threw).toBe(true);
  });
});

describe('§18 a partial detection is not a hand', () => {
  it('accepts a whole hand', () => {
    expect(isUsableHand(hand(0.5, 0.5))).toBe(true);
  });

  it('rejects a few points found under a bad light', () => {
    // Treating a low-confidence handful of points as a hand is how a gesture
    // happens that nobody made.
    expect(isUsableHand({ landmarks: [{ x: 0.5, y: 0.5 }], at: 0 })).toBe(false);
  });

  it('rejects coordinates outside the frame and non-finite ones', () => {
    const off = hand(1.5, 0.5);
    expect(isUsableHand(off)).toBe(false);
    const nan = hand(Number.NaN, 0.5);
    expect(isUsableHand(nan)).toBe(false);
  });

  it('rejects nothing at all without throwing', () => {
    expect(isUsableHand(null)).toBe(false);
    expect(isUsableHand(undefined)).toBe(false);
  });
});

describe('§18 pointing, in the pixels the scene graph already speaks', () => {
  it('uses the index fingertip rather than the wrist', () => {
    const frame = hand(0.25, 0.5);
    const point = pointingPoint(frame, VIEWPORT, false);
    expect(point).not.toBeNull();
    expect(point!.x).toBeCloseTo(0.25 * VIEWPORT.width);
  });

  it('mirrors by default, because a front camera shows a reflection', () => {
    // Moving a hand right moves the reflection left. A console that followed
    // the raw coordinate would move focus the opposite way from the gesture.
    const point = pointingPoint(hand(0.25, 0.5), VIEWPORT)!;
    expect(point.x).toBeCloseTo(0.75 * VIEWPORT.width);
  });

  it('answers null for something that is not a hand', () => {
    expect(pointingPoint({ landmarks: [], at: 0 }, VIEWPORT)).toBeNull();
  });
});

describe('§18 a hand becomes the track the recogniser already reads', () => {
  it('produces a swipe the existing recogniser recognises', () => {
    // The whole design in one assertion: nothing downstream of here is new.
    const frames = [hand(0.7, 0.5, 1_000), hand(0.5, 0.5, 1_080), hand(0.2, 0.5, 1_160)];
    const track = trackFromHands(frames, VIEWPORT);
    // Mirrored, so a hand moving LEFT across the sensor is a swipe right.
    expect(recogniseGesture(track)).toBe('swipe_right');
  });

  it('makes time relative, or every gesture is one very long press', () => {
    const frames = [hand(0.7, 0.5, 1_700_000_000_000), hand(0.2, 0.5, 1_700_000_000_100)];
    const track = trackFromHands(frames, VIEWPORT);
    expect(track[0]!.t).toBe(0);
    expect(track[track.length - 1]!.t).toBe(100);
  });

  it('drops frames where the hand was lost rather than interpolating them', () => {
    // A gap in the detection is a gap. Inventing the missing points invents
    // the gesture that spans them.
    const frames = [hand(0.7, 0.5, 0), { landmarks: [], at: 50 }, hand(0.2, 0.5, 100)];
    const track = trackFromHands(frames, VIEWPORT);
    expect(track).toHaveLength(2);
  });

  it('is bounded by the same cap as pointer input', () => {
    // A camera at 60Hz fills a track faster than a finger does, so the bound
    // matters more here, not less.
    const frames = Array.from({ length: 5_000 }, (_, i) => hand(0.5, 0.5, i));
    expect(trackFromHands(frames, VIEWPORT).length).toBeLessThanOrEqual(MAX_TRACK_POINTS);
  });

  it('returns an empty track when no frame was a hand', () => {
    expect(trackFromHands([{ landmarks: [], at: 0 }], VIEWPORT)).toEqual([]);
  });
});
