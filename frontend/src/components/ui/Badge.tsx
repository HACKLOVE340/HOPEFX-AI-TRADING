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
  bull:     'bg-[var(--bull)]/10 text-[var(--bull)] border-[var(--bull)]/20',
  bear:     'bg-[var(--bear)]/10 text-[var(--bear)] border-[var(--bear)]/20',
  neutral:  'bg-slate-800 text-slate-400 border-slate-700',
  high:     'bg-[#ff3b5c]/10 text-[#ff3b5c] border-[#ff3b5c]/20',
  medium:   'bg-[#ffb800]/10 text-[#ffb800] border-[#ffb800]/20',
  low:      'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/20',
  active:   'bg-[var(--bull)]/10 text-[var(--bull)] border-[var(--bull)]/20',
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
          'bg-[var(--bull)]': variant === 'bull' || variant === 'active',
          'bg-[var(--bear)]': variant === 'bear',
          'bg-[#ffb800]': variant === 'medium',
          'bg-[#ff3b5c]': variant === 'high',
          'bg-[var(--accent)]': variant === 'low',
          'bg-slate-500': variant === 'neutral' || variant === 'expired' || variant === 'default',
        })} />
      )}
      {children}
    </span>
  );
}
