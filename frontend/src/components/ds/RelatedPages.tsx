/**
 * ds/RelatedPages.tsx — the footer that ends a page with somewhere to go.
 *
 * Why this exists: 31 of 82 routes have ZERO outbound links in their content
 * area (audit F188/F196). A user who lands on /watchlist, /signals, /backtest
 * or /terminal can only leave via the sidebar — there is no "see the trades
 * behind this", no next step. Professional apps chain screens together.
 *
 * Deliberately a nav landmark with a label, so it is skippable and does not
 * pollute the reading order of the page's real content.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { ArrowRight } from 'lucide-react';

export interface RelatedLink {
  to: string;
  label: string;
  /** What the destination answers — the reason to click, not a restatement. */
  hint: string;
  icon?: LucideIcon;
}

export const RelatedPages: React.FC<{ links: RelatedLink[]; title?: string }> = ({
  links, title = 'Where to next',
}) => {
  if (links.length === 0) return null;
  return (
    <nav aria-label={title} className="mt-4">
      <h2 className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
        {title}
      </h2>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {links.map((l) => (
          <li key={l.to}>
            <Link
              to={l.to}
              className="group flex min-h-[44px] items-center gap-3 rounded-lg border
                         border-[#1e2d3d] bg-[#0d1421] px-3 py-2.5 cursor-pointer
                         transition-colors duration-150 hover:border-[#2b3f56] hover:bg-[#111827]
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-sky-500 focus-visible:ring-offset-2
                         focus-visible:ring-offset-[#080c14]"
            >
              {l.icon && (
                <span aria-hidden className="shrink-0 text-slate-600 transition-colors group-hover:text-sky-400">
                  <l.icon size={15} strokeWidth={1.75} />
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-slate-300">{l.label}</span>
                <span className="block truncate text-[11.5px] text-slate-600">{l.hint}</span>
              </span>
              <ArrowRight
                size={13} strokeWidth={2} aria-hidden
                className="shrink-0 text-slate-700 transition-colors group-hover:text-sky-400"
              />
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
};
