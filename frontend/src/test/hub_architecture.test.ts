/**
 * §23's architecture layer: what to render, where, how much of it, and at what
 * fidelity — decided before anything is drawn.
 *
 * ## Nothing here renders, and that is the point
 *
 * These are pure functions and small classes, like the rest of `hub/`. The
 * layout engine assigns a span; the renderer decides what a span looks like.
 * Keeping the decisions testable without a browser is what makes rules like
 * "never render zero" assertable at all.
 *
 * ## §22's rule, carried into the browser
 *
 * The telemetry phase established that an unmeasured metric is absent, never
 * zero. Two of the modules below are where that rule bites hardest on screen:
 *
 * - **An unknown viewport must never render zero items.** A virtualiser that
 *   computes a window from a height it does not have produces an empty screen —
 *   and an empty screen is indistinguishable from "there is nothing to show".
 * - **An unmeasured load must not be read as an idle machine.** Full fidelity
 *   because the probe failed is the 0% CPU gauge deciding to start more work.
 *   The honest move is to hold whatever fidelity is current and say the input
 *   was missing.
 *
 * ## A restored session names what it could not restore
 *
 * A saved workspace referring to a surface kind the build no longer has must
 * not quietly come back one panel short. The operator saved four things.
 */

import { describe, it, expect } from 'vitest';

// ── the scene graph ───────────────────────────────────────────────────────────

import { SceneGraph } from '../hub/sceneGraph';

const RECT = (x: number, y: number, w = 100, h = 100) => ({ x, y, width: w, height: h });

describe('scene graph', () => {
  it('answers what is next to what, which is how the AI says "the panel on the left"', () => {
    const graph = new SceneGraph();
    graph.place('chart', RECT(0, 0));
    graph.place('news', RECT(200, 0));
    graph.place('table', RECT(0, 200));

    expect(graph.neighbour('news', 'left')).toBe('chart');
    expect(graph.neighbour('chart', 'right')).toBe('news');
    expect(graph.neighbour('chart', 'below')).toBe('table');
    expect(graph.neighbour('chart', 'above')).toBeNull();
  });

  it('returns null rather than the nearest thing in the wrong direction', () => {
    const graph = new SceneGraph();
    graph.place('chart', RECT(0, 0));
    graph.place('news', RECT(200, 0));
    expect(graph.neighbour('news', 'right')).toBeNull();
  });

  it('picks the closest neighbour, not an arbitrary one', () => {
    const graph = new SceneGraph();
    graph.place('chart', RECT(0, 0));
    graph.place('near', RECT(150, 0));
    graph.place('far', RECT(600, 0));
    expect(graph.neighbour('chart', 'right')).toBe('near');
  });

  it('knows containment, so "inside the war room" resolves', () => {
    const graph = new SceneGraph();
    graph.place('room', RECT(0, 0, 400, 400));
    graph.place('chart', RECT(10, 10, 50, 50), { parent: 'room' });

    expect(graph.childrenOf('room')).toEqual(['chart']);
    expect(graph.parentOf('chart')).toBe('room');
    expect(graph.ancestry('chart')).toEqual(['room', 'chart']);
  });

  it('refuses a parent that does not exist rather than orphaning silently', () => {
    const graph = new SceneGraph();
    expect(() => graph.place('chart', RECT(0, 0), { parent: 'nowhere' })).toThrow();
  });

  it('refuses a containment cycle at the moment the edge is made', () => {
    const graph = new SceneGraph();
    graph.place('a', RECT(0, 0));
    graph.place('b', RECT(0, 0), { parent: 'a' });
    expect(() => graph.reparent('a', 'b')).toThrow();
  });

  it('reports occlusion by z-order, so "the panel behind it" is answerable', () => {
    const graph = new SceneGraph();
    graph.place('back', RECT(0, 0, 100, 100), { z: 0 });
    graph.place('front', RECT(50, 50, 100, 100), { z: 1 });

    expect(graph.occludedBy('back')).toEqual(['front']);
    expect(graph.occludedBy('front')).toEqual([]);
  });

  it('does not call two panels that merely touch an occlusion', () => {
    const graph = new SceneGraph();
    graph.place('a', RECT(0, 0, 100, 100), { z: 0 });
    graph.place('b', RECT(100, 0, 100, 100), { z: 1 });
    expect(graph.occludedBy('a')).toEqual([]);
  });

  it('reports an unknown id as unknown rather than as empty', () => {
    const graph = new SceneGraph();
    expect(() => graph.neighbour('ghost', 'left')).toThrow(/ghost/);
  });

  it('forgets a removed panel and everything it contained', () => {
    const graph = new SceneGraph();
    graph.place('room', RECT(0, 0, 400, 400));
    graph.place('chart', RECT(10, 10), { parent: 'room' });
    graph.remove('room');
    expect(graph.ids()).toEqual([]);
  });
});

