/**
 * PropFirmTracker renders the standard page frame, and keeps what it had.
 *
 * This page had no test at all, and it is the one that tells a funded trader
 * how close today has come to a limit that ends their account. It was migrated
 * onto PageShell — title, icon, status badge, four tabs and two onward actions
 * — so the risk worth covering is that the migration dropped one of them. That
 * is what a page migration does when it goes wrong: the page still renders, it
 * just renders less, and nothing throws.
 *
 * It is also gated by plan, so neither the signed-in trader nor a browser
 * sweep can reach its body — the sweep sees "Upgrade now" both before and
 * after. That is why this is a test rather than a runtime check: the component
 * is rendered directly, with the providers the real app mounts, and no
 * subscription stands in the way.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

vi.mock('../hooks/useApi', () => ({
  propFirmExtApi: {
    status:       vi.fn().mockResolvedValue({ data: null }),
    history:      vi.fn().mockResolvedValue({ data: [] }),
    challenges:   vi.fn().mockResolvedValue({ data: [] }),
    dailyStats:   vi.fn().mockResolvedValue({ data: [] }),
    breachAlerts: vi.fn().mockResolvedValue({ data: [] }),
    accounts:     vi.fn().mockResolvedValue({ data: [] }),
    acknowledgeAlert: vi.fn().mockResolvedValue({ data: {} }),
  },
  extractApiError: (_e: unknown, fallback: string) => fallback,
}));

import PropFirmTracker from '../pages/PropFirmTracker';

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={['/prop-firm']}>
      <QueryClientProvider client={qc}><PropFirmTracker /></QueryClientProvider>
    </MemoryRouter>,
  );
};

describe('PropFirmTracker on the standard shell', () => {
  beforeEach(() => vi.clearAllMocks());

  it('states its own title', async () => {
    wrap();
    expect(await screen.findByText(/Prop Firm Challenge Tracker/i)).toBeTruthy();
  });

  it('keeps all four tabs the header carried before the migration', async () => {
    wrap();
    await screen.findByText(/Prop Firm Challenge Tracker/i);
    for (const label of ['Live', 'History', 'Alerts', 'Daily']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it('keeps both onward actions', async () => {
    wrap();
    await screen.findByText(/Prop Firm Challenge Tracker/i);
    // These navigate to the two pages a trader reaches from here. Losing one is
    // silent: the page still renders, and the way out is simply gone.
    expect(screen.getByText('Risk Calc')).toBeTruthy();
    expect(screen.getByText('Trade')).toBeTruthy();
  });

  it('offers somewhere to go next', async () => {
    const { container } = wrap();
    await screen.findByText(/Prop Firm Challenge Tracker/i);
    expect(container.querySelector('nav[aria-label="Where to next"]')).toBeTruthy();
  });
});
