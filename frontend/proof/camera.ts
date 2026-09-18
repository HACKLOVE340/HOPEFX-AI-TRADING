/**
 * The second half of §18's evidence: the path an operator actually uses.
 *
 * `proof/hands.ts` proves the DETECTOR against a still photograph. This proves
 * the CHAIN — getUserMedia → <video> → HandDetector → HandGestureSource →
 * recogniseGesture — because shipping that chain unexecuted would be the same
 * faith-based commit that kept these rows staged.
 *
 * Chromium serves `proof/swipe.y4m` as the camera, so the CAMERA is the only
 * synthetic part. The hand in those frames is MediaPipe's own photograph,
 * translated across the frame by `scripts/make_swipe_y4m.py`.
 *
 * The expected answer is `swipe_left`, not `swipe_right`. The hand moves left
 * to right in the video and the console mirrors the camera, because an operator
 * is looking at their own reflection — so the mirroring is part of what this
 * checks rather than an incidental detail.
 */

import { HandDetector } from '../src/hub/handDetector';
import { HandGestureSource } from '../src/hub/handGestureSource';
import { loadHandLandmarker, DEFAULT_MODEL_PATH } from '../src/hub/handRuntime';
import { recogniseGesture, type TrackPoint } from '../src/hub/gestures';
import { startTicker } from '../src/hub/backgroundTicker';
import { drawHand } from './draw';
import type { Landmark } from '../src/hub/landmarks';

declare global {
  interface Window {
    __proof: unknown;
  }
}

const VIEWPORT = { width: 1280, height: 720 };

async function run() {
  const video = document.getElementById('camera') as HTMLVideoElement;
  const stream = await navigator.mediaDevices.getUserMedia({ video: true });
  video.srcObject = stream;
  await video.play();

  const detector = new HandDetector({
    modelUrl: DEFAULT_MODEL_PATH,
    origin: window.location.origin,
    consented: true,
    loadRuntime: loadHandLandmarker,
  });
  await detector.start();

  const tracks: TrackPoint[][] = [];
  /** Whether the document was hidden when each track completed. */
  const trackHidden: boolean[] = [];
  let lastLandmarks: readonly Landmark[] | null = null;

  // Wrap the detector so the proof can keep one frame's landmarks to draw.
  // Wrapping rather than reaching inside: `HandGestureSource` reads the
  // narrow `FrameReader` interface, which is what makes this possible without
  // a test hook in production code.
  const observed = {
    read: (input: unknown, at: number) => {
      const frame = detector.read(input, at);
      if (frame) lastLandmarks = frame.landmarks;
      return frame;
    },
    close: () => detector.close(),
  };

  const source = new HandGestureSource({
    detector: observed,
    viewport: VIEWPORT,
    onTrack: (points) => {
      tracks.push(points);
      trackHidden.push(document.visibilityState === 'hidden');
    },
  });

  // Driven by `startTicker`, the same production loop the hook uses, and NOT by
  // requestAnimationFrame — rAF stops firing in a hidden tab, which is the whole
  // thing this phase exists to check. The driver hides this page part-way
  // through; frames read after that are the evidence.
  const started = performance.now();
  let framesSeen = 0;
  let framesWhileHidden = 0;
  const visibilitySeen = new Set<string>();
  document.addEventListener('visibilitychange', () => visibilitySeen.add(document.visibilityState));
  const ticker = startTicker(33, () => {
    visibilitySeen.add(document.visibilityState);
    if (document.visibilityState === 'hidden') framesWhileHidden += 1;
    source.onFrame(video, performance.now());
    framesSeen += 1;
  });
  await new Promise<void>((resolve) => {
    const check = setInterval(() => {
      if (performance.now() - started > 9000) {
        clearInterval(check);
        ticker.stop();
        resolve();
      }
    }, 100);
  });

  const statusBeforeStop = detector.status();

  const canvas = document.createElement('canvas');
  canvas.id = 'shot';
  document.body.appendChild(canvas);
  const gesturesSoFar = tracks.map((points) => recogniseGesture(points));
  drawHand(
    canvas,
    video,
    video.videoWidth || 640,
    video.videoHeight || 480,
    lastLandmarks,
    `camera - ${tracks.length} track(s) - ${gesturesSoFar.filter(Boolean).join(', ') || 'no gesture yet'}`,
  );

  source.stop();
  for (const track of stream.getTracks()) track.stop();

  const gestures = tracks.map((points) => recogniseGesture(points));

  window.__proof = {
    ok: tracks.length > 0,
    tickerKind: ticker.kind,
    framesSeen,
    framesWhileHidden,
    visibilitySeen: [...visibilitySeen],
    hasFocus: document.hasFocus(),
    gesturesWhileHidden: gestures.filter((g, i) => g !== null && trackHidden[i]),
    videoSize: { width: video.videoWidth, height: video.videoHeight },
    statusBeforeStop: statusBeforeStop.state,
    tracks: tracks.length,
    longestTrack: tracks.reduce((best, t) => Math.max(best, t.length), 0),
    // Reported because a null gesture is otherwise undiagnosable: a track can
    // fail SWIPE_MAX_MS, SWIPE_DISTANCE or AXIS_DOMINANCE and look identical.
    trackSpans: tracks.map((t) => Math.round((t[t.length - 1]?.t ?? 0) - (t[0]?.t ?? 0))),
    trackTravelX: tracks.map((t) => Math.round((t[t.length - 1]?.x ?? 0) - (t[0]?.x ?? 0))),
    gestures,
    recognised: gestures.filter((g) => g !== null),
  };
}

run().catch((error) => {
  window.__proof = { ok: false, error: String((error as Error)?.stack ?? error) };
});
