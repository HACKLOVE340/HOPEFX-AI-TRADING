/**
 * hub/head.ts — the presence's face, and where it is looking.
 *
 * §7: "a professional holographic head as the default presence", "lip
 * synchronisation where the voice pipeline supports it", "a particle field,
 * used with restraint", "move toward the panel being discussed", "pointing,
 * highlighting and gesture overlays".
 *
 * Pure. Takes numbers, returns numbers; `PresenceCore` draws them. Every rule
 * below — what the mouth does when nobody is measuring, how many particles a
 * quiet system gets, where the head looks when the target has no rect — is
 * testable without a canvas.
 *
 * ## Lip sync is to the text, at the resolution the engine reports
 *
 * The tempting implementation is a sine wave: the mouth flaps while `speaking`
 * is true and stops when it is false. It looks approximately right and it is
 * telling you nothing — the same animation plays for "yes" and for a
 * four-hundred-word briefing, and it keeps playing when synthesis has silently
 * died.
 *
 * `speechProgress` is a real character index from the synthesis engine (or a
 * playback position from the audio element). So the mouth is driven by **the
 * character actually being spoken**: open vowels wide, closed vowels less,
 * consonants nearly shut, spaces closed. That is not phoneme-accurate — it is
 * graphemes, and English spelling is not phonetic — but it is derived from the
 * utterance rather than invented, it stops when synthesis stops, and a long
 * sentence looks different from a short one because it is.
 *
 * When progress is unmeasured the mouth **holds a steady speaking shape** and
 * `measured` is false. Half-open and still is honest; a waveform driven by
 * `Date.now()` is a claim about an audio signal nobody has looked at.
 */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Mouth {
  /** 0 shut, 1 wide. */
  openness: number;
  /**
   * True when the shape follows the utterance. False means "speaking, but
   * nothing measured the progress" — the caller must not present the resulting
   * animation as lip sync.
   */
  measured: boolean;
}

/** Wide open. */
const OPEN_VOWELS = new Set(['a', 'o']);
/** Open, but less. */
const MID_VOWELS = new Set(['e', 'i', 'u', 'y']);
/** Lips together — these read wrong if the mouth is open on them. */
const CLOSED_CONSONANTS = new Set(['m', 'b', 'p']);

/** The steady shape used while speaking with no measurement. */
const UNMEASURED_OPENNESS = 0.42;

export function mouthFor(utterance: string, progress: number | null, speaking: boolean): Mouth {
  if (!speaking) return { openness: 0, measured: false };

  const text = utterance ?? '';
  if (progress === null || !Number.isFinite(progress) || text.length === 0) {
    return { openness: UNMEASURED_OPENNESS, measured: false };
  }

  const index = Math.max(0, Math.min(text.length - 1, Math.floor(progress * text.length)));
  const ch = text[index]?.toLowerCase() ?? ' ';

  if (ch === ' ' || ch === '\n') return { openness: 0.05, measured: true };
  if (/[.,!?;:]/.test(ch)) return { openness: 0, measured: true };
  if (OPEN_VOWELS.has(ch)) return { openness: 1, measured: true };
  if (MID_VOWELS.has(ch)) return { openness: 0.62, measured: true };
  if (CLOSED_CONSONANTS.has(ch)) return { openness: 0.04, measured: true };
  if (/[a-z0-9]/.test(ch)) return { openness: 0.24, measured: true };
  return { openness: 0.12, measured: true };
}

// ── the particle field, used with restraint (§7) ──────────────────────────────

export interface Particle {
  /** -1..1, relative to the core's centre. */
  x: number;
  y: number;
  /** 0..1. */
  alpha: number;
  radius: number;
}

/**
 * §7's own words are "used with restraint", so restraint is enforced here
 * rather than left to the drawing code.
 *
 * - **None under reduced motion.** A field of drifting dots is exactly the
 *   thing that setting exists to stop.
 * - **None when offline.** Particles read as activity, and there is none — the
 *   same reason the outer ring stops dead rather than spinning prettily over a
 *   dead socket (§22: no decorative "live" values).
 * - **Few when quiet.** The count tracks measured intensity, so a busy system
 *   looks busy and an idle one looks idle instead of both looking impressive.
 *
 * Deterministic in `t`: same time, same field. A random field cannot be tested
 * and flickers between frames on a slow device.
 */
const MAX_PARTICLES = 28;

