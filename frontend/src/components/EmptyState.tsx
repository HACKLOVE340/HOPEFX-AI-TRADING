/**
 * EmptyState — zero-data placeholder with icon, title, description,
 * optional CTA button, and optional cross-links to related pages.
 */

import React from 'react';
import { Link } from 'react-router-dom';

export interface EmptyStateLink {
  label: string;
  href: string;
  icon?: string;
}

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  /** Quick-links to related pages shown below the CTA */
  links?: EmptyStateLink[];
  style?: React.CSSProperties;
  /** Compact variant — less vertical padding */
  compact?: boolean;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon = '📭',
  title,
  description,
  action,
  links,
  style,
  compact = false,
}) => (
  <div
    style={{
      alignItems: 'center',
      color: '#64748b',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      padding: compact ? '28px 24px' : '56px 24px',
      textAlign: 'center',
      ...style,
    }}
  >
    <div style={{
      width: 64, height: 64, borderRadius: 16,
      background: 'rgba(30,41,59,0.8)',
      border: '1px solid #1e293b',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 28, lineHeight: 1,
      marginBottom: 4,
    }}>
      {icon}
    </div>
    <p style={{ color: '#94a3b8', fontSize: 15, fontWeight: 600, margin: 0 }}>{title}</p>
    {description && (
      <p style={{ fontSize: 13, margin: 0, maxWidth: 360, lineHeight: 1.6, color: '#64748b' }}>
        {description}
      </p>
    )}
    {action && <div style={{ marginTop: 8 }}>{action}</div>}
    {links && links.length > 0 && (
      <div style={{
        display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center',
        marginTop: action ? 4 : 8,
      }}>
        {links.map((l) => (
          <Link
            key={l.href}
            to={l.href}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              fontSize: 12, color: '#475569',
              padding: '5px 12px', borderRadius: 6,
              border: '1px solid #1e293b',
              background: 'rgba(30,41,59,0.5)',
              textDecoration: 'none',
              transition: 'color 0.15s, border-color 0.15s',
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget as HTMLAnchorElement;
              el.style.color = '#94a3b8';
              el.style.borderColor = '#334155';
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget as HTMLAnchorElement;
              el.style.color = '#475569';
              el.style.borderColor = '#1e293b';
            }}
          >
            {l.icon && <span>{l.icon}</span>}
            {l.label}
          </Link>
        ))}
      </div>
    )}
  </div>
);
