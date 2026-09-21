/**
 * Owner request: "The head can have auto mode, detection mode, reaction mode,
 * mimicking mode, consign mode, worried mode, panicking mode, awareness mode.
 * All this should be in the AI brain."
 *
 * The last sentence is the whole design. A head that can look worried is a
 * feature; a head that looks worried on a timer is a lie with a face, and this
 * platform already has a rule against decorative "live" values (§22). So there
 * is no `setMode`. `chooseHeadMode` is the auto mode — it reads the same
 * measured signals the presence machine reads and returns the mode those
 * signals justify, together with the sentence naming which measurement chose
 * it. A forced mode exists only for the review surface, and it is the caller's
 * word, not the brain's.
 *
 * Two modes are refusals, and they are the interesting ones:
 *
 * - **mimicking** requires a live vision source. Mirroring a face nobody
 *   measured is a fabricated claim about the operator.
 * - **panicking** requires a catastrophic measurement, not a loud one. If it
 *   could be reached by an amber alert it would be reached constantly, and an
 *   operator learns to ignore a face that is always alarmed — the same reason
 *   `/health` refuses to fold the engine's state into the overall verdict.
 */
import { describe, it, expect } from 'vitest';

import {
  HEAD_MODES,
  type HeadMode,
  type HeadSignals,
  blinkAt,
  chooseHeadMode,
  expressionFor,
  signalsFromPresence,
} from '../hub/headModes';

const CALM: HeadSignals = {
  state: 'idle',
  tone: 'ok',
  intensity: 0.1,
  riskHeadroom: 0.8,
  alertSeverity: null,
  feedStale: false,
  providersReachable: 2,
  micOpen: false,
  speaking: false,
  visionLive: false,
  refused: false,
  reactedWithinMs: null,
};

const mode = (s: Partial<HeadSignals>) => chooseHeadMode({ ...CALM, ...s }).mode;

describe('the brain chooses the mode', () => {
  it('is awake and attending when everything is healthy and nothing is happening', () => {
    expect(mode({})).toBe('awareness');
  });

  it('is dormant when nothing is arriving', () => {
    expect(mode({ state: 'offline' })).toBe('dormant');
  });

  it('panics only for a catastrophic measurement', () => {
    expect(mode({ alertSeverity: 'critical' })).toBe('panicking');
    expect(mode({ riskHeadroom: 0.0 })).toBe('panicking');
    // Loud is not catastrophic. A face that is alarmed at every amber is a
    // face nobody reads.
    expect(mode({ alertSeverity: 'medium' })).not.toBe('panicking');
    expect(mode({ tone: 'warn' })).not.toBe('panicking');
  });

  it('worries about a real adverse number without panicking about it', () => {
    expect(mode({ riskHeadroom: 0.06 })).toBe('worried');
    expect(mode({ alertSeverity: 'high' })).toBe('worried');
  });

  it('is concerned — not worried — when it cannot see', () => {
    // "Concerned" is the degraded face: the measurement is missing, not bad.
    // Reporting a missing number as an adverse one is the defect this
    // repository fixed in the risk ring, where an unknown headroom was drawn
    // as a full one.
    expect(mode({ feedStale: true })).toBe('concerned');
    expect(mode({ providersReachable: 0 })).toBe('concerned');
    expect(mode({ riskHeadroom: null })).toBe('concerned');
  });

  it('refuses with a face of its own', () => {
    // The platform's ledger treats a refusal as a first-class entry rather than
    // a failure. The presence should too: a refusal that looked like an error
    // invites the operator to retry it.
    expect(mode({ refused: true })).toBe('refusing');
  });

  it('will not mimic without a live vision source', () => {
    expect(mode({ visionLive: false })).not.toBe('mimicking');
    expect(mode({ visionLive: true })).toBe('mimicking');
  });

  it('detects while it is classifying, and reacts just after something landed', () => {
    expect(mode({ state: 'thinking' })).toBe('detection');
    expect(mode({ reactedWithinMs: 300 })).toBe('reaction');
    // A reaction is brief by definition. One that lasted would be a mood.
    expect(mode({ reactedWithinMs: 9000 })).toBe('awareness');
  });

  it('speaks and listens', () => {
    expect(mode({ speaking: true })).toBe('speaking');
    expect(mode({ micOpen: true })).toBe('listening');
  });

  it('lets alarm outrank conversation', () => {
    // §19's critical floor: a kill switch is not silenced by the fact that the
    // assistant was mid-sentence.
    expect(mode({ speaking: true, alertSeverity: 'critical' })).toBe('panicking');
    expect(mode({ micOpen: true, feedStale: true })).toBe('concerned');
  });

  it('names the measurement that chose the mode, every time', () => {
    // Without this the face is the only evidence, and a face is not evidence.
    for (const signals of [
      CALM,
      { ...CALM, state: 'offline' as const },
      { ...CALM, alertSeverity: 'critical' as const },
      { ...CALM, riskHeadroom: 0.05 },
      { ...CALM, riskHeadroom: null },
      { ...CALM, refused: true },
      { ...CALM, visionLive: true },
      { ...CALM, state: 'thinking' as const },
      { ...CALM, speaking: true },
      { ...CALM, micOpen: true },
      { ...CALM, reactedWithinMs: 200 },
    ]) {
      const chosen = chooseHeadMode(signals);
      expect(chosen.reason.length).toBeGreaterThan(8);
      expect(HEAD_MODES).toContain(chosen.mode);
      expect(chosen.severity).toBeGreaterThanOrEqual(0);
      expect(chosen.severity).toBeLessThanOrEqual(1);
    }
  });

  it('scales severity with how bad the measurement is, rather than by mode', () => {
    // Two accounts can both be in breach and not be equally in breach.
    const nearly = chooseHeadMode({ ...CALM, riskHeadroom: 0.02 }).severity;
    const gone = chooseHeadMode({ ...CALM, riskHeadroom: 0 }).severity;
    expect(gone).toBeGreaterThan(nearly);
  });
});

