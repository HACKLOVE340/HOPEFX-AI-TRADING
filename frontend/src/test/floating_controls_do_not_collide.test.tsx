/**
 * Two floating controls, one corner.
 *
 * `presenceDock.ts` was built so the presence "never silently covers
 * something": `dockFor` takes an `avoid` list, tries each corner, and reports
 * the overlap when every corner collides. That machinery works. Nothing ever
 * passed it a rect — `PresenceAnywhereMount` never set `avoid` — so it chose
 * `bottom-right` on every page, which is exactly where the support launcher
 * sits. Measured in Chromium at 1440x1000 on /dashboard: the launcher occupies
 * (1358,924)-(1414,980) and the presence panel (1320,880)-(1416,1351). They
 * intersect, and the launcher's z-index of 1200 puts it on top of a control at
 * z-40 — so the presence was not merely ugly there, part of it was unclickable.
 *
 * A guard that can never open is the `hopefx-dead-controls` shape. These tests
 * hold the wiring, not the algorithm: the algorithm already had a test.
 */
import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import fs from 'node:fs';
import path from 'node:path';

import {
  LAUNCHER_RIGHT_PX,
  LAUNCHER_SIZE_PX,
  SLIVER_HEIGHT_PX,
  SLIVER_WIDTH_PX,
  launcherRect,
} from '../components/ai/AISupportWidget';
import { clearLanes, reserveLane, readLanes } from '../hub/floatingLanes';
import { PresenceAnywhereMount } from '../hub/PresenceAnywhereMount';
import { dockFor } from '../hub/presenceDock';

const VIEWPORT = { x: 0, y: 0, width: 1440, height: 1000 };

/* The suite's global ResizeObserver stub is a no-op, so nothing a component
   measures ever arrives. Capture the callbacks here and fire them by hand. */
const observerCallbacks: Array<() => void> = [];
class RecordingResizeObserver {
  constructor(callback: () => void) {
    observerCallbacks.push(callback);
  }
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', RecordingResizeObserver);

function overlaps(a: DOMRect | typeof VIEWPORT, b: typeof VIEWPORT): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

beforeEach(() => {
  observerCallbacks.length = 0;
  clearLanes();
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ capabilities: [] }) }));
  window.innerWidth = VIEWPORT.width;
  window.innerHeight = VIEWPORT.height;
});

describe('the support launcher publishes where it is', () => {
  it('reports a rect in the corner it actually occupies', () => {
    const rect = launcherRect({ bottom: 20, docked: false }, VIEWPORT);
    // Bottom-right, above the fold, and big enough to be the thing you click.
    expect(rect.width).toBeGreaterThanOrEqual(44);
    expect(rect.height).toBeGreaterThanOrEqual(44);
    expect(rect.x + rect.width).toBeLessThanOrEqual(VIEWPORT.width);
    expect(rect.y + rect.height).toBeLessThanOrEqual(VIEWPORT.height);
    expect(rect.y).toBeGreaterThan(VIEWPORT.height / 2);
  });

  it('reports a narrower rect once parked at the edge', () => {
    const out = launcherRect({ bottom: 20, docked: false }, VIEWPORT);
    const parked = launcherRect({ bottom: 20, docked: true }, VIEWPORT);
    expect(parked.width).toBeLessThan(out.width);
  });
});

describe('the presence is told about it', () => {
  it('places itself clear of a reserved lane', async () => {
    reserveLane('support-launcher', launcherRect({ bottom: 20, docked: false }, VIEWPORT));

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <PresenceAnywhereMount />
      </MemoryRouter>,
    );

    const panel = await screen.findByRole('complementary', { name: /assistant/i });
    // The dock writes its chosen corner into inline left/top, so the position
    // is readable without a layout engine.
    const x = parseFloat(panel.style.left);
    const y = parseFloat(panel.style.top);
    const width = parseFloat(panel.style.width) || 96;
    const height = 96;
    expect(Number.isFinite(x)).toBe(true);

    const lane = readLanes()[0];
    expect(lane).toBeDefined();
    expect(overlaps({ x, y, width, height } as never, lane as typeof VIEWPORT)).toBe(false);
  });
});

describe('the published rect matches the stylesheet', () => {
  it('uses the size and offset index.css actually renders', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../index.css'), 'utf8');
    const rule = (selector: string) => {
      const at = css.indexOf(selector + ' {');
      return at < 0 ? '' : css.slice(at, css.indexOf('}', at));
    };
    const launcher = rule('.support-launcher');
    expect(launcher).toContain(`right: ${LAUNCHER_RIGHT_PX}px`);
    expect(launcher).toContain(`width: ${LAUNCHER_SIZE_PX}px`);
    expect(launcher).toContain(`height: ${LAUNCHER_SIZE_PX}px`);

    const sliver = rule('.support-sliver');
    expect(sliver).toContain(`width: ${SLIVER_WIDTH_PX}px`);
    expect(sliver).toContain(`height: ${SLIVER_HEIGHT_PX}px`);
  });
});

