/**
 * hub/backgroundTicker.ts — a loop that keeps running when the tab is hidden.
 *
 * Camera gestures were first driven by `requestAnimationFrame`, which is the
 * obvious choice for anything reading video and the wrong one here: **browsers
 * stop firing rAF entirely in a hidden tab.** Switch to another tab and the
 * camera stays open, the hardware light stays on, and not a single frame is
 * read. The operator sees a console that is plainly watching them and quietly
 * doing nothing — a control that looks alive and is not, which is the defect
 * shape this codebase has spent the most time removing.
 *
 * The owner asked for gestures to keep working in the background, so the tick
 * cannot come from compositing at all.
 *
 * ## Why a Worker
 *
 * A hidden document's `setTimeout`/`setInterval` are throttled to roughly one
 * call a second. A 500ms swipe would get one sample, and `recogniseGesture`
 * needs two. **A dedicated Worker's timers are not throttled that way**, so the
 * tick is posted from a Worker and the main thread only reads the video frame
 * and runs the detector. There is no visibility handling anywhere, and that is
 * deliberate: a loop that switches strategies on `visibilitychange` has two
 * paths, one of which is exercised only when nobody is looking at it.
 *
 * ## The fallback says what it is
 *
 * A Worker can be refused — a CSP without `blob:` in `worker-src`, or an
 * environment with no `Worker`. Falling back to `setInterval` is right, because
 * a throttled loop beats no loop, but `kind` reports which one was obtained so
 * a caller can tell an operator that background gestures will be slow rather
 * than letting them wonder.
 */

export type TickerKind = 'worker' | 'timer';

export interface Ticker {
  /** Which loop was actually obtained. `timer` is throttled when hidden. */
  readonly kind: TickerKind;
  /** Idempotent. */
  stop(): void;
}

/** The Worker's whole program: post a message every `interval` ms. */
const WORKER_SOURCE = `
let handle = null;
self.onmessage = (event) => {
  const data = event.data || {};
  if (data.stop) {
    if (handle !== null) clearInterval(handle);
    handle = null;
    return;
  }
  if (handle !== null) clearInterval(handle);
  handle = setInterval(() => self.postMessage('tick'), data.interval);
};
`;

export function startTicker(intervalMs: number, onTick: () => void): Ticker {
  let stopped = false;

  const worker = makeWorker();
  if (worker !== null) {
    worker.onmessage = () => {
      if (!stopped) onTick();
    };
    worker.postMessage({ interval: intervalMs });
    return {
      kind: 'worker',
      stop() {
        if (stopped) return;
        stopped = true;
        try {
          worker.postMessage({ stop: true });
        } catch {
          // Already gone; terminate below is what matters.
        }
        worker.terminate();
      },
    };
  }

  const handle = setInterval(() => {
    if (!stopped) onTick();
  }, intervalMs);
  return {
    kind: 'timer',
    stop() {
      if (stopped) return;
      stopped = true;
      clearInterval(handle);
    },
  };
}

function makeWorker(): Worker | null {
  try {
    if (typeof Worker === 'undefined' || typeof URL?.createObjectURL !== 'function') return null;
    const url = URL.createObjectURL(new Blob([WORKER_SOURCE], { type: 'text/javascript' }));
    const worker = new Worker(url);
    // Safe immediately: the Worker holds its own reference to the script it was
    // constructed from, and leaving the object URL alive leaks it for the life
    // of the document.
    URL.revokeObjectURL(url);
    return worker;
  } catch {
    // A CSP without blob: in worker-src lands here. Not fatal — see `kind`.
    return null;
  }
}
