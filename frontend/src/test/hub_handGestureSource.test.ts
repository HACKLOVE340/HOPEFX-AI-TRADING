/**
 * `HandGestureSource` — the camera half of §18, as a state machine.
 *
 * `HandDetector` turns one frame into one hand. This turns a *run* of frames
 * into the completed `TrackPoint[]` that `recogniseGesture` reads, which is the
 * piece that makes a hand a source for the pipeline Phase I3 wired rather than
 * a second pipeline that would eventually disagree with it.
 *
 * ## A hand has no pointer-up
 *
 * The pointer track ends on `pointerup`. A hand never lifts, so the end of a
 * gesture has to be inferred, and the inference is the part worth testing:
 * a run ends when the hand LEAVES, and "leaves" means several consecutive
 * frames with no usable hand rather than one. One dropped detection mid-swipe
 * is ordinary — a hand crossing a shadow — and ending the track there would cut
 * one gesture into two, each too short to recognise.
 *
 * ## Nothing is emitted for a track too short to mean anything
 *
 * Two points is a jitter, not a swipe. Emitting it would have the console act
 * on a hand that was resting.
 */

import { describe, expect, it, vi } from 'vitest';

import { HandGestureSource } from '../hub/handGestureSource';
import { HAND_LANDMARK_COUNT } from '../hub/landmarks';

const VIEWPORT = { width: 1000, height: 500 };

function handAt(x: number, y = 0.5) {
  return Array.from({ length: HAND_LANDMARK_COUNT }, (_, i) => (i === 8 ? { x, y } : { x: 0.4, y: 0.6 }));
}

/** A detector stand-in that plays a scripted list of frames. */
function scripted(script: Array<ReturnType<typeof handAt> | null>) {
  let i = 0;
  return {
    read: (_input: unknown, at: number) => {
      const landmarks = script[i];
      i += 1;
      return landmarks ? { landmarks, at } : null;
    },
    close: vi.fn(),
    status: () => ({ state: 'measured' as const, reason: '' }),
  };
}

function drive(source: HandGestureSource, frames: number) {
  for (let i = 0; i < frames; i += 1) source.onFrame({}, 1000 + i * 33);
}

describe('a run of hands becomes one track', () => {
  it('emits nothing while the hand is still there', () => {
    const emitted: unknown[] = [];
    const source = new HandGestureSource({
      detector: scripted([handAt(0.2), handAt(0.4), handAt(0.6)]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t),
    });
    drive(source, 3);
    expect(emitted).toHaveLength(0);
  });

  it('emits once the hand has left', () => {
    const emitted: Array<{ length: number }> = [];
    const source = new HandGestureSource({
      detector: scripted([handAt(0.2), handAt(0.4), handAt(0.6), null, null, null]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t),
    });
    drive(source, 6);
    expect(emitted).toHaveLength(1);
    expect(emitted[0]!.length).toBe(3);
  });

  it('a single dropped detection does not cut the gesture in two', () => {
    const emitted: Array<{ length: number }> = [];
    const source = new HandGestureSource({
      detector: scripted([handAt(0.2), null, handAt(0.4), handAt(0.6), null, null, null]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t),
    });
    drive(source, 7);
    expect(emitted).toHaveLength(1);
    expect(emitted[0]!.length).toBe(3);
  });

  it('does not emit a track too short for the recogniser to read', () => {
    // One point. `recogniseGesture` returns null below two, and this defers to
    // that rather than holding a second opinion about what a gesture is.
    const emitted: unknown[] = [];
    const source = new HandGestureSource({
      detector: scripted([handAt(0.5), null, null, null]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t),
    });
    drive(source, 4);
    expect(emitted).toHaveLength(0);
  });

  it('emits nothing at all when no hand is ever seen', () => {
    const emitted: unknown[] = [];
    const source = new HandGestureSource({
      detector: scripted([null, null, null, null, null]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t),
    });
    drive(source, 5);
    expect(emitted).toHaveLength(0);
  });

  it('a second gesture after the first is its own track', () => {
    const emitted: Array<{ length: number }> = [];
    const source = new HandGestureSource({
      detector: scripted([
        handAt(0.2), handAt(0.3), handAt(0.4),
        null, null, null,
        handAt(0.7), handAt(0.8),
        null, null, null,
      ]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t),
    });
    drive(source, 11);
    expect(emitted.map((t) => t.length)).toEqual([3, 2]);
  });
});

describe('the track it emits is the one recogniseGesture reads', () => {
  it('is mirrored, in viewport pixels, with time from the first point', () => {
    const emitted: Array<Array<{ x: number; y: number; t: number }>> = [];
    const source = new HandGestureSource({
      detector: scripted([handAt(0.25), handAt(0.75), null, null, null]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t as never),
    });
    drive(source, 5);
    const track = emitted[0]!;
    // Mirrored: a fingertip at 0.25 of a front camera frame is 0.75 across the
    // screen, because the operator is looking at their own reflection.
    expect(track[0]!.x).toBeCloseTo(750);
    expect(track[1]!.x).toBeCloseTo(250);
    expect(track[0]!.t).toBe(0);
    expect(track[1]!.t).toBe(33);
  });
});

describe('stopping', () => {
  it('closes the detector and stops emitting', () => {
    const detector = scripted([handAt(0.2), handAt(0.4), null, null, null]);
    const emitted: unknown[] = [];
    const source = new HandGestureSource({ detector, viewport: VIEWPORT, onTrack: (t) => emitted.push(t) });
    source.onFrame({}, 1000);
    source.stop();
    drive(source, 4);
    expect(detector.close).toHaveBeenCalledTimes(1);
    expect(emitted).toHaveLength(0);
  });

  it('an in-flight gesture is dropped rather than fired on the way out', () => {
    // Firing a half-finished swipe as the operator switches the camera off
    // would move a panel they were reading, after they turned the feature off.
    const emitted: unknown[] = [];
    const source = new HandGestureSource({
      detector: scripted([handAt(0.2), handAt(0.4), handAt(0.6)]),
      viewport: VIEWPORT,
      onTrack: (t) => emitted.push(t),
    });
    drive(source, 3);
    source.stop();
    expect(emitted).toHaveLength(0);
  });
});
