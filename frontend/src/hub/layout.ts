/**
 * hub/layout.ts — how much room each surface gets, and whether it is on screen.
 *
 * §8 names six of these: "focus, compare, split, timeline, war-room and
 * presentation layouts", chosen from "task, viewport, object count and
 * attention". §23 wants the layout engine independent of the content engine,
 * so this is a pure function: surfaces in, placements out. It imports no React,
 * touches no DOM, and every rule below is asserted without a browser.
 *
 * ## Why layout is not just "span from priority"
 *
 * The workspace engine already assigns a span from a surface's tier, and for
 * ordinary work that is right — critical dominant, background quiet (§10). But
 * a tier is a statement about importance, and a layout is a statement about
 * *what the operator is doing*, and the two disagree constantly:
 *
 * - Comparing two instruments means they must be the SAME size. A comparison
 *   where one panel is twice the other is not a comparison; it is a chart with
 *   a footnote. Tiers cannot express that, because both panels are "primary".
 * - Focusing means one thing dominates even when three others outrank it.
 * - A war room means density: more things smaller, deliberately.
 *
 * So a layout overrides the tier's span while leaving the tier's *ordering*
 * alone. What matters most is still first; how wide it is depends on the task.
 *
 * ## The viewport rule, which overrides everything
 *
 * A three-of-twelve panel is 90 pixels wide on a phone. It renders, it passes
 * a screenshot test, and it is unreadable — the failure mode §27 is about. So
 * the narrow breakpoint collapses every layout to one column, and the medium
 * one floors every span at half width. A layout is a preference; legibility is
 * not.
 */

import type { Surface, SurfacePriority } from './workspace';

export type LayoutName =
  | 'auto'
  | 'focus'
  | 'compare'
  | 'split'
  | 'timeline'
  | 'war_room'
  | 'presentation';

export const LAYOUTS: readonly LayoutName[] = [
  'auto',
  'focus',
  'compare',
  'split',
  'timeline',
  'war_room',
  'presentation',
] as const;

/** A surface with the layout's decision attached. */
export interface Placement {
  surface: Surface;
  /** Grid columns out of 12. */
  span: number;
  /**
   * False when this layout deliberately takes the surface off screen —
   * presentation mode shows one thing at a time.
   *
   * It is a separate field rather than a filtered-out row because the caller
   * has to be able to say "and four others are hidden". A surface that vanishes
   * with no trace is indistinguishable from one that was closed, and an
   * operator who cannot tell will close the workspace and rebuild it.
   */
  visible: boolean;
}

export interface Viewport {
  width: number;
}

export interface LayoutInput {
  layout?: LayoutName;
  focusedId?: string | null;
  viewport?: Viewport;
}

/** Below this a second column is unreadable, whatever the layout wanted. */
const NARROW = 640;
/** Below this, nothing narrower than half width. */
const MEDIUM = 1024;

const FULL = 12;

/** The tier spans, used by `auto` and as the fallback everywhere else. */
const SPAN_BY_PRIORITY: Record<SurfacePriority, number> = {
  critical: 12,
  primary: 6,
  secondary: 4,
  background: 3,
  on_demand: 3,
};

/**
 * Pick a layout from what is on the plane, when nobody named one.
 *
 * §8 asks for the layout to be chosen from "task, viewport, object count and
 * attention". This is the object-count and attention half: one surface has
 * nothing to lay out against, two invite comparison, and a dozen is a war room
 * whether or not anyone called it that.
 *
 * Deliberately conservative — it never chooses `presentation`, because hiding
 * surfaces is a decision an operator makes, not one inferred from a count.
 */
export function suggestLayout(surfaces: readonly Surface[], focusedId?: string | null): LayoutName {
  if (focusedId && surfaces.some((s) => s.id === focusedId)) return 'focus';
  if (surfaces.length >= 8) return 'war_room';
  if (surfaces.length === 2) return 'compare';
  return 'auto';
}

function rawSpan(
  surface: Surface,
  index: number,
  total: number,
  layout: LayoutName,
  focusedId: string | null,
): number {
  const focused = focusedId !== null && surface.id === focusedId;

  switch (layout) {
    case 'focus':
      // One thing dominates even when three others outrank it. The rest stay
      // visible and small: taking them away would answer a different request —
      // "focus on risk" is not "close everything else".
      return focused ? FULL : 3;

    case 'compare':
      // Equal width, always. Two panels of different sizes are not a
      // comparison, and this is the one layout where the tier's opinion is
      // actively wrong.
      return total <= 1 ? FULL : total === 2 ? 6 : 4;

    case 'split':
      // The two that matter most get half each; everything after is context.
      return index < 2 ? 6 : 4;

    case 'timeline':
      // Time reads horizontally. A timeline in a quarter-width column is a
      // sparkline pretending to be a history.
      return FULL;

    case 'war_room':
      // Density on purpose: more things, smaller, all at once.
      return 4;

    case 'presentation':
      return FULL;

    case 'auto':
    default:
      return SPAN_BY_PRIORITY[surface.priority] ?? 4;
  }
}

/**
 * Place surfaces for a layout and a viewport.
 *
 * Ordering is the caller's — `Workspace.surfaces` already sorts by importance
 * then recency, and re-sorting here would make two engines disagree about what
 * comes first. This decides width and visibility only.
 */
export function place(surfaces: readonly Surface[], input: LayoutInput = {}): Placement[] {
  const focusedId = input.focusedId ?? null;
  const layout = input.layout ?? 'auto';
  const width = input.viewport?.width ?? MEDIUM;
  const total = surfaces.length;

  // Presentation shows one surface: the focused one, or the first, which is
  // the most important one because the caller sorted them.
  const shown =
    layout === 'presentation'
      ? (surfaces.find((s) => s.id === focusedId) ?? surfaces[0])?.id
      : null;

  return surfaces.map((surface, index) => {
    const visible = layout !== 'presentation' || surface.id === shown;
    let span = rawSpan(surface, index, total, layout, focusedId);

    // Legibility overrides the layout, never the other way round. A pinned
    // surface does not get an exemption: pinning says "keep this on screen",
    // not "make it 90 pixels wide".
    if (width < NARROW) span = FULL;
    else if (width < MEDIUM) span = Math.max(span, 6);

    return { surface, span: Math.min(FULL, Math.max(1, span)), visible };
  });
}

/**
 * Read a layout out of something the operator said.
 *
 * Local and deterministic for the same reason `intent.ts` is: rearranging the
 * plane should not cost a model call or stop working when a vendor is
 * unreachable. Returns null when nothing was named, so the caller can fall
 * through to `suggestLayout` rather than being handed a guess.
 */
export function readLayout(phrase: string): LayoutName | null {
  const text = (phrase ?? '').toLowerCase();
  if (/\bwar[ -]?room\b|\beverything at once\b|\bfull picture\b/.test(text)) return 'war_room';
  if (/\bcompare\b|\bside by side\b|\bagainst each other\b|\bversus\b|\bvs\b/.test(text)) return 'compare';
  if (/\bpresent(ation)?\b|\bone at a time\b|\bfull screen\b|\bfullscreen\b/.test(text)) return 'presentation';
  if (/\btimeline\b|\bover time\b|\bhistory\b|\bchronolog/.test(text)) return 'timeline';
  if (/\bsplit\b|\btwo up\b|\bhalf and half\b/.test(text)) return 'split';
  if (/\bfocus\b|\bzoom\b|\bjust show\b|\bonly show\b/.test(text)) return 'focus';
  if (/\bauto\b|\bnormal\b|\bdefault layout\b|\breset layout\b/.test(text)) return 'auto';
  return null;
}
