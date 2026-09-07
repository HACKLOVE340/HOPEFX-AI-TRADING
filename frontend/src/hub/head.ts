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
