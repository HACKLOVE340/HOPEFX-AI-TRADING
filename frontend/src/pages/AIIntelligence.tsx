/**
 * AIIntelligence — a single surface for the trading "brain": live ML safety
 * gates, signal-engine output with full context, and signal-quality analytics.
 *
 * Everything here is read-only and sourced from existing endpoints:
 *   - GET /api/ml/health        → MlSafetyStrip
 *   - GET /api/signals/active   → SignalIntelligenceCard list
 *   - GET /api/signals/analytics→ quality summary (hit rate, avg R:R, etc.)
 *
 * It surfaces intelligence the platform already computes (strength tiers,
 * model consensus, raw vs calibrated probability, regime/session, hit rates)
 * that the rest of the UI dropped on the floor.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { signalsApi } from '../hooks/useApi';
import { MlSafetyStrip } from '../components/intelligence/MlSafetyStrip';
import { RiskTransparencyStrip } from '../components/intelligence/RiskTransparencyStrip';
import { SignalIntelligenceCard } from '../components/intelligence/SignalIntelligenceCard';
import { SignalDistribution } from '../components/intelligence/SignalDistribution';
import { EmptyState } from '../components/EmptyState';
import { Spinner } from '../components/Spinner';
import { PanelSkeleton } from '../components/ui/Skeleton';
import type { EngineSignal, SignalAnalyticsReport } from '../types';

const Stat: React.FC<{ label: string; value: string; sub?: string; color?: string }> = ({ label, value, sub, color }) => (
  <div style={{
    background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10,
    padding: '12px 14px', flex: 1, minWidth: 130,
  }}>
    <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 800, color: color ?? '#f1f5f9', marginTop: 2 }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: '#475569', marginTop: 1 }}>{sub}</div>}
  </div>
);

const SectionTitle: React.FC<{ children: React.ReactNode; right?: React.ReactNode }> = ({ children, right }) => (
  <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
    <h2 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>{children}</h2>
    {right && <div style={{ marginLeft: 'auto' }}>{right}</div>}
  </div>
);

const AIIntelligence: React.FC = () => {
  const signalsQuery = useQuery({
    queryKey: ['signals', 'active'],
    queryFn: async () => {
      const d = (await signalsApi.active()).data as { signals?: EngineSignal[] } | EngineSignal[];
      return Array.isArray(d) ? d : (d.signals ?? []);
    },
    refetchInterval: 20_000,
  });

  const analyticsQuery = useQuery({
    queryKey: ['signals', 'analytics'],
    queryFn: async () => (await signalsApi.analytics()).data as SignalAnalyticsReport,
    refetchInterval: 60_000,
  });

  const signals = signalsQuery.data ?? [];
  const a = analyticsQuery.data;
  const totalOutcomes = a ? a.hit_rate.tp + a.hit_rate.sl + a.hit_rate.expired : 0;

  return (
    <div className="fade-in" style={{ padding: 20, maxWidth: 1100, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: '#f8fafc', margin: 0 }}>
          AI Intelligence
        </h1>
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 4, marginBottom: 0 }}>
          Live model health, signal-engine output, and signal-quality analytics — the reasoning behind every trade.
        </p>
      </div>

      {/* Risk state — what to check before acting on anything below */}
      <div style={{ marginBottom: 16 }}>
        <RiskTransparencyStrip />
      </div>

      {/* ML safety gates */}
      <div style={{ marginBottom: 22 }}>
        <MlSafetyStrip />
      </div>

      {/* Signal quality analytics */}
      <div style={{ marginBottom: 22 }}>
        <SectionTitle right={
          a && totalOutcomes === 0
            ? <span style={{ fontSize: 11, color: '#475569' }}>awaiting resolved outcomes</span>
            : undefined
        }>
          Signal Quality
        </SectionTitle>
        {analyticsQuery.isLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#475569', fontSize: 13 }}>
            <Spinner size="sm" /> Loading analytics…
          </div>
        ) : a ? (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Stat label="Signals generated" value={a.signals_generated.toLocaleString()} />
            <Stat
              label="TP hit rate"
              value={totalOutcomes ? `${(a.tp_rate * 100).toFixed(0)}%` : '—'}
              sub={totalOutcomes ? `${a.hit_rate.tp}/${totalOutcomes} resolved` : 'no outcomes yet'}
              color={a.tp_rate >= 0.5 ? '#22c55e' : '#fbbf24'}
            />
            <Stat
              label="SL hit rate"
              value={totalOutcomes ? `${(a.sl_rate * 100).toFixed(0)}%` : '—'}
              color={a.sl_rate > 0.5 ? '#f87171' : '#94a3b8'}
            />
            <Stat label="Avg confidence" value={`${(a.avg_confidence * 100).toFixed(0)}%`} />
            <Stat label="Avg R:R" value={a.avg_rr_ratio.toFixed(2)} color={a.avg_rr_ratio >= 1.5 ? '#22c55e' : '#fbbf24'} />
          </div>
        ) : (
          <div style={{ fontSize: 13, color: '#475569' }}>Analytics unavailable.</div>
        )}
      </div>

      {/* Signal distribution — where/when the engine finds edge */}
      {a && a.signals_generated > 0 && (
        <div style={{ marginBottom: 22 }}>
          <SectionTitle>Signal Distribution</SectionTitle>
          <SignalDistribution analytics={a} />
        </div>
      )}

      {/* Live engine signals */}
      <div>
        <SectionTitle right={
          <span style={{ fontSize: 11, color: '#475569' }}>
            {signals.length} active · refreshes every 20s
          </span>
        }>
          Live Engine Signals
        </SectionTitle>
        {signalsQuery.isLoading ? (
          <div style={{
            display: 'grid', gap: 12,
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          }}>
            {Array.from({ length: 3 }).map((_, i) => <PanelSkeleton key={i} rows={5} />)}
          </div>
        ) : signals.length === 0 ? (
          <EmptyState
            icon="📡"
            title="No active signals"
            description="The engine is monitoring the market — signals appear here as they fire."
            links={[
              { label: 'Generate AI signals', href: '/ai-strategy', icon: '✨' },
              { label: 'View signal feed', href: '/signals', icon: '📡' },
            ]}
          />
        ) : (
          <div className="stagger" style={{
            display: 'grid', gap: 12,
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          }}>
            {signals.map((sig) => (
              <SignalIntelligenceCard key={sig.id} signal={sig} />
            ))}
          </div>
        )}
      </div>

      <p style={{ fontSize: 11, color: '#334155', marginTop: 24, lineHeight: 1.6 }}>
        Signals are model output, not financial advice. Confidence and strength reflect the model's
        internal state and historical calibration; they do not guarantee outcomes.
      </p>
    </div>
  );
};

export default AIIntelligence;
