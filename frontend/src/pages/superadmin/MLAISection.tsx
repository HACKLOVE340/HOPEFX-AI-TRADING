// superadmin/MLAISection.tsx — ML model management, RL agent control, metrics
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, StatusBadge, ActionBtn, Select,
  ErrorState, LoadingRows, ConfirmDialog, SAStyles, KpiTile,
} from './ui';
import type { MLModel } from './types';

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
  episode: number;
  total_reward: number;
  win_rate: number;
  last_updated: string;
  model_version: string;
}

const MLAISection: React.FC = () => {
  const [models, setModels]     = useState<MLModel[]>([]);
  const [metrics, setMetrics]   = useState<Record<string, number>>({});
  const [rlStatus, setRlStatus] = useState<RLStatus | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [confirm, setConfirm]   = useState<{ model: string; action: string } | null>(null);
  const [deployTarget, setDeployTarget] = useState<{ model: string; version: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [mRes, meRes, rlRes] = await Promise.all([
        superadminApi.mlModels(),
        superadminApi.mlMetrics(),
        superadminApi.rlAgentStatus(),
      ]);
      setModels(mRes.data.models ?? mRes.data);
      setMetrics(meRes.data);
      setRlStatus(rlRes.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load ML data');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const doAction = async (model: string, action: string, version?: string) => {
    setBusy(`${model}-${action}`); setActionMsg('');
    try {
      if (action === 'retrain')  await superadminApi.retrainModel(model);
      if (action === 'rollback') await superadminApi.rollbackModel(model);
      if (action === 'deploy' && version) await superadminApi.deployModel(model, version);
      setActionMsg(`${action} triggered for ${model}`);
      setTimeout(load, 1500);
    } catch (e: unknown) {
      setActionMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? `${action} failed`);
    } finally { setBusy(null); setConfirm(null); setDeployTarget(null); }
  };

  const rlControl = async (action: string) => {
    setBusy(`rl-${action}`); setActionMsg('');
    try {
      await superadminApi.rlAgentControl(action);
      setActionMsg(`RL agent ${action} triggered`);
      setTimeout(load, 1500);
    } catch (e: unknown) {
      setActionMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'RL control failed');
    } finally { setBusy(null); }
  };

  if (loading) return <><SAStyles /><LoadingRows rows={8} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />

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
          subtitle={`Model v${rlStatus.model_version} · Last updated ${fmtDate(rlStatus.last_updated)}`}
          actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
            {[
              { label: 'Status',       value: <StatusBadge status={rlStatus.status} size="sm" /> },
              { label: 'Episode',      value: rlStatus.episode.toLocaleString() },
              { label: 'Total Reward', value: rlStatus.total_reward.toFixed(2) },
              { label: 'Win Rate',     value: `${(rlStatus.win_rate * 100).toFixed(1)}%` },
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

      {actionMsg && (
        <div style={{
          padding: '12px 16px', borderRadius: 8, marginTop: 4,
          background: actionMsg.includes('failed') ? '#450a0a' : '#052e16',
          color: actionMsg.includes('failed') ? '#f87171' : '#4ade80',
          fontSize: 13, fontWeight: 600,
        }}>
          {actionMsg}
        </div>
      )}
    </div>
  );
};

export default MLAISection;
