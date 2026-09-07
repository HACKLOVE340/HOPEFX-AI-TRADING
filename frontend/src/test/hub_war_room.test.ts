/**
 * Phase H5 — §20's war room and §21's representation choice.
 *
 * Both are the same flow from two ends: somebody says something, and the
 * platform decides WHICH panels to open and in WHAT form.
 *
 * ## What "generated on demand" was missing
 *
 * `war_room` already exists as a LAYOUT: `readLayout('war room')` returns it
 * and `suggestLayout` picks it once eight surfaces are open. So saying "war
 * room" today rearranges whatever happens to be on the plane — and on an empty
 * plane it rearranges nothing and looks broken. §20 asks for one to be
 * generated, which means assembling the panels, not tidying the ones already
 * there.
 *
 * ## And it must not fabricate one
 *
 * The obvious implementation opens all eight known surfaces. On a deployment
 * with no news feed and a flat book that is six panels reading "nothing is
 * connected yet" — a war room that looks like a dead platform, which is worse
 * than not opening it. So the set is filtered by what actually has data, and
 * what was left out is reported rather than silently dropped.
 *
 * ## Representation is chosen from the data's shape, not from a model
 *
 * The staged note said "a model does not choose it yet", which framed the row
 * as waiting for a model call. It is not. A series is a chart, pairs are a
 * table, timestamped events are a timeline — decidable from what arrived,
 * instantly, deterministically, and while every vendor is unreachable. That is
 * the argument `intent.ts` already makes for resolving the obvious commands
 * locally, and it applies here with more force: the model is the fallback for
 * the ambiguous case, not the mechanism.
 */

import { describe, expect, it } from 'vitest';

import { representationFor, describeChoice } from '../hub/representation';
import { warRoomSurfaces, WAR_ROOM_CANDIDATES } from '../hub/warRoom';
import type { SurfaceData } from '../hub/surfaceData';

const empty: SurfaceData = { empty: true, note: 'nothing yet' };

describe('§21 the representation follows the shape of what arrived', () => {
  it('draws a numeric series as a chart', () => {
    expect(representationFor({ empty: false, points: [1, 2, 3, 4, 5] })).toBe('chart');
  });

  it('draws pairs as a table', () => {
    expect(representationFor({ empty: false, rows: [['a', '1'], ['b', '2']] })).toBe('table');
  });

  it('draws timestamped events as a timeline', () => {
    expect(
      representationFor({
        empty: false,
        events: [{ at: 1, label: 'x', category: 'news' }],
      }),
    ).toBe('timeline');
  });

  it('draws nodes and edges as a network', () => {
    expect(
      representationFor({
        empty: false,
        nodes: [{ id: 'a', label: 'A', category: 'x' }],
        edges: [{ from: 'a', to: 'a', because: 'it references itself' }],
      }),
    ).toBe('network');
  });

  it('draws a row-and-column grid of intensities as a heatmap', () => {
    expect(
      representationFor({
        empty: false,
        cells: [{ row: 'Mon', column: 'AM', intensity: 0.5, label: '0.5' }],
      }),
    ).toBe('heatmap');
  });

  it('prefers the richer form when two shapes are present', () => {
    // Cells AND rows is a heatmap with its accessible twin, not a table that
    // happens to carry cells. Picking the weaker one would throw away the
    // structure the sender took the trouble to send.
    const both: SurfaceData = {
      empty: false,
      rows: [['a', '1']],
      cells: [{ row: 'Mon', column: 'AM', intensity: 0.5, label: '0.5' }],
    };
    expect(representationFor(both)).toBe('heatmap');
  });

  it('refuses to choose for a series of one point', () => {
    // A line drawn between one point is a dot, and a chart of it is a shape
    // rather than a trend — `surfaceData` already refuses this for gold and
    // the chooser must not undo that refusal.
    expect(representationFor({ empty: false, points: [42] })).toBeNull();
  });

  it('returns null for an empty surface rather than guessing', () => {
    expect(representationFor(empty)).toBeNull();
    expect(representationFor({ empty: false })).toBeNull();
  });

  it('says why it chose, in words, for every choice it makes', () => {
    const said = describeChoice({ empty: false, points: [1, 2, 3] });
    expect(said).toMatch(/chart/);
    expect(said).toMatch(/3/);
    // A refusal explains itself too. "I could not tell" with no reason is what
    // makes an assistant look broken rather than careful.
    expect(describeChoice(empty)).toMatch(/nothing|empty|no data/i);
  });

  it('never invents a kind the workspace cannot open', async () => {
    const { SURFACE_KINDS } = await import('../hub/contracts.shared');
    const shapes: SurfaceData[] = [
      { empty: false, points: [1, 2, 3] },
      { empty: false, rows: [['a', 'b']] },
      { empty: false, items: ['x'] },
      { empty: false, body: 'text' },
      { empty: false, values: [1, 2] },
      { empty: false, events: [{ at: 1, label: 'x', category: 'c' }] },
      { empty: false, nodes: [{ id: 'a', label: 'A', category: 'x' }], edges: [] },
      { empty: false, cells: [{ row: 'r', column: 'c', intensity: 0.1, label: 'l' }] },
    ];
    for (const shape of shapes) {
      const chosen = representationFor(shape);
      if (chosen !== null) expect(SURFACE_KINDS).toContain(chosen);
    }
  });
});

