/**
 * AdminPanel.tsx
 * Admin landing dashboard — role: admin or superadmin.
 *
 * Sections:
 *   - Platform KPIs (users, trades, revenue, uptime)
 *   - Active system alerts
 *   - Recent audit events
 *   - Quick-action links to sub-sections
 *
 * Backend endpoints:
 *   GET /api/admin/overview
 *   GET /api/admin/audit-log?limit=8
 *   GET /api/admin/alerts
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, adminApi } from '../hooks/useApi';
import { PageHeader } from '../components/PageHeader';
import { Spinner } from '../components/Spinner';
import { ErrorBanner } from '../components/ErrorBanner';

// ── Maintenance / Broadcast types ─────────────────────────────────────────────

interface MaintenanceStatus {
  maintenance_mode: boolean;
  maintenance_message: string;
}

interface BroadcastForm {
  title: string;
  body: string;
  type: 'info' | 'warning' | 'success' | 'error';
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface AdminOverview {
  total_users: number;
  active_users_24h: number;
  total_trades_today: number;
  open_positions: number;
  revenue_today_usd: number;
  revenue_mtd_usd: number;
  platform_uptime_pct: number;
  active_subscriptions: number;
  pending_withdrawals: number;
  flagged_accounts: number;
  ml_model_accuracy: number;
  ws_connections: number;
}

interface AuditEvent {
  event_id: string;
  user_id: string;
  event_type: string;
  detail: string;
  ip_address: string;
  created_at: string;
}

interface AdminAlert {
  id: string;
  severity: 'critical' | 'warning' | 'info';
  title: string;
  message: string;
  created_at: string;
  resolved: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtUSD = (n: number) =>
  n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(2)}M`
    : n >= 1_000
    ? `$${(n / 1_000).toFixed(1)}K`
    : `$${n.toFixed(2)}`;

const fmtDate = (iso: string) => {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

const severityColor = (sev: string | undefined | null) => {
  const s = sev ?? '';
  return s === 'critical' ? '#f87171' : s === 'warning' ? '#fbbf24' : '#60a5fa';
};

const eventColor = (type: string | undefined | null) => {
  const t = type ?? '';
  if (t.includes('fail') || t.includes('ban') || t.includes('block')) return '#f87171';
  if (t.includes('warn') || t.includes('withdraw')) return '#fbbf24';
  if (t.includes('trade') || t.includes('signal')) return '#60a5fa';
  return '#94a3b8';
};

// ── Sub-components ────────────────────────────────────────────────────────────

const KpiCard: React.FC<{
  label: string; value: string; sub?: string; accent?: string;
}> = ({ label, value, sub, accent }) => (
  <div style={{
    background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
    padding: '18px 20px', borderTop: accent ? `3px solid ${accent}` : undefined,
  }}>
    <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
      {label}
    </div>
    <div style={{ fontSize: 26, fontWeight: 800, color: '#f8fafc', lineHeight: 1 }}>{value}</div>
    {sub && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{sub}</div>}
  </div>
);

const QuickAction: React.FC<{
  icon: string; label: string; desc: string; path: string; onClick: (p: string) => void;
}> = ({ icon, label, desc, path, onClick }) => (
  <button
    onClick={() => onClick(path)}
    style={{
      background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
      padding: '14px 16px', cursor: 'pointer', textAlign: 'left', color: '#f1f5f9',
      transition: 'border-color 0.15s, background 0.15s',
    }}
    onMouseEnter={e => {
      (e.currentTarget as HTMLButtonElement).style.borderColor = '#3b82f6';
      (e.currentTarget as HTMLButtonElement).style.background = '#1e293b';
    }}
    onMouseLeave={e => {
      (e.currentTarget as HTMLButtonElement).style.borderColor = '#334155';
      (e.currentTarget as HTMLButtonElement).style.background = '#0f172a';
    }}
  >
    <div style={{ fontSize: 22, marginBottom: 6 }}>{icon}</div>
    <div style={{ fontSize: 13, fontWeight: 700, color: '#f8fafc', marginBottom: 2 }}>{label}</div>
    <div style={{ fontSize: 11, color: '#64748b' }}>{desc}</div>
  </button>
);

// ── Maintenance + Broadcast Panel ─────────────────────────────────────────────

const MaintenanceBroadcastPanel: React.FC = () => {
  const [maint, setMaint] = useState<MaintenanceStatus>({ maintenance_mode: false, maintenance_message: '' });
  const [broadcast, setBroadcast] = useState<BroadcastForm>({ title: '', body: '', type: 'info' });
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  useEffect(() => {
    api.get<MaintenanceStatus>('/admin/maintenance')
      .then(r => setMaint(r.data))
      .catch(() => {/* non-fatal — endpoint may require superadmin */});
  }, []);

  const flash = (msg: string) => {
    setStatusMsg(msg);
    setTimeout(() => setStatusMsg(''), 4000);
  };

  const toggleMaintenance = async () => {
    setSaving(true);
    try {
      await api.post('/admin/maintenance', {
        enabled: !maint.maintenance_mode,
        message: maint.maintenance_message,
      });
      setMaint(m => ({ ...m, maintenance_mode: !m.maintenance_mode }));
      flash(`Maintenance mode ${!maint.maintenance_mode ? 'enabled' : 'disabled'}`);
    } catch {
      flash('Failed — check superadmin privileges');
    } finally {
      setSaving(false);
    }
  };

  const sendBroadcast = async () => {
    if (!broadcast.title || !broadcast.body) return;
    setSaving(true);
    try {
      await api.post('/admin/broadcast', broadcast);
      setBroadcast({ title: '', body: '', type: 'info' });
      flash('Broadcast sent to all active users ✓');
    } catch {
      flash('Broadcast failed — check superadmin privileges');
    } finally {
      setSaving(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '8px 12px', background: '#0f172a',
    border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9',
    fontSize: 13, boxSizing: 'border-box', outline: 'none', fontFamily: 'inherit',
  };

  const BROADCAST_COLORS: Record<string, string> = {
    info: '#3b82f6', warning: '#f59e0b', success: '#22c55e', error: '#ef4444',
  };

  return (
    <div style={{ margin: '0 24px 24px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      {/* Maintenance mode */}
      <div style={{ background: '#1e293b', border: `1px solid ${maint.maintenance_mode ? '#f59e0b' : '#334155'}`, borderRadius: 10, padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f8fafc' }}>🔧 Maintenance Mode</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
              {maint.maintenance_mode ? '⚠️ ACTIVE — users see downtime page' : 'Platform is live'}
            </div>
          </div>
          <div style={{
            padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700,
            background: maint.maintenance_mode ? '#f59e0b20' : '#22c55e20',
            color: maint.maintenance_mode ? '#f59e0b' : '#22c55e',
            border: `1px solid ${maint.maintenance_mode ? '#f59e0b40' : '#22c55e40'}`,
          }}>
            {maint.maintenance_mode ? 'ON' : 'OFF'}
          </div>
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginBottom: 5 }}>Message shown to users</label>
          <input
            style={inputStyle}
            value={maint.maintenance_message}
            onChange={e => setMaint(m => ({ ...m, maintenance_message: e.target.value }))}
            placeholder="We're performing scheduled maintenance. Back shortly."
          />
        </div>
        <button
          onClick={toggleMaintenance}
          disabled={saving}
          style={{
            width: '100%', padding: '9px 16px', borderRadius: 7, cursor: 'pointer',
            fontSize: 13, fontWeight: 700, border: 'none', fontFamily: 'inherit',
            background: maint.maintenance_mode ? '#16a34a' : '#b45309',
            color: '#fff', opacity: saving ? 0.7 : 1,
          }}
        >
          {maint.maintenance_mode ? '✅ Disable Maintenance Mode' : '🔧 Enable Maintenance Mode'}
        </button>
      </div>

      {/* Broadcast */}
      <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#f8fafc', marginBottom: 14 }}>📡 Broadcast Message</div>
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginBottom: 5 }}>Title</label>
          <input style={inputStyle} value={broadcast.title} onChange={e => setBroadcast(b => ({ ...b, title: e.target.value }))} placeholder="Important update" />
        </div>
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginBottom: 5 }}>Message</label>
          <textarea
            style={{ ...inputStyle, resize: 'vertical' as const }}
            rows={3}
            value={broadcast.body}
            onChange={e => setBroadcast(b => ({ ...b, body: e.target.value }))}
            placeholder="Message to send to all active users…"
          />
        </div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          {(['info', 'warning', 'success', 'error'] as const).map(t => (
            <button key={t} onClick={() => setBroadcast(b => ({ ...b, type: t }))} style={{
              flex: 1, padding: '5px 0', borderRadius: 5, cursor: 'pointer', fontSize: 10, fontWeight: 700,
              border: `1px solid ${broadcast.type === t ? BROADCAST_COLORS[t] : '#334155'}`,
              background: broadcast.type === t ? `${BROADCAST_COLORS[t]}20` : 'transparent',
              color: broadcast.type === t ? BROADCAST_COLORS[t] : '#475569',
              fontFamily: 'inherit', textTransform: 'uppercase',
            }}>{t}</button>
          ))}
        </div>
        <button
          onClick={sendBroadcast}
          disabled={saving || !broadcast.title || !broadcast.body}
          style={{
            width: '100%', padding: '9px 16px', borderRadius: 7, cursor: 'pointer',
            fontSize: 13, fontWeight: 700, border: 'none', fontFamily: 'inherit',
            background: '#1d4ed8', color: '#fff',
            opacity: (saving || !broadcast.title || !broadcast.body) ? 0.5 : 1,
          }}
        >
          📡 Send to All Users
        </button>
      </div>

      {statusMsg && (
        <div style={{
          gridColumn: '1 / -1',
          padding: '10px 14px', borderRadius: 7, fontSize: 13, fontWeight: 600,
          background: statusMsg.includes('failed') || statusMsg.includes('Failed') ? '#450a0a' : '#052e16',
          color: statusMsg.includes('failed') || statusMsg.includes('Failed') ? '#f87171' : '#4ade80',
        }}>
          {statusMsg}
        </div>
      )}
    </div>
  );
};

