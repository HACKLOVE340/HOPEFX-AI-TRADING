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
const HEAD_HEIGHT = 1.44;
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

/**
 * How far the mandible also TRANSLATES down at full opening, in units of
 * `radius`.
 *
 * Not a fudge — it is what a jaw does. Past a small angle the condyle leaves
 * the mandibular fossa and slides down and forward; a mouth that opened by
 * rotation alone would reach about 20mm on a real skull and a shout needs 50.
 *
 * It is also what makes the opening VISIBLE here, and the taller head is what
 * exposed that. A pure hinge moves a chin that is 1.44 radii below the pivot
 * mostly BACKWARD: at the full 19-degree swing it dropped the chin 5% and
 * retreated it 28%, and the perspective divide then shrank the retreating chin
 * by more than the swing had lowered it — so `mouthOpenness` 1 drew a chin
 * marginally HIGHER on screen than `mouthOpenness` 0. Caught by
 * `drops the chin as the mouth opens`, which is exactly the assertion that
 * would otherwise have been quietly relaxed to make a re-proportioned head
 * pass.
 */
const JAW_DROP = 0.18;

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
const MOUTH_SPAN = 0.32;

/**
 * The neck, as latitude-like slices below the chin.
 *
 * Each row is [how far below the head's bottom, half-width, front-back depth],
 * all in units of `radius`. It narrows at the throat and spreads into
 * shoulders, because a column at head width is not a neck.
 */
const NECK: readonly (readonly [number, number, number])[] = [
  [-0.04, 0.42, 0.4],
  [0.1, 0.39, 0.37],
  [0.26, 0.42, 0.4],
  [0.42, 0.55, 0.46],
  [0.56, 0.78, 0.52],
];
const NECK_STEPS = 26;

/**
 * The horizontal contours.
 *
 * Close together on purpose: the reference head reads as a hologram because the
 * latitude lines are dense enough to describe a surface. Ten of them described
 * a cage. They are packed tighter across the face (v in -0.5..0.5) than over
 * the crown, because that is where the relief is and a contour with nothing to
 * follow is a line.
 */
const RINGS = [
  0.95, 0.88, 0.8, 0.71, 0.62, 0.53, 0.44, 0.35, 0.27, 0.19, 0.11, 0.03,
  -0.05, -0.13, -0.21, -0.3, -0.39, -0.48, -0.58, -0.68, -0.79, -0.89,
] as const;
const MERIDIANS = 16;
const ARC_STEPS = 22;
const MERIDIAN_STEPS = 30;

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
  // Rounded at both ends, not pointed and not flat.
  //
  // Closing to zero abruptly gave a teardrop — pinched crown, pointed chin —
  // and holding width to the last row gave a hard cap across the top of the
  // skull. Both were visible the moment the surface was shaded. The ends now
  // follow a circular falloff, which is what a cranium and a jaw actually do.
  [1.0, 0.0],
  [0.985, 0.21],
  [0.95, 0.4],
  [0.89, 0.57],
  [0.79, 0.73],
  [0.65, 0.85],
  [0.47, 0.92],
  [0.29, 0.96],
  [0.2, 0.97],
  [0.04, 0.96],
  [-0.14, 0.94],
  [-0.32, 0.9],
  [-0.48, 0.84],
  [-0.62, 0.75],
  [-0.74, 0.64],
  [-0.84, 0.51],
  [-0.92, 0.37],
  [-0.975, 0.21],
  [-1.0, 0.0],
];

/**
 * Facial relief: how far the surface moves along its own normal at (u, v).
 *
 * Positive is toward the viewer. This is what turns a head-shaped silhouette
 * into a face — straight on, a profile-only mesh is an egg with features
 * painted on it, because every point on it sits at the same radius.
 *
 * Deliberately anatomical rather than decorative. The nose is on the centre
 * line, the sockets are where the eyes are, the brow is above them, the chin is
 * under the mouth. Everything is multiplied by `FRONT`, a smooth window that
 * reaches zero behind the ears, so the cranium stays clean: relief on the back
 * of a skull reads as damage rather than as anatomy.
 *
 * Each feature is a product of two Gaussians — one across, one up — which is
 * what keeps this continuous. A rectangular region with a constant lift inside
 * it puts a visible crease down the face at its edge.
 *
 * ## Why not a mesh file
 *
 * A head is the obvious case for a loaded model, and it is the wrong answer
 * here. A .glb is bytes nobody can review in a diff, it needs a loader and a
 * renderer this canvas does not have, and the head has to respond to
 * measurements anyway — a jaw that hinges on the character being spoken, brows
 * that carry a risk reading — which means driving vertices at runtime either
 * way. Sixty lines of arithmetic every reviewer can check beats a binary
 * nobody can.
 */
