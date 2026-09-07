/**
 * hub/representation.ts — §21: choose the representation that suits the
 * information.
 *
 * The staged note said "Intent picks the kind; a model does not choose it
 * yet", which framed this row as waiting for a model call. That framing was
 * mine and it was wrong.
 *
 * A numeric series is a chart. Pairs are a table. Timestamped events are a
 * timeline. Nodes with edges are a network. Those follow from the SHAPE of
 * what arrived, and deciding them here is better than deciding them in a
 * model: instant, free, deterministic, testable, and still working when every
 * vendor is unreachable. `intent.ts` makes exactly this argument for resolving
 * the obvious commands locally — "this is the reflex, the model is the
 * thought" — and it applies with more force to a question whose answer is
 * already in the data.
 *
 * The model is not cut out. It remains the fallback for the case this cannot
 * decide, which is what `null` means here.
 *
 * ## Null is a refusal, and it is the right answer twice
 *
 * For an empty surface, because a representation of nothing is a shape rather
 * than information. And for a one-point series, because a line drawn between
 * one point is a dot — `surfaceData` already refuses to chart a single price,
 * and a chooser that reinstated it would undo a decision made for a reason.
 *
 * ## Richer beats simpler when both are present
 *
 * A payload carrying cells AND rows is a heatmap with its accessible twin, not
 * a table that happens to have cells attached. Picking the weaker form would
 * throw away structure the sender took the trouble to include.
 */

import type { SurfaceKind } from './contracts.shared';
import type { SurfaceData } from './surfaceData';

/**
 * Shapes in the order they are checked: richest first.
 *
 * A list rather than a chain of ifs so the precedence is visible in one place
 * and a new shape cannot be inserted at the wrong priority by accident.
 */
const SHAPES: readonly { kind: SurfaceKind; suits: (d: SurfaceData) => boolean; why: (d: SurfaceData) => string }[] = [
  {
    kind: 'network',
    suits: (d) => Array.isArray(d.nodes) && d.nodes.length > 0 && Array.isArray(d.edges),
    why: (d) => `${d.nodes!.length} things with relationships between them`,
  },
  {
    kind: 'heatmap',
    suits: (d) => Array.isArray(d.cells) && d.cells.length > 0,
    why: (d) => `${d.cells!.length} values across two dimensions`,
  },
  {
    kind: 'timeline',
    suits: (d) => Array.isArray(d.events) && d.events.length > 0,
    why: (d) => `${d.events!.length} things that happened, each with a time`,
  },
  {
    // Two points is the minimum that can show a direction. See the docstring.
    kind: 'chart',
    suits: (d) => Array.isArray(d.points) && d.points.length >= 2,
    why: (d) => `${d.points!.length} numbers in sequence`,
  },
  {
    kind: 'distribution',
    suits: (d) => Array.isArray(d.values) && d.values.length >= 2,
    why: (d) => `${d.values!.length} magnitudes with no order between them`,
  },
  {
    kind: 'table',
    suits: (d) => Array.isArray(d.rows) && d.rows.length > 0,
    why: (d) => `${d.rows!.length} labelled values`,
  },
  {
    kind: 'news',
    suits: (d) => Array.isArray(d.items) && d.items.length > 0,
    why: (d) => `${d.items!.length} headlines`,
  },
  {
    kind: 'document',
    suits: (d) => typeof d.body === 'string' && d.body.length > 0,
    why: (d) => `${d.body!.length} characters of prose`,
  },
];

/**
 * The kind that suits this data, or null when nothing here can decide.
 *
 * Null is handed on to a model rather than resolved by a guess: a wrongly
 * chosen representation is not a neutral mistake — a table of prices rendered
 * as a distribution says something false about the data.
 */
export function representationFor(data: SurfaceData): SurfaceKind | null {
  if (!data || data.empty) return null;
  for (const shape of SHAPES) {
    if (shape.suits(data)) return shape.kind;
  }
  return null;
}

/**
 * The choice in words, including the refusals.
 *
 * A refusal with no reason is what makes an assistant look broken rather than
 * careful, and this string is spoken as well as logged.
 */
export function describeChoice(data: SurfaceData): string {
  if (!data || data.empty) {
    return `Nothing to draw${data?.note ? `: ${data.note}` : ''}`;
  }
  for (const shape of SHAPES) {
    if (shape.suits(data)) return `A ${shape.kind}, because this is ${shape.why(data)}.`;
  }
  // The one-point series lands here, and saying which is more useful than
  // "unrecognised" — it is the difference between a bug and a decision.
  if (Array.isArray(data.points) && data.points.length === 1) {
    return 'One number is not a trend, so there is no chart to draw from it.';
  }
  return 'This shape does not match anything the plane knows how to draw.';
}
