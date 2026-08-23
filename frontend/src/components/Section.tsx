/**
 * Section — a titled content block whose heading is a real <h2>.
 *
 * Pairs with PageHeader's single <h1>. Measured: /dashboard rendered ZERO
 * h1-h3 while /landing rendered 24 (audit F173), so the authenticated app had
 * no document outline to navigate by.
 */

import React from 'react';

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
