/**
 * Regression tests: the client must be able to detect a stalled feed.
 *
 * Round 3 audit findings S9-01 and S10-05 (docs/HARDENING_BACKLOG.md).
 *
 * `lastHeartbeat` was written to the store on every server heartbeat and read
 * nowhere outside test files — no component, selector or interval ever
 * compared it against `Date.now()`. The `noLiveFeed` banner is not a
 * substitute: it fires only when the *server explicitly sends* that condition,
 * which a stalled server cannot do.
 *
 * So when the server's broadcast loop blocked on one slow socket (S8-01), the
 * WebSocket stayed OPEN at the TCP level, `wsStatus` stayed `'connected'`,
 * `onclose` never fired, and the UI kept rendering the last price it received
 * — indefinitely, under a green indicator, with no age shown anywhere.
 * `LivePriceTicker.tsx` contains no timestamp, age, or `Date.now` reference at
 * all, so there was no per-price fallback either.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';

describe('feed staleness state (S9-01)', () => {
  beforeEach(() => {
    useStore.setState({
      wsStatus: 'connected',
      lastHeartbeat: null,
      lastDataAt: null,
      feedStale: false,
    });
  });

  it('exposes the state a stall detector needs', () => {
    const s = useStore.getState();
    expect(s).toHaveProperty('lastDataAt');
    expect(s).toHaveProperty('feedStale');
    expect(typeof s.markDataReceived).toBe('function');
    expect(typeof s.setFeedStale).toBe('function');
  });

  it('records the arrival time of any data message', () => {
    const before = Date.now();
    useStore.getState().markDataReceived();
    const { lastDataAt } = useStore.getState();
    expect(lastDataAt).not.toBeNull();
    expect(lastDataAt as number).toBeGreaterThanOrEqual(before);
  });

  it('clears staleness when data arrives again', () => {
    useStore.getState().setFeedStale(true);
    expect(useStore.getState().feedStale).toBe(true);

    useStore.getState().markDataReceived();
    expect(useStore.getState().feedStale).toBe(false);
  });

  it('treats a heartbeat as evidence the feed is alive', () => {
    useStore.getState().setFeedStale(true);
    useStore.getState().setHeartbeat(Date.now());

    const s = useStore.getState();
    expect(s.feedStale).toBe(false);
    expect(s.lastDataAt).not.toBeNull();
  });

  it('can represent "connected but stalled" — the state that had no expression', () => {
    // The exact S8-01 scenario: socket open, nothing arriving.
    useStore.setState({
      wsStatus: 'connected',
      noLiveFeed: false,
      lastDataAt: Date.now() - 120_000,
    });
    useStore.getState().setFeedStale(true);

    const s = useStore.getState();
    expect(s.wsStatus).toBe('connected');
    expect(s.noLiveFeed).toBe(false);
    expect(s.feedStale).toBe(true);
  });
});
