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
        // `min-w-0` lets the tile shrink inside a narrow grid/flex parent.
        // `min-w-[80px]` alone is a FLOOR: the tile refused to go below it,
        // overflowed the panel, and the panel's `overflow-hidden` cut the value
        // mid-glyph — equity rendered as "$100,000.(" on the dashboard, which
        // reads as a complete number and is not one. See audit F166.
        'min-w-0',
        compact ? 'sm:min-w-[80px]' : 'sm:min-w-[100px]',
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
          'font-mono tabular-nums font-semibold leading-tight truncate',
          // `compact` tiles live in narrow panel grids, so the value font is
          // sized for the CELL, not the viewport — a `sm:` prefix would
          // re-inflate it on every desktop and re-clip the number.
          compact ? 'text-xs' : 'text-base',
        )}
        style={valueColor ? { color: valueColor } : undefined}
        // A monetary value that cannot fit must fail VISIBLY. `truncate` gives
        // an ellipsis ("$100,0…") instead of a mid-glyph cut, and the title
        // carries the full figure for hover and screen readers.
        title={typeof value === 'string' || typeof value === 'number' ? String(value) : undefined}
      >
        {value}
      </span>
      {sub && (
        <span className="text-[10px] text-slate-600 font-mono tabular-nums">{sub}</span>
      )}
    </div>
  );
}
