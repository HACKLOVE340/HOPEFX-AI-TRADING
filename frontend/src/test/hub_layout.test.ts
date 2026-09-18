/**
 * §8: "focus, compare, split, timeline, war-room and presentation layouts",
 * chosen from "task, viewport, object count and attention".
 *
 * The capability registry carried `workspace.layouts` as planned and
 * `workspace.auto_layout` as staged with the note "span from priority;
 * viewport-aware layout is not built". These tests are what moves both.
 *
 * They fail on the pre-fix tree — `hub/layout.ts` does not exist there.
 */

import { describe, expect, it } from 'vitest';

import { LAYOUTS, place, readLayout, suggestLayout, type LayoutName } from '../hub/layout';
import { Workspace } from '../hub/workspace';
import type { Surface } from '../hub/workspace';

/**
 * Indexing under `noUncheckedIndexedAccess` yields `T | undefined`, and a `!`
 * on every access would turn "the layout returned nothing" into a null-pointer
 * error three lines later. This fails where the mistake is.
 */
function nth<T>(xs: readonly T[], i: number): T {
  const value = xs[i];
  if (value === undefined) throw new Error(`expected an element at index ${i}, got ${xs.length}`);
  return value;
}

function build(specs: [string, Surface['priority']][]): readonly Surface[] {
  const ws = new Workspace();
  for (const [key, priority] of specs) {
    ws.open({ kind: 'chart', intent: key, priority, key });
  }
  return ws.surfaces;
}

const WIDE = { width: 1600 };

describe('the layouts §8 names all exist', () => {
  it('has every one of them', () => {
    for (const name of ['focus', 'compare', 'split', 'timeline', 'war_room', 'presentation']) {
      expect(LAYOUTS).toContain(name as LayoutName);
    }
  });

  it('places every surface under every layout, with no zero or overflowing span', () => {
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'primary'],
      ['c', 'secondary'],
      ['d', 'background'],
    ]);
    for (const layout of LAYOUTS) {
      const placed = place(surfaces, { layout, viewport: WIDE, focusedId: nth(surfaces, 1).id });
      expect(placed).toHaveLength(surfaces.length);
      for (const p of placed) {
        expect(p.span).toBeGreaterThanOrEqual(1);
        expect(p.span).toBeLessThanOrEqual(12);
      }
    }
  });
});

describe('compare means the same size', () => {
  it('gives two surfaces equal width even when their tiers differ', () => {
    // The whole point. Both are "the thing being compared"; one is critical and
    // one is background, and under `auto` that is 12 against 3 — a chart with a
    // footnote, not a comparison.
    const surfaces = build([
      ['gold', 'critical'],
      ['dxy', 'background'],
    ]);
    const auto = place(surfaces, { layout: 'auto', viewport: WIDE });
    expect(nth(auto, 0).span).not.toBe(nth(auto, 1).span);

    const compared = place(surfaces, { layout: 'compare', viewport: WIDE });
    expect(nth(compared, 0).span).toBe(nth(compared, 1).span);
  });

  it('keeps them equal at three and four surfaces too', () => {
    for (const n of [3, 4]) {
      const surfaces = build(
        Array.from({ length: n }, (_, i) => [`s${i}`, i === 0 ? 'critical' : 'background'] as [string, Surface['priority']]),
      );
      const spans = place(surfaces, { layout: 'compare', viewport: WIDE }).map((p) => p.span);
      expect(new Set(spans).size).toBe(1);
    }
  });
});

describe('focus means one dominates, not that the rest are gone', () => {
  it('gives the focused surface the full width', () => {
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'background'],
    ]);
    const target = surfaces.find((s) => s.key === 'b')!;
    const placed = place(surfaces, { layout: 'focus', focusedId: target.id, viewport: WIDE });
    expect(placed.find((p) => p.surface.id === target.id)!.span).toBe(12);
  });

  it('leaves the others on screen', () => {
    // "Focus on risk" is not "close everything else", and a layout that answered
    // the second question would lose work the operator did not ask to discard.
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'primary'],
      ['c', 'primary'],
    ]);
    const placed = place(surfaces, { layout: 'focus', focusedId: nth(surfaces, 0).id, viewport: WIDE });
    expect(placed.every((p) => p.visible)).toBe(true);
    expect(placed.filter((p) => p.surface.id !== nth(surfaces, 0).id).every((p) => p.span < 12)).toBe(true);
  });
});

describe('presentation shows one thing, and says the others are hidden', () => {
  it('marks exactly one visible', () => {
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'primary'],
      ['c', 'primary'],
    ]);
    const placed = place(surfaces, { layout: 'presentation', focusedId: nth(surfaces, 2).id, viewport: WIDE });
    expect(placed.filter((p) => p.visible)).toHaveLength(1);
    expect(placed.find((p) => p.visible)!.surface.id).toBe(nth(surfaces, 2).id);
  });

  it('still returns the hidden ones so the caller can say how many there are', () => {
    // A surface that vanishes with no trace is indistinguishable from one that
    // was closed, and an operator who cannot tell rebuilds the workspace.
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'primary'],
    ]);
    const placed = place(surfaces, { layout: 'presentation', viewport: WIDE });
    expect(placed).toHaveLength(2);
    expect(placed.filter((p) => !p.visible)).toHaveLength(1);
  });

  it('falls back to the most important surface when nothing is focused', () => {
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'primary'],
    ]);
    const placed = place(surfaces, { layout: 'presentation', focusedId: null, viewport: WIDE });
    expect(placed.find((p) => p.visible)!.surface.key).toBe('a');
  });
});

