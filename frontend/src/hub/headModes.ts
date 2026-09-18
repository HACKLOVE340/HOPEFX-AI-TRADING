/**
 * hub/headModes.ts — what the head is doing, and why.
 *
 * Owner request: "The head can have auto mode, detection mode, reaction mode,
 * mimicking mode, consign mode, worried mode, panicking mode, awareness mode.
 * All this should be in the AI brain."
 *
 * The last sentence decided the shape of this file. There is no `setMode`.
 * `chooseHeadMode` **is** the auto mode: it reads the same measured signals the
 * presence machine reads — socket state, feed staleness, risk headroom, alert
 * severity, whether the microphone is open, whether a vision source is actually
 * running — and returns the mode those signals justify, along with the sentence
 * naming which measurement chose it.
 *
 * ## Why it cannot be a toggle
 *
 * A head that can look worried is a feature. A head that looks worried because
 * someone set `mode="worried"` is a lie with a face, and this platform already
 * refuses decorative "live" values (§22) for the same reason it stops the
 * activity ring dead over a closed socket rather than spinning prettily.
 *
 * The one override is `force`, and it exists for the review surface, where the
 * point is to look at all eleven faces without arranging eleven outages. It is
 * the caller's word and it is labelled as such, never the brain's.
 *
 * ## Two of these modes are refusals
 *
 * **mimicking** requires a live vision source. `hub/visionSource.ts` knows
 * whether a camera is delivering frames; mirroring an operator nobody measured
 * would be a fabricated claim about a person.
 *
 * **panicking** requires a catastrophic measurement, not a loud one. If an
 * amber alert could reach it, it would be reached constantly, and an operator
 * learns to ignore a face that is always alarmed — the same argument that keeps
 * the engine's state out of `/health`'s overall verdict.
 *
 * ## And one is a mode this codebase needed and did not have
 *
 * **refusing.** `ai/ledger/decisions.py` records refusals as first-class
 * entries rather than failures, on the reasoning that a platform declining to
 * act has said something. The presence had no way to show it, so a refusal
 * looked like an error — which invites the operator to retry it.
 *
 * ## Expression is not animation
 *
 * `expressionFor` separates the two deliberately. Brow, eyelids and tilt are
 * the *reading*, and reduced motion keeps every one of them: hiding the alarm
 * from the operator who asked for a still interface would be an accessibility
 * setting that removes information. Tremor, breath, sweep and the scan are
 * motion, and reduced motion removes all of them.
 */

import type { PresenceState, PresenceTone } from './presence';

/**
 * Every face, in the order the brain considers them: most urgent first.
 *
 * Exported so the review surface and the tests can enumerate them. A mode with
 * no expression is a head that freezes at the moment it most needs to say
 * something, which is exactly what `PRESENCE_STATES` exists to prevent for the
 * presence machine.
 */
export const HEAD_MODES = [
  'panicking',
  'refusing',
  'worried',
  'concerned',
  'speaking',
  'listening',
  'mimicking',
  'detection',
  'reaction',
  'awareness',
  'dormant',
] as const;

export type HeadMode = (typeof HEAD_MODES)[number];

export type AlertSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface HeadSignals {
  state: PresenceState;
  tone: PresenceTone;
  /** 0..1 from the presence machine. */
  intensity: number;
  /** 0..1, or **null** when nobody measured it. Null is not zero and not full. */
  riskHeadroom: number | null;
  alertSeverity: AlertSeverity | null;
  feedStale: boolean;
  /** How many model vendors this deployment can actually reach. */
  providersReachable: number;
  micOpen: boolean;
  speaking: boolean;
  /** A camera is delivering frames right now. Not "a camera exists". */
  visionLive: boolean;
  /** The platform declined to act, and said so. */
  refused: boolean;
  /** How long ago something landed, in ms, or null if nothing has. */
  reactedWithinMs: number | null;
}

export interface ChosenMode {
  mode: HeadMode;
  /** The measurement that chose it, in a sentence. Shown, not just logged. */
  reason: string;
  /** 0..1. How bad, not merely which kind — two breaches are not equal. */
  severity: number;
}

/** Below this fraction of the daily risk limit, the face stops being calm. */
const HEADROOM_WORRY = 0.1;
/** At or below this, it is catastrophic rather than adverse. */
const HEADROOM_PANIC = 0.02;
/** A reaction is brief by definition. One that lasted would be a mood. */
const REACTION_WINDOW_MS = 2500;

