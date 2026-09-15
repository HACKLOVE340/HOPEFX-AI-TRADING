/**
 * A page that is loading, or that failed, is still that page.
 *
 * Twelve of the sixty-three pages were off `PageShell` because they return
 * early for loading, error and signed-out states, and each return carried its
 * own bare `page-content` root. So those states rendered a paragraph and
 * nothing else — no heading, no breadcrumbs, no onward navigation:
 *
 *     if (loading) return <div style={s.loading}>Loading walk-forward results…</div>;
 *     if (loading) return <div className="page-content"><p>Loading profile…</p></div>;
 *
 * An operator who lands on a slow page sees a sentence with no indication of
 * what page it is or where to go instead, and an operator whose page ERRORED
 * sees the same — at the moment they most need a way out. `no_page_is_a_dead_end`
 * already holds that rule for the happy path; this holds it for the two states
 * where it matters more.
 *
 * The fix is not to wrap each branch in its own shell. It is to let the shell
 * OUTLIVE the branch: one `PageShell` with the branch deciding only its body.
 * The header is then a property of the page rather than of the page having
 * succeeded.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const never = () => new Promise(() => {});
const fails = () => Promise.reject(new Error('upstream is down'));

const walkForwardGet = vi.fn();
const profileGet = vi.fn();

vi.mock('../hooks/useApi', async (orig) => {
  const real = await (orig() as Promise<Record<string, unknown>>);
  return {
    ...real,
    api: { ...(real.api as object), get: (...a: unknown[]) => walkForwardGet(...a) },
    profileApi: { get: (...a: unknown[]) => profileGet(...a), update: vi.fn() },
  };
});

vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
  LineSeries: {},
}));

import WalkForward from '../pages/WalkForward';
import Profile from '../pages/Profile';

const PAGES = [
  { name: 'Walk-Forward', Component: WalkForward, mock: walkForwardGet, heading: /walk-forward/i },
  { name: 'Profile', Component: Profile, mock: profileGet, heading: /profile/i },
];

beforeEach(() => {
  walkForwardGet.mockReset();
  profileGet.mockReset();
});
afterEach(() => cleanup());

describe.each(PAGES)('$name', ({ Component, mock, heading }) => {
  it('names itself while it is still loading', async () => {
    mock.mockImplementation(never);
    render(<MemoryRouter><Component /></MemoryRouter>);
    const h1 = await screen.findByRole('heading', { level: 1 });
    expect(h1.textContent).toMatch(heading);
  });

  it('names itself when the request failed', async () => {
    // This is the state where it matters most: something went wrong and the
    // operator needs to know where they are and where else they can go.
    mock.mockImplementation(fails);
    render(<MemoryRouter><Component /></MemoryRouter>);
    await waitFor(async () => {
      const h1 = await screen.findByRole('heading', { level: 1 });
      expect(h1.textContent).toMatch(heading);
    });
  });

  it('has exactly one h1 in every state', async () => {
    // Two headings is what you get by wrapping each branch in its own shell
    // instead of letting one shell outlive them.
    for (const impl of [never, fails]) {
      cleanup();
      mock.mockReset();
      mock.mockImplementation(impl);
      render(<MemoryRouter><Component /></MemoryRouter>);
      await waitFor(() => expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1));
    }
  });
});
