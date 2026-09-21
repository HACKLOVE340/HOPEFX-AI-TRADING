/**
 * F3-01 — the HTTP fallback is switched off by the failure it exists for.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F3: *"is any money-bearing query
 * configured to serve cached data indefinitely?"*
 *
 * `useOrchestratorData.ts` — three queries, and the comment above the first one
 * says what it is for:
 *
 *     // ── Account (every 10s — fallback when WS is down) ───────────────────
 *     refetchInterval: wsStatus === 'connected' ? false : 10_000,   // :277  account
 *     refetchInterval: wsStatus === 'connected' ? false : 10_000,   // :321  positions
 *     refetchInterval: wsStatus === 'connected' ? false : 15_000,   // :354  signals
 *
 * The fallback is right. Its trigger is not. "WS is down" is measured as
 * `wsStatus !== 'connected'`, and S9-01 is precisely that `wsStatus` **stays**
 * `'connected'` while the server's broadcast loop stalls: the socket is open,
 * nothing is arriving, nothing errors, nothing reconnects.
 *
 * So in the one failure this fallback was built for, it never runs. Account,
 * positions and signals freeze at their last pushed value, and the polling that
 * would have refreshed them is suppressed by the flag that failed to notice.
 * A stalled feed is not a degraded state the app rides out — it is permanent
 * until something else forces a refetch.
 *
 * This compounds with F1-02 in an unhappy way. Those notices now tell the user
 * their figures may have moved — while the app holds a working HTTP path it has
 * switched off. It could have been self-healing and was instead merely honest.
 *
 * `selectFeedLive` is the condition that was missing: connected **and** not
 * stale **and** something has actually arrived. Poll whenever that is false,
 * and a stalled feed repairs itself within one interval.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore, selectFeedLive } from '../store';

/**
 * The predicate under test, read out of the source. A behavioural test would
 * need to run React Query's scheduler against fake timers for 10s of virtual
 * time per case; the defect is entirely in which flag the interval is keyed to,
 * so that is what this pins — plus a source check that the flag in the file is
 * the shared selector and not a fresh local copy.
 */
const shouldPoll = (s: unknown) => !selectFeedLive(s as never);

const feed = (over: Record<string, unknown>) =>
  ({ wsStatus: 'connected', feedStale: false, lastDataAt: Date.now(), ...over });

describe('F3-01 — polling resumes whenever the feed is not delivering', () => {
  it('does not poll while the feed is genuinely live', () => {
    expect(shouldPoll(feed({}))).toBe(false);
  });

  it('polls when the socket is closed', () => {
    expect(shouldPoll(feed({ wsStatus: 'disconnected' }))).toBe(true);
  });

  it('polls when the socket is open but silent — the case that was missed', () => {
    // wsStatus === 'connected', so the old predicate suppressed the fallback
    // in exactly the failure the fallback exists for.
    expect(shouldPoll(feed({ feedStale: true }))).toBe(true);
  });

  it('polls before the first message has ever arrived', () => {
    expect(shouldPoll(feed({ lastDataAt: null }))).toBe(true);
  });

  it('stops polling again once the feed recovers', () => {
    expect(shouldPoll(feed({ feedStale: true }))).toBe(true);
    expect(shouldPoll(feed({ feedStale: false, lastDataAt: Date.now() }))).toBe(false);
  });
});

describe('F3-01 — the money-bearing queries key their interval to the feed', () => {
  const QUERIES = ['account', 'positions', 'signals'];

  it('useOrchestratorData no longer keys refetchInterval to wsStatus alone', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(
      path.resolve(process.cwd(), 'src/hooks/useOrchestratorData.ts'),
      'utf8',
    );

    const offenders = src
      .split('\n')
      .map((l, i) => [i + 1, l] as const)
      .filter(([, l]) => /refetchInterval:.*wsStatus\s*===\s*'connected'/.test(l));

    expect(
      offenders,
      `refetchInterval keyed to wsStatus alone at line(s) ` +
        `${offenders.map(([n]) => n).join(', ')}. A stalled socket keeps ` +
        `wsStatus === 'connected', so the HTTP fallback for ${QUERIES.join('/')} ` +
        `stays off during the exact failure it exists for (F3-01).`,
    ).toEqual([]);
  });

  it('uses the shared selector rather than a fourth local copy of the rule', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(
      path.resolve(process.cwd(), 'src/hooks/useOrchestratorData.ts'),
      'utf8',
    );
    expect(src.includes('selectFeedLive')).toBe(true);
  });
});

// ── F3-02 ────────────────────────────────────────────────────────────────────

/**
 * `lastHeartbeat` is written by `useWebSocket` and read by nothing.
 *
 * The playbook named it as the known example — *"fields that are written and
 * never read (`lastHeartbeat` was one)"* — and it is still there. Counting
 * `s.<field>` references across `src/`, every one of the store's 33 state
 * fields has at least one reader except this one, which has zero.
 *
 * It is not merely unused, it is a decoy: it is the field whose name promises
 * to answer "is the feed alive?", it is kept faithfully up to date, and the
 * codebase had to grow `lastDataAt` and `feedStale` to answer that question
 * because nothing consumed this. Anyone reaching for liveness reaches for it
 * first. This test keeps it honest — either something reads it, or the comment
 * on it says plainly that nothing does and points at what to use instead.
 */
describe('F3-02 — lastHeartbeat must not read as the liveness signal', () => {
  beforeEach(() => useStore.setState({ lastHeartbeat: null } as never));

  it('is documented as not being the freshness source', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(path.resolve(process.cwd(), 'src/store/index.ts'), 'utf8');

    const i = src.indexOf('lastHeartbeat:');
    expect(i).toBeGreaterThan(-1);
    const preamble = src.slice(Math.max(0, i - 900), i);

    expect(
      /lastDataAt|selectFeedLive|not.*(freshness|liveness)/i.test(preamble),
      'lastHeartbeat is written and read by nothing, while carrying the name a ' +
        'reader will reach for when they want liveness. Say so at the ' +
        'declaration and point at lastDataAt / selectFeedLive (F3-02).',
    ).toBe(true);
  });
});
