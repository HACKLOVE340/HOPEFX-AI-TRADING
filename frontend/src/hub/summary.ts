/**
 * hub/summary.ts — what everything on the plane adds up to.
 *
 * §10: "summarise across surfaces and name relationships." Six panels open is
 * six things to read; the value the AI adds is saying how they bear on each
 * other, which is the part a dashboard has never been able to do.
 *
 * ## The relationships are declared, not inferred
 *
 * A model could be asked to find connections between whatever happens to be on
 * screen. It would find some, and some of those would be wrong, and a confident
 * false statement about how risk limits relate to open exposure is a much more
 * expensive mistake on this platform than saying nothing.
 *
 * So RELATIONS below is a table somebody wrote down and a test asserts. It is
 * incomplete on purpose — an unlisted pair produces no claim rather than a
 * plausible one, and the summary says how many surfaces it had nothing to say
 * about instead of implying it covered them.
 *
 * ## It states what it can see, not what is true
 *
 * The summary names the panels and their relationships. It does not read the
 * numbers inside them and conclude anything: "risk limits govern that exposure"
 * is a fact about the screen, "you are close to your limit" is a fact about the
 * account, and only the first is knowable from here. Mixing them is how a
 * layout engine ends up making a risk assertion.
 */

import type { Surface } from './workspace';

export interface Relation {
  /** Surface keys, in either order. */
  a: string;
  b: string;
  /** How they bear on each other, as a sentence fragment. */
  because: string;
}

/**
 * Pairs of surfaces whose relationship somebody has written down.
 *
 * Keyed on `SurfaceRequest.key`, the stable identifier — not on the displayed
 * meaning, which is prose and changes.
 */
export const RELATIONS: readonly Relation[] = [
  { a: 'gold-chart', b: 'gold-exposure', because: 'that exposure is to the instrument on this chart' },
  { a: 'gold-chart', b: 'gold-news', because: 'these headlines are what move that price' },
  { a: 'gold-chart', b: 'positions', because: 'the open positions are in the instrument on this chart' },
  { a: 'gold-exposure', b: 'risk', because: 'those limits are what govern this exposure' },
  { a: 'positions', b: 'risk', because: 'those limits are what govern these positions' },
  { a: 'risk', b: 'risk-dist', because: 'this distribution is where those limits came from' },
  { a: 'news', b: 'gold-chart', because: 'these headlines are what move that price' },
  { a: 'spend', b: 'calls', because: 'these calls are what that spend paid for' },
  { a: 'spend', b: 'agents', because: 'these agents are what is spending it' },
  { a: 'agents', b: 'calls', because: 'these calls are what those agents made' },
];

export interface CrossSurfaceSummary {
  /** One paragraph, ready to be spoken. Empty when the plane is empty. */
  text: string;
  /** The relationships found, for a caller that wants to draw them. */
  relations: { a: Surface; b: Surface; because: string }[];
  /** Surfaces with no declared relationship to anything else here. */
  unrelated: Surface[];
}

function relationFor(a: string, b: string): Relation | undefined {
  return RELATIONS.find((r) => (r.a === a && r.b === b) || (r.a === b && r.b === a));
}

function list(items: string[]): string {
  if (items.length === 0) return '';
  if (items.length === 1) return items[0]!;
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

export function summarise(surfaces: readonly Surface[]): CrossSurfaceSummary {
  if (surfaces.length === 0) {
    return { text: '', relations: [], unrelated: [] };
  }

  const relations: CrossSurfaceSummary['relations'] = [];
  const related = new Set<string>();
  for (let i = 0; i < surfaces.length; i += 1) {
    for (let j = i + 1; j < surfaces.length; j += 1) {
      const a = surfaces[i]!;
      const b = surfaces[j]!;
      const found = relationFor(a.key, b.key);
      if (!found) continue;
      relations.push({ a, b, because: found.because });
      related.add(a.id);
      related.add(b.id);
    }
  }
  const unrelated = surfaces.filter((s) => !related.has(s.id));

  if (surfaces.length === 1) {
    return { text: `One surface: ${surfaces[0]!.meaning}.`, relations: [], unrelated: [...surfaces] };
  }

  const parts: string[] = [
    `${surfaces.length} surfaces: ${list(surfaces.map((s) => s.meaning))}.`,
  ];

  if (relations.length > 0) {
    // At most three, spoken. A summary that recites nine relationships is a
    // second thing to read rather than a way of not reading the first.
    parts.push(
      ...relations
        .slice(0, 3)
        .map((r) => `${r.a.meaning} and ${r.b.meaning} are connected — ${r.because}.`),
    );
    if (relations.length > 3) {
      parts.push(`${relations.length - 3} more connections between them.`);
    }
  }

  if (unrelated.length > 0) {
    // Said rather than left out. "I have nothing to say about these two" is
    // information; quietly omitting them implies they were covered.
    parts.push(
      unrelated.length === surfaces.length
        ? 'I have no declared relationship between any of these.'
        : `Nothing declared linking ${list(unrelated.map((s) => s.meaning))} to the rest.`,
    );
  }

  return { text: parts.join(' '), relations, unrelated };
}

/** Whether a phrase is asking for this. Local and deterministic, like the rest. */
export function asksForSummary(phrase: string): boolean {
  const text = (phrase ?? '').toLowerCase();
  return /\b(summari[sz]e|summary|what am i looking at|explain (all of )?(this|these)|how (do|does) (these|they|this) (relate|connect)|tie (this|these) together|what does this mean)\b/.test(
    text,
  );
}
