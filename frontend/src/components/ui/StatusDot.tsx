/**
 * components/ui/StatusDot.tsx
 * Animated connection/status indicator dot.
 */

import React from 'react';
import { cn } from '../../lib/utils';
import type { WsStatus } from '../../types';

interface StatusDotProps {
  status:    WsStatus | 'ok' | 'degraded' | 'error' | 'offline';
  label?:    string;
  size?:     'sm' | 'md';
  className?: string;
}

const COLOR: Record<string, string> = {
  connected:    'bg-[#00e676]',
  ok:           'bg-[#00e676]',
  connecting:   'bg-[#ffb800]',
  degraded:     'bg-[#ffb800]',
  disconnected: 'bg-[#475569]',
  offline:      'bg-[#475569]',
  error:        'bg-[#ff3b5c]',
};

const PULSE: Record<string, boolean> = {
  connected:  true,
  ok:         false,
  connecting: true,
  degraded:   true,
};

export function StatusDot({ status, label, size = 'sm', className }: StatusDotProps) {
  const color = COLOR[status] ?? 'bg-[#475569]';
  const pulse = PULSE[status] ?? false;
  const dim   = size === 'md' ? 'w-2.5 h-2.5' : 'w-1.5 h-1.5';

  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span className={cn('rounded-full shrink-0', dim, color, pulse && 'animate-pulse')} />
      {label && (
        <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500">
          {label}
        </span>
      )}
    </span>
  );
}
