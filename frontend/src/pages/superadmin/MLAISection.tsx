// superadmin/MLAISection.tsx — ML model management, RL agent control, metrics
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, StatusBadge, ActionBtn, Select,
  ErrorState, LoadingRows, ConfirmDialog, KpiTile,
} from './ui';
import type { MLModel } from './types';
import { asArray, extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const AccuracyBar: React.FC<{ value: number }> = ({ value }) => {
  const color = value >= 70 ? '#4ade80' : value >= 55 ? '#fbbf24' : '#f87171';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${value}%`, background: color, borderRadius: 3, transition: 'width 0.5s' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 40 }}>{value.toFixed(1)}%</span>
    </div>
  );
};

const DriftBar: React.FC<{ value: number }> = ({ value }) => {
  const color = value < 0.1 ? '#4ade80' : value < 0.3 ? '#fbbf24' : '#f87171';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.min(value * 100, 100)}%`, background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 40 }}>{value.toFixed(3)}</span>
    </div>
  );
};

interface RLStatus {
  status: string;
  episode: number | null | undefined;
  total_reward: number | null | undefined;
  win_rate: number | null | undefined;
  last_updated: string | null | undefined;
  model_version: string | null | undefined;
}

interface MLStatus {
  status: string;
  active_model: string;
  inference_latency_ms: number;
  predictions_today: number;
  accuracy_7d: number;
  drift_score: number;
}

