/**
 * hub/presenceDock.ts — where the presence sits so it helps and never blocks.
 *
 * Owner request, 2026-09-07: the presence should be able to appear on any
 * screen and move around the page.
 *
 * On the AI Core page the presence owns the plane. Everywhere else it is a
 * guest on somebody else's screen — one of them the order ticket — and the
 * whole job of this module is deciding where it can be without being in the
 * way.
 *
 * ## It never silently covers something
 *
 * `avoid` is what the operator is currently using. The dock tries each corner
 * and takes the first that collides with none of it. When every corner
 * collides it does NOT quietly pick one: it reports the overlap and says why,
 * so the overlay can shrink, dim, or step aside rather than sitting on top of a
 * form somebody is filling in.
 *
 * ## It is never a keyboard trap
 *
 * A floating panel that captures Tab makes every page behind it unusable for
 * anyone navigating by keyboard. `role="complementary"` with a label, and
 * `trapsFocus` is a field rather than an assumption so a test can assert it.
 *
 * ## Dismissal survives navigation
 *
 * A presence that comes back on the next route change was not dismissed, it was
 * delayed — and a thing that reappears after you close it is the definition of
 * an annoyance.
 *
 * ## Motion
 *
 * Transform and opacity only, so travel never triggers layout on a page that is
 * also rendering a live chart. Reduced motion removes the travel entirely, in
 * line with `usePrefersReducedMotion`, which defaults to no-motion because for
 * some people the setting is medical rather than aesthetic.
 */

import { BREAKPOINTS } from './a11yBreakpoints';
import type { Rect } from './spatial';

export type DockCorner = 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
export type DockMode = 'float' | 'bar';
export type DockState = 'active' | 'dismissed';

export const DISMISSED: DockState = 'dismissed';

/** Below this a floating orb covers content whatever corner it picks. */
const NARROW_VIEWPORT = BREAKPOINTS.narrow;

/**
 * What the presence occupies when nobody says otherwise.
 *
 * This was the only size this module knew, and `PresenceAnywhere` renders its
 * panel at `dock.rect.width` — so the closed panel was laid out 96px wide and
 * wrapped a status sentence, a dismiss button and an "Ask about this page"
 * button into a 72px content box, 471px tall, one word per line. It was
 * unreadable on every authenticated page and went unnoticed because the
 * bottom-right corner ran the top of it off the screen.
 *
 * It also made every collision answer wrong: the module reserved 96x96 and
 * something four times that tall was drawn, so `avoid` was checked against a
 * box the presence does not occupy. Callers now pass the size they will
 * actually render at.
 */
const ORB = { width: 96, height: 96 };
const MARGIN = 24;
const BAR_HEIGHT = 72;

const TRANSITION = 'transform 220ms ease, opacity 220ms ease';

export interface DockRequest {
  viewport: Rect;
  /** What the caller will render. Defaults to the collapsed orb. */
  size?: { width: number; height: number };
  /** What the operator is interacting with. The dock stays off all of it. */
  avoid?: readonly Rect[];
  state?: DockState;
  reducedMotion?: boolean;
}

export interface Dock {
  visible: boolean;
  mode: DockMode;
  corner: DockCorner;
  rect: Rect;
  /** Rects the chosen position still overlaps. Empty when it found a clear corner. */
  overlapping: Rect[];
  transition: string;
  trapsFocus: false;
  a11y: { role: 'complementary'; 'aria-label': string };
  /** Empty only when the dock is visible, clear, and needed no explanation. */
  reason: string;
}

const CORNERS: DockCorner[] = ['bottom-right', 'bottom-left', 'top-right', 'top-left'];

function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function rectFor(corner: DockCorner, viewport: Rect, size: { width: number; height: number }): Rect {
  const right = viewport.x + viewport.width - size.width - MARGIN;
  const bottom = viewport.y + viewport.height - size.height - MARGIN;
  const left = viewport.x + MARGIN;
  const top = viewport.y + MARGIN;
  const x = corner.endsWith('right') ? right : left;
  const y = corner.startsWith('bottom') ? bottom : top;
  return { x, y, width: size.width, height: size.height };
}

