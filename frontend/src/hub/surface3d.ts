/**
 * hub/surface3d.ts — §21's last row: 3D **where it aids understanding**.
 *
 * The note said "only canvas2d is implemented", which describes what exists
 * rather than naming a blocker. Two things were confused in it, and separating
 * them is most of this module:
 *
 * **3D is not WebGL.** A mesh projected onto a 2D context is real 3D — the
 * dimension is in the data and in the projection, not in the API that rasterises
 * the triangles. WebGL is an ACCELERATION path. It stays honestly unavailable in
 * `projection.ts` because no GPU-backed context has been proven here, and that
 * no longer holds the capability hostage.
 *
 * ## "Where they aid understanding" is a constraint, not a licence
 *
 * That clause is in the spec and this module enforces it. `warrants3D` REFUSES
 * more often than it accepts, because on a trading screen the failure modes of a
 * gratuitous third dimension are not cosmetic:
 *
 * * **occlusion** — a peak hides the trough behind it, and the hidden value is
 *   the one somebody needed;
 * * **foreshortening** — two bars of equal height read as different because one
 *   is further away, so the chart misstates magnitude;
 * * **no shared baseline** — comparing heights across a receding plane is a
 *   task humans do badly and confidently.
 *
 * A 2D heatmap of the same grid has none of those, so 3D has to earn the swap.
 * It earns it for a genuine z = f(x, y) over two ORDERED, densely-sampled axes,
 * where the shape between the samples is the information: a volatility surface
 * across strike and expiry, a term structure through time. It does not earn it
 * for a bar chart with a category axis pushed into depth.
 *
 * ## A hole is never interpolated
 *
 * The rule this module exists for. A volatility surface with no quote at a
 * strike has a HOLE, and a mesh drawn straight across it renders a smooth
 * surface where there is no market — a price somebody could trade against that
 * nobody ever quoted. `validateGrid` finds holes and `meshFaces` omits every
 * face touching one, so a gap in the data is a gap in the picture.
 *
 * That is the same rule `trackFromHands` holds for a lost camera frame and
 * `sceneFrom` holds for containment: absent is absent, never inferred.
 */

export interface SurfaceGrid {
  /** Ordered x samples — strikes, tenors. Ascending, and checked. */
  xs: readonly number[];
  /** Ordered y samples. Ascending, and checked. */
  ys: readonly number[];
  /** `z[yIndex][xIndex]`. `null` is a hole and stays one. */
  z: readonly (readonly (number | null)[])[];
  xLabel?: string;
  yLabel?: string;
  zLabel?: string;
}

export interface GridProblem {
  kind: 'ragged' | 'unordered' | 'non_finite' | 'too_small';
  detail: string;
}

/** Below this a surface is a handful of points and a table reads better. */
export const MIN_SAMPLES_PER_AXIS = 4;

/**
 * Everything wrong with a grid, or an empty list.
 *
 * Returns ALL the problems rather than the first: a caller that fixed one and
 * came back for the next would be told about a two-line defect three times.
 */
export function validateGrid(grid: SurfaceGrid): GridProblem[] {
  const problems: GridProblem[] = [];
  const { xs, ys, z } = grid;

  if (xs.length < MIN_SAMPLES_PER_AXIS || ys.length < MIN_SAMPLES_PER_AXIS) {
    problems.push({
      kind: 'too_small',
      detail: `a surface needs at least ${MIN_SAMPLES_PER_AXIS} samples on each axis; this has ${xs.length} by ${ys.length}`,
    });
  }

  if (z.length !== ys.length || z.some((row) => row.length !== xs.length)) {
    problems.push({
      kind: 'ragged',
      detail: `the z grid is not ${ys.length} rows of ${xs.length}, so some cell has no coordinates`,
    });
  }

  for (const [name, axis] of [
    ['x', xs],
    ['y', ys],
  ] as const) {
    if (axis.some((v) => !Number.isFinite(v))) {
      problems.push({ kind: 'non_finite', detail: `the ${name} axis contains a value that is not a number` });
      continue;
    }
    // Strictly ascending. A repeated sample means two different z values sit at
    // one coordinate, and the mesh silently keeps whichever it drew last.
    for (let i = 1; i < axis.length; i += 1) {
      if (axis[i]! <= axis[i - 1]!) {
        problems.push({
          kind: 'unordered',
          detail: `the ${name} axis is not strictly ascending at index ${i}`,
        });
        break;
      }
    }
  }

  // A z that is NaN or Infinity is not a hole — a hole is null, and says so.
  // NaN is a computation that went wrong and must not read as "no quote".
  if (z.some((row) => row.some((v) => v !== null && !Number.isFinite(v)))) {
    problems.push({
      kind: 'non_finite',
      detail: 'a z value is not a number and is not null; a missing sample must be null, so that a ' +
        'failed calculation is not read as an absent quote',
    });
  }

  return problems;
}