const MLAISection: React.FC = () => {
  const [models, setModels]       = useState<MLModel[]>([]);
  const [metrics, setMetrics]     = useState<Record<string, number>>({});
  const [rlStatus, setRlStatus]   = useState<RLStatus | null>(null);
  const [mlStatus, setMlStatus]   = useState<MLStatus | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [actionMsgOk, setActionMsgOk] = useState(true);
  const [busy, setBusy]           = useState<string | null>(null);
  const [confirm, setConfirm]     = useState<{ model: string; action: string } | null>(null);
  const [deployTarget, setDeployTarget] = useState<{ model: string; version: string } | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [mRes, meRes, rlRes, stRes] = await Promise.all([
        superadminApi.mlModels(),
        superadminApi.mlMetrics(),
        superadminApi.rlAgentStatus(),
        superadminApi.mlStatus(),
      ]);
      if (!mountedRef.current) return;
      setModels(asArray(mRes.data, 'models'));
      setMetrics(meRes.data);
      setRlStatus(rlRes.data);
      setMlStatus(stRes.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load ML data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 30 s — configuration and model data changes less frequently.
  usePolling(load, 30_000);

  const doAction = async (model: string, action: string, version?: string) => {
    setBusy(`${model}-${action}`); setActionMsg('');
    try {
      if (action === 'retrain')  await superadminApi.retrainModel(model);
      if (action === 'rollback') await superadminApi.rollbackModel(model);
      if (action === 'deploy' && version) await superadminApi.deployModel(model, version);
      setActionMsgOk(true);
      setActionMsg(`${action} triggered for ${model}`);
      setTimeout(load, 1500);
    } catch (e: unknown) {
      setActionMsgOk(false);
      setActionMsg(extractApiError(e, `${action} failed`));
    } finally { setBusy(null); setConfirm(null); setDeployTarget(null); }
  };

  const rlControl = async (action: string) => {
    setBusy(`rl-${action}`); setActionMsg('');
    try {
      await superadminApi.rlAgentControl(action);
      setActionMsgOk(true);
      setActionMsg(`RL agent ${action} triggered`);
      setTimeout(load, 1500);
    } catch (e: unknown) {
      setActionMsgOk(false);
      setActionMsg(extractApiError(e, 'RL control failed'));
    } finally { setBusy(null); }
  };

  if (loading) return <><LoadingRows rows={8} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>


      {confirm && (
        <ConfirmDialog
          title={`${confirm.action === 'retrain' ? 'Retrain' : 'Rollback'} ${confirm.model}`}
          message={confirm.action === 'retrain'
            ? `This will queue a full retrain job for ${confirm.model}. The model will be unavailable during training.`
            : `This will roll back ${confirm.model} to the previous stable version. Current predictions will be affected.`}
          confirmLabel={confirm.action === 'retrain' ? 'Start Retrain' : 'Rollback'}
          variant={confirm.action === 'rollback' ? 'danger' : 'warning'}
          onConfirm={() => doAction(confirm.model, confirm.action)}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* ── ML System Status banner ── */}
      {mlStatus && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20, padding: '14px 18px', background: mlStatus.status === 'healthy' ? '#052e16' : '#450a0a', borderRadius: 12, border: `1px solid ${mlStatus.status === 'healthy' ? '#16a34a44' : '#dc262644'}` }}>
          {[
            { label: 'ML System',        value: mlStatus.status.toUpperCase(),                   color: mlStatus.status === 'healthy' ? '#4ade80' : '#f87171', icon: '🧠' },
            { label: 'Active Model',     value: mlStatus.active_model,                           color: '#a78bfa', icon: '📦' },
            { label: 'Latency',          value: `${mlStatus.inference_latency_ms.toFixed(0)}ms`, color: mlStatus.inference_latency_ms < 50 ? '#4ade80' : '#fbbf24', icon: '⚡' },
            { label: 'Predictions Today', value: mlStatus.predictions_today.toLocaleString(),    color: '#60a5fa', icon: '📊' },
            { label: '7-Day Accuracy',   value: `${mlStatus.accuracy_7d.toFixed(1)}%`,           color: mlStatus.accuracy_7d >= 65 ? '#4ade80' : '#f87171', icon: '🎯' },
            { label: 'Drift Score',      value: mlStatus.drift_score.toFixed(3),                 color: mlStatus.drift_score < 0.1 ? '#4ade80' : mlStatus.drift_score < 0.3 ? '#fbbf24' : '#f87171', icon: '📈' },
          ].map(m => (
            <div key={m.label}>
              <div style={{ fontSize: 11, color: '#475569', marginBottom: 3 }}>{m.icon} {m.label}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: m.color }}>{m.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Metrics KPIs */}
      {Object.keys(metrics).length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12, marginBottom: 20 }}>
          {Object.entries(metrics).slice(0, 6).map(([k, v]) => (
            <KpiTile key={k} label={k.replace(/_/g, ' ')} value={typeof v === 'number' ? v.toFixed(2) : String(v)} accent="#8b5cf6" />
          ))}
        </div>
      )}

      {/* RL Agent */}
      {rlStatus && (
        <SectionCard title="RL Agent" icon="🤖" accent="#a78bfa"
          subtitle={`Model v${rlStatus.model_version ?? '1.0'} · Last updated ${fmtDate(rlStatus.last_updated ?? null)}`}
          actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
            {[
              { label: 'Status',       value: <StatusBadge status={rlStatus.status ?? 'unknown'} size="sm" /> },
              { label: 'Episode',      value: (rlStatus.episode ?? 0).toLocaleString() },
              { label: 'Total Reward', value: (rlStatus.total_reward ?? 0).toFixed(2) },
              { label: 'Win Rate',     value: `${((rlStatus.win_rate ?? 0) * 100).toFixed(1)}%` },
            ].map(m => (
              <div key={m.label} style={{ background: '#1e293b', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{m.value}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <ActionBtn label="Start Training" onClick={() => rlControl('start')}  variant="success"  icon="▶️" loading={busy === 'rl-start'} />
            <ActionBtn label="Pause"          onClick={() => rlControl('pause')}  variant="warning"  icon="⏸️" loading={busy === 'rl-pause'} />
            <ActionBtn label="Stop"           onClick={() => rlControl('stop')}   variant="danger"   icon="⏹️" loading={busy === 'rl-stop'} />
            <ActionBtn label="Reset"          onClick={() => rlControl('reset')}  variant="ghost"    icon="🔄" loading={busy === 'rl-reset'} />
          </div>
        </SectionCard>
      )}

      {/* Models table */}
      <SectionCard title="ML Models" icon="🧠" accent="#8b5cf6"
        subtitle={`${models.length} models registered`}
        actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['Model', 'Version', 'Status', 'Accuracy', 'Drift', 'Predictions Today', 'Last Trained', 'Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map(m => (
                <tr key={m.name} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '12px 12px', fontWeight: 600, color: '#f1f5f9' }}>{m.name}</td>
                  <td style={{ padding: '12px 12px', color: '#64748b', fontSize: 12 }}>v{m.version}</td>
                  <td style={{ padding: '12px 12px' }}><StatusBadge status={m.status} size="sm" /></td>
                  <td style={{ padding: '12px 12px', minWidth: 120 }}><AccuracyBar value={m.accuracy} /></td>
                  <td style={{ padding: '12px 12px', minWidth: 120 }}><DriftBar value={m.drift_score} /></td>
                  <td style={{ padding: '12px 12px', color: '#94a3b8' }}>{m.predictions_today.toLocaleString()}</td>
                  <td style={{ padding: '12px 12px', color: '#64748b', fontSize: 12, whiteSpace: 'nowrap' }}>{fmtDate(m.last_trained)}</td>
                  <td style={{ padding: '12px 12px' }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <ActionBtn
                        label="Retrain"
                        onClick={() => setConfirm({ model: m.name, action: 'retrain' })}
                        variant="warning" size="sm"
                        loading={busy === `${m.name}-retrain`}
                        disabled={m.status === 'training'}
                      />
                      <ActionBtn
                        label="Rollback"
                        onClick={() => setConfirm({ model: m.name, action: 'rollback' })}
                        variant="danger" size="sm"
                        loading={busy === `${m.name}-rollback`}
                        disabled={m.status === 'training'}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {models.length === 0 && (
            <div style={{ textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>No models registered.</div>
          )}
        </div>
      </SectionCard>

      <ActionBanner message={actionMsg} ok={actionMsgOk} />

      {/* ── Advanced ML Subsystems ── */}
      <MLSubsystemsPanel />
    </div>
  );
};

// ── Advanced ML Subsystems Panel ──────────────────────────────────────────────

const MLSubsystemsPanel: React.FC = () => {
  const [filterStats, setFilterStats]   = useState<Record<string, unknown> | null>(null);
  const [onlineStatus, setOnlineStatus] = useState<Record<string, unknown> | null>(null);
  const [driftStatus, setDriftStatus]   = useState<Record<string, unknown> | null>(null);
  const [sharpeStatus, setSharpeStatus] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading]           = useState(false);
  const [tab, setTab]                   = useState<'filter' | 'online' | 'drift' | 'features'>('filter');

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [f, o, d, s] = await Promise.allSettled([
        superadminApi.mlFilterStats(),
        superadminApi.mlOnlineLearnerStatus(),
        superadminApi.mlDriftStatus(),
        superadminApi.mlSharpeCircuitBreaker(),
      ]);
      if (!mountedRef.current) return;
      if (f.status === 'fulfilled') setFilterStats(f.value.data);
      if (o.status === 'fulfilled') setOnlineStatus(o.value.data);
      if (d.status === 'fulfilled') setDriftStatus(d.value.data);
      if (s.status === 'fulfilled') setSharpeStatus(s.value.data);
    } catch { /* non-fatal */ }
    finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const STABS = [
    { id: 'filter',   label: '🎯 Signal Filter' },
    { id: 'online',   label: '📡 Online Learner' },
    { id: 'drift',    label: '📉 Drift Monitor' },
    { id: 'features', label: '🔢 ML Metrics' },
  ] as const;

  return (
    <SectionCard title="Advanced ML Subsystems" icon="⚙️" accent="#a78bfa">
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {STABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
            fontWeight: tab === t.id ? 700 : 500,
            background: tab === t.id ? '#2e1065' : '#1e293b',
            color: tab === t.id ? '#c084fc' : '#94a3b8',
          }}>{t.label}</button>
        ))}
        <button onClick={load} disabled={loading} style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #334155', background: 'transparent', color: '#64748b', cursor: 'pointer', fontSize: 12 }}>
          {loading ? '…' : '↻'}
        </button>
      </div>

      {tab === 'filter' && filterStats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
          {Object.entries(filterStats as Record<string, unknown>).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
            <div key={key} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#c084fc' }}>{String(val)}</div>
            </div>
          ))}
        </div>
      )}
      {tab === 'filter' && !filterStats && (
        <div style={{ color: '#475569', fontSize: 13 }}>Signal filter stats not available. Ensure the ML engine is running.</div>
      )}

      {tab === 'online' && onlineStatus && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
          {Object.entries(onlineStatus as Record<string, unknown>).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
            <div key={key} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#60a5fa' }}>{String(val)}</div>
            </div>
          ))}
        </div>
      )}
      {tab === 'online' && !onlineStatus && (
        <div style={{ color: '#475569', fontSize: 13 }}>Online learner status not available. Enable FEATURE_ONLINE_LEARNING to activate.</div>
      )}

      {tab === 'drift' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
          {driftStatus && Object.entries(driftStatus).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
            <div key={key} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#fbbf24' }}>{String(val)}</div>
            </div>
          ))}
          {sharpeStatus && (
            <div style={{ gridColumn: '1 / -1', marginTop: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>Sharpe Circuit Breaker</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
                {Object.entries(sharpeStatus).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
                  <div key={key} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                    <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: (val as boolean) === true ? '#f87171' : '#4ade80' }}>{String(val)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {!driftStatus && !sharpeStatus && (
            <div style={{ color: '#475569', fontSize: 13, gridColumn: '1 / -1' }}>
              Drift monitor and Sharpe circuit breaker data not available. Ensure the ML engine is running.
            </div>
          )}
        </div>
      )}

      {tab === 'features' && (
        <div style={{ color: '#64748b', fontSize: 13 }}>
          <p>The HOPEFX ML pipeline uses <strong style={{ color: '#f1f5f9' }}>176 engineered features</strong> including:</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8, marginTop: 12 }}>
            {[
              'MTF Fusion (M1/M5/M15/H1/H4/D1)', 'Anomaly Weighting', 'Macro Calendar Features',
              'Sentiment Features (DL + rule)', 'Technical Indicators (50+)', 'Microstructure Features',
              'Regime Detection Features', 'Geopolitical Risk Score', 'Order Flow Imbalance',
              'GARCH Volatility Estimate', 'Correlation Features', 'COT Positioning',
            ].map(f => (
              <div key={f} style={{ padding: '8px 12px', borderRadius: 6, background: '#0f172a', border: '1px solid #1e293b', fontSize: 12, color: '#94a3b8' }}>
                ✓ {f}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, padding: '12px 14px', borderRadius: 8, background: '#0f172a', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>Model Ensemble Architecture</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {[
                { name: 'XGBoost', role: 'Primary signal classifier', weight: '40%' },
                { name: 'LightGBM', role: 'Secondary classifier', weight: '30%' },
                { name: 'Random Forest', role: 'Ensemble diversity', weight: '20%' },
                { name: 'LSTM Signal Layer', role: 'Temporal patterns', weight: '10%' },
                { name: 'Online SGD', role: 'Real-time adaptation', weight: 'blend' },
                { name: 'RL Agent (PPO/SAC)', role: 'Position sizing', weight: 'overlay' },
              ].map(m => (
                <div key={m.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 10px', borderRadius: 6, background: '#1e293b' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#f1f5f9' }}>{m.name}</span>
                  <span style={{ fontSize: 12, color: '#64748b' }}>{m.role}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#a78bfa' }}>{m.weight}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </SectionCard>
  );
};

export default MLAISection;
