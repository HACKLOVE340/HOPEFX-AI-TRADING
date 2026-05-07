/**
 * AuditLog — browse, filter, and export the platform audit trail.
 *
 * Backend: GET /api/admin/audit-log?page=&limit=&user_id=&event_type=
 *          GET /api/admin/audit-log/export  (CSV download)
 *
 * Access: admin role only (enforced by AuthGuard + backend).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { adminApi } from '../hooks/useApi';
import { useStore } from '../store';
import { getWsBase } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { DataTable, type Column } from '../components/DataTable';
import { Badge, type BadgeVariant } from '../components/Badge';
import { Spinner } from '../components/Spinner';
import { ErrorBanner } from '../components/ErrorBanner';
import { EmptyState } from '../components/EmptyState';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuditEvent {
  event_id: string;
  user_id: string;
  event_type: string;
  detail: string;
  ip_address: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

type ViewMode = 'table' | 'timeline' | 'grouped';

interface AuditResponse {
  events: AuditEvent[];
  total: number;
  page: number;
  pages: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const EVENT_CATEGORIES: Record<string, BadgeVariant> = {
  login:        'success',
  'login.failed': 'danger',
  logout:       'neutral',
  'trade.placed': 'info',
  'trade.closed': 'info',
  'settings.changed': 'warning',
  'user.banned': 'danger',
  'withdrawal.requested': 'warning',
  startup:      'neutral',
  'signal.copied': 'info',
};

function eventVariant(type: string | undefined | null): BadgeVariant {
  if (!type || typeof type !== 'string') return 'neutral';
  for (const [key, variant] of Object.entries(EVENT_CATEGORIES)) {
    if (type.includes(key)) return variant;
  }
  return 'neutral';
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch {
    return iso;
  }
}

// ── Event category icons ──────────────────────────────────────────────────────

function eventIcon(type: string | undefined | null): string {
  if (!type || typeof type !== 'string') return '📋';
  if (type.includes('login.failed') || type.includes('ban'))  return '🚨';
  if (type.includes('login'))        return '🔑';
  if (type.includes('logout'))       return '🚪';
  if (type.includes('trade'))        return '📈';
  if (type.includes('withdrawal'))   return '💸';
  if (type.includes('settings'))     return '⚙️';
  if (type.includes('signal'))       return '📡';
  if (type.includes('startup'))      return '🚀';
  if (type.includes('2fa'))          return '🔐';
  if (type.includes('admin'))        return '🛡️';
  return '📋';
}

// ── Drill-down modal ──────────────────────────────────────────────────────────

const DrillDownModal: React.FC<{ event: AuditEvent; onClose: () => void }> = ({ event, onClose }) => {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: '#0d1421', border: '1px solid #334155', borderRadius: 14, padding: 28, maxWidth: 560, width: '100%', boxShadow: '0 24px 64px rgba(0,0,0,0.6)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 18, marginBottom: 4 }}>{eventIcon(event.event_type)}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9' }}>{event.event_type}</div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{fmtDate(event.created_at)}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20, lineHeight: 1 }}>✕</button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            { label: 'Event ID',   value: event.event_id,   mono: true },
            { label: 'User ID',    value: event.user_id,    mono: true },
            { label: 'IP Address', value: event.ip_address || '—', mono: true },
            { label: 'Detail',     value: event.detail,     mono: false },
          ].map(({ label, value, mono }) => (
            <div key={label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 13, color: '#e2e8f0', fontFamily: mono ? 'monospace' : 'inherit', wordBreak: 'break-all' }}>{value}</div>
            </div>
          ))}

          {event.metadata && Object.keys(event.metadata).length > 0 && (
            <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Metadata</div>
              <pre style={{ margin: 0, fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify(event.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <Link to={`/admin/users?id=${event.user_id}`}
            style={{ flex: 1, textAlign: 'center', padding: '8px 0', background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
            👤 View User
          </Link>
          <Link to={`/security?ip=${event.ip_address}`}
            style={{ flex: 1, textAlign: 'center', padding: '8px 0', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 7, color: '#f87171', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
            🛡️ Check IP
          </Link>
        </div>
      </div>
    </div>
  );
};

// ── Timeline view ─────────────────────────────────────────────────────────────

const TimelineView: React.FC<{ events: AuditEvent[]; onDrillDown: (e: AuditEvent) => void }> = ({ events, onDrillDown }) => (
  <div style={{ paddingLeft: 16, borderLeft: '2px solid #1e293b' }}>
    {events.map((ev, i) => (
      <div key={ev.event_id} style={{ position: 'relative', paddingLeft: 20, paddingBottom: 16 }}>
        {/* Connector dot */}
        <div style={{
          position: 'absolute', left: -9, top: 4,
          width: 14, height: 14, borderRadius: '50%',
          background: '#0d1421', border: `2px solid ${eventVariant(ev.event_type) === 'danger' ? '#ef4444' : eventVariant(ev.event_type) === 'success' ? '#22c55e' : eventVariant(ev.event_type) === 'warning' ? '#f59e0b' : '#3b82f6'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 7,
        }}>
          {i === 0 && <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#3b82f6' }} />}
        </div>
        <button
          onClick={() => onDrillDown(ev)}
          style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, background: '#0d1421', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px', transition: 'border-color 0.15s' }}
            onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.borderColor = '#334155'; }}
            onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.borderColor = '#1e293b'; }}>
            <span style={{ fontSize: 16, flexShrink: 0 }}>{eventIcon(ev.event_type)}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <Badge variant={eventVariant(ev.event_type)}>{ev.event_type}</Badge>
                <span style={{ fontSize: 10, color: '#475569', fontFamily: 'monospace', flexShrink: 0 }}>
                  {fmtDate(ev.created_at)}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.detail}</div>
              <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
                <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>{ev.user_id}</span>
                {ev.ip_address && <span style={{ marginLeft: 8 }}>· {ev.ip_address}</span>}
              </div>
            </div>
            <span style={{ color: '#334155', fontSize: 14, flexShrink: 0 }}>›</span>
          </div>
        </button>
      </div>
    ))}
  </div>
);

// ── Grouped view ──────────────────────────────────────────────────────────────

const GroupedView: React.FC<{ events: AuditEvent[]; onDrillDown: (e: AuditEvent) => void }> = ({ events, onDrillDown }) => {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  // Group by event_type
  const groups = events.reduce<Record<string, AuditEvent[]>>((acc, ev) => {
    const key = ev.event_type;
    if (!acc[key]) acc[key] = [];
    acc[key].push(ev);
    return acc;
  }, {});

  const toggle = (key: string) => setCollapsed(prev => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Object.entries(groups)
        .sort(([, a], [, b]) => b.length - a.length)
        .map(([type, evs]) => (
          <div key={type} style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, overflow: 'hidden' }}>
            <button
              onClick={() => toggle(type)}
              style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
              <span style={{ fontSize: 16 }}>{eventIcon(type)}</span>
              <Badge variant={eventVariant(type)}>{type}</Badge>
              <span style={{ fontSize: 12, color: '#64748b', marginLeft: 4 }}>{evs.length} event{evs.length !== 1 ? 's' : ''}</span>
              <span style={{ marginLeft: 'auto', color: '#475569', fontSize: 12 }}>{collapsed.has(type) ? '▸' : '▾'}</span>
            </button>
            {!collapsed.has(type) && (
              <div style={{ borderTop: '1px solid #1e293b' }}>
                {evs.slice(0, 10).map(ev => (
                  <button key={ev.event_id} onClick={() => onDrillDown(ev)}
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12, padding: '8px 16px', background: 'none', border: 'none', borderBottom: '1px solid #0f172a', cursor: 'pointer', textAlign: 'left' }}
                    onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = '#111827'; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'none'; }}>
                    <span style={{ fontSize: 10, color: '#475569', fontFamily: 'monospace', width: 140, flexShrink: 0 }}>{fmtDate(ev.created_at)}</span>
                    <span style={{ fontSize: 12, color: '#94a3b8', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.detail}</span>
                    <span style={{ fontSize: 11, color: '#60a5fa', fontFamily: 'monospace', flexShrink: 0 }}>{ev.user_id}</span>
                    <span style={{ color: '#334155', fontSize: 12 }}>›</span>
                  </button>
                ))}
                {evs.length > 10 && (
                  <div style={{ padding: '6px 16px', fontSize: 11, color: '#475569' }}>+{evs.length - 10} more — use filters to narrow down</div>
                )}
              </div>
            )}
          </div>
        ))}
    </div>
  );
};

// ── Columns ───────────────────────────────────────────────────────────────────

const COLUMNS: Column<AuditEvent>[] = [
  {
    key: 'created_at',
    header: 'Timestamp',
    width: '180px',
    sortKey: 'created_at',
    sortable: true,
    render: (row) => (
      <span style={{ color: '#94a3b8', fontFamily: 'monospace', fontSize: 12 }}>
        {fmtDate(row.created_at)}
      </span>
    ),
  },
  {
    key: 'user_id',
    header: 'User',
    width: '130px',
    sortKey: 'user_id',
    sortable: true,
    render: (row) => (
      <span style={{ color: '#60a5fa', fontFamily: 'monospace', fontSize: 12 }}>
        {row.user_id}
      </span>
    ),
  },
  {
    key: 'event_type',
    header: 'Event',
    width: '160px',
    sortKey: 'event_type',
    sortable: true,
    render: (row) => (
      <Badge variant={eventVariant(row.event_type)}>
        {row.event_type ?? '—'}
      </Badge>
    ),
  },
  {
    key: 'detail',
    header: 'Detail',
    render: (row) => (
      <span style={{ color: '#cbd5e1', fontSize: 13 }}>{row.detail}</span>
    ),
  },
  {
    key: 'ip_address',
    header: 'IP',
    width: '130px',
    render: (row) => (
      <span style={{ color: '#64748b', fontFamily: 'monospace', fontSize: 12 }}>
        {row.ip_address || '—'}
      </span>
    ),
  },
];

// ── Page ──────────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

const AuditLog: React.FC = () => {
  const [events, setEvents]     = useState<AuditEvent[]>([]);
  const [total, setTotal]       = useState(0);
  const [page, setPage]         = useState(1);
  const [pages, setPages]       = useState(1);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [filterUser, setFilterUser]   = useState('');
  const [filterType, setFilterType]   = useState('');
  const [exporting, setExporting]     = useState(false);
  const [liveCount, setLiveCount]     = useState(0);
  const [viewMode, setViewMode]       = useState<ViewMode>('table');
  const [drillEvent, setDrillEvent]   = useState<AuditEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const token = useStore(s => s.token);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchAudit = useCallback(async (pg: number, uid: string, etype: string) => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, unknown> = { page: pg, limit: PAGE_SIZE };
      if (uid.trim())   params.user_id    = uid.trim();
      if (etype.trim()) params.event_type = etype.trim();

      const res = await adminApi.auditLog(params);
      if (!mountedRef.current) return;
      const d = res.data as AuditResponse;
      setEvents(Array.isArray(d.events) ? d.events : []);
      setTotal(typeof d.total === 'number' ? d.total : 0);
      setPage(typeof d.page === 'number' ? d.page : pg);
      setPages(typeof d.pages === 'number' ? d.pages : 1);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      const msg = e instanceof Error ? e.message : 'Failed to load audit log';
      setError(msg);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    void fetchAudit(1, filterUser, filterType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Real-time WS event injection — subscribe to /ws/audit-events
  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${getWsBase()}/ws/audit-events?token=${token}`);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as { type?: string; event?: AuditEvent };
          if (msg.type === 'audit_event' && msg.event) {
            // Prepend new event to the top of the list (most recent first)
            setEvents(prev => [msg.event!, ...prev].slice(0, PAGE_SIZE));
            setTotal(prev => prev + 1);
            setLiveCount(prev => prev + 1);
          }
        } catch { /* ignore malformed frames */ }
      };
      ws.onerror = () => { /* WS unavailable — polling only */ };
    } catch { /* WS unavailable */ }
    return () => { ws?.close(); wsRef.current = null; };
  }, [token]);

  const handleSearch = () => {
    void fetchAudit(1, filterUser, filterType);
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await adminApi.auditExport();
      const url = URL.createObjectURL(res.data as Blob);
      const a   = document.createElement('a');
      a.href    = url;
      a.download = `audit_log_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div style={s.page}>
      <PageHeader
        title="Audit Log"
        subtitle={`${total.toLocaleString()} events total${liveCount > 0 ? ` · ${liveCount} live` : ''}`}
        breadcrumbs={[
          { label: 'Home',        href: '/home' },
          { label: 'Admin Panel', href: '/admin' },
          { label: 'Audit Log' },
        ]}
        badge={
          liveCount > 0
            ? <Badge variant="success" style={{ fontSize: 11 }}>● {liveCount} Live</Badge>
            : undefined
        }
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {/* View mode switcher */}
            <div style={{ display: 'flex', background: '#0f172a', border: '1px solid #334155', borderRadius: 6, overflow: 'hidden' }}>
              {(['table', 'timeline', 'grouped'] as ViewMode[]).map(m => (
                <button key={m} onClick={() => setViewMode(m)}
                  style={{ padding: '5px 12px', background: viewMode === m ? '#1e3a5f' : 'transparent', border: 'none', color: viewMode === m ? '#60a5fa' : '#64748b', cursor: 'pointer', fontSize: 11, fontWeight: 600, fontFamily: 'inherit', textTransform: 'capitalize' }}>
                  {m === 'table' ? '⊞ Table' : m === 'timeline' ? '⏱ Timeline' : '⊟ Grouped'}
                </button>
              ))}
            </div>
            <button
              onClick={() => void fetchAudit(1, filterUser, filterType)}
              disabled={loading}
              style={{ ...s.exportBtn, color: '#60a5fa', borderColor: 'rgba(59,130,246,0.35)' }}
            >
              {loading ? <Spinner size="sm" /> : '↻'} Refresh
            </button>
            <button
              onClick={handleExport}
              disabled={exporting}
              style={s.exportBtn}
            >
              {exporting ? <Spinner size="sm" /> : '⬇'} Export CSV
            </button>
          </div>
        }
      />

      {/* Filters */}
      <div style={s.filters}>
        <input
          type="text"
          placeholder="Filter by user ID…"
          value={filterUser}
          onChange={(e) => setFilterUser(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          style={s.input}
        />
        <input
          type="text"
          placeholder="Filter by event type…"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          style={s.input}
        />
        <button onClick={handleSearch} style={s.searchBtn}>
          Search
        </button>
        <button
          onClick={() => {
            setFilterUser('');
            setFilterType('');
            void fetchAudit(1, '', '');
          }}
          style={s.clearBtn}
        >
          Clear
        </button>
      </div>

      {error && (
        <ErrorBanner
          message={error}
          onDismiss={() => setError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {!loading && events.length === 0 && !error ? (
        <EmptyState
          icon="🔍"
          title="No events match your filters"
          description="Try adjusting your filters or check back after some activity."
        />
      ) : (
        <>
          {viewMode === 'table' && (
            <DataTable<AuditEvent>
              columns={COLUMNS.map(col => ({
                ...col,
                render: col.key === 'detail'
                  ? (row: AuditEvent) => (
                      <button onClick={() => setDrillEvent(row)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0, color: '#cbd5e1', fontSize: 13 }}>
                        {row.detail} <span style={{ color: '#334155' }}>›</span>
                      </button>
                    )
                  : col.render,
              }))}
              data={events}
              rowKey={(r) => r.event_id}
              loading={loading}
              pageSize={PAGE_SIZE}
              emptyMessage="No events match your filters"
            />
          )}

          {viewMode === 'timeline' && !loading && (
            <TimelineView events={events} onDrillDown={setDrillEvent} />
          )}

          {viewMode === 'grouped' && !loading && (
            <GroupedView events={events} onDrillDown={setDrillEvent} />
          )}

          {/* Manual pagination (server-side) */}
          {pages > 1 && !loading && (
            <div style={s.pagination}>
              <span style={{ color: '#64748b', fontSize: 12 }}>
                Page {page} of {pages}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  disabled={page <= 1}
                  onClick={() => void fetchAudit(page - 1, filterUser, filterType)}
                  style={s.pageBtn}
                >
                  ‹ Prev
                </button>
                <button
                  disabled={page >= pages}
                  onClick={() => void fetchAudit(page + 1, filterUser, filterType)}
                  style={s.pageBtn}
                >
                  Next ›
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Drill-down modal */}
      {drillEvent && <DrillDownModal event={drillEvent} onClose={() => setDrillEvent(null)} />}

      {/* Cross-links */}
      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 20, marginTop: 32 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Related
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {[
            { icon: '🔧', label: 'Admin Panel',          desc: 'Platform overview & KPIs',         to: '/admin' },
            { icon: '🛡️', label: 'Security Dashboard',   desc: 'Threats, IPs, lockdown controls',  to: '/security' },
            { icon: '🩺', label: 'Auto-Heal',            desc: 'Self-healing & fix approvals',     to: '/auto-heal' },
            { icon: '⚡', label: 'Super Admin',          desc: 'Master control panel',             to: '/superadmin' },
          ].map(({ icon, label, desc, to }) => (
            <Link
              key={to}
              to={to}
              style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '12px 16px', textDecoration: 'none' }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155'; (e.currentTarget as HTMLAnchorElement).style.background = '#111827'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1e293b'; (e.currentTarget as HTMLAnchorElement).style.background = '#0d1421'; }}
            >
              <span style={{ fontSize: 20, flexShrink: 0 }}>{icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{label}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{desc}</div>
              </div>
              <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 16 }}>›</span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    padding: '24px 28px',
    maxWidth: 1200,
  },
  filters: {
    display: 'flex',
    gap: 8,
    marginBottom: 16,
    flexWrap: 'wrap',
  },
  input: {
    background: 'var(--surface, #1e293b)',
    border: '1px solid var(--border, #334155)',
    borderRadius: 6,
    color: 'var(--text, #f1f5f9)',
    fontSize: 13,
    padding: '7px 12px',
    width: 220,
    outline: 'none',
  },
  searchBtn: {
    background: '#3b82f6',
    border: 'none',
    borderRadius: 6,
    color: '#fff',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
    padding: '7px 16px',
  },
  clearBtn: {
    background: 'transparent',
    border: '1px solid var(--border, #334155)',
    borderRadius: 6,
    color: 'var(--text-muted, #94a3b8)',
    cursor: 'pointer',
    fontSize: 13,
    padding: '7px 12px',
  },
  exportBtn: {
    alignItems: 'center',
    background: 'transparent',
    border: '1px solid var(--border, #334155)',
    borderRadius: 6,
    color: 'var(--text-muted, #94a3b8)',
    cursor: 'pointer',
    display: 'flex',
    fontSize: 13,
    gap: 6,
    padding: '7px 14px',
  },
  pagination: {
    alignItems: 'center',
    display: 'flex',
    gap: 12,
    justifyContent: 'flex-end',
    marginTop: 12,
  },
  pageBtn: {
    background: 'transparent',
    border: '1px solid var(--border, #334155)',
    borderRadius: 6,
    color: '#94a3b8',
    cursor: 'pointer',
    fontSize: 12,
    padding: '5px 12px',
  },
};

export default AuditLog;