describe('§20 a war room is assembled, not rearranged', () => {
  it('names the candidates rather than deciding them at the call site', () => {
    expect(WAR_ROOM_CANDIDATES.length).toBeGreaterThanOrEqual(6);
    for (const candidate of WAR_ROOM_CANDIDATES) {
      expect(candidate.key).toBeTruthy();
      expect(candidate.intent).toBeTruthy();
    }
  });

  it('opens only the panels that actually have something in them', () => {
    // A war room of six "nothing is connected yet" panels looks like a dead
    // platform. Worse than not opening it.
    const has = new Set(['gold-chart', 'positions', 'risk']);
    const built = warRoomSurfaces((key) => has.has(key));
    expect(built.surfaces.map((s) => s.key).sort()).toEqual(['gold-chart', 'positions', 'risk']);
  });

  it('reports what it left out and why, rather than dropping it silently', () => {
    const built = warRoomSurfaces((key) => key === 'risk');
    expect(built.omitted.length).toBeGreaterThan(0);
    expect(built.reason).toMatch(/no data|nothing/i);
    // Every omission is nameable, so an operator can ask about a panel they
    // expected and get an answer instead of a shrug.
    for (const key of built.omitted) {
      expect(WAR_ROOM_CANDIDATES.map((c) => c.key)).toContain(key);
    }
  });

  it('says so plainly when nothing has any data at all', () => {
    const built = warRoomSurfaces(() => false);
    expect(built.surfaces).toEqual([]);
    expect(built.reason).toMatch(/nothing|no feed|no data/i);
    // Not an exception and not an empty success. An operator who asked for a
    // war room and got a blank plane needs to be told the feeds are silent.
    expect(built.omitted.length).toBe(WAR_ROOM_CANDIDATES.length);
  });

  it('puts the risk panel at a tier that cannot be collapsed away', () => {
    // `layout.ts` folds `background` and `on_demand` into the stack once the
    // plane is crowded, and a war room is crowded by definition. Risk
    // disappearing into a chip at exactly the moment somebody opened a war
    // room is the one collapse that must not happen.
    const risk = WAR_ROOM_CANDIDATES.find((c) => c.key === 'risk');
    expect(risk).toBeDefined();
    expect(risk!.priority).toBe('critical');
  });

  it('never asks for a surface kind the workspace does not know', async () => {
    const { SURFACE_KINDS } = await import('../hub/contracts.shared');
    for (const candidate of WAR_ROOM_CANDIDATES) {
      expect(SURFACE_KINDS).toContain(candidate.kind);
    }
  });
});