// ── Main ──────────────────────────────────────────────────────────────────────

const AdminPanel: React.FC = () => {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [alerts, setAlerts] = useState<AdminAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [ovRes, auditRes, alertsRes] = await Promise.allSettled([
        adminApi.overview(),
        adminApi.auditLog({ limit: 8 }),
        adminApi.alerts(),
      ]);
      if (!mountedRef.current) return;

      if (ovRes.status === 'fulfilled') {
        const d = ovRes.value.data as Record<string, unknown>;
        // Backend may return nested { data: {...} } or flat object
        const ov = (d && typeof d === 'object' && 'data' in d && d.data && typeof d.data === 'object')
          ? d.data as Record<string, unknown>
          : d;
        setOverview({
          total_users:           Number(ov.total_users ?? 0),
          active_users_24h:      Number(ov.active_users_24h ?? 0),
          total_trades_today:    Number(ov.total_trades_today ?? 0),
          open_positions:        Number(ov.open_positions ?? 0),
          revenue_today_usd:     Number(ov.revenue_today_usd ?? 0),
          revenue_mtd_usd:       Number(ov.revenue_mtd_usd ?? 0),
          platform_uptime_pct:   Number(ov.platform_uptime_pct ?? 100),
          active_subscriptions:  Number(ov.active_subscriptions ?? 0),
          pending_withdrawals:   Number(ov.pending_withdrawals ?? 0),
          flagged_accounts:      Number(ov.flagged_accounts ?? 0),
          ml_model_accuracy:     Number(ov.ml_model_accuracy ?? 0),
          ws_connections:        Number(ov.ws_connections ?? 0),
        });
      } else {
        setError('Failed to load admin overview.');
      }

      if (auditRes.status === 'fulfilled') {
        const d = auditRes.value.data as Record<string, unknown>;
        const events = Array.isArray(d)
          ? d
          : Array.isArray(d.events)
          ? d.events
          : [];
        setAuditEvents((events as unknown[]).map((e) => {
          const ev = (e ?? {}) as Record<string, unknown>;
          return {
            event_id:   String(ev.event_id ?? ev.id ?? Math.random()),
            user_id:    String(ev.user_id ?? ''),
            event_type: String(ev.event_type ?? ev.type ?? ''),
            detail:     String(ev.detail ?? ev.message ?? ''),
            ip_address: String(ev.ip_address ?? ev.ip ?? ''),
            created_at: String(ev.created_at ?? ev.timestamp ?? new Date().toISOString()),
          } as AuditEvent;
        }));
      }

      if (alertsRes.status === 'fulfilled') {
        const d = alertsRes.value.data as Record<string, unknown>;
        const alerts = Array.isArray(d)
          ? d
          : Array.isArray(d.alerts)
          ? d.alerts
          : Array.isArray(d.items)
          ? d.items
          : [];
        setAlerts((alerts as unknown[]).map((a) => {
          const al = (a ?? {}) as Record<string, unknown>;
          return {
            id:         String(al.id ?? Math.random()),
            severity:   (al.severity ?? 'info') as AdminAlert['severity'],
            title:      String(al.title ?? al.name ?? ''),
            message:    String(al.message ?? al.detail ?? ''),
            created_at: String(al.created_at ?? al.timestamp ?? new Date().toISOString()),
            resolved:   Boolean(al.resolved),
          } as AdminAlert;
        }));
      }
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const go = (path: string) => navigate(path);
  const activeAlerts = alerts.filter(a => !a.resolved);

  const sectionStyle: React.CSSProperties = {
    margin: '0 24px 24px',
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: 10,
    overflow: 'hidden',
  };
  const sectionHeader: React.CSSProperties = {
    padding: '14px 20px',
    borderBottom: '1px solid #334155',
    fontSize: 13, fontWeight: 700, color: '#94a3b8',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  };
  const rowStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 12,
    padding: '12px 20px', borderBottom: '1px solid #0f172a', fontSize: 13,
  };

  return (
    <div style={{ minHeight: '100vh', background: '#0f172a', color: '#f1f5f9', fontFamily: 'Inter, system-ui, sans-serif', paddingBottom: 48 }}>
      <PageHeader
        title="🔧 Admin Panel"
        subtitle="Platform operations, user management, and system health"
        actions={
          <button
            onClick={load}
            style={{ background: '#1e3a5f', border: '1px solid #1d4ed8', borderRadius: 6, color: '#60a5fa', fontSize: 12, cursor: 'pointer', padding: '6px 14px', fontWeight: 600 }}
          >
            ↻ Refresh
          </button>
        }
      />

      {error && <div style={{ padding: '0 24px 16px' }}><ErrorBanner message={error} /></div>}

      {loading && !overview ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spinner /></div>
      ) : (
        <>
          {/* KPI Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16, padding: '0 24px 24px' }}>
            <KpiCard label="Total Users"      value={overview ? Number(overview.total_users).toLocaleString() : '—'}          sub={overview ? `${overview.active_users_24h} active (24h)` : undefined}                                accent="#3b82f6" />
            <KpiCard label="Trades Today"     value={overview ? Number(overview.total_trades_today).toLocaleString() : '—'}    sub={overview ? `${overview.open_positions} open positions` : undefined}                              accent="#22c55e" />
            <KpiCard label="Revenue Today"    value={overview ? fmtUSD(Number(overview.revenue_today_usd)) : '—'}              sub={overview ? `MTD: ${fmtUSD(Number(overview.revenue_mtd_usd))}` : undefined}                               accent="#f59e0b" />
            <KpiCard label="Active Subs"      value={overview ? Number(overview.active_subscriptions).toLocaleString() : '—'}  sub={overview ? `${overview.pending_withdrawals} pending withdrawals` : undefined}                    accent="#8b5cf6" />
            <KpiCard label="Platform Uptime"  value={overview ? `${Number(overview.platform_uptime_pct).toFixed(2)}%` : '—'}   sub={overview ? `${overview.ws_connections} WS connections` : undefined}                              accent="#06b6d4" />
            <KpiCard label="ML Accuracy"      value={overview ? `${(Number(overview.ml_model_accuracy) * 100).toFixed(1)}%` : '—'} sub={overview && overview.flagged_accounts > 0 ? `⚠️ ${overview.flagged_accounts} flagged` : 'No flagged accounts'} accent={overview && overview.flagged_accounts > 0 ? '#f87171' : '#22c55e'} />
          </div>

          {/* Active Alerts */}
          {activeAlerts.length > 0 && (
            <div style={sectionStyle}>
              <div style={sectionHeader}>
                <span>⚠️ Active Alerts</span>
                <span style={{ fontSize: 11, color: '#f87171' }}>{activeAlerts.length} unresolved</span>
              </div>
              {activeAlerts.map(alert => (
                <div key={alert.id} style={{ ...rowStyle, borderLeft: `3px solid ${severityColor(alert.severity)}`, background: `${severityColor(alert.severity)}08` }}>
                  <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: `${severityColor(alert.severity)}20`, color: severityColor(alert.severity), textTransform: 'uppercase', flexShrink: 0 }}>
                    {alert.severity}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13 }}>{alert.title}</div>
                    <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{alert.message}</div>
                  </div>
                  <span style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>{fmtDate(alert.created_at)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Recent Audit Events */}
          <div style={sectionStyle}>
            <div style={sectionHeader}>
              <span>🔍 Recent Audit Events</span>
              <button onClick={() => go('/audit')} style={{ background: 'transparent', border: 'none', color: '#3b82f6', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>
                View all →
              </button>
            </div>
            {auditEvents.length === 0 ? (
              <div style={{ padding: '24px 20px', color: '#475569', fontSize: 13 }}>No recent audit events.</div>
            ) : auditEvents.map(ev => (
              <div key={ev.event_id} style={rowStyle}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: eventColor(ev.event_type), flexShrink: 0 }} />
                <span style={{ fontSize: 11, fontWeight: 600, color: eventColor(ev.event_type), minWidth: 160, flexShrink: 0 }}>{ev.event_type || '—'}</span>
                <span style={{ flex: 1, color: '#94a3b8', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.detail || '—'}</span>
                <span style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>{ev.ip_address || '—'}</span>
                <span style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>{fmtDate(ev.created_at)}</span>
              </div>
            ))}
          </div>

          {/* Maintenance Mode + Broadcast */}
          <div style={{ margin: '0 24px', marginBottom: 8 }}>
            <div style={{ ...sectionHeader, background: '#1e293b', border: '1px solid #334155', borderRadius: '10px 10px 0 0', padding: '14px 20px' }}>
              <span>⚙️ Platform Controls</span>
              <span style={{ fontSize: 11, color: '#475569' }}>Maintenance mode & user broadcasts</span>
            </div>
          </div>
          <MaintenanceBroadcastPanel />

          {/* Quick Actions */}
          <div style={sectionStyle}>
            <div style={sectionHeader}>Quick Actions</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, padding: '16px 20px' }}>
              <QuickAction icon="🔍" label="Audit Log"      desc="Browse all platform events"       path="/audit"      onClick={go} />
              <QuickAction icon="🛡️" label="Security Ops"   desc="Threats, IPs, sessions"           path="/security"   onClick={go} />
              <QuickAction icon="🩺" label="Auto-Heal"      desc="Self-healing & circuit breakers"  path="/auto-heal"  onClick={go} />
              <QuickAction icon="🏷️" label="Whitelabel"     desc="Branding & tenant config"         path="/whitelabel" onClick={go} />
              <QuickAction icon="🟢" label="System Status"  desc="Health & uptime"                  path="/status"     onClick={go} />
              <QuickAction icon="⚡" label="Super Admin"    desc="Master control panel"             path="/superadmin" onClick={go} />
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default AdminPanel;
