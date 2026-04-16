// superadmin/AuditTrailSection.tsx
// Immutable hash-chained audit trail (ImmutableAuditLog) — SEC/CFTC compliant
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, ActionBtn, Select, Input,
  KpiTile, ErrorState, LoadingRows, SAStyles,
} from './ui';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';

const LEVEL_COLORS: Record<string, string> = {
  DEBUG:      '#475569',
  INFO:       '#60a5fa',
  COMPLIANCE: '#a78bfa',
  CRITICAL:   '#f87171',
};

const CATEGORY_COLORS: Record<string, string> = {
  ORDER:    '#22c55e',
  RISK:     '#f87171',
  STRATEGY: '#60a5fa',
  GDPR:     '#a78bfa',
  AUTH:     '#fbbf24',
  ADMIN:    '#f97316',
  SYSTEM:   '#94a3b8',
};

interface AuditRecord {
  sequence: number;
  timestamp: string;
  level: string;
  category: string;
  actor: string;
  action: string;
  data: Record<string, unknown>;
  hash_chain: string;
  signature: string | null;
}

interface SystemAuditEntry {
  id: string;
  timestamp: string;
  user_id: string;
  username: string;
  action: string;
  resource: string;
  resource_id: string;
  ip: string;
  status: string;
  details: Record<string, unknown>;
}

