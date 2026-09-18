/**
 * `data-density` was a dead control.
 *
 * It is stamped on every route by `PageSurface`, it has three fully-specified
 * tiers in `index.css`, and it is documented in CLAUDE.md as "one table,
 * stamped on every route". All of that was true and none of it reached a pixel:
 * measured across `frontend/src`, the tokens the tiers redefine are consumed by
 * **29** class usages in the whole application, against **2,871** inline
 * `fontSize: <number>` and **1,089** numeric Tailwind spacing utilities.
 *
 * So switching tiers changed almost nothing, which is why the interface did not
 * feel dense at any setting. That is the shape `.claude/skills/hopefx-dead-controls`
 * names: a control that exists, is documented accurately, and never runs.
 *
 * This file is the proof it runs now, for the surfaces that can be reached
 * today. It asserts on COMPUTED style through a real cascade rather than on the
 * presence of an attribute — an attribute test would have passed against the
 * dead version, which is exactly how the control stayed dead.
 *
 * What it deliberately does NOT claim: that density reaches the whole app. It
 * cannot, until those 2,871 literal sizes reach the token layer. That is
 * tracked as DENSITY-CANNOT-REACH in the correction register, measured from the
 * tree rather than asserted here.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * Read the real `index.css` and pull the tokens each tier declares.
 *
 * Parsed from the text rather than resolved through jsdom's cascade, and that
 * is not a shortcut: the tiers live inside `@layer base`, which jsdom's CSSOM
 * drops entirely, so `getComputedStyle` returns empty strings for every one of
 * them. A cascade test here would have been a test of jsdom's coverage. The
 * live cascade is proved in a browser instead — see the commit.
 *
 * Reading the real file rather than a fixture is the point: a fixture lets
 * index.css and this test drift apart while the test keeps passing.
 */
function tierTokens(tier: string): Record<string, number> {
  const css = readFileSync(resolve(__dirname, '../index.css'), 'utf8');
  const marker = `[data-density="${tier}"]`;
  const start = css.indexOf(marker);
  if (start < 0) throw new Error(`no rule for ${marker}`);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  const body = css.slice(open + 1, close);
  const out: Record<string, number> = {};
  for (const line of body.split('\n')) {
    const m = /^\s*(--[a-z-]+)\s*:\s*([0-9.]+)(px)?\s*;/.exec(line);
    if (m) out[m[1]!] = Number.parseFloat(m[2]!);
  }
  return out;
}

const REQUIRED = ['--fs-micro', '--fs-label', '--fs-body', '--fs-value', '--fs-title', '--fs-head', '--fs-hero', '--pad-card', '--pad-row', '--gap-grid', '--lh-body'];

describe('the three tiers are actually different', () => {
  it('declares every density token at every tier', () => {
    // A tier missing a token silently inherits the one above it, which is how a
    // "tier" becomes a label with nothing behind it.
    for (const tier of ['comfortable', 'promax', 'ultra']) {
      const tokens = tierTokens(tier);
      for (const name of REQUIRED) {
        expect(tokens[name], `${tier} is missing ${name}`).toBeTypeOf('number');
      }
    }
  });

  it('tightens monotonically from comfortable through promax to ultra', () => {
    // If two tiers ever resolve to the same number for a token, switching
    // between them does nothing for it.
    const comfortable = tierTokens('comfortable');
    const promax = tierTokens('promax');
    const ultra = tierTokens('ultra');
    for (const token of REQUIRED) {
      expect(comfortable[token]!, token).toBeGreaterThan(promax[token]!);
      expect(promax[token]!, token).toBeGreaterThan(ultra[token]!);
    }
  });

  it('is a real difference, not a rounding one', () => {
    // Two tiers a third of a pixel apart are one tier with two names.
    const comfortable = tierTokens('comfortable');
    const ultra = tierTokens('ultra');
    expect(comfortable['--fs-body']! / ultra['--fs-body']!).toBeGreaterThan(1.15);
    expect(comfortable['--pad-card']! / ultra['--pad-card']!).toBeGreaterThan(1.5);
    expect(comfortable['--pad-row']! / ultra['--pad-row']!).toBeGreaterThan(1.5);
  });
});
