/**
 * components/panels/MLModelPanel.tsx
 * ML model status panel: accuracy metrics, feature importance bar chart,
 * model list, and health status.
 *
 * Wires to:
 *   GET /api/ml/accuracy   — AccuracyResponse
 *   GET /api/ml/health     — MLHealthResponse
 *   GET /api/ml/models     — ModelInfo[]
 *   GET /api/ml/features   — { features: FeatureEntry[], note? } (admin only)
 */

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { mlApi, mlExtendedApi } from '../../hooks/useApi';
import { Panel } from '../ui/Panel';
import { PanelSkeleton } from '../ui/Skeleton';
import { withPanelGuard } from '../ui/withPanelGuard';
import { cn } from '../../lib/utils';

// ── Types (mirror backend Pydantic models) ────────────────────────────────────

interface AccuracyThresholds {
  accuracy_good: number;
  accuracy_warn: number;
  win_rate_good: number;
  sharpe_good:   number;
  sharpe_warn:   number;
  f1_good:       number;
}

// Default thresholds used when the API response does not include them
// (e.g. older backend versions).  These match the backend defaults.
const DEFAULT_THRESHOLDS: AccuracyThresholds = {
  accuracy_good: 0.60,
  accuracy_warn: 0.50,
  win_rate_good: 0.55,
  sharpe_good:   1.50,
  sharpe_warn:   0.50,
  f1_good:       0.60,
};

interface AccuracyResponse {
  model_id:      string;
  accuracy:      number;
  precision:     number;
  recall:        number;
  f1:            number;
  sharpe:        number;
  win_rate:      number;
  total_signals: number;
  evaluated_at:  string;
  note:          string;
  thresholds?:   AccuracyThresholds;
}

interface ModelInfo {
  model_id:   string;
  name:       string;
  available:  boolean;
  size_kb?:   number;
  trained_at?: string;
}

interface FeatureEntry {
  name:       string;
  importance: number;
}

interface MLHealthResponse {
  status:         string;
  model_loaded:   boolean;
  model_id:       string;
  feature_count:  number;
  oos_accuracy?:  number;
  last_trained_at?: string;
  predict_count:  number;
}

// ── Metric tile ───────────────────────────────────────────────────────────────

function MetricTile({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: string;
  color?: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2 bg-[#0d1421] rounded border border-[#1e2d3d]">
      <span className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</span>
      <span className={cn('text-[15px] font-bold tabular-nums', color ?? 'text-slate-200')}>
        {value}
      </span>
      {sub && <span className="text-[10px] text-slate-600">{sub}</span>}
    </div>
  );
}

// ── Feature importance bar ────────────────────────────────────────────────────

function FeatureBar({ name, importance, max }: { name: string; importance: number; max: number }) {
  const pct = max > 0 ? (importance / max) * 100 : 0;
  const color =
    pct > 66 ? '#00e676' :
    pct > 33 ? '#ffb800' : '#60a5fa';

  return (
    <div className="flex items-center gap-2 group">
      <span
        className="text-[10px] text-slate-400 truncate shrink-0"
        style={{ width: 140 }}
        title={name}
      >
        {name}
      </span>
      <div className="flex-1 h-1.5 bg-[#1e2d3d] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-slate-500 shrink-0 w-10 text-right">
        {(importance * 100).toFixed(1)}%
      </span>
    </div>
  );
}

// ── Health badge ──────────────────────────────────────────────────────────────

function HealthBadge({ status, loaded }: { status: string; loaded: boolean }) {
  const ok = loaded && (status === 'ok' || status === 'healthy');
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold',
      ok
        ? 'bg-[#00e676]/10 text-[#00e676]'
        : 'bg-[#ff1744]/10 text-[#ff1744]',
    )}>
      <span className={cn('w-1.5 h-1.5 rounded-full', ok ? 'bg-[#00e676]' : 'bg-[#ff1744]')} />
      {ok ? 'Live' : loaded ? status : 'No model'}
    </span>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

type Tab = 'metrics' | 'features' | 'models';

