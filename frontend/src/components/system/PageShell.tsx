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

export type PageWidth = 'wide' | 'standard' | 'narrow';

const WIDTH: Record<PageWidth, string> = {
  wide: 'max-w-[var(--page-wide)]',
  standard: 'max-w-[var(--page-standard)]',
  narrow: 'max-w-[var(--page-narrow)]',
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
      className={`mx-auto flex w-full flex-col ${WIDTH[width]} px-s4 pb-s8 pt-s4
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
      <div className="flex flex-col gap-grid">{children}</div>

      {links.length > 0 && <RelatedPages links={links} />}
    </div>
  );
};
