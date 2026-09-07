/**
 * hub/layoutStrategy.ts — the same placements, in a different geometry.
 *
 * §23 asks for a layout engine independent of content. `hub/layout.ts` is the
 * content-independent half and already decides span, visibility and collapse
 * across seven layouts. What it did not have was a second GEOMETRY: everything
 * it produced was a twelve-column grid.
 *
 * This adds one without touching `place()`. Two thousand two hundred existing
 * tests depend on that function's output, and a rewrite to add a second
 * strategy would put all of them at risk to gain one.
 *
 * ## grid and stack are different questions
 *
 * `grid` keeps the importance ordering the engine decided and expresses it as
 * width. `stack` is for reading and for narrow screens: one thing after
 * another, full width, in the order the engine ranked them. Importance is still
 * the engine's answer — the stack expresses it as sequence rather than size.
 *
 * ## An unknown strategy is refused
 *
 * Falling back to grid would render a screen nobody asked for and report
 * success, and the caller would never find out their strategy name was wrong.
 */

export const STRATEGIES = ['grid', 'stack'] as const;
export type Strategy = (typeof STRATEGIES)[number];

/** Below this a twelve-column grid is columns of about thirty pixels. */
const NARROW = 640;

const FULL = 12;

export interface PlacedLike {
  id: string;
  span: number;
  priority?: string;
}

export interface Geometry {
  id: string;
  span: number;
  /** Position in the reading order. Meaningful in `stack`, stable in `grid`. */
  order: number;
  strategy: Strategy;
  /** True when the caller named a strategy the viewport would not have chosen. */
  forced: boolean;
}

export interface GeometryOptions {
  strategy?: Strategy;
  viewport?: { width: number };
}

export function geometryFor(placed: readonly PlacedLike[], options: GeometryOptions = {}): Geometry[] {
  const width = options.viewport?.width;
  const suggested: Strategy = width !== undefined && width < NARROW ? 'stack' : 'grid';

  let strategy: Strategy = suggested;
  let forced = false;
  if (options.strategy !== undefined) {
    if (!(STRATEGIES as readonly string[]).includes(options.strategy)) {
      throw new Error(
        `unknown layout strategy ${options.strategy}; falling back to a grid would render a screen nobody asked for`,
      );
    }
    forced = options.strategy !== suggested;
    strategy = options.strategy;
  }

  return placed.map((surface, order) => ({
    id: surface.id,
    // Grid keeps what place() decided. The strategy layer adds geometry; it does
    // not re-decide importance.
    span: strategy === 'stack' ? FULL : surface.span,
    order,
    strategy,
    forced,
  }));
}
