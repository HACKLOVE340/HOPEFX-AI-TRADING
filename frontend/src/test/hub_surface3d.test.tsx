/**
 * Phase I6 — §21's last row: 3D **where it aids understanding**.
 *
 * The note said "only canvas2d is implemented", which describes what exists
 * rather than naming a blocker, and it confused two things:
 *
 * **3D is not WebGL.** A mesh projected onto a 2D context is real 3D — the
 * dimension is in the data and the projection, not in the API that rasterises
 * the triangles. WebGL is an acceleration path, and it stays honestly
 * unavailable in `projection.ts` because no GPU-backed context has been proven
 * here. That no longer holds the capability hostage.
 *
 * ## The clause in the spec is a constraint
 *
 * "Where they aid understanding". On a trading screen a gratuitous third
 * dimension costs three things that are not cosmetic — occlusion hides the
 * value somebody needed, foreshortening makes equal magnitudes read as
 * different, and a receding plane removes the shared baseline that comparison
 * depends on. So `warrants3D` refuses more often than it accepts, and most of
 * the tests below are refusals.
 *
 * ## The one that matters most on this platform
 *
 * A volatility surface with no quote at a strike has a HOLE. A mesh drawn
 * straight across it renders a smooth surface where there is no market — a
 * price a reader could act on that nobody ever quoted. Every face touching a
 * hole is omitted, so a gap in the data is a gap in the picture.
 */

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_CAMERA,
  MAX_PITCH,
  MIN_SAMPLES_PER_AXIS,
  describeSurface,
  expectedFaceCount,
  holes,
  meshFaces,
  project,
  validateGrid,
  warrants3D,
  type SurfaceGrid,
} from '../hub/surface3d';

/** A well-formed volatility-surface-shaped grid: a smile that steepens with tenor. */
function volSurface(nx = 6, ny = 5): SurfaceGrid {
  const xs = Array.from({ length: nx }, (_, i) => 1800 + i * 25); // strikes
  const ys = Array.from({ length: ny }, (_, i) => 7 + i * 30); // days to expiry
  const z = ys.map((tenor) =>
    xs.map((strike) => {
      const moneyness = (strike - 1860) / 100;
      return 0.12 + moneyness * moneyness * (0.4 + tenor / 400);
    }),
  );
  return { xs, ys, z, xLabel: 'strike', yLabel: 'days to expiry', zLabel: 'implied volatility' };
}

describe('§21 a grid says what is wrong with it, all of it', () => {
  it('accepts a well-formed surface', () => {
    expect(validateGrid(volSurface())).toEqual([]);
  });

  it('refuses a grid whose rows do not match its axes', () => {
    const grid = volSurface();
    const broken: SurfaceGrid = { ...grid, z: grid.z.map((row) => row.slice(0, 3)) };
    expect(validateGrid(broken).map((p) => p.kind)).toContain('ragged');
  });

  it('refuses an axis that is not strictly ascending', () => {
    // A repeated sample puts two different z values at one coordinate, and the
    // mesh silently keeps whichever it drew last.
    const grid = volSurface();
    const repeated: SurfaceGrid = { ...grid, xs: [1800, 1825, 1825, 1875, 1900, 1925] };
    expect(validateGrid(repeated).map((p) => p.kind)).toContain('unordered');
  });

  it('distinguishes NaN from a hole, because they mean opposite things', () => {
    // null is "nobody quoted this". NaN is "a calculation went wrong". Letting
    // NaN read as absent hides a broken pricer behind a plausible gap.
    const grid = volSurface();
    const z = grid.z.map((row) => [...row]);
    z[0]![0] = Number.NaN;
    const problems = validateGrid({ ...grid, z });
    expect(problems.map((p) => p.kind)).toContain('non_finite');
    expect(problems.find((p) => p.kind === 'non_finite')!.detail).toMatch(/null/);
  });

  it('reports every problem rather than only the first', () => {
    // A caller that fixed one and came back for the next would be told about a
    // two-line defect three times.
    const bad: SurfaceGrid = { xs: [3, 1, 2], ys: [1, 2], z: [[1]] };
    expect(validateGrid(bad).length).toBeGreaterThan(1);
  });

  it('refuses a grid too small to be a surface', () => {
    const small: SurfaceGrid = { xs: [1, 2], ys: [1, 2], z: [[1, 2], [3, 4]] };
    expect(validateGrid(small).map((p) => p.kind)).toContain('too_small');
    expect(MIN_SAMPLES_PER_AXIS).toBeGreaterThanOrEqual(3);
  });
});

