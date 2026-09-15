/**
 * PageShell — the standard page.
 *
 * Measured on 2026-09-14, across 74 pages:
 *
 *   * **twelve different page widths** — 360, 420, 460, 480, 520, 700, 800,
 *     900, 1100, 1200, 1400, 1500 — chosen per page with nothing to say which
 *     was right for what;
 *   * **31 of 74** used `PageHeader`, so 43 had no breadcrumb, no consistent
 *     title, and nowhere for their actions to live;
 *   * **40 of 74 ended in nothing** — no outbound link anywhere in the content
 *     area, so the reader could only leave by the sidebar.
 *
 * That is what "the pages aren't standard" means, precisely. Tokens fixed the
 * colours; this fixes the frame around them.
 *
 * Those three counts are real but were taken over every file under `pages/`,
 * which is 74 files and 66 pages: the difference is `settings/*Section` and
 * `superadmin/*Section`, which render as tab content inside Settings and
 * SuperAdminDashboard and must NEVER be on this shell — a panel with its own
 * page header, its own width and a "Where to next" footer in the middle of a
 * tab is worse than one without. Nor do the pages mounted outside <AppShell/>
 * — /privacy, /terms, /pricing — belong here: this footer is the AUTHENTICATED
 * navigation, and offering it to a signed-out reader is worse than offering
 * nothing. `scripts/frontend_page_shell_ratchet.py` scopes itself to what the
 * router mounts behind the app shell; it read 80 of 108 while counting panels
 * and public pages as pages. Run it for today's figure —
 * `python scripts/frontend_page_shell_ratchet.py --check` — rather than reading
 * one here: 14 of 63 were still off the shell on 2026-09-14, and a number typed
 * into a comment is stale by the next migration.
 *
 * Three widths replace twelve, and they are chosen by what the page IS rather
 * than by how much happened to fit:
 *
 *   wide      a book, a ledger, a terminal — as much as the screen gives
 *   standard  a normal working page
 *   narrow    prose or a single form, kept near 65 characters so it reads
 *
 * The footer is the part that matters most and is the easiest to skip:
 * `related` defaults to ON and derives its links from navConfig, so a page
 * cannot quietly become a dead end. Pass `related={false}` only where leaving
 * is the wrong thing to offer — a checkout, a confirmation, a KYC step.
 */

import React from 'react';
import { useLocation } from 'react-router-dom';

import { PageHeader, type PageTab } from '../PageHeader';
import { RelatedPages, type RelatedLink } from '../RelatedPages';
import type { BreadcrumbItem } from '../Breadcrumb';
import { relatedFor } from '../../lib/related';

/**
 * `full` is the fourth, added 2026-09-15 for the workspaces.
 *
 * Four pages could not reach this shell because it had no width for them —
 * `NuclearDashboardPage`, `AICore`, `Trading`, `TradingDashboard`. Each is a
 * workspace rather than a document: a chart surface, an order book, a plane.
 * Forcing one into a max-width does not restyle it, it LETTERBOXES it and takes
 * away screen the operator was using, which is a migration that removes what a
 * page displays.
 *
 * So the shell gained a width rather than the pages losing their layout. It is
 * purely additive: the other three are untouched and `full` is opt-in.
 */
export type PageWidth = 'wide' | 'standard' | 'narrow' | 'full';

const WIDTH: Record<PageWidth, string> = {
  wide: 'max-w-[var(--page-wide)]',
  standard: 'max-w-[var(--page-standard)]',
  narrow: 'max-w-[var(--page-narrow)]',
  full: 'max-w-none',
};

export interface PageShellProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  width?: PageWidth;
  breadcrumbs?: BreadcrumbItem[];
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  tabs?: PageTab[];
  activeTab?: string;
  onTabChange?: (key: string) => void;
  icon?: React.ComponentProps<typeof PageHeader>['icon'];
  /**
   * The body fills the shell and scrolls inside itself, rather than growing the
   * page.
   *
   * The default body wrapper is a `flex flex-col gap-grid` with no `min-h-0`,
   * so a child asking for `flex: 1; min-height: 0` gets nothing and its inner
   * scroller never scrolls. `min-h-0` is the half that is easy to forget: a
   * flex child refuses to shrink below its content without it.
   *
   * Deliberately a separate prop rather than something `width="full"` implies.
   * A full-bleed page that scrolls as one long document is a real shape, and so
   * is a standard-width page with an inner scroller; coupling the two would
   * take one of them away.
   */
  fills?: boolean;
  /**
   * Onward navigation. `true` derives it; an array adds hand-picked links
   * ahead of the derived ones; `false` suppresses it, which should be rare
   * and is only right where leaving mid-flow would lose the user's work.
   */
  related?: boolean | RelatedLink[];
  className?: string;
}

export const PageShell: React.FC<PageShellProps> = ({
  title,
  subtitle,
  children,
  width = 'standard',
  breadcrumbs,
  badge,
  actions,
  tabs,
  activeTab,
  onTabChange,
  icon,
  fills = false,
  related = true,
  className = '',
}) => {
  const { pathname } = useLocation();
  const links =
    related === false
      ? []
      : relatedFor(pathname, Array.isArray(related) ? related : []);

  return (
    <div
      // `flex-[1_0_auto]` is the rule `.page-content` carried, and this shell
      // replaced that class without it: grow to fill `.app-shell-scroller`
      // (a flex column) when the page is short, never shrink below content when
      // it is tall. NOT `flex-1` — that is `1 1 0%`, which index.css records as
      // having clamped every page to the viewport and trapped taller content.
      // Measured before the fix at 1440x900: seven migrated pages stopped at
      // 540-701px in a 900px scroller while every legacy page filled it.
      className={`mx-auto flex w-full flex-[1_0_auto] flex-col ${WIDTH[width]} px-s4 pb-s8 pt-s4
                  sm:px-s5 md:px-s6 md:pt-s5 ${className}`}
    >
      <PageHeader
        title={title}
        subtitle={subtitle}
        breadcrumbs={breadcrumbs}
        badge={badge}
        actions={actions}
        tabs={tabs}
        activeTab={activeTab}
        onTabChange={onTabChange}
        icon={icon}
      />

      {/* One rhythm for every page. Sections are siblings in a flex column with
          a single gap token, so vertical spacing is a property of the shell
          rather than a margin each section remembers differently. */}
      <div className={`flex flex-col gap-grid${fills ? ' flex-1 min-h-0' : ''}`}>{children}</div>

      {links.length > 0 && <RelatedPages links={links} />}
    </div>
  );
};
