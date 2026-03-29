/**
 * PageHeader — consistent page title + optional subtitle + action slot.
 * Used at the top of every authenticated page.
 */

import React from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Right-aligned action buttons / controls */
  actions?: React.ReactNode;
  style?: React.CSSProperties;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  actions,
  style,
}) => (
  <div
    style={{
      alignItems: 'flex-start',
      borderBottom: '1px solid var(--border, #334155)',
      display: 'flex',
      gap: 12,
      justifyContent: 'space-between',
      marginBottom: 24,
      paddingBottom: 16,
      ...style,
    }}
  >
    <div>
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
);
