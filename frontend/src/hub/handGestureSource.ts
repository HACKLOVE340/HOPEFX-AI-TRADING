/**
 * hub/handGestureSource.ts — a run of camera frames becomes one gesture track.
 *
 * `HandDetector` answers "what is this one frame". `recogniseGesture` answers
 * "what was that movement". This is the part between them, and it exists so a
 * hand is a SOURCE for the pipeline Phase I3 wired rather than a second
 * pipeline — two ways to decide what a swipe is would eventually disagree, and
 * an operator cannot be told which one their console is using.
 *
 * ## A hand has no pointer-up
 *
 * The pointer track ends on `pointerup`, an event the operator generates. A
 * hand never lifts, so the end of a gesture is inferred: the hand LEAVES.
 *
 * "Leaves" deliberately means several consecutive frames with no usable hand,
 * not one. A single dropped detection mid-swipe is ordinary — a hand crossing a
 * shadow, a frame the model was unsure about — and ending the track there would
 * cut one gesture into two, each too short for `recogniseGesture` to call
 * anything. The console would then do nothing, and the operator would repeat
 * the gesture harder.
 *
 * ## Nothing fires for a movement that is not clearly anything
 *
 * A track under `MIN_TRACK_POINTS` is dropped. Two points is a resting hand
 * with jitter, and acting on it moves a panel somebody was reading — the same
 * rule `recogniseGesture` already applies when it returns null.
 *
 * ## Stopping drops what was in flight
 *
 * `stop()` discards a half-finished gesture instead of emitting it. Firing a
 * swipe as the operator switches the camera off would move their attention
 * after they asked the feature to stop.
 */

import { trackFromHands, type HandFrame, type Viewport } from './landmarks';
import type { TrackPoint } from './gestures';

/** Consecutive frames with no usable hand that end a gesture. */
export const FRAMES_WITHOUT_HAND_TO_END = 3;

/**
 * The recogniser's own minimum, restated rather than invented.
 *
 * `recogniseGesture` returns null below two points, and applies distance, time
 * and axis-dominance thresholds above it — so "is this jitter" is already
 * decided, in one place. A stricter floor here would be a SECOND opinion about
 * what counts as a gesture, which is the exact failure this module exists to
 * avoid: the camera and the pointer would disagree, and an operator could not
 * be told which rule their console was using.
 */
export const MIN_TRACK_POINTS = 2;

/** The slice of `HandDetector` this needs. Narrow, so tests can script it. */
export interface FrameReader {
  read(input: unknown, at: number): HandFrame | null;
  close(): void;
}

export interface HandGestureSourceOptions {
  detector: FrameReader;
  viewport: Viewport;
  onTrack: (points: TrackPoint[]) => void;
  /** A front camera shows a reflection. See `pointingPoint`. */
  mirrored?: boolean;
}

export class HandGestureSource {
  private readonly options: HandGestureSourceOptions;
  private frames: HandFrame[] = [];
  private missing = 0;
  private stopped = false;

  constructor(options: HandGestureSourceOptions) {
    this.options = options;
  }

  /** One camera frame. Call it from the render loop; it never throws. */
  onFrame(input: unknown, at: number): void {
    if (this.stopped) return;

    const frame = this.options.detector.read(input, at);
    if (frame !== null) {
      this.frames.push(frame);
      this.missing = 0;
      return;
    }

    // No hand this frame. Only a RUN of them ends the gesture.
    if (this.frames.length === 0) return;
    this.missing += 1;
    if (this.missing < FRAMES_WITHOUT_HAND_TO_END) return;

    this.flush();
  }

  private flush(): void {
    const frames = this.frames;
    this.frames = [];
    this.missing = 0;
    if (frames.length < MIN_TRACK_POINTS) return;

    const track = trackFromHands(frames, this.options.viewport, this.options.mirrored ?? true);
    if (track.length < MIN_TRACK_POINTS) return;
    this.options.onTrack(track);
  }

  /** Stop reading and release the detector. Idempotent. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    // Dropped, not flushed. See the docstring.
    this.frames = [];
    this.missing = 0;
    this.options.detector.close();
  }
}
