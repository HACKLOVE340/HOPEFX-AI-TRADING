/**
 * hub/handDetector.ts — the producer §18's two `vision.` rows were missing.
 *
 * `landmarks.ts` shipped everything on either side of a hand-landmark detector
 * and, deliberately, not the detector. The recorded reason (AI_HUB_DECISIONS.md,
 * Phase I5) was never the dependency — npm is reachable and the package is one
 * install away — but that **there was no camera to execute it against**, and
 * putting a runtime plus an eight-megabyte model into a platform that moves
 * money without running either once is committing code on faith.
 *
 * That reason is now false, and it was measured rather than argued away.
 * `npm run prove:hands` drives the real MediaPipe detector in real Chromium
 * against MediaPipe's own photograph of a hand, with the model served from this
 * origin, and reads back 21 landmarks. The transcript is the evidence for both
 * registry rows.
 *
 * ## The runtime is not paid for by an operator who never asks for it
 *
 * The MediaPipe vision bundle plus its WASM is tens of megabytes. Importing it
 * at module scope would put that in front of every operator who opens a trading
 * console, including the overwhelming majority who will never wave at it. So it
 * arrives through a dynamic `import()` inside `start()` — a separate chunk, on
 * demand — and `handRuntime.ts` exists so this module can be unit-tested without
 * pulling any of it in.
 *
 * ## The order of the refusals is the security property
 *
 * Consent is checked BEFORE the runtime loads and before anything touches a
 * camera. A detector that opens the camera and then asks has already opened the
 * camera, and "we checked afterwards" is not consent. §25's rule holds here in
 * its strictest form: undefined is refusal.
 *
 * The model URL is checked first of all, and a third-party URL throws rather
 * than degrading — see `resolveModelUrl`. A model that quietly failed to load
 * would present as `unsupported`, and somebody would go hunting for a browser
 * fault that does not exist.
 *
 * ## `measured` means landmarks arrived
 *
 * Not "the detector started". Starting proves the runtime loaded; it says
 * nothing about whether the camera is pointed at a wall. Reporting `measured`
 * on start is the same defect as a gate that reports success for work that did
 * not happen, and §22 is explicit that the four states must stay distinguishable.
 */

import {
  HAND_LANDMARK_COUNT,
  isUsableHand,
  landmarkStatus,
  resolveModelUrl,
  type HandFrame,
  type Landmark,
  type LandmarkStatus,
} from './landmarks';

/** The slice of MediaPipe's `HandLandmarker` this module actually uses. */
export interface HandLandmarkerLike {
  detectForVideo(input: unknown, timestampMs: number): { landmarks: Landmark[][] };
  close(): void;
}

/**
 * Loads a detector for a model URL. Injected so the unit suite never imports
 * the real runtime, and so a browser proof can supply the real one.
 */
export type RuntimeLoader = (modelUrl: string) => Promise<HandLandmarkerLike>;

export interface DetectorOptions {
  /** A same-origin model URL. Empty or absent means none is deployed. */
  modelUrl?: string;
  /** The origin to judge `modelUrl` against. */
  origin: string;
  /** §25's camera consent. Undefined is NOT consent. */
  consented?: boolean;
  loadRuntime?: RuntimeLoader;
}

async function defaultLoader(modelUrl: string): Promise<HandLandmarkerLike> {
  const { loadHandLandmarker } = await import('./handRuntime');
  return loadHandLandmarker(modelUrl);
}

export class HandDetector {
  private readonly options: DetectorOptions;
  private readonly loadRuntime: RuntimeLoader;
  private detector: HandLandmarkerLike | null = null;
  /** Whether the runtime load was ever ATTEMPTED. Undefined-vs-false matters. */
  private probed = false;
  private receiving = false;
  private closed = false;

  constructor(options: DetectorOptions) {
    this.options = options;
    this.loadRuntime = options.loadRuntime ?? defaultLoader;
  }

  /** What an operator should be told right now. Never claims what it cannot see. */
  status(): LandmarkStatus {
    return landmarkStatus({
      modelUrl: this.options.modelUrl,
      // Undefined until the load is attempted, so `landmarkStatus` reports the
      // consent it is waiting on rather than declaring the browser incapable of
      // running something nobody asked it to run.
      runtimeAvailable: this.probed ? this.detector !== null : undefined,
      consented: this.options.consented,
      receiving: this.receiving,
    });
  }

  /**
   * Bring the detector up, or say precisely which of the four absences this is.
   *
   * Throws only for a refused model URL, which is a deployment mistake rather
   * than a state an operator can be in.
   */
  async start(): Promise<LandmarkStatus> {
    if (this.detector !== null || this.closed) return this.status();

    // First, because a bad model URL is a misconfiguration, not a state.
    const url = resolveModelUrl(this.options.modelUrl, this.options.origin);
    if (!url) return this.status(); // unconfigured

    // Before the runtime and before any camera. Undefined is refusal.
    if (this.options.consented !== true) return this.status(); // unpermitted

    this.probed = true;
    try {
      this.detector = await this.loadRuntime(url);
    } catch {
      // Deliberately not re-thrown. "This browser cannot run it" is a state the
      // operator is in, and the four states exist so it can be told apart from
      // "no model deployed" and "you have not said yes".
      this.detector = null;
    }
    return this.status();
  }

  /**
   * One frame in, one hand out — or null, which is an answer.
   *
   * Null covers three different things on purpose: nothing was detected, what
   * was detected is not a whole hand (`isUsableHand`), or this detector is not
   * running. Downstream, `trackFromHands` drops nulls rather than interpolating,
   * because inventing the missing points invents the gesture that spans them.
   */
  read(input: unknown, at: number): HandFrame | null {
    if (this.detector === null || this.closed) return null;

    let landmarks: Landmark[][];
    try {
      landmarks = this.detector.detectForVideo(input, at).landmarks ?? [];
    } catch {
      return null;
    }

    const first = landmarks[0];
    if (!first || first.length !== HAND_LANDMARK_COUNT) return null;

    const frame: HandFrame = { landmarks: first, at };
    if (!isUsableHand(frame)) return null;

    this.receiving = true;
    return frame;
  }

  /**
   * Release the runtime. Idempotent, because a double close is a crash.
   *
   * `probed` is reset, and that is not tidying. Leaving it set made a closed
   * detector report `unsupported` — an operator who switched camera gestures
   * OFF was told their browser could not run them. Closing measures nothing
   * about the runtime, so the honest report is the one from before it started.
   * Found by `npm run prove:hands`, which printed `closedState: "unsupported"`.
   */
  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.probed = false;
    this.receiving = false;
    const detector = this.detector;
    this.detector = null;
    detector?.close();
  }
}
