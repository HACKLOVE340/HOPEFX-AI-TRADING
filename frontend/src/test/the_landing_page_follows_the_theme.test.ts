/**
 * The landing page obeys the theme, and a subtree can ask for dark.
 *
 * Measured in Chromium on the built page, 2026-09-19, before this change:
 *
 *     html data-theme = light
 *     body background = rgb(246, 247, 250)     <- light
 *     h1 colour       = rgb(11, 18, 32)        <- light --text-strong, near-black
 *     CTA background  = rgb(138, 90, 0)        <- light --accent, dark brown
 *
 * The app defaults to light. The landing page painted its own dark ground with
 * fixed literals -- `bg-terminal-bg`, `bg-neon-blue`, `text-slate-100` -- which
 * are theme-blind, so it looked right by not participating. `tailwind.config.ts`
 * says so itself about those groups: "fixed literals and are not [following the
 * theme] ... the thing new code should stop reaching for."
 *
 * That made the literals load-bearing. Moving the text to real tokens without
 * fixing the ground first put light-theme text on a dark background: proven by
 * the measurement above, which is why that attempt was reverted rather than
 * shipped.
 *
 * Two things are needed and this file holds both.
 *
 * (A) A dark scope that works BELOW the document root. `:root` already carries
 *     the dark values and `:root[data-theme="light"]` overrides them, so there
 *     was no way for one subtree to opt back into dark -- no `[data-theme="dark"]`
 *     block existed, and no `prefers-color-scheme` query either.
 *
 * (B) The landing page reaching for tokens instead of literals, so it is
 *     legible in whichever theme it is rendered under rather than only in the
 *     one its literals happened to match.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const CSS_RAW = readFileSync(resolve(__dirname, '../index.css'), 'utf-8');

/**
 * Comments stripped before anything is asserted about ORDER or presence.
 *
 * The first version of this file did not, and the comment written to explain
 * the dark scope mentions both selectors by name -- so the order check read
 * prose and failed against source that was correct. That is F255/F257 exactly,
 * committed by a test written the same hour as the note warning about it: a
 * checker that reads prose is not reading code.
 */
const CSS = CSS_RAW.replace(/\/\*[\s\S]*?\*\//g, '');
const LANDING = readFileSync(resolve(__dirname, '../pages/LandingPage.tsx'), 'utf-8');

describe('the harness reads what it claims to', () => {
  it('loaded both files', () => {
    expect(CSS.length).toBeGreaterThan(5_000);
    expect(LANDING.length).toBeGreaterThan(20_000);
    // If the token layer stops declaring these, every assertion below is vacuous.
    expect(CSS).toContain('--text-strong');
    expect(CSS).toContain('--accent');
  });
});

describe('(A) a subtree can ask for the dark palette', () => {
  it('declares a [data-theme="dark"] scope', () => {
    expect(CSS).toMatch(/\[data-theme="dark"\]/);
  });

  it('gives that scope the dark values, not an empty block', () => {
    // The scope must carry the same custom properties the root dark set does,
    // or a subtree opting into it would inherit light from the document.
    const match = CSS.match(/\[data-theme="dark"\][^{]*\{([\s\S]*?)\n  \}/);
    expect(match, 'the dark scope exists but its block could not be read').toBeTruthy();
    const block = match![1];
    for (const token of ['--bg', '--surface', '--text', '--text-strong', '--accent', '--border']) {
      expect(block, `the dark scope does not set ${token}`).toContain(token);
    }
  });

  it('keeps the light override able to win at the document root', () => {
    // Order matters: a later, equally specific rule wins. The light block must
    // still come after the dark one or toggling the theme would do nothing.
    expect(CSS.indexOf('[data-theme="dark"]')).toBeLessThan(CSS.indexOf(':root[data-theme="light"]'));
  });
});

describe('(B) the landing page reaches for tokens, not fixed literals', () => {
  /**
   * `terminal-*` and `neon-*` are named as fixed literals by the Tailwind
   * config's own comment; `slate-*` is stock Tailwind. None follows the theme.
   */
  const BANNED = [
    /\b(?:bg|text|border|from|via|to)-terminal-[a-z]+\b/g,
    /\b(?:bg|text|border|from|via|to)-neon-[a-z]+\b/g,
    /\b(?:bg|text|border|from|via|to)-slate-\d{2,3}\b/g,
  ];

  it('uses no theme-blind colour class', () => {
    const found = BANNED.flatMap((re) => LANDING.match(re) ?? []);
    const tally = [...new Set(found)].map((c) => `${c} x${found.filter((f) => f === c).length}`);
    expect(found, `theme-blind colour classes on the landing page: ${tally.join(', ')}`).toHaveLength(0);
  });

  it('actually reaches for the accent token', () => {
    // Guard against "passes because every colour was deleted".
    expect(LANDING).toMatch(/\b(?:bg|text|border)-accent\b/);
  });

  it('actually reaches for the surface and text roles', () => {
    expect(LANDING).toMatch(/\bbg-(?:base|surface|raised)\b/);
    expect(LANDING).toMatch(/\btext-(?:strong|ink|dim|muted|faint)\b/);
  });
});