describe('§21 3D has to earn the swap from a heatmap', () => {
  it('accepts a real two-variable surface and says why', () => {
    const verdict = warrants3D(volSurface());
    expect(verdict.warranted).toBe(true);
    expect(verdict.reason).toMatch(/both directions|between them/i);
  });

  it('refuses data that changes in only one direction', () => {
    // A line repeated. Its third dimension is decoration, which is exactly
    // what "where they aid understanding" excludes.
    const xs = [1, 2, 3, 4, 5];
    const ys = [1, 2, 3, 4];
    const grid: SurfaceGrid = { xs, ys, z: ys.map(() => xs.map((x) => x * 2)) };
    const verdict = warrants3D(grid);
    expect(verdict.warranted).toBe(false);
    expect(verdict.reason).toMatch(/one direction|line/i);
  });

  it('refuses a grid that is mostly gaps', () => {
    // Drawn as a surface it would be mostly invention.
    const grid = volSurface();
    const z = grid.z.map((row, yi) => row.map((v, xi) => ((xi + yi) % 2 === 0 ? null : v)));
    const verdict = warrants3D({ ...grid, z });
    expect(verdict.warranted).toBe(false);
    expect(verdict.reason).toMatch(/%|gaps/i);
  });

  it('refuses a malformed grid rather than drawing it', () => {
    const verdict = warrants3D({ xs: [1, 2], ys: [1, 2], z: [[1, 2], [3, 4]] });
    expect(verdict.warranted).toBe(false);
  });

  it('always gives a reason, including when it says yes', () => {
    // The panel shows this. A verdict with no reason is a decision the
    // operator cannot argue with.
    for (const grid of [volSurface(), { xs: [1, 2], ys: [1, 2], z: [[1, 2], [3, 4]] } as SurfaceGrid]) {
      expect(warrants3D(grid).reason.length).toBeGreaterThan(0);
    }
  });
});

describe('§21 the projection measures rather than photographs', () => {
  it('is orthographic: equal heights project to equal screen heights', () => {
    // The money assertion. Under perspective these two differ, and on a screen
    // where z is a price that is a chart misstating its own numbers.
    const near = project({ x: -0.5, y: -0.5, z: 1 }, DEFAULT_CAMERA);
    const nearBase = project({ x: -0.5, y: -0.5, z: 0 }, DEFAULT_CAMERA);
    const far = project({ x: 0.5, y: 0.5, z: 1 }, DEFAULT_CAMERA);
    const farBase = project({ x: 0.5, y: 0.5, z: 0 }, DEFAULT_CAMERA);
    expect(nearBase.y - near.y).toBeCloseTo(farBase.y - far.y, 10);
  });

  it('puts a larger z higher up the screen', () => {
    const low = project({ x: 0, y: 0, z: 0 }, DEFAULT_CAMERA);
    const high = project({ x: 0, y: 0, z: 1 }, DEFAULT_CAMERA);
    expect(high.y).toBeLessThan(low.y);
  });

  it('does not look straight down the rows', () => {
    // Axis-aligned, every row hides the one behind it exactly, which is the
    // worst possible angle for the thing a surface is for.
    expect(DEFAULT_CAMERA.yaw % (Math.PI / 2)).not.toBeCloseTo(0, 6);
  });

  it('clamps pitch so the surface cannot turn inside out', () => {
    const overturned = project({ x: 0, y: 1, z: 0 }, { ...DEFAULT_CAMERA, pitch: Math.PI });
    const clamped = project({ x: 0, y: 1, z: 0 }, { ...DEFAULT_CAMERA, pitch: MAX_PITCH });
    expect(overturned.y).toBeCloseTo(clamped.y, 6);
  });

  it('reports depth so faces can be drawn without a depth buffer', () => {
    const front = project({ x: 0, y: -1, z: 0 }, DEFAULT_CAMERA);
    const back = project({ x: 0, y: 1, z: 0 }, DEFAULT_CAMERA);
    expect(back.depth).toBeGreaterThan(front.depth);
  });
});

