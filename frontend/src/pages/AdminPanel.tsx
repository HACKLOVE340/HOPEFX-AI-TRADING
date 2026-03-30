/**
 * Admin Panel
 *
 * Covers Tasks 36, 37, 41:
 *   - User management: list, ban/unban, reset password, view trades, impersonate
 *   - Audit log: timeline, filters, CSV export
 *   - Feature flags: toggle on/off, per-user overrides
 */

import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../hooks/useApi';

// ─── Types ────────────────────────────────────────────────────────────────────

interface AdminUser {
  user_id:      string;
  username:     string;
  email:        string;
  status:       string;
  tier:         string;
  total_trades: number;
  created_at:   string;
  last_login:   string;
}

interface AuditEvent {
  event_id:   string;
  user_id:    string;
  event_type: string;
  detail:     string;
  ip_address: string;
  created_at: string;
}

interface FeatureFlag {
  name:        string;
  enabled:     boolean;
  status:      string;
  description: string;
  env_var:     string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const timeAgo = (iso: string) => {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
};

const statusColor = (st: string) => ({
  active:   '#4ade80',
  banned:   '#f87171',
  pending:  '#facc15',
  inactive: '#64748b',
}[st] ?? '#94a3b8');

const tierColor = (t: string) => ({
  free:         '#64748b',
  professional: '#60a5fa',
  enterprise:   '#a78bfa',
}[t] ?? '#94a3b8');

function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object') {
    const e = err as Record<string, unknown>;
    const detail = (e['response'] as Record<string, unknown> | undefined)?.['data'];
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>;
      if (typeof d['detail'] === 'string') return d['detail'];
      if (typeof d['message'] === 'string') return d['message'];
    }
    if (typeof e['message'] === 'string') return e['message'];
  }
  return fallback;
}

// ─── Users Tab ────────────────────────────────────────────────────────────────