// ── virtualisation ────────────────────────────────────────────────────────────

import { windowFor } from '../hub/virtualization';

describe('virtualisation', () => {
  it('renders only what the viewport can show, plus overscan', () => {
    const win = windowFor({ count: 1000, itemHeight: 20, viewportHeight: 200, scrollTop: 0, overscan: 2 });
    expect(win.start).toBe(0);
    expect(win.end).toBe(12);
    expect(win.measured).toBe(true);
  });

  it('moves the window as the list scrolls', () => {
    const win = windowFor({ count: 1000, itemHeight: 20, viewportHeight: 200, scrollTop: 400, overscan: 2 });
    expect(win.start).toBe(18);
    expect(win.end).toBe(32);
  });

  it('never renders zero when the viewport height is unknown', () => {
    // A window computed from a height nobody measured is an empty screen, and
    // an empty screen reads as "there is nothing to show".
    const win = windowFor({ count: 50, itemHeight: 20, viewportHeight: 0, scrollTop: 0 });
    expect(win.measured).toBe(false);
    expect(win.end).toBeGreaterThan(win.start);
    expect(win.reason).toMatch(/viewport/i);
  });

  it('falls back to a stated number of items rather than to all of them', () => {
    const win = windowFor({ count: 100000, itemHeight: 20, viewportHeight: 0, scrollTop: 0 });
    expect(win.end - win.start).toBeLessThanOrEqual(50);
  });

  it('shows everything when the list is smaller than the window', () => {
    const win = windowFor({ count: 3, itemHeight: 20, viewportHeight: 800, scrollTop: 0 });
    expect(win.start).toBe(0);
    expect(win.end).toBe(3);
  });

  it('reports an empty list as genuinely empty, not as unmeasured', () => {
    const win = windowFor({ count: 0, itemHeight: 20, viewportHeight: 200, scrollTop: 0 });
    expect(win.start).toBe(0);
    expect(win.end).toBe(0);
    expect(win.measured).toBe(true);
    expect(win.reason).toBe('');
  });

  it('clamps a scroll position past the end instead of returning a negative window', () => {
    const win = windowFor({ count: 10, itemHeight: 20, viewportHeight: 200, scrollTop: 99999 });
    expect(win.start).toBeGreaterThanOrEqual(0);
    expect(win.end).toBeLessThanOrEqual(10);
    expect(win.end).toBeGreaterThan(win.start);
  });

  it('refuses a zero item height rather than dividing by it', () => {
    const win = windowFor({ count: 10, itemHeight: 0, viewportHeight: 200, scrollTop: 0 });
    expect(win.measured).toBe(false);
    expect(win.reason).toMatch(/item height/i);
  });
});

// ── the frame budget ──────────────────────────────────────────────────────────

import { FIDELITIES, nextFidelity } from '../hub/frameBudget';

