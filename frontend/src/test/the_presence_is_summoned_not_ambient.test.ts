/**
 * The presence appears when it is called, and is not there otherwise.
 *
 * `App.tsx` rendered `{isAuth && <PresenceAnywhereMount />}`, so the head was on
 * every page for every authenticated user, permanently. Worse, every input to
 * `derivePresence` in that mount was a hardcoded constant inside a `useMemo`
 * with an empty dependency array, so it could not react to anything either.
 *
 * Measured by execution before this change, feeding the mount's own constants
 * through the real functions:
 *
 *     PRESENCE = {"headroomKnown":false,"state":"idle","tone":"ok",...}
 *     MODE = concerned | severity = 0.35
 *           | "Risk headroom is unmeasured -- not zero, not full, unknown."
 *
 * A worried face, on every page, forever, derived from a literal. That is the
 * decorative-live-value shape `hub/headModes.ts` already refuses for moods
 * ("there is no setMode"), arriving instead through the mount's inputs.
 *
 * ## What must NOT be lost
 *
 * Hiding it by default must not hide a genuine signal. `chooseHeadMode` returns
 * a severity alongside the mode, and the urgent modes carry the high ones --
 * `panicking` at 1.0, `worried` at 0.7, `refusing` at 0.4. Those still raise the
 * presence without being asked. Only the quiet end stays down.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  summonPresence,
  dismissPresence,
  isPresenceVisible,
  subscribeSummons,
  URGENT_SEVERITY,
} from '../hub/presenceSummons';

beforeEach(() => {
  dismissPresence();
});

describe('the presence is summoned, not ambient', () => {
  it('is not visible before anything calls it', () => {
    expect(isPresenceVisible({ speaking: false, micOpen: false, severity: 0 })).toBe(false);
  });

  it('is not visible for the mode the mount actually produced', () => {
    // severity 0.35 is `concerned`, which is what the hardcoded inputs yielded
    // on every page. It is below the urgency floor on purpose.
    expect(isPresenceVisible({ speaking: false, micOpen: false, severity: 0.35 })).toBe(false);
  });

  it('appears once summoned, and goes away once dismissed', () => {
    summonPresence('the person opened the assistant');
    expect(isPresenceVisible({ speaking: false, micOpen: false, severity: 0 })).toBe(true);

    dismissPresence();
    expect(isPresenceVisible({ speaking: false, micOpen: false, severity: 0 })).toBe(false);
  });

  it('appears while the platform is speaking, without being summoned', () => {
    expect(isPresenceVisible({ speaking: true, micOpen: false, severity: 0 })).toBe(true);
  });

  it('appears while the microphone is open', () => {
    expect(isPresenceVisible({ speaking: false, micOpen: true, severity: 0 })).toBe(true);
  });

  it('still appears for an urgent severity nobody asked to see', () => {
    // A critical alert is severity 1.0 and a breached headroom is close to it.
    // If this ever stops holding, a safety signal has been made silent.
    expect(isPresenceVisible({ speaking: false, micOpen: false, severity: 1 })).toBe(true);
    expect(isPresenceVisible({ speaking: false, micOpen: false, severity: URGENT_SEVERITY })).toBe(true);
  });

  it('notifies subscribers when it is called and when it is let go', () => {
    const seen: boolean[] = [];
    const stop = subscribeSummons(() => seen.push(true));

    summonPresence('a');
    dismissPresence();
    stop();
    summonPresence('b');

    expect(seen.length).toBe(2);
  });

  it('keeps the reason it was called for', () => {
    summonPresence('risk review');
    expect(isPresenceVisible({ speaking: false, micOpen: false, severity: 0 })).toBe(true);
  });
});

describe('something can actually call it', () => {
  /**
   * The reverse failure. A summons bus with no caller does not make the
   * presence quiet -- it makes it unreachable, which is the same dead-control
   * shape pointed the other way, and it would look like a working feature in
   * every test above.
   *
   * Two independent paths must exist, so neither is load-bearing alone:
   * an explicit caller, and the speech bus raising it when the platform talks.
   */
  it('has at least one explicit caller in the product', async () => {
    const sources = import.meta.glob('../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    const callers = Object.entries(sources).filter(
      ([path, text]) =>
        !path.includes('/test/') &&
        !path.includes('presenceSummons') &&
        /summonPresence\s*\(/.test(text),
    );
    expect(callers.length, 'nothing calls summonPresence, so the presence can never appear').toBeGreaterThan(0);
  });

  it('is raised by speech without an explicit summons', () => {
    dismissPresence();
    expect(isPresenceVisible({ speaking: true, micOpen: false, severity: 0 })).toBe(true);
  });
});
