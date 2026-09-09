/**
 * `startTicker` — a loop that does not stop when the operator looks away.
 *
 * The first version of `useHandGestures` drove the detector from
 * `requestAnimationFrame`, which is the obvious choice and the wrong one here:
 * **browsers stop firing rAF entirely in a hidden tab.** The camera would have
 * stayed open, the hardware light would have stayed on, and not one frame would
 * have been read — a control that looks alive and does nothing, which is the
 * defect shape this repository has spent the most time removing.
 *
 * The owner asked for camera gestures to keep working in the background, so the
 * loop cannot be tied to compositing at all. A dedicated Worker's timers are not
 * throttled the way a hidden document's are, so the tick comes from a Worker and
 * the main thread only does the reading.
 *
 * ## The fallback is reported, not silent
 *
 * A Worker can fail to construct — a CSP that forbids `blob:` workers, an
 * environment without `Worker` at all. Falling back to `setInterval` is right,
 * because a throttled loop beats no loop. Pretending the fallback is equivalent
 * is not: a hidden tab throttles main-thread timers to roughly one a second,
 * which is too slow for a 500ms swipe. `startTicker` says which one it got.
 */

import { describe, expect, it, vi } from 'vitest';

import { startTicker } from '../hub/backgroundTicker';

describe('it ticks', () => {
  it('calls back repeatedly and reports how', async () => {
    const seen: number[] = [];
    const ticker = startTicker(10, () => seen.push(Date.now()));
    await vi.waitFor(() => expect(seen.length).toBeGreaterThan(2), { timeout: 2000 });
    ticker.stop();
    expect(['worker', 'timer']).toContain(ticker.kind);
  });

  it('stops when told, and stopping twice is not a crash', async () => {
    let count = 0;
    const ticker = startTicker(10, () => {
      count += 1;
    });
    await vi.waitFor(() => expect(count).toBeGreaterThan(0), { timeout: 2000 });
    ticker.stop();
    ticker.stop();
    const settled = count;
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(count).toBe(settled);
  });
});

describe('it does not depend on the document being visible', () => {
  it('never touches requestAnimationFrame', async () => {
    // The whole point. rAF does not fire in a hidden tab, so a loop that used
    // it would leave the camera on and read nothing.
    const raf = vi.spyOn(globalThis, 'requestAnimationFrame');
    let count = 0;
    const ticker = startTicker(10, () => {
      count += 1;
    });
    await vi.waitFor(() => expect(count).toBeGreaterThan(1), { timeout: 2000 });
    ticker.stop();
    expect(raf).not.toHaveBeenCalled();
    raf.mockRestore();
  });
});

describe('a worker that cannot be built is a fallback, not a failure', () => {
  it('falls back to a timer and says so', async () => {
    const original = globalThis.Worker;
    // @ts-expect-error — deliberately removing it, the way a CSP would.
    globalThis.Worker = undefined;
    try {
      let count = 0;
      const ticker = startTicker(10, () => {
        count += 1;
      });
      expect(ticker.kind).toBe('timer');
      await vi.waitFor(() => expect(count).toBeGreaterThan(0), { timeout: 2000 });
      ticker.stop();
    } finally {
      globalThis.Worker = original;
    }
  });

  it('a worker that throws on construction still ticks', async () => {
    const original = globalThis.Worker;
    // @ts-expect-error — a CSP refusal looks like this.
    globalThis.Worker = class {
      constructor() {
        throw new DOMException('Refused to create a worker from blob:', 'SecurityError');
      }
    };
    try {
      let count = 0;
      const ticker = startTicker(10, () => {
        count += 1;
      });
      expect(ticker.kind).toBe('timer');
      await vi.waitFor(() => expect(count).toBeGreaterThan(0), { timeout: 2000 });
      ticker.stop();
    } finally {
      globalThis.Worker = original;
    }
  });
});
