/**
 * hub/gestures.ts — the half of §18's gesture and pointing rows that is real.
 *
 * §18 asks for gesture recognition and for "pointing and object reference".
 * Both, read as camera capabilities, need hand or body landmarks — and this
 * repository has no landmark source. Building a recogniser that nothing feeds
 * would be `hopefx-dead-controls` wearing a camera: a component that exists,
 * reads correctly, and never runs.
 *
 * So what is built here is the half that is genuinely available and genuinely
 * useful: **pointer gestures**, which need no camera and no consent, and
 * **object reference**, which is a hit test against the scene graph. The two
 * registry rows stay `staged` with the missing half named, rather than claiming
 * a capability the platform does not have.
 *
 * ## Null rather than the nearest gesture
 *
 * A movement that is not clearly one thing returns null. On a trading screen a
 * wrongly-recognised swipe moves a panel somebody was reading, and the cost of
 * guessing is higher than the cost of the operator repeating themselves.
 */

import type { SceneGraph } from './sceneGraph';

export type Gesture = 'swipe_left' | 'swipe_right' | 'swipe_up' | 'swipe_down' | 'long_press';

export interface TrackPoint {
  x: number;
  y: number;
  /** Milliseconds since the gesture started. */
  t: number;
}

/** Minimum travel for a swipe. Below this it is a tap with a shaky hand. */
const SWIPE_DISTANCE = 80;
/** A swipe slower than this is a drag, and a drag means something else. */
const SWIPE_MAX_MS = 600;
/** How much longer the dominant axis must be, so a diagonal is not a swipe. */
const AXIS_DOMINANCE = 2;

/** A press must be still for this long. */
const LONG_PRESS_MS = 500;
/** And must not have wandered more than this. */
const LONG_PRESS_SLOP = 12;

export function recogniseGesture(points: readonly TrackPoint[]): Gesture | null {
  if (points.length < 2) return null;

  const first = points[0];
  const last = points[points.length - 1];
  if (first === undefined || last === undefined) return null;

  const dx = last.x - first.x;
  const dy = last.y - first.y;
  const dt = last.t - first.t;
  const absX = Math.abs(dx);
  const absY = Math.abs(dy);

  if (dt >= LONG_PRESS_MS && absX <= LONG_PRESS_SLOP && absY <= LONG_PRESS_SLOP) {
    return 'long_press';
  }

  if (dt > SWIPE_MAX_MS) return null;

  if (absX >= SWIPE_DISTANCE && absX > absY * AXIS_DOMINANCE) {
    return dx < 0 ? 'swipe_left' : 'swipe_right';
  }
  if (absY >= SWIPE_DISTANCE && absY > absX * AXIS_DOMINANCE) {
    return dy < 0 ? 'swipe_up' : 'swipe_down';
  }

  // Not clearly anything. On a trading screen a wrong guess moves a panel
  // somebody was reading.
  return null;
}

/**
 * What is under `(x, y)` — the object-reference half of §18's pointing row.
 *
 * Topmost by z, so an overlapping panel answers for the one behind it. Null on
 * empty space rather than the nearest panel: "I am pointing at nothing" is an
 * answer, and the nearest panel to a point in the margin is not what was meant.
 */
export function pointingAt(graph: SceneGraph, x: number, y: number): string | null {
  let best: { id: string; z: number } | null = null;
  for (const id of graph.ids()) {
    const rect = graph.rectOf(id);
    const inside = x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
    if (!inside) continue;
    const z = graph.zOf(id);
    if (best === null || z >= best.z) best = { id, z };
  }
  return best === null ? null : best.id;
}
