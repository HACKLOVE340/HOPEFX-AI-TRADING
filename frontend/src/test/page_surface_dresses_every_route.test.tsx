/**
 * Every route gets a density, and only AI routes get the AI palette.
 *
 * `PageSurface` is the single place that decides how 87 routes are dressed.
 * That is its value and its risk: one wrong prefix silently restyles a whole
 * section, and a stale entry keeps styling a route that no longer exists.
 *
 * So this asserts three things the mechanism can get wrong without any visible
 * error:
 *   1. the prefix matcher does not swallow siblings — `/ai` must not catch
 *      `/alerts`, `/trade` must not catch `/trading` by accident of ordering;
 *   2. every path named in the tables is a route the app actually has, checked
 *      against App.tsx rather than trusted;
 *   3. a page with no entry still gets the default, never an empty attribute —
 *      an empty `data-surface` still matches `[data-surface]` selectors written
 *      later, and the page would acquire a palette nobody chose.
 */

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import React from 'react';
import { PageSurface, densityFor, surfaceFor } from '../components/system/PageSurface';

const APP = readFileSync(resolve(__dirname, '../App.tsx'), 'utf8');

/**
 * Every route prefix declared in App.tsx.
 *
 * A parameterised route contributes its static head: `/positions/:id` is what
 * makes `/positions` a real prefix to style, and an extractor that only saw
 * literal paths called it an orphan.
 */
const ROUTES = new Set(
  [...APP.matchAll(/path="(\/[^"]*)"/g)].map((m) => {
    const head = m[1]!.split('/:')[0]!;
    return head === '' ? '/' : head;
  }),
);

function stamp(path: string): HTMLElement {
  const { container } = render(
    <MemoryRouter initialEntries={[path]}>
      <PageSurface>
        <span>page</span>
      </PageSurface>
    </MemoryRouter>,
  );
  return container.firstElementChild as HTMLElement;
}

describe('PageSurface', () => {
  it('gives data pages ultra density', () => {
    for (const p of ['/trade', '/portfolio', '/journal', '/superadmin', '/tca']) {
      expect(densityFor(p), p).toBe('ultra');
    }
  });

  it('gives reading pages comfortable density', () => {
    for (const p of ['/academy', '/docs', '/terms', '/pricing', '/onboarding']) {
      expect(densityFor(p), p).toBe('comfortable');
    }
  });

  it('leaves everything else at the pro-max default', () => {
    for (const p of ['/dashboard', '/settings', '/notifications', '/marketplace']) {
      expect(densityFor(p), p).toBe('promax');
    }
  });

  it('does not let a prefix swallow a sibling route', () => {
    // `/ai-*` are AI surfaces; `/alerts` and `/affiliate` start with the same
    // letters and are not. `/trade` and `/trading` are separate routes.
    expect(surfaceFor('/alerts')).toBe('default');
    expect(surfaceFor('/affiliate')).toBe('default');
    expect(surfaceFor('/ai-core')).toBe('ai');
    expect(surfaceFor('/ai-strategy')).toBe('ai');
    expect(densityFor('/trade')).toBe('ultra');
    expect(densityFor('/trading')).toBe('ultra');
    // A deeper path under a listed prefix inherits it — that is the point of
    // matching prefixes, and `/positions/:id` is the reason.
    expect(densityFor('/positions/P-8841')).toBe('ultra');
  });

  it('only names routes the app actually has', () => {
    const tables = readFileSync(
      resolve(__dirname, '../components/system/PageSurface.tsx'),
      'utf8',
    );
    const paths = [...tables.matchAll(/'(\/[a-z0-9-]+)'/g)].map((m) => m[1]!);
    expect(paths.length).toBeGreaterThan(40);
    const orphans = [...new Set(paths)].filter((p) => !ROUTES.has(p));
    expect(
      orphans,
      `PageSurface styles routes that do not exist — a stale entry silently dresses nothing:\n  ${orphans.join('\n  ')}`,
    ).toEqual([]);
  });

  it('stamps density on every page and the AI palette on only AI pages', () => {
    const ai = stamp('/ai-core');
    expect(ai.getAttribute('data-density')).toBe('promax');
    expect(ai.getAttribute('data-surface')).toBe('ai');

    const plain = stamp('/dashboard');
    expect(plain.getAttribute('data-density')).toBe('promax');
    // Absent, not empty: an empty attribute still matches [data-surface].
    expect(plain.hasAttribute('data-surface')).toBe(false);

    expect(stamp('/portfolio').getAttribute('data-density')).toBe('ultra');
  });

  it('adds no box of its own, so no page layout shifts', () => {
    // display:contents — the attributes inherit, the layout does not change.
    expect(stamp('/dashboard').className).toBe('contents');
  });
});
