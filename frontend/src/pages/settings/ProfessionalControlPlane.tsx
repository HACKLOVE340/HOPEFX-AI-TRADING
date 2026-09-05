import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../hooks/useApi';
import type { SettingsTab } from './types';

type Readiness = { status: string; active_model: string; components: Record<string, string>; degraded_reasons: string[]; configuration_revision: number; paper_mode: boolean };
type Props = { tab: SettingsTab };

const domains: Record<string, string> = {
  'control-brain': 'core_brain', 'control-models': 'models', 'control-agents': 'agents',
  'control-connectors': 'connectors', 'control-sandbox': 'sandbox', 'control-startup': 'startup',
};

export default function ProfessionalControlPlane({ tab }: Props) {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [configuration, setConfiguration] = useState<Record<string, any> | null>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      const [ready, config] = await Promise.all([api.get<Readiness>('/control-plane/readiness'), api.get('/control-plane/configuration')]);
      setReadiness(ready.data);
      setConfiguration(config.data.configuration);
      if (tab === 'control-audit') setAudit((await api.get('/control-plane/audit')).data.items ?? []);
    } catch (e: any) { setError(e?.response?.data?.detail ?? 'Control plane is unavailable'); }
  }, [tab]);
  useEffect(() => { void load(); }, [load]);

  const reprobe = async () => { setBusy(true); try { await api.post('/control-plane/readiness/reprobe'); await load(); } finally { setBusy(false); } };
  const runSandboxTest = async () => { setBusy(true); try { await api.post('/control-plane/sandbox/test', { command: 'python --version', timeout_seconds: 5 }); await load(); } catch (e: any) { setError(e?.response?.data?.detail ?? 'Sandbox test rejected'); } finally { setBusy(false); } };

  if (error) return <div style={styles.alert}><strong>Control plane unavailable</strong><p>{error}</p><button style={styles.button} onClick={() => void load()}>Retry</button></div>;
  if (!readiness || !configuration) return <div style={styles.card}>Loading professional configuration…</div>;

  const domain = domains[tab];
  const title = tab === 'control-overview' ? 'Operations readiness' : tab === 'control-audit' ? 'Configuration audit' : domain?.replace('_', ' ');
  return <div style={styles.stack}>
    <div style={styles.header}><div><div style={styles.eyebrow}>PROFESSIONAL CONTROL PLANE</div><h2 style={styles.title}>{title}</h2><p style={styles.muted}>Versioned, permissioned configuration with truthful runtime health.</p></div><div style={{ display: 'flex', gap: 8 }}><span style={badge(readiness.status)}>{readiness.status.toUpperCase()}</span><span style={badge(readiness.paper_mode ? 'paper' : 'live')}>{readiness.paper_mode ? 'PAPER MODE' : 'LIVE MODE'}</span></div></div>
    {readiness.degraded_reasons.length > 0 && <div style={styles.warning}><strong>Degraded operation</strong><div>{readiness.degraded_reasons.join(' · ')}</div></div>}
    {tab === 'control-overview' && <><div style={styles.grid}>{Object.entries(readiness.components).map(([name, state]) => <div key={name} style={styles.card}><div style={styles.row}><strong>{name.replace('_', ' ')}</strong><span style={badge(state)}>{state}</span></div><div style={styles.muted}>Lifecycle component</div></div>)}</div><div style={styles.card}><div style={styles.row}><strong>Active model route</strong><code>{readiness.active_model}</code></div><div style={styles.muted}>Revision {readiness.configuration_revision}. Secrets remain redacted.</div></div><button style={styles.button} disabled={busy} onClick={() => void reprobe()}>{busy ? 'Checking…' : 'Re-run readiness probes'}</button></>}
    {domain && <div style={styles.card}><pre style={styles.pre}>{JSON.stringify(configuration[domain], null, 2)}</pre>{domain === 'sandbox' && <button style={styles.button} disabled={busy} onClick={() => void runSandboxTest()}>Run safe paper-mode test</button>}</div>}
    {tab === 'control-audit' && <div style={styles.card}>{audit.length === 0 ? <div style={styles.muted}>No configuration mutations recorded.</div> : audit.map(item => <div key={item.id} style={styles.audit}><strong>{item.action}</strong><span>{item.result}</span><small>{item.reason} · {new Date(item.created_at).toLocaleString()}</small></div>)}</div>}
  </div>;
}

const badge = (value: string): React.CSSProperties => ({ color: value === 'ready' || value === 'paper' ? '#34d399' : value === 'degraded' ? '#fbbf24' : '#94a3b8', fontSize: 11, fontWeight: 800, letterSpacing: '.08em' });
const styles: Record<string, React.CSSProperties> = { stack: { display: 'flex', flexDirection: 'column', gap: 16 }, header: { display: 'flex', justifyContent: 'space-between', gap: 20, alignItems: 'flex-start' }, eyebrow: { color: '#60a5fa', fontSize: 11, fontWeight: 800, letterSpacing: '.12em' }, title: { margin: '6px 0', color: '#f8fafc', fontSize: 25, textTransform: 'capitalize' }, muted: { color: '#94a3b8', fontSize: 13, lineHeight: 1.5 }, grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }, card: { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 16 }, row: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, color: '#e2e8f0' }, warning: { padding: 14, borderRadius: 10, border: '1px solid #92400e', background: '#451a03', color: '#fef3c7', fontSize: 13, lineHeight: 1.5 }, alert: { padding: 20, borderRadius: 12, border: '1px solid #7f1d1d', background: '#450a0a', color: '#fecaca' }, button: { border: 0, borderRadius: 8, padding: '10px 14px', background: '#2563eb', color: '#fff', fontWeight: 700, cursor: 'pointer' }, pre: { margin: 0, whiteSpace: 'pre-wrap', color: '#cbd5e1', fontSize: 12, fontFamily: 'monospace' }, audit: { display: 'grid', gridTemplateColumns: '1fr auto', gap: 5, padding: '12px 0', borderBottom: '1px solid #1e293b', color: '#e2e8f0' } };
