/**
 * hub/hostLoad.ts — the two inputs `frameBudget.nextFidelity` never had.
 *
 * The decider was built in Phase D1 and, measured before this file existed,
 * was called from no component at all. It decides correctly given a load
 * sample; nothing produced one. So §26's "pause or reduce animation under
 * load" was a rule with no reading behind it.
 *
 * Both inputs are read here, as pure functions, for the same reason
 * `layout.ts` is pure and `useViewportWidth` is the hook: the part that can be
 * quietly wrong should be testable without a browser and without a server.
 *
 * ## The §22 reading, read properly
 *
 * `GET /api/ai-core/telemetry` returns host CPU as a §22 `Reading`: a value, a
 * `measured` flag, and a reason when it is absent. Reading `value` without
 * checking `measured` is F176 itself — `infrastructure/metrics.py` leaves
 * `system_cpu_percent` unset when psutil is missing, an unset gauge reads back
 * 0.0, and the machine reports itself idle because nobody looked. Here
 * `measured` is the authority, a number beside `measured: false` is refused,
 * and the reason travels with the null so a held fidelity can be explained.
 *
 * ## Why the frame time is a median
 *
 * A single slow frame is noise. A tab regaining focus, one garbage collection,
 * one layout thrash — a mean drags over the 50ms threshold and steps fidelity
 * down for a machine that is fine, then the next sample sends it back. A
 * screen that oscillates between two appearances is worse than one that is
 * consistently reduced, which is the same reasoning `nextFidelity` already
 * applies when it refuses to jump two levels at once.
 *
 * And an interval spanning a hidden tab is not a frame at all: `requestAnimation
 * Frame` stops while the tab is in the background, so the first callback on
 * return is seconds long. Counting it would degrade the plane of somebody who
 * switched away and came back.
 */

/** Longer than this and the gap is a paused tab, not a slow frame. */
const IMPLAUSIBLE_FRAME_MS = 1_000;

/** Frames kept for the median. Five is about a fifth of a second at 30fps. */
const DEFAULT_WINDOW = 5;

export interface HostCpu {
  /** Percent, or null when §22 said it could not be measured. */
  cpu: number | null;
  /** Empty when measured. The stated reason otherwise, so a hold is explainable. */
  reason: string;
}

/**
 * Host CPU out of a telemetry payload.
 *
 * Takes `unknown` on purpose: this is a network boundary, and typing the
 * response as its happy shape would make a malformed payload a render-time
 * crash rather than an unmeasured reading.
 */
export function readHostCpu(payload: unknown): HostCpu {
  const reading = pick(payload, ['host', 'readings', 'cpu']);
  if (reading === undefined || reading === null || typeof reading !== 'object') {
    return { cpu: null, reason: 'the telemetry payload carried no cpu reading' };
  }
  const record = reading as Record<string, unknown>;
  const stated = typeof record.reason === 'string' ? record.reason : '';

  if (record.measured !== true) {
    return { cpu: null, reason: stated || 'the cpu reading says it was not measured' };
  }
  const value = record.value;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 100) {
    // A reading that claims to be measured and carries something that is not a
    // percentage is worse than an absent one: it would be trusted.
    return { cpu: null, reason: `the cpu reading claims to be measured and carries ${String(value)}` };
  }
  return { cpu: value, reason: '' };
}

function pick(source: unknown, path: readonly string[]): unknown {
  let cursor: unknown = source;
  for (const key of path) {
    if (cursor === null || typeof cursor !== 'object') return undefined;
    cursor = (cursor as Record<string, unknown>)[key];
  }
  return cursor;
}

export interface SamplerOptions {
  /** How many frames the median is taken over. */
  window?: number;
}

/**
 * A rolling median of frame intervals.
 *
 * Fed timestamps, not durations, so the caller hands `requestAnimationFrame`'s
 * argument straight in and the interval arithmetic lives in one place.
 */
export class FrameSampler {
  private readonly window: number;
  private readonly intervals: number[] = [];
  private last: number | null = null;

  constructor(options: SamplerOptions = {}) {
    this.window = Math.max(1, Math.floor(options.window ?? DEFAULT_WINDOW));
  }

  record(timestampMs: number): void {
    if (!Number.isFinite(timestampMs)) return;
    const previous = this.last;
    this.last = timestampMs;
    if (previous === null) return;
    const interval = timestampMs - previous;
    // Negative: a timestamp origin changed under us. Implausible: a paused tab.
    if (interval <= 0 || interval > IMPLAUSIBLE_FRAME_MS) return;
    this.intervals.push(interval);
    while (this.intervals.length > this.window) this.intervals.shift();
  }

  /**
   * The median interval, or null.
   *
   * Null until the window is full, because a median of two frames is not a
   * trend — and §22's rule applies to the browser too: an unmeasured metric is
   * absent, never zero. `nextFidelity` holds on null, which is the right thing
   * to do while the page is still starting up.
   */
  get frameMs(): number | null {
    if (this.intervals.length < this.window) return null;
    const sorted = [...this.intervals].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    const value =
      sorted.length % 2 === 1
        ? sorted[middle]!
        : ((sorted[middle - 1]! + sorted[middle]!) / 2);
    return Math.round(value);
  }

  /** Forget everything. A tab that has just been resumed has no useful history. */
  reset(): void {
    this.intervals.length = 0;
    this.last = null;
  }
}
