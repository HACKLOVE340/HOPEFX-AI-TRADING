// superadmin/AuditTrailSection.tsx
// Immutable hash-chained audit trail (ImmutableAuditLog) — SEC/CFTC compliant
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { EmptyState } from '../../components/EmptyState';

import {
  SectionCard, ActionBtn, Select, Input,
  KpiTile, ErrorState, LoadingRows,
} from './ui';
import { extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';
import { ClipboardList, Link2, Lock, Search, Tag } from 'lucide-react';
const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';

const LEVEL_COLORS: Record<string, string> = {
  DEBUG:      '#475569',
  INFO:       'var(--link)',
  COMPLIANCE: 'var(--ai-model)',
  CRITICAL:   'var(--loss)',
};

const CATEGORY_COLORS: Record<string, string> = {
  ORDER:    '#22c55e',
  RISK:     'var(--loss)',
  STRATEGY: 'var(--link)',
  GDPR:     'var(--ai-model)',
  AUTH:     'var(--warn)',
  ADMIN:    '#f97316',
  SYSTEM:   'var(--text-dim)',
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

/**
 * The shape GET /api/superadmin/audit actually returns.
 *
 * This interface previously described a different API entirely — `id`,
 * `timestamp`, `username`, `resource`, `resource_id`, `ip`, `status`, `details`
 * — none of which the endpoint has ever sent. TypeScript did not catch it
 * because the response is read from `res.data` as `any`, so every field
 * resolved to `undefined` at runtime and the table rendered blank cells under
 * a heading that claimed "15 total admin actions".
 *
 * `resource_id` and `status` are gone rather than renamed: `AuditLogEntry` has
 * no column for either, so any column bound to them can only ever be empty.
 */
interface SystemAuditEntry {
  event_id: string;
  created_at: string;
  /** user_id or system component — NOT NULL on AuditLogEntry. */
  actor: string;
  user_id: string | null;
  /** NOT NULL on AuditLogEntry; `event_type` is the nullable secondary label. */
  action: string;
  event_type: string | null;
  /** ORDER | RISK | KYC | SYSTEM */
  category: string;
  /** INFO | COMPLIANCE | CRITICAL */
  level: string;
  ip_address: string | null;
  detail: string;
}

const AuditTrailSection: React.FC = () => {
  const [records, setRecords]     = useState<AuditRecord[]>([]);
  const [total, setTotal]         = useState(0);
  const [page, setPage]           = useState(1);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [busy, setBusy]           = useState(false);
  const [msg, setMsg]             = useState('');
  const [msgOk, setMsgOk] = useState(true);
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

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async (p = 1) => {
    setLoading(true); setError('');
    try {
      const params: Record<string, string> = { page: String(p), limit: '100' };
      if (categoryFilter) params.category = categoryFilter;
      const res = await superadminApi.immutableAuditLog(params);
      if (!mountedRef.current) return;
      const raw = res.data.records ?? res.data.events ?? res.data.entries ?? res.data;
      setRecords(Array.isArray(raw) ? raw : []);
      setTotal(res.data.total ?? 0);
      setPage(p);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load audit trail'));
    } finally { if (mountedRef.current) setLoading(false); }
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
      setMsgOk(true);
      setMsg('Audit trail exported');
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Export failed'));
    } finally { setBusy(false); }
  };

  const loadSysAudit = useCallback(async (p = 1) => {
    setSysLoading(true);
    try {
      const params: Record<string, string> = { page: String(p), limit: '50' };
      if (sysSearch) params.search = sysSearch;
      const res = await superadminApi.auditLog(params);
      if (!mountedRef.current) return;
      const sysRaw = res.data.entries ?? res.data.events ?? res.data;
      setSysEntries(Array.isArray(sysRaw) ? sysRaw : []);
      setSysTotal(res.data.total ?? 0);
      setSysPage(p);
    } catch {
      if (!mountedRef.current) return;
      setSysEntries([]);
    } finally { if (mountedRef.current) setSysLoading(false); }
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
      setMsgOk(true);
      setMsg('System audit exported');
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Export failed'));
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


      <ActionBanner message={msg} ok={msgOk} onDismiss={() => setMsg('')} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14, marginBottom: 20 }}>
        <KpiTile label="Total Records" value={total.toLocaleString()} icon={<ClipboardList size={18} aria-hidden />} accent="#a78bfa" />
        <KpiTile label="Showing" value={filtered.length} icon={<Search size={18} aria-hidden />} accent="#60a5fa" />
        <KpiTile label="Categories" value={categories.length} icon={<Tag size={18} aria-hidden />} accent="#22c55e" />
        <KpiTile label="Hash-Chained" value="Yes" icon={<Link2 size={18} aria-hidden />} accent="#4ade80" sub="Tamper-evident" />
      </div>

      {/* Main tab switcher */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {(['compliance', 'system'] as const).map(t => (
          <button key={t} onClick={() => setMainTab(t)} style={{ background: mainTab === t ? 'var(--raised)' : 'transparent', border: `1px solid ${mainTab === t ? '#475569' : '#1e293b'}`, borderRadius: 8, color: mainTab === t ? 'var(--text-strong)' : 'var(--text-muted)', padding: '7px 16px', fontSize: 'var(--fs-body)', cursor: 'pointer' }}>
            {{ compliance: <><Link2 size="1em" aria-hidden="true" /> Compliance Audit Trail</>, system: <><ClipboardList size="1em" aria-hidden="true" /> System Audit Log</> }[t]}
          </button>
        ))}
      </div>

      {mainTab === 'compliance' && (
        <>
      {/* Compliance notice */}
      <div style={{
        background: 'rgba(167,139,250,0.05)', border: '1px solid #4c1d95',
        borderRadius: 10, padding: '12px 16px', marginBottom: 16,
        display: 'flex', alignItems: 'center', gap: 10, fontSize: 'var(--fs-body)', color: 'var(--ai-model)',
      }}>
        <span style={{ fontSize: 16 }}><Lock size="1em" aria-hidden /></span>
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

      <SectionCard title="Immutable Audit Trail" icon={<Link2 size={18} aria-hidden />} accent="#a78bfa" noPad>
        {filtered.length === 0 ? (
          <div style={{ color: 'var(--text-faint)', fontSize: 'var(--fs-body)', textAlign: 'center', padding: 32 }}>No audit records match this filter</div>
        ) : (
          <div>
            {filtered.map((r, i) => (
              <div key={r.sequence ?? i}>
                <div
                  onClick={() => setExpanded(expanded === r.sequence ? null : r.sequence)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 16px', cursor: 'pointer',
                    borderBottom: '1px solid var(--hairline)',
                    background: expanded === r.sequence ? '#0f1f35' : 'transparent',
                  }}
                >
                  {/* Sequence */}
                  <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)', fontFamily: 'monospace', minWidth: 50, flexShrink: 0 }}>
                    #{r.sequence}
                  </span>
                  {/* Level */}
                  <span style={{
                    fontSize: 'var(--fs-micro)', fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                    background: `${LEVEL_COLORS[r.level] ?? 'var(--text-dim)'}22`,
                    color: LEVEL_COLORS[r.level] ?? 'var(--text-dim)',
                    minWidth: 80, textAlign: 'center', flexShrink: 0,
                  }}>
                    {r.level}
                  </span>
                  {/* Category */}
                  <span style={{
                    fontSize: 'var(--fs-micro)', fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                    background: `${CATEGORY_COLORS[r.category] ?? 'var(--text-dim)'}22`,
                    color: CATEGORY_COLORS[r.category] ?? 'var(--text-dim)',
                    minWidth: 70, textAlign: 'center', flexShrink: 0,
                  }}>
                    {r.category}
                  </span>
                  {/* Actor + Action */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)' }}>{r.actor}</span>
                    <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-faint)', margin: '0 6px' }}>→</span>
                    <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-strong)', fontWeight: 600 }}>{r.action}</span>
                  </div>
                  {/* Hash (truncated) */}
                  <span style={{ fontSize: 'var(--fs-micro)', fontFamily: 'monospace', color: 'var(--text-faint)', flexShrink: 0 }}>
                    {r.hash_chain?.slice(0, 12)}…
                  </span>
                  {/* Timestamp */}
                  <span style={{ fontSize: 'var(--fs-label)', color: 'var(--text-faint)', flexShrink: 0 }}>{fmtDate(r.timestamp)}</span>
                  <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)' }}>{expanded === r.sequence ? '▲' : '▼'}</span>
                </div>
                {expanded === r.sequence && (
                  <div style={{ background: '#050d1a', padding: '12px 16px', borderBottom: '1px solid var(--hairline)' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 10 }}>
                      <div>
                        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)', fontWeight: 600, marginBottom: 4 }}>FULL HASH CHAIN</div>
                        <div style={{ fontSize: 'var(--fs-label)', fontFamily: 'monospace', color: 'var(--ai-model)', wordBreak: 'break-all' }}>{r.hash_chain}</div>
                      </div>
                      {r.signature && (
                        <div>
                          <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)', fontWeight: 600, marginBottom: 4 }}>SIGNATURE</div>
                          <div style={{ fontSize: 'var(--fs-label)', fontFamily: 'monospace', color: 'var(--link)', wordBreak: 'break-all' }}>{r.signature}</div>
                        </div>
                      )}
                    </div>
                    {Object.keys(r.data ?? {}).length > 0 && (
                      <div>
                        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)', fontWeight: 600, marginBottom: 4 }}>DATA PAYLOAD</div>
                        <pre style={{ fontSize: 'var(--fs-label)', color: 'var(--text-dim)', background: 'var(--surface)', padding: '8px 10px', borderRadius: 6, overflow: 'auto', margin: 0 }}>
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
          <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-muted)' }}>Page {page} of {Math.ceil(total / 100)}</span>
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

          <SectionCard title="System Audit Log" icon={<ClipboardList size={18} aria-hidden />} accent="#60a5fa"
            subtitle={`${sysTotal.toLocaleString()} total admin actions`} noPad>
            {sysLoading ? (
              <LoadingRows rows={6} />
            ) : sysEntries.length === 0 ? (
              <EmptyState compact icon={ClipboardList} title="No audit entries found" description="System audit events will appear here as platform actions are recorded." links={[{ label: 'Audit Log', href: '/audit', icon: <Search size={16} aria-hidden /> }]} />
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--fs-body)'}}>
                <thead>
                  {/* 'Resource ID' is gone: AuditLogEntry has no such column, so it
                      rendered '—' on every row forever. Every other header here read a
                      field the API never sent — username, action, resource, ip, status —
                      while the API sent event_type, ip_address, created_at and (now)
                      actor, action, category, level. The result was a page reporting
                      "15 total admin actions" above 15 rows showing a bare UUID and
                      nothing else: no action, no resource, no time. The records were
                      complete the whole time; only the read was wrong. */}
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['User', 'Action', 'Category', 'IP', 'Level', 'Timestamp'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 'var(--fs-label)', fontWeight: 600, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sysEntries.map((e) => (
                    <tr key={e.event_id} className="sa-row" style={{ borderBottom: '1px solid var(--hairline)' }}>
                      <td style={{ padding: '8px 12px' }}>
                        <div style={{ fontSize: 'var(--fs-body)', fontWeight: 600, color: 'var(--text-strong)' }}>{e.actor || '—'}</div>
                        <div style={{ fontSize: 'var(--fs-micro)', fontFamily: 'monospace', color: 'var(--text-faint)' }}>{e.user_id}</div>
                      </td>
                      <td style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--ai-model)', fontSize: 'var(--fs-body)'}}>
                        <div>{e.action || e.event_type || '—'}</div>
                        {e.detail && <div style={{ fontSize: 'var(--fs-micro)', fontWeight: 400, color: 'var(--text-muted)' }}>{e.detail}</div>}
                      </td>
                      <td style={{ padding: '8px 12px', fontSize: 'var(--fs-label)'}}>
                        {e.category
                          ? <span style={{ background: 'var(--raised)', padding: '2px 6px', borderRadius: 3, color: 'var(--text-dim)', fontSize: 'var(--fs-micro)', fontWeight: 700, textTransform: 'uppercase' }}>{e.category}</span>
                          : <span style={{ color: 'var(--text-faint)' }}>—</span>}
                      </td>
                      <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 'var(--fs-label)', color: 'var(--text-faint)' }}>{e.ip_address || '—'}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <span style={{ fontSize: 'var(--fs-label)', fontWeight: 700, color: e.level === 'CRITICAL' ? 'var(--loss)' : e.level === 'COMPLIANCE' ? 'var(--warn)' : 'var(--gain)' }}>{e.level || '—'}</span>
                      </td>
                      <td style={{ padding: '8px 12px', fontSize: 'var(--fs-label)', color: 'var(--text-faint)', whiteSpace: 'nowrap' }}>{fmtDate(e.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </SectionCard>

          {sysTotal > 50 && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 16, alignItems: 'center' }}>
              <ActionBtn label="← Prev" onClick={() => loadSysAudit(sysPage - 1)} accent="#475569" size="sm" disabled={sysPage <= 1} />
              <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-muted)' }}>Page {sysPage} of {Math.ceil(sysTotal / 50)}</span>
              <ActionBtn label="Next →" onClick={() => loadSysAudit(sysPage + 1)} accent="#475569" size="sm" disabled={sysEntries.length < 50} />
            </div>
          )}
        </>
      )}
    </>
  );
};

export default AuditTrailSection;
