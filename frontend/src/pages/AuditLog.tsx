/**
 * AuditLog — browse, filter, and export the platform audit trail.
 *
 * Backend: GET /api/admin/audit-log?page=&limit=&user_id=&event_type=
 *          GET /api/admin/audit-log/export  (CSV download)
 *
 * Access: admin role only (enforced by AuthGuard + backend).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminApi } from '../hooks/useApi';
import { useStore } from '../store';
import { getWsBase, extractApiError } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { DataTable, type Column } from '../components/DataTable';
import { Badge, type BadgeVariant } from '../components/Badge';
import { Spinner } from '../components/Spinner';
import { ErrorBanner } from '../components/ErrorBanner';
import { EmptyState } from '../components/EmptyState';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuditEvent {
  event_id:   string;
  user_id:    string | null;
  event_type: string | null;
  detail:     string | null;
  ip_address: string | null;
  created_at: string | null;
}

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

function eventVariant(type: string | null | undefined): BadgeVariant {
  if (!type) return 'neutral';
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
        {row.created_at ? fmtDate(row.created_at) : '—'}
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
        {row.user_id || '—'}
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
        {row.event_type || 'unknown'}
      </Badge>
    ),
  },
  {
    key: 'detail',
    header: 'Detail',
    render: (row) => (
      <span style={{ color: '#cbd5e1', fontSize: 13 }}>{row.detail || '—'}</span>
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
  const navigate = useNavigate();
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
      setEvents(d.events ?? []);
      setTotal(d.total ?? 0);
      setPage(d.page ?? pg);
      setPages(d.pages ?? 1);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      const msg = extractApiError(e, 'Failed to load audit log');
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
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button onClick={() => navigate('/security')}
              style={{ padding: '6px 13px', background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.35)', borderRadius: 7, color: '#f87171', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              🛡 Security
            </button>
            <button onClick={() => navigate('/auto-heal')}
              style={{ padding: '6px 13px', background: 'rgba(34,197,94,0.12)', border: '1px solid rgba(34,197,94,0.35)', borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              🔧 Auto-Heal
            </button>
            <button
              onClick={handleExport}
              disabled={exporting}
              style={s.exportBtn}
            >
              {exporting ? <Spinner size="sm" /> : '⬇ Export CSV'}
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
        <DataTable<AuditEvent>
          columns={COLUMNS}
          data={events}
          rowKey={(r) => r.event_id}
          loading={loading}
          pageSize={PAGE_SIZE}
          emptyMessage="No events match your filters"
        />
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
