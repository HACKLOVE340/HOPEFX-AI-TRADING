/**
 * Breadcrumb — hierarchical navigation trail.
 *
 * Usage:
 *   <Breadcrumb items={[
 *     { label: 'Dashboard', href: '/dashboard' },
 *     { label: 'Performance' },
 *   ]} />
 */

import React from 'react';
import { Link } from 'react-router-dom';

export interface BreadcrumbItem {
  label: string;
  /** When omitted the item renders as plain text (current page). */
  href?: string;
  icon?: React.ReactNode;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  style?: React.CSSProperties;
}

export const Breadcrumb: React.FC<BreadcrumbProps> = ({ items, style }) => (
  <nav
    aria-label="Breadcrumb"
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      fontSize: 12,
      color: '#64748b',
      marginBottom: 12,
      flexWrap: 'wrap',
      ...style,
    }}
  >
    {items.map((item, idx) => {
      const isLast = idx === items.length - 1;
      return (
        <React.Fragment key={idx}>
          {idx > 0 && (
            <span style={{ color: '#334155', userSelect: 'none', fontSize: 11 }}>›</span>
          )}
          {item.href && !isLast ? (
            <Link
              to={item.href}
              style={{
                color: '#64748b',
                textDecoration: 'none',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                transition: 'color 0.15s',
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.color = '#94a3b8';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.color = '#64748b';
              }}
            >
              {item.icon && <span style={{ lineHeight: 1 }}>{item.icon}</span>}
              {item.label}
            </Link>
          ) : (
            <span
              style={{
                color: isLast ? '#94a3b8' : '#64748b',
                fontWeight: isLast ? 500 : 400,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              {item.icon && <span style={{ lineHeight: 1 }}>{item.icon}</span>}
              {item.label}
            </span>
          )}
        </React.Fragment>
      );
    })}
  </nav>
);