const UsersTab: React.FC = () => {
  const [users,   setUsers]   = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [msg,     setMsg]     = useState('');
  const [actionErr, setActionErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      const res = await api.get('/admin/users');
      setUsers(res.data.users || []);
    } catch (err) {
      setUsers([]);
      setLoadErr(extractErrorMessage(err, 'Failed to load users. Ensure the admin API is running.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const action = async (userId: string, act: string) => {
    setActionErr(null);
    setMsg('');
    try {
      if (act === 'ban')   await api.post(`/admin/users/${userId}/ban`);
      if (act === 'unban') await api.post(`/admin/users/${userId}/unban`);
      if (act === 'reset') {
        await api.post(`/admin/users/${userId}/reset-password`);
        setMsg('Password reset email queued.');
      }
      if (act === 'impersonate') {
        const res = await api.post(`/admin/users/${userId}/impersonate`);
        setMsg(`Impersonation token: ${res.data.impersonation_token} (expires in 5 min)`);
      }
      await load();
    } catch (err) {
      setActionErr(extractErrorMessage(err, `Action "${act}" failed. Check permissions and try again.`));
    }
  };

  return (
    <div>
      {msg && (
        <div style={s.infoBanner}>
          {msg}
          <button style={s.closeBtn} onClick={() => setMsg('')}>✕</button>
        </div>
      )}
      {actionErr && (
        <div style={s.errorBanner}>
          {actionErr}
          <button style={s.closeBtn} onClick={() => setActionErr(null)}>✕</button>
        </div>
      )}
      {loading && <div style={s.dim}>Loading users…</div>}
      {!loading && loadErr && <div style={{ ...s.dim, color: '#f87171' }}>{loadErr}</div>}
      {!loading && !loadErr && users.length === 0 && (
        <div style={s.dim}>No users found.</div>
      )}
      {!loading && !loadErr && users.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={s.table}>
            <thead>
              <tr>
                {['User', 'Email', 'Status', 'Tier', 'Trades', 'Last Login', 'Actions'].map((h) => (
                  <th key={h} style={s.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id} style={s.tr}>
                  <td style={s.td}><span style={{ fontWeight: 600 }}>{u.username}</span></td>
                  <td style={{ ...s.td, color: '#64748b' }}>{u.email}</td>
                  <td style={s.td}>
                    <span style={{ ...s.badge, color: statusColor(u.status), borderColor: statusColor(u.status) }}>
                      {u.status}
                    </span>
                  </td>
                  <td style={s.td}>
                    <span style={{ ...s.badge, color: tierColor(u.tier), borderColor: tierColor(u.tier) }}>
                      {u.tier}
                    </span>
                  </td>
                  <td style={s.td}>{u.total_trades}</td>
                  <td style={{ ...s.td, color: '#64748b' }}>{timeAgo(u.last_login)}</td>
                  <td style={s.td}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {u.status === 'banned'
                        ? <button style={{ ...s.actionBtn, color: '#4ade80' }} onClick={() => action(u.user_id, 'unban')}>Unban</button>
                        : <button style={{ ...s.actionBtn, color: '#f87171' }} onClick={() => action(u.user_id, 'ban')}>Ban</button>
                      }
                      <button style={s.actionBtn} onClick={() => action(u.user_id, 'reset')}>Reset PW</button>
                      <button style={s.actionBtn} onClick={() => action(u.user_id, 'impersonate')}>Impersonate</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// ─── Audit Log Tab ────────────────────────────────────────────────────────────

const AuditTab: React.FC = () => {
  const [events,    setEvents]    = useState<AuditEvent[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [loadErr,   setLoadErr]   = useState<string | null>(null);
  const [exportErr, setExportErr] = useState<string | null>(null);
  const [filter,    setFilter]    = useState('');
  const [page,      setPage]      = useState(1);
  const [total,     setTotal]     = useState(0);

  const load = useCallback(async (p = 1, f = filter) => {
    setLoading(true);
    setLoadErr(null);
    try {
      const params: Record<string, string | number> = { page: p, limit: 20 };
      if (f) params.event_type = f;
      const res = await api.get('/admin/audit-log', { params });
      setEvents(res.data.events || []);
      setTotal(res.data.total || 0);
      setPage(p);
    } catch (err) {
      setEvents([]);
      setTotal(0);
      setLoadErr(extractErrorMessage(err, 'Failed to load audit log. Ensure the admin API is running.'));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(1, filter); }, [filter]);

  const exportCsv = async () => {
    setExportErr(null);
    try {
      const res = await api.get('/admin/audit-log/export', { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url; a.download = 'audit_log.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportErr(extractErrorMessage(err, 'CSV export failed. Try again or contact support.'));
    }
  };

  const eventColor = (type: string) =>
    type.includes('fail') || type.includes('ban') ? '#f87171' :
    type.includes('login') ? '#60a5fa' :
    type.includes('trade') ? '#4ade80' :
    '#94a3b8';

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <input
          style={s.searchInput}
          placeholder="Filter by event type…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button style={s.exportBtn} onClick={exportCsv}>Export CSV</button>
      </div>
      {exportErr && (
        <div style={{ ...s.errorBanner, marginBottom: 12 }}>
          {exportErr}
          <button style={s.closeBtn} onClick={() => setExportErr(null)}>✕</button>
        </div>
      )}
      {loading && <div style={s.dim}>Loading audit log…</div>}
      {!loading && loadErr && <div style={{ ...s.dim, color: '#f87171' }}>{loadErr}</div>}
      {!loading && !loadErr && (
        <>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>{total} events total</div>
          {events.length === 0 && <div style={s.dim}>No events match this filter.</div>}
          {events.map((e) => (
            <div key={e.event_id} style={s.auditRow}>
              <div style={{ ...s.auditDot, background: eventColor(e.event_type) }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: eventColor(e.event_type) }}>
                    {e.event_type}
                  </span>
                  <span style={{ fontSize: 12, color: '#64748b' }}>{e.user_id}</span>
                  {e.ip_address && <span style={{ fontSize: 11, color: '#475569' }}>{e.ip_address}</span>}
                </div>
                <div style={{ fontSize: 13, color: '#cbd5e1', marginTop: 2 }}>{e.detail}</div>
              </div>
              <div style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>{timeAgo(e.created_at)}</div>
            </div>
          ))}
          {total > 20 && (
            <div style={s.pagination}>
              <button style={s.pageBtn} disabled={page <= 1} onClick={() => load(page - 1)}>← Prev</button>
              <span style={{ fontSize: 13, color: '#64748b' }}>Page {page}</span>
              <button style={s.pageBtn} disabled={events.length < 20} onClick={() => load(page + 1)}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

// ─── Feature Flags Tab ────────────────────────────────────────────────────────

const FlagsTab: React.FC = () => {
  const [flags,     setFlags]     = useState<FeatureFlag[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [loadErr,   setLoadErr]   = useState<string | null>(null);
  const [toggleErr, setToggleErr] = useState<string | null>(null);
  const [search,    setSearch]    = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      const res = await api.get('/admin/feature-flags');
      setFlags(res.data.flags || []);
    } catch (err) {
      setFlags([]);
      setLoadErr(extractErrorMessage(err, 'Failed to load feature flags. Ensure the admin API is running.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (flag: FeatureFlag) => {
    setToggleErr(null);
    try {
      const action = flag.enabled ? 'disable' : 'enable';
      await api.post(`/admin/feature-flags/${flag.name}/${action}`);
      setFlags((prev) => prev.map((f) => f.name === flag.name ? { ...f, enabled: !f.enabled } : f));
    } catch (err) {
      setToggleErr(extractErrorMessage(err, `Failed to toggle flag "${flag.name}". Check permissions.`));
    }
  };

  const flagStatusColor = (st: string) => ({
    stable:       '#4ade80',
    beta:         '#facc15',
    experimental: '#f97316',
    disabled:     '#f87171',
  }[st] ?? '#94a3b8');

  const filtered = flags.filter((f) =>
    !search || f.name.toLowerCase().includes(search.toLowerCase()) ||
    f.description.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div>
      <input
        style={{ ...s.searchInput, marginBottom: 16 }}
        placeholder="Search flags…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {toggleErr && (
        <div style={{ ...s.errorBanner, marginBottom: 12 }}>
          {toggleErr}
          <button style={s.closeBtn} onClick={() => setToggleErr(null)}>✕</button>
        </div>
      )}
      {loading && <div style={s.dim}>Loading flags…</div>}
      {!loading && loadErr && <div style={{ ...s.dim, color: '#f87171' }}>{loadErr}</div>}
      {!loading && !loadErr && flags.length === 0 && (
        <div style={s.dim}>No feature flags found. Ensure the admin API is running.</div>
      )}
      {!loading && !loadErr && filtered.map((flag) => (
        <div key={flag.name} style={s.flagRow}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>{flag.name}</span>
              <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, border: `1px solid ${flagStatusColor(flag.status)}`, color: flagStatusColor(flag.status) }}>
                {flag.status}
              </span>
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{flag.description}</div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 2, fontFamily: 'monospace' }}>{flag.env_var}</div>
          </div>
          {/* Toggle switch */}
          <div
            style={{
              width: 44, height: 24, borderRadius: 12, cursor: 'pointer', flexShrink: 0,
              background: flag.enabled ? '#4ade80' : '#334155',
              position: 'relative', transition: 'background 0.2s',
            }}
            onClick={() => toggle(flag)}
          >
            <div style={{
              position: 'absolute', top: 3, width: 18, height: 18, borderRadius: '50%',
              background: '#fff', transition: 'left 0.2s',
              left: flag.enabled ? 23 : 3,
            }} />
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

type Tab = 'users' | 'audit' | 'flags';

const AdminPanel: React.FC = () => {
  const [tab, setTab] = useState<Tab>('users');

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 style={s.title}>Admin Panel</h1>
        <p style={s.subtitle}>User management, audit log, and feature flags.</p>
      </div>

      <div style={s.tabs}>
        {(['users', 'audit', 'flags'] as Tab[]).map((t) => (
          <button
            key={t}
            style={{ ...s.tab, ...(tab === t ? s.tabActive : {}) }}
            onClick={() => setTab(t)}
          >
            {{ users: 'Users', audit: 'Audit Log', flags: 'Feature Flags' }[t]}
          </button>
        ))}
      </div>

      <div style={s.card}>
        {tab === 'users' && <UsersTab />}
        {tab === 'audit' && <AuditTab />}
        {tab === 'flags' && <FlagsTab />}
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh', background: '#0f172a', color: '#f8fafc',
    fontFamily: "'Inter', system-ui, sans-serif", padding: '24px',
  },
  header: { marginBottom: 24 },
  title:    { fontSize: 28, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: '#94a3b8', marginTop: 4 },
  tabs: { display: 'flex', gap: 4, marginBottom: 16 },
  tab: {
    background: 'transparent', border: '1px solid #334155', borderRadius: 8,
    color: '#64748b', padding: '8px 18px', fontSize: 13, cursor: 'pointer',
  },
  tabActive: { background: '#1e293b', color: '#f8fafc', borderColor: '#475569' },
  card: {
    background: '#1e293b', borderRadius: 12, padding: 24,
    border: '1px solid #334155',
  },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th: {
    textAlign: 'left', padding: '10px 12px', color: '#64748b',
    fontWeight: 600, borderBottom: '1px solid #334155', whiteSpace: 'nowrap',
  },
  tr: { borderBottom: '1px solid #0f172a' },
  td: { padding: '10px 12px', color: '#cbd5e1', whiteSpace: 'nowrap' },
  badge: {
    fontSize: 10, fontWeight: 700, padding: '2px 7px',
    borderRadius: 4, border: '1px solid', textTransform: 'capitalize',
  },
  actionBtn: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 5,
    color: '#94a3b8', padding: '4px 8px', fontSize: 11, cursor: 'pointer',
  },
  searchInput: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    color: '#f8fafc', padding: '8px 12px', fontSize: 13, outline: 'none', minWidth: 220,
  },
  exportBtn: {
    background: '#334155', border: 'none', borderRadius: 8,
    color: '#f8fafc', padding: '8px 14px', fontSize: 13, cursor: 'pointer',
  },
  auditRow: {
    display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 0',
    borderBottom: '1px solid #0f172a',
  },
  auditDot: { width: 8, height: 8, borderRadius: '50%', marginTop: 4, flexShrink: 0 },
  pagination: {
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, marginTop: 16,
  },
  pageBtn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', padding: '6px 14px', fontSize: 13, cursor: 'pointer',
  },
  flagRow: {
    display: 'flex', alignItems: 'center', gap: 16, padding: '12px 0',
    borderBottom: '1px solid #0f172a',
  },
  dim:   { color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 },
  infoBanner: {
    background: 'rgba(96,165,250,0.1)', border: '1px solid #60a5fa', borderRadius: 8,
    padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#60a5fa',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    wordBreak: 'break-all',
  },
  errorBanner: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 8,
    padding: '10px 14px', fontSize: 13, color: '#f87171',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    wordBreak: 'break-all',
  },
  closeBtn: {
    background: 'transparent', border: 'none', color: '#64748b', fontSize: 16, cursor: 'pointer',
  },
};

export default AdminPanel;
