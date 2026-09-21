/**
 * hub/virtualization.ts — which slice of a long list is worth rendering.
 *
 * §23 asks for "virtualisation for high-density displays". A war-room table of
 * ten thousand ticks does not need ten thousand DOM nodes; it needs the fifteen
 * the operator can see, plus a few either side so scrolling does not flash.
 *
 * ## The rule this module exists to hold
 *
 * **An unknown viewport must never render zero items.**
 *
 * That is §22's rule arriving in the browser. A virtualiser computing a window
 * from a height nobody measured — a container not laid out yet, a hidden tab, a
 * ref that has not attached — produces `start === end`, and an empty list is
 * indistinguishable from "there is nothing to show". The operator concludes
 * their data is missing.
 *
 * So an unmeasured viewport falls back to a *stated* number of rows, says it
 * was not measured, and says why. Not to all of them either: rendering ten
 * thousand nodes because a ref was late is the failure this module was added to
 * prevent, arriving from the other direction.
 */

export interface WindowRequest {
  count: number;
  itemHeight: number;
  viewportHeight: number;
  scrollTop: number;
  /** Rows rendered either side of the visible range, to hide scroll latency. */
  overscan?: number;
}

export interface RenderWindow {
  /** First index to render, inclusive. */
  start: number;
  /** Last index to render, exclusive. */
  end: number;
  /** Pixels of list above `start`, for the spacer. */
  offsetTop: number;
  /** Total list height, for the scrollbar. */
  totalHeight: number;
  /** False when the window came from a fallback rather than a measurement. */
  measured: boolean;
  /** Empty when measured. Populated whenever `measured` is false. */
  reason: string;
}

const DEFAULT_OVERSCAN = 3;

/**
 * Rows to show when the viewport could not be measured.
 *
 * Enough to fill any plausible screen, few enough that a mistake costs a
 * scroll rather than a frozen tab.
 */
export const UNMEASURED_FALLBACK_ROWS = 50;

export function windowFor(request: WindowRequest): RenderWindow {
  const count = Math.max(0, Math.floor(request.count));
  const overscan = Math.max(0, Math.floor(request.overscan ?? DEFAULT_OVERSCAN));
  const itemHeight = request.itemHeight;

  if (count === 0) {
    // A genuinely empty list is measured. Reporting it as unmeasured would put
    // "we could not tell" on a screen that knows perfectly well.
    return { start: 0, end: 0, offsetTop: 0, totalHeight: 0, measured: true, reason: '' };
  }

  if (!(itemHeight > 0) || !Number.isFinite(itemHeight)) {
    return fallback(count, `item height is ${itemHeight}, so no window can be computed from it`);
  }

  const totalHeight = count * itemHeight;

  if (!(request.viewportHeight > 0) || !Number.isFinite(request.viewportHeight)) {
    return { ...fallback(count, 'the viewport height has not been measured yet'), totalHeight };
  }

  const maxScroll = Math.max(0, totalHeight - request.viewportHeight);
  const scrollTop = Math.min(Math.max(0, request.scrollTop || 0), maxScroll);

  const firstVisible = Math.floor(scrollTop / itemHeight);
  const visibleRows = Math.ceil(request.viewportHeight / itemHeight);

  const start = Math.max(0, firstVisible - overscan);
  const end = Math.min(count, firstVisible + visibleRows + overscan);

  return {
    start,
    // A window that renders nothing while rows exist is the defect above in
    // miniature, so the end is nudged past the start rather than clamped onto it.
    end: Math.max(end, Math.min(count, start + 1)),
    offsetTop: start * itemHeight,
    totalHeight,
    measured: true,
    reason: '',
  };
}

function fallback(count: number, reason: string): RenderWindow {
  const end = Math.min(count, UNMEASURED_FALLBACK_ROWS);
  return {
    start: 0,
    end,
    offsetTop: 0,
    totalHeight: 0,
    measured: false,
    reason: `${reason}; showing the first ${end} of ${count} rows rather than none`,
  };
}
