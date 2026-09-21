/**
 * components/ui/StaleDataNotice.tsx
 *
 * The visible half of the F1-01 fix. A page that could not load its data must
 * say so — otherwise it renders identically whether the backend is healthy or
 * completely unreachable, and every number on it reads as fact.
 *
 * Deliberately `aria-live="polite"`, not `assertive`: this is important, not an
 * emergency, and an assertive region interrupts a screen-reader user mid-word.
 */

import React from 'react';

export function StaleDataNotice({
  failed,
  what = 'data',
  className = '',
}: {
  failed: boolean;
  what?: string;
  className?: string;
}) {
  if (!failed) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={
        'flex items-start gap-2 px-3 py-2 rounded border text-[12px] ' +
        'bg-[#ffb800]/10 border-[#ffb800]/30 text-[#ffb800] ' +
        className
      }
    >
      <span aria-hidden="true">⚠</span>
      <span>
        Couldn&apos;t load {what}. What you see below may be out of date — it is not live.
        Check your broker directly before acting on it.
      </span>
    </div>
  );
}

export default StaleDataNotice;
