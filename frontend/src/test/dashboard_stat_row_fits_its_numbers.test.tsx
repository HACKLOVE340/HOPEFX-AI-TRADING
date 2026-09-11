/**
 * The stat row has to hold the numbers it is given.
 *
 * Measured in Chromium at 1440x1000 and at 1280x1000, after the tier change
 * shipped: the BALANCE tile's value needed 126px and had 112px of content box,
 * so `$100,000.00` was cut off mid-digit. Every funded account is six figures,
 * so this was not an edge case, it was the default. A prop account at
 * $1,000,000.00 needs ~149px.
 *
 * The same measurement showed the row breaking to [7, 1] at 1440 and [6, 2] at
 * 1280 — the eighth tile alone on a row with five empty columns beside it.
 * Both come from one cause: `repeat(auto-fill, minmax(130px, 1fr))` picks
 * however many 130px columns happen to fit, and the tier-1 tile's
 * `grid-column: span 2` made nine cells out of eight tiles, so the count never
 * divided evenly.
 *
 * jsdom has no layout engine, so it cannot measure a clip. What it can hold is
 * the decision: the row is a class with declared column counts, not an inline
 * style that no media query can reach.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const CSS = fs.readFileSync(path.resolve(__dirname, '../index.css'), 'utf8');

function block(selector: string): string {
  const at = CSS.indexOf(selector + ' {');
  if (at < 0) return '';
  return CSS.slice(at, CSS.indexOf('}', at));
}

describe('the stat row is laid out by the stylesheet', () => {
  it('declares a column count rather than auto-filling one', () => {
    const rule = block('.stat-row');
    expect(rule).not.toBe('');
    expect(rule).toMatch(/grid-template-columns:\s*repeat\(\s*\d+/);
    expect(rule).not.toMatch(/auto-fill|auto-fit/);
  });

  it('divides the eight tiles evenly at every width it declares', () => {
    const counts = [...CSS.matchAll(/\.stat-row\s*\{[^}]*grid-template-columns:\s*repeat\((\d+)/g)].map((m) =>
      Number(m[1]),
    );
    const media = [...CSS.matchAll(/\.stat-row\s*\{\s*grid-template-columns:\s*repeat\((\d+)/g)].map((m) =>
      Number(m[1]),
    );
    const all = [...new Set([...counts, ...media])];
    expect(all.length).toBeGreaterThan(1);
    for (const n of all) expect(8 % n).toBe(0);
  });

  it('gives no tile a column span, so eight tiles are eight cells', () => {
    expect(block('.stat-tile[data-tier="1"]')).not.toMatch(/grid-column/);
  });
});
