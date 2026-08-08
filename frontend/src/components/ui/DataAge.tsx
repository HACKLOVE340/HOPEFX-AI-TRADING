/**
 * components/ui/DataAge.tsx
 *
 * "How old is what I am looking at?" — the indicator S10-05 found missing
 * everywhere in the app.
 *
 * Ticks live, so the label re-renders on a timer; without that it would freeze
 * at the age it had when the parent last rendered, which is the same class of
 * bug it exists to expose.
 */

import React, { useEffect, useState } from 'react';
import { DATA_STALE_AFTER_MS, formatAge } from '../../lib/utils';

export function DataAge({
  at,
  staleAfterMs = DATA_STALE_AFTER_MS,
  label = '',
  className = '',
}: {
  /** Client-side arrival time of the data, ms epoch. Null = never received. */
  at: number | null | undefined;
  staleAfterMs?: number;
  label?: string;
  className?: string;
}) {
  const [, force] = useState(0);

  // Re-render every second so the age counts up on screen rather than freezing
  // at whatever it was when the parent last rendered.
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1_000);
    return () => clearInterval(id);
  }, []);

  const age = at == null ? null : Date.now() - at;
  const stale = age == null || age >= staleAfterMs;

  return (
    <span
      role="status"
      aria-live="polite"
      data-stale={String(stale)}
      title={at == null ? 'No data received yet' : new Date(at).toLocaleTimeString()}
      className={className}
      style={{
        fontSize: 11,
        fontFamily: 'monospace',
        color: stale ? '#ffb800' : '#64748b',
      }}
    >
      {label ? `${label} ` : ''}
      {at == null ? 'no data' : formatAge(age)}
    </span>
  );
}

export default DataAge;
