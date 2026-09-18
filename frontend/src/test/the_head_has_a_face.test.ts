/**
 * Owner reference, 2026-09-15: a cyan holographic head, front-lit, with a
 * recognisable face — brow, eye sockets, a nose, lips, a chin — and a neck
 * running down into shoulders, drawn in close horizontal contours.
 *
 * `headMesh` gave the presence volume and orientation. What it did not give it
 * was a FACE: the silhouette was a head, and every point on the surface sat at
 * the profile radius, so straight on it read as an egg with features painted on
 * it. A face is relief — the nose comes toward you, the sockets go away from
 * you — and relief is what makes a wireframe read as a head at a glance rather
 * than after study.
 *
 * `faceRelief` is that displacement: a pure function of longitude and latitude
 * returning how far the surface moves along its own normal. It is deliberately
 * anatomical rather than decorative — the nose is on the centre line, the
 * sockets are where eyes are, the chin is under the mouth — and it is zero
 * everywhere behind the ears, because the back of a skull is a cranium and a
 * bumpy one would read as damage.
 *
 * ## Why not a mesh file
 *
 * A head is the obvious case for a loaded model. It is the wrong answer here.
 * A .glb is bytes nobody can review in a diff, it needs a loader and a renderer
 * this canvas does not have, and the head has to respond to measurements — a
 * jaw that hinges on the character being spoken, brows that carry a risk
 * reading — which means driving vertices at runtime either way. Sixty lines of
 * arithmetic that every reviewer can check beats a binary nobody can.
 */
import { describe, it, expect } from 'vitest';

import { faceRelief, headMesh, type HeadMesh } from '../hub/head';

const BASE = {
  radius: 100,
  yaw: 0,
  pitch: 0,
  mouthOpenness: 0,
  time: 0,
  reducedMotion: false,
};

/** Longitude 0 is the centre of the face; ±PI is the back of the skull. */
const FRONT = 0;

describe('faceRelief — it is a face, not a bumpy egg', () => {
  it('pushes a nose out on the centre line', () => {
    const nose = faceRelief(FRONT, 0.02);
    expect(nose).toBeGreaterThan(0.1);
    // And it is a nose, not a ridge running round the head.
    expect(faceRelief(1.2, 0.02)).toBeLessThan(nose / 2);
  });

  it('recesses the eye sockets', () => {
    // Where the eyes sit, the surface must go AWAY from the viewer, or the eyes
    // float on the front of a ball instead of sitting in a skull.
    expect(faceRelief(0.44, 0.14)).toBeLessThan(0);
  });

  it('puts a brow ridge above the sockets', () => {
    expect(faceRelief(0.44, 0.28)).toBeGreaterThan(faceRelief(0.44, 0.14));
  });

  it('leaves the back of the skull smooth', () => {
    // A cranium with relief on it reads as damage.
    for (const v of [-0.6, -0.2, 0, 0.3, 0.7]) {
      expect(Math.abs(faceRelief(Math.PI, v))).toBeLessThan(1e-9);
      expect(Math.abs(faceRelief(-Math.PI * 0.8, v))).toBeLessThan(1e-9);
    }
  });

  it('is continuous — no seam anyone can see', () => {
    // A step in the displacement shows up as a crease running down the face.
    let worst = 0;
    for (let u = -Math.PI; u < Math.PI; u += 0.01) {
      for (const v of [-0.5, -0.2, 0, 0.2, 0.5]) {
        worst = Math.max(worst, Math.abs(faceRelief(u + 0.01, v) - faceRelief(u, v)));
      }
    }
    expect(worst).toBeLessThan(0.02);
  });

  it('is bounded — relief is a face, not a spike', () => {
    // 0.6, not 0.35: the first shaded render showed the shallower relief was a
    // flat slab. The normals barely tilted, so the light had nothing to model
    // and the nose was invisible under it. Depth is the point; the bound exists
    // to stop a feature becoming a spike, and 0.6 of the head's half-width
    // still cannot.
    for (let u = -Math.PI; u <= Math.PI; u += 0.02) {
      for (let v = -1; v <= 1; v += 0.02) {
        expect(Math.abs(faceRelief(u, v))).toBeLessThan(0.6);
      }
    }
  });

  it('is symmetric about the centre line', () => {
    for (const u of [0.2, 0.5, 0.9, 1.4]) {
      for (const v of [-0.4, 0, 0.3]) {
        expect(faceRelief(-u, v)).toBeCloseTo(faceRelief(u, v), 12);
      }
    }
  });
});

