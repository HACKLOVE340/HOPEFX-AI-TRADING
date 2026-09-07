/**
 * hub/spatial.ts — where things are, how you got there, and how to get back.
 *
 * §9's remaining four: coordinate and viewport awareness, animated focus
 * transitions, zoom into data regions, layer navigation and breadcrumbs.
 *
 * All pure. Rects come in as numbers measured by the DOM, so every rule here —
 * which ninth of the screen a panel is in, what a zoom does to a series, what
 * happens to a breadcrumb trail when you go back twice — is testable without a
 * browser.
 *
 * ## Position is measured or it is not claimed
 *
 * "The risk table, top right" is only useful if it is true. A layout engine
 * that computed the position from its own grid intentions would be wrong the
 * moment anything wrapped, scrolled, or was collapsed into the background
 * stack, and it would be wrong confidently — the AI directing an operator's
 * eyes to the wrong corner of their own screen.
 *
 * So position comes from a measured `DOMRect` and nothing else. No rect, no
 * position: `positionOf` returns null and the caller says "the risk table"
 * rather than inventing a corner.
 */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * A coarse position, in words an operator would use.
 *
 * Nine cells rather than pixels, because "at 1,204 by 380" helps nobody and
 * "top right" is what a person standing at the screen would say.
 */
export type Vertical = 'top' | 'middle' | 'bottom';
export type Horizontal = 'left' | 'centre' | 'right';

export interface Position {
  vertical: Vertical;
  horizontal: Horizontal;
  /** "top right", "middle centre" → "the centre". Ready to be spoken. */
  phrase: string;
}

function band<T extends string>(value: number, extent: number, names: [T, T, T]): T {
  if (extent <= 0) return names[1];
  const third = extent / 3;
  if (value < third) return names[0];
  if (value < third * 2) return names[1];
  return names[2];
}

/**
 * Which ninth of the viewport a rect's centre sits in.
 *
 * Null for a rect that was never measured, or measured as nothing — a
 * zero-sized rect is what `getBoundingClientRect` returns for an element that
 * is not laid out yet, and treating that as "top left" would have the AI point
 * at a corner where nothing is.
 */
export function positionOf(rect: Rect | null | undefined, viewport: Rect): Position | null {
  if (!rect || rect.width <= 0 || rect.height <= 0) return null;
  if (viewport.width <= 0 || viewport.height <= 0) return null;

  const cx = rect.x - viewport.x + rect.width / 2;
  const cy = rect.y - viewport.y + rect.height / 2;
  const vertical = band<Vertical>(cy, viewport.height, ['top', 'middle', 'bottom']);
  const horizontal = band<Horizontal>(cx, viewport.width, ['left', 'centre', 'right']);

  const phrase =
    vertical === 'middle' && horizontal === 'centre'
      ? 'the centre'
      : vertical === 'middle'
        ? `the ${horizontal}`
        : horizontal === 'centre'
          ? `${vertical} centre`
          : `${vertical} ${horizontal}`;

  return { vertical, horizontal, phrase };
}

// ── zoom into a data region (§9) ──────────────────────────────────────────────

export interface ZoomRange {
  /** Index of the first point kept. */
  from: number;
  /** Index just past the last point kept. */
  to: number;
}

/**
 * The slice a phrase asks for, over a series of `length` points.
 *
 * Returns null when the phrase names no region, so the caller leaves the chart
 * alone rather than zooming somewhere arbitrary.
 *
 * The fractions are honest about what they are: "the last hour" over a series
 * with no timestamps cannot mean an hour, so it means the most recent quarter
 * and the caller is expected to say "the most recent stretch". Pretending to
 * slice by time when the points carry none is the fake-precision failure §22
 * exists to prevent.
 */
export function readZoom(phrase: string, length: number): ZoomRange | null {
  if (length <= 1) return null;
  const text = (phrase ?? '').toLowerCase();

  if (/\b(zoom out|reset zoom|show (me )?(it )?all|full (range|history)|whole (thing|series))\b/.test(text)) {
    return { from: 0, to: length };
  }
  if (!/\bzoom\b|\bcloser\b|\bin on\b|\bfocus on the (last|first|recent)\b/.test(text)) return null;

  const explicit = /\b(?:last|latest|recent(?:ly)?|final)\s+(\d+)\b/.exec(text);
  if (explicit?.[1]) {
    const n = Math.min(length, Math.max(2, Number(explicit[1])));
    return { from: length - n, to: length };
  }
  const firstN = /\bfirst\s+(\d+)\b/.exec(text);
  if (firstN?.[1]) {
    const n = Math.min(length, Math.max(2, Number(firstN[1])));
    return { from: 0, to: n };
  }

  if (/\bhalf\b|\bsecond half\b/.test(text)) return { from: Math.floor(length / 2), to: length };
  if (/\bfirst\b|\bstart\b|\bbeginning\b/.test(text)) return { from: 0, to: Math.max(2, Math.ceil(length / 4)) };
  if (/\blast\b|\brecent\b|\bend\b|\bnow\b|\bhour\b|\btoday\b/.test(text)) {
    return { from: Math.max(0, length - Math.max(2, Math.ceil(length / 4))), to: length };
  }

  // "Zoom in" with no region named: halve the window, keeping the newest data,
  // which is what somebody looking at a price series means by it.
  return { from: Math.max(0, length - Math.max(2, Math.ceil(length / 2))), to: length };
}

