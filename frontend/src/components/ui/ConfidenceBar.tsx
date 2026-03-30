/**
 * components/ui/ConfidenceBar.tsx
 * Horizontal confidence/progress bar with color-coded fill.
 */

import React from 'react';
import { cn, confColor } from '../../lib/utils';

interface ConfidenceBarProps {
  value:      number;   // 0–1
  label?:     string;
  showPct?:   boolean;
  height?:    'xs' | 'sm' | 'md';
  className?: string;
}

const H = { xs: 'h-0.5', sm: 'h-1', md: 'h-1.5' };

export function ConfidenceBar({
  value,
  label,
  showPct = false,
  height  = 'sm',
  className,
}: ConfidenceBarProps) {
  const pct   = Math.min(Math.max(value * 100, 0), 100);
  const color = confColor(value);

  return (
    <div className={cn('flex items-center gap-2', className)}>
      {label && (
        <span className="text-[10px] text-slate-500 shrink-0 w-16 truncate">{label}</span>
      )}
      <div className={cn('flex-1 bg-[#1e2d3d] rounded-full overflow-hidden', H[height])}>
        <div
          className={cn('h-full rounded-full transition-all duration-500')}
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      {showPct && (
        <span
          className="text-[10px] font-mono tabular-nums shrink-0 w-8 text-right"
          style={{ color }}
        >
          {pct.toFixed(0)}%
        </span>
      )}
    </div>
  );
}
