/**
 * Phase I2 — §10's multi-display console.
 *
 * I staged this row saying it needed "a second physical screen this deployment
 * does not have". The Window Management API — `getScreenDetails`,
 * `screen.isExtended` — is a browser API, and the code plus its honest
 * degradation are buildable without owning a monitor. Being unable to *verify*
 * placement on real hardware is a reason to say so, not a reason to call the
 * work blocked.
 *
 * ## Every failure mode here is a reporting problem
 *
 * The API is permission-gated and Chromium-only, so on most browsers it is
 * simply absent. Three states that look alike and are not:
 *
 *   not supported   this browser has no Window Management API
 *   not permitted   it has one and the operator has not granted it
 *   one screen      it answered, and there is genuinely one display
 *
 * Collapsing those into "no extra screens" is §22's defect in a new place: an
 * unmeasured display count is absent, never zero. An operator on a three-screen
 * desk being told they have one screen would go looking for a bug in their
 * hardware.
 *
 * ## Permission is never requested by rendering
 *
 * `getScreenDetails()` prompts. Calling it because a component mounted makes
 * *opening the app* the request, which is the same mistake the camera panel
 * made before §25 — a prompt nobody asked for is one people learn to dismiss.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import {
  DISPLAY_STATES,
  assignSurfacesToScreens,
  describeDisplays,
  readDisplays,
  type DisplaySnapshot,
} from '../hub/displays';

function screen(id: string, width: number, height: number, primary = false) {
  return { label: id, left: 0, top: 0, width, height, isPrimary: primary, isInternal: primary };
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('§10 reading the displays, honestly', () => {
  it('names the three states rather than one boolean', () => {
    expect([...DISPLAY_STATES]).toEqual(['unsupported', 'unpermitted', 'measured']);
  });

  it('reports unsupported when the browser has no such API', async () => {
    vi.stubGlobal('window', { screen: {} });
    const snapshot = await readDisplays();
    expect(snapshot.state).toBe('unsupported');
    // Not zero and not one. An unmeasured count is absent — §22's rule, and the
    // difference between "your browser cannot tell me" and "you have one
    // screen", which are different things for an operator to act on.
    expect(snapshot.screens).toEqual([]);
    expect(snapshot.count).toBeNull();
    expect(snapshot.reason).toMatch(/browser|support/i);
  });

  it('reports unpermitted when the operator has not granted it', async () => {
    vi.stubGlobal('window', {
      screen: { isExtended: true },
      getScreenDetails: () => Promise.reject(new DOMException('denied', 'NotAllowedError')),
    });
    const snapshot = await readDisplays();
    expect(snapshot.state).toBe('unpermitted');
    expect(snapshot.count).toBeNull();
    expect(snapshot.reason).toMatch(/permission|not been granted|denied/i);
  });

  it('reports what it measured when the operator has granted it', async () => {
    vi.stubGlobal('window', {
      screen: { isExtended: true },
      getScreenDetails: () =>
        Promise.resolve({ screens: [screen('built-in', 1512, 982, true), screen('desk', 2560, 1440)] }),
    });
    const snapshot = await readDisplays();
    expect(snapshot.state).toBe('measured');
    expect(snapshot.count).toBe(2);
    expect(snapshot.screens.map((s) => s.label)).toEqual(['built-in', 'desk']);
    expect(snapshot.reason).toBe('');
  });

  it('measures one screen as one, not as unsupported', async () => {
    // A real answer that happens to be small. Folding it into the "cannot
    // tell" bucket would throw away the one case where the app knows.
    vi.stubGlobal('window', {
      screen: { isExtended: false },
      getScreenDetails: () => Promise.resolve({ screens: [screen('built-in', 1512, 982, true)] }),
    });
    const snapshot = await readDisplays();
    expect(snapshot.state).toBe('measured');
    expect(snapshot.count).toBe(1);
  });

  it('never asks for permission by being called with probe:true', async () => {
    // The rule §25 exists for: a prompt nobody asked for is one people learn
    // to dismiss, and then the real request is dismissed too.
    const getScreenDetails = vi.fn();
    vi.stubGlobal('window', { screen: { isExtended: true }, getScreenDetails });
    const snapshot = await readDisplays({ probe: true });
    expect(getScreenDetails).not.toHaveBeenCalled();
    expect(snapshot.state).toBe('unpermitted');
    expect(snapshot.reason).toMatch(/ask|request|grant/i);
  });

  it('treats a malformed answer as unmeasured rather than trusting it', async () => {
    vi.stubGlobal('window', {
      screen: { isExtended: true },
      getScreenDetails: () => Promise.resolve({ screens: 'not an array' }),
    });
    const snapshot = await readDisplays();
    expect(snapshot.state).toBe('unsupported');
    expect(snapshot.count).toBeNull();
  });

  it('drops a screen with no area rather than placing panels on it', async () => {
    vi.stubGlobal('window', {
      screen: { isExtended: true },
      getScreenDetails: () =>
        Promise.resolve({ screens: [screen('real', 1512, 982, true), screen('ghost', 0, 0)] }),
    });
    const snapshot = await readDisplays();
    expect(snapshot.count).toBe(1);
    expect(snapshot.screens.map((s) => s.label)).toEqual(['real']);
  });
});

describe('§10 saying it in words', () => {
  it('says which of the three states it is in, every time', async () => {
    for (const state of DISPLAY_STATES) {
      const snapshot: DisplaySnapshot = { state, screens: [], count: null, reason: 'because' };
      const said = describeDisplays(snapshot);
      expect(said.length).toBeGreaterThan(0);
      expect(said).not.toMatch(/undefined|null/);
    }
  });

  it('does not claim one screen when it could not tell', () => {
    const said = describeDisplays({ state: 'unsupported', screens: [], count: null, reason: 'no API' });
    expect(said).not.toMatch(/\bone screen\b/i);
    expect(said).toMatch(/cannot|could not|unable/i);
  });
});

describe('§10 spreading the plane across what is really there', () => {
  const surfaces = [
    { id: 'risk', priority: 'critical' as const },
    { id: 'chart', priority: 'primary' as const },
    { id: 'news', priority: 'secondary' as const },
    { id: 'spend', priority: 'background' as const },
  ];

  it('puts everything on one screen when there is one', () => {
    const plan = assignSurfacesToScreens(surfaces, {
      state: 'measured',
      screens: [screen('built-in', 1512, 982, true)],
      count: 1,
      reason: '',
    });
    expect(new Set(Object.values(plan.byScreen).flat())).toEqual(new Set(['risk', 'chart', 'news', 'spend']));
    expect(Object.keys(plan.byScreen)).toEqual(['built-in']);
    expect(plan.spread).toBe(false);
  });

  it('puts everything on one screen when it could not tell how many there are', () => {
    // The important degradation. An unmeasured display count must produce
    // exactly today's behaviour, not a guess at a second monitor.
    const plan = assignSurfacesToScreens(surfaces, {
      state: 'unsupported',
      screens: [],
      count: null,
      reason: 'no API',
    });
    expect(plan.spread).toBe(false);
    expect(plan.byScreen).toEqual({ '': ['risk', 'chart', 'news', 'spend'] });
    expect(plan.reason).toMatch(/could not|cannot|one/i);
  });

  it('keeps the critical surface on the primary screen', () => {
    // Risk does not go to the monitor somebody is not looking at. This is the
    // same reasoning that made risk `critical` in the war room so the crowded
    // plane could not collapse it away.
    const plan = assignSurfacesToScreens(surfaces, {
      state: 'measured',
      screens: [screen('built-in', 1512, 982, true), screen('desk', 2560, 1440)],
      count: 2,
      reason: '',
    });
    expect(plan.spread).toBe(true);
    expect(plan.byScreen['built-in']).toContain('risk');
  });

  it('uses the second screen rather than leaving it empty', () => {
    const plan = assignSurfacesToScreens(surfaces, {
      state: 'measured',
      screens: [screen('built-in', 1512, 982, true), screen('desk', 2560, 1440)],
      count: 2,
      reason: '',
    });
    expect(plan.byScreen['desk']?.length).toBeGreaterThan(0);
    // And nothing is lost or duplicated in the split.
    const placed = Object.values(plan.byScreen).flat();
    expect(placed.sort()).toEqual(['chart', 'news', 'risk', 'spend']);
  });

  it('places nothing at all when there are no surfaces', () => {
    const plan = assignSurfacesToScreens([], {
      state: 'measured',
      screens: [screen('built-in', 1512, 982, true)],
      count: 1,
      reason: '',
    });
    expect(Object.values(plan.byScreen).flat()).toEqual([]);
  });
});