function TabBar({
  active, onChange, modelCount, featureCount,
}: {
  active: Tab;
  onChange: (t: Tab) => void;
  modelCount?: number;
  featureCount?: number;
}) {
  const tabs: { id: Tab; icon: string; label: string; badge?: number; color: string }[] = [
    { id: 'metrics',  icon: '📊', label: 'Metrics',  color: '#60a5fa' },
    { id: 'features', icon: '🧬', label: 'Features', badge: featureCount, color: '#a78bfa' },
    { id: 'models',   icon: '🤖', label: 'Models',   badge: modelCount,   color: '#34d399' },
  ];
  return (
    <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #1e2d3d', marginBottom: 2 }}>
      {tabs.map(({ id, icon, label, badge, color }) => {
        const isActive = active === id;
        return (
          <button
            key={id}
            onClick={() => onChange(id)}
            title={label}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
              padding: '6px 4px',
              background: isActive ? `${color}12` : 'transparent',
              border: 'none',
              borderBottom: isActive ? `2px solid ${color}` : '2px solid transparent',
              color: isActive ? color : '#475569',
              fontSize: 10, fontWeight: 700, cursor: 'pointer',
              transition: 'all 0.15s ease',
              letterSpacing: 0.5,
            }}
            onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8'; }}
            onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLButtonElement).style.color = '#475569'; }}
          >
            <span style={{ fontSize: 11 }}>{icon}</span>
            <span style={{ textTransform: 'uppercase' }}>{label}</span>
            {badge !== undefined && badge > 0 && (
              <span style={{
                fontSize: 9, fontWeight: 800,
                background: isActive ? `${color}25` : '#1e2d3d',
                color: isActive ? color : '#64748b',
                padding: '0px 4px', borderRadius: 8, lineHeight: '14px',
                minWidth: 16, textAlign: 'center',
              }}>
                {badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

function MLModelPanelInner() {
  const [tab, setTab] = useState<Tab>('metrics');

  // Accuracy metrics
  const accuracyQ = useQuery<AccuracyResponse>({
    queryKey: ['ml', 'accuracy'],
    queryFn:  async () => { const r = await mlApi.accuracy(); return r.data; },
    refetchInterval: 60_000,
    staleTime:       30_000,
  });

  // ML health
  const healthQ = useQuery<MLHealthResponse>({
    queryKey: ['ml', 'health'],
    queryFn:  async () => { const r = await mlExtendedApi.health(); return r.data; },
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  // Models list
  const modelsQ = useQuery<ModelInfo[]>({
    queryKey: ['ml', 'models'],
    queryFn:  async () => { const r = await mlApi.models(); return r.data; },
    refetchInterval: 120_000,
    staleTime:       60_000,
    enabled: tab === 'models',
  });

  // Feature importances (admin-only — gracefully handles 403)
  const featuresQ = useQuery<{ features: FeatureEntry[]; note?: string }>({
    queryKey: ['ml', 'features'],
    queryFn:  async () => {
      const r = await mlApi.features();
      // Backend returns { features: [...], note? } or flat array
      const raw = r.data as FeatureEntry[] | { features: FeatureEntry[]; note?: string };
      return Array.isArray(raw) ? { features: raw } : raw;
    },
    refetchInterval: 120_000,
    staleTime:       60_000,
    enabled: tab === 'features',
    retry: (count, err: unknown) => {
      // Don't retry 403 (non-admin user)
      const status = (err as { response?: { status?: number } })?.response?.status;
      return status !== 403 && count < 2;
    },
  });

  const acc    = accuracyQ.data;
  const health = healthQ.data;
  // Merge API-supplied thresholds with defaults so the UI colour-coding can be
  // tuned server-side (via env vars on the backend) without a frontend deploy.
  const t = { ...DEFAULT_THRESHOLDS, ...(acc?.thresholds ?? {}) };

  const headerRight = health ? (
    <HealthBadge status={health.status} loaded={health.model_loaded} />
  ) : undefined;

  const modelCount   = modelsQ.data?.length;
  const featureCount = featuresQ.data?.features.length;

  return (
    <Panel title="ML Model" headerRight={headerRight}>
      <div className="flex flex-col gap-3">
        <TabBar
          active={tab}
          onChange={setTab}
          modelCount={modelCount}
          featureCount={featureCount}
        />

        {/* ── Metrics tab ─────────────────────────────────────────────────── */}
        {tab === 'metrics' && (
          <>
            {accuracyQ.isLoading && <PanelSkeleton rows={4} />}
            {accuracyQ.isError && (
              <div className="text-[11px] text-[#ff1744] px-1">
                Failed to load accuracy metrics
              </div>
            )}
            {acc && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <MetricTile
                    label="Accuracy"
                    value={`${(acc.accuracy * 100).toFixed(1)}%`}
                    color={acc.accuracy >= t.accuracy_good ? 'text-[#00e676]' : acc.accuracy >= t.accuracy_warn ? 'text-[#ffb800]' : 'text-[#ff1744]'}
                  />
                  <MetricTile
                    label="Win Rate"
                    value={`${(acc.win_rate * 100).toFixed(1)}%`}
                    color={acc.win_rate >= t.win_rate_good ? 'text-[#00e676]' : 'text-[#ffb800]'}
                  />
                  <MetricTile
                    label="Sharpe"
                    value={acc.sharpe.toFixed(2)}
                    color={acc.sharpe >= t.sharpe_good ? 'text-[#00e676]' : acc.sharpe >= t.sharpe_warn ? 'text-[#ffb800]' : 'text-[#ff1744]'}
                  />
                  <MetricTile
                    label="F1 Score"
                    value={acc.f1.toFixed(3)}
                    color={acc.f1 >= t.f1_good ? 'text-[#00e676]' : 'text-[#ffb800]'}
                  />
                  <MetricTile
                    label="Precision"
                    value={`${(acc.precision * 100).toFixed(1)}%`}
                  />
                  <MetricTile
                    label="Recall"
                    value={`${(acc.recall * 100).toFixed(1)}%`}
                  />
                </div>

                <div className="flex flex-col gap-1 px-2.5 py-2 bg-[#0d1421] rounded border border-[#1e2d3d] text-[10px]">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Model ID</span>
                    <span className="text-slate-300 font-mono truncate max-w-[160px]">{acc.model_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Total signals</span>
                    <span className="text-slate-300 tabular-nums">{acc.total_signals.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Evaluated</span>
                    <span className="text-slate-400">
                      {acc.evaluated_at ? new Date(acc.evaluated_at).toLocaleDateString() : '—'}
                    </span>
                  </div>
                  {health && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Predict count</span>
                      <span className="text-slate-300 tabular-nums">{health.predict_count.toLocaleString()}</span>
                    </div>
                  )}
                </div>

                {acc.note && (
                  <div className="px-2.5 py-2 rounded bg-[#78350f]/20 border border-[#92400e]/30 text-[10px] text-[#fbbf24]">
                    {acc.note}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* ── Features tab ────────────────────────────────────────────────── */}
        {tab === 'features' && (
          <>
            {featuresQ.isLoading && <PanelSkeleton rows={8} />}
            {featuresQ.isError && (
              <div className="text-[11px] text-[#ff1744] px-1">
                {(featuresQ.error as { response?: { status?: number } })?.response?.status === 403
                  ? 'Feature importances require admin role'
                  : 'Failed to load feature importances'}
              </div>
            )}
            {featuresQ.data && (
              <>
                {featuresQ.data.note && (
                  <div className="px-2.5 py-1.5 rounded bg-[#1e2d3d] text-[10px] text-slate-500">
                    {featuresQ.data.note}
                  </div>
                )}
                {featuresQ.data.features.length === 0 ? (
                  <div className="text-[11px] text-slate-500 text-center py-6">
                    No feature importances available — run training first
                  </div>
                ) : (
                  <div className="flex flex-col gap-1.5 max-h-72 overflow-y-auto pr-1">
                    {(() => {
                      const sorted = [...featuresQ.data!.features]
                        .sort((a, b) => b.importance - a.importance)
                        .slice(0, 20);
                      const max = sorted[0]?.importance ?? 1;
                      return sorted.map((f) => (
                        <FeatureBar key={f.name} name={f.name} importance={f.importance} max={max} />
                      ));
                    })()}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* ── Models tab ──────────────────────────────────────────────────── */}
        {tab === 'models' && (
          <>
            {modelsQ.isLoading && <PanelSkeleton rows={3} />}
            {modelsQ.isError && (
              <div className="text-[11px] text-[#ff1744] px-1">Failed to load models</div>
            )}
            {modelsQ.data && modelsQ.data.length === 0 && (
              <div className="text-[11px] text-slate-500 text-center py-6">
                No trained models found
              </div>
            )}
            {modelsQ.data && modelsQ.data.length > 0 && (
              <div className="flex flex-col gap-1.5">
                {modelsQ.data.map((m) => (
                  <div
                    key={m.model_id}
                    className="flex items-center gap-3 px-3 py-2 rounded bg-[#0d1421] border border-[#1e2d3d]"
                  >
                    <span className={cn(
                      'w-2 h-2 rounded-full shrink-0',
                      m.available ? 'bg-[#00e676]' : 'bg-[#334155]',
                    )} />
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] font-semibold text-slate-200 truncate">{m.name}</div>
                      <div className="text-[10px] text-slate-500 font-mono truncate">{m.model_id}</div>
                    </div>
                    <div className="flex flex-col items-end gap-0.5 shrink-0">
                      {m.size_kb && (
                        <span className="text-[10px] text-slate-500">{m.size_kb.toFixed(0)} KB</span>
                      )}
                      {m.trained_at && (
                        <span className="text-[10px] text-slate-600">
                          {new Date(m.trained_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

// ── Exports ───────────────────────────────────────────────────────────────────

export { MLModelPanelInner as MLModelPanel };
export const MLModelPanelGuarded = withPanelGuard(MLModelPanelInner, 'ML Model', 6);
export default MLModelPanelInner;
