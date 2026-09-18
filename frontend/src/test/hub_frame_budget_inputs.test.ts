/**
 * Phase H2 — §26, the inputs `nextFidelity` never had.
 *
 * `frameBudget.ts` was built in Phase D1 and decides correctly given a load
 * sample. Measured now, nothing produces one: `nextFidelity` is called from no
 * component, so the whole resource-aware rendering row was a decider with no
 * question put to it.
 *
 * Two things have to arrive before it can decide, and each has its own way of
 * being quietly wrong:
 *
 *   host CPU     `GET /api/ai-core/telemetry` returns a §22 Reading, whose
 *                `value` is null with a reason when unmeasured — and reading
 *                `value` without checking `measured` is F176 exactly, the
 *                0%-CPU gauge that decides the machine is idle.
 *
 *   frame time   the browser's own timing. A single slow frame is noise; a
 *                per-frame reading would send fidelity oscillating between two
 *                appearances, which is worse than being consistently reduced.
 *
 * Both are pure functions here so they are testable without a browser and
 * without a server, which is the same split `layout.ts` and `useViewportWidth`
 * already hold.
 */

import { describe, expect, it } from 'vitest';

import { FrameSampler, readHostCpu } from '../hub/hostLoad';
import { nextFidelity } from '../hub/frameBudget';

describe('§26 readHostCpu — measured, or null with the reason', () => {
  it('reads a measured value', () => {
    const payload = {
      host: { readings: { cpu: { name: 'cpu', value: 73.5, unit: '%', reason: '', measured: true, at: 1 } } },
    };
    expect(readHostCpu(payload)).toEqual({ cpu: 73.5, reason: '' });
  });

  it('returns null and the stated reason when the probe could not run', () => {
    // The exact shape §22 produces when psutil is missing. Reading `value`
    // here yields null, which coerces to 0 in enough JavaScript paths that
    // "unmeasured" becomes "idle" — the defect the whole section exists for.
    const payload = {
      host: {
        readings: {
          cpu: { name: 'cpu', value: null, unit: '%', reason: 'psutil is not installed', measured: false, at: 1 },
        },
      },
    };
    const read = readHostCpu(payload);
    expect(read.cpu).toBeNull();
    expect(read.reason).toContain('psutil');
  });

  it('refuses a value whose reading says it was not measured, even when a number is present', () => {
    // Belt and braces: `measured` is the authority, not the presence of a
    // number. A stale value left in the field must not be read as current.
    const payload = {
      host: { readings: { cpu: { name: 'cpu', value: 12, unit: '%', reason: 'stale', measured: false, at: 1 } } },
    };
    expect(readHostCpu(payload).cpu).toBeNull();
  });

  it('says so for a payload with no cpu reading at all', () => {
    expect(readHostCpu({ host: { readings: {} } }).cpu).toBeNull();
    expect(readHostCpu({}).cpu).toBeNull();
    expect(readHostCpu(null).cpu).toBeNull();
    expect(readHostCpu(null).reason).toMatch(/no cpu reading|not present|could not/i);
  });

  it('refuses a value outside the range a percentage can take', () => {
    const bad = (value: unknown) => ({
      host: { readings: { cpu: { name: 'cpu', value, unit: '%', reason: '', measured: true, at: 1 } } },
    });
    expect(readHostCpu(bad(-1)).cpu).toBeNull();
    expect(readHostCpu(bad(101)).cpu).toBeNull();
    expect(readHostCpu(bad('busy')).cpu).toBeNull();
    expect(readHostCpu(bad(Number.NaN)).cpu).toBeNull();
    // 0 and 100 are both real readings and must survive.
    expect(readHostCpu(bad(0)).cpu).toBe(0);
    expect(readHostCpu(bad(100)).cpu).toBe(100);
  });
});

describe('§26 FrameSampler — a trend, not the last frame', () => {
  it('reports nothing until it has enough frames to mean something', () => {
    const sampler = new FrameSampler();
    expect(sampler.frameMs).toBeNull();
    sampler.record(0);
    // One timestamp is not an interval.
    expect(sampler.frameMs).toBeNull();
  });

  it('reports the median of the window once it has one', () => {
    const sampler = new FrameSampler({ window: 5 });
    // Intervals of 16, 16, 16, 16, 16 ms.
    for (let i = 0; i <= 5; i += 1) sampler.record(i * 16);
    expect(sampler.frameMs).toBe(16);
  });

  it('is not moved by a single slow frame', () => {
    // The reason it is a median and not a mean: one 400ms frame (a tab
    // regaining focus, a garbage collection) would drag a mean over the slow
    // threshold and step fidelity down for a machine that is fine.
    const sampler = new FrameSampler({ window: 5 });
    let t = 0;
    for (let i = 0; i < 4; i += 1) {
      t += 16;
      sampler.record(t);
    }
    t += 400;
    sampler.record(t);
    t += 16;
    sampler.record(t);
    expect(sampler.frameMs).toBeLessThan(50);
  });

  it('does report a sustained slow frame rate', () => {
    const sampler = new FrameSampler({ window: 5 });
    for (let i = 0; i <= 6; i += 1) sampler.record(i * 90);
    expect(sampler.frameMs).toBe(90);
  });

  it('drops an interval that spans a hidden tab rather than calling it a slow frame', () => {
    // rAF stops while a tab is hidden, so the first frame back is seconds
    // long. Counting that would degrade the plane of somebody who simply
    // switched away and came back.
    const sampler = new FrameSampler({ window: 5 });
    let t = 0;
    // Six timestamps make five intervals, which is a full window. Five would
    // leave the sampler reporting null and the assertion below would pass for
    // the wrong reason.
    for (let i = 0; i < 6; i += 1) {
      t += 16;
      sampler.record(t);
    }
    expect(sampler.frameMs).toBe(16);
    t += 30_000;
    sampler.record(t);
    expect(sampler.frameMs).toBe(16);
  });

  it('forgets on demand, because a resumed tab has no useful history', () => {
    const sampler = new FrameSampler({ window: 5 });
    for (let i = 0; i <= 5; i += 1) sampler.record(i * 90);
    expect(sampler.frameMs).toBe(90);
    sampler.reset();
    expect(sampler.frameMs).toBeNull();
  });
});

describe('§26 the two inputs, given to the decider they were built for', () => {
  it('holds fidelity when neither input was measured', () => {
    const cpu = readHostCpu(null).cpu;
    const frameMs = new FrameSampler().frameMs;
    const step = nextFidelity({ current: 'full', cpu, frameMs, reducedMotion: false });
    expect(step.fidelity).toBe('full');
    expect(step.changed).toBe(false);
    expect(step.reason).toMatch(/unmeasured/i);
  });

  it('steps down on a measured, sustained slow frame rate', () => {
    const sampler = new FrameSampler({ window: 5 });
    for (let i = 0; i <= 6; i += 1) sampler.record(i * 90);
    const step = nextFidelity({ current: 'full', cpu: null, frameMs: sampler.frameMs, reducedMotion: false });
    expect(step.fidelity).toBe('reduced');
    expect(step.reason).toContain('90');
  });
});
