/**
 * Owner reference, 2026-09-15: "Make it look like the head exactly."
 *
 * The reference head is a SHADED VOLUME. It has a lit side and a dark side, a
 * bright rim where the surface turns away, and horizontal scan bands running
 * across the form. `headMesh` gives contours, and contours alone read as a wire
 * cage however dense they get — you can see the back of the head through the
 * front of it, and no amount of line weight fixes that, because the problem is
 * that nothing is filled.
 *
 * `headSurface` is the fill: the same geometry sampled as quads, each carrying
 * the three numbers a renderer needs and nothing else — how much light it
 * catches, how close it is to the silhouette, and how deep it sits. Pure, so
 * the lighting is testable without a canvas, which is the same reason
 * `mouthFor` and `faceRelief` live here.
 *
 * ## Only the front is returned
 *
 * Back-facing quads are dropped rather than drawn and covered. Painter's
 * algorithm would get the right picture either way; it would also double the
 * fill calls, and this runs every frame on a page that also places orders.
 *
 * ## The rim is a Fresnel term, not an outline
 *
 * An outline is drawn where the artist decided the edge is. A Fresnel term is
 * bright wherever the surface turns away from the viewer, so it brightens the
 * jaw and the brow and the bridge of the nose on its own, and it follows the
 * head when it turns without anyone maintaining a second silhouette.
 */
import { describe, it, expect } from 'vitest';

import { headSurface, type SurfaceQuad } from '../hub/head';

const BASE = {
  radius: 100,
  yaw: 0,
  pitch: 0,
  mouthOpenness: 0,
  time: 0,
  reducedMotion: false,
};

const quads = (over: Partial<typeof BASE> = {}): SurfaceQuad[] =>
  headSurface({ ...BASE, ...over });

describe('headSurface — it is a solid', () => {
  it('returns enough quads to read as a surface, not a mesh', () => {
    expect(quads().length).toBeGreaterThan(300);
  });

  it('returns only the quads facing the viewer', () => {
    // Drawing the far side and covering it is the same picture for twice the
    // fill calls, every frame, on a page that also places orders.
    for (const q of quads()) expect(q.facing).toBeGreaterThan(0);
  });

  it('gives every quad four finite corners', () => {
    for (const q of quads({ yaw: 0.6, pitch: -0.3, mouthOpenness: 1 })) {
      expect(q.points).toHaveLength(4);
      for (const p of q.points) {
        expect(Number.isFinite(p.x)).toBe(true);
        expect(Number.isFinite(p.y)).toBe(true);
      }
    }
  });

  it('sorts back to front, so a painter can just draw them in order', () => {
    const list = quads();
    for (let i = 1; i < list.length; i += 1) {
      expect(list[i]!.depth).toBeGreaterThanOrEqual(list[i - 1]!.depth);
    }
  });

  it('scales with radius', () => {
    // Not quad-for-quad: the grid is chosen from the size, because 40x46 across
    // a 56-pixel dock is nine hundred quads on a thumbnail, most of them
    // smaller than a pixel and every one a fill and a stroke. What must scale
    // is the SHAPE, so the claim is about the silhouette rather than the
    // sampling.
    const span = (radius: number) => {
      const list = quads({ radius });
      const xs = list.flatMap((q) => q.points.map((p) => p.x));
      const ys = list.flatMap((q) => q.points.map((p) => p.y));
      return {
        w: Math.max(...xs) - Math.min(...xs),
        h: Math.max(...ys) - Math.min(...ys),
      };
    };
    const small = span(50);
    const large = span(100);
    expect(large.w / small.w).toBeCloseTo(2, 1);
    expect(large.h / small.h).toBeCloseTo(2, 1);
  });

  it('spends fewer quads on a small head than a large one', () => {
    expect(quads({ radius: 18 }).length).toBeLessThan(quads({ radius: 140 }).length / 3);
    // But never so few that the dock's head stops being a surface.
    expect(quads({ radius: 18 }).length).toBeGreaterThan(80);
  });
});