function bump(x: number, centre: number, width: number): number {
  const d = (x - centre) / width;
  return Math.exp(-d * d);
}

export function faceRelief(u: number, v: number): number {
  // Wrap to -PI..PI so the caller can pass any longitude.
  let a = u;
  while (a > Math.PI) a -= Math.PI * 2;
  while (a < -Math.PI) a += Math.PI * 2;
  // Symmetric about the centre line: a face is, and computing from |u| means
  // the two halves cannot drift apart as the numbers below are tuned.
  const t = Math.abs(a);

  // The window. cos(u) at the front, floored at zero, cubed so it falls away by
  // the ears rather than lingering round the sides.
  const front = Math.max(0, Math.cos(t));
  const FRONT = front * front * front;
  if (FRONT <= 0) return 0;

  const nose =
    0.44 * bump(t, 0, 0.28) * bump(v, 0.02, 0.17) +
    // The tip, lower and narrower than the bridge.
    0.14 * bump(t, 0, 0.2) * bump(v, -0.1, 0.07);
  const brow = 0.17 * bump(t, 0.46, 0.42) * bump(v, 0.29, 0.09);
  const socket = -0.16 * bump(t, 0.46, 0.3) * bump(v, 0.13, 0.1);
  const cheek = 0.1 * bump(t, 0.78, 0.36) * bump(v, -0.04, 0.16);
  const lips = 0.075 * bump(t, 0, 0.42) * bump(v, -0.2, 0.06);
  // The groove between the lips, so the mouth is not one pillow.
  const philtrum = -0.05 * bump(t, 0, 0.2) * bump(v, -0.155, 0.03);
  const chin = 0.12 * bump(t, 0, 0.38) * bump(v, -0.5, 0.13);
  const temple = -0.05 * bump(t, 1.05, 0.3) * bump(v, 0.38, 0.18);

  return FRONT * (nose + brow + socket + cheek + lips + philtrum + chin + temple);
}

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
   * The neck and shoulders.
   *
   * A head floating alone reads as a head-shaped object; a neck reads as a
   * person. It is not part of the shell because the jaw must not drag it and
   * the relief must not reach it — a neck with cheekbones is not a neck.
   */
  neck: Strand[];
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

/**
 * A point in the head's own space, before rotation.
 *
 * The relief is added along the outward direction rather than to `z` alone:
 * displacing only in depth would flatten the nose as the head turns and leave
 * the cheeks sliding around the skull instead of sitting on it.
 */