describe('every mode has a face', () => {
  it('covers the whole list — a mode with no expression is a head that freezes', () => {
    for (const m of HEAD_MODES) {
      const e = expressionFor(m, { time: 1000, severity: 0.5, reducedMotion: false });
      expect(Number.isFinite(e.brow)).toBe(true);
      expect(Number.isFinite(e.tilt)).toBe(true);
      expect(Number.isFinite(e.sweep)).toBe(true);
      expect(e.lidClosure).toBeGreaterThanOrEqual(0);
      expect(e.lidClosure).toBeLessThanOrEqual(1);
      expect(e.pupil).toBeGreaterThan(0);
    }
  });

  it('draws the brow in when worried and up when alarmed', () => {
    const t = { time: 0, severity: 0.5, reducedMotion: false };
    expect(expressionFor('worried', t).brow).toBeLessThan(0);
    expect(expressionFor('panicking', t).brow).toBeGreaterThan(0);
    expect(Math.abs(expressionFor('awareness', t).brow)).toBeLessThan(0.2);
  });

  it('tilts when it is unsure and not when it is not', () => {
    const t = { time: 0, severity: 0.5, reducedMotion: false };
    expect(Math.abs(expressionFor('concerned', t).tilt)).toBeGreaterThan(0.02);
    expect(Math.abs(expressionFor('awareness', t).tilt)).toBeLessThan(0.02);
  });

  it('trembles only when panicking, and by how bad it is', () => {
    const at = (m: HeadMode, severity: number) =>
      expressionFor(m, { time: 133, severity, reducedMotion: false }).tremor;
    expect(at('awareness', 1)).toBe(0);
    expect(at('worried', 1)).toBe(0);
    expect(at('panicking', 0.9)).toBeGreaterThan(at('panicking', 0.2));
  });

  it('closes the eyes when dormant and opens them wide when panicking', () => {
    const t = { time: 0, severity: 0.8, reducedMotion: false };
    expect(expressionFor('dormant', t).lidClosure).toBeGreaterThan(0.6);
    expect(expressionFor('panicking', t).lidClosure).toBeLessThan(0.1);
  });

  it('stops the scan when there is nothing arriving to scan', () => {
    const t = { time: 0, severity: 0.2, reducedMotion: false };
    expect(expressionFor('dormant', t).scanRate).toBe(0);
    expect(expressionFor('detection', t).scanRate).toBeGreaterThan(
      expressionFor('awareness', t).scanRate,
    );
  });

  it('stops everything that moves under reduced motion, and keeps everything that means', () => {
    for (const m of HEAD_MODES) {
      const e = expressionFor(m, { time: 4321, severity: 1, reducedMotion: true });
      expect(e.tremor).toBe(0);
      expect(e.breath).toBe(0);
      expect(e.sweep).toBe(0);
      expect(e.scanRate).toBe(0);
      // The brow, the lids and the tilt are not motion — they are the reading.
      // Removing them would hide the alarm from the operator who most needs a
      // still interface.
      const moving = expressionFor(m, { time: 4321, severity: 1, reducedMotion: false });
      expect(e.brow).toBeCloseTo(moving.brow, 6);
      expect(e.lidClosure).toBeCloseTo(moving.lidClosure, 6);
    }
  });

  it('is deterministic in time', () => {
    const a = expressionFor('panicking', { time: 500, severity: 0.7, reducedMotion: false });
    const b = expressionFor('panicking', { time: 500, severity: 0.7, reducedMotion: false });
    expect(b).toEqual(a);
  });
});

