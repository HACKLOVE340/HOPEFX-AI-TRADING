/**
 * hub/floatingLanes.ts — the corners already spoken for.
 *
 * `presenceDock.ts` was written so the presence "never silently covers
 * something": hand `dockFor` an `avoid` list and it tries each corner, takes
 * the first that collides with none of it, and reports the overlap when every
 * corner collides. That is good machinery, and until now nothing filled it in.
 * `PresenceAnywhereMount` never passed `avoid`, so the list was always empty,
 * every corner was always clear, and the dock took `bottom-right` every time —
 * the same corner the support launcher sits in.
 *
 * Measured in Chromium at 1440x1000 on /dashboard: launcher at
 * (1358,924)-(1414,980), presence panel at (1320,880)-(1416,1351). They
 * intersect, and the launcher's z-index of 1200 covers a control at z-40, so
 * part of the presence was not clickable. A guard that cannot open is worse
 * than no guard, because the code reads as though the case is handled.
 *
 * This module is the missing input, and nothing more: a small registry of
 * rectangles that persistent floating controls claim while they are mounted.
 * It deliberately holds no React state — the launcher can move on every pointer
 * event during a drag, and a store that re-rendered the whole presence tree at
 * pointer rate would cost more than the collision it prevents. Subscribers are
 * notified, and it is up to them how often they act.
 */
import type { Rect } from './spatial';

type Listener = () => void;

const lanes = new Map<string, Rect>();
const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** Claim a rectangle. Calling again with the same id replaces the claim. */
export function reserveLane(id: string, rect: Rect): void {
  const held = lanes.get(id);
  if (held && held.x === rect.x && held.y === rect.y && held.width === rect.width && held.height === rect.height) {
    // Identical claim: no listener has anything to do, so do not wake them.
    return;
  }
  lanes.set(id, rect);
  notify();
}

/** Give a rectangle back — on unmount, or when the control stops being visible. */
export function releaseLane(id: string): void {
  if (lanes.delete(id)) notify();
}

/** Every claim currently held, in claim order. */
export function readLanes(): Rect[] {
  return [...lanes.values()];
}

export function subscribeLanes(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Tests only: a module-level registry outlives a render, so it must be reset. */
export function clearLanes(): void {
  lanes.clear();
  notify();
}
