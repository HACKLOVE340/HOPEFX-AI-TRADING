/**
 * Regression tests: "no open positions" must never be shown when we don't know.
 *
 * Round 3 audit finding S9-03 (docs/HARDENING_BACKLOG.md).
 *
 * The positions panel rendered `filtered.length === 0` as the empty state, and
 * `positions` is populated from the WebSocket store. So a stalled feed, a
 * disconnected socket, or a failed load all produced an empty array — and the
 * panel confidently displayed "📭 No open positions".
 *
 * That is the one false negative that matters on this screen: it is the panel a
 * trader checks before deciding whether to intervene, and it reads identically
 * whether they are genuinely flat or the client simply has no idea. The
 * `brokerReady` flag covered only one narrow case (account present but
 * uninitialised), not "we lost the feed".
 *
 * `feedStale` and `wsStatus` are already in the store — S9-01 put the first one
 * there. These tests pin that an unknown state is rendered as unknown.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { useStore } from '../store';
import PositionsTable from '../components/panels/PositionsTable';

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PositionsTable />
    </QueryClientProvider>,
  );
}

describe('positions panel: empty vs unknown (S9-03)', () => {
  beforeEach(() => {
    useStore.setState({
      positions: [],
      account: { balance: 100_000, equity: 100_000 } as never,
      wsStatus: 'connected',
      feedStale: false,
      lastDataAt: Date.now(),
    });
  });

  it('shows a genuine empty state when the feed is healthy', () => {
    renderPanel();
    expect(screen.getByText(/no open positions/i)).toBeTruthy();
  });

  it('does NOT claim "no open positions" while the feed is stale', () => {
    useStore.setState({ feedStale: true });
    renderPanel();

    expect(screen.queryByText(/no open positions/i)).toBeNull();
  });

  it('says so explicitly when position state is unknown', () => {
    useStore.setState({ feedStale: true });
    renderPanel();

    // The wording matters: a trader must be able to tell "we don't know" from
    // "you are flat". Matches both the heading and the explanatory body.
    expect(
      screen.getAllByText(/can't confirm|cannot confirm|unknown|not up to date/i).length,
    ).toBeGreaterThan(0);
  });

  it('does NOT claim "no open positions" while disconnected', () => {
    useStore.setState({ wsStatus: 'disconnected' });
    renderPanel();

    expect(screen.queryByText(/no open positions/i)).toBeNull();
  });

  it('still lists positions when it has them, stale or not', () => {
    useStore.setState({
      feedStale: true,
      positions: [
        {
          id: 'p1',
          symbol: 'XAUUSD',
          side: 'long',
          quantity: 1,
          entry_price: 2350,
          current_price: 2360,
          unrealized_pnl: 10,
        } as never,
      ],
    });
    renderPanel();

    expect(screen.queryByText(/no open positions/i)).toBeNull();
    expect(screen.getByText(/XAUUSD/i)).toBeTruthy();
  });
});
