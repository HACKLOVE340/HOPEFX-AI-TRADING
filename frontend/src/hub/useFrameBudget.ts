/**
 * hub/useFrameBudget.ts — the loop that asks `nextFidelity` a question.
 *
 * §26 asks the plane to pause or reduce animation under load. Phase D1 built
 * the decider and Phase H2 built the two readings; this is the only place they
 * meet a real browser and a real server.
 *
 * ## It costs nothing while nothing is wrong
 *
 * A frame-timing loop that runs `requestAnimationFrame` forever is itself a
 * cost, and one paid on exactly the loaded machine it is meant to help. So the
 * sampler runs on a coarse cadence — a burst of frames, then a rest — rather
 * than every frame for the life of the page.
 *
 * ## It stops when nobody is looking
 *
 * `requestAnimationFrame` is throttled or stopped in a hidden tab, and the
 * telemetry poll on a background tab is a request nobody reads. Both stop on
 * `visibilitychange`, and the sampler is reset on return: the history from
 * before the tab was hidden describes a different situation.
 *
 * ## A failed poll is an unmeasured reading, never a busy machine
 *
 * A 401, a network drop, a server without psutil — all of them produce
 * `cpu: null` with a reason, and `nextFidelity` holds. The alternative would
 * degrade the plane because a fetch failed, which trains an operator to ignore
 * the indicator that is meant to warn them.
 */

import { useEffect, useRef, useState } from 'react';

import { nextFidelity, type Fidelity } from './frameBudget';
import { FrameSampler, readHostCpu } from './hostLoad';

/** How often host CPU is polled. Slow: it is a trend, and each poll costs a request. */
const DEFAULT_POLL_MS = 15_000;

/** Frames sampled per burst. Enough to fill the sampler's window. */
const BURST_FRAMES = 8;

/** Rest between bursts. The sampler is asleep for the whole of it. */
const BURST_REST_MS = 4_000;

export interface FrameBudget {
  fidelity: Fidelity;
  /** Why it is what it is. Always populated — a degraded screen is explainable. */
  reason: string;
  /** The last host reading, or null. Null is a fact, not a zero. */
  cpu: number | null;
  /** The last measured frame median, or null while the sampler is filling. */
  frameMs: number | null;
}

export interface FrameBudgetOptions {
  /** Off by default at the call site's discretion — a hidden plane needs no loop. */
  enabled?: boolean;
  /** Caps fidelity outright. Passed through to `nextFidelity`, which owns the rule. */
  reducedMotion?: boolean;
  pollMs?: number;
  /** Injected in tests. Production passes nothing and gets `window.fetch`. */
  fetcher?: typeof fetch;
}

export function useFrameBudget(options: FrameBudgetOptions = {}): FrameBudget {
  const { enabled = true, reducedMotion, pollMs = DEFAULT_POLL_MS, fetcher } = options;

  const [budget, setBudget] = useState<FrameBudget>({
    fidelity: 'full',
    reason: 'nothing has been measured yet, so fidelity holds at full',
    cpu: null,
    frameMs: null,
  });

  // The sampler and the last reading live in refs: they change many times per
  // second and rendering on each would be the cost this hook exists to avoid.
  const sampler = useRef<FrameSampler | null>(null);
  if (sampler.current === null) sampler.current = new FrameSampler();
  const cpu = useRef<{ value: number | null; reason: string }>({
    value: null,
    reason: 'host telemetry has not been read yet',
  });
  const fidelity = useRef<Fidelity>('full');

  // -- host cpu --------------------------------------------------------------
  useEffect(() => {
    if (!enabled) return undefined;
    const get = fetcher ?? (typeof fetch === 'function' ? fetch : null);
    if (get === null) {
      cpu.current = { value: null, reason: 'this environment has no fetch, so host load cannot be read' };
      return undefined;
    }
    let alive = true;

    const poll = async () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      try {
        const response = await get('/api/ai-core/telemetry', { credentials: 'same-origin' });
        if (!response.ok) {
          cpu.current = { value: null, reason: `host telemetry returned ${response.status}` };
          return;
        }
        const read = readHostCpu(await response.json());
        if (alive) cpu.current = { value: read.cpu, reason: read.reason };
      } catch (error) {
        // Never a busy machine. See the module docstring.
        cpu.current = {
          value: null,
          reason: `host telemetry could not be read (${error instanceof Error ? error.name : 'unknown error'})`,
        };
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), Math.max(1_000, pollMs));
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [enabled, pollMs, fetcher]);

  // -- frame timing, in bursts ----------------------------------------------
  useEffect(() => {
    if (!enabled) return undefined;
    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') return undefined;

    let raf = 0;
    let rest = 0;
    let taken = 0;
    let stopped = false;

    const decide = () => {
      const measured = sampler.current!.frameMs;
      const step = nextFidelity({
        current: fidelity.current,
        cpu: cpu.current.value,
        frameMs: measured,
        reducedMotion,
      });
      fidelity.current = step.fidelity;
      const why = step.reason || cpu.current.reason;
      setBudget((previous) =>
        previous.fidelity === step.fidelity &&
        previous.reason === why &&
        previous.cpu === cpu.current.value &&
        previous.frameMs === measured
          ? previous
          : { fidelity: step.fidelity, reason: why, cpu: cpu.current.value, frameMs: measured },
      );
    };

    const frame = (timestamp: number) => {
      if (stopped) return;
      sampler.current!.record(timestamp);
      taken += 1;
      if (taken < BURST_FRAMES) {
        raf = window.requestAnimationFrame(frame);
        return;
      }
      decide();
      taken = 0;
      // A burst then a rest. Sampling every frame forever costs the loaded
      // machine the very frames this is trying to protect.
      rest = window.setTimeout(() => {
        if (stopped) return;
        raf = window.requestAnimationFrame(frame);
      }, BURST_REST_MS);
    };

    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        window.cancelAnimationFrame(raf);
        window.clearTimeout(rest);
        // The history describes a tab that was in the foreground. Keeping it
        // would decide the next fidelity from frames measured before a gap.
        sampler.current!.reset();
        taken = 0;
      } else if (!stopped) {
        raf = window.requestAnimationFrame(frame);
      }
    };

    raf = window.requestAnimationFrame(frame);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stopped = true;
      window.cancelAnimationFrame(raf);
      window.clearTimeout(rest);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, reducedMotion]);

  return budget;
}
