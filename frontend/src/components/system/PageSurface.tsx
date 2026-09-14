/**
 * PageSurface — one place that decides how every route is dressed.
 *
 * 72 pages, and no two of them agreed on density: 24 distinct font sizes
 * between 9px and 56px, with 343 uses of 12px and 366 of 13px sitting a pixel
 * apart. Fixing that by editing 72 files would have produced a 73rd opinion
 * the first time someone added a page.
 *
 * So the decision is made here, once, from the route. `wrap()` in App.tsx puts
 * every route inside this, it looks up the path, and it stamps two attributes:
 *
 *   data-density   how tight the type and padding are
 *   data-surface   which palette is underneath
 *
 * Both are scoped token overrides declared in `index.css`. Nothing else
 * changes — no second component library, no per-page pixel decisions, and a
 * page that has not been migrated still inherits the right density for what it
 * is. A new page gets a sensible default by being a new page.
 *
 * The two axes are independent on purpose: an AI page that is also a dense
 * table is one attribute on each, not a fourth palette.
 */

import React from 'react';
import { useLocation } from 'react-router-dom';

export type Density = 'comfortable' | 'promax' | 'ultra';
export type Surface = 'default' | 'ai';

/**
 * Data surfaces. The reader is scanning rows, not reading sentences: books,
 * ledgers, terminals, audit trails, admin tables. Ultra buys roughly three
 * extra rows per screen at a laptop height, which is the difference between
 * seeing your open risk and scrolling for it.
 */
const ULTRA = [
  '/trade', '/trading', '/terminal', '/portfolio', '/watchlist', '/positions',
  '/pnl', '/journal', '/tca', '/audit', '/audit-log', '/leaderboard',
  '/replay', '/walk-forward', '/ab-testing', '/observability', '/reliability',
  '/system-reliability', '/security', '/superadmin', '/admin',
  '/master-control', '/whitelabel', '/sub-accounts', '/support-console',
  '/prop-firm', '/correlation', '/indicators', '/backtest', '/ml-ops',
  '/signals', '/performance', '/alerts', '/auto-heal', '/wallet',
];

/**
 * Reading surfaces. Prose, not figures — and prose at 13px in a 1.5 line box
 * is a wall. These are also the pages a new user meets first, where looking
 * approachable is worth more than fitting another paragraph above the fold.
 */
const COMFORTABLE = [
  '/academy', '/docs', '/terms', '/privacy', '/risk-disclosure', '/onboarding',
  '/pricing', '/support', '/status', '/system-status', '/transparency', '/kyc',
  '/upgrade', '/landing', '/profile', '/teams', '/research',
];

/**
 * AI surfaces. The instrument palette — see InstrumentSurface for what it is
 * and why it stays dark in both themes.
 */
const AI = [
  '/ai-core', '/ai-assistant', '/ai-strategy', '/ai-chart', '/ai-charts',
  '/ai-chart-dashboard', '/intelligence', '/nuclear', '/pattern-detector',
  '/strategy-builder',
];

/** Longest prefix wins, so `/ai-strategy` is not caught by a bare `/ai`. */
function match(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function densityFor(pathname: string): Density {
  if (match(pathname, ULTRA)) return 'ultra';
  if (match(pathname, COMFORTABLE)) return 'comfortable';
  return 'promax';
}

export function surfaceFor(pathname: string): Surface {
  return match(pathname, AI) ? 'ai' : 'default';
}

export const PageSurface: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { pathname } = useLocation();
  const surface = surfaceFor(pathname);
  return (
    <div
      data-density={densityFor(pathname)}
      // Absent rather than "default": an empty attribute would still match
      // [data-surface] selectors written later, and a page would silently
      // acquire a palette nobody chose for it.
      {...(surface === 'ai' ? { 'data-surface': 'ai' } : {})}
      className="contents"
    >
      {children}
    </div>
  );
};