/** Apply a range. Out-of-bounds is clamped; an empty result returns the input. */
export function applyZoom<T>(points: readonly T[], range: ZoomRange | null): T[] {
  if (!range) return [...points];
  const from = Math.max(0, Math.min(points.length - 1, Math.floor(range.from)));
  const to = Math.max(from + 1, Math.min(points.length, Math.ceil(range.to)));
  const sliced = points.slice(from, to);
  return sliced.length > 0 ? sliced : [...points];
}

// ── layer navigation and breadcrumbs (§9) ─────────────────────────────────────

export interface Layer {
  /** Surface id this layer is about, or null for the plane itself. */
  surfaceId: string | null;
  /** What to show in the trail. */
  label: string;
  /** The zoom applied at this layer, when there is one. */
  zoom?: ZoomRange | null;
}

/**
 * Where the operator has drilled to, and how to get back.
 *
 * A stack rather than a single "current layer", because §9 asks for
 * breadcrumbs and a breadcrumb with no history is a label. Going back one level
 * has to be possible from any depth, and going back from the root has to be a
 * no-op rather than an error — an operator who taps back twice at the top has
 * not done anything wrong.
 */
export class LayerStack {
  private layers: Layer[];

  constructor(rootLabel = 'Plane') {
    this.layers = [{ surfaceId: null, label: rootLabel }];
  }

  /** Root first. Always at least one entry. */
  get trail(): readonly Layer[] {
    return this.layers;
  }

  get current(): Layer {
    return this.layers[this.layers.length - 1]!;
  }

  get depth(): number {
    return this.layers.length - 1;
  }

  /**
   * Descend into a surface, or deeper into the one already current.
   *
   * Entering the surface you are already in replaces the top rather than
   * stacking a duplicate — otherwise zooming three times leaves three
   * identical breadcrumbs and "back" appears to do nothing twice.
   */
  enter(layer: Layer): void {
    if (layer.surfaceId !== null && this.current.surfaceId === layer.surfaceId) {
      this.layers[this.layers.length - 1] = layer;
      return;
    }
    this.layers.push(layer);
  }

  /** Up one. A no-op at the root. Returns the layer now current. */
  back(): Layer {
    if (this.layers.length > 1) this.layers.pop();
    return this.current;
  }

  /** Jump to a depth in the trail. Clamped, so a stale breadcrumb cannot throw. */
  to(index: number): Layer {
    const clamped = Math.max(0, Math.min(this.layers.length - 1, Math.floor(index)));
    this.layers = this.layers.slice(0, clamped + 1);
    return this.current;
  }

  /** Straight to the top. */
  reset(): Layer {
    this.layers = [this.layers[0]!];
    return this.current;
  }

  /**
   * Drop any layer whose surface is gone.
   *
   * Closing a surface you had drilled into must not leave a breadcrumb that
   * navigates nowhere. The root always survives.
   */
  prune(liveIds: ReadonlySet<string>): void {
    const kept: Layer[] = [this.layers[0]!];
    for (const layer of this.layers.slice(1)) {
      if (layer.surfaceId !== null && !liveIds.has(layer.surfaceId)) break;
      kept.push(layer);
    }
    this.layers = kept;
  }
}

/** Read a navigation phrase. Null when none was named. */
export function readNavigation(phrase: string): 'back' | 'root' | null {
  const text = (phrase ?? '').toLowerCase();
  if (/\b(back to (the )?(top|plane|start)|all the way back|start over|top level)\b/.test(text)) return 'root';
  if (/\b(go back|back up|out of (this|that)|zoom back out|previous layer|step back)\b/.test(text)) return 'back';
  return null;
}

// ── focus transitions (§9) ────────────────────────────────────────────────────

/**
 * The transition a focus change uses.
 *
 * Transform and opacity only — animating width or height on a grid of a dozen
 * panels drops frames on exactly the device that can least afford it, and
 * `ui-ux-pro-max` names it as a rule rather than a preference.
 *
 * 200ms sits inside the 150-300ms band for a micro-interaction: fast enough to
 * feel like a response, slow enough to be seen.
 *
 * Motion is removed, not merely shortened, under `prefers-reduced-motion`. A
 * 1ms transform is still a transform, and the setting is a medical one for some
 * people rather than an aesthetic preference.
 */
export interface FocusTransition {
  transition: string;
  transform: string;
  opacity: number;
}

export function focusTransition(
  state: { focused: boolean; spokenAbout: boolean; reducedMotion: boolean },
): FocusTransition {
  const lift = state.focused ? 1.012 : state.spokenAbout ? 1.006 : 1;
  if (state.reducedMotion) {
    return { transition: 'none', transform: 'none', opacity: 1 };
  }
  return {
    transition: 'transform 200ms cubic-bezier(.2,.7,.3,1), opacity 200ms ease, border-color 200ms ease',
    transform: lift === 1 ? 'none' : `scale(${lift})`,
    opacity: 1,
  };
}
