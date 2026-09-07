/**
 * Phase H1 — §9's scene model and semantic panel registry, given a producer.
 *
 * Both rows were staged with the same note: the model exists and nothing
 * populates it. `sceneGraph.ts` was built in Phase D1 and, measured now, is
 * constructed in exactly zero production files — `gestures.ts` imports the
 * *type*. A scene graph nothing places panels into answers every question with
 * a throw, which is `hopefx-dead-controls` with a spatial API.
 *
 * `PresenceStage` already reads every panel's `getBoundingClientRect()` once a
 * frame and throws the rectangle away, keeping only the ninth-of-the-screen
 * phrase. `sceneFrom` is the missing half: the same measurement, kept.
 *
 * `resolveReference` is the consumer. `referencesIn` matches a phrase against
 * what a panel MEANS, which cannot answer "the one on the left" — most of how
 * people actually refer to things on a screen is relative, and relative needs
 * the scene.
 */

import { describe, expect, it } from 'vitest';

import { SceneGraph } from '../hub/sceneGraph';
import { sceneFrom, type Measurement } from '../hub/sceneFrom';
import { resolveReference } from '../hub/resolveReference';
import type { Surface } from '../hub/workspace';

function surface(id: string, meaning: string, kind: Surface['kind'] = 'chart'): Surface {
  return {
    id,
    kind,
    meaning,
    priority: 'primary',
    span: 4,
    data: {},
    pinned: false,
    key: id,
    openedAt: 1_700_000_000_000,
    order: 0,
  };
}

/** Three panels in a row: gold on the left, dollar centre, risk on the right. */
function row(): { scene: SceneGraph; surfaces: Surface[] } {
  const measurements: Measurement[] = [
    { id: 'gold', rect: { x: 0, y: 0, width: 300, height: 200 } },
    { id: 'dollar', rect: { x: 320, y: 0, width: 300, height: 200 } },
    { id: 'risk', rect: { x: 640, y: 0, width: 300, height: 200 } },
  ];
  return {
    scene: sceneFrom(measurements),
    surfaces: [surface('gold', 'Gold price'), surface('dollar', 'Dollar index'), surface('risk', 'Risk headroom')],
  };
}

describe('§9 sceneFrom — a producer for the scene model', () => {
  it('places every measured panel', () => {
    const { scene } = row();
    expect(scene.ids().sort()).toEqual(['dollar', 'gold', 'risk']);
    expect(scene.rectOf('gold')).toEqual({ x: 0, y: 0, width: 300, height: 200 });
  });

  it('gives z from paint order, so occlusion is answerable at all', () => {
    // Every node at z 0 makes `occludedBy` return nothing for every pair,
    // whatever they overlap — which reads as "nothing is covered" rather than
    // as "z was never populated".
    const scene = sceneFrom([
      { id: 'under', rect: { x: 0, y: 0, width: 200, height: 200 } },
      { id: 'over', rect: { x: 50, y: 50, width: 200, height: 200 } },
    ]);
    expect(scene.zOf('over')).toBeGreaterThan(scene.zOf('under'));
    expect(scene.occludedBy('under')).toEqual(['over']);
    expect(scene.occludedBy('over')).toEqual([]);
  });

  it('drops a rectangle that was never laid out rather than placing it at the origin', () => {
    // `getBoundingClientRect` on an unlaid-out element is all zeros. Placing
    // that puts a panel in the top-left corner of the scene, and then "the
    // panel on the far left" is a panel that is not on screen.
    const scene = sceneFrom([
      { id: 'real', rect: { x: 10, y: 10, width: 100, height: 100 } },
      { id: 'unlaid', rect: { x: 0, y: 0, width: 0, height: 0 } },
    ]);
    expect(scene.ids()).toEqual(['real']);
    expect(() => scene.rectOf('unlaid')).toThrow(/unlaid/);
  });

  it('invents no containment', () => {
    // A grid panel never contains another, and a scene that guessed parents
    // from overlap would report "inside" for two panels that merely overlap
    // during a transition.
    const { scene } = row();
    for (const id of scene.ids()) expect(scene.parentOf(id)).toBeNull();
  });

  it('accepts declared containment, and refuses a parent that was not measured', () => {
    const scene = sceneFrom(
      [
        { id: 'war-room', rect: { x: 0, y: 0, width: 900, height: 400 } },
        { id: 'gold', rect: { x: 10, y: 10, width: 300, height: 200 }, parent: 'war-room' },
      ],
    );
    expect(scene.ancestry('gold')).toEqual(['war-room', 'gold']);
    expect(() => sceneFrom([{ id: 'orphan', rect: { x: 0, y: 0, width: 10, height: 10 }, parent: 'ghost' }])).toThrow(
      /ghost/,
    );
  });

  it('answers what is next to what, which is the point of having one', () => {
    const { scene } = row();
    expect(scene.neighbour('dollar', 'left')).toBe('gold');
    expect(scene.neighbour('dollar', 'right')).toBe('risk');
    expect(scene.neighbour('gold', 'left')).toBeNull();
  });
});

