/**
 * components/ui/Badge.tsx
 * Compact label badge for directions, statuses, and impact levels.
 */

import React from 'react';
import { cn } from '../../lib/utils';

type Variant = 'bull' | 'bear' | 'neutral' | 'high' | 'medium' | 'low' | 'active' | 'expired' | 'default';

interface BadgeProps {
  variant?:   Variant;
  children:   React.ReactNode;
  className?: string;
  dot?:       boolean;
}

const STYLES: Record<Variant, string> = {
  bull:     'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/20',
  bear:     'bg-[#ff1744]/10 text-[#ff1744] border-[#ff1744]/20',
  neutral:  'bg-slate-800 text-slate-400 border-slate-700',
  high:     'bg-[#ff3b5c]/10 text-[#ff3b5c] border-[#ff3b5c]/20',
  medium:   'bg-[#ffb800]/10 text-[#ffb800] border-[#ffb800]/20',
  low:      'bg-[#00d4ff]/10 text-[#00d4ff] border-[#00d4ff]/20',
  active:   'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/20',
  expired:  'bg-slate-800 text-slate-500 border-slate-700',
  default:  'bg-slate-800 text-slate-300 border-slate-700',
};

export function Badge({ variant = 'default', children, className, dot }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold',
        'uppercase tracking-wider border',
        STYLES[variant],
        className,
      )}
    >
      {dot && (
        <span className={cn('w-1 h-1 rounded-full', {
          'bg-[#00e676]': variant === 'bull' || variant === 'active',
          'bg-[#ff1744]': variant === 'bear',
          'bg-[#ffb800]': variant === 'medium',
          'bg-[#ff3b5c]': variant === 'high',
          'bg-[#00d4ff]': variant === 'low',
          'bg-slate-500': variant === 'neutral' || variant === 'expired' || variant === 'default',
        })} />
      )}
      {children}
    </span>
  );
}
