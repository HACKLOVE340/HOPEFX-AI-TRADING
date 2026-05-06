/**
 * PageHeader — consistent page title, optional subtitle, breadcrumb trail,
 * status badge, and right-aligned action slot.
 *
 * Used at the top of every authenticated page.
 */

import React from 'react';
import { Breadcrumb, type BreadcrumbItem } from './Breadcrumb';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Breadcrumb trail rendered above the title. */
  breadcrumbs?: BreadcrumbItem[];
  /** Small badge rendered next to the title (e.g. "BETA", "LIVE"). */
  badge?: React.ReactNode;
  /** Right-aligned action buttons / controls. */
  actions?: React.ReactNode;
  style?: React.CSSProperties;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  breadcrumbs,
  badge,
  actions,
  style,
}) => (
  <div
    style={{
      borderBottom: '1px solid var(--border, #1e293b)',
      marginBottom: 24,
      paddingBottom: 16,
      ...style,
    }}
  >
    {breadcrumbs && breadcrumbs.length > 0 && (
      <Breadcrumb items={breadcrumbs} />
    )}

    <div
      style={{
        alignItems: 'flex-start',
        display: 'flex',
        gap: 12,
        justifyContent: 'space-between',
      }}
    >
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <h1
            style={{
              color: 'var(--text, #f1f5f9)',
              fontSize: 20,
              fontWeight: 700,
              letterSpacing: -0.3,
              margin: 0,
            }}
          >
            {title}
          </h1>
          {badge && badge}
        </div>
        {subtitle && (
          <p
            style={{
              color: 'var(--text-muted, #64748b)',
              fontSize: 13,
              margin: '4px 0 0',
            }}
          >
            {subtitle}
          </p>
        )}
      </div>

      {actions && (
        <div style={{ alignItems: 'center', display: 'flex', flexShrink: 0, gap: 8 }}>
          {actions}
        </div>
      )}
    </div>
  </div>
);
