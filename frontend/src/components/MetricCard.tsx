/**
 * MetricCard — single KPI display card.
 *
 * Mobile-first: full-width on xs, auto-sized in grid on sm+.
 * Supports loading skeleton, delta colour, icon, trend sparkline slot.
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
  /**
   * A Lucide element is preferred: it inherits `currentColor` from the icon
   * chip, so it tracks the card's accent. A string is a legacy emoji or glyph
   * call site (audit F170/F175) and still renders.
   */
  icon?: React.ReactNode;
  /** Optional trend indicator: 'up' | 'down' | 'flat' */
  trend?: 'up' | 'down' | 'flat';
  /** Accent colour override for the card border/icon bg */
  accent?: 'blue' | 'green' | 'red' | 'amber' | 'purple';
  className?: string;
  style?: React.CSSProperties;
  loading?: boolean;
  onClick?: () => void;
}

const ACCENT_CLASSES: Record<string, { border: string; iconBg: string }> = {
  blue:   { border: 'border-blue-500/30',   iconBg: 'bg-blue-500/10 text-blue-400' },
  green:  { border: 'border-green-500/30',  iconBg: 'bg-green-500/10 text-green-400' },
  red:    { border: 'border-red-500/30',    iconBg: 'bg-red-500/10 text-red-400' },
  amber:  { border: 'border-amber-500/30',  iconBg: 'bg-amber-500/10 text-amber-400' },
  purple: { border: 'border-purple-500/30', iconBg: 'bg-purple-500/10 text-purple-400' },
};

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  delta,
  deltaPositive,
  subLabel,
  icon,
  trend,
  accent,
  className = '',
  style,
  loading = false,
  onClick,
}) => {
  const deltaColor =
    deltaPositive === undefined
      ? 'text-slate-400'
      : deltaPositive
      ? 'text-green-400'
      : 'text-red-400';

  const accentCls = accent ? ACCENT_CLASSES[accent] : null;
  const borderCls = accentCls ? accentCls.border : 'border-terminal-border';

  const trendIcon =
    trend === 'up' ? '↑' : trend === 'down' ? '↓' : trend === 'flat' ? '→' : null;
  const trendColor =
    trend === 'up' ? 'text-green-400' : trend === 'down' ? 'text-red-400' : 'text-slate-500';

  return (
    <div
      className={`bg-terminal-surface border ${borderCls} rounded-xl flex flex-col gap-1 p-3 sm:p-4 transition-all ${
        onClick ? 'cursor-pointer hover:border-blue-500/40 hover:bg-terminal-raised' : ''
      } ${className}`}
      style={style}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <span className="text-slate-500 text-2xs sm:text-xs font-semibold uppercase tracking-wider leading-tight">
          {label}
        </span>
        {icon && (
          <div
            className={`w-7 h-7 sm:w-8 sm:h-8 rounded-lg flex items-center justify-center text-sm flex-shrink-0 ${
              accentCls ? accentCls.iconBg : 'bg-terminal-raised text-slate-400'
            }`}
          >
            {icon}
          </div>
        )}
      </div>

      {/* Value row */}
      {loading ? (
        <div className="h-7 sm:h-8 rounded bg-terminal-raised animate-pulse mt-1 w-3/5" />
      ) : (
        <div className="flex items-baseline gap-2 mt-1 flex-wrap">
          <span className="text-slate-100 text-xl sm:text-2xl font-bold tracking-tight tabular-nums leading-none">
            {value}
          </span>
          {delta && (
            <span className={`text-xs font-semibold tabular-nums ${deltaColor}`}>
              {delta}
            </span>
          )}
          {trendIcon && (
            <span className={`text-xs font-bold ${trendColor}`}>{trendIcon}</span>
          )}
        </div>
      )}

      {/* Sub-label */}
      {subLabel && !loading && (
        <span className="text-slate-600 text-2xs sm:text-xs mt-0.5 leading-tight">
          {subLabel}
        </span>
      )}
    </div>
  );
};
