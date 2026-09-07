/**
 * hub/resolveReference.ts — §9's semantic panel registry, asked a question.
 *
 * `reference.ts:referencesIn` matches a phrase against what a panel MEANS. It
 * cannot answer "the one on the left", and relative reference is most of how
 * people actually point at things on a screen: beside it, under it, behind
 * that one, the other one.
 *
 * That needs the scene, which is why this file exists rather than another
 * branch inside `referencesIn`: one function answers "which panels does this
 * sentence touch" for highlighting, and this one answers "which single panel
 * does the operator want acted on". Merging them would make a highlight and an
 * action share a resolution, and the right answer differs — a sentence
 * comparing gold and the dollar highlights two panels and acts on neither.
 *
 * ## Refusal carries the reason, and the reason is different every time
 *
 * Four things can go wrong, and an operator's next move differs for each:
 *
 *   nothing matched          → say what is on screen
 *   two panels matched       → ask which, naming both
 *   relative with no anchor  → ask which panel they mean by "it"
 *   nothing in that direction → say so; do NOT wrap round to the far side
 *
 * A single `null` for all four is the shape that makes an assistant say "I did
 * not understand" to somebody who was perfectly clear.
 *
 * ## Wrapping is refused on purpose
 *
 * `RovingFocus` wraps, because a keyboard list that stops dead reads as broken.
 * A spatial reference is the opposite: "the one on the left" wrapping to the
 * far right of the plane moves a panel the operator was not looking at, and on
 * a trading screen that is the failure that costs something.
 */

import type { SceneGraph, Direction } from './sceneGraph';
import { referencesIn } from './reference';
import type { Surface } from './workspace';

export type Reference =
  | { resolved: true; id: string; how: string }
  | { resolved: false; why: string; candidates: readonly string[] };

export interface ResolveOptions {
  /** What the operator last selected. The anchor for "it" and "that one". */
  focusedId?: string | null;
}

/**
 * Relative phrases, longest first.
 *
 * Longest first because "to the left of" contains "left": matching the short
 * form first would take "to the left of the dollar index" apart at the wrong
 * seam and lose the anchor.
 */
const DIRECTIONS: readonly { pattern: RegExp; direction: Direction; word: string }[] = [
  { pattern: /\b(?:to the |on the )?left(?: of)?\b/, direction: 'left', word: 'left' },
  { pattern: /\b(?:to the |on the )?right(?: of)?\b/, direction: 'right', word: 'right' },
  { pattern: /\b(?:just )?(?:above|over|on top of)\b/, direction: 'above', word: 'above' },
  { pattern: /\b(?:just )?(?:below|under|underneath|beneath)\b/, direction: 'below', word: 'below' },
];

/** Depth phrases. Answered from z-order, which is why the scene has to carry it. */
const IN_FRONT = /\b(?:in front of|over the top of|covering)\b/;
const BEHIND = /\b(?:behind|beneath in the stack|hidden by)\b/;

export function resolveReference(
  phrase: string,
  surfaces: readonly Surface[],
  scene: SceneGraph,
  options: ResolveOptions = {},
): Reference {
  const text = (phrase ?? '').toLowerCase().trim();
  if (!text) return refuse('an empty phrase names no panel');

  const measured = new Set(scene.ids());
  const named = referencesIn(text, surfaces);

  // Depth first: "in front of the heatmap" names the heatmap and wants what is
  // on top of it, so a name match alone would return the wrong panel.
  if (IN_FRONT.test(text) || BEHIND.test(text)) {
    return byDepth(text, named, scene, measured, options);
  }

  const directional = DIRECTIONS.find((d) => d.pattern.test(text));
  if (directional) return byDirection(directional, named, scene, measured, options);

  if (named.length === 1) {
    const id = named[0]!;
    if (!measured.has(id)) return refuse(notMeasured(id));
    return { resolved: true, id, how: `it is the only panel whose meaning matches those words` };
  }
  if (named.length > 1) {
    return refuse(`more than one panel matches those words`, named);
  }
  return refuse('no panel on the plane matches those words');
}

function byDirection(
  directional: { direction: Direction; word: string },
  named: readonly string[],
  scene: SceneGraph,
  measured: Set<string>,
  options: ResolveOptions,
): Reference {
  const anchor = anchorFor(named, measured, options);
  if (!anchor.resolved) return anchor;

  const found = scene.neighbour(anchor.id, directional.direction);
  if (found === null) {
    // Deliberately not wrapped. See the module docstring.
    return refuse(`there is nothing to the ${directional.word} of that panel`);
  }
  return { resolved: true, id: found, how: `it is the panel to the ${directional.word} of ${anchor.id}` };
}

function byDepth(
  text: string,
  named: readonly string[],
  scene: SceneGraph,
  measured: Set<string>,
  options: ResolveOptions,
): Reference {
  const anchor = anchorFor(named, measured, options);
  if (!anchor.resolved) return anchor;

  if (IN_FRONT.test(text)) {
    const covering = scene.occludedBy(anchor.id);
    if (covering.length === 0) return refuse(`nothing is drawn in front of that panel`);
    if (covering.length > 1) return refuse(`more than one panel is drawn in front of that one`, covering);
    return { resolved: true, id: covering[0]!, how: `it is drawn in front of ${anchor.id}` };
  }

  // "behind X" — the panels X is drawn in front of.
  const behind = scene.ids().filter((id) => id !== anchor.id && scene.occludedBy(id).includes(anchor.id));
  if (behind.length === 0) return refuse(`nothing is behind that panel`);
  if (behind.length > 1) return refuse(`more than one panel is behind that one`, behind);
  return { resolved: true, id: behind[0]!, how: `it is drawn behind ${anchor.id}` };
}

/**
 * What a relative phrase is relative to.
 *
 * A name in the phrase wins over the focused panel: "the one to the left of
 * the dollar index" is explicit, and preferring the selection there would
 * answer a question nobody asked.
 */
function anchorFor(
  named: readonly string[],
  measured: Set<string>,
  options: ResolveOptions,
): { resolved: true; id: string; how: string } | { resolved: false; why: string; candidates: readonly string[] } {
  if (named.length > 1) return refuse('more than one panel matches the words in that phrase', named);
  if (named.length === 1) {
    const id = named[0]!;
    if (!measured.has(id)) return refuse(notMeasured(id));
    return { resolved: true, id, how: '' };
  }
  const focused = options.focusedId;
  if (focused && measured.has(focused)) return { resolved: true, id: focused, how: '' };
  return refuse('that phrase is relative and nothing says which panel it is relative to');
}

function notMeasured(id: string): string {
  return `${id} is no longer on the plane, or was not measured in the last pass`;
}

function refuse(why: string, candidates: readonly string[] = []): { resolved: false; why: string; candidates: readonly string[] } {
  return { resolved: false, why, candidates };
}
