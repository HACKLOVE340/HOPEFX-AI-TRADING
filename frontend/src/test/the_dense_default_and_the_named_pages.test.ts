/**
 * Two things the design review settled, held where they can't drift back.
 *
 * DENSITY. `densityFor()` returned `promax` for anything not explicitly listed,
 * so the `ultra` tier existed and reached a handful of routes. The owner asked
 * for the dense treatment everywhere, so `ultra` is the default and
 * `comfortable` stays opt-in for the pages that read rather than scan.
 *
 * COPY. Eight destinations were in the route table with no line in
 * navDescriptions.ts — /dashboard /trade /portfolio /watchlist /alerts
 * /terminal /journal /settings. Every hub card and every "Where to next" tile
 * pointing at them rendered an empty paragraph. That is not a styling problem:
 * a card with a title and no sentence looks finished and says nothing.
 */
import { describe, it, expect } from 'vitest';

import { densityFor } from '../components/system/PageSurface';
import { NAV_ITEMS, HUBS } from '../components/sidebar/navConfig';
import { NAV_DESCRIPTIONS } from '../components/sidebar/navDescriptions';

describe('density', () => {
  it('defaults to ultra for a route that claims nothing', () => {
    expect(densityFor('/some-new-page')).toBe('ultra');
    expect(densityFor('/portfolio')).toBe('ultra');
  });

  it('still lets a reading page opt into comfortable', () => {
    // Whatever COMFORTABLE lists must still win over the new default,
    // otherwise the tier is dead code.
    const reading = ['/docs', '/academy', '/privacy', '/terms'];
    const honoured = reading.filter((p) => densityFor(p) === 'comfortable');
    expect(honoured.length, 'no route resolves to comfortable — the tier is unreachable')
      .toBeGreaterThan(0);
  });
});

describe('every destination says what it is', () => {
  it('has a description for each nav item', () => {
    const missing = NAV_ITEMS.filter((i) => !NAV_DESCRIPTIONS[i.path]).map((i) => i.path);
    expect(missing, `no line in navDescriptions.ts for: ${missing.join(', ')}`).toEqual([]);
  });

  it('has a description for each hub', () => {
    const missing = HUBS.filter((h) => !h.description).map((h) => h.path);
    expect(missing).toEqual([]);
  });

  it('writes them as sentences, not labels', () => {
    const tooShort = Object.entries(NAV_DESCRIPTIONS)
      .filter(([, d]) => d.trim().length < 20)
      .map(([p]) => p);
    expect(tooShort, `these read as labels rather than descriptions: ${tooShort.join(', ')}`).toEqual([]);
  });
});