describe('headSurface — the light', () => {
  it('lights the side the light comes from', () => {
    // The key light sits up and to the viewer's left, as it does in the
    // reference. So the left of the face is brighter than the right — and if
    // this ever reverses, the head is lit from somewhere nobody chose.
    const list = quads();
    const left = list.filter((q) => q.points[0]!.x < -30);
    const right = list.filter((q) => q.points[0]!.x > 30);
    const mean = (qs: SurfaceQuad[]) => qs.reduce((a, q) => a + q.light, 0) / qs.length;
    expect(left.length).toBeGreaterThan(10);
    expect(right.length).toBeGreaterThan(10);
    expect(mean(left)).toBeGreaterThan(mean(right));
  });

  it('keeps light in 0..1 across the whole input range', () => {
    for (const yaw of [-1, 0, 1]) {
      for (const pitch of [-0.5, 0, 0.5]) {
        for (const q of quads({ yaw, pitch })) {
          expect(q.light).toBeGreaterThanOrEqual(0);
          expect(q.light).toBeLessThanOrEqual(1);
        }
      }
    }
  });

  it('keeps the lamp with the viewer, not with the head', () => {
    // A light fixed to the head turns with it, which is a head carrying its own
    // lamp — the shading then never changes and the rotation stops reading. A
    // light fixed to the viewer is a room. So the bright side stays on the
    // viewer's left at every angle, and that is the decision, not an accident:
    // if this ever flips, the light has been attached to the model.
    for (const yaw of [-1, -0.5, 0, 0.5, 1]) {
      const list = headSurface({ ...BASE, yaw });
      const lit = [...list].sort((a, b) => b.light - a.light).slice(0, 60);
      const meanX = lit.reduce((a, q) => a + q.points[0]!.x, 0) / lit.length;
      expect(meanX).toBeLessThan(0);
    }
  });

  it('turns a different part of the surface toward the viewer as it rotates', () => {
    // The proof that rotation reaches the shading rather than stopping at the
    // outline: which quads are front-facing at all is a function of yaw.
    const facingCount = (yaw: number) => headSurface({ ...BASE, yaw }).length;
    const straight = facingCount(0);
    expect(Math.abs(facingCount(1.1) - straight)).toBeGreaterThan(5);
    // And the nose swings with the head. The nearest point of the surface to
    // the viewer IS the nose — that is what `faceRelief` builds — so where it
    // lands on screen is a direct read on whether the rotation reached the
    // geometry or stopped at the silhouette.
    const noseX = (yaw: number) => {
      const list = headSurface({ ...BASE, yaw });
      const nearest = list[list.length - 1]!;
      return nearest.points[0]!.x;
    };
    // 0.07 of the radius, measured rather than chosen: at 0.9 radians the
    // nearest quad lands about 9.6 units off centre on a 100-unit head. It is a
    // discrete sample of a smooth surface, so the figure is the grid's
    // resolution as much as the rotation's — which is why the threshold sits
    // under it rather than on it.
    expect(noseX(0.9)).toBeGreaterThan(noseX(0) + BASE.radius * 0.07);
    expect(noseX(-0.9)).toBeLessThan(noseX(0) - BASE.radius * 0.07);
  });
});

describe('headSurface — the rim', () => {
  it('is brightest at the silhouette and dimmest looking straight at the face', () => {
    const list = quads();
    const edge = list.filter((q) => Math.abs(q.points[0]!.x) > 60);
    const centre = list.filter((q) => Math.abs(q.points[0]!.x) < 26 && Math.abs(q.points[0]!.y) < 45);
    const mean = (qs: SurfaceQuad[]) => qs.reduce((a, q) => a + q.rim, 0) / qs.length;
    expect(edge.length).toBeGreaterThan(5);
    expect(centre.length).toBeGreaterThan(5);
    expect(mean(edge)).toBeGreaterThan(mean(centre) + 0.2);
  });

  it('stays in 0..1', () => {
    for (const q of quads({ yaw: 1.2, pitch: 0.4 })) {
      expect(q.rim).toBeGreaterThanOrEqual(0);
      expect(q.rim).toBeLessThanOrEqual(1);
    }
  });
});

describe('headSurface — the scan bands', () => {
  it('carries the latitude each quad sits at, so bands can follow the form', () => {
    // A scan band drawn as a straight screen-space line crosses the nose and
    // the cheek at the same height and tells you nothing about either. Banding
    // by latitude wraps the band around the head.
    const vs = quads().map((q) => q.v);
    expect(Math.min(...vs)).toBeLessThan(-0.5);
    expect(Math.max(...vs)).toBeGreaterThan(0.5);
  });

  it('does not move with the clock', () => {
    // The surface is a function of where the head is and what it is saying.
    // The travelling band is the renderer's job, from `time`, over a surface
    // that does not itself flicker.
    const a = headSurface({ ...BASE, time: 0 });
    const b = headSurface({ ...BASE, time: 8888 });
    expect(JSON.stringify(b)).toBe(JSON.stringify(a));
  });
});

describe('headSurface — the jaw', () => {
  it('opens with the mouth', () => {
    const lowest = (o: number) =>
      Math.max(...headSurface({ ...BASE, mouthOpenness: o }).flatMap((q) => q.points.map((p) => p.y)));
    expect(lowest(1)).toBeGreaterThan(lowest(0));
  });

  it('is absent above the jaw line, so the face does not stretch', () => {
    const shutTop = Math.min(...headSurface({ ...BASE, mouthOpenness: 0 }).map((q) => Math.min(...q.points.map((p) => p.y))));
    const wideTop = Math.min(...headSurface({ ...BASE, mouthOpenness: 1 }).map((q) => Math.min(...q.points.map((p) => p.y))));
    expect(wideTop).toBeCloseTo(shutTop, 6);
  });
});
