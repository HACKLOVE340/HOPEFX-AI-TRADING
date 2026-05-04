/**
 * components/ui/Panel.tsx
 * Base panel container used by every dashboard widget.
 * Supports maximize (fullscreen overlay) via the maximize button in the header.
 */

import React, { useState } from 'react';
import { cn } from '../../lib/utils';

interface PanelProps {
  title?:       string;
  subtitle?:    string;
  headerRight?: React.ReactNode;
  children:     React.ReactNode;
  className?:   string;
  bodyClass?:   string;
  noPad?:       boolean;
  /** Set false to hide the maximize button */
  maximizable?: boolean;
}

export function Panel({
  title,
  subtitle,
  headerRight,
  children,
  className,
  bodyClass,
  noPad = false,
  maximizable = true,
}: PanelProps) {
  const [maximized, setMaximized] = useState(false);

  const inner = (
    <div
      className={cn(
        'flex flex-col bg-[#0d1421] border border-[#1e2d3d] rounded-lg overflow-hidden',
        maximized ? 'fixed inset-4 z-[9000] rounded-xl shadow-2xl' : '',
        !maximized ? className : '',
      )}
      style={maximized ? { boxShadow: '0 0 0 9999px rgba(0,0,0,0.7)' } : undefined}
    >
      {(title || headerRight || maximizable) && (
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
          <div className="flex items-center gap-2">
            {headerRight && <>{headerRight}</>}
            {maximizable && (
              <button
                onClick={() => setMaximized((v) => !v)}
                title={maximized ? 'Restore' : 'Maximize panel'}
                style={{
                  background: 'transparent', border: 'none',
                  color: maximized ? '#60a5fa' : '#334155',
                  fontSize: 13, cursor: 'pointer', padding: '2px 4px',
                  lineHeight: 1, borderRadius: 4,
                  transition: 'color 0.15s ease',
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#60a5fa'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = maximized ? '#60a5fa' : '#334155'; }}
              >
                {maximized ? '⊡' : '⊞'}
              </button>
            )}
          </div>
        </div>
      )}
      <div className={cn('flex-1 min-h-0', !noPad && 'p-4', bodyClass)}>
        {children}
      </div>
    </div>
  );

  return inner;
}