export function particleField(
  t: number,
  options: { intensity: number; reducedMotion: boolean; offline: boolean },
): Particle[] {
  if (options.reducedMotion || options.offline) return [];
  const intensity = Math.max(0, Math.min(1, options.intensity));
  const count = Math.round(MAX_PARTICLES * intensity);
  if (count === 0) return [];

  const out: Particle[] = [];
  for (let i = 0; i < count; i += 1) {
    // Golden-angle placement so the field never bands into visible spokes.
    const angle = i * 2.39996 + t * 0.00018 * (0.4 + intensity);
    const radius = 0.52 + ((i * 37) % 100) / 100 * 0.42;
    const drift = Math.sin(t * 0.0009 + i) * 0.02;
    out.push({
      x: Math.cos(angle) * (radius + drift),
      y: Math.sin(angle) * (radius + drift),
      alpha: 0.12 + (((i * 53) % 100) / 100) * 0.28 * (0.4 + intensity),
      radius: 0.8 + (((i * 29) % 100) / 100) * 1.4,
    });
  }
  return out;
}

// ── looking at, and pointing to, the panel being discussed (§7) ───────────────

export interface Gaze {
  /** -1..1 from the core's centre. Zero is facing the viewer. */
  x: number;
  y: number;
  /** Distance to the target as a fraction of the core's own size, for a lean. */
  reach: number;
}

/**
 * Where to look. Null when either rect was never measured.
 *
 * Null is not "straight ahead" — the caller draws a forward-facing head and
 * makes no pointing gesture at all, rather than pointing confidently at the
 * origin. A presence that gestures at the top-left corner because a rect was
 * zero is worse than one that does not gesture.
 */
export function gazeToward(core: Rect | null, target: Rect | null): Gaze | null {
  if (!core || !target) return null;
  if (core.width <= 0 || core.height <= 0) return null;
  if (target.width <= 0 || target.height <= 0) return null;

  const cx = core.x + core.width / 2;
  const cy = core.y + core.height / 2;
  const tx = target.x + target.width / 2;
  const ty = target.y + target.height / 2;

  const dx = tx - cx;
  const dy = ty - cy;
  const distance = Math.hypot(dx, dy);
  if (distance === 0) return { x: 0, y: 0, reach: 0 };

  // Normalised by the core's own radius, so "how far" is expressed in units of
  // the presence rather than in pixels the drawing code would have to rescale.
  const span = Math.max(core.width, core.height) / 2;
  return {
    x: Math.max(-1, Math.min(1, dx / (span * 3))),
    y: Math.max(-1, Math.min(1, dy / (span * 3))),
    reach: Math.max(0, Math.min(1, distance / (span * 6))),
  };
}

/**
 * How far the head physically shifts, in pixels, for a given gaze.
 *
 * Small on purpose. §7 asks the presence to "move toward the panel being
 * discussed"; a presence that slides across the screen to do it takes the
 * operator's eyes off the panel it is trying to draw them to, which is the
 * opposite of the point. Zero under reduced motion.
 */
export function headOffset(gaze: Gaze | null, size: number, reducedMotion: boolean): { x: number; y: number } {
  if (!gaze || reducedMotion) return { x: 0, y: 0 };
  const limit = size * 0.06;
  return { x: gaze.x * limit, y: gaze.y * limit };
}

// ── the skull: a head with volume, that turns and articulates (§7) ────────────

/**
 * What was here before was an ellipse, two dots and a second ellipse for a
 * mouth. It faced forward always, because an outline has no orientation:
 * `gazeToward` measured where to look and `headOffset` slid the whole drawing a
 * few pixels toward it, which is the most a flat shape can do.
 *
 * `headMesh` builds the head as geometry — a wireframe skull sampled on
 * latitude rings and meridians, rotated by yaw and pitch, projected with a mild
 * perspective divide so the near side is larger, and split at the mandible so
 * the jaw hinges open with the measured mouth openness.
 *
 * ## Still not a mascot
 *
 * §7 asks for "professional". A rendered human face on a platform that places
 * orders reads as a character; a wireframe skull reads as an instrument, which
 * is what this is. The silhouette comes from a profile table rather than a
 * circle, so it has cheekbones and a chin and could not be mistaken for a ball,
 * but nothing here draws skin, hair or an expression the data did not supply.
 *
 * ## Nothing here animates from a clock except the scan ring
 *
 * The jaw is driven by `mouthOpenness`, which comes from `mouthFor`, which
 * comes from the character the engine reports it is speaking. The head's
 * orientation comes from `gazeToward`, which comes from a measured rect. The
 * one thing a clock may move is the scan ring, and it carries no information,
 * which is why it is the one thing reduced motion removes.
 */

