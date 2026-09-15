/**
 * Reduced motion is honoured in ONE place, and that place had no test.
 *
 * `docs/audit/FRONTEND_HANDOVER.md` said: "There is no motion layer:
 * transitions are per-component inline strings, so there is no way to honour
 * `prefers-reduced-motion` in one place." Measured 2026-09-15, that is wrong in
 * the direction that matters — there IS one place, at the top level of
 * `index.css`:
 *
 *     @media (prefers-reduced-motion: reduce) {
 *       *, *::before, *::after {
 *         animation-duration: 0.001ms !important;
 *         animation-iteration-count: 1 !important;
 *         transition-duration: 0.001ms !important;
 *         scroll-behavior: auto !important;
 *       }
 *       .hover-lift:hover { transform: none; }
 *     }
 *
 * That single rule is what stops 152 inline `transition:` strings and 192
 * Tailwind `transition-*` / `animate-*` classes from moving for someone who has
 * asked the operating system not to animate. It is unlayered and `!important`,
 * so it beats both Tailwind's `@layer` rules and a component's own inline
 * `style` attribute.
 *
 * Three things could delete that guarantee without any test going red: removing
 * the block, dropping `!important` from a declaration (an inline style then
 * wins), or moving it inside `@layer` (where an unlayered rule would outrank
 * it). `design_tokens.test.ts` pins only the token half — `--dur-fast: 0ms` —
 * which reaches the handful of transitions written as `var(--dur-*)` and not
 * the literal-millisecond majority.
 *
 * So this file pins the universal half. It asserts the rule, not a look: WCAG
 * 2.3.3 is a correctness requirement, and this is the only thing enforcing it
 * for most of the app.
 *
 * The OTHER half — a canvas, which is not the cascade and which no stylesheet
 * can quiet — is `src/hub/usePrefersReducedMotion.ts`, asserted by
 * `hub_viz.test.tsx` and `hub_spatial.test.ts`. Outside `src/hub/`, 17 files
 * call `requestAnimationFrame` and every one is a resize or visible-range
 * handler being rAF-throttled rather than an animation loop — checked one by
 * one, because "there is no motion layer" was also believed.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const CSS = readFileSync(resolve(__dirname, '../index.css'), 'utf8');

/** Body text of each `@media (prefers-reduced-motion: reduce)` block. */
function reducedMotionBlocks(css: string): { body: string; at: number }[] {
  const blocks: { body: string; at: number }[] = [];
  const opener = /@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{/g;
  let m: RegExpExecArray | null;
  while ((m = opener.exec(css)) !== null) {
    let depth = 1;
    let i = m.index + m[0].length;
    const start = i;
    while (i < css.length && depth > 0) {
      if (css[i] === '{') depth += 1;
      else if (css[i] === '}') depth -= 1;
      i += 1;
    }
    blocks.push({ body: css.slice(start, i - 1), at: m.index });
  }
  return blocks;
}

/** True when `index` sits inside an `@layer name { ... }` block. */
function insideALayer(css: string, index: number): boolean {
  const opener = /@layer\s+[\w\s,]+\{/g;
  let m: RegExpExecArray | null;
  while ((m = opener.exec(css)) !== null) {
    let depth = 1;
    let i = m.index + m[0].length;
    while (i < css.length && depth > 0) {
      if (css[i] === '{') depth += 1;
      else if (css[i] === '}') depth -= 1;
      i += 1;
    }
    if (index > m.index && index < i) return true;
  }
  return false;
}

const universal = () => reducedMotionBlocks(CSS).find((b) => /(?:^|\})\s*\*\s*,/.test(b.body));
const body = () => universal()?.body ?? '';

describe('someone who asked not to be animated is not animated', () => {
  it('has a reduced-motion block that reaches every element', () => {
    expect(universal(), 'no `*, *::before, *::after` reduced-motion rule in index.css').toBeTruthy();
    expect(body()).toMatch(/\*::before/);
    expect(body()).toMatch(/\*::after/);
  });

  it.each([
    ['animation-duration', /animation-duration\s*:\s*0(?:\.\d+)?m?s\s*!important/],
    ['transition-duration', /transition-duration\s*:\s*0(?:\.\d+)?m?s\s*!important/],
    ['animation-iteration-count', /animation-iteration-count\s*:\s*1\s*!important/],
    ['scroll-behavior', /scroll-behavior\s*:\s*auto\s*!important/],
  ])('zeroes %s, and with !important', (_name, pattern) => {
    // Without `!important` a component's own inline `style={{ transition: ... }}`
    // outranks the stylesheet and keeps moving.
    expect(body()).toMatch(pattern);
  });

  it('is NOT inside an @layer, where an unlayered rule would outrank it', () => {
    const block = universal();
    expect(block).toBeTruthy();
    expect(insideALayer(CSS, block!.at)).toBe(false);
  });

  it('also stills the hover lift, which is a transform rather than a duration', () => {
    // A 0ms transition does not stop `:hover { transform: translateY(-2px) }`;
    // it only makes the jump instant.
    expect(body()).toMatch(/\.hover-lift:hover\s*\{[^}]*transform\s*:\s*none/);
  });

  it('still zeroes the duration TOKENS, for the transitions that use them', () => {
    // The other half, and the half design_tokens.test.ts already guards. Both
    // are needed: tokens reach `var(--dur-*)` call sites, the universal rule
    // reaches the literal-millisecond majority.
    const tokenBlock = reducedMotionBlocks(CSS).find((b) => b.body.includes('--dur-fast'));
    expect(tokenBlock, 'no reduced-motion block zeroing the duration tokens').toBeTruthy();
    for (const token of ['--dur-fast', '--dur-base', '--dur-slow']) {
      expect(tokenBlock!.body).toMatch(new RegExp(`${token}\\s*:\\s*0m?s`));
    }
  });

  it('reads a stylesheet at all', () => {
    // The floor. A renamed or moved index.css would make the finders return
    // nothing, and a suite of `toBeTruthy` on undefined is a suite that only
    // looks green.
    expect(CSS.length).toBeGreaterThan(10_000);
    expect(reducedMotionBlocks(CSS).length).toBeGreaterThanOrEqual(2);
  });
});