const AuditTrailSection: React.FC = () => {
  const [records, setRecords]     = useState<AuditRecord[]>([]);
  const [total, setTotal]         = useState(0);
  const [page, setPage]           = useState(1);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [busy, setBusy]           = useState(false);
  const [msg, setMsg]             = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [search, setSearch]       = useState('');
  const [expanded, setExpanded]   = useState<number | null>(null);
  const [mainTab, setMainTab]     = useState<'compliance' | 'system'>('compliance');
  // System audit tab state
  const [sysEntries, setSysEntries]   = useState<SystemAuditEntry[]>([]);
  const [sysLoading, setSysLoading]   = useState(false);
  const [sysSearch, setSysSearch]     = useState('');
  const [sysPage, setSysPage]         = useState(1);
  const [sysTotal, setSysTotal]       = useState(0);

  const load = useCallback(async (p = 1) => {
    setLoading(true); setError('');
    try {
      const params: Record<string, string> = { page: String(p), limit: '100' };
      if (categoryFilter) params.category = categoryFilter;
      const res = await superadminApi.immutableAuditLog(params);
      setRecords(res.data.records ?? res.data);
      setTotal(res.data.total ?? 0);
      setPage(p);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load audit trail');
    } finally { setLoading(false); }
  }, [categoryFilter]);

  useEffect(() => { load(1); }, [load]);

  const exportTrail = async () => {
    setBusy(true); setMsg('');
    try {
      const res = await superadminApi.exportAuditTrail();
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url; a.download = `audit_trail_${new Date().toISOString().slice(0, 10)}.ndjson`; a.click();
      URL.revokeObjectURL(url);
      setMsg('Audit trail exported');
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Export failed');
    } finally { setBusy(false); }
  };

  const loadSysAudit = useCallback(async (p = 1) => {
    setSysLoading(true);
    try {
      const params: Record<string, string> = { page: String(p), limit: '50' };
      if (sysSearch) params.search = sysSearch;
      const res = await superadminApi.auditLog(params);
      setSysEntries(res.data.entries ?? res.data ?? []);
      setSysTotal(res.data.total ?? 0);
      setSysPage(p);
    } catch {
      setSysEntries([]);
    } finally { setSysLoading(false); }
  }, [sysSearch]);

  useEffect(() => {
    if (mainTab === 'system') loadSysAudit(1);
  }, [mainTab, loadSysAudit]);

  const exportSysAudit = async () => {
    setBusy(true); setMsg('');
    try {
      const res = await superadminApi.exportAudit();
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url; a.download = `system_audit_${new Date().toISOString().slice(0, 10)}.csv`; a.click();
      URL.revokeObjectURL(url);
      setMsg('System audit exported');
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Export failed');
    } finally { setBusy(false); }
  };

  if (loading && page === 1) return <LoadingRows rows={8} />;
  if (error)                  return <ErrorState message={error} onRetry={() => load(1)} />;

  const filtered = search
    ? records.filter(r =>
        r.action.toLowerCase().includes(search.toLowerCase()) ||
        r.actor.toLowerCase().includes(search.toLowerCase()) ||
        r.category.toLowerCase().includes(search.toLowerCase()))
    : records;

  const categories = Array.from(new Set(records.map(r => r.category))).sort();

  return (
    <>
      <SAStyles />

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
        <KpiTile label="Total Records" value={total.toLocaleString()} icon="📋" accent="#a78bfa" />
        <KpiTile label="Showing" value={filtered.length} icon="🔍" accent="#60a5fa" />
        <KpiTile label="Categories" value={categories.length} icon="🏷️" accent="#22c55e" />
        <KpiTile label="Hash-Chained" value="Yes" icon="🔗" accent="#4ade80" sub="Tamper-evident" />
      </div>

      {/* Main tab switcher */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {(['compliance', 'system'] as const).map(t => (
          <button key={t} onClick={() => setMainTab(t)} style={{ background: mainTab === t ? '#1e293b' : 'transparent', border: `1px solid ${mainTab === t ? '#475569' : '#1e293b'}`, borderRadius: 8, color: mainTab === t ? '#f8fafc' : '#64748b', padding: '7px 16px', fontSize: 13, cursor: 'pointer' }}>
            {{ compliance: '🔗 Compliance Audit Trail', system: '📋 System Audit Log' }[t]}
          </button>
        ))}
      </div>

      {mainTab === 'compliance' && (
        <>
      {/* Compliance notice */}
      <div style={{
        background: 'rgba(167,139,250,0.05)', border: '1px solid #4c1d95',
        borderRadius: 10, padding: '12px 16px', marginBottom: 16,
        display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#a78bfa',
      }}>
        <span style={{ fontSize: 16 }}>🔒</span>
        <span>
          <strong>Tamper-evident audit trail</strong> — SHA-256 hash-chained records meeting SEC Rule 17a-4 and CFTC requirements.
          Each record links to the previous via cryptographic hash. Export for regulatory submission.
        </span>
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <Input
            label=""
            placeholder="Search action, actor, category…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <Select
          label=""
          value={categoryFilter}
          onChange={e => setCategoryFilter(e.target.value)}
          options={[
            { value: '', label: 'All categories' },
            ...categories.map(c => ({ value: c, label: c })),
          ]}
          style={{ minWidth: 160 }}
        />
        <ActionBtn
          label="Export NDJSON"
          onClick={exportTrail}
          loading={busy}
          accent="#a78bfa"
          size="sm"
        />
      </div>

      <SectionCard title="Immutable Audit Trail" icon="🔗" accent="#a78bfa" noPad>
        {filtered.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>No audit records match this filter</div>
        ) : (
          <div>
            {filtered.map((r, i) => (
              <div key={r.sequence ?? i}>
                <div
                  onClick={() => setExpanded(expanded === r.sequence ? null : r.sequence)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 16px', cursor: 'pointer',
                    borderBottom: '1px solid #0f172a',
                    background: expanded === r.sequence ? '#0f1f35' : 'transparent',
                  }}
                >
                  {/* Sequence */}
                  <span style={{ fontSize: 10, color: '#334155', fontFamily: 'monospace', minWidth: 50, flexShrink: 0 }}>
                    #{r.sequence}
                  </span>
                  {/* Level */}
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                    background: `${LEVEL_COLORS[r.level] ?? '#94a3b8'}22`,
                    color: LEVEL_COLORS[r.level] ?? '#94a3b8',
                    minWidth: 80, textAlign: 'center', flexShrink: 0,
                  }}>
                    {r.level}
                  </span>
                  {/* Category */}
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                    background: `${CATEGORY_COLORS[r.category] ?? '#94a3b8'}22`,
                    color: CATEGORY_COLORS[r.category] ?? '#94a3b8',
                    minWidth: 70, textAlign: 'center', flexShrink: 0,
                  }}>
                    {r.category}
                  </span>
                  {/* Actor + Action */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: 12, color: '#94a3b8' }}>{r.actor}</span>
                    <span style={{ fontSize: 12, color: '#475569', margin: '0 6px' }}>→</span>
                    <span style={{ fontSize: 12, color: '#f1f5f9', fontWeight: 600 }}>{r.action}</span>
                  </div>
                  {/* Hash (truncated) */}
                  <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#334155', flexShrink: 0 }}>
                    {r.hash_chain?.slice(0, 12)}…
                  </span>
                  {/* Timestamp */}
                  <span style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>{fmtDate(r.timestamp)}</span>
                  <span style={{ fontSize: 10, color: '#334155' }}>{expanded === r.sequence ? '▲' : '▼'}</span>
                </div>
                {expanded === r.sequence && (
                  <div style={{ background: '#050d1a', padding: '12px 16px', borderBottom: '1px solid #0f172a' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 10 }}>
                      <div>
                        <div style={{ fontSize: 10, color: '#475569', fontWeight: 600, marginBottom: 4 }}>FULL HASH CHAIN</div>
                        <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#a78bfa', wordBreak: 'break-all' }}>{r.hash_chain}</div>
                      </div>
                      {r.signature && (
                        <div>
                          <div style={{ fontSize: 10, color: '#475569', fontWeight: 600, marginBottom: 4 }}>SIGNATURE</div>
                          <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#60a5fa', wordBreak: 'break-all' }}>{r.signature}</div>
                        </div>
                      )}
                    </div>
                    {Object.keys(r.data ?? {}).length > 0 && (
                      <div>
                        <div style={{ fontSize: 10, color: '#475569', fontWeight: 600, marginBottom: 4 }}>DATA PAYLOAD</div>
                        <pre style={{ fontSize: 11, color: '#94a3b8', background: '#0f172a', padding: '8px 10px', borderRadius: 6, overflow: 'auto', margin: 0 }}>
                          {JSON.stringify(r.data, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Pagination */}
      {total > 100 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 16, alignItems: 'center' }}>
          <ActionBtn label="← Prev" onClick={() => load(page - 1)} accent="#475569" size="sm" disabled={page <= 1} />
          <span style={{ fontSize: 13, color: '#64748b' }}>Page {page} of {Math.ceil(total / 100)}</span>
          <ActionBtn label="Next →" onClick={() => load(page + 1)} accent="#475569" size="sm" disabled={records.length < 100} />
        </div>
      )}
        </>
      )}

      {/* ── System Audit Log tab ── */}
      {mainTab === 'system' && (
        <>
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <Input label="" placeholder="Search user, action, resource…" value={sysSearch} onChange={e => setSysSearch(e.target.value)} />
            </div>
            <ActionBtn label="Search" onClick={() => loadSysAudit(1)} loading={sysLoading} size="sm" />
            <ActionBtn label="Export CSV" onClick={exportSysAudit} loading={busy} accent="#60a5fa" size="sm" />
          </div>

          <SectionCard title="System Audit Log" icon="📋" accent="#60a5fa"
            subtitle={`${sysTotal.toLocaleString()} total admin actions`} noPad>
            {sysLoading ? (
              <LoadingRows rows={6} />
            ) : sysEntries.length === 0 ? (
              <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>No system audit entries found.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #1e293b' }}>
                    {['User', 'Action', 'Resource', 'Resource ID', 'IP', 'Status', 'Timestamp'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sysEntries.map((e) => (
                    <tr key={e.id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                      <td style={{ padding: '8px 12px' }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: '#f1f5f9' }}>{e.username}</div>
                        <div style={{ fontSize: 10, fontFamily: 'monospace', color: '#475569' }}>{e.user_id}</div>
                      </td>
                      <td style={{ padding: '8px 12px', fontWeight: 600, color: '#a78bfa', fontSize: 12 }}>{e.action}</td>
                      <td style={{ padding: '8px 12px', fontSize: 11 }}>
                        <span style={{ background: '#1e293b', padding: '2px 6px', borderRadius: 3, color: '#94a3b8', fontSize: 10, fontWeight: 700, textTransform: 'uppercase' }}>{e.resource}</span>
                      </td>
                      <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 11, color: '#60a5fa' }}>{e.resource_id || '—'}</td>
                      <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 11, color: '#334155' }}>{e.ip}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: e.status === 'success' ? '#4ade80' : '#f87171' }}>{e.status}</span>
                      </td>
                      <td style={{ padding: '8px 12px', fontSize: 11, color: '#475569', whiteSpace: 'nowrap' }}>{fmtDate(e.timestamp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </SectionCard>

          {sysTotal > 50 && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 16, alignItems: 'center' }}>
              <ActionBtn label="← Prev" onClick={() => loadSysAudit(sysPage - 1)} accent="#475569" size="sm" disabled={sysPage <= 1} />
              <span style={{ fontSize: 13, color: '#64748b' }}>Page {sysPage} of {Math.ceil(sysTotal / 50)}</span>
              <ActionBtn label="Next →" onClick={() => loadSysAudit(sysPage + 1)} accent="#475569" size="sm" disabled={sysEntries.length < 50} />
            </div>
          )}
        </>
      )}
    </>
  );
};

export default AuditTrailSection;