describe('§9 resolveReference — meaning first, then the scene', () => {
  it('resolves a phrase that names one panel', () => {
    const { scene, surfaces } = row();
    const found = resolveReference('zoom into the gold price', surfaces, scene);
    expect(found.resolved).toBe(true);
    if (found.resolved) {
      expect(found.id).toBe('gold');
      expect(found.how).toMatch(/mean|name/i);
    }
  });

  it('refuses an ambiguous phrase and names the candidates', () => {
    // A trading screen is the wrong place to guess. `recogniseGesture` returns
    // null rather than the nearest gesture for the same reason: acting on the
    // wrong panel is worse than asking.
    const scene = sceneFrom([
      { id: 'a', rect: { x: 0, y: 0, width: 100, height: 100 } },
      { id: 'b', rect: { x: 200, y: 0, width: 100, height: 100 } },
    ]);
    const surfaces = [surface('a', 'Gold price'), surface('b', 'Gold exposure')];
    const found = resolveReference('the gold one', surfaces, scene);
    expect(found.resolved).toBe(false);
    if (!found.resolved) {
      expect([...found.candidates].sort()).toEqual(['a', 'b']);
      expect(found.why).toMatch(/two|more than one|ambiguous/i);
    }
  });

  it('resolves a relative phrase against a named anchor', () => {
    const { scene, surfaces } = row();
    const found = resolveReference('the panel to the left of the dollar index', surfaces, scene);
    expect(found.resolved).toBe(true);
    if (found.resolved) {
      expect(found.id).toBe('gold');
      expect(found.how).toContain('left');
    }
  });

  it('resolves a relative phrase against the focused panel when none is named', () => {
    const { scene, surfaces } = row();
    const found = resolveReference('the one on the right', surfaces, scene, { focusedId: 'dollar' });
    expect(found.resolved).toBe(true);
    if (found.resolved) expect(found.id).toBe('risk');
  });

  it('refuses a relative phrase with nothing to be relative to', () => {
    const { scene, surfaces } = row();
    const found = resolveReference('the one on the right', surfaces, scene);
    expect(found.resolved).toBe(false);
    if (!found.resolved) expect(found.why).toMatch(/relative|anchor|which panel/i);
  });

  it('says so when there is nothing in that direction, rather than wrapping round', () => {
    const { scene, surfaces } = row();
    const found = resolveReference('the one on the left', surfaces, scene, { focusedId: 'gold' });
    expect(found.resolved).toBe(false);
    if (!found.resolved) {
      expect(found.why).toMatch(/nothing/i);
      expect(found.candidates).toEqual([]);
    }
  });

  it('answers "the panel behind that one" from z, not from order', () => {
    const scene = sceneFrom([
      { id: 'under', rect: { x: 0, y: 0, width: 200, height: 200 } },
      { id: 'over', rect: { x: 50, y: 50, width: 200, height: 200 } },
    ]);
    const surfaces = [surface('under', 'Session heatmap'), surface('over', 'Order ticket')];
    const found = resolveReference('what is in front of the session heatmap', surfaces, scene);
    expect(found.resolved).toBe(true);
    if (found.resolved) expect(found.id).toBe('over');
  });

  it('refuses a panel the scene has never heard of instead of throwing at the caller', () => {
    // `SceneGraph` throws on an unknown id by design. A phrase naming a surface
    // that closed between the measurement and the sentence is normal, not
    // exceptional, so this boundary turns it into a refusal.
    const { scene } = row();
    const surfaces = [surface('ghost', 'Ghost panel')];
    const found = resolveReference('the ghost panel', surfaces, scene);
    expect(found.resolved).toBe(false);
    if (!found.resolved) expect(found.why).toMatch(/no longer on the plane|not measured|not on screen/i);
  });

  it('refuses an empty phrase without searching', () => {
    const { scene, surfaces } = row();
    const found = resolveReference('   ', surfaces, scene);
    expect(found.resolved).toBe(false);
  });
});
