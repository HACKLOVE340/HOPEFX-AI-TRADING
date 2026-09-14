// superadmin/MLAISection.tsx — ML model management, RL agent control, metrics
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, StatusBadge, ActionBtn, Input,
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
      <div style={{ flex: 1, height: 6, background: 'var(--raised)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${value}%`, background: color, borderRadius: 3, transition: 'width 0.5s' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 40 }}>{value.toFixed(1)}%</span>
    </div>
  );
};

/** Drift, or the honest absence of it.
 *
 *  `value` was `number` and this rendered `value.toFixed(3)` directly. The API
 *  sent 0.0 whenever it could not read the drift monitor, so an unreachable
 *  monitor painted a green 0.000 next to a healthy model. The API now sends
 *  null with a state, and this renders that state rather than inventing a bar.
 */
const DriftBar: React.FC<{ value: number | null; state?: string }> = ({ value, state }) => {
  if (value === null || value === undefined) {
    const label = state === 'not_serving' ? 'not serving' : 'not measured';
    const title = state === 'not_serving'
      ? 'This version is not serving inference, so no drift is measured for it.'
      : 'The drift monitor could not be read — this is not a reading of zero drift.';
    return (
      <span title={title} style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', fontStyle: 'italic' }}>
        — {label}
      </span>
    );
  }
  const color = value < 0.1 ? '#4ade80' : value < 0.3 ? '#fbbf24' : '#f87171';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--raised)', borderRadius: 3, overflow: 'hidden' }}>
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
  /** The active model's training-time out-of-sample accuracy, despite the
   *  name — nothing computes a 7-day rolling figure yet. Labelled "OOS
   *  ACCURACY" below so the display does not repeat the field name's claim. */
  accuracy_7d: number;
  drift_score: number | null;
  drift_state?: 'measured' | 'unmeasured' | 'not_serving';
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

      {deployTarget && (
        <ConfirmDialog
          title={`Deploy ${deployTarget.model}`}
          message="The named version starts serving inference immediately. Predictions in flight are unaffected; everything after the switch comes from this version."
          confirmLabel={busy === `${deployTarget.model}-deploy` ? 'Deploying…' : 'Deploy'}
          variant="warning"
          onConfirm={() => doAction(deployTarget.model, 'deploy', deployTarget.version.trim())}
          onCancel={() => setDeployTarget(null)}
        >
          <label style={{ display: 'block', fontSize: 12, color: 'var(--text-dim)' }}>
            Version to serve
            <Input
              aria-label={`Version of ${deployTarget.model} to deploy`}
              value={deployTarget.version}
              onChange={e => setDeployTarget(t => (t ? { ...t, version: e.target.value } : t))}
              style={{ marginTop: 6 }}
            />
          </label>
        </ConfirmDialog>
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
            // Never renders a number the backend did not measure: an
            // unreachable drift monitor reads "not measured", in grey, not a
            // green 0.000.
            { label: 'Drift Score',      value: mlStatus.drift_score === null || mlStatus.drift_score === undefined ? 'not measured' : mlStatus.drift_score.toFixed(3), color: mlStatus.drift_score === null || mlStatus.drift_score === undefined ? '#64748b' : mlStatus.drift_score < 0.1 ? '#4ade80' : mlStatus.drift_score < 0.3 ? '#fbbf24' : '#f87171', icon: '📈' },
          ].map(m => (
            <div key={m.label}>
              <div style={{ fontSize: 11, color: 'var(--text-faint)', marginBottom: 3 }}>{m.icon} {m.label}</div>
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
              <div key={m.label} style={{ background: 'var(--raised)', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontSize: 10, color: 'var(--text-faint)', marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-strong)' }}>{m.value}</div>
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
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Model', 'Version', 'Status', 'Accuracy', 'Drift', 'Predictions Today', 'Last Trained', 'Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map(m => (
                <tr key={m.name} className="sa-row" style={{ borderBottom: '1px solid var(--hairline)' }}>
                  <td style={{ padding: '12px 12px', fontWeight: 600, color: 'var(--text-strong)' }}>{m.name}</td>
                  <td style={{ padding: '12px 12px', color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap' }}>
                    v{m.version}
                    {/* sha256[:8] identifies the artifact, not the row. Four
                        entries here share one file, so without this the table
                        shows the same version against four different names. */}
                    {m.shares_artifact_with && m.shares_artifact_with.length > 0 && (
                      <span
                        title={`Same artifact as: ${m.shares_artifact_with.join(', ')}`}
                        style={{ marginLeft: 6, color: 'var(--warn)', fontWeight: 700 }}
                      >
                        ×{m.shares_artifact_with.length + 1}
                      </span>
                    )}
                    {m.metrics_conflict && (
                      <span
                        title="Entries over these identical bytes report different measured metrics — at least one is wrong"
                        style={{ marginLeft: 6, color: 'var(--loss)', fontWeight: 700 }}
                      >
                        ⚠ conflict
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '12px 12px' }}><StatusBadge status={m.status} size="sm" /></td>
                  <td style={{ padding: '12px 12px', minWidth: 120 }}><AccuracyBar value={m.accuracy} /></td>
                  <td style={{ padding: '12px 12px', minWidth: 120 }}><DriftBar value={m.drift_score} state={m.drift_state} /></td>
                  <td style={{ padding: '12px 12px', color: 'var(--text-dim)' }}>{m.predictions_today.toLocaleString()}</td>
                  <td style={{ padding: '12px 12px', color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap' }}>{fmtDate(m.last_trained)}</td>
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
                      {/* `doAction` has handled 'deploy' with a version since
                          it was written, `deployModel` is in the API, and
                          `deployTarget` existed to carry the choice — there was
                          simply no control, so promoting a specific version was
                          unreachable from the product. */}
                      <ActionBtn
                        label="Deploy version"
                        onClick={() => setDeployTarget({ model: m.name, version: String(m.version ?? '') })}
                        variant="primary" size="sm"
                        loading={busy === `${m.name}-deploy`}
                        disabled={m.status === 'training'}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {models.length === 0 && (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-faint)', fontSize: 13 }}>No models registered.</div>
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
  const [loadErr, setLoadErr]           = useState('');
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
      // Each subsystem is reported independently: a blank drift tab must not be
      // mistaken for "no drift detected".
      const failed: string[] = [];
      if (f.status === 'fulfilled') setFilterStats(f.value.data); else failed.push('signal filter');
      if (o.status === 'fulfilled') setOnlineStatus(o.value.data); else failed.push('online learner');
      if (d.status === 'fulfilled') setDriftStatus(d.value.data); else failed.push('drift monitor');
      if (s.status === 'fulfilled') setSharpeStatus(s.value.data); else failed.push('Sharpe circuit breaker');
      setLoadErr(failed.length ? `Status unavailable for: ${failed.join(', ')}. Figures below may be stale or missing.` : '');
    } finally { if (mountedRef.current) setLoading(false); }
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
            background: tab === t.id ? '#2e1065' : 'var(--raised)',
            color: tab === t.id ? '#c084fc' : 'var(--text-dim)',
          }}>{t.label}</button>
        ))}
        <button onClick={load} disabled={loading} style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border-strong)', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12 }}>
          {loading ? '…' : '↻'}
        </button>
      </div>

      {loadErr && <ActionBanner message={loadErr} ok={false} onDismiss={() => setLoadErr('')} />}

      {tab === 'filter' && filterStats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
          {Object.entries(filterStats as Record<string, unknown>).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
            <div key={key} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#c084fc' }}>{String(val)}</div>
            </div>
          ))}
        </div>
      )}
      {tab === 'filter' && !filterStats && (
        <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>Signal filter stats not available. Ensure the ML engine is running.</div>
      )}

      {tab === 'online' && onlineStatus && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
          {Object.entries(onlineStatus as Record<string, unknown>).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
            <div key={key} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--link)' }}>{String(val)}</div>
            </div>
          ))}
        </div>
      )}
      {tab === 'online' && !onlineStatus && (
        <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>Online learner status not available. Enable FEATURE_ONLINE_LEARNING to activate.</div>
      )}

      {tab === 'drift' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
          {driftStatus && Object.entries(driftStatus).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
            <div key={key} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--warn)' }}>{String(val)}</div>
            </div>
          ))}
          {sharpeStatus && (
            <div style={{ gridColumn: '1 / -1', marginTop: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-strong)', marginBottom: 8 }}>Sharpe Circuit Breaker</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
                {Object.entries(sharpeStatus).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
                  <div key={key} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: (val as boolean) === true ? 'var(--loss)' : 'var(--gain)' }}>{String(val)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {!driftStatus && !sharpeStatus && (
            <div style={{ color: 'var(--text-faint)', fontSize: 13, gridColumn: '1 / -1' }}>
              Drift monitor and Sharpe circuit breaker data not available. Ensure the ML engine is running.
            </div>
          )}
        </div>
      )}

      {tab === 'features' && (
        <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          <p>The HOPEFX ML pipeline uses <strong style={{ color: 'var(--text-strong)' }}>176 engineered features</strong> including:</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8, marginTop: 12 }}>
            {[
              'MTF Fusion (M1/M5/M15/H1/H4/D1)', 'Anomaly Weighting', 'Macro Calendar Features',
              'Sentiment Features (DL + rule)', 'Technical Indicators (50+)', 'Microstructure Features',
              'Regime Detection Features', 'Geopolitical Risk Score', 'Order Flow Imbalance',
              'GARCH Volatility Estimate', 'Correlation Features', 'COT Positioning',
            ].map(f => (
              <div key={f} style={{ padding: '8px 12px', borderRadius: 6, background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12, color: 'var(--text-dim)' }}>
                ✓ {f}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, padding: '12px 14px', borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-strong)', marginBottom: 8 }}>Model Ensemble Architecture</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {[
                { name: 'XGBoost', role: 'Primary signal classifier', weight: '40%' },
                { name: 'LightGBM', role: 'Secondary classifier', weight: '30%' },
                { name: 'Random Forest', role: 'Ensemble diversity', weight: '20%' },
                { name: 'LSTM Signal Layer', role: 'Temporal patterns', weight: '10%' },
                { name: 'Online SGD', role: 'Real-time adaptation', weight: 'blend' },
                { name: 'RL Agent (PPO/SAC)', role: 'Position sizing', weight: 'overlay' },
              ].map(m => (
                <div key={m.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 10px', borderRadius: 6, background: 'var(--raised)' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-strong)' }}>{m.name}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{m.role}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--ai-model)' }}>{m.weight}</span>
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
