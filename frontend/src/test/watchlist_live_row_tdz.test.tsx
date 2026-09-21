/**
 * src/test/watchlist_live_row_tdz.test.tsx
 * ========================================
 * The deployed Watchlist page crashed with:
 *
 *     Cannot access 'N' before initialization
 *
 * `N` is the minified name of `tickHistory`. The page computed `enrichedItems`
 * near the top of the component body and read `tickHistory[item.symbol]` inside
 * the map callback — but `const [tickHistory, setTickHistory] = useState(...)`
 * was declared ~40 lines *below* that computation. A `const` read before its
 * declaration in the same scope is a temporal dead zone violation, which throws
 * at runtime.
 *
 * Nothing in the toolchain catches it:
 *
 *  * `tsc` reports TS2448 ("used before its declaration") only for a *direct*
 *    reference in the same scope. Here the read is inside an arrow function
 *    passed to `.map()`, and TypeScript cannot know when that runs — so
 *    `npm run typecheck` and `npm run build` both pass.
 *  * The project has no ESLint, so `no-use-before-define` never ran.
 *  * Every existing Watchlist test renders with an empty list and a dead feed.
 *    The throwing line sits behind `if (!feedLive) return item;` inside
 *    `items.map(...)`, so with `items === []` it is unreachable. The page was
 *    covered by ten tests and none of them could reach the defect.
 *
 * The reachable state is the *normal* one: watchlist has symbols, socket is
 * connected, a tick has arrived. That is a hard page crash, on every render,
 * for every user whose watchlist is not empty.
 *
 * These tests drive the page into exactly that state.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';
import { useStore } from '../store';

const listMock   = vi.fn();
const pricesMock = vi.fn();

vi.mock('../hooks/useApi', () => ({
  watchlistApi: {
    list:   (...a: unknown[]) => listMock(...a),
    prices: (...a: unknown[]) => pricesMock(...a),
    add:    vi.fn().mockResolvedValue({ data: {} }),
    remove: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

const ROW = {
  symbol: 'EURUSD',
  bid: 1.08512,
  ask: 1.08528,
  mid: 1.0852,
  change_pct: 0.31,
  timestamp: 1_760_000_000_000,
  history: [1.0840, 1.0846, 1.0852],
};

const TICK = {
  symbol: 'EUR/USD',
  bid: 1.08600,
  ask: 1.08614,
  mid: 1.08607,
  spread: 0.00014,
  timestamp: 1_760_000_005_000,
  change_pct: 0.42,
};

/** The live-feed state: connected socket, not stale, data has arrived. */
function makeFeedLive() {
  useStore.setState({
    wsStatus: 'connected',
    feedStale: false,
    lastDataAt: Date.now(),
    prices: { 'EUR/USD': TICK },
  } as never);
}

async function renderWatchlist() {
  const Watchlist = (await import('../pages/Watchlist')).default;
  return render(
    <MemoryRouter>
      <Watchlist />
    </MemoryRouter>,
  );
}

describe('Watchlist renders a live row without a temporal dead zone', () => {
  beforeEach(() => {
    listMock.mockResolvedValue({ data: { items: [ROW] } });
    pricesMock.mockResolvedValue({ data: [ROW] });
    useStore.setState({ wsStatus: 'disconnected', feedStale: true, lastDataAt: null, prices: {} } as never);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('does not throw when the feed is live and the watchlist has a symbol', async () => {
    // The exact deployed condition. Before the fix this render threw
    // "Cannot access 'tickHistory' before initialization" and the page went blank.
    makeFeedLive();
    await renderWatchlist();

    await waitFor(() => {
      expect(screen.getByText('EURUSD')).toBeInTheDocument();
    });
  });

  it('shows the live tick price on the row, not the polled snapshot', async () => {
    // Pins that the overlay this crash lived inside still does its job — a fix
    // that deletes the overlay would make the crash test pass for the wrong reason.
    makeFeedLive();
    await renderWatchlist();

    await waitFor(() => {
      expect(screen.getByText('1.08600')).toBeInTheDocument(); // tick bid, not 1.08512
    });
  });

  it('still renders when the feed is dead — the pre-fix covered path', async () => {
    await renderWatchlist();
    await waitFor(() => {
      expect(screen.getByText('EURUSD')).toBeInTheDocument();
    });
    expect(screen.getByText('1.08512')).toBeInTheDocument(); // polled snapshot bid
  });

  it('accumulates tick history for the sparkline once a tick arrives', async () => {
    makeFeedLive();
    const { container } = await renderWatchlist();

    await waitFor(() => {
      // >= 2 points renders a <path>; the flat fallback renders a <line>.
      expect(container.querySelector('svg path')).not.toBeNull();
    });
  });
});

describe('the component body declares state before it is read', () => {
  it('declares tickHistory above the render-time computation that reads it', async () => {
    // A source assertion, because the runtime test above only catches the case
    // where the crashing branch is reachable from the props under test. If
    // someone reorders the hooks again, this fails immediately and names the
    // reason rather than surfacing as a blank page in production.
    const fs = await import('node:fs/promises');
    const url = await import('node:url');
    const path = await import('node:path');

    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const src = await fs.readFile(path.join(here, '../pages/Watchlist.tsx'), 'utf-8');

    const declaration = src.indexOf('const [tickHistory, setTickHistory]');
    const firstRead = src.indexOf('tickHistory[item.symbol]');

    expect(declaration).toBeGreaterThan(-1);
    expect(firstRead).toBeGreaterThan(-1);
    expect(declaration).toBeLessThan(firstRead);
  });
});
