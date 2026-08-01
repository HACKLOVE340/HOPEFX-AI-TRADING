// superadmin/GDPRSection.tsx
// Data subject requests, erasure, consent log, retention policies
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import { EmptyState } from '../../components/EmptyState';
import {
  SectionCard, StatusBadge, ActionBtn, Select, Input,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog,
} from './ui';
import type { DataSubjectRequest } from './types';
import { extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const REQUEST_TYPE_COLORS: Record<string, string> = {
  export:        '#60a5fa',
  erasure:       '#f87171',
  rectification: '#fbbf24',
  portability:   '#a78bfa',
};

interface RetentionPolicy { data_type: string; retention_days: number; legal_basis?: string }
interface ConsentEntry    { user_id: string; event: string; timestamp: string; details: string; ip?: string }

const GDPRSection: React.FC = () => {
  const [requests, setRequests]     = useState<DataSubjectRequest[]>([]);
  const [policies, setPolicies]     = useState<RetentionPolicy[]>([]);
  const [policyEdits, setPolicyEdits] = useState<Record<string, number>>({});
  const [consentLog, setConsentLog] = useState<ConsentEntry[]>([]);
  const [consentLoading, setConsentLoading] = useState(false);
  const [consentUserFilter, setConsentUserFilter] = useState('');
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState('');
  const [statusFilter, setStatusFilter] = useState('pending');
  const [typeFilter, setTypeFilter]     = useState('');
  const [busy, setBusy]             = useState<string | null>(null);
  const [msg, setMsg]               = useState('');
  const [msgOk, setMsgOk] = useState(true);
  const [confirm, setConfirm]       = useState<{ id: string; action: 'approve' | 'reject'; label: string } | null>(null);
  const [eraseUserId, setEraseUserId] = useState('');
  const [eraseReason, setEraseReason] = useState('');
  const [eraseConfirm, setEraseConfirm] = useState(false);
  const [tab, setTab]               = useState<'requests' | 'policies' | 'consent'>('requests');

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params: Record<string, string> = {};
      if (statusFilter) params.status = statusFilter;
      if (typeFilter)   params.request_type = typeFilter;
      const [rRes, pRes] = await Promise.all([
        superadminApi.gdprRequests(params),
        superadminApi.retentionPolicies(),
      ]);
      if (!mountedRef.current) return;
      const reqRaw = rRes.data.requests ?? rRes.data;
      setRequests(Array.isArray(reqRaw) ? reqRaw : []);
      const polRaw = pRes.data.policies ?? pRes.data;
      const p: RetentionPolicy[] = Array.isArray(polRaw) ? polRaw : [];
      setPolicies(p);
      // Initialise edit map with current values
      const edits: Record<string, number> = {};
      p.forEach(pol => { edits[pol.data_type] = pol.retention_days; });
      setPolicyEdits(edits);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load GDPR data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [statusFilter, typeFilter]);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  // Load consent log lazily when tab selected
  useEffect(() => {
    if (tab !== 'consent') return;
    setConsentLoading(true);
    superadminApi.consentLog(consentUserFilter || undefined)
      .then(r => setConsentLog(r.data.entries ?? r.data ?? []))
      .catch(() => setConsentLog([]))
      .finally(() => setConsentLoading(false));
  }, [tab, consentUserFilter]);

  const processRequest = async (id: string, action: 'approve' | 'reject') => {
    setBusy(id); setMsg('');
    try {
      await superadminApi.processGdprRequest(id, action);
      setMsgOk(true);
      setMsg(`Request ${action === 'approve' ? 'approved' : 'rejected'}`);
      await load();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Action failed'));
    } finally { setBusy(null); setConfirm(null); }
  };

  const eraseUser = async () => {
    if (!eraseUserId.trim()) return;
    setBusy('erase'); setMsg('');
    try {
      await superadminApi.gdprEraseUser(eraseUserId.trim(), eraseReason || 'Superadmin GDPR erasure');
      setMsgOk(true);
      setMsg(`User ${eraseUserId} erased — PII anonymised`);
      setEraseUserId(''); setEraseReason('');
      await load();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Erasure failed'));
    } finally { setBusy(null); setEraseConfirm(false); }
  };

  const exportUserData = async (userId: string) => {
    setBusy(`export-${userId}`); setMsg('');
    try {
      await superadminApi.gdprExportUser(userId);
      setMsgOk(true);
      setMsg(`Export queued for ${userId} — user will receive download link`);
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Export failed'));
    } finally { setBusy(null); }
  };

  const savePolicy = async (dataType: string) => {
    const days = policyEdits[dataType];
    if (days === undefined) return;
    setBusy(`policy-${dataType}`); setMsg('');
    try {
      await superadminApi.updateRetentionPolicy({ data_type: dataType, retention_days: days });
      setMsgOk(true);
      setMsg(`Retention for "${dataType}" updated to ${days} days`);
      // Update local state
      setPolicies(prev => prev.map(p => p.data_type === dataType ? { ...p, retention_days: days } : p));
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Update failed'));
    } finally { setBusy(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  const pending  = requests.filter(r => r.status === 'pending').length;
  const erasures = requests.filter(r => r.request_type === 'erasure').length;

  return (
    <>

      {confirm && (
        <ConfirmDialog
          title={confirm.label}
          message={confirm.action === 'approve' && requests.find(r => r.request_id === confirm.id)?.request_type === 'erasure'
            ? "This will permanently anonymise the user's PII. This action cannot be undone."
            : 'Confirm this GDPR action?'}
          confirmLabel={confirm.label}
          danger={confirm.action === 'approve' && requests.find(r => r.request_id === confirm.id)?.request_type === 'erasure'}
          onConfirm={() => processRequest(confirm.id, confirm.action)}
          onCancel={() => setConfirm(null)}
        />
      )}
      {eraseConfirm && (
        <ConfirmDialog
          title="Erase User Data"
          message={`Permanently anonymise all PII for user "${eraseUserId}". This cannot be undone.`}
          confirmLabel="Erase User"
          danger
          onConfirm={eraseUser}
          onCancel={() => setEraseConfirm(false)}
        />
      )}

      <ActionBanner message={msg} ok={msgOk} onDismiss={() => setMsg('')} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14, marginBottom: 20 }}>
        <KpiTile label="Pending Requests"  value={pending}           icon="⏳" accent={pending > 0 ? '#fbbf24' : '#22c55e'} />
        <KpiTile label="Total Requests"    value={requests.length}   icon="📋" accent="#60a5fa" />
        <KpiTile label="Erasure Requests"  value={erasures}          icon="🗑️" accent="#f87171" />
        <KpiTile label="Retention Policies" value={policies.length}  icon="📅" accent="#a78bfa" />
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {(['requests', 'policies', 'consent'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ background: tab === t ? '#1e293b' : 'transparent', border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`, borderRadius: 8, color: tab === t ? '#f8fafc' : '#64748b', padding: '7px 16px', fontSize: 13, cursor: 'pointer' }}>
            {{ requests: 'Data Subject Requests', policies: 'Retention Policies', consent: 'Consent Log' }[t]}
          </button>
        ))}
      </div>

      {/* ── TAB: Requests ── */}
      {tab === 'requests' && (
        <>
          {/* Manual Erasure */}
          <SectionCard title="Manual Erasure (Art. 17)" icon="🗑️" accent="#f87171"
            subtitle="Directly erase a user's PII without a formal request">
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <Input label="User ID" placeholder="user_id or email" value={eraseUserId} onChange={e => setEraseUserId(e.target.value)} />
              </div>
              <div style={{ flex: 2, minWidth: 240 }}>
                <Input label="Reason" placeholder="Regulatory order, user request…" value={eraseReason} onChange={e => setEraseReason(e.target.value)} />
              </div>
              <ActionBtn label="Erase User" onClick={() => setEraseConfirm(true)} loading={busy === 'erase'} accent="#f87171" disabled={!eraseUserId.trim()} />
            </div>
          </SectionCard>

          {/* Filters */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
            <Select label="" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ minWidth: 160 }}
              options={[{ value: '', label: 'All statuses' }, { value: 'pending', label: 'Pending' }, { value: 'processing', label: 'Processing' }, { value: 'completed', label: 'Completed' }, { value: 'rejected', label: 'Rejected' }]} />
            <Select label="" value={typeFilter} onChange={e => setTypeFilter(e.target.value)} style={{ minWidth: 200 }}
              options={[{ value: '', label: 'All types' }, { value: 'export', label: 'Export (Art. 15)' }, { value: 'erasure', label: 'Erasure (Art. 17)' }, { value: 'rectification', label: 'Rectification (Art. 16)' }, { value: 'portability', label: 'Portability (Art. 20)' }]} />
          </div>

          <SectionCard title="Data Subject Requests" icon="📋" accent="#60a5fa" noPad>
            {requests.length === 0 ? (
              <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>No requests match this filter</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    {['User', 'Type', 'Status', 'Submitted', 'Completed', 'Actions'].map(h => (
                      <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {requests.map(r => (
                    <tr key={r.request_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                      <td style={{ padding: '10px 16px' }}>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{r.username || r.user_id}</div>
                        <div style={{ fontSize: 11, color: '#64748b' }}>{r.email}</div>
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: `${REQUEST_TYPE_COLORS[r.request_type] ?? '#94a3b8'}22`, color: REQUEST_TYPE_COLORS[r.request_type] ?? '#94a3b8', border: `1px solid ${REQUEST_TYPE_COLORS[r.request_type] ?? '#94a3b8'}44` }}>
                          {r.request_type.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px' }}><StatusBadge status={r.status} /></td>
                      <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(r.submitted_at)}</td>
                      <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(r.completed_at)}</td>
                      <td style={{ padding: '10px 16px' }}>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {r.request_type === 'export' && (
                            <ActionBtn label="Export Data" onClick={() => exportUserData(r.user_id)} loading={busy === `export-${r.user_id}`} accent="#60a5fa" size="sm" />
                          )}
                          {r.status === 'pending' && (
                            <>
                              <ActionBtn label="Approve" onClick={() => setConfirm({ id: r.request_id, action: 'approve', label: 'Approve Request' })} loading={busy === r.request_id} accent="#22c55e" size="sm" />
                              <ActionBtn label="Reject"  onClick={() => setConfirm({ id: r.request_id, action: 'reject',  label: 'Reject Request'  })} loading={busy === r.request_id} accent="#f87171" size="sm" />
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </SectionCard>
        </>
      )}

      {/* ── TAB: Retention Policies ── */}
      {tab === 'policies' && (
        <SectionCard title="Data Retention Policies" icon="📅" accent="#a78bfa"
          subtitle="GDPR Art. 5(1)(e) — data minimisation and storage limitation. Edit retention days and save per row.">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {['Data Type', 'Retention (days)', 'Legal Basis', ''].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.data_type} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 16px', fontWeight: 600 }}>{p.data_type.replace(/_/g, ' ')}</td>
                  <td style={{ padding: '10px 16px' }}>
                    <input
                      type="number" min={1} max={3650}
                      value={policyEdits[p.data_type] ?? p.retention_days}
                      onChange={e => setPolicyEdits(prev => ({ ...prev, [p.data_type]: Number(e.target.value) }))}
                      style={{ width: 80, background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', padding: '4px 8px', fontSize: 13 }}
                    />
                    <span style={{ marginLeft: 8, color: '#475569', fontSize: 11 }}>
                      {(policyEdits[p.data_type] ?? p.retention_days) >= 365
                        ? `(${((policyEdits[p.data_type] ?? p.retention_days) / 365).toFixed(1)} yrs)`
                        : 'days'}
                    </span>
                  </td>
                  <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{p.legal_basis ?? '—'}</td>
                  <td style={{ padding: '10px 16px' }}>
                    <ActionBtn
                      label="Save"
                      onClick={() => savePolicy(p.data_type)}
                      loading={busy === `policy-${p.data_type}`}
                      disabled={(policyEdits[p.data_type] ?? p.retention_days) === p.retention_days}
                      accent="#a78bfa"
                      size="sm"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

      {/* ── TAB: Consent Log ── */}
      {tab === 'consent' && (
        <SectionCard title="Consent Log" icon="✅" accent="#22c55e"
          subtitle="GDPR Art. 7 — audit trail of all consent events"
          actions={
            <div style={{ display: 'flex', gap: 8 }}>
              <Input placeholder="Filter by user ID…" value={consentUserFilter} onChange={e => setConsentUserFilter(e.target.value)} style={{ width: 200 }} />
              <ActionBtn label="Load" onClick={() => {
                setConsentLoading(true);
                superadminApi.consentLog(consentUserFilter || undefined)
                  .then(r => setConsentLog(r.data.entries ?? r.data ?? []))
                  .catch(() => setConsentLog([]))
                  .finally(() => setConsentLoading(false));
              }} size="sm" loading={consentLoading} />
            </div>
          }>
          {consentLoading ? (
            <LoadingRows rows={4} />
          ) : consentLog.length === 0 ? (
            <EmptyState compact icon="📜" title="No consent events found" description="User consent records will appear here as users accept or withdraw consent." />
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['User', 'Event', 'Details', 'IP', 'Timestamp'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '8px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {consentLog.map((c, i) => (
                  <tr key={i} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '8px 16px', fontFamily: 'monospace', fontSize: 11, color: '#a78bfa' }}>{c.user_id}</td>
                    <td style={{ padding: '8px 16px', fontWeight: 600, color: '#f1f5f9' }}>{c.event}</td>
                    <td style={{ padding: '8px 16px', color: '#64748b', fontSize: 12 }}>{c.details}</td>
                    <td style={{ padding: '8px 16px', fontFamily: 'monospace', color: '#334155', fontSize: 11 }}>{c.ip ?? '—'}</td>
                    <td style={{ padding: '8px 16px', color: '#475569', fontSize: 12, whiteSpace: 'nowrap' }}>{fmtDate(c.timestamp)}</td>
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

export default GDPRSection;