describe('blinking', () => {
  it('is mostly open', () => {
    // A head that never blinks is uncanny; one that blinks constantly is a
    // fault light. Sampled across a minute, the eyes should be open for the
    // overwhelming majority of it.
    let shut = 0;
    const samples = 600;
    for (let i = 0; i < samples; i += 1) {
      if (blinkAt(i * 100, false) > 0.5) shut += 1;
    }
    expect(shut / samples).toBeLessThan(0.1);
    expect(shut).toBeGreaterThan(0);
  });

  it('does not blink under reduced motion', () => {
    for (let i = 0; i < 200; i += 1) expect(blinkAt(i * 97, true)).toBe(0);
  });

  it('is deterministic', () => {
    expect(blinkAt(12345, false)).toBe(blinkAt(12345, false));
  });
});

describe('the collapsed form', () => {
  const base: Parameters<typeof signalsFromPresence>[0] = {
    state: 'idle', tone: 'ok', intensity: 0.1, headroomKnown: true,
  };
  const m = (p: Partial<typeof base>, extra: Parameters<typeof signalsFromPresence>[1] = {}) =>
    chooseHeadMode(signalsFromPresence({ ...base, ...p }, extra)).mode;

  it('carries the states a Presence can still express', () => {
    expect(m({})).toBe('awareness');
    expect(m({ state: 'offline', tone: 'dead' })).toBe('dormant');
    expect(m({ state: 'alerting', tone: 'bad' })).toBe('panicking');
    expect(m({ state: 'alerting', tone: 'warn' })).toBe('worried');
    expect(m({ state: 'degraded', tone: 'warn' })).toBe('concerned');
    expect(m({ state: 'thinking' })).toBe('detection');
    expect(m({ state: 'speaking' })).toBe('speaking');
    expect(m({ state: 'listening' })).toBe('listening');
  });

  it('reports an unknown headroom as concerned rather than fine', () => {
    expect(m({ headroomKnown: false })).toBe('concerned');
  });

  it('does not invent a headroom figure it was never given', () => {
    // The collapsed Presence keeps only whether the number was known. Passing a
    // fabricated low value here to unlock the worried face would be a face
    // driven by a number nobody measured.
    expect(signalsFromPresence({ ...base, headroomKnown: true }).riskHeadroom).toBe(1);
    expect(signalsFromPresence({ ...base, headroomKnown: false }).riskHeadroom).toBeNull();
  });

  it('lets the caller override with what it actually measured', () => {
    expect(m({}, { visionLive: true })).toBe('mimicking');
    expect(m({}, { refused: true })).toBe('refusing');
    expect(m({}, { speaking: true })).toBe('speaking');
  });
});