/** Half-height of the head, in units of `radius`. */
const HEAD_HEIGHT = 1.3;
/** Front-to-back depth, in units of `radius`. A head is deeper than it is wide. */
const HEAD_DEPTH = 1.18;
/** How far the skull's mass sits behind the origin, so it rotates about itself. */
const BACKSET = 0.12;
/** Perspective focal length, in units of `radius`. Large enough to be a cue, not a fisheye. */
const FOCAL = 5;

/** Latitude of the jaw hinge. Everything below this is the mandible. */
const JAW_V = -0.16;
/** How far the jaw swings at full openness, in radians (~19 degrees). */
const MAX_JAW = 0.34;
/** Where the hinge sits, front-to-back, in units of `radius`. */
const JAW_HINGE_Z = -0.55;

/** Latitude and longitude of an eye on the face. */
const EYE_V = 0.14;
const EYE_U = 0.44;

/** How far the brow arc reaches either side of the eye, in radians of longitude. */
const BROW_SPAN = 0.26;
/** How far above the eye the brow sits at rest, in latitude. */
const BROW_LIFT = 0.12;
/** How far a full raise or a full frown moves it. */
const BROW_TRAVEL = 0.07;

/** How far the mouth reaches either side of the face's centre line, in radians. */
const MOUTH_SPAN = 0.42;

const RINGS = [0.92, 0.78, 0.62, 0.44, 0.24, 0.04, -0.16, -0.38, -0.6, -0.8] as const;
const MERIDIANS = 10;
const ARC_STEPS = 16;
const MERIDIAN_STEPS = 18;

/** How long the scan ring takes to travel the head and back, in milliseconds. */
const SCAN_PERIOD = 2600;

/**
 * The silhouette, as a table rather than a formula.
 *
 * A circle is widest exactly halfway between its poles. A head is widest above
 * that, at the cheekbones, and tapers to a chin — which no single closed-form
 * curve gives you without fitting constants that then mean nothing. Reading it
 * off a table keeps the shape legible and lets it be adjusted by looking at it.
 */
const PROFILE: readonly (readonly [number, number])[] = [
  [1.0, 0.0],
  [0.92, 0.42],
  [0.8, 0.68],
  [0.62, 0.86],
  [0.4, 0.96],
  [0.18, 1.0],
  [0.0, 0.98],
  [-0.2, 0.92],
  [-0.42, 0.8],
  [-0.62, 0.64],
  [-0.82, 0.42],
  [-1.0, 0.0],
];

/** Half-width of the head at latitude `v`, in units of `radius`. */
export function headWidthAt(v: number): number {
  const t = Math.max(-1, Math.min(1, v));
  for (let i = 0; i < PROFILE.length - 1; i += 1) {
    const [v0, w0] = PROFILE[i]!;
    const [v1, w1] = PROFILE[i + 1]!;
    if (t <= v0 && t >= v1) {
      const span = v0 - v1;
      const k = span === 0 ? 0 : (v0 - t) / span;
      return w0 + (w1 - w0) * k;
    }
  }
  return 0;
}

export interface Projected {
  x: number;
  y: number;
}

export interface Strand {
  points: Projected[];
  /** Mean depth, -1 (behind) to 1 (toward the viewer). The drawing dims by it. */
  depth: number;
}

export interface MeshEye {
  x: number;
  y: number;
  /** -1 (behind) to 1 (toward the viewer). */
  z: number;
  radius: number;
  /** The pupil, inside the eye. Dilated or contracted by the mode. */
  pupilRadius: number;
  /**
   * 0 shut, 1 open. The drawing squashes the eye's height by this rather than
   * scaling it: a shut eye is a line across the socket, whereas an eye that
   * shrank to a dot would read as a pupil contracting, which means something
   * else entirely.
   */
  openness: number;
}

export interface HeadMesh {
  /** The cranium and the face. Never moved by the jaw. */
  shell: Strand[];
  /** The mandible. Hinges with `mouthOpenness`. */
  jaw: Strand[];
  eyes: MeshEye[];
  /** Two arcs above the eyes. Angle and height come from `brow`. */
  brows: Strand[];
  /**
   * The lip line, in halves.
   *
   * The jaw hinging is not visible on its own — a wireframe skull with an
   * articulating mandible and no lip line is a talking head you cannot see
   * talk, which is what the ellipse-and-dots head at least got right. The
   * upper lip rides the shell and the lower rides the mandible, so the two
   * meet when shut and part by exactly as much as the jaw has swung.
   */
  mouth: { upper: Strand; lower: Strand };
  /** The travelling scan ring, or null under reduced motion. */
  scan: Strand | null;
  /** 0 (profile) to 1 (facing the viewer). */
  facing: number;
}

