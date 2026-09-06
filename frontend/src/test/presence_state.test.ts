/**
 * What the presence is doing, derived from what the system is doing.
 *
 * The existing `HologramPanel` sets its own state with `setState('analyzing')`
 * and no request is made — it narrates an analysis that never happened. That
 * comment is in the file. This module is the fix generalised: presence state is
 * a pure function of real inputs, so it cannot claim something the system is not
 * doing.
 *
 * Two properties the tests below exist for:
 *
 * - **Every state carries a reason.** A presence that cannot say why it looks
 *   alarmed is a decorative badge. The reason is what the caption reads out and
 *   what a screen reader announces.
 * - **Precedence is explicit and tested.** Several inputs are true at once far
 *   more often than not — a job runs while the mic is open while the feed is
 *   stale — and "whichever branch was written first" is not a design.
 */

import { describe, it, expect } from 'vitest';
import { derivePresence, PRESENCE_STATES, type PresenceInputs } from '../hub/presence';

const calm: PresenceInputs = {
  wsStatus: 'connected',
  feedStale: false,
  micOpen: false,
  speaking: false,
  jobsRunning: 0,
  jobsQueued: 0,
  riskHeadroom: 0.68,
  alert: null,
  providersReachable: 3,
};

describe('the resting state', () => {
  it('is idle when nothing is happening', () => {
    expect(derivePresence(calm).state).toBe('idle');
  });

  it('says why, even at rest', () => {
    // "All clear" with no statement of what was checked has told you nothing.
    expect(derivePresence(calm).reason).toMatch(/\w{4,}/);
  });

  it('names every state in one exported list', () => {
    // So the renderer cannot silently lack an animation for a state the
    // machine can produce.
    for (const s of PRESENCE_STATES) expect(typeof s).toBe('string');
    expect(PRESENCE_STATES).toContain('idle');
    expect(PRESENCE_STATES).toContain('alerting');
  });

  it('only ever returns a state from that list', () => {
    const cases: PresenceInputs[] = [
      calm,
      { ...calm, micOpen: true },
      { ...calm, speaking: true },
      { ...calm, jobsRunning: 2 },
      { ...calm, feedStale: true },
      { ...calm, wsStatus: 'disconnected' },
      { ...calm, providersReachable: 0 },
      { ...calm, riskHeadroom: 0.02 },
      { ...calm, alert: { severity: 'critical', text: 'kill switch tripped' } },
      { ...calm, riskHeadroom: null },
    ];
    for (const c of cases) {
      expect(PRESENCE_STATES).toContain(derivePresence(c).state);
    }
  });
});

describe('conversation states', () => {
  it('is listening while the microphone is open', () => {
    expect(derivePresence({ ...calm, micOpen: true }).state).toBe('listening');
  });

  it('is speaking while it speaks', () => {
    expect(derivePresence({ ...calm, speaking: true }).state).toBe('speaking');
  });

  it('is thinking while work is in flight and it has nothing to say yet', () => {
    const p = derivePresence({ ...calm, jobsRunning: 1 });
    expect(p.state).toBe('thinking');
    expect(p.reason).toMatch(/1/);
  });

  it('counts queued work as thinking too', () => {
    // A queued job is work the operator asked for and is waiting on. Showing
    // idle would say nothing is happening.
    expect(derivePresence({ ...calm, jobsQueued: 3 }).state).toBe('thinking');
  });

  it('prefers listening over speaking, because barge-in means the user won', () => {
    // If both are true the user has interrupted. The presence must follow the
    // user, not talk over them.
    expect(derivePresence({ ...calm, micOpen: true, speaking: true }).state).toBe('listening');
  });

  it('prefers speaking over thinking', () => {
    // It is answering from work already done; the spinner is over.
    expect(derivePresence({ ...calm, speaking: true, jobsRunning: 2 }).state).toBe('speaking');
  });
});