function modelPoint(u: number, v: number, radius: number): [number, number, number] {
  const w = headWidthAt(v);
  const relief = faceRelief(u, v);
  const x = w * Math.sin(u);
  const z = w * Math.cos(u) * HEAD_DEPTH - BACKSET;
  // Outward normal, approximated by the direction from the axis. At the poles
  // `w` is zero and there is no outward direction, so the relief is zero there
  // too — which is correct: the crown and the point of the chin have none.
  const len = Math.hypot(Math.sin(u), Math.cos(u) * HEAD_DEPTH) || 1;
  return [
    (x + (relief * Math.sin(u)) / len) * radius,
    -v * HEAD_HEIGHT * radius,
    (z + (relief * Math.cos(u) * HEAD_DEPTH) / len) * radius,
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
  openness: number,
  radius: number,
): [number, number, number] {
  if (angle === 0) return p;
  const yHinge = -JAW_V * HEAD_HEIGHT * radius;
  const zHinge = JAW_HINGE_Z * radius;
  const dy = p[1] - yHinge;
  const dz = p[2] - zHinge;
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return [
    p[0],
    yHinge + dy * c + dz * s + openness * JAW_DROP * radius,
    zHinge - dy * s + dz * c,
  ];
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
  jawOpen: number,
): Strand {
  const points: Projected[] = [];
  let depthSum = 0;
  for (const [u, v] of samples) {
    let p = modelPoint(u, v, o.radius);
    if (v < JAW_V) p = hinge(p, jawAngle, jawOpen, o.radius);
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
      (v < JAW_V ? jaw : shell).push(strandFrom(samples, o, jawAngle, openness));
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
    if (upper.length > 1) shell.push(strandFrom(upper, o, jawAngle, openness));
    if (lower.length > 1) jaw.push(strandFrom(lower, o, jawAngle, openness));
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
    return strandFrom(samples, o, 0, 0);
  });

  // The lip line. Both halves are sampled at the SAME latitude and longitudes;
  // the only difference is that the lower one is swung with the mandible. So
  // "shut" is not a tuned constant, it is the two halves being the same points.
  const lipSamples: [number, number][] = [];
  for (let i = 0; i <= 10; i += 1) {
    lipSamples.push([-MOUTH_SPAN + (i / 10) * MOUTH_SPAN * 2, JAW_V]);
  }
  const mouth = {
    upper: strandFrom(lipSamples, o, 0, 0),
    lower: strandFrom(lipSamples.map(([u, v]) => [u, v - 1e-9] as [number, number]), o, jawAngle, openness),
  };

  // The neck. Its own geometry, in its own space: no profile table, no relief,
  // and never the jaw angle — a neck that hinged when the mouth opened would
  // be a jaw with a collar on it.
  const bottom = HEAD_HEIGHT * o.radius;
  const neck: Strand[] = NECK.map(([drop, halfWidth, depth]) => {
    const points: Projected[] = [];
    let depthSum = 0;
    for (let i = 0; i <= NECK_STEPS; i += 1) {
      const a = (i / NECK_STEPS) * Math.PI * 2;
      const q = project(
        orient(
          [
            Math.sin(a) * halfWidth * o.radius,
            bottom + drop * o.radius,
            Math.cos(a) * depth * o.radius - BACKSET * o.radius,
          ],
          o.yaw,
          o.pitch,
          roll,
        ),
        o.radius,
      );
      points.push({ x: q.x, y: q.y });
      depthSum += q.depth;
    }
    return { points, depth: depthSum / (NECK_STEPS + 1) };
  });

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
    scan = strandFrom(samples, o, jawAngle, openness);
  }

  return {
    shell,
    jaw,
    eyes,
    brows,
    mouth,
    neck,
    scan,
    facing: Math.max(0, Math.min(1, Math.cos(o.yaw) * Math.cos(o.pitch))),
  };
}

// ── the lit surface (§7, and the owner's reference of 2026-09-15) ─────────────

/**
 * The contours describe a head. They cannot make it solid.
 *
 * However dense a wireframe gets, you see the back of the skull through the
 * front of it, and no line weight fixes that — the problem is that nothing is
 * filled. The reference head is a shaded volume: a lit side, a dark side, a
 * bright rim where the surface turns away, and bands running across the form.
 *
 * `headSurface` samples the same geometry as quads and returns, per quad, the
 * three numbers a renderer needs and nothing else: how much light it catches,
 * how close it is to the silhouette, and how deep it sits. The colours are the
 * renderer's; the geometry and the lighting are here, where they can be tested
 * without a canvas.
 */

/**
 * Grid resolution, chosen from the head's size.
 *
 * A fixed grid is wrong at both ends: 40x46 across a 56-pixel dock is nine
 * hundred quads spread over a thumbnail, most of them smaller than a pixel and
 * every one of them a fill and a stroke, while the same grid on the AI Core
 * plane is about right. The ceiling is what a 460-pixel head measured at — 44.8
 * FPS with one drawImage and 131 fills a frame, the surface cached per pose.
 */
const SURF_MAX_LAT = 40;
const SURF_MAX_LON = 46;

function gridFor(radius: number): { lat: number; lon: number } {
  return {
    lat: Math.max(14, Math.min(SURF_MAX_LAT, Math.round(radius / 3.2))),
    lon: Math.max(18, Math.min(SURF_MAX_LON, Math.round(radius / 2.7))),
  };
}

/**
 * The key light: up, and to the viewer's left, in view space.
 *
 * In view space rather than model space on purpose. A light fixed to the head
 * turns with it, which is a head carrying its own lamp; a light fixed to the
 * viewer is a room, and the shading then changes as the head looks around —
 * which is the cue that sells the rotation.
 */
