/**
 * §7's last three: multiple projections, contextual transformation, and the
 * renderer abstraction.
 *
 * The rule that matters here is about honesty rather than about drawing: the
 * abstraction must not let a deployment believe it is rendering in VR when
 * there is no VR backend. That is the same class of defect as a ring drawn for
 * an unmeasured number, and it would be absurd to commit it in the module
 * implementing the capability registry's own §7 rows.
 *
 * Fails on the pre-fix tree — `hub/projection.ts` does not exist there.
 */

import { describe, expect, it } from 'vitest';

import {
  RENDERERS,
  availableRenderers,
  minimiseProjections,
  readProjection,
  representationFor,
  repositionProjections,
  selectRenderer,
  singleProjection,
  splitProjection,
} from '../hub/projection';
import { Workspace, type Surface } from '../hub/workspace';

function surfaces(...kinds: string[]): readonly Surface[] {
  const ws = new Workspace();
  kinds.forEach((kind, i) =>
    ws.open({ kind: kind as Surface['kind'], intent: `S${i}`, priority: 'primary', key: `s${i}` }),
  );
  return ws.surfaces;
}

describe('splitting the presence', () => {
  it('gives one projection per subject', () => {
    const split = splitProjection(surfaces('chart', 'table'));
    expect(split).toHaveLength(2);
    expect(new Set(split.map((p) => p.subjectId)).size).toBe(2);
  });

  it('caps at three', () => {
    // A plane with six talking heads is a worse screen than one with a single
    // presence that turns, and the operator cannot follow which is speaking.
    expect(splitProjection(surfaces('chart', 'table', 'news', 'terminal', 'map'))).toHaveLength(3);
  });

  it('is a single presence when there is only one thing to attend to', () => {
    expect(splitProjection(surfaces('chart'))).toHaveLength(1);
    expect(splitProjection([])).toHaveLength(1);
  });

  it('puts them in different places', () => {
    const split = splitProjection(surfaces('chart', 'table', 'news'));
    expect(new Set(split.map((p) => p.anchor)).size).toBe(3);
  });
});

describe('minimising', () => {
  it('makes it small, never gone', () => {
    // The presence is where the alert state is shown. One that can be dismissed
    // entirely is one an operator can lose, and with it the only element that
    // says the kill switch tripped.
    const small = minimiseProjections(singleProjection(), true);
    expect(small[0]!.scale).toBeGreaterThan(0);
    expect(small[0]!.minimised).toBe(true);
  });

  it('restores to full size', () => {
    const restored = minimiseProjections(minimiseProjections(singleProjection(), true), false);
    expect(restored[0]!.scale).toBe(1);
    expect(restored[0]!.minimised).toBe(false);
  });

  it('does not restore a split projection to full size', () => {
    // Three full-size presences would cover the plane they are pointing at.
    const restored = minimiseProjections(
      minimiseProjections(splitProjection(surfaces('chart', 'table')), true),
      false,
    );
    for (const p of restored) expect(p.scale).toBeLessThan(1);
  });
});

describe('repositioning', () => {
  it('moves every projection', () => {
    const moved = repositionProjections(splitProjection(surfaces('chart', 'table')), 'bottom_right');
    expect(moved.every((p) => p.anchor === 'bottom_right')).toBe(true);
  });
});

describe('reading a projection command', () => {
  it('recognises the ones §7 names', () => {
    expect(readProjection('split yourself')?.kind).toBe('split');
    expect(readProjection('minimise')?.kind).toBe('minimise');
    expect(readProjection('get out of the way')?.kind).toBe('minimise');
    expect(readProjection('come back to full size')?.kind).toBe('restore');
    expect(readProjection('just one of you please')?.kind).toBe('merge');
    expect(readProjection('move to the left')).toEqual({ kind: 'move', anchor: 'left' });
    expect(readProjection('go to the bottom right')).toEqual({ kind: 'move', anchor: 'bottom_right' });
  });

  it('returns null for an ordinary question', () => {
    for (const phrase of ['show me gold', 'what is the risk', '']) {
      expect(readProjection(phrase)).toBeNull();
    }
  });
});

describe('contextual transformation', () => {
  it('becomes the representation when the representation is the subject', () => {
    expect(representationFor(surfaces('distribution')[0])).toBe('distribution');
    expect(representationFor(surfaces('network')[0])).toBe('network');
    expect(representationFor(surfaces('timeline')[0])).toBe('timeline');
  });

  it('stays a core for everything else', () => {
    // A presence that reshapes constantly is a distraction wearing the costume
    // of information.
    expect(representationFor(surfaces('table')[0])).toBe('core');
    expect(representationFor(surfaces('news')[0])).toBe('core');
    expect(representationFor(null)).toBe('core');
    expect(representationFor(undefined)).toBe('core');
  });
});

describe('the renderer abstraction tells the truth', () => {
  it('lists every backend §7 names', () => {
    for (const id of ['canvas2d', 'webgl', 'webxr', 'holographic']) {
      expect(RENDERERS.map((r) => r.id)).toContain(id);
    }
  });

  it('reports exactly the one that exists', () => {
    // Claiming a capability the code does not have is the specific failure the
    // capability registry exists to catch.
    expect(availableRenderers().map((r) => r.id)).toEqual(['canvas2d']);
  });

  it('gives a reason for every unavailable backend', () => {
    for (const r of RENDERERS) {
      if (!r.available) expect(r.reason.length).toBeGreaterThan(10);
    }
  });

  it('does not fall back silently when VR is asked for', () => {
    // A deployment believing it is in VR, with nothing on screen to tell the
    // operator otherwise, is the same defect as a ring drawn for an unmeasured
    // number.
    const picked = selectRenderer('webxr');
    expect(picked.renderer.id).toBe('canvas2d');
    expect(picked.fellBack).toBe(true);
    expect(picked.reason).toMatch(/WebXR/i);
  });

  it('does not report a fall-back when none happened', () => {
    expect(selectRenderer('canvas2d')).toEqual({
      renderer: RENDERERS[0],
      fellBack: false,
      reason: '',
    });
    expect(selectRenderer().fellBack).toBe(false);
  });

  it('says so for a renderer nobody has heard of', () => {
    const picked = selectRenderer('hologram_deck' as never);
    expect(picked.fellBack).toBe(true);
    expect(picked.reason).toMatch(/unknown renderer/i);
  });
});
