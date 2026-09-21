/**
 * Choosing Light must move the whole document, not just the chrome.
 *
 * `body` became token-driven when the light theme landed, and the toggle has
 * been correct since it was written — but `AppBackground` is a `position:fixed;
 * inset:0; z-index:0` layer mounted on every authenticated route, and it
 * painted a hardcoded dark gradient:
 *
 *     linear-gradient(180deg, #0a1424 0%, #0a0f1c 45%, #06090f 100%)
 *
 * So the ground stayed dark whatever the theme said. Measured in Chromium at
 * 1440x900 on /ai with colorScheme light: body resolved to #f4f5f8 and the
 * sidebar to #ffffff, over a navy canvas — a white sidebar on a dark page,
 * which is what the phone screenshot showed.
 *
 * The gradient, the aurora glows and the grid are now tokens that both themes
 * define. This test reads the component's source because the values must not
 * come back as literals: jsdom will not composite a fixed layer, and the
 * browser measurement that proves the rendered result is recorded in the commit
 * rather than re-run here.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(__dirname, '..');
const bg = fs.readFileSync(path.join(ROOT, 'components/AppBackground.tsx'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'index.css'), 'utf8');

/** Source with comments stripped — a literal quoted in a note explaining the
 *  fix is not a literal the browser paints. */
const code = bg.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const GROUND_TOKENS = [
  '--ground-base',
  '--ground-mid',
  '--ground-deep',
  '--ground-glow-a',
  '--ground-glow-b',
  '--ground-glow-c',
  '--ground-glow-d',
  '--ground-grid',
];

describe('the app background is theme-aware', () => {
  it('paints its ground from tokens, not from hex literals', () => {
    const hexes = code.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
    expect(hexes, `AppBackground still hardcodes ${hexes.join(', ')}`).toEqual([]);
  });

  it('does not hardcode rgba() tints either', () => {
    const rgba = code.match(/rgba?\(\s*\d+\s*,/g) ?? [];
    expect(rgba, `AppBackground still hardcodes ${rgba.length} rgb/rgba colour(s)`).toEqual([]);
  });

  it('every ground token is defined for BOTH themes', () => {
    const light = css.slice(css.indexOf(':root[data-theme="light"]'));
    for (const token of GROUND_TOKENS) {
      expect(css, `${token} is not declared at all`).toContain(`${token}:`);
      expect(light, `${token} has no light-theme value, so light mode keeps the dark one`)
        .toContain(`${token}:`);
    }
  });

  it('the dark gradient that caused this is gone', () => {
    expect(code).not.toContain('#0a1424');
    expect(code).not.toContain('#06090f');
  });
});
