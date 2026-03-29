/**
 * MetricCard — single KPI display card.
 *
 * Shows a label, primary value, optional delta (with colour), and optional
 * sub-label. Used across Dashboard, Performance, Risk pages.
 */

import React from 'react';

interface MetricCardProps {
  label: string;
  value: string | number;
  /** Signed delta string, e.g. "+2.4%" or "-$120" */
  delta?: string;
  /** Positive delta = green, negative = red */
  deltaPositive?: boolean;
  subLabel?: string;
  icon?: string;
  style?: React.CSSProperties;
  loading?: boolean;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  delta,
  deltaPositive,
  subLabel,
  icon,
  style,
  loading = false,
}) => {
  const deltaColor =
    deltaPositive === undefined
      ? '#94a3b8'
      : deltaPositive
      ? '#4ade80'
      : '#f87171';

  return (
    <div style={{ ...cardStyle, ...style }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <span style={labelStyle}>{label}</span>
        {icon && <span style={{ fontSize: 18, opacity: 0.6 }}>{icon}</span>}
      </div>

      {loading ? (
        <div style={skeletonStyle} />
      ) : (
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
          <span style={valueStyle}>{value}</span>
          {delta && (
            <span style={{ color: deltaColor, fontSize: 12, fontWeight: 600 }}>
              {delta}
            </span>
          )}
        </div>
      )}

      {subLabel && !loading && (
        <span style={subLabelStyle}>{subLabel}</span>
      )}
    </div>
  );
};

const cardStyle: React.CSSProperties = {
  background: 'var(--surface, #1e293b)',
  border: '1px solid var(--border, #334155)',
  borderRadius: 10,
  display: 'flex',
  flexDirection: 'column',
  gap: 2,
  padding: '14px 16px',
};

const labelStyle: React.CSSProperties = {
  color: 'var(--text-muted, #94a3b8)',
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: 0.5,
  textTransform: 'uppercase',
};

const valueStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)',
  fontSize: 22,
  fontWeight: 700,
  letterSpacing: -0.5,
};

const subLabelStyle: React.CSSProperties = {
  color: 'var(--text-muted, #64748b)',
  fontSize: 11,
  marginTop: 2,
};

const skeletonStyle: React.CSSProperties = {
  background: 'linear-gradient(90deg, #1e293b 25%, #334155 50%, #1e293b 75%)',
  backgroundSize: '200% 100%',
  borderRadius: 4,
  height: 28,
  marginTop: 6,
  width: '60%',
};
