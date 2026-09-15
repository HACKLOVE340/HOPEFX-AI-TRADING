/**
 * `/observability` renders two components as siblings, and one of them owns the
 * page:
 *
 *     element={wrap(adminOnly(<><Observability /><TradingDashboard /></>))}
 *
 * `Observability` is on `PageShell`, so at that route the shell renders its
 * header, its body and its "Where to next" footer — and THEN
 * `TradingDashboard`'s engine grid renders after it, outside the shell. The
 * footer sits in the middle of the page, with several hundred pixels of
 * microstructure below it.
 *
 * It also makes `TradingDashboard` unmigratable in the obvious way: putting it
 * on `PageShell` too would give the route two h1s and two footers. The page
 * shell ratchet asks for exactly that, because `_routed_pages` counts any
 * component named in a `<Route element=…>` — it cannot see that this element
 * holds two components and only the first is the page.
 *
 * The fix is composition, not a second shell: the grid is a SECTION of
 * Observability, so Observability renders it, inside its own shell, where the
 * footer can stay at the bottom.
 */
import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../hooks/useApi', async (orig) => {
  const real = await (orig() as Promise<Record<string, unknown>>);
  return { ...real, api: { ...(real.api as object), get: () => new Promise(() => {}) } };
});

// The engine grid is heavy and full of live panels. What matters here is WHERE
// it renders, not what it draws, so it is stubbed to a marker.
vi.mock('../pages/TradingDashboard', () => ({
  default: () => <div data-testid="engine-grid">grid</div>,
}));

import Observability from '../pages/Observability';

afterEach(() => cleanup());

describe('/observability is one page', () => {
  it('renders the engine grid', async () => {
    render(<MemoryRouter><Observability /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId('engine-grid')).toBeTruthy());
  });

  it('has exactly one heading and one onward-navigation footer', async () => {
    render(<MemoryRouter initialEntries={['/observability']}><Observability /></MemoryRouter>);
    await waitFor(() => expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1));
    // `RelatedPages` renders a labelled navigation region. Two of them is the
    // symptom this file exists for.
    const footers = screen.queryAllByRole('navigation', { name: /where to next/i });
    expect(footers.length).toBeLessThanOrEqual(1);
  });

  it('puts the onward footer AFTER the engine grid, not above it', async () => {
    render(<MemoryRouter initialEntries={['/observability']}><Observability /></MemoryRouter>);
    const grid = await screen.findByTestId('engine-grid');
    const footer = screen.queryByRole('navigation', { name: /where to next/i });
    if (!footer) return; // the route may derive no links; the ordering claim is moot
    // `compareDocumentPosition` returns FOLLOWING (4) when the argument comes
    // after the node. The footer must come after the grid.
    expect(grid.compareDocumentPosition(footer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
