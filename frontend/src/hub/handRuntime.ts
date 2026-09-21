/**
 * hub/handRuntime.ts — the only module that imports MediaPipe.
 *
 * Kept apart from `handDetector.ts` for one reason: the vision bundle and its
 * WASM are tens of megabytes, and a unit suite that imports them pays that on
 * every run while proving nothing about them. `handDetector` injects a loader;
 * this is the real one, reached through a dynamic `import()` so the bundler
 * emits it as a separate chunk that an operator downloads only if they turn
 * camera gestures on.
 *
 * ## Everything is served from this origin
 *
 * The documented way to construct a MediaPipe task is to hand it a
 * `storage.googleapis.com` URL for the WASM and another for the model. That
 * would have a trading console fetch executable code from a third party on the
 * operator's behalf, tell that third party whenever this desk opens its
 * console, and put a host nobody here controls in front of a feature.
 *
 * `resolveModelUrl` already refuses a third-party model. This file holds the
 * other half: the WASM base is a path on this origin too. `scripts/fetch_hand_model.py`
 * puts both in place at deploy time.
 *
 * ## VIDEO, not IMAGE
 *
 * The running mode is VIDEO because the pipeline downstream is a *track* — a run
 * of frames that `recogniseGesture` reads as a gesture. IMAGE mode re-detects
 * from scratch each frame and discards the tracking that makes a swipe a swipe.
 */

import type { HandLandmarkerLike } from './handDetector';

/** Where the WASM lives on this origin. Same reasoning as the model URL. */
export const WASM_BASE = '/vendor/tasks-vision/wasm';

/** Where `scripts/fetch_hand_model.py` puts the model on this origin. */
export const DEFAULT_MODEL_PATH = '/models/hand_landmarker.task';

/**
 * One hand, because the console follows one pointer.
 *
 * Two hands would need a rule for which one is pointing, and "whichever was
 * detected first" is not a rule an operator can predict.
 */
export const NUM_HANDS = 1;

export async function loadHandLandmarker(modelUrl: string): Promise<HandLandmarkerLike> {
  const vision = await import('@mediapipe/tasks-vision');
  const fileset = await vision.FilesetResolver.forVisionTasks(WASM_BASE);
  return vision.HandLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: modelUrl },
    numHands: NUM_HANDS,
    runningMode: 'VIDEO',
  }) as unknown as HandLandmarkerLike;
}
