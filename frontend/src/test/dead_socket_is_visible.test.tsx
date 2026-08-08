/**
 * F1-02 — a page fed by the WebSocket must not look identical when the socket
 * is dead.
 *
 * docs/HARDENING_BACKLOG.md F1-02, found by the F1 runtime failure matrix.
 *
 * F1-01 covered the HTTP half: three pages that swallowed a failed fetch and
 * rendered byte-identically to the healthy case. This is the socket half, and
 * it is the more likely production failure of the two, because S9-01 is exactly
 * that `wsStatus` stays `'connected'` while the server's broadcast loop stalls.
 * Nothing errors. Nothing reconnects. The numbers simply stop moving.
 *
 *   PriceAlerts  — the "Live Triggers" tab reads
 *                  "No live triggers yet. Alerts fire here in real-time via
 *                  WebSocket."
 *                  With a dead socket that sentence is false: nothing will ever
 *                  appear there. An empty list is shown for "nothing has
 *                  triggered" and for "your alert channel is down" alike — the
 *                  S10-01 empty-vs-unknown defect, on the page whose entire
 *                  promise is that it will tell you when something happens.
 *
 *   Portfolio    — equity, margin, unrealized P&L and the positions tables all
 *                  read socket-fed store fields. Dead socket freezes every one
 *                  of them at its last value with nothing on screen saying so.
 *                  Unrealized P&L is the number a trader watches to decide
 *                  whether to close.
 *
 * `Wallet` was also in the F1-02 row, but it consumes no socket data at all —
 * four one-shot HTTP reads on mount, and it already surfaces their failures.
 * Rendering identically under a dead socket is *correct* for that page. What it
 * genuinely lacks is any statement of when the balance was read, which is
 * S10-05 (data age), not a socket defect. Covered at the bottom.
 *
 * One selector answers "is the feed live?" for every surface. Three surfaces
 * each deriving the kill switch their own way was S10-02; this is the same
 * mistake waiting to happen, and `PositionsTable` had already started it with
 * an inline copy of the expression.
 */

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useStore, selectFeedLive } from '../store';

// ── The single source of truth ───────────────────────────────────────────────

const feed = (over: Record<string, unknown>) =>
  ({ wsStatus: 'connected', feedStale: false, lastDataAt: Date.now(), ...over }) as never;

describe('selectFeedLive — F1-02', () => {
  it('is true only when connected, not stale, and something has arrived', () => {
    expect(selectFeedLive(feed({}))).toBe(true);
  });

  it('is false when the socket is closed', () => {
    expect(selectFeedLive(feed({ wsStatus: 'disconnected' }))).toBe(false);
    expect(selectFeedLive(feed({ wsStatus: 'connecting' }))).toBe(false);
    expect(selectFeedLive(feed({ wsStatus: 'error' }))).toBe(false);
  });

  it('is false when the socket is open but silent — the S9-01 case', () => {
    // The failure that does not announce itself: connection fine, feed dead.
    expect(selectFeedLive(feed({ feedStale: true }))).toBe(false);
  });

  it('is false before the first message, not true', () => {
    // Connected but nothing received yet is "unknown", not "live". A safety
    // indicator may over-report a problem; it must never under-report one.
    expect(selectFeedLive(feed({ lastDataAt: null }))).toBe(false);
  });
});

// ── The notice ───────────────────────────────────────────────────────────────

describe('LiveFeedNotice — F1-02', () => {
  it('renders nothing while the feed is live', async () => {
    const { LiveFeedNotice } = await import('../components/ui/LiveFeedNotice');
    const { container } = render(<LiveFeedNotice live />);
    expect(container.textContent?.trim()).toBe('');
  });

  it('says the updates are not arriving, not merely that something is wrong', async () => {
    const { LiveFeedNotice } = await import('../components/ui/LiveFeedNotice');
    render(<LiveFeedNotice live={false} what="alerts" />);
    const text = screen.getByRole('status').textContent ?? '';
    expect(text).toMatch(/live|real-?time|updates/i);
    expect(text).toMatch(/not|stopped|no longer|isn/i);
  });

  it('names what has stopped updating', async () => {
    const { LiveFeedNotice } = await import('../components/ui/LiveFeedNotice');
    render(<LiveFeedNotice live={false} what="alerts" />);
    expect((screen.getByRole('status').textContent ?? '').toLowerCase()).toContain('alerts');
  });

  it('is announced politely, not assertively', async () => {
    const { LiveFeedNotice } = await import('../components/ui/LiveFeedNotice');
    render(<LiveFeedNotice live={false} />);
    expect(screen.getByRole('status').getAttribute('aria-live')).toBe('polite');
  });
});

// ── The pages ────────────────────────────────────────────────────────────────

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

const setFeed = (over: Record<string, unknown>) =>
  useStore.setState({
    wsStatus: 'connected',
    feedStale: false,
    lastDataAt: Date.now(),
    ...over,
  } as never);

