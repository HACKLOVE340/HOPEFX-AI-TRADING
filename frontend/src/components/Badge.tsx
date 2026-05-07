/**
 * Badge — small status/label pill.
 *
 * Variants: success | warning | danger | info | neutral
 */

import React from 'react';

export type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}

const VARIANT_STYLES: Record<BadgeVariant, React.CSSProperties> = {
  success: { background: 'rgba(74,222,128,0.15)', color: '#4ade80', border: '1px solid rgba(74,222,128,0.3)' },
  warning: { background: 'rgba(251,191,36,0.15)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.3)' },
  danger:  { background: 'rgba(248,113,113,0.15)', color: '#f87171', border: '1px solid rgba(248,113,113,0.3)' },
  info:    { background: 'rgba(96,165,250,0.15)',  color: '#60a5fa', border: '1px solid rgba(96,165,250,0.3)' },
  neutral: { background: 'rgba(148,163,184,0.15)', color: '#94a3b8', border: '1px solid rgba(148,163,184,0.3)' },
};

export const Badge: React.FC<BadgeProps> = ({ variant = 'neutral', children, style, className }) => (
  <span
    className={className}
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: 0.3,
      padding: '2px 7px',
      textTransform: 'uppercase',
      whiteSpace: 'nowrap',
      ...VARIANT_STYLES[variant],
      ...style,
    }}
  >
    {children}
  </span>
);
