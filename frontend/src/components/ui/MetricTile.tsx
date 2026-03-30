/**
 * components/ui/MetricTile.tsx
 * Single KPI tile used in account metrics bar and risk dashboard.
 */

import React from 'react';
import { cn } from '../../lib/utils';

interface MetricTileProps {
  label:      string;
  value:      string | React.ReactNode;
  sub?:       string | React.ReactNode;
  valueColor?: string;
  icon?:      React.ReactNode;
  className?: string;
  compact?:   boolean;
}

export function MetricTile({
  label,
  value,
  sub,
  valueColor,
  icon,
  className,
  compact = false,
}: MetricTileProps) {
  return (
    <div
      className={cn(
        'flex flex-col gap-0.5',
        compact ? 'min-w-[80px]' : 'min-w-[100px]',
        className,
      )}
    >
      <div className="flex items-center gap-1">
        {icon && <span className="text-slate-500">{icon}</span>}
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-500 truncate">
          {label}
        </span>
      </div>
      <span
        className={cn(
          'font-mono tabular-nums font-semibold leading-tight',
          compact ? 'text-sm' : 'text-base',
        )}
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
      </span>
      {sub && (
        <span className="text-[10px] text-slate-600 font-mono tabular-nums">{sub}</span>
      )}
    </div>
  );
}
