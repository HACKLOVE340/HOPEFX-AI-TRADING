/**
 * SubPageGrid — what is behind this page.
 *
 * The app has 87 routes and, until the position detail page, exactly one of
 * them took a parameter. Everything was a flat top-level destination reachable
 * only from the sidebar, which is why a large product read as a shallow one:
 * nothing drilled in, so nothing felt like it had depth behind it.
 *
 * This is the hub half of the fix. A section page declares its children and
 * they render as a grid of real links — visible, keyboard-operable, and
 * described, so a reader can see what exists without opening a menu and
 * guessing. Five or fifteen children is fine; the grid fills the row it has.
 *
 * The other half is the leaf: a row that opens a detail page for the thing in
 * it. See `pages/PositionDetail.tsx`.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, type LucideIcon } from 'lucide-react';

export interface SubPage {
  to: string;
  title: string;
  /** One line on what the page is for. Written from the reader's side. */
  description: string;
  icon?: LucideIcon;
  /** A live figure worth seeing before clicking — a count, a state. */
  badge?: React.ReactNode;
}

export const SubPageGrid: React.FC<{
  items: readonly SubPage[];
  /** Labels the region for screen readers when the grid has no visible title. */
  label?: string;
  className?: string;
}> = ({ items, label, className = '' }) => (
  <nav
    aria-label={label ?? 'Sections'}
    className={`grid gap-grid [grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr))] ${className}`}
  >
    {items.map((item) => {
      const Icon = item.icon;
      return (
        <Link
          // Destination AND label — see CrossLinkBar.
          key={`${item.to}|${item.title}`}
          to={item.to}
          className="group flex flex-col gap-s2 rounded-md2 border border-edge bg-surface p-card
                     no-underline shadow-e1 transition-colors duration-fast ease-out
                     hover:border-accent hover:bg-hover
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        >
          <span className="flex items-center gap-s2">
            {Icon ? <Icon size={14} strokeWidth={2} className="text-accent" aria-hidden /> : null}
            <span className="text-body font-semibold text-strong">{item.title}</span>
            {item.badge !== undefined && (
              <span className="ml-auto font-mono text-micro tabular-nums text-faint">{item.badge}</span>
            )}
            <ArrowUpRight
              size={13}
              strokeWidth={2}
              aria-hidden
              className={`text-faint transition-colors duration-fast ease-out group-hover:text-accent
                          ${item.badge !== undefined ? '' : 'ml-auto'}`}
            />
          </span>
          <span className="text-label text-dim">{item.description}</span>
        </Link>
      );
    })}
  </nav>
);
