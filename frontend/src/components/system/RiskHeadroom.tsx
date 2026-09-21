/**
 * RiskHeadroom — how close is this account to being stopped out by a rule?
 *
 * `prop_firm_mode.json` ships with `enabled: true` and the FTMO ruleset, so a
 * daily-loss limit and a maximum drawdown are live constraints on a fresh
 * deployment, and the margin call is a third. None of them appeared anywhere
 * in the UI. A trader reading "margin level 1116.6%" is not being told the
 * thing they are actually afraid of.
 *
 * So this is one bar for the three rules that can end the session, and a line
 * of prose naming whichever is nearest, in money. The bar is the glance; the
 * sentence is the answer.
 *
 * It reports headroom; it does not enforce anything. The gates live in
 * `risk/manager.py` and `invariants/`, and a display that implied otherwise
 * would be the shape this repository keeps finding — a control that looks
 * like a control and runs nothing.
 */

import React from 'react';

export interface Constraint {
  /** What the rule is called, in the words the trader knows it by. */
  name: string;
  /** 0–1. How much of the allowance is spent. Clamped for display. */
  used: number;
  /** Money still available before the rule bites. */
  remaining: number;
  tone: 'loss' | 'warn' | 'accent';
}

const FILL: Record<Constraint['tone'], string> = {
  loss: 'bg-loss',
  warn: 'bg-warn',
  accent: 'bg-accent',
};

const SWATCH: Record<Constraint['tone'], string> = {
  loss: 'bg-loss',
  warn: 'bg-warn',
  accent: 'bg-accent',
};

/**
 * The binding constraint is the one with the least headroom left, which is not
 * always the one with the largest absolute number. Ties resolve to the first
 * given, so the caller's ordering is the tiebreak rather than an accident.
 */
export function nearestConstraint(constraints: readonly Constraint[]): Constraint | null {
  let worst: Constraint | null = null;
  for (const c of constraints) {
    if (worst === null || c.used > worst.used) worst = c;
  }
  return worst;
}

const clamp01 = (n: number): number => (Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : 0);

export const RiskHeadroom: React.FC<{
  constraints: readonly Constraint[];
  /** Formats money the way the rest of the screen does. */
  format: (value: number) => string;
  className?: string;
}> = ({ constraints, format, className = '' }) => {
  const nearest = nearestConstraint(constraints);
  if (!nearest) return null;

  const tone = nearest.used > 0.75 ? 'text-loss' : nearest.used > 0.5 ? 'text-warn' : 'text-gain';
  const summary = constraints
    .map((c) => `${c.name} ${Math.round(clamp01(c.used) * 100)} percent used`)
    .join(', ');

  return (
    <div className={`flex flex-col gap-s3 p-card ${className}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-s3">
        <span className="text-label text-dim">
          Nearest constraint · <strong className="font-semibold text-ink">{nearest.name}</strong>
        </span>
        <span className={`font-mono text-value font-semibold tabular-nums ${tone}`}>
          {format(nearest.remaining)} left
        </span>
      </div>

      <div
        className="flex h-2 overflow-hidden rounded-pill border border-hairline bg-sunken"
        role="img"
        aria-label={`Risk headroom: ${summary}.`}
      >
        {constraints.map((c) => (
          <i
            key={c.name}
            className={`block h-full ${FILL[c.tone]}`}
            style={{ width: `${(clamp01(c.used) * 100).toFixed(1)}%` }}
          />
        ))}
      </div>

      <div className="flex flex-wrap gap-x-s5 gap-y-s1 font-mono text-micro tabular-nums text-faint">
        {constraints.map((c) => (
          <span key={c.name} className="inline-flex items-center gap-s2">
            <i className={`inline-block h-1.5 w-1.5 rounded-sm2 ${SWATCH[c.tone]}`} aria-hidden />
            {c.name} {Math.round(clamp01(c.used) * 100)}%
          </span>
        ))}
      </div>
    </div>
  );
};
