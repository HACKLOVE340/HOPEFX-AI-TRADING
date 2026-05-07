// superadmin/SystemHealthSection.tsx
// Service health, backups, scheduled jobs, API key audit
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import { EmptyState } from '../../components/EmptyState';
import {
  SectionCard, StatusBadge, ActionBtn, KpiTile,
  ErrorState, LoadingRows, ConfirmDialog,
} from './ui';
import type { ServiceStatus, BackupRecord, ScheduledJob } from './types';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const fmtDuration = (ms: number) =>
  ms < 1000 ? `${ms}ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)}s` : `${(ms / 60000).toFixed(1)}m`;

const SERVICE_ICONS: Record<string, string> = {
  database:   '🗄️',
  redis:      '⚡',
  broker:     '📈',
  ml_engine:  '🧠',
  websocket:  '🔌',
  celery:     '⚙️',
};

interface ApiKey {
  key_id: string;
  user_id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used: string | null;
  active: boolean;
}

const SystemHealthSection: React.FC = () => {
  const [services, setServices]   = useState<ServiceStatus[]>([]);
  const [backups, setBackups]     = useState<BackupRecord[]>([]);
  const [jobs, setJobs]           = useState<ScheduledJob[]>([]);
  const [apiKeys, setApiKeys]     = useState<ApiKey[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [busy, setBusy]           = useState<string | null>(null);
  const [msg, setMsg]             = useState('');
  const [tab, setTab]             = useState<'services' | 'backups' | 'jobs' | 'apikeys'>('services');
  const [backupType, setBackupType] = useState<'full' | 'incremental' | 'snapshot'>('incremental');
  const [revokeConfirm, setRevokeConfirm] = useState<string | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [sRes, bRes, jRes, kRes] = await Promise.all([
        superadminApi.serviceStatuses(),
        superadminApi.infraBackups(),
        superadminApi.infraScheduledJobs(),
        superadminApi.infraApiKeys(),
      ]);
      if (!mountedRef.current) return;
      setServices(sRes.data.services ?? sRes.data);
      setBackups(bRes.data.backups ?? bRes.data);
      setJobs(jRes.data.jobs ?? jRes.data);
      setApiKeys(kRes.data.api_keys ?? kRes.data.keys ?? kRes.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load system health data');
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 15 s while the tab is active — live operational data.
  usePolling(load, 15_000);

  const triggerBackup = async () => {
    setBusy('backup'); setMsg('');
    try {
      await superadminApi.infraTriggerBackup(backupType);
      setMsg(`${backupType} backup triggered`);
      setTimeout(load, 1500);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Backup trigger failed');
    } finally { setBusy(null); }
  };

  const jobAction = async (jobId: string, action: 'trigger' | 'pause' | 'resume') => {
    setBusy(jobId); setMsg('');
    try {
      if (action === 'trigger') await superadminApi.triggerJob(jobId);
      else if (action === 'pause') await superadminApi.pauseJob(jobId);
      else await superadminApi.resumeJob(jobId);
      setMsg(`Job ${jobId} ${action}d`);
      await load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? `Job ${action} failed`);
    } finally { setBusy(null); }
  };

  const revokeKey = async (keyId: string) => {
    setBusy(keyId); setMsg('');
    try {
      await superadminApi.infraRevokeApiKey(keyId, 'Revoked by superadmin');
      setApiKeys(prev => prev.map(k => k.key_id === keyId ? { ...k, active: false } : k));
      setMsg('API key revoked');
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Revoke failed');
    } finally { setBusy(null); setRevokeConfirm(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  const healthyServices = services.filter(s => s.status === 'healthy').length;
  const downServices    = services.filter(s => s.status === 'down').length;
  const activeJobs      = jobs.filter(j => j.status === 'active').length;
  const activeKeys      = apiKeys.filter(k => k.active).length;

  return (
    <>

      {revokeConfirm && (
        <ConfirmDialog
          title="Revoke API Key"
          message="This API key will be immediately invalidated. Any integrations using it will stop working."
          confirmLabel="Revoke Key"
          danger
          onConfirm={() => revokeKey(revokeConfirm)}
          onCancel={() => setRevokeConfirm(null)}
        />
      )}

      {msg && (
        <div style={{
          background: msg.includes('fail') || msg.includes('error') ? 'rgba(248,113,113,0.1)' : 'rgba(74,222,128,0.1)',
          border: `1px solid ${msg.includes('fail') || msg.includes('error') ? '#f87171' : '#4ade80'}`,
          borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13,
          color: msg.includes('fail') || msg.includes('error') ? '#f87171' : '#4ade80',
          display: 'flex', justifyContent: 'space-between',
        }}>
          {msg}
          <button onClick={() => setMsg('')} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14, marginBottom: 20 }}>
        <KpiTile label="Healthy Services" value={`${healthyServices}/${services.length}`} icon="✅" accent={downServices > 0 ? '#f87171' : '#22c55e'} />
        <KpiTile label="Down Services" value={downServices} icon="❌" accent={downServices > 0 ? '#ef4444' : '#22c55e'} />
        <KpiTile label="Active Jobs" value={activeJobs} icon="⏰" accent="#60a5fa" />
        <KpiTile label="Active API Keys" value={activeKeys} icon="🔑" accent="#a78bfa" />
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        {(['services', 'backups', 'jobs', 'apikeys'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? '#1e293b' : 'transparent',
            border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`,
            borderRadius: 8, color: tab === t ? '#f8fafc' : '#64748b',
            padding: '7px 14px', fontSize: 13, cursor: 'pointer',
          }}>
            {{ services: `Services (${services.length})`, backups: `Backups (${backups.length})`, jobs: `Jobs (${jobs.length})`, apikeys: `API Keys (${apiKeys.length})` }[t]}
          </button>
        ))}
        <ActionBtn label="Refresh" onClick={load} accent="#475569" size="sm" style={{ marginLeft: 'auto' }} />
      </div>

      {tab === 'services' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
          {services.map(svc => (
            <div key={svc.name} style={{
              background: '#0f172a', border: `1px solid ${svc.status === 'healthy' ? '#16a34a33' : svc.status === 'down' ? '#7f1d1d' : '#334155'}`,
              borderRadius: 12, padding: '16px 18px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 18 }}>{SERVICE_ICONS[svc.name] ?? '🔧'}</span>
                  <span style={{ fontWeight: 700, fontSize: 14, textTransform: 'capitalize' }}>{svc.name.replace(/_/g, ' ')}</span>
                </div>
                <StatusBadge status={svc.status} />
              </div>
              <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
                <div>
                  <div style={{ color: '#475569', marginBottom: 2 }}>Latency</div>
                  <div style={{ color: svc.latency_ms > 500 ? '#f87171' : svc.latency_ms > 100 ? '#fbbf24' : '#4ade80', fontWeight: 700 }}>
                    {svc.latency_ms}ms
                  </div>
                </div>
                <div>
                  <div style={{ color: '#475569', marginBottom: 2 }}>Last Check</div>
                  <div style={{ color: '#64748b' }}>{fmtDate(svc.last_check)}</div>
                </div>
              </div>
              {svc.error && (
                <div style={{ marginTop: 8, fontSize: 11, color: '#f87171', background: 'rgba(248,113,113,0.05)', padding: '4px 8px', borderRadius: 4 }}>
                  {svc.error}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'backups' && (
        <>
          <SectionCard title="Trigger Backup" icon="💾" accent="#22c55e">
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              {(['full', 'incremental', 'snapshot'] as const).map(t => (
                <button key={t} onClick={() => setBackupType(t)} style={{
                  background: backupType === t ? '#1e3a5f' : '#0f172a',
                  border: `1px solid ${backupType === t ? '#3b82f6' : '#334155'}`,
                  borderRadius: 8, color: backupType === t ? '#60a5fa' : '#64748b',
                  padding: '7px 16px', fontSize: 13, cursor: 'pointer', textTransform: 'capitalize',
                }}>
                  {t}
                </button>
              ))}
              <ActionBtn label="Trigger Backup" onClick={triggerBackup} loading={busy === 'backup'} accent="#22c55e" />
            </div>
          </SectionCard>

          <SectionCard title="Backup History" icon="📦" accent="#60a5fa" noPad>
            {backups.length === 0 ? (
              <EmptyState compact icon="💾" title="No backups found" description="Database and config backups will appear here once scheduled jobs run." />
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    {['Backup ID', 'Type', 'Status', 'Size', 'Created'].map(h => (
                      <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {backups.map(b => (
                    <tr key={b.backup_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                      <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 11, color: '#60a5fa' }}>{b.backup_id}</td>
                      <td style={{ padding: '10px 16px', textTransform: 'capitalize', color: '#94a3b8' }}>{b.type}</td>
                      <td style={{ padding: '10px 16px' }}><StatusBadge status={b.status} /></td>
                      <td style={{ padding: '10px 16px', color: '#94a3b8', fontSize: 12 }}>{b.size_mb.toFixed(1)} MB</td>
                      <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(b.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </SectionCard>
        </>
      )}

      {tab === 'jobs' && (
        <SectionCard title="Scheduled Jobs" icon="⏰" accent="#fbbf24" noPad>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {['Job', 'Schedule', 'Status', 'Last Run', 'Duration', 'Actions'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => (
                <tr key={job.job_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 16px' }}>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{job.name}</div>
                    <div style={{ fontSize: 11, color: '#475569', fontFamily: 'monospace' }}>{job.job_id}</div>
                  </td>
                  <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 11, color: '#a78bfa' }}>{job.schedule}</td>
                  <td style={{ padding: '10px 16px' }}><StatusBadge status={job.status} /></td>
                  <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(job.last_run)}</td>
                  <td style={{ padding: '10px 16px', color: '#94a3b8', fontSize: 12 }}>
                    {job.last_duration_ms ? fmtDuration(job.last_duration_ms) : '—'}
                  </td>
                  <td style={{ padding: '10px 16px' }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <ActionBtn label="Run" onClick={() => jobAction(job.job_id, 'trigger')} loading={busy === job.job_id} accent="#22c55e" size="sm" />
                      {job.status === 'active'
                        ? <ActionBtn label="Pause" onClick={() => jobAction(job.job_id, 'pause')} loading={busy === job.job_id} accent="#fbbf24" size="sm" />
                        : <ActionBtn label="Resume" onClick={() => jobAction(job.job_id, 'resume')} loading={busy === job.job_id} accent="#60a5fa" size="sm" />
                      }
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

      {tab === 'apikeys' && (
        <SectionCard title="API Key Audit" icon="🔑" accent="#a78bfa" noPad
          subtitle="Cross-user API key inventory — revoke compromised keys immediately">
          {apiKeys.length === 0 ? (
            <EmptyState compact icon="🔑" title="No API keys found" description="Platform API keys will appear here once created." />
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Key', 'User', 'Scopes', 'Created', 'Last Used', 'Active', 'Actions'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {apiKeys.map(k => (
                  <tr key={k.key_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 16px' }}>
                      <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#a78bfa' }}>{k.prefix}…</div>
                      <div style={{ fontSize: 11, color: '#475569' }}>{k.name}</div>
                    </td>
                    <td style={{ padding: '10px 16px', fontSize: 12, color: '#94a3b8', fontFamily: 'monospace' }}>{k.user_id.slice(0, 12)}…</td>
                    <td style={{ padding: '10px 16px', fontSize: 11, color: '#64748b' }}>{k.scopes?.join(', ') || 'all'}</td>
                    <td style={{ padding: '10px 16px', fontSize: 12, color: '#64748b' }}>{fmtDate(k.created_at)}</td>
                    <td style={{ padding: '10px 16px', fontSize: 12, color: k.last_used ? '#94a3b8' : '#334155' }}>{fmtDate(k.last_used)}</td>
                    <td style={{ padding: '10px 16px' }}>
                      <span style={{ color: k.active ? '#4ade80' : '#f87171', fontSize: 12, fontWeight: 700 }}>
                        {k.active ? 'Active' : 'Revoked'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 16px' }}>
                      {k.active && (
                        <ActionBtn
                          label="Revoke"
                          onClick={() => setRevokeConfirm(k.key_id)}
                          loading={busy === k.key_id}
                          accent="#f87171"
                          size="sm"
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </SectionCard>
      )}
    </>
  );
};

export default SystemHealthSection;