describe('PriceAlerts — F1-02', () => {
  beforeEach(() => useStore.setState({ triggeredAlerts: [] } as never));

  it('does not claim alerts fire in real-time while the socket is dead', async () => {
    const { default: PriceAlerts } = await import('../pages/PriceAlerts');

    setFeed({});
    const healthy = wrap(<PriceAlerts />).container.textContent ?? '';

    setFeed({ feedStale: true });
    const dead = wrap(<PriceAlerts />).container.textContent ?? '';

    expect(
      dead,
      'the alerts page renders identically whether or not the channel that ' +
        'delivers alerts is working (F1-02)',
    ).not.toBe(healthy);
  });

  it('tells the user alerts may have fired without appearing', async () => {
    const { default: PriceAlerts } = await import('../pages/PriceAlerts');
    setFeed({ feedStale: true });
    const { container } = wrap(<PriceAlerts />);
    expect(container.textContent ?? '').toMatch(/not (live|arriving)|disconnected|may have|without/i);
  });

  it('is unchanged when the feed is healthy', async () => {
    const { default: PriceAlerts } = await import('../pages/PriceAlerts');
    setFeed({});
    const { container } = wrap(<PriceAlerts />);
    expect(container.querySelector('[data-testid="live-feed-notice"]')).toBeNull();
  });
});

describe('Portfolio — F1-02', () => {
  // Note on why this is *not* a whole-page string differential like the
  // PriceAlerts one: Portfolio embeds `PositionsTable`, which S10-01 already
  // taught to say "can't confirm positions" when the feed is stale. So the page
  // text already differs, and a differential assertion here would pass without
  // any of this work being done — proving nothing. The part still silent is the
  // account summary: equity, margin, unrealized and daily P&L, all read from
  // socket-fed store fields and all rendered as plain current figures.
  it('does not present frozen equity and P&L as current', async () => {
    const { default: Portfolio } = await import('../pages/Portfolio');
    useStore.setState({
      account: { balance: 10_000, equity: 10_250, total_pnl: 250 },
    } as never);

    setFeed({});
    expect(
      wrap(<Portfolio />).container.querySelector('[data-testid="live-feed-notice"]'),
      'notice shown while the feed is healthy',
    ).toBeNull();

    setFeed({ feedStale: true });
    expect(
      wrap(<Portfolio />).container.querySelector('[data-testid="live-feed-notice"]'),
      'equity, margin and unrealized P&L are frozen at their last values and ' +
        'the page says nothing about it (F1-02)',
    ).not.toBeNull();
  });

  it('shows how old the portfolio figures are', async () => {
    const { default: Portfolio } = await import('../pages/Portfolio');
    useStore.setState({ account: { balance: 10_000, equity: 10_000 } } as never);
    setFeed({ lastDataAt: Date.now() - 42_000, feedStale: true });
    const { container } = wrap(<Portfolio />);
    expect(container.textContent ?? '').toMatch(/42s ago/);
  });
});

describe('Dashboard connection badge — F1-02', () => {
  const renderBadge = async () => {
    const { default: Dashboard } = await import('../pages/Dashboard');
    return wrap(<Dashboard />);
  };

  it('says Live when the feed is actually delivering', async () => {
    setFeed({});
    const { container } = await renderBadge();
    expect(container.textContent ?? '').toMatch(/live/i);
  });

  it('does not say Live when the socket is open but silent', async () => {
    // The S9-01 badge: green, glowing, and reading "Live" while nothing has
    // arrived for five minutes. It is the one cue a trader glances at to decide
    // whether the prices beside it can be trusted.
    setFeed({ feedStale: true, lastDataAt: Date.now() - 300_000 });
    const { container } = await renderBadge();
    const text = container.textContent ?? '';
    expect(text).toMatch(/stalled|not live|no data/i);
  });

  it('does not say Live when the socket never opened', async () => {
    setFeed({ wsStatus: 'disconnected', lastDataAt: null });
    const { container } = await renderBadge();
    expect(container.textContent ?? '').toMatch(/disconnected/i);
  });
});

// ── S10-05 tail: Wallet reads its balance once and never says when ───────────

describe('Wallet — data age (S10-05)', () => {
  it('states when the balance was read', async () => {
    const { default: Wallet } = await import('../pages/Wallet');
    const { container } = wrap(<Wallet />);
    // Not a socket concern — Wallet subscribes to nothing. But a balance
    // fetched once at mount and never refreshed still reads as current.
    // Awaited because the figure only exists once the mount fetch settles;
    // here it settles as a failure, which is itself the case that must not
    // render a bare number with no indication of where it came from.
    await waitFor(() =>
      expect(container.textContent ?? '').toMatch(/just now|s ago|m ago|h ago|no data|as of/i),
    );
  });
});

// ── The selector must be the only copy ───────────────────────────────────────

describe('no surface re-derives feed liveness itself — F1-02', () => {
  const SURFACES = [
    'src/components/panels/PositionsTable.tsx',
    'src/pages/PriceAlerts.tsx',
    'src/pages/Portfolio.tsx',
  ];

  it.each(SURFACES)('%s uses selectFeedLive', async (rel) => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const file = path.resolve(process.cwd(), rel);
    if (!fs.existsSync(file)) return;
    const src = fs.readFileSync(file, 'utf8');

    expect(
      src.includes('selectFeedLive'),
      `${rel} derives "is the feed live" locally. Every duplicated pair in this ` +
        `codebase has already produced a defect (S13-01, S10-02) — the copies ` +
        `drift and then disagree on screen about the same fact.`,
    ).toBe(true);
  });
});