function clamp01(n: number): number {
  return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0;
}

/**
 * The auto mode. Order is precedence, and precedence is urgency.
 *
 * `force` overrides the choice for the review surface only, and the reason says
 * so rather than inventing a measurement to justify it.
 */
export function chooseHeadMode(signals: HeadSignals, force?: HeadMode): ChosenMode {
  const s = signals;
  const headroom = typeof s.riskHeadroom === 'number' && Number.isFinite(s.riskHeadroom)
    ? clamp01(s.riskHeadroom)
    : null;

  if (force) {
    return { mode: force, reason: `Held at ${force} by the review surface, not by a measurement.`, severity: 0.5 };
  }

  // Nothing arriving. Everything below is a reading of data, and there is none.
  if (s.state === 'offline') {
    return { mode: 'dormant', reason: 'Nothing is arriving — no feed, so nothing to read.', severity: 0 };
  }

  if (s.alertSeverity === 'critical') {
    return { mode: 'panicking', reason: 'A critical alert is open.', severity: 1 };
  }
  if (headroom !== null && headroom <= HEADROOM_PANIC) {
    return {
      mode: 'panicking',
      // Severity rises as the remaining headroom falls, so "almost gone" and
      // "gone" do not shake the same amount.
      reason: `Risk headroom is ${(headroom * 100).toFixed(1)}% — at or below the ${(HEADROOM_PANIC * 100).toFixed(0)}% floor.`,
      severity: 1 - headroom / HEADROOM_PANIC * 0.35,
    };
  }

  if (s.refused) {
    return { mode: 'refusing', reason: 'The platform declined to act, and recorded why.', severity: 0.4 };
  }

  if (s.alertSeverity === 'high') {
    return { mode: 'worried', reason: 'A high-severity alert is open.', severity: 0.7 };
  }
  if (headroom !== null && headroom < HEADROOM_WORRY) {
    return {
      mode: 'worried',
      reason: `Risk headroom is ${(headroom * 100).toFixed(1)}%, under the ${(HEADROOM_WORRY * 100).toFixed(0)}% mark.`,
      severity: 0.5 + (1 - headroom / HEADROOM_WORRY) * 0.3,
    };
  }

  // Degraded: the measurement is MISSING, which is a different thing from bad.
  // Drawing a missing number as an adverse one is the defect the risk ring
  // already fixed by refusing to draw an unmeasured headroom as a full one.
  if (headroom === null) {
    return { mode: 'concerned', reason: 'Risk headroom is unmeasured — not zero, not full, unknown.', severity: 0.35 };
  }
  if (s.feedStale) {
    return { mode: 'concerned', reason: 'The feed is open and silent — the last tick is stale.', severity: 0.4 };
  }
  if (s.providersReachable <= 0) {
    return { mode: 'concerned', reason: 'No model vendor is reachable from this deployment.', severity: 0.4 };
  }

  if (s.speaking) {
    return { mode: 'speaking', reason: 'Speaking now.', severity: 0.15 };
  }
  if (s.micOpen) {
    return { mode: 'listening', reason: 'The microphone is open.', severity: 0.15 };
  }

  // Mirroring a face nobody measured would be a fabricated claim about the
  // operator, so this needs frames, not a camera permission.
  if (s.visionLive) {
    return { mode: 'mimicking', reason: 'A vision source is delivering frames — mirroring the measured pose.', severity: 0.1 };
  }

  if (s.state === 'thinking') {
    return { mode: 'detection', reason: 'Classifying what just arrived.', severity: clamp01(0.2 + s.intensity * 0.3) };
  }

  if (s.reactedWithinMs !== null && Number.isFinite(s.reactedWithinMs) && s.reactedWithinMs >= 0 && s.reactedWithinMs < REACTION_WINDOW_MS) {
    return { mode: 'reaction', reason: 'Something landed a moment ago.', severity: 0.25 };
  }

  return { mode: 'awareness', reason: 'Attending — inputs healthy, nothing outstanding.', severity: 0.05 };
}

// ── the face each mode wears ─────────────────────────────────────────────────

