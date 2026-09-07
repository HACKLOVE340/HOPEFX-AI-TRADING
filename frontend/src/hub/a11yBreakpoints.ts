/**
 * hub/a11yBreakpoints.ts — §27 responsive layout: one definition of "narrow".
 *
 * Before this module, `640` appeared three times in `hub/` — in `layout.ts` as
 * `NARROW`, in `presenceDock.ts` as `NARROW_VIEWPORT`, and in
 * `layoutStrategy.ts` as `NARROW` again. They agreed, by coincidence and by
 * copy-paste. Changing one would have moved the panel grid to one column at a
 * width where the presence overlay still floated over it rather than docking to
 * the edge bar — a layout nobody designed, reachable only on a device nobody
 * tested.
 *
 * Three constants that must agree are one constant. This is it.
 *
 * ## An unreadable width is narrow
 *
 * `useViewportWidth` returns an assumed desktop width when there is no window,
 * because zero is below every breakpoint and would collapse the plane for one
 * frame on every mount. That is the right call *there*, where the alternative
 * is a visible flash on every desktop mount.
 *
 * Here, where the input is a number that arrived from somewhere, an
 * unusable one resolves to `narrow`. Guessing wide renders a six-column plane
 * onto a phone, where the content is unreachable. Guessing narrow renders one
 * column onto a desktop: visibly wrong, and everything is still reachable.
 */

export const BAND_NAMES = ['narrow', 'medium', 'wide'] as const;
export type Band = (typeof BAND_NAMES)[number];

/**
 * Lower bound of each band, in CSS pixels.
 *
 * `narrow` is the value the three modules above were each holding privately;
 * `medium` is `layout.ts`'s existing `MEDIUM`. Both are kept so this module is
 * a consolidation and not, quietly, a redesign of every breakpoint in the hub.
 */
export const BREAKPOINTS: Readonly<Record<Band, number>> = Object.freeze({
  narrow: 640,
  medium: 1024,
  wide: 1536,
});

/**
 * Which band a width falls in.
 *
 * `< 640` narrow, `640..1023` medium, `>= 1024` wide. `BREAKPOINTS.wide` is
 * the largest declared step rather than a fourth band: nothing in the hub lays
 * out differently above it, and a band with no behaviour behind it is a number
 * that looks like a decision.
 */
export function breakpointFor(width: number): Band {
  if (!Number.isFinite(width) || width <= 0) return 'narrow';
  if (width < BREAKPOINTS.narrow) return 'narrow';
  if (width < BREAKPOINTS.medium) return 'medium';
  return 'wide';
}

/** Whether the viewport is too narrow for side-by-side content. */
export function isNarrow(width: number): boolean {
  return breakpointFor(width) === 'narrow';
}