export interface HeadMeshOptions {
  /** Half the head's width, in pixels. */
  radius: number;
  /** Radians. Positive turns the face toward the viewer's right. */
  yaw: number;
  /** Radians. Positive tips the chin down. */
  pitch: number;
  /** 0 shut, 1 wide. From `mouthFor`. */
  mouthOpenness: number;
  /** Milliseconds. Moves the scan ring and nothing else. */
  time: number;
  reducedMotion: boolean;
  /**
   * The face the brain chose — see `hub/headModes.ts`. All optional, and all
   * defaulting to a level, open-eyed, neutral head, because every caller that
   * existed before modes did passes none of them.
   */
  /** Roll in radians. A tilt reads as "I am not certain". */
  roll?: number;
  /** 0 shut, 1 open. */
  lidOpen?: number;
  /** -1 drawn in and down, 0 neutral, +1 raised. */
  brow?: number;
  /** Pupil scale. Around 1 is resting; wide when alarmed, narrow when concentrating. */
  pupil?: number;
}

/** A point in the head's own space, before rotation. */
function modelPoint(u: number, v: number, radius: number): [number, number, number] {
  const w = headWidthAt(v);
  return [
    w * Math.sin(u) * radius,
    -v * HEAD_HEIGHT * radius,
    (w * Math.cos(u) * HEAD_DEPTH - BACKSET) * radius,
  ];
}

/**
 * Swing a point with the mandible.
 *
 * A rotation about the hinge axis, not a translation: a jaw that slid downward
 * would separate from the skull and leave a gap at the ear. The chin therefore
 * moves down AND back, which is what a jaw does.
 */
function hinge(
  p: [number, number, number],
  angle: number,
  radius: number,
): [number, number, number] {
  if (angle === 0) return p;
  const yHinge = -JAW_V * HEAD_HEIGHT * radius;
  const zHinge = JAW_HINGE_Z * radius;
  const dy = p[1] - yHinge;
  const dz = p[2] - zHinge;
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return [p[0], yHinge + dy * c + dz * s, zHinge - dy * s + dz * c];
}

/**
 * Yaw about the vertical axis, then pitch about the horizontal one, then roll
 * about the line of sight.
 *
 * Roll is last so a tilt is a tilt of the head as it is currently turned,
 * rather than a tilt of the model that the turn then swings somewhere else.
 */
function orient(
  p: [number, number, number],
  yaw: number,
  pitch: number,
  roll: number,
): [number, number, number] {
  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);
  const x1 = p[0] * cy + p[2] * sy;
  const z1 = -p[0] * sy + p[2] * cy;
  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);
  const y2 = p[1] * cp - z1 * sp;
  const z2 = p[1] * sp + z1 * cp;
  if (roll === 0) return [x1, y2, z2];
  const cr = Math.cos(roll);
  const sr = Math.sin(roll);
  return [x1 * cr - y2 * sr, x1 * sr + y2 * cr, z2];
}

/** Orthographic with a mild divide — enough that the near side reads as nearer. */
function project(p: [number, number, number], radius: number): { x: number; y: number; depth: number } {
  const focal = FOCAL * radius;
  const k = focal / Math.max(focal * 0.35, focal - p[2]);
  return {
    x: p[0] * k,
    y: p[1] * k,
    depth: Math.max(-1, Math.min(1, p[2] / (HEAD_DEPTH * radius))),
  };
}

function strandFrom(
  samples: readonly [number, number][],
  o: HeadMeshOptions,
  jawAngle: number,
): Strand {
  const points: Projected[] = [];
  let depthSum = 0;
  for (const [u, v] of samples) {
    let p = modelPoint(u, v, o.radius);
    if (v < JAW_V) p = hinge(p, jawAngle, o.radius);
    const q = project(orient(p, o.yaw, o.pitch, o.roll ?? 0), o.radius);
    points.push({ x: q.x, y: q.y });
    depthSum += q.depth;
  }
  return { points, depth: samples.length === 0 ? 0 : depthSum / samples.length };
}

