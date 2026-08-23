/**
 * F170 regression — sidebar navigation must render SVG icons, not emoji.
 *
 * Emoji were used as nav icons on every page (129-181 glyphs per rendered
 * page). They render differently on every OS, cannot inherit `currentColor`
 * so they ignore active/locked/hover state, and are announced literally by
 * screen readers ("chart increasing" for a Performance link).
 *
 * These tests are structural: they assert the shape of the config and the
 * absence of emoji in the two files that render it, so a future edit that
 * reintroduces a glyph fails here rather than in a screenshot review.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { NAV_ITEMS } from '../components/sidebar/navConfig';

const SRC = path.resolve(__dirname, '..');
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf-8');

/** Symbol/emoji code points, excluding the box-drawing chars used in comments. */
const GLYPH = /[\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2300}-\u{23FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;

describe('F170 — nav icons are SVG components', () => {
  it('every NAV_ITEMS icon is a renderable component, not a string', () => {
    expect(NAV_ITEMS.length).toBeGreaterThan(50);
    const bad = NAV_ITEMS.filter((i) => typeof i.icon === 'string' || i.icon == null);
    expect(bad.map((i) => i.path)).toEqual([]);
    for (const item of NAV_ITEMS) {
      // Lucide icons are forwardRef objects, not plain functions.
      expect(['function', 'object']).toContain(typeof item.icon);
    }
  });

  it('navConfig.ts contains no emoji or symbol glyphs', () => {
    const lines = read('components/sidebar/navConfig.ts').split('\n');
    const hits = lines
      .map((l, n) => [n + 1, l] as const)
      .filter(([, l]) => GLYPH.test(l));
    expect(hits).toEqual([]);
  });

  it('Sidebar.tsx renders no emoji or symbol glyphs', () => {
    const lines = read('components/sidebar/Sidebar.tsx').split('\n');
    const hits = lines
      .map((l, n) => [n + 1, l] as const)
      .filter(([, l]) => GLYPH.test(l));
    expect(hits).toEqual([]);
  });

  it('Sidebar.tsx does not render {item.icon} as bare text', () => {
    // The old renderer was `<span ...>{item.icon}</span>`, which stringifies a
    // component object to "[object Object]" if the type is ever loosened again.
    const src = read('components/sidebar/Sidebar.tsx');
    expect(src).not.toMatch(/>\s*\{item\.icon\}\s*</);
    expect(src).toMatch(/<item\.icon\b/);
  });

  it('icons are distinct enough to disambiguate destinations', () => {
    // F168: 📊 was reused 3x, 🤖 3x, 🔍 3x — the icon carried no information.
    const names = NAV_ITEMS.map((i) => (i.icon as { displayName?: string }).displayName ?? String(i.icon));
    const distinct = new Set(names);
    expect(distinct.size).toBeGreaterThanOrEqual(Math.floor(NAV_ITEMS.length * 0.9));
  });
});