export interface Expression {
  /** Extra eyelid closure. 0 open, 1 shut. */
  lidClosure: number;
  /** -1 drawn in and down (worried), +1 raised (alarm). */
  brow: number;
  /** Head roll in radians. A tilt reads as "I am not certain". */
  tilt: number;
  /** Positional jitter in pixels. Zero unless the measurement is catastrophic. */
  tremor: number;
  /** Idle motion: amplitude 0..1 and rate in Hz. */
  breath: number;
  breathHz: number;
  /** Multiplier on the scan ring's travel. 0 stops it. */
  scanRate: number;
  /** Extra yaw the head adds on its own — searching, or averting. */
  sweep: number;
  /** Pupil scale. Wide when alarmed, narrow when concentrating. */
  pupil: number;
}

export interface ExpressionOptions {
  time: number;
  /** 0..1 from `chooseHeadMode`. Drives amplitude, never kind. */
  severity: number;
  reducedMotion: boolean;
}

/**
 * The still half of each face: what it MEANS.
 *
 * Reduced motion keeps every field in this table. Hiding a raised brow from the
 * operator who asked for a still interface would be an accessibility setting
 * that removes information rather than movement.
 */
const STILL: Record<HeadMode, Pick<Expression, 'lidClosure' | 'brow' | 'tilt' | 'pupil'>> = {
  panicking: { lidClosure: 0.0, brow: 0.85, tilt: 0.0, pupil: 1.35 },
  refusing: { lidClosure: 0.28, brow: -0.15, tilt: 0.0, pupil: 0.85 },
  worried: { lidClosure: 0.12, brow: -0.7, tilt: -0.03, pupil: 1.1 },
  concerned: { lidClosure: 0.18, brow: -0.35, tilt: 0.09, pupil: 1.0 },
  speaking: { lidClosure: 0.05, brow: 0.12, tilt: 0.0, pupil: 1.0 },
  listening: { lidClosure: 0.08, brow: 0.2, tilt: 0.07, pupil: 1.05 },
  mimicking: { lidClosure: 0.06, brow: 0.0, tilt: 0.0, pupil: 1.0 },
  detection: { lidClosure: 0.3, brow: -0.1, tilt: 0.0, pupil: 0.75 },
  reaction: { lidClosure: 0.0, brow: 0.55, tilt: 0.0, pupil: 1.2 },
  awareness: { lidClosure: 0.1, brow: 0.0, tilt: 0.0, pupil: 1.0 },
  dormant: { lidClosure: 0.82, brow: -0.05, tilt: 0.0, pupil: 0.7 },
};

/**
 * The moving half: how ALIVE it is.
 *
 * `tremorGain` is a gain on severity, not a constant, so a breach that is
 * nearly total and one that is total do not shake identically. Everything here
 * is zero under reduced motion.
 */
const MOVING: Record<HeadMode, { tremorGain: number; breath: number; breathHz: number; scanRate: number; sweep: number }> = {
  panicking: { tremorGain: 3.2, breath: 0.9, breathHz: 0.95, scanRate: 2.2, sweep: 0.05 },
  refusing: { tremorGain: 0, breath: 0.25, breathHz: 0.18, scanRate: 0.35, sweep: -0.14 },
  worried: { tremorGain: 0, breath: 0.55, breathHz: 0.42, scanRate: 0.8, sweep: 0.06 },
  concerned: { tremorGain: 0, breath: 0.4, breathHz: 0.3, scanRate: 0.5, sweep: 0.12 },
  speaking: { tremorGain: 0, breath: 0.35, breathHz: 0.3, scanRate: 1.0, sweep: 0.03 },
  listening: { tremorGain: 0, breath: 0.3, breathHz: 0.24, scanRate: 0.9, sweep: 0.04 },
  mimicking: { tremorGain: 0, breath: 0.3, breathHz: 0.26, scanRate: 0.7, sweep: 0 },
  detection: { tremorGain: 0, breath: 0.45, breathHz: 0.55, scanRate: 2.0, sweep: 0.22 },
  reaction: { tremorGain: 0, breath: 0.6, breathHz: 0.7, scanRate: 1.5, sweep: 0.1 },
  awareness: { tremorGain: 0, breath: 0.3, breathHz: 0.2, scanRate: 0.6, sweep: 0.08 },
  dormant: { tremorGain: 0, breath: 0, breathHz: 0, scanRate: 0, sweep: 0 },
};