export function headMesh(options: HeadMeshOptions): HeadMesh {
  const o = options;
  const openness = Math.max(0, Math.min(1, o.mouthOpenness));
  const jawAngle = openness * MAX_JAW;

  const shell: Strand[] = [];
  const jaw: Strand[] = [];

  // Latitude rings, each cut into a front arc and a back arc.
  //
  // A whole ring would average to one depth for every latitude, so the back of
  // the skull would be drawn exactly as brightly as the face and the mesh would
  // read as a tangle. Cut in two, the front arc is in front and the back arc is
  // behind, and the drawing has something to dim.
  for (const v of RINGS) {
    for (const half of [0, 1] as const) {
      const samples: [number, number][] = [];
      for (let i = 0; i <= ARC_STEPS; i += 1) {
        const u = -Math.PI / 2 + (i / ARC_STEPS) * Math.PI + half * Math.PI;
        samples.push([u, v]);
      }
      (v < JAW_V ? jaw : shell).push(strandFrom(samples, o, jawAngle));
    }
  }

  // Meridians, crown to chin, split at the jaw line so the mandible can move
  // without dragging the cheek down with it.
  for (let m = 0; m < MERIDIANS; m += 1) {
    const u = (m / MERIDIANS) * Math.PI * 2;
    const upper: [number, number][] = [];
    const lower: [number, number][] = [];
    for (let i = 0; i <= MERIDIAN_STEPS; i += 1) {
      const v = 1 - (i / MERIDIAN_STEPS) * 2;
      (v < JAW_V ? lower : upper).push([u, v]);
    }
    // The hinge latitude itself belongs to both, so the two halves meet.
    if (upper.length > 0 && lower.length > 0) lower.unshift([u, JAW_V]);
    if (upper.length > 1) shell.push(strandFrom(upper, o, jawAngle));
    if (lower.length > 1) jaw.push(strandFrom(lower, o, jawAngle));
  }

  const roll = o.roll ?? 0;
  const lidOpen = Math.max(0, Math.min(1, o.lidOpen ?? 1));
  const brow = Math.max(-1, Math.min(1, o.brow ?? 0));
  const pupil = Math.max(0.1, o.pupil ?? 1);

  const eyes: MeshEye[] = [-1, 1].map((side) => {
    const q = project(orient(modelPoint(side * EYE_U, EYE_V, o.radius), o.yaw, o.pitch, roll), o.radius);
    const radius = o.radius * 0.1;
    return {
      x: q.x,
      y: q.y,
      z: q.depth,
      radius,
      // Clamped inside the eye whatever the caller asks for: a pupil the size
      // of its socket is a black dot, not a dilation.
      pupilRadius: radius * Math.max(0.2, Math.min(0.72, 0.42 * pupil)),
      openness: lidOpen,
    };
  });

  // The brows. An arc across the socket, lifted or drawn in by `brow` — the
  // one part of the face that carries the reading rather than the speech, which
  // is why reduced motion keeps it and removes the scan.
  const brows: Strand[] = [-1, 1].map((side) => {
    const samples: [number, number][] = [];
    for (let i = 0; i <= 6; i += 1) {
      const across = (i / 6) * 2 - 1;
      const u = side * EYE_U + across * BROW_SPAN * side;
      // Raised lifts the whole arc; drawn in lowers the inner end further than
      // the outer one, which is what makes a worried brow read as worried
      // rather than merely low.
      const inner = side * across < 0 ? 1 : 0;
      const v = EYE_V + BROW_LIFT + brow * BROW_TRAVEL - inner * Math.max(0, -brow) * BROW_TRAVEL * 0.6;
      samples.push([u, v]);
    }
    return strandFrom(samples, o, 0);
  });

  // The lip line. Both halves are sampled at the SAME latitude and longitudes;
  // the only difference is that the lower one is swung with the mandible. So
  // "shut" is not a tuned constant, it is the two halves being the same points.
  const lipSamples: [number, number][] = [];
  for (let i = 0; i <= 10; i += 1) {
    lipSamples.push([-MOUTH_SPAN + (i / 10) * MOUTH_SPAN * 2, JAW_V]);
  }
  const mouth = {
    upper: strandFrom(lipSamples, o, 0),
    lower: strandFrom(lipSamples.map(([u, v]) => [u, v - 1e-9] as [number, number]), o, jawAngle),
  };

  // The scan ring: a real latitude ring at the height the sweep has reached, so
  // it follows the skull's width instead of ruling a straight line across it.
  let scan: Strand | null = null;
  if (!o.reducedMotion) {
    const phase = ((o.time % SCAN_PERIOD) + SCAN_PERIOD) % SCAN_PERIOD / SCAN_PERIOD;
    const sweep = 1 - 2 * Math.abs(phase - 0.5);
    const v = -0.9 + sweep * 1.8;
    const samples: [number, number][] = [];
    for (let i = 0; i <= ARC_STEPS * 2; i += 1) {
      samples.push([(i / (ARC_STEPS * 2)) * Math.PI * 2, v]);
    }
    scan = strandFrom(samples, o, jawAngle);
  }

  return {
    shell,
    jaw,
    eyes,
    brows,
    mouth,
    scan,
    facing: Math.max(0, Math.min(1, Math.cos(o.yaw) * Math.cos(o.pitch))),
  };
}
