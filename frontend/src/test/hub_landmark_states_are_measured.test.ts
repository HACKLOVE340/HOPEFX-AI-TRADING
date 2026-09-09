/**
 * `landmarkStatus` reported "your browser cannot run it" about a runtime it
 * had never tried to load.
 *
 * The four states exist so an operator whose camera gesture does nothing learns
 * WHICH absence it is. `landmarks.ts` says so itself: collapsing them "sends
 * them to look for a fault that is not there".
 *
 * It then did exactly that. The runtime branch read
 *
 *     if (input.runtimeAvailable !== true) return { state: 'unsupported', ... }
 *
 * with the comment "an unmeasured runtime is absent, never present" — which is
 * half of Rule 2. Not claiming an unprobed runtime WORKS is right. Reporting it
 * as BROKEN is the same error pointed the other way: a value nobody measured
 * stated as a negative fact.
 *
 * It surfaced the moment a real detector existed. `HandDetector` deliberately
 * does not load the runtime before consent — downloading a detector for someone
 * who has not agreed is the thing §25 forbids — so in the ordinary
 * "hasn't said yes yet" case `runtimeAvailable` is undefined, and every one of
 * those operators was told their browser was incapable.
 *
 * `unsupported` now means probed and failed. Nothing else can produce it.
 */

import { describe, expect, it } from 'vitest';

import { landmarkStatus } from '../hub/landmarks';

const MODEL = '/models/hand_landmarker.task';

describe('unsupported is a measurement, not a default', () => {
  it('an unprobed runtime is not reported as unsupported', () => {
    const status = landmarkStatus({ modelUrl: MODEL });
    expect(status.state).not.toBe('unsupported');
  });

  it('an unprobed runtime with no consent reports the consent it is waiting on', () => {
    const status = landmarkStatus({ modelUrl: MODEL });
    expect(status.state).toBe('unpermitted');
    expect(status.reason).toContain('not been permitted');
  });

  it('a runtime that was probed and failed is unsupported', () => {
    const status = landmarkStatus({ modelUrl: MODEL, runtimeAvailable: false, consented: true });
    expect(status.state).toBe('unsupported');
    expect(status.reason).toContain('cannot run it');
  });

  it('still refuses to call an unprobed runtime available', () => {
    // The half of the original rule that was right, kept.
    const status = landmarkStatus({ modelUrl: MODEL, consented: true });
    expect(status.state).not.toBe('measured');
  });
});

describe('the earlier prerequisites still come first', () => {
  it('no model deployed outranks everything', () => {
    expect(landmarkStatus({ runtimeAvailable: false, consented: true }).state).toBe('unconfigured');
  });

  it('consented and running but nothing arriving is still unpermitted, and says why', () => {
    const status = landmarkStatus({ modelUrl: MODEL, runtimeAvailable: true, consented: true });
    expect(status.state).toBe('unpermitted');
    expect(status.reason).toContain('no landmarks have arrived');
  });

  it('measured needs all four', () => {
    const status = landmarkStatus({
      modelUrl: MODEL,
      runtimeAvailable: true,
      consented: true,
      receiving: true,
    });
    expect(status.state).toBe('measured');
    expect(status.reason).toBe('');
  });
});
