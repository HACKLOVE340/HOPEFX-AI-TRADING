/**
 * F1-03 — a missing field must not white-screen the page.
 *
 * Found by the F1 runtime failure matrix, which could not score `Performance`
 * at all: it crashed in every scenario including the healthy control, so its
 * whole row read `?`.
 *
 *   Performance.tsx:412  value={pub.total_trades.toString()}
 *   Performance.tsx:416  value={`${pub.max_drawdown_pct}%`}
 *
 * The three fields between them are guarded:
 *
 *   pub.win_rate       != null ? `${pub.win_rate}%`  : '—'   ← "Need 50+ trades"
 *   pub.avg_return_pct != null ? …                   : '—'
 *   pub.sharpe         != null ? pub.sharpe.toString() : '—' ← "Need 50+ trades"
 *
 * So the component already knows this payload arrives partially populated —
 * its own copy says the stats appear once there are 50 trades — and two of the
 * six tiles were left unguarded. The same page guards the same two fields
 * correctly elsewhere (`wr.total_trades ?? '—'`, line 558), which is the S13-01
 * duplication pattern again: two copies of one rule, one of them wrong.
 *
 * `.toString()` on undefined throws inside render, and a throw in render takes
 * the whole route down — not the tile. A user asking "how is my strategy
 * doing?" gets a blank screen.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('Performance — partial public payload (F1-03)', () => {
  beforeEach(() => vi.resetModules());

  const renderWith = async (pub: Record<string, unknown>) => {
    vi.doMock('../hooks/useApi', async () => {
      const actual = await vi.importActual<Record<string, unknown>>('../hooks/useApi');
      return {
        ...actual,
        performanceApi: {
          ...(actual.performanceApi as object),
          summary: vi.fn(async () => ({ data: pub })),
        },
      };
    });
    const { default: Performance } = await import('../pages/Performance');
    return wrap(<Performance />);
  };

  it('renders when the payload has every field', async () => {
    const { container } = await renderWith({
      total_trades: 120, win_rate: 61, avg_return_pct: 0.4,
      sharpe: 1.4, max_drawdown_pct: 3.2,
    });
    await waitFor(() => expect(container.textContent ?? '').toMatch(/total trades/i));
  });

  it('does not crash when total_trades is missing', async () => {
    // The exact shape the component's own "Need 50+ trades" copy anticipates.
    const { container } = await renderWith({ win_rate: null, sharpe: null });
    await waitFor(() => expect(container.textContent ?? '').toMatch(/total trades/i));
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('does not crash when max_drawdown_pct is missing', async () => {
    const { container } = await renderWith({ total_trades: 3, win_rate: null });
    await waitFor(() => expect(container.textContent ?? '').toMatch(/max drawdown/i));
    expect(container.textContent ?? '').not.toMatch(/undefined%|NaN/);
  });

  it('never prints the string "undefined" or "NaN" as a statistic', async () => {
    const { container } = await renderWith({});
    await waitFor(() => expect(container.textContent ?? '').toMatch(/total trades/i));
    expect(container.textContent ?? '').not.toMatch(/undefined|NaN/);
  });
});

/**
 * Same class, second site: `Dashboard`'s market-regime panel.
 *
 *   Dashboard.tsx:481  if (err || !regime)          ← null only
 *   Dashboard.tsx:499  regime.regime.replace(…)     ← throws on {}
 *
 * `/trading/regime` returns a partial object before the classifier has enough
 * bars. The guard caught null and nothing else, so the panel threw during
 * render and took the whole Dashboard route with it. This is why the Dashboard
 * row of the F1 matrix read `?` in every column, healthy included — the page
 * could not be scored because it never rendered.
 */
describe('Dashboard market regime — partial payload (F1-03)', () => {
  beforeEach(() => vi.resetModules());

  const renderWith = async (regime: unknown) => {
    vi.doMock('../hooks/useApi', async () => {
      const actual = await vi.importActual<Record<string, unknown>>('../hooks/useApi');
      return {
        ...actual,
        tradingApi: {
          ...(actual.tradingApi as object),
          regime: vi.fn(async () => ({ data: regime })),
        },
      };
    });
    const { default: Dashboard } = await import('../pages/Dashboard');
    return wrap(<Dashboard />);
  };

  it('renders the regime when the payload is complete', async () => {
    const { container } = await renderWith({
      regime: 'trending_up', confidence: 0.8, volatility: 'low', trend: 'up',
    });
    await waitFor(() => expect(container.textContent ?? '').toMatch(/Trending Up/));
  });

  it('does not take the page down when the regime field is absent', async () => {
    const { container } = await renderWith({ confidence: 0.5 });
    // The panel degrades; the route survives.
    await waitFor(() => expect(container.textContent ?? '').toMatch(/regime data unavailable/i));
  });

  it('does not take the page down on an empty object', async () => {
    const { container } = await renderWith({});
    await waitFor(() => expect(container.textContent ?? '').toMatch(/regime data unavailable/i));
  });

  it('does not print NaN% for a missing confidence', async () => {
    const { container } = await renderWith({ regime: 'ranging', volatility: 'high', trend: 'flat' });
    await waitFor(() => expect(container.textContent ?? '').toMatch(/Ranging/));
    expect(container.textContent ?? '').not.toMatch(/NaN/);
  });
});
