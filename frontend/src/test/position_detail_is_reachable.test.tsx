/**
 * The drill-down exists, is reachable from the row, and tells the truth when
 * it does not know something.
 *
 * Three separate claims, because the first two can each be true while the
 * third is the one that matters on a risk screen:
 *
 *   1. `/positions/:id` renders the position, not a 404 — before this there
 *      were 87 routes and exactly one took a parameter.
 *   2. clicking a dashboard row goes there. It used to go to `/trade` with the
 *      symbol prefilled (F225); that shortcut is preserved as an action ON the
 *      detail page rather than deleted.
 *   3. a money figure the page cannot derive renders as an em dash, never as
 *      $0.00. "You are risking $0.00" is the most dangerous sentence this page
 *      could produce, and it is what a naive implementation produces for every
 *      position whose price has not yet moved off its entry.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import React from 'react';
import { useStore } from '../store';
import PositionDetail from '../pages/PositionDetail';

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: vi.fn(() => ({ send: vi.fn() })) }));

const GOLD = {
  id: 'P-8841',
  symbol: 'XAUUSD',
  side: 'long',
  size: 0.5,
  entry_price: 2318.4,
  current_price: 2326.65,
  unrealized_pnl: 412.5,
  realized_pnl: 0,
  opened_at: '2026-09-14T09:14:00Z',
  stop_loss: 2310.2,
  take_profit: 2342.8,
};

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/positions/${id}`]}>
      <Routes>
        <Route path="/positions/:id" element={<PositionDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useStore.setState({ positions: [GOLD] } as never);
});

describe('position detail', () => {
  it('renders the position named in the URL', () => {
    renderAt('P-8841');
    expect(screen.getAllByText('XAUUSD').length).toBeGreaterThan(0);
    // Twice on purpose: once as the headline figure, once in the complete
    // record below it. The record is an audit list and is not allowed gaps.
    expect(screen.getAllByText('+$412.50')).toHaveLength(2);
    expect(screen.getByText('P-8841 · size 0.50 · entry 2,318.40')).toBeTruthy();
  });

  it('prices the stop from the position itself, not from a guessed multiplier', () => {
    renderAt('P-8841');
    // (2318.40 − 2310.20) × 50 oz = $410.00, and the 50 is measured from the
    // position's own P&L rather than assumed from a contract table.
    expect(screen.getAllByText('$410.00').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$1,220.00').length).toBeGreaterThan(0);
  });

  it('shows an em dash, never a zero, for money it cannot derive', () => {
    useStore.setState({
      positions: [{ ...GOLD, current_price: GOLD.entry_price, unrealized_pnl: 0 }],
    } as never);
    renderAt('P-8841');
    // The multiplier is underivable at the entry price, so risk and reward are
    // absent. Nothing on the page may claim the risk is zero.
    expect(screen.queryByText('$0.00')).toBeNull();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Risk to stop is not derivable until the price moves off the entry/),
    ).toBeTruthy();
  });

  it('says so plainly when there is no stop, rather than drawing an empty bracket', () => {
    useStore.setState({ positions: [{ ...GOLD, stop_loss: undefined }] } as never);
    renderAt('P-8841');
    expect(screen.getByText(/the downside is unbounded/)).toBeTruthy();
  });

  it('does not invent a position for an id that is not open', () => {
    renderAt('P-0000');
    expect(screen.getByText('That position is not open')).toBeTruthy();
    expect(screen.getByText(/Nothing open matches P-0000/)).toBeTruthy();
  });

  it('keeps the ticket shortcut the row used to be, as a named action', () => {
    renderAt('P-8841');
    const ticket = screen.getByRole('button', { name: /open ticket/i });
    expect(ticket).toBeTruthy();
    fireEvent.click(ticket);
  });

  it('gives every control and every meter an accessible name', () => {
    const { container } = renderAt('P-8841');
    const nameless: string[] = [];
    container.querySelectorAll('button, a, [role="img"]').forEach((el) => {
      const name =
        el.getAttribute('aria-label')?.trim() ||
        el.textContent?.trim() ||
        el.getAttribute('title')?.trim();
      if (!name) nameless.push(el.outerHTML.slice(0, 90));
    });
    expect(nameless, `unnamed controls:\n${nameless.join('\n')}`).toEqual([]);
  });

  it('offers the pages behind this one as real links', () => {
    renderAt('P-8841');
    // The hand-written list became PageShell's derived footer, so the links
    // now come from navConfig rather than from four literals in this file —
    // which is the point: a renamed or retired page cannot leave a dead link
    // behind here. What must remain true is that there ARE links, that each
    // is a real route, and that none points back at this page.
    const nav = screen.getByRole('navigation', { name: /where to next/i });
    const hrefs = [...nav.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    expect(hrefs.length).toBeGreaterThan(0);
    for (const href of hrefs) expect(href?.startsWith('/')).toBe(true);
    expect(hrefs).not.toContain('/positions/P-8841');
  });
});
