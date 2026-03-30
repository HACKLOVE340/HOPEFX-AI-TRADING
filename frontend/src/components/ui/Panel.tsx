/**
 * components/ui/Panel.tsx
 * Base panel container used by every dashboard widget.
 */

import React from 'react';
import { cn } from '../../lib/utils';

interface PanelProps {
  title?:       string;
  subtitle?:    string;
  headerRight?: React.ReactNode;
  children:     React.ReactNode;
  className?:   string;
  bodyClass?:   string;
  noPad?:       boolean;
}

export function Panel({
  title,
  subtitle,
  headerRight,
  children,
  className,
  bodyClass,
  noPad = false,
}: PanelProps) {
  return (
    <div
      className={cn(
        'flex flex-col bg-[#0d1421] border border-[#1e2d3d] rounded-lg overflow-hidden',
        className,
      )}
    >
      {(title || headerRight) && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#1e2d3d] shrink-0">
          <div className="flex items-center gap-2">
            {title && (
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                {title}
              </span>
            )}
            {subtitle && (
              <span className="text-[10px] text-slate-600">{subtitle}</span>
            )}
          </div>
          {headerRight && (
            <div className="flex items-center gap-2">{headerRight}</div>
          )}
        </div>
      )}
      <div className={cn('flex-1 min-h-0', !noPad && 'p-4', bodyClass)}>
        {children}
      </div>
    </div>
  );
}
