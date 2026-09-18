/**
 * Data primitives — the three shapes a trading screen actually needs.
 *
 * MetricStrip, KeyValue and Tag. All token-only, all tabular-numeric, all at
 * pro-max density: this is an instrument, and the reader wants more of the
 * book on screen rather than more air around less of it.
 *
 * `tone` is SEMANTIC, never appearance. `gain` and `loss` mean money moved;
 * `warn` means attention; `accent` means interactive. A caller asking for a
 * colour would be writing the same defect the token layer exists to end.
 */

import React from 'react';

export type ValueTone = 'neutral' | 'gain' | 'loss' | 'warn' | 'accent' | 'model';

const TONE: Record<ValueTone, string> = {
  neutral: 'text-strong',
  gain: 'text-gain',
  loss: 'text-loss',
  warn: 'text-warn',
  accent: 'text-accent',
  model: 'text-model',
};

/** Pick a tone from a signed number, so callers stop re-deciding it. */
export function toneOf(value: number | null | undefined): ValueTone {
  if (value === null || value === undefined || Number.isNaN(value)) return 'neutral';
  if (value > 0) return 'gain';
  if (value < 0) return 'loss';
  return 'neutral';
}

export interface Metric {
  label: string;
  value: React.ReactNode;
  /** Secondary line: the context that makes the figure mean something. */
  sub?: React.ReactNode;
  tone?: ValueTone;
}

/**
 * One hairline-divided object, not N floating cards.
 *
 * Five cards imply five separate things to act on. These are one account
 * state, so they read as one object. A fifth item that would otherwise sit
 * alone in a row runs to the end of the grid instead of leaving dead space.
 */
export const MetricStrip: React.FC<{ items: Metric[]; className?: string }> = ({
  items,
  className = '',
}) => (
  <dl
    className={`grid gap-px overflow-hidden rounded-md2 border border-edge bg-edge
                [grid-template-columns:repeat(auto-fit,minmax(118px,1fr))]
                [&>div:last-child:nth-child(odd)]:[grid-column:auto/-1] ${className}`}
  >
    {items.map((m) => (
      <div key={m.label} className="bg-surface px-card py-s3">
        <dt className="text-micro font-medium uppercase text-faint">{m.label}</dt>
        <dd className={`mt-s1 font-mono text-value font-semibold tabular-nums ${TONE[m.tone ?? 'neutral']}`}>
          {m.value}
        </dd>
        {m.sub !== undefined && (
          <div className="mt-s1 font-mono text-micro tabular-nums text-faint">{m.sub}</div>
        )}
      </div>
    ))}
  </dl>
);

export interface KeyValueRow {
  label: React.ReactNode;
  value: React.ReactNode;
  tone?: ValueTone;
}

/** Label left, figure right, hairline between. The densest honest layout. */
export const KeyValue: React.FC<{ rows: KeyValueRow[]; className?: string }> = ({
  rows,
  className = '',
}) => (
  <dl className={`flex flex-col ${className}`}>
    {rows.map((r, i) => (
      <div
        key={typeof r.label === 'string' ? r.label : i}
        className="flex items-baseline justify-between gap-s4 border-b border-hairline px-card py-row last:border-b-0"
      >
        <dt className="text-label text-dim">{r.label}</dt>
        <dd className={`m-0 text-right font-mono text-label font-medium tabular-nums ${TONE[r.tone ?? 'neutral']}`}>
          {r.value}
        </dd>
      </div>
    ))}
  </dl>
);

/**
 * Tag — a pill that encodes state in form as well as in text, so what needs
 * attention reads at a glance rather than after a sentence.
 */
export const Tag: React.FC<{ tone?: ValueTone; children: React.ReactNode; className?: string }> = ({
  tone = 'neutral',
  children,
  className = '',
}) => (
  <span
    className={`inline-block rounded-pill border border-current px-s2 py-px font-mono text-micro
                uppercase tracking-wider ${TONE[tone]} ${className}`}
  >
    {children}
  </span>
);
