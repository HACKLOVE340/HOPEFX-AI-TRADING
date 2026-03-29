/**
 * EmptyState — zero-data placeholder with icon, title, and optional CTA.
 */

import React from 'react';

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  style?: React.CSSProperties;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon = '📭',
  title,
  description,
  action,
  style,
}) => (
  <div
    style={{
      alignItems: 'center',
      color: '#64748b',
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      padding: '48px 24px',
      textAlign: 'center',
      ...style,
    }}
  >
    <span style={{ fontSize: 40, lineHeight: 1 }}>{icon}</span>
    <p style={{ color: '#94a3b8', fontSize: 15, fontWeight: 600, margin: 0 }}>{title}</p>
    {description && (
      <p style={{ fontSize: 13, margin: 0, maxWidth: 320 }}>{description}</p>
    )}
    {action && <div style={{ marginTop: 8 }}>{action}</div>}
  </div>
);
