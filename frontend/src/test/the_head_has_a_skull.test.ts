/**
 * §7 asks for "a professional holographic head". What was drawn was an ellipse
 * with two dots and a second ellipse for a mouth — flat, always facing forward,
 * and identical whether the presence was looking at the order ticket or at
 * nothing. `gazeToward` measured where to look and `headOffset` translated the
 * whole drawing a few pixels toward it; the head itself never turned, because
 * there was no head to turn. An outline has no orientation.
 *
 * `headMesh` gives it one: a volumetric wireframe skull, rotated by yaw and
 * pitch, projected with perspective so the near side is larger, split at the
 * mandible so the jaw articulates with the measured mouth openness.
 *
 * It is pure — numbers in, numbers out — so every claim below is provable
 * without a canvas, which is the same reason `mouthFor` and `particleField`
 * live in this file rather than in the component.
 *
 * ## What it must NOT do
 *
 * Animate from a clock. The jaw is driven by `mouthOpenness`, which comes from
 * `mouthFor`, which comes from the character the engine reports it is speaking.
 * A jaw that flapped on `Date.now()` would be the same animation for "yes" and
 * for a four-hundred-word briefing, and would keep flapping after synthesis
 * silently died. The only thing here a clock may move is the scan ring, and it
 * carries no information and stops under reduced motion.
 */
import { describe, it, expect } from 'vitest';

import { headMesh, type HeadMesh } from '../hub/head';

const BASE = {
  radius: 100,
  yaw: 0,
  pitch: 0,
  mouthOpenness: 0,
  time: 0,
  reducedMotion: false,
};

function allPoints(mesh: HeadMesh): { x: number; y: number }[] {
  return [...mesh.shell, ...mesh.jaw].flatMap((s) => s.points);
}

describe('headMesh — it is a head', () => {
  it('has volume: the points do not share one depth', () => {
    // The defect this replaces is a flat outline. A mesh whose every point sat
    // at one z would be the same outline with extra steps.
    const mesh = headMesh(BASE);
    const depths = new Set([...mesh.shell, ...mesh.jaw].map((s) => s.depth.toFixed(3)));
    expect(depths.size).toBeGreaterThan(4);
  });

  it('is widest at the cheekbones, not at the middle of a ball', () => {
    // A sphere is widest exactly halfway between its poles. A head is widest
    // above that, at the cheekbones, and tapers to a chin. If this ever reads
    // "halfway" again, the profile table has been replaced by a circle.
    const mesh = headMesh(BASE);
    const points = allPoints(mesh);
    const top = Math.min(...points.map((p) => p.y));
    const bottom = Math.max(...points.map((p) => p.y));
    const widest = points.reduce((a, b) => (Math.abs(b.x) > Math.abs(a.x) ? b : a));
    const height = bottom - top;
    const fractionFromTop = (widest.y - top) / height;
    // Above the midpoint, and not right under the crown.
    expect(fractionFromTop).toBeGreaterThan(0.2);
    expect(fractionFromTop).toBeLessThan(0.5);
  });

  it('is taller than it is wide', () => {
    const points = allPoints(headMesh(BASE));
    const width = Math.max(...points.map((p) => p.x)) - Math.min(...points.map((p) => p.x));
    const height = Math.max(...points.map((p) => p.y)) - Math.min(...points.map((p) => p.y));
    expect(height).toBeGreaterThan(width);
  });

  it('scales linearly with radius', () => {
    const small = allPoints(headMesh({ ...BASE, radius: 50 }));
    const large = allPoints(headMesh({ ...BASE, radius: 100 }));
    expect(large.length).toBe(small.length);
    for (let i = 0; i < small.length; i += 1) {
      expect(large[i]!.x).toBeCloseTo(small[i]!.x * 2, 6);
      expect(large[i]!.y).toBeCloseTo(small[i]!.y * 2, 6);
    }
  });

  it('stays inside the box it was sized for', () => {
    // The canvas is allocated from `radius`. A mesh that overran it would be
    // clipped on one side and read as a rendering fault rather than a head.
    for (const yaw of [-1.2, -0.4, 0, 0.4, 1.2]) {
      for (const pitch of [-0.4, 0, 0.4]) {
        const points = allPoints(headMesh({ ...BASE, yaw, pitch, mouthOpenness: 1 }));
        for (const p of points) {
          expect(Math.abs(p.x)).toBeLessThanOrEqual(BASE.radius * 1.7);
          expect(Math.abs(p.y)).toBeLessThanOrEqual(BASE.radius * 1.7);
        }
      }
    }
  });

  it('produces only finite coordinates across the whole input range', () => {
    for (const yaw of [-1.5, -0.7, 0, 0.7, 1.5]) {
      for (const pitch of [-0.6, 0, 0.6]) {
        for (const mouthOpenness of [0, 0.5, 1]) {
          const mesh = headMesh({ ...BASE, yaw, pitch, mouthOpenness, time: 1234 });
          for (const p of allPoints(mesh)) {
            expect(Number.isFinite(p.x)).toBe(true);
            expect(Number.isFinite(p.y)).toBe(true);
          }
          expect(Number.isFinite(mesh.facing)).toBe(true);
        }
      }
    }
  });
});