describe('§21 a hole is never drawn across', () => {
  it('omits every face touching a missing sample', () => {
    // The rule this module exists for. A face spanning a hole renders a
    // surface where there is no market.
    const grid = volSurface();
    const z = grid.z.map((row) => [...row]);
    z[2]![3] = null;
    const faces = meshFaces({ ...grid, z });
    // One interior sample touches four quads.
    expect(faces.length).toBe(expectedFaceCount(grid) - 4);
  });

  it('draws every face when nothing is missing', () => {
    const grid = volSurface();
    expect(meshFaces(grid).length).toBe(expectedFaceCount(grid));
  });

  it('names the holes rather than hiding them', () => {
    const grid = volSurface();
    const z = grid.z.map((row) => [...row]);
    z[1]![2] = null;
    expect(holes({ ...grid, z })).toEqual([{ x: grid.xs[2]!, y: grid.ys[1]! }]);
  });

  it('draws nothing at all for a malformed grid', () => {
    // Rather than drawing part of it, which would look like a surface.
    expect(meshFaces({ xs: [1, 2], ys: [1, 2], z: [[1, 2], [3, 4]] })).toEqual([]);
  });

  it('orders faces back to front so a 2D context can paint them', () => {
    // The whole reason this needs no GPU.
    const faces = meshFaces(volSurface());
    const depths = faces.map((f) => f.depth);
    expect([...depths].sort((a, b) => a - b)).toEqual(depths);
  });
});

describe('§21 what the panel says out loud', () => {
  it('tells a reader the bite out of the surface is missing data', () => {
    // Otherwise they read the gap as a shape.
    const grid = volSurface();
    const z = grid.z.map((row) => [...row]);
    z[2]![3] = null;
    const withHole = { ...grid, z };
    const said = describeSurface(withHole, meshFaces(withHole));
    expect(said).toMatch(/left out|no data/i);
    expect(said).toMatch(/4 of 20/);
  });

  it('says it is complete when it is', () => {
    const grid = volSurface();
    expect(describeSurface(grid, meshFaces(grid))).toMatch(/complete/i);
  });

  it('explains the fall back to a table when 3D was refused', () => {
    const xs = [1, 2, 3, 4, 5];
    const ys = [1, 2, 3, 4];
    const flat: SurfaceGrid = { xs, ys, z: ys.map(() => xs.map((x) => x * 2)) };
    expect(describeSurface(flat, [])).toMatch(/table/i);
  });

  it('uses the axis names it was given', () => {
    const grid = volSurface();
    const said = describeSurface(grid, meshFaces(grid));
    expect(said).toContain('implied volatility');
    expect(said).toContain('strike');
  });
});

