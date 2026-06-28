// superadmin/AlertingSection.tsx
// Alert rules, fired alerts, Prometheus status, silence controls
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, SeverityBadge, ActionBtn, Select, Input, Toggle,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog,
} from './ui';
import type { AlertRule } from './types';
import { asArray, extractApiError } from '../../lib/utils';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

interface FiredAlert {
  rule_id: string;
  name: string;
  severity: string;
  fired_at: string;
  value?: string;
  message?: string;
}

const AlertingSection: React.FC = () => {
  const [rules, setRules]       = useState<AlertRule[]>([]);
  const [fired, setFired]       = useState<FiredAlert[]>([]);
  const [promStatus, setPromStatus] = useState<{ available: boolean; firing_alerts: number; active_rules: number } | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [tab, setTab]           = useState<'rules' | 'fired'>('rules');
  const [showCreate, setShowCreate] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [silenceId, setSilenceId] = useState<string | null>(null);
  const [silenceDuration, setSilenceDuration] = useState('60');
  const [newRule, setNewRule]   = useState({ name: '', condition: '', severity: 'warning', channels: 'slack' });

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [rRes, fRes, pRes] = await Promise.all([
        superadminApi.alertRules(),
        superadminApi.firedAlerts(),
        superadminApi.prometheusStatus(),
      ]);
      if (!mountedRef.current) return;
      setRules(asArray(rRes.data, 'rules'));
      setFired(asArray(fRes.data.alerts ?? fRes.data.fired ?? fRes.data.history ?? fRes.data));
      setPromStatus(pRes.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load alerting data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 15 s while the tab is active — live operational data.
  usePolling(load, 15_000);

  const toggleRule = async (rule: AlertRule) => {
    setBusy(rule.rule_id); setMsg('');
    try {
      await superadminApi.updateAlertRule(rule.rule_id, { enabled: !rule.enabled });
      setRules(prev => prev.map(r => r.rule_id === rule.rule_id ? { ...r, enabled: !r.enabled } : r));
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Toggle failed'));
    } finally { setBusy(null); }
  };

  const silenceRule = async () => {
    if (!silenceId) return;
    setBusy(silenceId); setMsg('');
    try {
      await superadminApi.silenceAlert(silenceId, parseInt(silenceDuration));
      setMsg(`Alert silenced for ${silenceDuration} minutes`);
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Silence failed'));
    } finally { setBusy(null); setSilenceId(null); }
  };

  const createRule = async () => {
    setBusy('create'); setMsg('');
    try {
      const res = await superadminApi.createAlertRule({
        name:      newRule.name,
        condition: newRule.condition,
        severity:  newRule.severity,
        channels:  newRule.channels.split(',').map(c => c.trim()).filter(Boolean),
        enabled:   true,
      });
      // Backend returns { ok, rule }, not the bare rule — push the rule so the
      // new row has channels/severity/rule_id and doesn't crash the table.
      setRules(prev => [...prev, res.data?.rule ?? res.data]);
      setNewRule({ name: '', condition: '', severity: 'warning', channels: 'slack' });
      setShowCreate(false);
      setMsg('Alert rule created');
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Create failed'));
    } finally { setBusy(null); }
  };

  const deleteRule = async (ruleId: string) => {
    setBusy(ruleId); setMsg('');
    try {
      await superadminApi.deleteAlertRule(ruleId);
      setRules(prev => prev.filter(r => r.rule_id !== ruleId));
      setMsg('Rule deleted');
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Delete failed'));
    } finally { setBusy(null); setDeleteConfirm(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  const criticalFired = fired.filter(f => f.severity === 'critical').length;

  return (
    <>

      {deleteConfirm && (
        <ConfirmDialog
          title="Delete Alert Rule"
          message="This alert rule will be permanently removed."
          confirmLabel="Delete"
          danger
          onConfirm={() => deleteRule(deleteConfirm)}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}
      {silenceId && (
        <ConfirmDialog
          title="Silence Alert"
          message={`Silence this alert for ${silenceDuration} minutes?`}
          confirmLabel="Silence"
          onConfirm={silenceRule}
          onCancel={() => setSilenceId(null)}
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
        <KpiTile label="Active Rules" value={rules.filter(r => r.enabled).length} icon="🔔" accent="#60a5fa" />
        <KpiTile label="Fired (24h)" value={fired.length} icon="🚨" accent={fired.length > 0 ? '#fbbf24' : '#22c55e'} />
        <KpiTile label="Critical Firing" value={criticalFired} icon="🔴" accent={criticalFired > 0 ? '#ef4444' : '#22c55e'} />
        <KpiTile label="Prometheus" value={promStatus?.available ? 'Connected' : 'Offline'} icon="📡" accent={promStatus?.available ? '#22c55e' : '#f87171'} />
      </div>

      {/* Prometheus status */}
      {promStatus && (
        <div style={{
          background: '#0f172a', border: `1px solid ${promStatus.available ? '#16a34a' : '#7f1d1d'}`,
          borderRadius: 10, padding: '12px 16px', marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 12, fontSize: 13,
        }}>
          <span style={{ fontSize: 16 }}>{promStatus.available ? '✅' : '❌'}</span>
          <span style={{ color: promStatus.available ? '#4ade80' : '#f87171', fontWeight: 600 }}>
            Prometheus {promStatus.available ? 'connected' : 'offline'}
          </span>
          {promStatus.available && (
            <span style={{ color: '#64748b' }}>
              — {promStatus.active_rules} rules · {promStatus.firing_alerts} firing
            </span>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {(['rules', 'fired'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? '#1e293b' : 'transparent',
            border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`,
            borderRadius: 8, color: tab === t ? '#f8fafc' : '#64748b',
            padding: '7px 16px', fontSize: 13, cursor: 'pointer',
          }}>
            {t === 'rules' ? `Rules (${rules.length})` : `Fired Alerts (${fired.length})`}
          </button>
        ))}
        {tab === 'rules' && (
          <ActionBtn label="+ New Rule" onClick={() => setShowCreate(s => !s)} accent="#3b82f6" size="sm" style={{ marginLeft: 'auto' }} />
        )}
      </div>

      {tab === 'rules' && (
        <>
          {showCreate && (
            <SectionCard title="Create Alert Rule" icon="➕" accent="#3b82f6">
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <Input label="Rule name" placeholder="High CPU Usage" value={newRule.name} onChange={e => setNewRule(p => ({ ...p, name: e.target.value }))} />
                </div>
                <div style={{ flex: 2, minWidth: 200 }}>
                  <Input label="Condition" placeholder="cpu_pct > 90" value={newRule.condition} onChange={e => setNewRule(p => ({ ...p, condition: e.target.value }))} />
                </div>
                <div style={{ width: 140 }}>
                  <Select label="Severity" value={newRule.severity} onChange={e => setNewRule(p => ({ ...p, severity: e.target.value }))}
                    options={[{ value: 'info', label: 'Info' }, { value: 'warning', label: 'Warning' }, { value: 'critical', label: 'Critical' }]} />
                </div>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <Input label="Channels (comma-sep)" placeholder="slack,email" value={newRule.channels} onChange={e => setNewRule(p => ({ ...p, channels: e.target.value }))} />
                </div>
                <ActionBtn label="Create" onClick={createRule} loading={busy === 'create'} accent="#22c55e" disabled={!newRule.name || !newRule.condition} />
              </div>
            </SectionCard>
          )}

          <SectionCard title="Alert Rules" icon="🔔" accent="#60a5fa" noPad>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Name', 'Condition', 'Severity', 'Channels', 'Last Fired', 'Fires', 'Enabled', 'Actions'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rules.map(rule => (
                  <tr key={rule.rule_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 16px', fontWeight: 600 }}>{rule.name}</td>
                    <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 11, color: '#94a3b8' }}>{rule.condition}</td>
                    <td style={{ padding: '10px 16px' }}><SeverityBadge severity={rule.severity} /></td>
                    <td style={{ padding: '10px 16px', fontSize: 11, color: '#64748b' }}>{rule.channels.join(', ')}</td>
                    <td style={{ padding: '10px 16px', fontSize: 11, color: '#64748b' }}>{fmtDate(rule.last_fired)}</td>
                    <td style={{ padding: '10px 16px', color: rule.fire_count > 0 ? '#fbbf24' : '#475569' }}>{rule.fire_count}</td>
                    <td style={{ padding: '10px 16px' }}>
                      <Toggle checked={rule.enabled} onChange={() => toggleRule(rule)} disabled={busy === rule.rule_id} />
                    </td>
                    <td style={{ padding: '10px 16px' }}>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <ActionBtn label="Silence" onClick={() => setSilenceId(rule.rule_id)} accent="#fbbf24" size="sm" />
                        <ActionBtn label="Delete" onClick={() => setDeleteConfirm(rule.rule_id)} accent="#f87171" size="sm" />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>
        </>
      )}

      {tab === 'fired' && (
        <SectionCard title="Fired Alerts" icon="🚨" accent="#fbbf24" noPad>
          {fired.length === 0 ? (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>No alerts fired recently</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Rule', 'Severity', 'Message', 'Fired At'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fired.slice(0, 100).map((a, i) => (
                  <tr key={i} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 16px', fontWeight: 600 }}>{a.name}</td>
                    <td style={{ padding: '10px 16px' }}><SeverityBadge severity={a.severity} /></td>
                    <td style={{ padding: '10px 16px', color: '#94a3b8', fontSize: 12 }}>{a.message ?? a.value ?? '—'}</td>
                    <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(a.fired_at)}</td>
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

export default AlertingSection;