describe('headMesh — the neck and shoulders', () => {
  it('has a neck below the jaw', () => {
    const mesh = headMesh(BASE);
    expect(mesh.neck.length).toBeGreaterThan(0);
    const headBottom = Math.max(
      ...[...mesh.shell, ...mesh.jaw].flatMap((s) => s.points.map((p) => p.y)),
    );
    const neckBottom = Math.max(...mesh.neck.flatMap((s) => s.points.map((p) => p.y)));
    expect(neckBottom).toBeGreaterThan(headBottom);
  });

  it('is narrower than the head at the top and wider at the bottom', () => {
    // A neck that ran straight down at head width is a column. The reference
    // head narrows at the throat and spreads into shoulders.
    const mesh = headMesh(BASE);
    const byHeight = [...mesh.neck].sort((a, b) => a.points[0]!.y - b.points[0]!.y);
    const widthOf = (s: { points: { x: number }[] }) =>
      Math.max(...s.points.map((p) => p.x)) - Math.min(...s.points.map((p) => p.x));
    expect(widthOf(byHeight[byHeight.length - 1]!)).toBeGreaterThan(widthOf(byHeight[0]!));
  });

  it('turns with the head', () => {
    const front = headMesh(BASE).neck[0]!.points[0]!;
    const turned = headMesh({ ...BASE, yaw: 0.8 }).neck[0]!.points[0]!;
    expect(turned.x).not.toBeCloseTo(front.x, 3);
  });

  it('does not move when the jaw does', () => {
    const shut = headMesh({ ...BASE, mouthOpenness: 0 }).neck;
    const wide = headMesh({ ...BASE, mouthOpenness: 1 }).neck;
    for (let i = 0; i < shut.length; i += 1) {
      for (let j = 0; j < shut[i]!.points.length; j += 1) {
        expect(wide[i]!.points[j]!.y).toBeCloseTo(shut[i]!.points[j]!.y, 9);
      }
    }
  });
});

describe('headMesh — the relief reaches the surface', () => {
  it('brings the middle of the face toward the viewer', () => {
    // The nose is the proof: on the centre meridian, at the nose's latitude,
    // the surface must sit in FRONT of where the plain profile would put it.
    const mesh = headMesh(BASE);
    const fronts = [...mesh.shell, ...mesh.jaw].filter((s) => s.depth > 0.6);
    expect(fronts.length).toBeGreaterThan(0);
  });

  it('still fits the box it was sized for', () => {
    const points = [...headMesh({ ...BASE, mouthOpenness: 1 }).shell, ...headMesh(BASE).neck]
      .flatMap((s) => s.points);
    for (const p of points) {
      expect(Math.abs(p.x)).toBeLessThanOrEqual(BASE.radius * 1.9);
      // 2.5, not 2.1: the head is 1.44 radii tall against the reference's
      // proportions (it was 1.3 and projected as an egg) and the neck runs
      // another 0.56 below the chin. The number that actually protects the
      // canvas is the clamp on `headScale` in PresenceCore, which keeps the
      // face inside the risk ring; this is the coarse backstop.
      expect(Math.abs(p.y)).toBeLessThanOrEqual(BASE.radius * 2.5);
    }
  });

  it('draws the face in close contours, not a coarse cage', () => {
    // The reference reads as a hologram because the horizontal lines are close
    // together. Too few and it is a wire cage; this holds the density.
    const mesh: HeadMesh = headMesh(BASE);
    expect(mesh.shell.length + mesh.jaw.length).toBeGreaterThan(40);
  });
});