describe('§21 the surface must not vanish into the panel it sits on', () => {
  it('keeps its darkest face clear of the panel background', async () => {
    // Measured, not chosen. At the 26% lightness this ramp started as, the
    // darkest faces sat at 1.65:1 against the panel — a TROUGH would have been
    // indistinguishable from a HOLE, which is exactly the distinction this
    // whole module exists to make. The number below is derived from the
    // palette rather than typed, so moving either one fails here.
    const { NON_TEXT_FLOOR, SURFACES, contrastRatio } = await import('../hub/a11yContrast');
    const { surfaceInkHex } = await import('../hub/VizMarks');

    const darkest = surfaceInkHex(0);
    expect(contrastRatio(darkest, SURFACES.panel)).toBeGreaterThanOrEqual(NON_TEXT_FLOOR);
  });

  it('keeps the two ends of the ramp apart from each other', async () => {
    const { NON_TEXT_FLOOR, contrastRatio } = await import('../hub/a11yContrast');
    const { surfaceInkHex } = await import('../hub/VizMarks');
    expect(contrastRatio(surfaceInkHex(0), surfaceInkHex(1))).toBeGreaterThanOrEqual(NON_TEXT_FLOOR);
  });

  it('is monotonic, so a higher value never reads as a lower one', async () => {
    // Colour is redundant here because height already encodes the value, but a
    // ramp that folded back on itself would make two different values the same
    // colour and undo the redundancy.
    const { relativeLuminance } = await import('../hub/a11yContrast');
    const { surfaceInkHex } = await import('../hub/VizMarks');
    const lums = [0, 0.25, 0.5, 0.75, 1].map((t) => relativeLuminance(surfaceInkHex(t)));
    expect([...lums].sort((a, b) => a - b)).toEqual(lums);
  });
});

describe('§21 the panel renders it, and never without its table', () => {
  it('registers surface3d as a rendered kind with a table twin', async () => {
    // The a11y rule this file already holds: a surface encodes in height AND
    // hue, and a keyboard-only screen reader has neither. A kind that rendered
    // without a twin would be the one mark in the panel with no text route.
    const { RENDERED_KINDS } = await import('../hub/SurfaceView');
    expect(RENDERED_KINDS).toContain('surface3d');

    const fs = await import('node:fs');
    const path = await import('node:path');
    const { fileURLToPath } = await import('node:url');
    const here = path.dirname(fileURLToPath(import.meta.url));
    const source = fs.readFileSync(path.resolve(here, '..', 'hub', 'SurfaceView.tsx'), 'utf8');
    const tables = source.slice(source.indexOf('const TABLES'), source.indexOf('export interface SurfaceViewProps'));
    expect(tables).toContain('surface3d');
  });

  it('draws the mesh and says how much of it is missing', async () => {
    const { render } = await import('@testing-library/react');
    const { Surface3D } = await import('../hub/VizMarks');

    const grid = volSurface();
    const z = grid.z.map((row) => [...row]);
    z[2]![3] = null;
    // Scoped to THIS render's container, not `document`. Querying the document
    // found the previous test's SVG and made the refusal test below pass while
    // looking at a drawn surface — a leak between cases that reads as a pass.
    const { container } = render(<Surface3D grid={{ ...grid, z }} />);

    const svg = container.querySelector('[data-surface3d="drawn"]')!;
    expect(svg).not.toBeNull();
    expect(svg.getAttribute('data-dropped')).toBe('4');
    // The picture carries its own caption, so the gap is not read as a shape.
    expect(svg.getAttribute('aria-label')).toMatch(/left out/i);
  });

  it('refuses to draw what warrants3D rejected, and says why instead', async () => {
    // Otherwise the rules are decoration.
    const { render } = await import('@testing-library/react');
    const { Surface3D } = await import('../hub/VizMarks');

    const xs = [1, 2, 3, 4, 5];
    const ys = [1, 2, 3, 4];
    const { container } = render(<Surface3D grid={{ xs, ys, z: ys.map(() => xs.map((x) => x * 2)) }} />);

    expect(container.querySelector('[data-surface3d="drawn"]')).toBeNull();
    expect(container.querySelector('[data-surface3d="refused"]')!.textContent).toMatch(/table/i);
  });

  it('writes "no data" in the table where a quote is missing', async () => {
    // Not an empty cell, which reads as a formatting accident rather than as
    // an absent market.
    const { render } = await import('@testing-library/react');
    const { SurfaceTable } = await import('../hub/VizMarks');

    const grid = volSurface();
    const z = grid.z.map((row) => [...row]);
    z[1]![2] = null;
    const { container } = render(<SurfaceTable grid={{ ...grid, z }} />);
    expect(container.textContent).toContain('no data');
  });
});
