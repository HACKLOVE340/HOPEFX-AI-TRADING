/**
 * hub/a11yMotion.ts — §27 reduced motion, decided in one place.
 *
 * Two separate things want to reduce animation: the operator's
 * `prefers-reduced-motion` setting (§27) and the frame budget's measured
 * fidelity (§23). Left apart, they become two policies that disagree — a fast
 * machine animating past somebody's accessibility setting, or a starved
 * machine animating because the setting said it could.
 *
 * `motionFor` takes the lower of the two, and says which one decided.
 *
 * ## The unmeasured preference is not "no preference"
 *
 * `usePrefersReducedMotion` defaults to reduced when it cannot read the media
 * query, because for some people the setting is medical rather than aesthetic:
 * a wrong guess in one direction causes symptoms, and in the other causes
 * disappointment. This module keeps that asymmetry rather than re-deciding it,
 * so a caller that has not read the preference yet gets no motion, not full.
 *
 * That is the opposite default from §22's "an unmeasured metric is absent,
 * never zero", and deliberately so — the same inversion the consent gate and
 * the kill switches make. Where being wrong harms somebody, unreadable means
 * refuse.
 *
 * ## Zero, not one millisecond
 *
 * `index.css` reduces durations to `0.001ms` under the media query, which is
 * the standard trick for keeping `transitionend` firing. That is a CSS
 * concern. A caller asking this module for a duration is about to schedule
 * something in JavaScript, and scheduling a 0.001ms timer is a frame of delay
 * dressed as none — so `none` returns 0 and the caller can skip the animation
 * outright.
 */

import type { Fidelity } from './frameBudget';

export const MOTION_LEVELS = ['full', 'reduced', 'none'] as const;
export type MotionLevel = (typeof MOTION_LEVELS)[number];

/** Lower index is more motion, so `Math.max` of two indices is the lower level. */
const RANK: Readonly<Record<MotionLevel, number>> = Object.freeze({ full: 0, reduced: 1, none: 2 });

/** What each fidelity affords on its own, before the preference is applied. */
const FROM_FIDELITY: Readonly<Record<Fidelity, MotionLevel>> = Object.freeze({
  full: 'full',
  reduced: 'reduced',
  minimal: 'none',
});

/** Multipliers for `scaleDuration`. `reduced` is halved, not merely trimmed. */
const SCALE: Readonly<Record<MotionLevel, number>> = Object.freeze({ full: 1, reduced: 0.5, none: 0 });

export interface MotionInput {
  /**
   * The operator's setting. **Undefined means it has not been read**, which is
   * treated as `true` — see the module docstring.
   */
  prefersReduced?: boolean;
  /** What the machine can currently afford. Defaults to `full`. */
  fidelity?: Fidelity;
}

export interface MotionDecision {
  level: MotionLevel;
  /** Which input decided, in words. A level with no reason cannot be argued with. */
  reason: string;
}

export function motionFor(input: MotionInput = {}): MotionDecision {
  const fidelity: Fidelity = input.fidelity ?? 'full';
  const affordable = FROM_FIDELITY[fidelity];

  if (input.prefersReduced === undefined) {
    return {
      level: 'none',
      reason:
        'the reduced-motion preference could not be read; an unknown setting is treated as reduce, ' +
        'because a wrong guess the other way causes symptoms rather than disappointment',
    };
  }
  if (input.prefersReduced) {
    return { level: 'none', reason: 'the operator prefers reduced motion; this is a floor, not one input among several' };
  }
  return {
    level: affordable,
    reason:
      affordable === 'full'
        ? 'the operator allows motion and the frame budget affords full fidelity'
        : `the frame budget is at ${fidelity} fidelity, so motion is ${affordable}`,
  };
}

/** A duration in milliseconds, scaled to the level. `none` is 0, never 0.001. */
export function scaleDuration(level: MotionLevel, milliseconds: number): number {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return 0;
  return Math.round(milliseconds * SCALE[level]);
}

/** The lower (less motion) of two levels. */
export function lowerOf(a: MotionLevel, b: MotionLevel): MotionLevel {
  return RANK[a] >= RANK[b] ? a : b;
}