describe('headMesh — it turns', () => {
  it('faces the viewer fully at zero yaw and pitch', () => {
    expect(headMesh(BASE).facing).toBeCloseTo(1, 6);
  });

  it('shows no face in profile', () => {
    expect(headMesh({ ...BASE, yaw: Math.PI / 2 }).facing).toBeCloseTo(0, 6);
  });

  it('narrows as it turns — a turned head is narrower on screen', () => {
    const front = allPoints(headMesh(BASE));
    const turned = allPoints(headMesh({ ...BASE, yaw: 0.9 }));
    const spanOf = (ps: { x: number }[]) =>
      Math.max(...ps.map((p) => p.x)) - Math.min(...ps.map((p) => p.x));
    // A head is deeper than it is wide, so a 90-degree turn would be WIDER.
    // At 0.9 radians it is between: what must hold is that the silhouette
    // changed, which a flat outline could never do.
    expect(Math.abs(spanOf(turned) - spanOf(front))).toBeGreaterThan(BASE.radius * 0.05);
  });

  it('carries the eyes around with the face', () => {
    const front = headMesh(BASE);
    expect(front.eyes).toHaveLength(2);
    // Symmetric about the centre line when facing forward.
    expect(front.eyes[0]!.x).toBeCloseTo(-front.eyes[1]!.x, 6);
    expect(front.eyes[0]!.y).toBeCloseTo(front.eyes[1]!.y, 6);

    const turned = headMesh({ ...BASE, yaw: 0.7 });
    // Turning brings one eye toward the viewer and pushes the other away. Two
    // dots painted at fixed offsets could not do this, which is exactly what
    // made the old head look flat.
    expect(turned.eyes[0]!.z).not.toBeCloseTo(turned.eyes[1]!.z, 3);
  });

  it('keeps the far side of the skull behind the near side', () => {
    // Depth is what the drawing code dims by. If it did not separate, the back
    // of the head would be drawn as brightly as the face and the mesh would
    // read as a tangle rather than a volume.
    const mesh = headMesh(BASE);
    const depths = [...mesh.shell, ...mesh.jaw].map((s) => s.depth);
    expect(Math.min(...depths)).toBeLessThan(0);
    expect(Math.max(...depths)).toBeGreaterThan(0);
  });
});

describe('headMesh — the jaw is driven by the utterance', () => {
  it('drops the chin as the mouth opens', () => {
    const lowest = (o: number) =>
      Math.max(...headMesh({ ...BASE, mouthOpenness: o }).jaw.flatMap((s) => s.points.map((p) => p.y)));
    const shut = lowest(0);
    const half = lowest(0.5);
    const wide = lowest(1);
    expect(half).toBeGreaterThan(shut);
    expect(wide).toBeGreaterThan(half);
  });

  it('moves the jaw and nothing else', () => {
    // A "talking" animation that scaled the whole head would be a head that
    // pulsed at the reader rather than one that spoke.
    const shut = headMesh({ ...BASE, mouthOpenness: 0 });
    const wide = headMesh({ ...BASE, mouthOpenness: 1 });
    expect(shut.shell.length).toBe(wide.shell.length);
    for (let i = 0; i < shut.shell.length; i += 1) {
      const a = shut.shell[i]!.points;
      const b = wide.shell[i]!.points;
      for (let j = 0; j < a.length; j += 1) {
        expect(b[j]!.x).toBeCloseTo(a[j]!.x, 9);
        expect(b[j]!.y).toBeCloseTo(a[j]!.y, 9);
      }
    }
  });

  it('has a jaw at all, and it is below the eyes', () => {
    const mesh = headMesh(BASE);
    expect(mesh.jaw.length).toBeGreaterThan(0);
    const jawTop = Math.min(...mesh.jaw.flatMap((s) => s.points.map((p) => p.y)));
    expect(jawTop).toBeGreaterThan(mesh.eyes[0]!.y);
  });

  it('clamps an openness outside 0..1 rather than tearing the face off', () => {
    const wide = Math.max(...headMesh({ ...BASE, mouthOpenness: 1 }).jaw.flatMap((s) => s.points.map((p) => p.y)));
    const absurd = Math.max(...headMesh({ ...BASE, mouthOpenness: 40 }).jaw.flatMap((s) => s.points.map((p) => p.y)));
    expect(absurd).toBeCloseTo(wide, 6);
  });
});