const LIGHT: readonly [number, number, number] = [-0.52, -0.46, 0.72];

export interface SurfaceQuad {
  points: Projected[];
  /** Mean depth, -1 (behind) to 1 (toward the viewer). Sorted ascending. */
  depth: number;
  /** Lambert term, 0..1. */
  light: number;
  /** Fresnel term, 0..1 — how far the surface has turned away from the viewer. */
  rim: number;
  /**
   * Blinn-Phong highlight, 0..1.
   *
   * Lambert alone is matte, and a matte cyan solid reads as a tinted
   * silhouette. The highlight is what puts the light ON the nose and the
   * cheekbone, which is what makes the relief visible at all — the first shaded
   * render had the relief and looked like a flat slab without this.
   */
  spec: number;
  /** How much of the quad faces the viewer, 0..1. Only positives are returned. */
  facing: number;
  /** Latitude, so a band can wrap the form rather than rule a line across it. */
  v: number;
}

function normalise(v: [number, number, number]): [number, number, number] {
  const len = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / len, v[1] / len, v[2] / len];
}


/**
 * One-entry memo on `headSurface`. `posePrint` is its key, exported because
 * the renderer caches a painted bitmap under the same pose and the two caches
 * must agree on what "the same pose" means.
 *
 * The surface is a pure function of pose and jaw, and `time` is provably not an
 * input — `does not move with the clock` asserts it. So between two frames in
 * which the head has not moved, it was rebuilding a 40x46 grid, 1,840 normals
 * and a smoothing pass to produce identical numbers, sixty times a second.
 *
 * The key is quantised because the pose is driven by a breath and a blink that
 * jitter continuously by fractions the drawing cannot resolve: without
 * rounding, the cache would never hit while the head was merely alive. The
 * steps are below what a pixel can show at the sizes this draws at — 0.004 rad
 * is about a quarter of a degree.
 */
let surfaceKey = '';
let surfaceValue: SurfaceQuad[] = [];

export function posePrint(o: HeadMeshOptions): string {
  const q = (n: number, step: number) => Math.round((n ?? 0) / step);
  return [
    q(o.radius, 0.5),
    q(o.yaw, 0.004),
    q(o.pitch, 0.004),
    q(o.roll ?? 0, 0.004),
    q(Math.max(0, Math.min(1, o.mouthOpenness)), 0.02),
  ].join(',');
}

/**
 * The surface, back to front.
 *
 * Back-facing quads are dropped rather than drawn and covered: painter's
 * algorithm gets the same picture either way, and this runs every frame on a
 * page that also places orders.
 */