describe('war room is density on purpose', () => {
  it('makes everything smaller than auto would', () => {
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'critical'],
      ['c', 'critical'],
    ]);
    const auto = place(surfaces, { layout: 'auto', viewport: WIDE });
    const war = place(surfaces, { layout: 'war_room', viewport: WIDE });
    expect(nth(auto, 0).span).toBe(12);
    expect(war.every((p) => p.span === 4)).toBe(true);
  });
});

describe('timeline gets the full width', () => {
  it('never puts a history in a quarter column', () => {
    const surfaces = build([
      ['a', 'background'],
      ['b', 'background'],
    ]);
    expect(place(surfaces, { layout: 'timeline', viewport: WIDE }).every((p) => p.span === 12)).toBe(true);
  });
});

// ── the rule that overrides every layout ─────────────────────────────────────

describe('legibility beats the layout', () => {
  it('collapses to one column on a phone, whatever was asked for', () => {
    // A three-of-twelve panel is 90 pixels wide at 375. It renders, it passes a
    // screenshot test, and nobody can read it.
    const surfaces = build([
      ['a', 'critical'],
      ['b', 'background'],
      ['c', 'background'],
    ]);
    for (const layout of LAYOUTS) {
      const placed = place(surfaces, { layout, viewport: { width: 375 }, focusedId: nth(surfaces, 0).id });
      expect(placed.filter((p) => p.visible).every((p) => p.span === 12)).toBe(true);
    }
  });

  it('floors every span at half width on a tablet', () => {
    const surfaces = build([
      ['a', 'background'],
      ['b', 'background'],
      ['c', 'background'],
    ]);
    const placed = place(surfaces, { layout: 'war_room', viewport: { width: 900 } });
    expect(placed.every((p) => p.span >= 6)).toBe(true);
  });

  it('does not exempt a pinned surface from the collapse', () => {
    // Pinning says "keep this on screen", not "make it 90 pixels wide".
    const ws = new Workspace();
    const id = ws.open({ kind: 'chart', intent: 'gold', priority: 'background', key: 'gold' });
    ws.pin(id);
    const placed = place(ws.surfaces, { layout: 'war_room', viewport: { width: 375 } });
    expect(nth(placed, 0).surface.pinned).toBe(true);
    expect(nth(placed, 0).span).toBe(12);
  });
});

// ── choosing one when nobody named one ───────────────────────────────────────

describe('suggestLayout reads the plane', () => {
  it('focuses when something is focused', () => {
    const surfaces = build([['a', 'primary'], ['b', 'primary']]);
    expect(suggestLayout(surfaces, nth(surfaces, 0).id)).toBe('focus');
  });

  it('compares when there are exactly two', () => {
    expect(suggestLayout(build([['a', 'primary'], ['b', 'primary']]), null)).toBe('compare');
  });

  it('opens the war room once the plane is crowded', () => {
    const surfaces = build(
      Array.from({ length: 9 }, (_, i) => [`s${i}`, 'secondary'] as [string, Surface['priority']]),
    );
    expect(suggestLayout(surfaces, null)).toBe('war_room');
  });

  it('never infers presentation, because hiding things is the operator’s call', () => {
    for (let n = 0; n <= 20; n += 1) {
      const surfaces = build(
        Array.from({ length: n }, (_, i) => [`s${i}`, 'secondary'] as [string, Surface['priority']]),
      );
      expect(suggestLayout(surfaces, null)).not.toBe('presentation');
    }
  });

  it('ignores a focus id that is not on the plane', () => {
    // Otherwise closing the focused surface leaves the plane in focus mode with
    // nothing focused, and one arbitrary panel silently full width.
    const surfaces = build([['a', 'primary'], ['b', 'primary']]);
    expect(suggestLayout(surfaces, 'gone')).toBe('compare');
  });
});

describe('readLayout understands what was said', () => {
  const cases: [string, LayoutName][] = [
    ['open the war room', 'war_room'],
    ['war-room please', 'war_room'],
    ['compare gold and the dollar', 'compare'],
    ['show them side by side', 'compare'],
    ['gold vs dxy', 'compare'],
    ['presentation mode', 'presentation'],
    ['one at a time', 'presentation'],
    ['show me the timeline', 'timeline'],
    ['what happened over time', 'timeline'],
    ['split the screen', 'split'],
    ['focus on risk', 'focus'],
    ['reset layout', 'auto'],
  ];

  for (const [phrase, expected] of cases) {
    it(`reads ${JSON.stringify(phrase)} as ${expected}`, () => {
      expect(readLayout(phrase)).toBe(expected);
    });
  }

  it('returns null rather than guessing when no layout was named', () => {
    // So the caller can fall through to suggestLayout. A guess here would
    // rearrange the plane every time somebody asked an ordinary question.
    expect(readLayout('what is gold doing')).toBeNull();
    expect(readLayout('')).toBeNull();
  });
});
