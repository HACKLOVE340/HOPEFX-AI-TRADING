// superadmin/RateLimitingSection.tsx
// Rate limit rules, live stats, violation log
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, ActionBtn, Select, Input, Toggle,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog,
} from './ui';
import type { RateLimitRule } from './types';
import { extractApiError } from '../../lib/utils';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const SCOPE_COLORS: Record<string, string> = {
  global:   '#a78bfa',
  per_user: '#60a5fa',
  per_ip:   '#fbbf24',
};

interface Violation {
  endpoint: string;
  ip?: string;
  user_id?: string;
  count: number;
  timestamp: string;
}

const RateLimitingSection: React.FC = () => {
  const [rules, setRules]           = useState<RateLimitRule[]>([]);
  const [stats, setStats]           = useState<{ total_requests: number; blocked_requests: number }>({ total_requests: 0, blocked_requests: 0 });
  const [violations, setViolations] = useState<Violation[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState('');
  const [busy, setBusy]             = useState<string | null>(null);
  const [msg, setMsg]               = useState('');
  const [tab, setTab]               = useState<'rules' | 'violations'>('rules');
  const [showCreate, setShowCreate] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [newRule, setNewRule]       = useState({ endpoint: '', limit: '100', window_seconds: '60', scope: 'per_user' });
  const [editing, setEditing]       = useState<Record<string, { limit: string; window_seconds: string }>>({});

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [rRes, sRes, vRes] = await Promise.all([
        superadminApi.rateLimitRules(),
        superadminApi.rateLimitStats(),
        superadminApi.rateLimitViolations(),
      ]);
      if (!mountedRef.current) return;
      const rulesRaw = rRes.data.rules ?? rRes.data;
      setRules(Array.isArray(rulesRaw) ? rulesRaw : []);

      // Backend returns either {total_requests, blocked_requests} or
      // {stats: [{endpoint, hits}, ...]}. Normalise to the expected shape.
      const sd = sRes.data ?? {};
      if (typeof sd.total_requests === 'number') {
        setStats({ total_requests: sd.total_requests, blocked_requests: sd.blocked_requests ?? 0 });
      } else {
        const statsArr: { hits?: number }[] = Array.isArray(sd.stats) ? sd.stats : [];
        const total = statsArr.reduce((acc, s) => acc + (s.hits ?? 0), 0);
        setStats({ total_requests: total, blocked_requests: 0 });
      }

      const violRaw = vRes.data.violations ?? vRes.data;
      setViolations(Array.isArray(violRaw) ? violRaw : []);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load rate limit data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 30 s — configuration and model data changes less frequently.
  usePolling(load, 30_000);

  const toggleRule = async (rule: RateLimitRule) => {
    setBusy(rule.rule_id); setMsg('');
    try {
      await superadminApi.updateRateLimitRule(rule.rule_id, { enabled: !rule.enabled });
      setRules(prev => prev.map(r => r.rule_id === rule.rule_id ? { ...r, enabled: !r.enabled } : r));
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Toggle failed'));
    } finally { setBusy(null); }
  };

  const saveEdit = async (ruleId: string) => {
    const edit = editing[ruleId];
    if (!edit) return;
    setBusy(ruleId); setMsg('');
    try {
      await superadminApi.updateRateLimitRule(ruleId, {
        limit:          parseInt(edit.limit),
        window_seconds: parseInt(edit.window_seconds),
      });
      setRules(prev => prev.map(r => r.rule_id === ruleId
        ? { ...r, limit: parseInt(edit.limit), window_seconds: parseInt(edit.window_seconds) }
        : r));
      setEditing(prev => { const n = { ...prev }; delete n[ruleId]; return n; });
      setMsg('Rule updated');
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Update failed'));
    } finally { setBusy(null); }
  };

  const createRule = async () => {
    setBusy('create'); setMsg('');
    try {
      const res = await superadminApi.createRateLimitRule({
        endpoint:       newRule.endpoint,
        limit:          parseInt(newRule.limit),
        window_seconds: parseInt(newRule.window_seconds),
        scope:          newRule.scope,
        enabled:        true,
      });
      // Backend returns { ok, rule }, not the bare rule — push the rule so the
      // new row has scope/current_hits/rule_id and doesn't crash the table.
      setRules(prev => [...prev, res.data?.rule ?? res.data]);
      setNewRule({ endpoint: '', limit: '100', window_seconds: '60', scope: 'per_user' });
      setShowCreate(false);
      setMsg('Rule created');
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Create failed'));
    } finally { setBusy(null); }
  };

  const deleteRule = async (ruleId: string) => {
    setBusy(ruleId); setMsg('');
    try {
      await superadminApi.deleteRateLimitRule(ruleId);
      setRules(prev => prev.filter(r => r.rule_id !== ruleId));
      setMsg('Rule deleted');
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Delete failed'));
    } finally { setBusy(null); setDeleteConfirm(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  const blockRate = stats.total_requests > 0
    ? ((stats.blocked_requests / stats.total_requests) * 100).toFixed(2)
    : '0.00';

  return (
    <>

      {deleteConfirm && (
        <ConfirmDialog
          title="Delete Rate Limit Rule"
          message="This will immediately remove the rate limit rule. Traffic will no longer be throttled for this endpoint."
          confirmLabel="Delete Rule"
          danger
          onConfirm={() => deleteRule(deleteConfirm)}
          onCancel={() => setDeleteConfirm(null)}
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
        <KpiTile label="Active Rules" value={rules.filter(r => r.enabled).length} icon="🔒" accent="#60a5fa" />
        <KpiTile label="Total Requests" value={stats.total_requests.toLocaleString()} icon="📊" accent="#22c55e" />
        <KpiTile label="Blocked Requests" value={stats.blocked_requests.toLocaleString()} icon="🚫" accent="#f87171" />
        <KpiTile label="Block Rate" value={`${blockRate}%`} icon="📉" accent={parseFloat(blockRate) > 5 ? '#f87171' : '#22c55e'} />
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {(['rules', 'violations'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? '#1e293b' : 'transparent',
            border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`,
            borderRadius: 8, color: tab === t ? '#f8fafc' : '#64748b',
            padding: '7px 16px', fontSize: 13, cursor: 'pointer',
          }}>
            {t === 'rules' ? `Rules (${rules.length})` : `Violations (${violations.length})`}
          </button>
        ))}
        {tab === 'rules' && (
          <ActionBtn label="+ New Rule" onClick={() => setShowCreate(s => !s)} accent="#3b82f6" size="sm" style={{ marginLeft: 'auto' }} />
        )}
      </div>

      {tab === 'rules' && (
        <>
          {showCreate && (
            <SectionCard title="Create Rate Limit Rule" icon="➕" accent="#3b82f6">
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <div style={{ flex: 2, minWidth: 200 }}>
                  <Input label="Endpoint pattern" placeholder="/api/trading/orders or *" value={newRule.endpoint} onChange={e => setNewRule(p => ({ ...p, endpoint: e.target.value }))} />
                </div>
                <div style={{ width: 100 }}>
                  <Input label="Limit" type="number" value={newRule.limit} onChange={e => setNewRule(p => ({ ...p, limit: e.target.value }))} />
                </div>
                <div style={{ width: 120 }}>
                  <Input label="Window (sec)" type="number" value={newRule.window_seconds} onChange={e => setNewRule(p => ({ ...p, window_seconds: e.target.value }))} />
                </div>
                <div style={{ width: 140 }}>
                  <Select label="Scope" value={newRule.scope} onChange={e => setNewRule(p => ({ ...p, scope: e.target.value }))}
                    options={[{ value: 'per_user', label: 'Per User' }, { value: 'per_ip', label: 'Per IP' }, { value: 'global', label: 'Global' }]} />
                </div>
                <ActionBtn label="Create" onClick={createRule} loading={busy === 'create'} accent="#22c55e" disabled={!newRule.endpoint} />
              </div>
            </SectionCard>
          )}

          <SectionCard title="Rate Limit Rules" icon="🔒" accent="#60a5fa" noPad>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Endpoint', 'Limit / Window', 'Scope', 'Hits', 'Enabled', 'Actions'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rules.map(rule => {
                  const isEditing = !!editing[rule.rule_id];
                  return (
                    <tr key={rule.rule_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                      <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 12, color: '#60a5fa' }}>{rule.endpoint}</td>
                      <td style={{ padding: '10px 16px' }}>
                        {isEditing ? (
                          <div style={{ display: 'flex', gap: 6 }}>
                            <input
                              type="number"
                              value={editing[rule.rule_id].limit}
                              onChange={e => setEditing(p => ({ ...p, [rule.rule_id]: { ...p[rule.rule_id], limit: e.target.value } }))}
                              style={{ width: 70, background: '#0f172a', border: '1px solid #334155', borderRadius: 4, color: '#f8fafc', padding: '3px 6px', fontSize: 12 }}
                            />
                            <span style={{ color: '#475569', alignSelf: 'center' }}>/</span>
                            <input
                              type="number"
                              value={editing[rule.rule_id].window_seconds}
                              onChange={e => setEditing(p => ({ ...p, [rule.rule_id]: { ...p[rule.rule_id], window_seconds: e.target.value } }))}
                              style={{ width: 70, background: '#0f172a', border: '1px solid #334155', borderRadius: 4, color: '#f8fafc', padding: '3px 6px', fontSize: 12 }}
                            />
                            <span style={{ color: '#475569', alignSelf: 'center', fontSize: 11 }}>s</span>
                          </div>
                        ) : (
                          <span style={{ color: '#f8fafc' }}>
                            {rule.limit} / {rule.window_seconds}s
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <span style={{
                          fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 4,
                          background: `${SCOPE_COLORS[rule.scope] ?? '#94a3b8'}22`,
                          color: SCOPE_COLORS[rule.scope] ?? '#94a3b8',
                          border: `1px solid ${SCOPE_COLORS[rule.scope] ?? '#94a3b8'}44`,
                        }}>
                          {rule.scope.replace('_', ' ').toUpperCase()}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px', color: rule.current_hits > rule.limit * 0.8 ? '#f87171' : '#94a3b8', fontSize: 12 }}>
                        {rule.current_hits.toLocaleString()}
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <Toggle checked={rule.enabled} onChange={() => toggleRule(rule)} disabled={busy === rule.rule_id} />
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <div style={{ display: 'flex', gap: 6 }}>
                          {isEditing ? (
                            <>
                              <ActionBtn label="Save" onClick={() => saveEdit(rule.rule_id)} loading={busy === rule.rule_id} accent="#22c55e" size="sm" />
                              <ActionBtn label="Cancel" onClick={() => setEditing(p => { const n = { ...p }; delete n[rule.rule_id]; return n; })} accent="#64748b" size="sm" />
                            </>
                          ) : (
                            <>
                              <ActionBtn label="Edit" onClick={() => setEditing(p => ({ ...p, [rule.rule_id]: { limit: String(rule.limit), window_seconds: String(rule.window_seconds) } }))} accent="#60a5fa" size="sm" />
                              <ActionBtn label="Delete" onClick={() => setDeleteConfirm(rule.rule_id)} accent="#f87171" size="sm" />
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </SectionCard>
        </>
      )}

      {tab === 'violations' && (
        <SectionCard title="Rate Limit Violations" icon="🚫" accent="#f87171" noPad>
          {violations.length === 0 ? (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>No violations recorded</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Endpoint', 'IP / User', 'Count', 'Time'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {violations.slice(0, 100).map((v, i) => (
                  <tr key={i} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 12, color: '#f87171' }}>{v.endpoint}</td>
                    <td style={{ padding: '10px 16px', color: '#94a3b8', fontSize: 12 }}>{v.ip ?? v.user_id ?? '—'}</td>
                    <td style={{ padding: '10px 16px', color: '#fbbf24', fontWeight: 700 }}>{v.count}</td>
                    <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(v.timestamp)}</td>
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

export default RateLimitingSection;
