/**
 * SignalDistribution — edge-analytics breakdown of generated signals from
 * GET /api/signals/analytics: by strength tier, by direction, by hour of day,
 * and the most active symbols. Read-only; helps a trader see *where* and *when*
 * the engine finds its edge.
 */

import React from 'react';
import type { SignalAnalyticsReport } from '../../types';

const Panel: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div style={{
    background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12,
    padding: 14, flex: 1, minWidth: 240,
  }}>
    <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', marginBottom: 10 }}>{title}</div>
    {children}
  </div>
);

// Horizontal labelled bar.
const Bar: React.FC<{ label: string; value: number; max: number; color: string }> = ({ label, value, max, color }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
    <span style={{ fontSize: 11, color: '#94a3b8', width: 78, flexShrink: 0, textTransform: 'capitalize' }}>{label}</span>
    <div style={{ flex: 1, height: 8, background: '#1e293b', borderRadius: 4, overflow: 'hidden' }}>
      <div style={{ width: max > 0 ? `${(value / max) * 100}%` : '0%', height: '100%', background: color }} />
    </div>
    <span style={{ fontSize: 11, fontWeight: 700, color: '#cbd5e1', width: 32, textAlign: 'right' }}>{value}</span>
  </div>
);

const STRENGTH_ORDER = ['very_strong', 'strong', 'moderate', 'weak', 'very_weak'] as const;
// Keyed by the actual unions rather than `string`, so indexing with a member of
// STRENGTH_ORDER / the direction tuple is definite. Under
// noUncheckedIndexedAccess (audit #38) a `Record<string, T>` lookup is
// `T | undefined` even when the key is provably one of the declared ones.
type StrengthTier = (typeof STRENGTH_ORDER)[number];
type Direction    = 'buy' | 'sell' | 'hold';

const STRENGTH_COLOR: Record<StrengthTier, string> = {
  very_strong: '#22c55e', strong: '#4ade80', moderate: '#fbbf24', weak: '#fb923c', very_weak: '#f87171',
};
const DIR_COLOR: Record<Direction, string> = { buy: '#22c55e', sell: '#f87171', hold: '#94a3b8' };

export const SignalDistribution: React.FC<{ analytics: SignalAnalyticsReport }> = ({ analytics }) => {
  const strengthMax = Math.max(1, ...Object.values(analytics.signals_by_strength ?? {}));
  const dirMax      = Math.max(1, ...Object.values(analytics.signals_by_direction ?? {}));

  // Hourly distribution (0–23).
  const hours = Array.from({ length: 24 }, (_, h) => analytics.hourly_distribution?.[String(h)] ?? 0);
  const hourMax = Math.max(1, ...hours);

  // Top symbols by signal count.
  const topSymbols = Object.entries(analytics.signals_by_symbol ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const symMax = Math.max(1, ...topSymbols.map(([, v]) => v));

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      <Panel title="By strength tier">
        {STRENGTH_ORDER.map((tier) => (
          <Bar
            key={tier}
            label={tier.replace('_', ' ')}
            value={analytics.signals_by_strength?.[tier] ?? 0}
            max={strengthMax}
            color={STRENGTH_COLOR[tier]}
          />
        ))}
      </Panel>

      <Panel title="By direction">
        {(['buy', 'sell', 'hold'] as const).map((d) => (
          <Bar
            key={d}
            label={d}
            value={analytics.signals_by_direction?.[d] ?? 0}
            max={dirMax}
            color={DIR_COLOR[d]}
          />
        ))}
        {topSymbols.length > 0 && (
          <>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', margin: '12px 0 8px' }}>Top symbols</div>
            {topSymbols.map(([sym, count]) => (
              <Bar key={sym} label={sym} value={count} max={symMax} color="#3b82f6" />
            ))}
          </>
        )}
      </Panel>

      <Panel title="By hour (UTC)">
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 110 }}>
          {hours.map((v, h) => (
            <div
              key={h}
              title={`${String(h).padStart(2, '0')}:00 — ${v} signal${v !== 1 ? 's' : ''}`}
              style={{
                flex: 1,
                height: `${Math.max(2, (v / hourMax) * 100)}%`,
                background: v === hourMax && v > 0 ? '#3b82f6' : '#1e3a5f',
                borderRadius: '2px 2px 0 0',
                minWidth: 3,
              }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 9, color: '#334155' }}>
          <span>00</span><span>06</span><span>12</span><span>18</span><span>23</span>
        </div>
      </Panel>
    </div>
  );
};

export default SignalDistribution;
