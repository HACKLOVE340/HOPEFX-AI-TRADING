/**
 * MlSafetyStrip — surfaces the ML inference engine's health and safety gates
 * from GET /api/ml/health (api/ml.py MLHealthResponse).
 *
 * These fields already gate live trading server-side (stale model, feature
 * drift, fallback path) but were never shown to the user. This is a read-only
 * surface — it never changes any gate, it only makes the gate state visible.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { mlApi } from '../../hooks/useApi';
import type { MlHealth } from '../../types';
import { Brain } from 'lucide-react';

// ── Small status pill ─────────────────────────────────────────────────────────
const Pill: React.FC<{
  label: string;
  value: string;
  tone: 'ok' | 'warn' | 'bad' | 'muted';
  title?: string;
}> = ({ label, value, tone, title }) => {
  const colors = {
    ok:    { fg: '#22c55e', bg: 'rgba(34,197,94,0.10)',  bd: 'rgba(34,197,94,0.30)'  },
    warn:  { fg: '#fbbf24', bg: 'rgba(251,191,36,0.10)', bd: 'rgba(251,191,36,0.30)' },
    bad:   { fg: '#f87171', bg: 'rgba(248,113,113,0.10)',bd: 'rgba(248,113,113,0.30)'},
    muted: { fg: '#94a3b8', bg: 'rgba(148,163,184,0.08)',bd: '#1e293b'               },
  }[tone];
  return (
    <div title={title} style={{
      display: 'flex', flexDirection: 'column', gap: 2,
      padding: '8px 12px', borderRadius: 8,
      background: colors.bg, border: `1px solid ${colors.bd}`,
      minWidth: 110,
    }}>
      <span style={{ fontSize: 'var(--fs-micro)', fontWeight: 700, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </span>
      <span style={{ fontSize: 14, fontWeight: 700, color: colors.fg }}>{value}</span>
    </div>
  );
};

const pct = (v: number | null | undefined) =>
  (v == null || !Number.isFinite(v)) ? '—' : `${(v * 100).toFixed(0)}%`;

export const MlSafetyStrip: React.FC = () => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['ml', 'health'],
    queryFn: async () => (await mlApi.health()).data as MlHealth,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  if (isLoading) {
    return (
      <div style={{ padding: '14px 16px', fontSize: 'var(--fs-body)', color: 'var(--text-faint)' }}>
        Loading model health…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div style={{
        padding: '12px 16px', fontSize: 'var(--fs-body)', color: 'var(--text-dim)',
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10,
      }}>
        Model health unavailable.
      </div>
    );
  }

  const statusTone = data.status === 'ok' ? 'ok' : data.status === 'degraded' ? 'warn' : 'bad';

  // Derived safety signals from the raw health payload.
  const fallbackTone   = data.fallback_rate > 0.5 ? 'bad' : data.fallback_rate > 0.15 ? 'warn' : 'ok';
  const directionalTone = data.non_neutral_rate < 0.2 ? 'warn' : 'ok';
  const calibTone      = data.calibrator_available ? 'ok' : 'warn';
  const latencyTone    = data.last_latency_ms > 1500 ? 'warn' : 'ok';

  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12,
      padding: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-strong)' }}><Brain size={14} aria-hidden style={{ verticalAlign: '-2px', marginRight: 6 }} />Model Health &amp; Safety Gates</span>
        <span style={{
          fontSize: 'var(--fs-micro)', fontWeight: 800, padding: '2px 8px', borderRadius: 5,
          textTransform: 'uppercase', letterSpacing: '0.06em',
          color: statusTone === 'ok' ? '#22c55e' : statusTone === 'warn' ? 'var(--warn)' : 'var(--loss)',
          background: statusTone === 'ok' ? 'rgba(34,197,94,0.12)' : statusTone === 'warn' ? 'rgba(251,191,36,0.12)' : 'rgba(248,113,113,0.12)',
          border: `1px solid ${statusTone === 'ok' ? 'rgba(34,197,94,0.3)' : statusTone === 'warn' ? 'rgba(251,191,36,0.3)' : 'rgba(248,113,113,0.3)'}`,
        }}>
          {data.status}
        </span>
        {data.model_id && (
          <span style={{ fontSize: 'var(--fs-label)', color: 'var(--text-faint)', fontFamily: 'monospace' }}>
            {data.model_id}
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 'var(--fs-label)', color: 'var(--text-faint)' }}>
          {data.predict_count.toLocaleString()} inferences
        </span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <Pill
          label="Model loaded" value={data.model_loaded ? 'Yes' : 'No'}
          tone={data.model_loaded ? 'ok' : 'bad'}
          title="Whether a trained model artifact is loaded (vs. deterministic fallback)."
        />
        <Pill
          label="OOS accuracy" value={pct(data.oos_accuracy)}
          tone={data.oos_accuracy == null ? 'muted' : data.oos_accuracy >= 0.52 ? 'ok' : 'warn'}
          title="Out-of-sample accuracy recorded at training time."
        />
        <Pill
          label="Fallback rate" value={pct(data.fallback_rate)}
          tone={fallbackTone}
          title="Share of recent inferences that used the deterministic fallback path instead of the model. High = model frequently unavailable."
        />
        <Pill
          label="Directional" value={pct(data.non_neutral_rate)}
          tone={directionalTone}
          title="Share of recent signals that were directional (not neutral). Very low means the model is mostly abstaining."
        />
        <Pill
          label="Calibrator" value={data.calibrator_available ? 'On' : 'Off'}
          tone={calibTone}
          title="Whether the isotonic probability calibrator is active. Off = confidence values are raw model output."
        />
        <Pill
          label="Latency" value={`${data.last_latency_ms.toFixed(0)} ms`}
          tone={latencyTone}
          title="Wall-clock latency of the most recent inference."
        />
        <Pill
          label="Online learn" value={data.online_learning_enabled ? 'On' : 'Off'}
          tone="muted"
          title="Whether the online learner is blended into predictions."
        />
        <Pill
          label="MTF fusion" value={data.mtf_fusion_enabled ? 'On' : 'Off'}
          tone="muted"
          title="Whether multi-timeframe feature fusion is active."
        />
      </div>

      <div style={{ marginTop: 10, fontSize: 'var(--fs-label)', color: 'var(--text-faint)', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <span>Long threshold: <strong style={{ color: 'var(--text-muted)' }}>{data.threshold_long.toFixed(3)}</strong></span>
        <span>Short threshold: <strong style={{ color: 'var(--text-muted)' }}>{data.threshold_short.toFixed(3)}</strong></span>
        {/* The date the freshness gate ACTED on, preferred over the meta file's.
            They disagree: `model_provenance_at` is the sha256-bound timestamp in
            registry.json (2026-04-01 for the committed artifact), while
            `last_trained_at` comes from advanced_oos_meta.json (2026-06-26) —
            the same bytes, nearly three months apart. Showing the meta date beside
            a stale badge that means 167 days was a contradiction on screen
            whichever record is right. Which one IS right is an ML decision, open
            as MODEL-PROVENANCE-DISAGREES; until then this shows the date the
            platform blocked on, and falls back to the meta file when the gate
            reports no provenance. */}
        {(data.model_provenance_at ?? data.last_trained_at) && (
          <span title={
            data.model_provenance_at
              ? 'The training date the freshness gate measured, from the model registry.'
              : 'From the model metadata file; the freshness gate could not read provenance.'
          }>
            Trained: <strong style={{ color: 'var(--text-muted)' }}>
              {new Date((data.model_provenance_at ?? data.last_trained_at) as string).toLocaleDateString()}
            </strong>
          </span>
        )}
        <span style={{ marginLeft: 'auto' }}>
          Updated {new Date(data.checked_at).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
};

export default MlSafetyStrip;