describe('the bar-mode dock reports what it covers', () => {
  it('does not claim an empty overlap when something is under it', () => {
    // On a narrow viewport the dock becomes a full-width bottom bar, on the
    // stated grounds that a bar "pushes content rather than sitting on it,
    // which is the only arrangement that cannot cover something on a small
    // screen". That is true of page content and false of a fixed control:
    // measured at 400x1000, the bar occupied (0,928)-(400,1178) and the
    // support launcher (318,924)-(374,980), and the launcher's z-index of 1200
    // put it on top. The branch returned `overlapping: []` unconditionally —
    // a measurement that cannot fail, which is the shape this repository has
    // been bitten by before. Where the bar sits is a design question and is
    // not changed here; what it reports about itself is not.
    const viewport = { x: 0, y: 0, width: 400, height: 1000 };
    const launcher = launcherRect({ bottom: 20, docked: false }, viewport);

    const dock = dockFor({ viewport, avoid: [launcher] });

    expect(dock.mode).toBe('bar');
    expect(dock.overlapping).toContainEqual(launcher);
    expect(dock.reason).toMatch(/cover/i);
  });

  it('still reports an empty overlap when nothing is under it', () => {
    const viewport = { x: 0, y: 0, width: 400, height: 1000 };
    const dock = dockFor({ viewport, avoid: [{ x: 0, y: 0, width: 40, height: 40 }] });
    expect(dock.mode).toBe('bar');
    expect(dock.overlapping).toEqual([]);
  });
});

describe('the dock reserves the box that gets drawn', () => {
  it('honours the size the caller says it will render at', () => {
    const viewport = { x: 0, y: 0, width: 1440, height: 1000 };
    const size = { width: 268, height: 124 };
    const dock = dockFor({ viewport, size });
    expect(dock.rect.width).toBe(size.width);
    expect(dock.rect.height).toBe(size.height);
    // And it is inside the viewport, not hanging off the corner it anchored to.
    expect(dock.rect.x + dock.rect.width).toBeLessThanOrEqual(viewport.width);
    expect(dock.rect.y + dock.rect.height).toBeLessThanOrEqual(viewport.height);
  });

  it('checks collisions against that box, not an orb', () => {
    const viewport = { x: 0, y: 0, width: 1440, height: 1000 };
    // A rect that a 96x96 orb in the bottom-right corner clears and a
    // 268x124 panel does not. Reserving the smaller box is how `avoid` came
    // back empty for something the panel was sitting on.
    const wide = { x: 1100, y: 850, width: 200, height: 120 };
    expect(dockFor({ viewport, avoid: [wide] }).corner).toBe('bottom-right');
    expect(dockFor({ viewport, size: { width: 268, height: 124 }, avoid: [wide] }).corner).not.toBe('bottom-right');
  });
});

describe('the closed presence panel is wide enough to read', () => {
  it('renders at a width that holds a sentence, not a column of single words', async () => {
    reserveLane('support-launcher', launcherRect({ bottom: 20, docked: false }, VIEWPORT));
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <PresenceAnywhereMount />
      </MemoryRouter>,
    );
    const panel = await screen.findByRole('complementary', { name: /assistant/i });
    // Closed, the panel holds a 56px orb beside a status sentence and a
    // dismiss button, then an "Ask about this page" button under them. At the
    // dock's old 96px default that content box was 72px wide and the panel
    // measured 471px tall in Chromium — one word per line. Anything under the
    // orb plus a readable measure is that bug again.
    expect(parseFloat(panel.style.width)).toBeGreaterThanOrEqual(240);
  });
});

describe('the panel is placed by what it measures, not what it guessed', () => {
  it('stays inside the viewport once its real height is known', async () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <PresenceAnywhereMount />
      </MemoryRouter>,
    );
    const panel = await screen.findByRole('complementary', { name: /assistant/i });

    // jsdom reports every box as 0x0 and its ResizeObserver is a no-op, so
    // feed the component the height Chromium actually measured for the closed
    // panel on /dashboard, through the same path the browser uses.
    const MEASURED = 276;
    Object.defineProperty(panel, 'getBoundingClientRect', {
      value: () => ({ x: 0, y: 0, width: 268, height: MEASURED, top: 0, left: 0, right: 268, bottom: MEASURED }),
    });
    await act(async () => {
      for (const fire of observerCallbacks) fire();
    });

    const top = parseFloat(panel.style.top);
    // A panel anchored by a guessed 124px while 276px renders hangs 152px below
    // the fold, which is how it shipped. Whatever the anchor, the box has to
    // end inside the window.
    expect(top + MEASURED).toBeLessThanOrEqual(window.innerHeight);
  });
});
