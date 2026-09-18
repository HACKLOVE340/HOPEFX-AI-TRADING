/**
 * hub/handDetector.ts — the one thing §18's two `vision.` rows were missing.
 *
 * `landmarks.ts` shipped everything on either side of a hand-landmark detector:
 * `resolveModelUrl` refuses a third-party model, `isUsableHand` refuses a
 * partial one, `pointingPoint` mirrors the front camera, and `trackFromHands`
 * turns a run of frames into the same `TrackPoint[]` that `recogniseGesture`
 * has read since Phase E2. What it deliberately did not contain was anything
 * that produces a `HandFrame`.
 *
 * The recorded reason (AI_HUB_DECISIONS.md, Phase I5) was not the dependency —
 * npm is reachable — but that **there was no camera to execute it against**, and
 * shipping a runtime plus a model into a money-moving platform without running
 * either once is committing code on faith.
 *
 * That reason is now measurably false. `npm run prove:hands` runs the real
 * MediaPipe detector, in real Chromium, against MediaPipe's own hand photograph,
 * with the model served from this origin — and gets 21 landmarks. The producer
 * below is therefore built, and the rows can stop being staged.
 *
 * These tests hold the parts that a browser run cannot: the refusals. A detector
 * is mostly refusals, and each one here is a defect if it goes the other way.
 */

import { describe, expect, it, vi } from 'vitest';

import { HandDetector, type HandLandmarkerLike } from '../hub/handDetector';
import { HAND_LANDMARK_COUNT, ModelUrlRefused } from '../hub/landmarks';

const ORIGIN = 'https://console.hopefx.test';
const MODEL = '/models/hand_landmarker.task';

function hand(x = 0.5, y = 0.5) {
  return Array.from({ length: HAND_LANDMARK_COUNT }, (_, i) => ({ x: i === 8 ? x : 0.4, y: i === 8 ? y : 0.6 }));
}

function fakeRuntime(landmarks: Array<ReturnType<typeof hand>> = [hand()]) {
  const closed = { count: 0 };
  const loader = vi.fn(
    async (): Promise<HandLandmarkerLike> => ({
      detectForVideo: () => ({ landmarks }),
      close: () => {
        closed.count += 1;
      },
    }),
  );
  return { loader, closed };
}

describe('the runtime is not paid for by an operator who never asks for it', () => {
  it('does not load anything on construction', () => {
    const { loader } = fakeRuntime();
    new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    expect(loader).not.toHaveBeenCalled();
  });

  it('does not load anything when no model is deployed', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ origin: ORIGIN, consented: true, loadRuntime: loader });
    expect((await detector.start()).state).toBe('unconfigured');
    expect(loader).not.toHaveBeenCalled();
  });
});

describe('consent is checked before the camera, not after', () => {
  it('refuses without consent and never loads the runtime', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, loadRuntime: loader });
    const status = await detector.start();
    expect(status.state).toBe('unpermitted');
    expect(loader).not.toHaveBeenCalled();
  });

  it('treats undefined consent as refusal', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({
      modelUrl: MODEL,
      origin: ORIGIN,
      consented: undefined,
      loadRuntime: loader,
    });
    expect((await detector.start()).state).toBe('unpermitted');
  });
});

describe('a model comes from this origin or not at all', () => {
  it('refuses a third-party model loudly', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({
      modelUrl: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker.task',
      origin: ORIGIN,
      consented: true,
      loadRuntime: loader,
    });
    await expect(detector.start()).rejects.toBeInstanceOf(ModelUrlRefused);
    expect(loader).not.toHaveBeenCalled();
  });
});

describe('a runtime this browser cannot run is unsupported, not broken', () => {
  it('reports unsupported when the runtime fails to load', async () => {
    const detector = new HandDetector({
      modelUrl: MODEL,
      origin: ORIGIN,
      consented: true,
      loadRuntime: async () => {
        throw new Error('WebAssembly.instantiate is not a function');
      },
    });
    const status = await detector.start();
    expect(status.state).toBe('unsupported');
    expect(status.reason).toContain('cannot run it');
  });
});

describe('measured means landmarks actually arrived', () => {
  it('is not measured on start alone', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    const status = await detector.start();
    expect(status.state).toBe('unpermitted');
    expect(status.reason).toContain('no landmarks have arrived');
  });

  it('becomes measured after a whole hand is read', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    await detector.start();
    const frame = detector.read({} as never, 1000);
    expect(frame).not.toBeNull();
    expect(frame?.landmarks).toHaveLength(HAND_LANDMARK_COUNT);
    expect(frame?.at).toBe(1000);
    expect(detector.status().state).toBe('measured');
  });

  it('a partial hand is not a hand, and does not make it measured', async () => {
    const { loader } = fakeRuntime([hand().slice(0, 5)]);
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    await detector.start();
    expect(detector.read({} as never, 1000)).toBeNull();
    expect(detector.status().state).not.toBe('measured');
  });

  it('an empty detection is null rather than a guess', async () => {
    const { loader } = fakeRuntime([]);
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    await detector.start();
    expect(detector.read({} as never, 1000)).toBeNull();
  });

  it('reading before start is null, not a crash', () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    expect(detector.read({} as never, 1)).toBeNull();
  });
});

describe('closing releases what was opened', () => {
  it('closes the underlying detector exactly once', async () => {
    const { loader, closed } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    await detector.start();
    detector.close();
    detector.close();
    expect(closed.count).toBe(1);
  });

  it('stops reading once closed, rather than using a freed detector', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    await detector.start();
    detector.close();
    expect(detector.read({} as never, 1)).toBeNull();
    expect(detector.status().state).not.toBe('measured');
  });

  it('a closed detector does not claim the browser is incapable', async () => {
    // Caught by `npm run prove:hands`, which reported `closedState:
    // "unsupported"` — an operator who switches camera gestures OFF was told
    // their browser could not run them, and would go looking for a fault that
    // is not there. Exactly the defect this detector was built to stop
    // `landmarkStatus` making one layer up.
    //
    // Closing un-probes: nothing has been measured about the runtime any more,
    // so the honest report is the one from before it started.
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    await detector.start();
    detector.read({} as never, 1000);
    expect(detector.status().state).toBe('measured');

    detector.close();
    const status = detector.status();
    expect(status.state).not.toBe('unsupported');
    expect(status.state).not.toBe('measured');
    expect(status.reason).not.toContain('cannot run it');
  });

  it('starting twice does not open a second runtime', async () => {
    const { loader } = fakeRuntime();
    const detector = new HandDetector({ modelUrl: MODEL, origin: ORIGIN, consented: true, loadRuntime: loader });
    await detector.start();
    await detector.start();
    expect(loader).toHaveBeenCalledTimes(1);
  });
});