function base(request: DockRequest): Pick<Dock, 'transition' | 'trapsFocus' | 'a11y'> {
  return {
    transition: request.reducedMotion === true ? 'none' : TRANSITION,
    trapsFocus: false,
    a11y: { role: 'complementary', 'aria-label': 'HOPEFX AI assistant' },
  };
}

export function dockFor(request: DockRequest): Dock {
  const { viewport } = request;
  const shared = base(request);

  if (request.state === DISMISSED) {
    return {
      ...shared,
      visible: false,
      mode: 'float',
      corner: 'bottom-right',
      rect: { x: 0, y: 0, width: 0, height: 0 },
      overlapping: [],
      reason: 'the operator dismissed the presence; it stays dismissed across navigation',
    };
  }

  if (!(viewport.width > 0) || !(viewport.height > 0)) {
    // Docking to a viewport nobody measured puts the presence off-screen, where
    // it is invisible and still focusable.
    return {
      ...shared,
      visible: false,
      mode: 'float',
      corner: 'bottom-right',
      rect: { x: 0, y: 0, width: 0, height: 0 },
      overlapping: [],
      reason: `the viewport is ${viewport.width}x${viewport.height}, so there is nowhere to dock`,
    };
  }

  if (viewport.width < NARROW_VIEWPORT) {
    // A bar spans the width and pushes page content rather than sitting on it,
    // which is the only arrangement that cannot cover the page on a small
    // screen. It does not push a *fixed* control: measured at 400x1000, the
    // bar covered the support launcher, which then drew on top of it at
    // z-index 1200. The branch used to answer `overlapping: []` regardless —
    // a measurement with no path to a non-empty answer, so the caller could
    // not have shrunk, dimmed or stepped aside even though this module
    // promises it will. Where the bar goes on a phone is a design question and
    // is unchanged; what it says about itself is now measured.
    const barRect = {
      x: viewport.x,
      y: viewport.y + viewport.height - BAR_HEIGHT,
      width: viewport.width,
      height: BAR_HEIGHT,
    };
    const covered = (request.avoid ?? []).filter((other) => overlaps(barRect, other));
    return {
      ...shared,
      visible: true,
      mode: 'bar',
      corner: 'bottom-left',
      rect: barRect,
      overlapping: covered,
      reason:
        covered.length === 0
          ? 'the viewport is narrow, so the presence docks to an edge bar rather than floating over content'
          : `the viewport is narrow, so the presence docks to an edge bar; it covers ${covered.length} fixed ` +
            'control the operator can still reach, because a bar has nowhere else to go on this screen',
    };
  }

  const avoid = request.avoid ?? [];
  const size = request.size ?? ORB;
  let fallback: { corner: DockCorner; rect: Rect; hits: Rect[] } | null = null;

  for (const corner of CORNERS) {
    const rect = rectFor(corner, viewport, size);
    const hits = avoid.filter((other) => overlaps(rect, other));
    if (hits.length === 0) {
      return { ...shared, visible: true, mode: 'float', corner, rect, overlapping: [], reason: '' };
    }
    // Keep the least-bad, so a fully occupied screen still gets a position —
    // reported as overlapping rather than presented as clear.
    if (fallback === null || hits.length < fallback.hits.length) fallback = { corner, rect, hits };
  }

  const chosen = fallback as { corner: DockCorner; rect: Rect; hits: Rect[] };
  return {
    ...shared,
    visible: true,
    mode: 'float',
    corner: chosen.corner,
    rect: chosen.rect,
    overlapping: chosen.hits,
    reason:
      'every corner overlaps something the operator is using; the presence is placed where it covers least ' +
      'and reports the overlap so the overlay can shrink or step aside rather than sit on top of it',
  };
}
