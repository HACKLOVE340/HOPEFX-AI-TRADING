/**
 * hub/frameBudget.ts — how much fidelity the machine can currently afford.
 *
 * §23 asks for "resource-aware rendering and frame-rate protection". The inputs
 * come from §22: `GET /api/ai-core/telemetry` for host load, and the browser's
 * own frame timing for what the operator is actually experiencing.
 *
 * ## Holding is a decision, and it is the right one when nothing was measured
 *
 * §22's rule is that an unmeasured metric is absent, never zero. Applied here,
 * neither guess is safe:
 *
 *   assume idle    → full fidelity because the probe failed, which is the 0%
 *                    CPU gauge deciding to start more work
 *   assume loaded  → a degraded screen on a fast machine because a number was
 *                    missing, which trains people to ignore the indicator
 *
 * So an unmeasured load changes nothing. The current fidelity holds, `changed`
 * is false, and the reason says the input was missing — which is a state
 * somebody can see and act on, unlike either guess.
 *
 * ## One step at a time
 *
 * A jump straight to `minimal` on a single slow frame is a visible lurch, and
 * the next measurement sends it straight back — a screen that oscillates
 * between two appearances is worse than one that is consistently reduced.
 *
 * ## Reduced motion is a floor, not a weight
 *
 * `usePrefersReducedMotion` defaults to no-motion when it cannot read the
 * query, because for some people the setting is medical rather than aesthetic.
 * Here it caps fidelity outright rather than being one input among several: a
 * fast machine must not animate its way past somebody's accessibility setting.
 */

export const FIDELITIES = ['full', 'reduced', 'minimal'] as const;
export type Fidelity = (typeof FIDELITIES)[number];

export interface LoadSample {
  current: Fidelity;
  /** Host CPU percentage, or null when §22 reported it unmeasured. */
  cpu: number | null;
  /** Milliseconds for the last frame, or null when not sampled. */
  frameMs: number | null;
  reducedMotion?: boolean;
}

export interface FidelityStep {
  fidelity: Fidelity;
  changed: boolean;
  /** Always populated, so a degraded screen is explainable rather than mysterious. */
  reason: string;
}

/** Above this the machine is struggling. */
const CPU_HIGH = 85;
/** Below this it has room to spare. */
const CPU_LOW = 40;
/** A frame slower than this is visible to the operator. 50ms is ~20fps. */
const FRAME_SLOW_MS = 50;
/** Comfortably inside a 60fps budget. */
const FRAME_FAST_MS = 20;

/** The best fidelity reduced motion allows. */
const REDUCED_MOTION_CEILING: Fidelity = 'reduced';

function step(from: Fidelity, direction: -1 | 1): Fidelity {
  const index = FIDELITIES.indexOf(from);
  const next = Math.min(FIDELITIES.length - 1, Math.max(0, index + direction));
  return FIDELITIES[next] as Fidelity;
}

function atLeastAsReducedAs(a: Fidelity, b: Fidelity): Fidelity {
  return FIDELITIES.indexOf(a) >= FIDELITIES.indexOf(b) ? a : b;
}

export function nextFidelity(sample: LoadSample): FidelityStep {
  const { current, cpu, frameMs } = sample;

  if (sample.reducedMotion === true) {
    const capped = atLeastAsReducedAs(current, REDUCED_MOTION_CEILING);
    return {
      fidelity: capped,
      changed: capped !== current,
      reason: 'reduced motion is set, which caps fidelity regardless of how much headroom the machine has',
    };
  }

  const measured = cpu !== null || frameMs !== null;
  if (!measured) {
    return {
      fidelity: current,
      changed: false,
      reason:
        'load is unmeasured, so fidelity holds: assuming an idle machine would be the 0% CPU gauge deciding ' +
        'to start more work, and assuming a busy one would degrade a fast machine over a missing number',
    };
  }

  const struggling = (cpu !== null && cpu >= CPU_HIGH) || (frameMs !== null && frameMs >= FRAME_SLOW_MS);
  if (struggling) {
    const next = step(current, 1);
    const why =
      frameMs !== null && frameMs >= FRAME_SLOW_MS
        ? `the last frame took ${frameMs}ms, which the operator can see`
        : `host cpu is ${cpu}%`;
    return {
      fidelity: next,
      changed: next !== current,
      reason: next === current ? `${why}; already at the lowest fidelity` : `${why}; stepping down one level`,
    };
  }

  const roomy = (cpu === null || cpu <= CPU_LOW) && (frameMs === null || frameMs <= FRAME_FAST_MS);
  if (roomy) {
    const next = step(current, -1);
    return {
      fidelity: next,
      changed: next !== current,
      reason:
        next === current
          ? 'there is headroom and fidelity is already full'
          : 'there is headroom; stepping up one level rather than jumping, so the screen does not oscillate',
    };
  }

  return { fidelity: current, changed: false, reason: 'load is between the thresholds; holding' };
}
