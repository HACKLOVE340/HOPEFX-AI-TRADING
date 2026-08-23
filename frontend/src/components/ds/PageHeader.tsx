/**
 * ds/PageHeader.tsx — the single page-title primitive.
 *
 * Why this exists: measured across all 82 routes, `/dashboard` rendered ZERO
 * h1-h3 elements while `/landing` rendered 24 (audit F173). Page titles were
 * styled `div`s, so the authenticated app had no document outline at all —
 * nothing for a screen reader to navigate by, and no visual hierarchy holding
 * the pages together.
 *
 * Every page gets exactly one <h1> from this component, and every Section
 * below it an <h2>. That is the whole contract.
 */

import React from 'react';
import type { LucideIcon } from 'lucide-react';

export interface PageHeaderProps {
  /** The page's name. Becomes the page's only <h1>. Sentence case, no emoji. */
  title: string;
  /** One line saying what the page is for, in the user's terms. */
  subtitle?: string;
  /** Lucide icon, sized and coloured by this component — never a glyph. */
  icon?: LucideIcon;
  /** Live status chip (e.g. a feed indicator) rendered beside the title. */
  status?: React.ReactNode;
  /** Primary actions. Keep to three; more belongs in a menu. */
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title, subtitle, icon: Icon, status, actions,
}) => (
  <header
    className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3
               border-b border-[#1e2d3d] px-4 py-4 sm:px-6"
  >
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2.5">
        {Icon && (
          <span
            aria-hidden
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg
                       bg-[#111827] text-[#00d4ff] ring-1 ring-inset ring-[#1e2d3d]"
          >
            <Icon size={16} strokeWidth={1.75} />
          </span>
        )}
        {/* The page's only h1. */}
        <h1 className="truncate text-[19px] font-semibold tracking-tight text-slate-100">
          {title}
        </h1>
        {status}
      </div>
      {subtitle && (
        <p className="mt-1.5 max-w-[68ch] text-[13px] leading-relaxed text-slate-400">
          {subtitle}
        </p>
      )}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </header>
);

export interface SectionProps {
  /** Becomes an <h2>. Omit only for a purely decorative grouping. */
  title?: string;
  /** Short clarifier under the heading. */
  description?: string;
  /** Right-aligned controls for this section only (filters, export, refresh). */
  actions?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}

export const Section: React.FC<SectionProps> = ({
  title, description, actions, className = '', children,
}) => (
  <section
    className={`rounded-xl border border-[#1e2d3d] bg-[#0d1421] ${className}`}
  >
    {(title || actions) && (
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#1e2d3d] px-4 py-3">
        <div className="min-w-0">
          {title && (
            <h2 className="truncate text-[13px] font-semibold uppercase tracking-wider text-slate-300">
              {title}
            </h2>
          )}
          {description && (
            <p className="mt-0.5 text-[12px] text-slate-500">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    )}
    <div className="p-4">{children}</div>
  </section>
);
