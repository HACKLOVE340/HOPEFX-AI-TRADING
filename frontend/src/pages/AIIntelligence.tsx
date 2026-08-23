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

/** GET /api/ml/engine-health — what the live inference engine reports. */
interface EngineHealth {
  status?: string;
  model_version?: string;
  feature_count?: number;
  oos_accuracy?: number;
  last_trained_at?: string;
}

/** GET /api/ml/feature-importance/{model}. `method` is load-bearing: when it
 *  reads "uniform" the server measured nothing and returned 1/n per feature
 *  (ml/explainability.py:270). See audit F232. */
interface FeatureImportance {
  model: string;
  method: string;
  features: { feature: string; importance: number }[];
}

/** GET /api/ml/drift-report — explains itself when it lacks samples. */
interface DriftReport {
  overall_status?: string;
  message?: string;
  requires_retrain?: boolean;
  live_samples?: number;
}
import { PageHeader, Section, RelatedPages } from '../components';
import {
  Sparkles, Brain, AlertTriangle, Activity, LineChart, BookOpen, Radar, Cpu,
} from 'lucide-react';
import { signalsApi, mlApi } from '../hooks/useApi';
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
  // Live model state. Each query is independent so one failing endpoint
  // cannot blank the section.
  const healthQuery = useQuery({
    queryKey: ['ml', 'engine-health'],
    queryFn:  async () => (await mlApi.engineHealth()).data as { engine?: EngineHealth },
    staleTime: 30_000,
    retry: 1,
  });
  const engine = healthQuery.data?.engine ?? null;

  const impQuery = useQuery({
    queryKey: ['ml', 'feature-importance', engine?.model_version],
    queryFn:  async () => (await mlApi.featureImportance('rf_xauusd')).data as FeatureImportance,
    staleTime: 60_000,
    retry: 1,
  });
  const imp = impQuery.data ?? null;
  // The `method` label is NOT sufficient on its own. /ml/feature-importance
  // reports method "feature_importances" for rf_xauusd while returning 30
  // identical values of 0.02 — a flat distribution carries no information
  // whatever it is called. Judge the numbers, not the label. See audit F232.
  const impIsDegenerate =
    !imp?.features?.length ||
    imp.method === 'uniform' ||
    new Set(imp.features.map((f) => f.importance)).size <= 1;

  const driftQuery = useQuery({
    queryKey: ['ml', 'drift-report'],
    queryFn:  async () => (await mlApi.driftReport()).data as DriftReport,
    staleTime: 30_000,
    retry: 1,
  });
  const drift = driftQuery.data ?? null;

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
      <PageHeader
        title="AI intelligence"
        icon={Sparkles}
        subtitle="What the live model is, how it was validated, what it says about its own inputs, and how its signals have actually resolved."
      />

      {/* Risk state — what to check before acting on anything below */}
      <div style={{ marginBottom: 16 }}>
        <RiskTransparencyStrip />
      </div>

      {/* ML safety gates */}
      <div style={{ marginBottom: 22 }}>
        <MlSafetyStrip />
      </div>

      {/* ── Model transparency ──────────────────────────────────────────
           /ml/engine-health, /ml/models, /ml/feature-importance and
           /ml/drift-report are all served by the backend and had no caller
           anywhere in the SPA (audit F185/F232). ── */}
      <div style={{ marginBottom: 22 }}>
        <Section
          title="Model transparency"
          description="What the live model is, how it was validated, and what it says about its own inputs."
        >
          {healthQuery.isLoading ? (
            <EmptyState compact title="Loading model health…" />
          ) : engine ? (
            <>
              <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
                {[
                  { k: 'Model version',   v: engine.model_version ?? '—' },
                  { k: 'Features',        v: engine.feature_count != null ? String(engine.feature_count) : '—' },
                  { k: 'OOS accuracy',    v: engine.oos_accuracy != null ? `${(engine.oos_accuracy * 100).toFixed(2)}%` : '—' },
                  { k: 'Last trained',    v: engine.last_trained_at ? new Date(engine.last_trained_at).toLocaleDateString() : '—' },
                ].map(({ k, v }) => (
                  <div key={k} style={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 10, padding: '10px 12px' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#475569' }}>{k}</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0', fontFamily: 'ui-monospace, monospace', marginTop: 3 }}>{v}</div>
                  </div>
                ))}
              </div>

              {/* Feature attribution. The endpoint reports HOW it derived the
                  numbers; when that is "uniform" it measured nothing, and
                  drawing the bars anyway would present a flat placeholder as
                  insight (F232). Say so instead. */}
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#475569', marginBottom: 8 }}>
                  Feature attribution
                </div>
                {impQuery.isLoading ? (
                  <EmptyState compact title="Loading feature attribution…" />
                ) : impIsDegenerate ? (
                  <EmptyState
                    compact
                    icon={AlertTriangle}
                    title="This model cannot explain itself yet"
                    description="Every feature came back with the same weight, so nothing here distinguishes one input from another. Charting it would present a flat placeholder as insight, so it is not charted."
                    serverNote={
                      imp
                        ? `Server reported method "${imp.method}" for model ${imp.model}, but returned ${imp.features?.length ?? 0} features with ${new Set((imp.features ?? []).map((f) => f.importance)).size} distinct value(s).`
                        : null
                    }
                  />
                ) : imp && imp.features?.length ? (
                  <>
                    <p style={{ fontSize: 11.5, color: '#64748b', margin: '0 0 8px' }}>
                      Derived by <strong style={{ color: '#94a3b8' }}>{imp.method}</strong> for model{' '}
                      <strong style={{ color: '#94a3b8' }}>{imp.model}</strong>.
                    </p>
                    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 5 }}>
                      {imp.features.slice(0, 12).map((f) => {
                        const max = imp.features[0]?.importance || 1;
                        return (
                          <li key={f.feature} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{ width: 130, flexShrink: 0, fontSize: 11.5, color: '#94a3b8', fontFamily: 'ui-monospace, monospace', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {f.feature}
                            </span>
                            <span style={{ flex: 1, height: 6, background: '#1e2d3d', borderRadius: 3, overflow: 'hidden' }}>
                              <span style={{ display: 'block', height: '100%', width: `${(f.importance / max) * 100}%`, background: '#00d4ff' }} />
                            </span>
                            <span style={{ width: 52, textAlign: 'right', fontSize: 11, color: '#64748b', fontFamily: 'ui-monospace, monospace' }}>
                              {f.importance.toFixed(4)}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </>
                ) : (
                  <EmptyState compact icon={Brain} title="No attribution available for this model" />
                )}
              </div>

              {/* Drift — the endpoint explains itself when it has no data. */}
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#475569', marginBottom: 8 }}>
                  Feature drift
                </div>
                {drift?.overall_status && drift.overall_status !== 'unknown' ? (
                  <p style={{ fontSize: 12.5, color: '#94a3b8', margin: 0 }}>
                    Status: <strong>{drift.overall_status}</strong>
                    {drift.requires_retrain ? ' — retrain recommended' : ''}
                  </p>
                ) : (
                  <EmptyState
                    compact
                    icon={Activity}
                    title="Drift cannot be assessed yet"
                    serverNote={drift?.message ?? null}
                  />
                )}
              </div>
            </>
          ) : (
            <EmptyState
              compact
              icon={Brain}
              title="Model health unavailable"
              description="The inference engine did not report its status."
            />
          )}
        </Section>
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
            <Stat label="Signals generated" value={Number.isFinite(a.signals_generated) ? a.signals_generated.toLocaleString() : '—'} />
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
            <Stat label="Avg confidence" value={Number.isFinite(a.avg_confidence) ? `${(a.avg_confidence * 100).toFixed(0)}%` : '—'} />
            <Stat label="Avg R:R" value={Number.isFinite(a.avg_rr_ratio) ? a.avg_rr_ratio.toFixed(2) : '—'} color={a.avg_rr_ratio >= 1.5 ? '#22c55e' : '#fbbf24'} />
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
      <RelatedPages
        links={[
          { to: '/signals',      label: 'Signal feed',     hint: 'Every signal as it is published',   icon: Radar },
          { to: '/ai-strategy',  label: 'AI strategy',     hint: 'Generate and test a strategy',      icon: Cpu },
          { to: '/performance',  label: 'Performance',     hint: 'What the signals produced',         icon: LineChart },
          { to: '/journal',      label: 'Trade journal',   hint: 'Your outcome on each one',          icon: BookOpen },
          { to: '/observability', label: 'Engine monitor', hint: 'Live orchestrator and model panels', icon: Activity },
        ]}
      />
    </div>
  );
};

export default AIIntelligence;
