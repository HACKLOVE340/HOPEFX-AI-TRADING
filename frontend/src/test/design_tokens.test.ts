/**
 * The token layer must be complete, in both themes and on every surface.
 *
 * `frontend/src/index.css` has declared semantic tokens since 2026-09-11 and is
 * deliberately exempt from `scripts/frontend_colour_ratchet.py` — it is where
 * the palette is DEFINED, so its literals are not debt. What it never had was a
 * second half: no `[data-theme="light"]` rule existed anywhere in the project,
 * while `ThemeContext.tsx` stamped `data-theme` correctly and
 * `AppearanceSection.tsx` offered light / dark / system. Choosing Light saved
 * the preference and changed nothing.
 *
 * A token declared in one theme and not the other is exactly that bug in
 * miniature: it renders one theme's ink on the other theme's ground. So this
 * asserts the set, not the values — the palette is a design decision, its
 * COMPLETENESS is a correctness one.
 *
 * Three rules, each of which was violable before it was written:
 *   1. every colour token in the base block is redefined for light;
 *   2. every `var(--x)` used in the stylesheet is declared somewhere in it;
 *   3. a surface override may only redefine tokens that already exist — a
 *      typo'd token name in a scoped block is silent, and inherits the wrong
 *      colour rather than failing.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const RAW = readFileSync(resolve(__dirname, '../index.css'), 'utf8');

/**
 * Comments stripped before anything is parsed.
 *
 * This is not tidiness. The first version of this file read prose as code: a
 * comment reading `--bg: wells, inputs, code` made the declaration regex match
 * `--bg` and then run to the next semicolon, swallowing the real
 * `--border-strong` declaration on the following line — so the test reported a
 * token missing that was plainly there, twice. The repository has paid for this
 * exact shape before (F255: `security/code_analyzer.py` scanned docstrings and
 * `#` comments as if they were source, and `verify_skill_claims.py`, written to
 * confirm that fix, then failed four correct files for quoting the defect they
 * fixed). A checker that reads prose is not reading code.
 */
const CSS = RAW.replace(/\/\*[\s\S]*?\*\//g, ' ');

/** Body of the first rule whose selector matches, brace-balanced. */
function block(selector: string): string {
  const at = CSS.indexOf(selector);
  if (at === -1) throw new Error(`no rule for ${selector} in index.css`);
  // Search from `at`, not past the selector: a selector string that already
  // ends in '{' would otherwise skip its own brace and balance the NEXT rule.
  const open = CSS.indexOf('{', at);
  if (open === -1) throw new Error(`no block for ${selector}`);
  let depth = 0;
  for (let i = open; i < CSS.length; i += 1) {
    if (CSS[i] === '{') depth += 1;
    else if (CSS[i] === '}') {
      depth -= 1;
      if (depth === 0) return CSS.slice(open + 1, i);
    }
  }
  throw new Error(`unbalanced block for ${selector}`);
}

/** Custom properties declared directly in a block body. */
function declared(body: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    out.set(m[1]!, m[2]!.trim());
  }
  return out;
}