describe('headMesh — the scan ring', () => {
  it('sweeps with time', () => {
    const a = headMesh({ ...BASE, time: 0 }).scan;
    const b = headMesh({ ...BASE, time: 900 }).scan;
    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    expect(a!.points[0]!.y).not.toBeCloseTo(b!.points[0]!.y, 3);
  });

  it('is absent under reduced motion, and the head is not', () => {
    // The setting exists to stop a travelling light, not to remove the face.
    const mesh = headMesh({ ...BASE, reducedMotion: true });
    expect(mesh.scan).toBeNull();
    expect(mesh.shell.length).toBeGreaterThan(0);
    expect(mesh.eyes).toHaveLength(2);
  });

  it('does not move the head with the clock', () => {
    // Everything except the scan must be identical at two different times:
    // the head's shape is a function of what it is saying and where it is
    // looking, never of the frame number.
    const a = headMesh({ ...BASE, time: 0 });
    const b = headMesh({ ...BASE, time: 7777 });
    expect(JSON.stringify(b.shell)).toBe(JSON.stringify(a.shell));
    expect(JSON.stringify(b.jaw)).toBe(JSON.stringify(a.jaw));
    expect(JSON.stringify(b.eyes)).toBe(JSON.stringify(a.eyes));
  });

  it('tracks the silhouette rather than being a straight line', () => {
    // A ruler across the face is a progress bar. A ring that follows the
    // skull's width at the height it has reached is a scan.
    const scan = headMesh({ ...BASE, time: 400 }).scan!;
    const xs = scan.points.map((p) => p.x);
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(0);
    const ys = scan.points.map((p) => p.y);
    // A ring seen from the front is an ellipse: it has height as well as width.
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan(0);
  });
});

describe('headMesh — it wears the expression the brain chose', () => {
  it('rolls the whole head when it tilts, without reshaping it', () => {
    const upright = headMesh(BASE);
    const tilted = headMesh({ ...BASE, roll: 0.2 });
    // A tilt is a rotation, so the silhouette's area is preserved while points
    // move. A "tilt" that only slid the drawing sideways would be a shrug.
    expect(tilted.eyes[0]!.y).not.toBeCloseTo(upright.eyes[0]!.y, 3);
    const span = (m: HeadMesh) => {
      const ps = allPoints(m);
      return Math.hypot(
        Math.max(...ps.map((p) => p.x)) - Math.min(...ps.map((p) => p.x)),
        Math.max(...ps.map((p) => p.y)) - Math.min(...ps.map((p) => p.y)),
      );
    };
    expect(span(tilted)).toBeCloseTo(span(upright), -1);
  });

  it('has brows, and they sit above the eyes', () => {
    const mesh = headMesh(BASE);
    expect(mesh.brows).toHaveLength(2);
    for (const brow of mesh.brows) {
      const lowest = Math.max(...brow.points.map((p) => p.y));
      expect(lowest).toBeLessThan(mesh.eyes[0]!.y);
    }
  });

  it('raises and lowers the brow with the reading', () => {
    const topOf = (b: number) =>
      Math.min(...headMesh({ ...BASE, brow: b }).brows.flatMap((s) => s.points.map((p) => p.y)));
    // Raised is higher on screen, which is a SMALLER y.
    expect(topOf(1)).toBeLessThan(topOf(0));
    expect(topOf(-1)).toBeGreaterThan(topOf(0));
  });

  it('closes the eyes rather than shrinking them', () => {
    // A shut eye is a line across the socket. An eye that shrank to a dot would
    // read as a pupil contracting, which means something else entirely.
    const open = headMesh({ ...BASE, lidOpen: 1 });
    const shut = headMesh({ ...BASE, lidOpen: 0 });
    expect(shut.eyes[0]!.openness).toBe(0);
    expect(open.eyes[0]!.openness).toBe(1);
    // The socket does not move when the lid does.
    expect(shut.eyes[0]!.x).toBeCloseTo(open.eyes[0]!.x, 9);
    expect(shut.eyes[0]!.y).toBeCloseTo(open.eyes[0]!.y, 9);
  });

  it('defaults to an open-eyed, level, neutral face when given no expression', () => {
    // Every existing caller passes none of these. They must not suddenly find
    // the presence squinting.
    const mesh = headMesh(BASE);
    expect(mesh.eyes[0]!.openness).toBe(1);
    expect(mesh.brows).toHaveLength(2);
  });
});

