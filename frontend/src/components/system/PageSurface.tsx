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

import React, { useCallback, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';

import { RelatedPages } from '../RelatedPages';
import { RelatedSlotProvider } from './RelatedContext';
import { relatedFor } from '../../lib/related';

export type Density = 'comfortable' | 'promax' | 'ultra';
export type Surface = 'default' | 'ai';

/**
 * Data surfaces — always dense, and they outrank every opt-out below.
 *
 * The reader is scanning rows, not reading sentences: books, ledgers,
 * terminals, audit trails, admin tables. Ultra buys roughly three extra rows
 * per screen at a laptop height, which is the difference between seeing your
 * open risk and scrolling for it.
 *
 * Dense became the DEFAULT on 2026-09-15, which briefly made this list look
 * redundant — and it was deleted for a few minutes on that reasoning. That was
 * wrong: the list is not "these get dense", it is "these are dense whatever
 * else anyone adds later". It is the precedence rule that stops a future
 * PROMAX entry quietly loosening the order book. Nothing is lost by keeping a
 * statement of intent; something is lost by throwing one away.
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
 * Pages that opt OUT of the dense default, back to the middle tier.
 *
 * Deliberately empty: nothing asks for the middle tier today. It is the seam
 * for a page that turns out to need air without being prose, and
 * `[data-density="promax"]` is still defined in index.css, so adding a path
 * here is the whole change. A path listed in ULTRA above beats anything here.
 */
const PROMAX: readonly string[] = [];

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

/**
 * Where offering somewhere else to go is the wrong thing to do.
 *
 * Mid-flow, leaving loses work or money: a checkout, an identity check, an
 * onboarding sequence. On the auth and marketing pages there is no logged-in
 * product to navigate, and a grid of trader tools under a sign-in form is
 * noise at best. Everywhere else, a dead end is the bug.
 */
const NO_FOOTER = [
  '/login', '/register', '/forgot-password', '/reset-password', '/landing',
  '/onboarding', '/checkout', '/kyc', '/upgrade', '/2fa-setup', '/mobile',
];

/** Longest prefix wins, so `/ai-strategy` is not caught by a bare `/ai`. */
function match(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function densityFor(pathname: string): Density {
  // `ultra` is the default as of 2026-09-15, by the owner's decision in the
  // design review: this is a trading terminal, and the dense tier is what a
  // terminal should feel like. It was previously opt-in per route, so the tier
  // existed and almost nothing used it.
  //
  // COMFORTABLE stays opt-in and still wins, because the pages that are READ
  // rather than scanned — docs, the academy, the legal pages — get worse when
  // you tighten them. `promax` remains defined and is now reached only by a
  // route that asks for it by name.
  // ULTRA first: a data surface stays dense no matter what anyone adds below.
  if (match(pathname, ULTRA)) return 'ultra';
  if (match(pathname, COMFORTABLE)) return 'comfortable';
  if (match(pathname, PROMAX)) return 'promax';
  return 'ultra';
}

export function surfaceFor(pathname: string): Surface {
  return match(pathname, AI) ? 'ai' : 'default';
}

export const PageSurface: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { pathname } = useLocation();
  const surface = surfaceFor(pathname);

  /**
   * The page's own footer wins; this is the fallback for the 40 pages that
   * have none. Counted rather than boolean so two footers unmounting in any
   * order cannot leave the slot wrongly claimed.
   */
  const [claims, setClaims] = useState(0);
  const slot = useMemo(
    () => ({
      claim: () => setClaims((n) => n + 1),
      release: () => setClaims((n) => Math.max(0, n - 1)),
    }),
    [],
  );

  const wantsFooter = !match(pathname, NO_FOOTER);
  const fallback = useCallback(() => relatedFor(pathname), [pathname]);
  const links = claims === 0 && wantsFooter ? fallback() : [];

  return (
    <div
      data-density={densityFor(pathname)}
      // Absent rather than "default": an empty attribute would still match
      // [data-surface] selectors written later, and a page would silently
      // acquire a palette nobody chose for it.
      {...(surface === 'ai' ? { 'data-surface': 'ai' } : {})}
      /* display:contents — the attributes inherit and the footer lands in the
         page's own flow, but this wrapper adds no box, so nothing shifts. */
      className="contents"
    >
      {/* The fallback below sits OUTSIDE this provider deliberately: it renders
          RelatedPages too, and a RelatedPages that could claim the slot would
          claim its own, hide itself, and unclaim — forever. */}
      <RelatedSlotProvider value={slot}>{children}</RelatedSlotProvider>
      {links.length > 0 && (
        <div className="mx-auto w-full max-w-[var(--page-wide)] px-card pb-s7">
          <RelatedPages links={links} />
        </div>
      )}
    </div>
  );
};