describe('frame budget', () => {
  it('holds full fidelity on an idle machine', () => {
    const step = nextFidelity({ current: 'full', cpu: 10, frameMs: 12 });
    expect(step.fidelity).toBe('full');
    expect(step.changed).toBe(false);
  });

  it('degrades one step at a time rather than collapsing to the floor', () => {
    // A jump straight to `minimal` on one slow frame is a visible lurch, and
    // the next measurement would send it straight back.
    const step = nextFidelity({ current: 'full', cpu: 95, frameMs: 60 });
    expect(step.fidelity).toBe('reduced');
    expect(FIDELITIES.indexOf(step.fidelity)).toBe(FIDELITIES.indexOf('full') + 1);
  });

  it('recovers one step at a time too', () => {
    const step = nextFidelity({ current: 'minimal', cpu: 5, frameMs: 8 });
    expect(step.fidelity).toBe('reduced');
  });

  it('holds current fidelity when the load could not be measured', () => {
    // Full fidelity because the probe failed is the 0% CPU gauge deciding to
    // start more work. Neither guess is safe, so it holds and says why.
    const step = nextFidelity({ current: 'reduced', cpu: null, frameMs: null });
    expect(step.fidelity).toBe('reduced');
    expect(step.changed).toBe(false);
    expect(step.reason).toMatch(/unmeasured|not measured/i);
  });

  it('acts on a measured frame time even when cpu is unmeasured', () => {
    const step = nextFidelity({ current: 'full', cpu: null, frameMs: 90 });
    expect(step.fidelity).toBe('reduced');
    expect(step.reason).toMatch(/frame/i);
  });

  it('never degrades below the floor', () => {
    const step = nextFidelity({ current: 'minimal', cpu: 99, frameMs: 200 });
    expect(step.fidelity).toBe('minimal');
    expect(step.changed).toBe(false);
  });

  it('never climbs above full', () => {
    const step = nextFidelity({ current: 'full', cpu: 1, frameMs: 4 });
    expect(step.fidelity).toBe('full');
  });

  it('always states a reason, so a degraded screen is explainable', () => {
    for (const current of FIDELITIES) {
      for (const cpu of [null, 5, 95]) {
        const step = nextFidelity({ current, cpu, frameMs: null });
        expect(step.reason.length).toBeGreaterThan(0);
      }
    }
  });

  it('honours reduced motion as a floor rather than as a preference to weigh', () => {
    const step = nextFidelity({ current: 'full', cpu: 5, frameMs: 8, reducedMotion: true });
    expect(step.fidelity).toBe('reduced');
    expect(step.reason).toMatch(/reduced motion/i);
  });
});

// ── the workspace store ───────────────────────────────────────────────────────

import { SCHEMA_VERSION, restore, save } from '../hub/workspaceStore';

const SESSION = {
  surfaces: [
    { id: 's1', kind: 'chart' as const, intent: 'gold this session', priority: 'primary' as const, span: 6 },
    { id: 's2', kind: 'news' as const, intent: 'headlines', priority: 'secondary' as const, span: 3 },
  ],
  focus: 's1',
  layout: 'compare',
};

describe('workspace store', () => {
  it('round-trips a session', () => {
    const restored = restore(save(SESSION));
    expect(restored.ok).toBe(true);
    expect(restored.session?.surfaces.map((s) => s.id)).toEqual(['s1', 's2']);
    expect(restored.session?.focus).toBe('s1');
  });

  it('stamps the schema version it was written with', () => {
    expect(save(SESSION).version).toBe(SCHEMA_VERSION);
  });

  it('refuses a version it does not understand rather than coercing it', () => {
    const restored = restore({ ...save(SESSION), version: SCHEMA_VERSION + 99 });
    expect(restored.ok).toBe(false);
    expect(restored.reason).toMatch(/version/i);
    expect(restored.session).toBeNull();
  });

  it('names a surface kind this build no longer has instead of dropping it', () => {
    // The operator saved four things. Coming back with three and no explanation
    // is the workspace quietly losing their work.
    const blob = save(SESSION);
    const tampered = {
      ...blob,
      surfaces: [...blob.surfaces, { id: 's3', kind: 'hologram', intent: 'gone', priority: 'primary', span: 3 }],
    };
    const restored = restore(tampered);

    expect(restored.ok).toBe(true);
    expect(restored.session?.surfaces.map((s) => s.id)).toEqual(['s1', 's2']);
    expect(restored.dropped).toEqual([{ id: 's3', reason: 'unknown surface kind: hologram' }]);
  });

  it('drops a focus that points at a surface that did not survive', () => {
    const blob = { ...save(SESSION), focus: 'gone' };
    const restored = restore(blob);
    expect(restored.session?.focus).toBeNull();
    expect(restored.dropped.some((d) => d.id === 'gone')).toBe(true);
  });

  it('refuses a blob that is not a session at all', () => {
    for (const bad of [null, undefined, 42, 'text', {}, { version: SCHEMA_VERSION }]) {
      const restored = restore(bad as never);
      expect(restored.ok).toBe(false);
      expect(restored.reason.length).toBeGreaterThan(0);
    }
  });

  it('survives a corrupt surface entry without losing the others', () => {
    const blob = save(SESSION);
    const tampered = { ...blob, surfaces: [...blob.surfaces, { id: 's4' }] };
    const restored = restore(tampered);
    expect(restored.session?.surfaces).toHaveLength(2);
    expect(restored.dropped.some((d) => d.id === 's4')).toBe(true);
  });

  it('is serialisable, because a session that cannot be stored is not a session', () => {
    const blob = save(SESSION);
    expect(() => JSON.parse(JSON.stringify(blob))).not.toThrow();
    expect(restore(JSON.parse(JSON.stringify(blob))).ok).toBe(true);
  });
});
