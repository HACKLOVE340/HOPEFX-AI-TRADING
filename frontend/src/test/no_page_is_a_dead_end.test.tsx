/**
 * Every page offers somewhere to go, and never twice.
 *
 * 40 of 74 pages had no outbound link anywhere in their content area, so the
 * only way off them was the sidebar. Editing 74 files would have fixed it
 * once — the 75th page would ship as a cul-de-sac like the 40 before it.
 *
 * `PageSurface` wraps every route and renders a derived footer as a fallback,
 * which raises the opposite risk: the 34 pages that already have one would get
 * two. `RelatedPages` claims the slot when it mounts, and the fallback stands
 * down when anything claimed it.
 *
 * Three things can go wrong here without anything erroring, and each has a
 * test: a page ends up with no footer, a page ends up with two, or the
 * fallback claims its own slot and loops forever. The last one is the reason
 * the fallback is rendered outside the provider, and it is invisible until it
 * hangs the browser.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

import { PageSurface } from '../components/system/PageSurface';
import { RelatedPages } from '../components/RelatedPages';
import { relatedFor } from '../lib/related';

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: vi.fn(() => ({ send: vi.fn() })) }));

function at(path: string, children: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PageSurface>{children}</PageSurface>
    </MemoryRouter>,
  );
}

/** Every "Where to next" landmark currently rendered. */
const footers = () => screen.queryAllByRole('navigation', { name: /where to next/i });

describe('no page is a dead end', () => {
  it('gives a bare page a derived footer', () => {
    at('/tca', <p>a page with no links of its own</p>);
    expect(footers()).toHaveLength(1);
  });

  it('does not give a page two footers when it has its own', () => {
    at(
      '/tca',
      <RelatedPages
        links={[{ to: '/performance', label: 'Performance', hint: 'Returns over time.' }]}
      />,
    );
    const found = footers();
    expect(found).toHaveLength(1);
    // And the one that survived is the page's own, not the derived fallback.
    expect(found[0]!.querySelectorAll('a')).toHaveLength(1);
  });

  it('treats a footer with no links as no footer, because that is what it is', () => {
    at('/tca', <RelatedPages links={[]} />);
    expect(footers()).toHaveLength(1);
  });

  it('offers nothing where leaving would lose the user something', () => {
    // Mid-flow and pre-auth: a grid of trader tools under a sign-in form is
    // noise, and under a KYC step it is an invitation to abandon it.
    for (const path of ['/login', '/register', '/checkout', '/kyc', '/onboarding']) {
      const { unmount } = at(path, <p>flow</p>);
      expect(footers(), `${path} should offer no footer`).toHaveLength(0);
      unmount();
    }
  });

  it('derives links that are real, described and never self-referential', () => {
    for (const path of ['/tca', '/journal', '/watchlist', '/leaderboard', '/wallet']) {
      const links = relatedFor(path);
      expect(links.length, `${path} derived nothing`).toBeGreaterThan(0);
      expect(links.map((l) => l.to)).not.toContain(path);
      for (const l of links) {
        expect(l.to.startsWith('/'), `${l.to} is not a route`).toBe(true);
        // A hint that restates the label is the sidebar's problem again.
        expect(l.hint.length, `${l.to} has no hint`).toBeGreaterThan(10);
        expect(l.hint.toLowerCase()).not.toBe(l.label.toLowerCase());
      }
      expect(new Set(links.map((l) => l.to)).size).toBe(links.length);
    }
  });

  it('does not show the same siblings on every page of one hub', () => {
    // A hub of fifteen that surfaced the same three pages on all fifteen
    // would be a footer that is technically present and practically useless.
    const a = relatedFor('/tca').map((l) => l.to).join();
    const b = relatedFor('/correlation').map((l) => l.to).join();
    const c = relatedFor('/replay').map((l) => l.to).join();
    expect(new Set([a, b, c]).size).toBeGreaterThan(1);
  });

  it('is stable across renders, so a footer does not reshuffle on refresh', () => {
    expect(relatedFor('/tca')).toEqual(relatedFor('/tca'));
  });

  it('finds somewhere to go for a page that is in no nav item at all', () => {
    // A detail page like /positions/P-8841 is in no nav item and never will
    // be — and an exact-match lookup derived NOTHING for it, so the one kind
    // of page most likely to be a leaf was the one kind that stayed a dead
    // end. Prefix first, then the hubs, which are always a correct answer.
    const detail = relatedFor('/positions/P-8841');
    expect(detail.length).toBeGreaterThan(0);
    for (const l of detail) expect(l.hint.length).toBeGreaterThan(10);

    const nowhere = relatedFor('/a-route-that-does-not-exist');
    expect(nowhere.length).toBeGreaterThan(0);
    // Admin hubs are not offered to a reader who probably cannot open them.
    expect(nowhere.map((l) => l.to)).not.toContain('/operations');
  });
});