/** Coordinates with no z value. Holes are data, not errors. */
export function holes(grid: SurfaceGrid): { x: number; y: number }[] {
  const out: { x: number; y: number }[] = [];
  grid.z.forEach((row, yi) => {
    row.forEach((value, xi) => {
      if (value === null) {
        const x = grid.xs[xi];
        const y = grid.ys[yi];
        if (x !== undefined && y !== undefined) out.push({ x, y });
      }
    });
  });
  return out;
}

export interface Verdict {
  warranted: boolean;
  /** Always populated, including when warranted: the panel says why. */
  reason: string;
}

/**
 * Whether this data is better as a surface than as a heatmap.
 *
 * Biased towards NO. A 2D heatmap of the same grid has no occlusion, no
 * foreshortening and a shared baseline, so the third dimension has to buy
 * something to be worth those three costs.
 */
export function warrants3D(grid: SurfaceGrid): Verdict {
  const problems = validateGrid(grid);
  if (problems.length > 0) {
    return {
      warranted: false,
      reason: `this is not a well-formed surface — ${problems[0]!.detail}`,
    };
  }

  const total = grid.xs.length * grid.ys.length;
  const missing = holes(grid).length;
  const coverage = total === 0 ? 0 : (total - missing) / total;

  // A sparse grid drawn as a surface is mostly invention. The threshold is not
  // a tuned number: below three quarters, more than one cell in four of the
  // shape a reader sees is a face that was omitted or a gap they must infer.
  if (coverage < 0.75) {
    return {
      warranted: false,
      reason: `only ${Math.round(coverage * 100)}% of this grid has values, so a surface would be ` +
        'mostly gaps; the table shows what is actually there',
    };
  }

  // The shape has to vary in BOTH directions. A grid whose rows are all the
  // same is a line repeated, and its third dimension is decoration — the exact
  // thing the spec's "where they aid understanding" excludes.
  if (!variesAlong(grid, 'x') || !variesAlong(grid, 'y')) {
    return {
      warranted: false,
      reason: 'this changes in only one direction, so it is a line and a chart shows it without ' +
        'the occlusion a surface would add',
    };
  }

  return {
    warranted: true,
    reason: `${grid.xs.length} by ${grid.ys.length} samples varying in both directions: the shape ` +
      'between them is the information, which is what a surface shows and a table does not',
  };
}

/** Whether z actually changes along an axis, beyond floating-point noise. */
function variesAlong(grid: SurfaceGrid, axis: 'x' | 'y'): boolean {
  const values: number[][] = [];
  if (axis === 'x') {
    for (let xi = 0; xi < grid.xs.length; xi += 1) {
      values.push(grid.z.map((row) => row[xi]).filter((v): v is number => v !== null && v !== undefined));
    }
  } else {
    for (const row of grid.z) values.push(row.filter((v): v is number => v !== null));
  }
  const means = values.filter((v) => v.length > 0).map((v) => v.reduce((a, b) => a + b, 0) / v.length);
  if (means.length < 2) return false;
  const spread = Math.max(...means) - Math.min(...means);
  const scale = Math.max(...means.map(Math.abs), 1);
  return spread / scale > 1e-9;
}

// ── projection ────────────────────────────────────────────────────────────────

export interface Point3 {
  x: number;
  y: number;
  z: number;
}

export interface Point2 {
  x: number;
  y: number;
  /** Distance from the camera. Kept so faces can be drawn back to front. */
  depth: number;
}

export interface Camera {
  /** Rotation about the vertical axis, radians. */
  yaw: number;
  /** Tilt, radians. Clamped, because past vertical the surface reads inside out. */
  pitch: number;
  /** Pixels per unit at depth zero. */
  scale: number;
  centre: { x: number; y: number };
}

export const DEFAULT_CAMERA: Camera = {
  // Not axis-aligned. Straight on, every row hides the one behind it exactly,
  // which is the worst possible angle for the thing a surface is for.
  yaw: Math.PI / 5,
  pitch: Math.PI / 7,
  scale: 1,
  centre: { x: 0, y: 0 },
};

export const MAX_PITCH = Math.PI / 2 - 0.01;

/**
 * Project a point in grid space onto the screen.
 *
 * ORTHOGRAPHIC, deliberately. A perspective projection makes two equal values
 * render at different heights depending on where they sit, and on a screen
 * where the z axis is a price that is a chart that misstates its own numbers.
 * Perspective is for photographs; measurement wants parallel projection.
 */