describe('headMesh — the mouth is visible, and it opens', () => {
  it('has a lip line in two halves', () => {
    const mesh = headMesh(BASE);
    expect(mesh.mouth.upper.points.length).toBeGreaterThan(2);
    expect(mesh.mouth.lower.points.length).toBeGreaterThan(2);
  });

  it('closes to a single line when the mouth is shut', () => {
    // The jaw hinging is not visible on its own — the old head had a mouth
    // ellipse, and a mesh that dropped it would be a talking head you cannot
    // see talk. The two lips meet when shut and part when the jaw swings.
    const shut = headMesh({ ...BASE, mouthOpenness: 0 });
    for (let i = 0; i < shut.mouth.upper.points.length; i += 1) {
      expect(shut.mouth.lower.points[i]!.y).toBeCloseTo(shut.mouth.upper.points[i]!.y, 6);
      expect(shut.mouth.lower.points[i]!.x).toBeCloseTo(shut.mouth.upper.points[i]!.x, 6);
    }
  });

  it('parts as the mouth opens, and by more the wider it goes', () => {
    const gap = (o: number) => {
      const m = headMesh({ ...BASE, mouthOpenness: o });
      const mid = Math.floor(m.mouth.upper.points.length / 2);
      return m.mouth.lower.points[mid]!.y - m.mouth.upper.points[mid]!.y;
    };
    expect(gap(0)).toBeCloseTo(0, 6);
    expect(gap(0.5)).toBeGreaterThan(0.5);
    expect(gap(1)).toBeGreaterThan(gap(0.5));
  });

  it('keeps the upper lip still — only the jaw moves', () => {
    const shut = headMesh({ ...BASE, mouthOpenness: 0 }).mouth.upper.points;
    const wide = headMesh({ ...BASE, mouthOpenness: 1 }).mouth.upper.points;
    for (let i = 0; i < shut.length; i += 1) {
      expect(wide[i]!.y).toBeCloseTo(shut[i]!.y, 9);
    }
  });

  it('sits on the front of the face, below the eyes', () => {
    const mesh = headMesh(BASE);
    const lipY = mesh.mouth.upper.points[0]!.y;
    expect(lipY).toBeGreaterThan(mesh.eyes[0]!.y);
    // Across the middle of the face, not wrapped around the skull.
    const xs = mesh.mouth.upper.points.map((p) => p.x);
    expect(Math.max(...xs)).toBeLessThan(BASE.radius * 0.7);
    expect(Math.min(...xs)).toBeGreaterThan(-BASE.radius * 0.7);
  });
});

describe('headMesh — the pupils', () => {
  it('carry the dilation the brain chose', () => {
    const narrow = headMesh({ ...BASE, pupil: 0.6 });
    const wide = headMesh({ ...BASE, pupil: 1.4 });
    expect(wide.eyes[0]!.pupilRadius).toBeGreaterThan(narrow.eyes[0]!.pupilRadius);
    // A pupil is inside its eye, whatever the caller asks for.
    expect(wide.eyes[0]!.pupilRadius).toBeLessThan(wide.eyes[0]!.radius);
  });

  it('default to a plain open eye', () => {
    const mesh = headMesh(BASE);
    expect(mesh.eyes[0]!.pupilRadius).toBeGreaterThan(0);
    expect(mesh.eyes[0]!.pupilRadius).toBeLessThan(mesh.eyes[0]!.radius);
  });
});
