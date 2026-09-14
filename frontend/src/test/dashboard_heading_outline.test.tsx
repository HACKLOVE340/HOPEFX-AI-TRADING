/**
 * The dashboard must expose a heading outline, and its metrics must drill through.
 *
 * F173 and F187, both of which the audit register described from a grep of
 * `Dashboard.tsx` and both of which that grep got wrong.
 *
 * **F187 — "1 onClick handler, the metrics do not drill through".** They do.
 * `StatCard` renders a react-router `<Link>` when given `to`, with a 44px
 * minimum target, a chevron affordance and an `aria-label` naming the figure
 * and its destination. All eight tiles pass `to`. Counting `onClick` measured
 * the wrong mechanism.
 *
 * **F173 — "renders zero h1-h3".** The page renders exactly one `<h1>`, from
 * the shared `<PageHeader>` component, which a grep of this file cannot see.
 *
 * What was genuinely missing is the level below it. The seven section titles —
 * Live Equity Curve, Open Positions, Active Signals, Market Regime, Risk
 * Snapshot, ML Model Accuracy, Quick Navigation — were `<span>`s carrying a
 * `cardTitle` style. Visually they read as headings; to a screen reader they
 * are decoration, so the page offers one landmark and no way to move between
 * its seven regions.
 *
 * These assertions run against the rendered DOM rather than the source, which
 * is the only way to see a heading a child component contributes.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Both API surfaces the page touches. `tradingApi.regime` was missed on the
// first pass and every assertion failed on an unhandled rejection rather than
// on what it was asserting — a red for the wrong reason is not a red.
vi.mock('../hooks/useApi', () => ({
  mlApi: { accuracy: vi.fn().mockResolvedValue({ data: { models: [] } }) },
  tradingApi: {
    regime: vi.fn().mockResolvedValue({ data: { regime: 'unknown' } }),
    equityCurve: vi.fn().mockResolvedValue({ data: [] }),
  },
}));

// lightweight-charts touches canvas APIs jsdom does not implement, and the
// chart is not the subject here.
vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn(), update: vi.fn() }),
    applyOptions: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
  AreaSeries: {},
  ColorType: { Solid: 'solid' },
}));

import Dashboard from '../pages/Dashboard';
import { useStore } from '../store';

// The stat row renders a skeleton until an account arrives, so without this the
// F187 assertions below fail on an absent element rather than on an absent
// link — a red for the wrong reason.
const seedAccount = () =>
  useStore.setState({
    account: {
      balance: 10_000,
      equity: 10_250,
      daily_pnl: 250,
      daily_pnl_pct: 2.5,
      total_pnl: 1_000,
      win_rate: 61.5,
      sharpe_ratio: 1.8,
      max_drawdown: 4.2,
      open_trades: 3,
    },
  } as never);

const renderDashboard = () => {
  seedAccount();
  // App.tsx mounts a QueryClientProvider above every route, so this harness was
  // under-specified rather than minimal: it happened to work only while the
  // Dashboard owned no queries of its own. RiskHeadroomPanel added one, and a
  // harness that does not mount what production always mounts fails for a
  // reason the page does not have.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('Dashboard heading outline — F173', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders exactly one h1', () => {
    renderDashboard();
    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/dashboard/i);
  });

  it('gives every section a heading, so the page can be navigated by region', () => {
    renderDashboard();
    const sectionHeadings = screen
      .getAllByRole('heading', { level: 2 })
      .map((h) => h.textContent?.trim() ?? '');

    // The seven card titles. Named individually so a section losing its
    // heading fails by name rather than by a count nobody can interpret.
    for (const title of [
      /live equity curve/i,
      /open positions/i,
      /active signals/i,
      /market regime/i,
      /risk snapshot/i,
      /ml model accuracy/i,
      /quick navigation/i,
    ]) {
      expect(sectionHeadings.some((t) => title.test(t))).toBe(true);
    }
  });

  it('does not skip a level between the page title and its sections', () => {
    renderDashboard();
    const levels = screen
      .getAllByRole('heading')
      .map((h) => Number(h.tagName.slice(1)))
      .sort((a, b) => a - b);

    expect(levels[0]).toBe(1);
    // Every step down the outline is at most one level; a jump from h1 to h3
    // reads to a screen reader as a missing section.
    const steps = levels.slice(1).map((level, i) => level - (levels[i] as number));
    expect(steps.every((step) => step <= 1)).toBe(true);
  });
});

describe('Dashboard metrics drill through — F187', () => {
  beforeEach(() => vi.clearAllMocks());

  it('makes each headline figure a link to the page that explains it', () => {
    renderDashboard();
    // The accessible name carries the label, the value and the destination, so
    // a screen-reader user knows what opening it will answer.
    const balance = screen.getByRole('link', { name: /balance:.*open wallet/i });
    expect(balance).toHaveAttribute('href', '/wallet');

    const winRate = screen.getByRole('link', { name: /win rate:.*open the trades behind it/i });
    expect(winRate).toHaveAttribute('href', '/journal');
  });

  it('keeps the drill-through targets large enough to hit', () => {
    renderDashboard();
    const tile = screen.getByRole('link', { name: /balance:/i });
    // 44px is the rubric minimum; the class is the mechanism, asserted because
    // jsdom does not do layout.
    expect(tile.className).toMatch(/min-h-\[44px\]/);
  });
});
