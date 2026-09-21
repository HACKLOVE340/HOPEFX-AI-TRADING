/**
 * hub/voicePrefs.ts — how fast and in whose voice, within bounds.
 *
 * §17 asks for "adjustable speech speed and voice preference". The adjustment
 * is trivial; the bounds are the part that matters.
 *
 * The presence speaks unprompted exactly once — when something is wrong. A rate
 * of 10 turns that alert into noise, and a rate of 0.05 turns it into something
 * the operator cannot wait out and will mute, which removes spoken alerts
 * entirely. Both ends of the range are ways of losing the one message that had
 * to arrive.
 *
 * ## It says what it changed
 *
 * Silently correcting an operator's setting means the next time they look, the
 * number they typed is not there and nothing explains why. `clamped` names
 * every field that was adjusted.
 *
 * ## A non-number falls back to the default, not to zero
 *
 * `Number.NaN` through a clamp comes out as whichever bound the comparison
 * happens to reach first, which is a silent behaviour decided by operator
 * precedence.
 */

export interface Limit {
  min: number;
  max: number;
  default: number;
}

export const VOICE_LIMITS: { rate: Limit; pitch: Limit } = {
  // 0.6 is slow and clear; 2.0 is brisk and still intelligible.
  rate: { min: 0.6, max: 2.0, default: 1.0 },
  pitch: { min: 0.5, max: 1.5, default: 1.0 },
};

export interface VoicePreferences {
  rate: number;
  pitch: number;
  /** A BCP-47 tag or a platform voice name. Empty means the system default. */
  voice: string;
  /** Fields that were out of range or unusable, and were adjusted. */
  clamped: string[];
}

function clampOne(value: unknown, limit: Limit, name: string, clamped: string[]): number {
  if (value === undefined) return limit.default;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    // Not a bound: NaN through a comparison yields whichever branch the
    // operator precedence reaches first, which is a behaviour nobody chose.
    clamped.push(name);
    return limit.default;
  }
  if (value < limit.min) {
    clamped.push(name);
    return limit.min;
  }
  if (value > limit.max) {
    clamped.push(name);
    return limit.max;
  }
  return value;
}

export function clampPreferences(input: { rate?: number; pitch?: number; voice?: string }): VoicePreferences {
  const clamped: string[] = [];
  return {
    rate: clampOne(input.rate, VOICE_LIMITS.rate, 'rate', clamped),
    pitch: clampOne(input.pitch, VOICE_LIMITS.pitch, 'pitch', clamped),
    voice: typeof input.voice === 'string' ? input.voice : '',
    clamped,
  };
}

/** A sentence for the operator, so a corrected setting is not a silent one. */
export function describePreferences(prefs: VoicePreferences): string {
  if (prefs.clamped.length === 0) {
    return `Speaking at rate ${prefs.rate}, pitch ${prefs.pitch}${prefs.voice ? ` in ${prefs.voice}` : ' in the default voice'}.`;
  }
  return (
    `Adjusted ${prefs.clamped.join(' and ')} to stay inside the range that keeps a spoken alert ` +
    `intelligible: rate ${prefs.rate}, pitch ${prefs.pitch}.`
  );
}
