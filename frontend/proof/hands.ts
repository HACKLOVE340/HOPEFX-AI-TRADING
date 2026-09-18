/**
 * The evidence for §18's two `vision.` rows.
 *
 * Both were staged for one recorded reason: there was no camera to execute a
 * hand-landmark model against, and shipping a runtime plus an 8 MB model into a
 * platform that moves money without running either once is committing code on
 * faith. This page removes that reason by running it.
 *
 * It imports the PRODUCTION modules — `HandDetector`, `loadHandLandmarker`,
 * `pointingPoint`, `trackFromHands`, `pointingAt` — because a proof built from
 * a parallel copy proves the copy. The model and the WASM are served from this
 * origin by `scripts/fetch_hand_model.py`, so `resolveModelUrl`'s third-party
 * refusal is exercised rather than bypassed.
 *
 * The input is MediaPipe's own photograph of a hand rather than a synthetic
 * one: a drawn hand would test whether the model tolerates a drawing.
 */

import { HandDetector } from '../src/hub/handDetector';
import { loadHandLandmarker, DEFAULT_MODEL_PATH } from '../src/hub/handRuntime';
import { pointingAt } from '../src/hub/gestures';
import { SceneGraph } from '../src/hub/sceneGraph';
import { trackFromHands, type HandFrame } from '../src/hub/landmarks';
import { drawHand } from './draw';

declare global {
  interface Window {
    __proof: unknown;
  }
}

const VIEWPORT = { width: 1280, height: 720 };

async function run() {
  const image = document.getElementById('hand') as HTMLImageElement;
  await image.decode();

  const detector = new HandDetector({
    modelUrl: DEFAULT_MODEL_PATH,
    origin: window.location.origin,
    consented: true,
    loadRuntime: loadHandLandmarker,
  });

  const started = await detector.start();

  // Several timestamps, because the runtime is in VIDEO mode and the thing
  // downstream is a track. One frame would prove the detector and not the
  // pipeline.
  const frames: HandFrame[] = [];
  for (let i = 0; i < 5; i += 1) {
    const frame = detector.read(image, 1000 + i * 33);
    if (frame) frames.push(frame);
  }

  const track = trackFromHands(frames, VIEWPORT);

  // Two panels side by side, so the answer distinguishes a real hit test from
  // "returns the only thing it was given".
  const scene = new SceneGraph();
  scene.place('gold-chart', { x: 0, y: 0, width: 640, height: 720 });
  scene.place('order-ticket', { x: 640, y: 0, width: 640, height: 720 });
  const last = track[track.length - 1];
  const pointed = last ? pointingAt(scene, last.x, last.y) : null;

  const status = detector.status();

  // Draw it, so the proof is checkable by eye and not only by assertion.
  const canvas = document.createElement('canvas');
  canvas.id = 'shot';
  document.body.appendChild(canvas);
  drawHand(
    canvas,
    image,
    image.naturalWidth,
    image.naturalHeight,
    frames[0]?.landmarks ?? null,
    `${frames[0]?.landmarks.length ?? 0} landmarks - pointing at ${pointed ?? 'nothing'}`,
  );

  detector.close();

  window.__proof = {
    ok: frames.length > 0,
    startedState: started.state,
    statusState: status.state,
    statusReason: status.reason,
    framesRead: frames.length,
    landmarksPerFrame: frames[0]?.landmarks.length ?? 0,
    trackPoints: track.length,
    firstPoint: track[0] ?? null,
    pointingAt: pointed,
    closedState: detector.status().state,
  };
}

run().catch((error) => {
  window.__proof = { ok: false, error: String((error as Error)?.stack ?? error) };
});