describe('something is wrong', () => {
  it('is offline when the socket is down', () => {
    const p = derivePresence({ ...calm, wsStatus: 'disconnected' });
    expect(p.state).toBe('offline');
    expect(p.reason).toMatch(/connect|offline|lost/i);
  });

  it('treats a socket error as offline, not as connected', () => {
    // The store has four ws statuses, not three. `error` was missing from this
    // machine until the type checker said so; untreated it would have fallen
    // through to idle and drawn a calm presence over a dead socket.
    const p = derivePresence({ ...calm, wsStatus: 'error' });
    expect(p.state).toBe('offline');
    expect(p.tone).toBe('dead');
  });

  it('is degraded when the feed has gone stale', () => {
    const p = derivePresence({ ...calm, feedStale: true });
    expect(p.state).toBe('degraded');
    expect(p.reason).toMatch(/stale|old/i);
  });

  it('is degraded when no model vendor can answer', () => {
    // The feed is not the model. Degraded, not offline — prices still work.
    const p = derivePresence({ ...calm, providersReachable: 0 });
    expect(p.state).toBe('degraded');
    expect(p.reason).toMatch(/model|vendor/i);
  });

  it('alerts on a critical system event', () => {
    const p = derivePresence({ ...calm, alert: { severity: 'critical', text: 'kill switch tripped' } });
    expect(p.state).toBe('alerting');
    expect(p.reason).toContain('kill switch tripped');
  });

  it('alerts when risk headroom is nearly gone', () => {
    const p = derivePresence({ ...calm, riskHeadroom: 0.04 });
    expect(p.state).toBe('alerting');
    expect(p.reason).toMatch(/risk|limit/i);
  });

  it('does not alert on comfortable headroom', () => {
    expect(derivePresence({ ...calm, riskHeadroom: 0.5 }).state).toBe('idle');
  });
});

describe('precedence, which is the whole design', () => {
  it('offline beats everything — nothing on screen can be trusted', () => {
    const p = derivePresence({
      ...calm, wsStatus: 'disconnected', micOpen: true, speaking: true,
      jobsRunning: 4, riskHeadroom: 0.01,
      alert: { severity: 'critical', text: 'anything' },
    });
    expect(p.state).toBe('offline');
  });

  it('an alert beats conversation — it is why you would interrupt someone', () => {
    const p = derivePresence({
      ...calm, micOpen: true, speaking: true, jobsRunning: 2,
      alert: { severity: 'critical', text: 'drawdown limit' },
    });
    expect(p.state).toBe('alerting');
  });

  it('conversation beats a degraded feed', () => {
    // A stale price does not stop it hearing you. Degrading the microphone
    // because a chart is old would be the tail wagging the dog.
    expect(derivePresence({ ...calm, feedStale: true, micOpen: true }).state).toBe('listening');
  });

  it('an informational alert does not outrank conversation', () => {
    // Only severity that warrants interruption interrupts. §19.
    const p = derivePresence({
      ...calm, micOpen: true,
      alert: { severity: 'informational', text: 'a model finished retraining' },
    });
    expect(p.state).toBe('listening');
  });
});

describe('what the renderer needs', () => {
  it('reports a normalised intensity the animation can be driven by', () => {
    // So the visual layer never has to interpret business state itself —
    // §30-J, business logic separate from animation.
    const idle = derivePresence(calm);
    const busy = derivePresence({ ...calm, jobsRunning: 4 });
    expect(idle.intensity).toBeGreaterThanOrEqual(0);
    expect(idle.intensity).toBeLessThanOrEqual(1);
    expect(busy.intensity).toBeGreaterThan(idle.intensity);
  });

  it('reports a tone so colour is chosen from meaning, not from the state name', () => {
    expect(derivePresence(calm).tone).toBe('ok');
    expect(derivePresence({ ...calm, feedStale: true }).tone).toBe('warn');
    expect(derivePresence({ ...calm, riskHeadroom: 0.02 }).tone).toBe('bad');
    expect(derivePresence({ ...calm, wsStatus: 'disconnected' }).tone).toBe('dead');
  });

  it('is a pure function — the same inputs give the same answer', () => {
    const a = derivePresence({ ...calm, jobsRunning: 2 });
    const b = derivePresence({ ...calm, jobsRunning: 2 });
    expect(a).toEqual(b);
  });

  it('survives missing risk data rather than inventing headroom', () => {
    // null means unknown. Treating unknown as 100% would draw a full ring for
    // a number nobody has.
    const p = derivePresence({ ...calm, riskHeadroom: null });
    expect(p.state).toBe('idle');
    expect(p.headroomKnown).toBe(false);
  });
});