/** A token whose value is a colour, as opposed to a measure or a font stack. */
function isColour(value: string): boolean {
  return /^(#|rgba?\(|hsla?\(|color-mix\()/.test(value);
}

const base = declared(block(':root {'));
const light = declared(block(':root[data-theme="light"]'));
const ai = declared(block('[data-surface="ai"]'));
const ultra = declared(block('[data-density="ultra"]'));
const comfortable = declared(block('[data-density="comfortable"]'));
const promax = declared(block('[data-density="promax"]'));

describe('design tokens — index.css', () => {
  it('declares a base palette worth having', () => {
    expect(base.size).toBeGreaterThan(30);
  });

  it('redefines every base colour token for the light theme', () => {
    const colours = [...base].filter(([, v]) => isColour(v)).map(([k]) => k);
    expect(colours.length).toBeGreaterThan(20);
    const missing = colours.filter((k) => !light.has(k));
    expect(
      missing,
      `these colours have no light value, so choosing Light leaves them dark:\n  ${missing.join('\n  ')}`,
    ).toEqual([]);
  });

  it('never introduces a colour that exists only in the light theme', () => {
    // The mirror of the rule above: a token defined only under [data-theme]
    // is undefined in the un-stamped default, which is what most viewers get.
    const orphan = [...light.keys()].filter((k) => !base.has(k));
    expect(orphan, `light-only tokens, undefined in the default theme: ${orphan.join(', ')}`).toEqual([]);
  });

  it('declares every token it uses', () => {
    const used = new Set<string>();
    for (const m of CSS.matchAll(/var\((--[\w-]+)/g)) used.add(m[1]!);
    const undeclared = [...used].filter((k) => !base.has(k) && !light.has(k) && !ai.has(k));
    expect(undeclared, `var() references nothing declares: ${undeclared.join(', ')}`).toEqual([]);
  });

  it('carries a ten-step type scale, so a page cannot invent a size', () => {
    // Seven until 2026-09-18, when three display steps were added for the
    // eleven sites written above the old top. `the_type_scale_reaches_display_sizes`
    // holds their values and their reason; this holds the set.
    const steps = [
      '--fs-micro', '--fs-label', '--fs-body', '--fs-value', '--fs-title',
      '--fs-head', '--fs-hero', '--fs-display-sm', '--fs-display', '--fs-display-lg',
    ];
    const missing = steps.filter((s) => !base.has(s));
    expect(missing, `type scale incomplete: ${missing.join(', ')}`).toEqual([]);

    // Strictly ascending — a scale with a flat or reversed step is two names
    // for one size, which is how 24 distinct sizes happened in the first place.
    const px = steps.map((s) => parseFloat(base.get(s)!));
    for (let i = 1; i < px.length; i += 1) {
      expect(px[i], `${steps[i]} (${px[i]}px) must exceed ${steps[i - 1]} (${px[i - 1]}px)`).toBeGreaterThan(px[i - 1]!);
    }
  });

  it('gives the AI surface its own instrument palette without inventing tokens', () => {
    expect(ai.size).toBeGreaterThan(8);
    const unknown = [...ai.keys()].filter((k) => !base.has(k));
    expect(
      unknown,
      `[data-surface="ai"] sets tokens nothing else declares — a typo here is silent: ${unknown.join(', ')}`,
    ).toEqual([]);
  });

  it('keeps money semantics identical on the AI surface', () => {
    // Green and red mean price direction platform-wide. A surface that
    // restyles them teaches the operator a second vocabulary for the one
    // thing that must never be ambiguous.
    for (const token of ['--bull', '--bear', '--gain', '--loss']) {
      expect(ai.has(token), `${token} must not be redefined for the AI surface`).toBe(false);
    }
  });

  it('gives each density tier the same tokens, only retuned', () => {
    // A tier that sets a token the others do not is a page that changes shape
    // depending on which ancestor won, which is the bug this mechanism exists
    // to avoid. Promax restates the default deliberately, so it is the set.
    for (const [name, tier] of [['ultra', ultra], ['comfortable', comfortable]] as const) {
      const unknown = [...tier.keys()].filter((k) => !base.has(k));
      expect(unknown, `[data-density="${name}"] invents ${unknown.join(', ')}`).toEqual([]);
      const missing = [...promax.keys()].filter((k) => !tier.has(k));
      expect(missing, `[data-density="${name}"] is missing ${missing.join(', ')}`).toEqual([]);
    }
  });

  it('orders the tiers, and keeps the headline figure from collapsing', () => {
    const px = (m: Map<string, string>, k: string) => parseFloat(m.get(k)!);
    for (const step of ['--fs-body', '--pad-card', '--pad-row', '--gap-grid']) {
      expect(px(ultra, step), `${step} must be tightest in ultra`).toBeLessThan(px(promax, step));
      expect(px(comfortable, step), `${step} must be loosest in comfortable`).toBeGreaterThan(px(promax, step));
    }
    // Padding buys the rows; the hero figure is what the screen is about and
    // must not pay for them. It may shrink, but nothing like as much.
    const padShrink = 1 - px(ultra, '--pad-row') / px(promax, '--pad-row');
    const heroShrink = 1 - px(ultra, '--fs-hero') / px(promax, '--fs-hero');
    expect(heroShrink).toBeLessThan(padShrink / 3);
  });

  it('keeps density and palette independent', () => {
    // A density tier that set a colour would mean "denser" also meant
    // "different colour", and the two would stop composing.
    for (const [name, tier] of [['ultra', ultra], ['comfortable', comfortable], ['promax', promax]] as const) {
      const colours = [...tier].filter(([, v]) => isColour(v)).map(([k]) => k);
      expect(colours, `[data-density="${name}"] sets colours: ${colours.join(', ')}`).toEqual([]);
    }
  });

  it('declares motion durations so reduced-motion can zero them centrally', () => {
    for (const t of ['--dur-fast', '--dur-base', '--dur-slow', '--ease-out']) {
      expect(base.has(t), `${t} missing`).toBe(true);
    }
    expect(CSS).toContain('prefers-reduced-motion');
    // And the rule must actually zero the declared durations, not merely exist.
    expect(CSS).toMatch(/--dur-fast:\s*0/);
  });
});