export function expressionFor(mode: HeadMode, options: ExpressionOptions): Expression {
  const still = STILL[mode] ?? STILL.awareness;
  const moving = MOVING[mode] ?? MOVING.awareness;
  const severity = clamp01(options.severity);

  if (options.reducedMotion) {
    return { ...still, tremor: 0, breath: 0, breathHz: 0, scanRate: 0, sweep: 0 };
  }

  // Two frequencies that do not divide, so the jitter never settles into a
  // visible beat — a tremor that pulses rhythmically reads as a loading
  // animation rather than as distress.
  const t = options.time;
  const tremor = moving.tremorGain === 0
    ? 0
    : moving.tremorGain * severity * (Math.sin(t * 0.047) * 0.6 + Math.sin(t * 0.113) * 0.4);

  return {
    ...still,
    tremor,
    breath: moving.breath,
    breathHz: moving.breathHz,
    scanRate: moving.scanRate,
    // The idle sweep is the head looking around of its own accord. It is
    // bounded small on purpose: §7 asks the presence to move toward the panel
    // being discussed, and a head wandering on its own competes with that.
    sweep: moving.sweep * Math.sin(t * 0.00042),
  };
}

// ── blinking ─────────────────────────────────────────────────────────────────

/** Roughly how often a resting human blinks. */
const BLINK_PERIOD_MS = 4300;
/** How long one blink takes. */
const BLINK_MS = 130;

/**
 * 0 (open) to 1 (shut).
 *
 * A head that never blinks is uncanny; one that blinks on a fixed beat is a
 * fault light. The interval is nudged by a cheap deterministic hash of the
 * blink's index so the rhythm is irregular but reproducible — a random blink
 * cannot be tested and flickers differently on every device.
 */
export function blinkAt(time: number, reducedMotion: boolean): number {
  if (reducedMotion) return 0;
  const index = Math.floor(time / BLINK_PERIOD_MS);
  // Deterministic jitter in [-0.35, 0.35] of a period.
  const hash = Math.abs(Math.sin(index * 12.9898) * 43758.5453) % 1;
  const jitter = hash * 0.7 - 0.35;
  const start = index * BLINK_PERIOD_MS + jitter * BLINK_PERIOD_MS;
  const since = time - start;
  if (since < 0 || since > BLINK_MS) return 0;
  // Shut and open again: a half sine, so the lid does not snap.
  return Math.sin((since / BLINK_MS) * Math.PI);
}

// ── the collapsed form, for callers that only have a Presence ─────────────────

/**
 * Best signals available from a `Presence` alone.
 *
 * `hub/presence.ts` takes the full `PresenceInputs` and collapses them into a
 * state, a tone and an intensity — which is the right shape for a renderer and
 * loses the numbers this file would rather read. A caller holding the original
 * inputs (`AICore` does) should build `HeadSignals` from those and not use
 * this; a caller holding only the collapsed form (every other page) gets this,
 * which is an approximation and says so.
 *
 * What it can NOT recover, and does not pretend to:
 *
 * - **The headroom figure.** `Presence` keeps only whether it was known. So a
 *   known headroom is passed through as healthy, and the worried face for a
 *   thin-but-not-breached account is reachable only from the full inputs. The
 *   alternative — inventing a number to drive a face — is the defect this whole
 *   module is built to avoid.
 * - **Which alert.** `alerting` with a `bad` tone is the platform's own
 *   shorthand for the interrupting severities (§19), so it maps to critical;
 *   `alerting` with any softer tone maps to high.
 */
export function signalsFromPresence(
  presence: { state: PresenceState; tone: PresenceTone; intensity: number; headroomKnown: boolean },
  extra: Partial<Pick<HeadSignals, 'micOpen' | 'speaking' | 'visionLive' | 'refused' | 'reactedWithinMs'>> = {},
): HeadSignals {
  const alerting = presence.state === 'alerting';
  return {
    state: presence.state,
    tone: presence.tone,
    intensity: presence.intensity,
    riskHeadroom: presence.headroomKnown ? 1 : null,
    alertSeverity: alerting ? (presence.tone === 'bad' ? 'critical' : 'high') : null,
    feedStale: presence.state === 'degraded',
    providersReachable: presence.state === 'offline' ? 0 : 1,
    micOpen: extra.micOpen ?? presence.state === 'listening',
    speaking: extra.speaking ?? (presence.state === 'speaking' || presence.state === 'explaining'),
    visionLive: extra.visionLive ?? false,
    refused: extra.refused ?? false,
    reactedWithinMs: extra.reactedWithinMs ?? null,
  };
}