export function project(point: Point3, camera: Camera): Point2 {
  const pitch = Math.max(-MAX_PITCH, Math.min(MAX_PITCH, camera.pitch));
  const cosYaw = Math.cos(camera.yaw);
  const sinYaw = Math.sin(camera.yaw);
  const cosPitch = Math.cos(pitch);
  const sinPitch = Math.sin(pitch);

  const rx = point.x * cosYaw - point.y * sinYaw;
  const ry = point.x * sinYaw + point.y * cosYaw;

  return {
    x: camera.centre.x + rx * camera.scale,
    // Screen y grows downward, so a larger z must move UP.
    y: camera.centre.y + (ry * sinPitch - point.z * cosPitch) * camera.scale,
    depth: ry * cosPitch + point.z * sinPitch,
  };
}

export interface Face {
  /** The four corners, already projected. */
  corners: readonly Point2[];
  /** Mean z of the corners, for colouring. */
  value: number;
  /** Mean depth, for painter's ordering. */
  depth: number;
}

export interface MeshOptions {
  camera?: Camera;
  /** Normalise the axes into a unit box so aspect does not depend on units. */
  normalise?: boolean;
}

/**
 * The quads of the mesh, ordered back to front.
 *
 * **Every face touching a hole is omitted.** A face drawn across a missing
 * sample is a surface where there is no market — on a volatility grid, a price
 * a reader could act on that nobody ever quoted. Omitting it leaves a visible
 * gap, which is the truth.
 *
 * Sorted back to front so a 2D context can paint them without a depth buffer.
 * That is the whole reason this needs no GPU.
 */
export function meshFaces(grid: SurfaceGrid, options: MeshOptions = {}): Face[] {
  if (validateGrid(grid).length > 0) return [];
  const camera = options.camera ?? DEFAULT_CAMERA;
  const normalise = options.normalise ?? true;

  const flat = grid.z.flat().filter((v): v is number => v !== null);
  if (flat.length === 0) return [];
  const zMin = Math.min(...flat);
  const zMax = Math.max(...flat);
  const zSpan = zMax - zMin || 1;

  const xs = grid.xs;
  const ys = grid.ys;
  const xSpan = (xs[xs.length - 1]! - xs[0]!) || 1;
  const ySpan = (ys[ys.length - 1]! - ys[0]!) || 1;

  const at = (xi: number, yi: number): Point3 | null => {
    const value = grid.z[yi]?.[xi];
    if (value === null || value === undefined) return null;
    return normalise
      ? {
          x: (xs[xi]! - xs[0]!) / xSpan - 0.5,
          y: (ys[yi]! - ys[0]!) / ySpan - 0.5,
          z: (value - zMin) / zSpan - 0.5,
        }
      : { x: xs[xi]!, y: ys[yi]!, z: value };
  };

  const faces: Face[] = [];
  for (let yi = 0; yi < ys.length - 1; yi += 1) {
    for (let xi = 0; xi < xs.length - 1; xi += 1) {
      const corners3 = [at(xi, yi), at(xi + 1, yi), at(xi + 1, yi + 1), at(xi, yi + 1)];
      // One missing corner drops the whole quad. See the docstring: a face
      // spanning a hole is a claim about a value nobody supplied.
      if (corners3.some((c) => c === null)) continue;

      const corners = corners3.map((c) => project(c!, camera));
      const raw = [grid.z[yi]![xi]!, grid.z[yi]![xi + 1]!, grid.z[yi + 1]![xi + 1]!, grid.z[yi + 1]![xi]!];
      faces.push({
        corners,
        value: raw.reduce((a, b) => a + b, 0) / raw.length,
        depth: corners.reduce((a, c) => a + c.depth, 0) / corners.length,
      });
    }
  }

  // Painter's algorithm: furthest first, so nearer faces overwrite them.
  return faces.sort((a, b) => a.depth - b.depth);
}

/** How many faces a complete grid would have, for reporting what was dropped. */
export function expectedFaceCount(grid: SurfaceGrid): number {
  return Math.max(0, grid.xs.length - 1) * Math.max(0, grid.ys.length - 1);
}

/**
 * What the panel says out loud, and what a screen reader gets.
 *
 * Names the dropped faces, because a reader looking at a surface with a bite
 * out of it must be told the bite is missing data rather than a shape.
 */
export function describeSurface(grid: SurfaceGrid, faces: readonly Face[]): string {
  const verdict = warrants3D(grid);
  if (!verdict.warranted) return `Shown as a table: ${verdict.reason}.`;
  const dropped = expectedFaceCount(grid) - faces.length;
  const axes = `${grid.zLabel ?? 'value'} across ${grid.xLabel ?? 'x'} and ${grid.yLabel ?? 'y'}`;
  if (dropped > 0) {
    return `A surface of ${axes}. ${dropped} of ${expectedFaceCount(grid)} patches are left out where there is no data.`;
  }
  return `A surface of ${axes}, complete across all ${expectedFaceCount(grid)} patches.`;
}