export function headSurface(options: HeadMeshOptions): SurfaceQuad[] {
  const o = options;
  const key = posePrint(o);
  if (key === surfaceKey) return surfaceValue;
  const { lat: SURF_LAT, lon: SURF_LON } = gridFor(o.radius);
  const openness = Math.max(0, Math.min(1, o.mouthOpenness));
  const jawAngle = openness * MAX_JAW;
  const roll = o.roll ?? 0;

  // One pass over the grid, keeping the oriented 3D point and its projection,
  // so each vertex is transformed once rather than four times.
  const grid: { p: [number, number, number]; q: { x: number; y: number; depth: number } }[][] = [];
  for (let i = 0; i <= SURF_LAT; i += 1) {
    const v = 1 - (i / SURF_LAT) * 2;
    const row: { p: [number, number, number]; q: { x: number; y: number; depth: number } }[] = [];
    for (let j = 0; j <= SURF_LON; j += 1) {
      const u = -Math.PI + (j / SURF_LON) * Math.PI * 2;
      let p = modelPoint(u, v, o.radius);
      if (v < JAW_V) p = hinge(p, jawAngle, openness, o.radius);
      const oriented = orient(p, o.yaw, o.pitch, roll);
      row.push({ p: oriented, q: project(oriented, o.radius) });
    }
    grid.push(row);
  }

  // Face normals first, then a smoothing pass, then the quads.
  //
  // Canvas 2D fills a quad with ONE colour — there is no interpolation across
  // it — so flat shading off raw face normals shows every grid cell. The relief
  // is built from Gaussians that turn faster than this grid samples, which made
  // the mosaic worse still: measured as visible checkerboarding across the
  // forehead and the cheek.
  //
  // Averaging each face normal with its neighbours is the standard fix and the
  // only one available without a shader: it is a two-ring blur of the normal
  // field, so neighbouring quads can no longer differ sharply, and the cost is
  // one extra pass over a grid that was already built.
  const faceN: [number, number, number][][] = [];
  for (let i = 0; i < SURF_LAT; i += 1) {
    const row: [number, number, number][] = [];
    for (let j = 0; j < SURF_LON; j += 1) {
      const a = grid[i]![j]!.p;
      const b = grid[i]![j + 1]!.p;
      const d = grid[i + 1]![j]!.p;
      const e1: [number, number, number] = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
      const e2: [number, number, number] = [d[0] - a[0], d[1] - a[1], d[2] - a[2]];
      row.push(
        normalise([
          e1[1] * e2[2] - e1[2] * e2[1],
          e1[2] * e2[0] - e1[0] * e2[2],
          e1[0] * e2[1] - e1[1] * e2[0],
        ]),
      );
    }
    faceN.push(row);
  }

  const smooth = (i: number, j: number): [number, number, number] => {
    let x = 0;
    let y = 0;
    let z = 0;
    for (let di = -1; di <= 1; di += 1) {
      const ri = Math.max(0, Math.min(SURF_LAT - 1, i + di));
      for (let dj = -1; dj <= 1; dj += 1) {
        // Longitude wraps: the seam at the back of the head must not be a
        // visible line of unsmoothed quads.
        const rj = (j + dj + SURF_LON) % SURF_LON;
        const n = faceN[ri]![rj]!;
        x += n[0];
        y += n[1];
        z += n[2];
      }
    }
    return normalise([x, y, z]);
  };

  const out: SurfaceQuad[] = [];
  for (let i = 0; i < SURF_LAT; i += 1) {
    const v = 1 - ((i + 0.5) / SURF_LAT) * 2;
    for (let j = 0; j < SURF_LON; j += 1) {
      const a = grid[i]![j]!;
      const b = grid[i]![j + 1]!;
      const c = grid[i + 1]![j + 1]!;
      const d = grid[i + 1]![j]!;

      const n = smooth(i, j);

      // The viewer looks down +z, so a quad faces us when its normal does.
      // Culled on the RAW face normal, not the smoothed one: the smoothed field
      // bleeds across the silhouette and would keep a ring of back-facing quads
      // that then draw over the rim.
      const raw = faceN[i]![j]![2];
      if (raw <= 0.02) continue;
      const facing = Math.max(0.02, n[2]);

      const lambert = n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2];
      // Half-vector between the light and the viewer's +z.
      const hv = normalise([LIGHT[0], LIGHT[1], LIGHT[2] + 1]);
      // A broad exponent on purpose: with one flat colour per quad, a tight
      // highlight lands as a field of hard bright squares rather than as a
      // highlight. Measured at 22: visible blocking across the forehead.
      const spec = Math.max(0, n[0] * hv[0] + n[1] * hv[1] + n[2] * hv[2]) ** 6;
      out.push({
        points: [
          { x: a.q.x, y: a.q.y },
          { x: b.q.x, y: b.q.y },
          { x: c.q.x, y: c.q.y },
          { x: d.q.x, y: d.q.y },
        ],
        depth: (a.q.depth + b.q.depth + c.q.depth + d.q.depth) / 4,
        light: Math.max(0, Math.min(1, lambert * 0.5 + 0.5)),
        spec: Math.max(0, Math.min(1, spec)),
        // Fresnel. Bright wherever the surface turns away, so the jaw, the brow
        // and the bridge of the nose light up on their own and follow the head
        // when it turns — which an artist-placed outline would not.
        rim: Math.max(0, Math.min(1, (1 - facing) ** 2.2)),
        facing,
        v,
      });
    }
  }

  out.sort((p, q) => p.depth - q.depth);
  surfaceKey = key;
  surfaceValue = out;
  return out;
}

/** Tests only. Drops the memo so a cache hit cannot mask a geometry change. */
export function resetSurfaceCache(): void {
  surfaceKey = '';
  surfaceValue = [];
}
