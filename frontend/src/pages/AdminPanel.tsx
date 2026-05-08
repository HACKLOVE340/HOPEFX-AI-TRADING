/**
 * AdminPanel.tsx — Admin landing dashboard (role: admin | superadmin).
 * Mobile-first: KPI grid 2-col xs → 3-col sm → 6-col lg,
 * audit table scrolls horizontally, controls stack on mobile.
 *
 * Endpoints:
 *   GET  /api/admin/overview
 *   GET  /api/admin/audit-log?limit=8
 *   GET  /api/admin/alerts
 *   GET  /api/admin/maintenance
 *   POST /api/admin/maintenance
 *   POST /api/admin/broadcast
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, adminApi, superadminApi } from '../hooks/useApi';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { Badge } from '../components/Badge';
import { Spinner } from '../components/Spinner';
import { ErrorBanner } from '../components/ErrorBanner';

// ── Types ─────────────────────────────────────────────────────────────────────

interface MaintenanceStatus { maintenance_mode: boolean; maintenance_message: string; }
interface BroadcastForm { title: string; body: string; type: 'info' | 'warning' | 'success' | 'error'; }

interface AdminOverview {
  total_users: number; active_users_24h: number; total_trades_today: number;
  open_positions: number; revenue_today_usd: number; revenue_mtd_usd: number;
  platform_uptime_pct: number; active_subscriptions: number; pending_withdrawals: number;
  flagged_accounts: number; ml_model_accuracy: number; ws_connections: number;
}

interface AuditEvent {
  event_id: string; user_id: string; event_type: string;
  detail: string; ip_address: string; created_at: string;
}

interface AdminAlert {
  id: string; severity: 'critical' | 'warning' | 'info';
  title: string; message: string; created_at: string; resolved: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtUSD = (n: number) =>
  n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(2)}M`
  : n >= 1_000   ? `$${(n / 1_000).toFixed(1)}K`
  : `$${n.toFixed(2)}`;

const fmtDate = (iso: string) => {
  try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso; }
};

const severityClasses: Record<string, { badge: string; border: string; bg: string }> = {
  critical: { badge: 'bg-red-500/20 text-red-400 border-red-500/40',    border: 'border-l-red-500',    bg: 'bg-red-500/5' },
  warning:  { badge: 'bg-amber-500/20 text-amber-400 border-amber-500/40', border: 'border-l-amber-500', bg: 'bg-amber-500/5' },
  info:     { badge: 'bg-blue-500/20 text-blue-400 border-blue-500/40',  border: 'border-l-blue-500',   bg: 'bg-blue-500/5' },
};

const eventColor = (type: string) => {
  if (type.includes('fail') || type.includes('ban') || type.includes('block')) return 'text-red-400';
  if (type.includes('warn') || type.includes('withdraw')) return 'text-amber-400';
  if (type.includes('trade') || type.includes('signal')) return 'text-blue-400';
  return 'text-slate-500';
};

const eventDot = (type: string) => {
  if (type.includes('fail') || type.includes('ban') || type.includes('block')) return 'bg-red-400';
  if (type.includes('warn') || type.includes('withdraw')) return 'bg-amber-400';
  if (type.includes('trade') || type.includes('signal')) return 'bg-blue-400';
  return 'bg-slate-500';
};

// ── KPI Card ──────────────────────────────────────────────────────────────────

const KpiCard: React.FC<{ label: string; value: string; sub?: string; accentClass?: string }> = ({
  label, value, sub, accentClass = 'border-t-blue-500',
}) => (
  <div className={`bg-terminal-surface border border-terminal-border rounded-xl p-3 sm:p-4 border-t-2 ${accentClass}`}>
    <div className="text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-1.5">{label}</div>
    <div className="text-slate-100 text-xl sm:text-2xl font-black tabular-nums leading-none">{value}</div>
    {sub && <div className="text-slate-500 text-xs mt-1.5">{sub}</div>}
  </div>
);

// ── Quick Action ──────────────────────────────────────────────────────────────

const QuickAction: React.FC<{ icon: string; label: string; desc: string; path: string }> = ({
  icon, label, desc, path,
}) => (
  <Link to={path}
    className="block bg-terminal-bg border border-terminal-border rounded-xl p-3 sm:p-4 no-underline hover:border-blue-500/60 hover:bg-terminal-raised transition-colors">
    <div className="text-xl sm:text-2xl mb-2">{icon}</div>
    <div className="text-slate-100 text-xs sm:text-sm font-bold mb-0.5">{label}</div>
    <div className="text-slate-500 text-2xs leading-snug">{desc}</div>
  </Link>
);

// ── Maintenance + Broadcast Panel ─────────────────────────────────────────────

const MaintenanceBroadcastPanel: React.FC = () => {
  const [maint, setMaint]       = useState<MaintenanceStatus>({ maintenance_mode: false, maintenance_message: '' });
  const [broadcast, setBroadcast] = useState<BroadcastForm>({ title: '', body: '', type: 'info' });
  const [saving, setSaving]     = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  useEffect(() => {
    api.get<MaintenanceStatus>('/admin/settings/system')
      .then(r => setMaint({
        maintenance_mode: Boolean(r.data.maintenance_mode),
        maintenance_message: String(r.data.maintenance_message ?? ''),
      }))
      .catch(() => {/* non-fatal */});
  }, []);

  const flash = (msg: string) => { setStatusMsg(msg); setTimeout(() => setStatusMsg(''), 4000); };

  const toggleMaintenance = async () => {
    setSaving(true);
    try {
      await api.post('/admin/settings/system', {
        maintenance_mode: !maint.maintenance_mode,
        maintenance_message: maint.maintenance_message,
      });
      setMaint(m => ({ ...m, maintenance_mode: !m.maintenance_mode }));
      flash(`Maintenance mode ${!maint.maintenance_mode ? 'enabled' : 'disabled'}`);
    } catch { flash('Failed — check superadmin privileges'); }
    finally { setSaving(false); }
  };

  const sendBroadcast = async () => {
    if (!broadcast.title || !broadcast.body) return;
    setSaving(true);
    try {
      await superadminApi.broadcastMessage(broadcast);
      setBroadcast({ title: '', body: '', type: 'info' });
      flash('Broadcast sent to all active users ✓');
    } catch { flash('Broadcast failed — check superadmin privileges'); }
    finally { setSaving(false); }
  };

  const BROADCAST_COLORS: Record<string, string> = {
    info: 'border-blue-500 bg-blue-500/15 text-blue-400',
    warning: 'border-amber-500 bg-amber-500/15 text-amber-400',
    success: 'border-green-500 bg-green-500/15 text-green-400',
    error: 'border-red-500 bg-red-500/15 text-red-400',
  };
  const BROADCAST_INACTIVE = 'border-terminal-border bg-transparent text-slate-600';

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
      {/* Maintenance mode */}
      <div className={`bg-terminal-surface border rounded-xl p-4 sm:p-5 ${maint.maintenance_mode ? 'border-amber-500/50' : 'border-terminal-border'}`}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-slate-100 text-sm font-bold">🔧 Maintenance Mode</div>
            <div className="text-slate-500 text-xs mt-0.5">
              {maint.maintenance_mode ? '⚠️ ACTIVE — users see downtime page' : 'Platform is live'}
            </div>
          </div>
          <span className={`text-2xs font-bold px-2 py-0.5 rounded-full border ${
            maint.maintenance_mode
              ? 'bg-amber-500/15 border-amber-500/40 text-amber-400'
              : 'bg-green-500/15 border-green-500/40 text-green-400'
          }`}>
            {maint.maintenance_mode ? 'ON' : 'OFF'}
          </span>
        </div>
        <label className="block text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-1.5">
          Message shown to users
        </label>
        <input
          value={maint.maintenance_message}
          onChange={e => setMaint(m => ({ ...m, maintenance_message: e.target.value }))}
          placeholder="We're performing scheduled maintenance. Back shortly."
          className="w-full bg-terminal-bg border border-terminal-border rounded-lg px-3 py-2 text-slate-200 text-xs outline-none focus:border-blue-500 transition-colors mb-3"
        />
        <button
          onClick={toggleMaintenance}
          disabled={saving}
          className={`w-full py-2.5 rounded-lg text-sm font-bold cursor-pointer border-0 transition-colors disabled:opacity-60 ${
            maint.maintenance_mode
              ? 'bg-green-700 hover:bg-green-600 text-white'
              : 'bg-amber-700 hover:bg-amber-600 text-white'
          }`}
        >
          {maint.maintenance_mode ? '✅ Disable Maintenance Mode' : '🔧 Enable Maintenance Mode'}
        </button>
      </div>

      {/* Broadcast */}
      <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-5">
        <div className="text-slate-100 text-sm font-bold mb-4">📡 Broadcast Message</div>
        <label className="block text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-1.5">Title</label>
        <input
          value={broadcast.title}
          onChange={e => setBroadcast(b => ({ ...b, title: e.target.value }))}
          placeholder="Important update"
          className="w-full bg-terminal-bg border border-terminal-border rounded-lg px-3 py-2 text-slate-200 text-xs outline-none focus:border-blue-500 transition-colors mb-3"
        />
        <label className="block text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-1.5">Message</label>
        <textarea
          rows={3}
          value={broadcast.body}
          onChange={e => setBroadcast(b => ({ ...b, body: e.target.value }))}
          placeholder="Message to send to all active users…"
          className="w-full bg-terminal-bg border border-terminal-border rounded-lg px-3 py-2 text-slate-200 text-xs outline-none focus:border-blue-500 transition-colors resize-y mb-3"
        />
        <div className="flex gap-1.5 mb-3">
          {(['info', 'warning', 'success', 'error'] as const).map(t => (
            <button key={t} onClick={() => setBroadcast(b => ({ ...b, type: t }))}
              className={`flex-1 py-1.5 rounded-md text-2xs font-bold cursor-pointer border uppercase transition-colors ${
                broadcast.type === t ? BROADCAST_COLORS[t] : BROADCAST_INACTIVE
              }`}>
              {t}
            </button>
          ))}
        </div>
        <button
          onClick={sendBroadcast}
          disabled={saving || !broadcast.title || !broadcast.body}
          className="w-full py-2.5 bg-blue-700 hover:bg-blue-600 text-white rounded-lg text-sm font-bold cursor-pointer border-0 transition-colors disabled:opacity-50"
        >
          📡 Send to All Users
        </button>
      </div>

      {statusMsg && (
        <div className={`sm:col-span-2 px-4 py-3 rounded-xl text-sm font-semibold ${
          statusMsg.toLowerCase().includes('fail')
            ? 'bg-red-950/40 border border-red-800 text-red-400'
            : 'bg-green-950/40 border border-green-800 text-green-400'
        }`}>
          {statusMsg}
        </div>
      )}
    </div>
  );
};

// ── Main ──────────────────────────────────────────────────────────────────────

const AdminPanel: React.FC = () => {
  const navigate = useNavigate();
  const [overview, setOverview]     = useState<AdminOverview | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [alerts, setAlerts]         = useState<AdminAlert[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

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
        const ov = (d && 'data' in d && d.data && typeof d.data === 'object') ? d.data as Record<string, unknown> : d;
        setOverview({
          total_users:          Number(ov.total_users ?? 0),
          active_users_24h:     Number(ov.active_users_24h ?? 0),
          total_trades_today:   Number(ov.total_trades_today ?? 0),
          open_positions:       Number(ov.open_positions ?? 0),
          revenue_today_usd:    Number(ov.revenue_today_usd ?? 0),
          revenue_mtd_usd:      Number(ov.revenue_mtd_usd ?? 0),
          platform_uptime_pct:  Number(ov.platform_uptime_pct ?? 100),
          active_subscriptions: Number(ov.active_subscriptions ?? 0),
          pending_withdrawals:  Number(ov.pending_withdrawals ?? 0),
          flagged_accounts:     Number(ov.flagged_accounts ?? 0),
          ml_model_accuracy:    Number(ov.ml_model_accuracy ?? 0),
          ws_connections:       Number(ov.ws_connections ?? 0),
        });
      } else { setError('Failed to load admin overview.'); }

      if (auditRes.status === 'fulfilled') {
        const d = auditRes.value.data as Record<string, unknown>;
        const events = Array.isArray(d) ? d : Array.isArray(d.events) ? d.events : [];
        setAuditEvents((events as unknown[]).map((e, idx) => {
          const ev = (e ?? {}) as Record<string, unknown>;
          return {
            event_id:   String(ev.event_id ?? ev.id ?? `audit-${idx}`),
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
        const list = Array.isArray(d) ? d : Array.isArray(d.alerts) ? d.alerts : Array.isArray(d.items) ? d.items : [];
        setAlerts((list as unknown[]).map((a, idx) => {
          const al = (a ?? {}) as Record<string, unknown>;
          return {
            id:         String(al.id ?? `alert-${idx}`),
            severity:   (al.severity ?? 'info') as AdminAlert['severity'],
            title:      String(al.title ?? al.name ?? ''),
            message:    String(al.message ?? al.detail ?? ''),
            created_at: String(al.created_at ?? al.timestamp ?? new Date().toISOString()),
            resolved:   Boolean(al.resolved),
          } as AdminAlert;
        }));
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); const id = setInterval(load, 30_000); return () => clearInterval(id); }, [load]);

  const activeAlerts = alerts.filter(a => !a.resolved);
  const criticalCount = activeAlerts.filter(a => a.severity === 'critical').length;

  return (
    <div className="min-h-screen bg-terminal-bg text-slate-100 px-3 sm:px-6 py-4 sm:py-8 pb-12">
      <div className="max-w-screen-xl mx-auto">
        <PageHeader
          title="Admin Panel"
          icon="🔧"
          subtitle="Platform operations, user management, and system health."
          breadcrumbs={[{ label: 'Home', href: '/home' }, { label: 'Admin Panel' }]}
          badge={
            criticalCount > 0
              ? <Badge variant="danger" className="text-2xs">{criticalCount} Critical</Badge>
              : <Badge variant="success" className="text-2xs">Operational</Badge>
          }
          actions={
            <button onClick={load} disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-950 border border-blue-800 rounded-lg text-blue-400 text-xs font-semibold cursor-pointer hover:bg-blue-900 transition-colors disabled:opacity-60">
              {loading ? <Spinner size="sm" /> : '↻'} Refresh
            </button>
          }
        />

        {error && <ErrorBanner message={error} className="mb-4" />}

        {loading && !overview ? (
          <div className="flex justify-center py-16"><Spinner size="lg" /></div>
        ) : (
          <>
            {/* KPI Grid — 2-col xs, 3-col sm, 6-col lg */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
              <KpiCard label="Total Users"     accentClass="border-t-blue-500"
                value={overview ? Number(overview.total_users).toLocaleString() : '—'}
                sub={overview ? `${overview.active_users_24h} active (24h)` : undefined} />
              <KpiCard label="Trades Today"    accentClass="border-t-green-500"
                value={overview ? Number(overview.total_trades_today).toLocaleString() : '—'}
                sub={overview ? `${overview.open_positions} open` : undefined} />
              <KpiCard label="Revenue Today"   accentClass="border-t-amber-500"
                value={overview ? fmtUSD(Number(overview.revenue_today_usd)) : '—'}
                sub={overview ? `MTD: ${fmtUSD(Number(overview.revenue_mtd_usd))}` : undefined} />
              <KpiCard label="Active Subs"     accentClass="border-t-violet-500"
                value={overview ? Number(overview.active_subscriptions).toLocaleString() : '—'}
                sub={overview ? `${overview.pending_withdrawals} pending w/d` : undefined} />
              <KpiCard label="Uptime"          accentClass="border-t-cyan-500"
                value={overview ? `${Number(overview.platform_uptime_pct).toFixed(2)}%` : '—'}
                sub={overview ? `${overview.ws_connections} WS` : undefined} />
              <KpiCard
                label="ML Accuracy"
                accentClass={overview && overview.flagged_accounts > 0 ? 'border-t-red-500' : 'border-t-green-500'}
                value={overview ? `${(Number(overview.ml_model_accuracy) * 100).toFixed(1)}%` : '—'}
                sub={overview && overview.flagged_accounts > 0 ? `⚠️ ${overview.flagged_accounts} flagged` : 'No flagged'} />
            </div>

            {/* Active Alerts */}
            {activeAlerts.length > 0 && (
              <div className="bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden mb-6">
                <div className="flex items-center justify-between px-4 py-3 border-b border-terminal-border">
                  <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">⚠️ Active Alerts</span>
                  <span className="text-red-400 text-xs font-semibold">{activeAlerts.length} unresolved</span>
                </div>
                {activeAlerts.map(alert => {
                  const cls = severityClasses[alert.severity] ?? severityClasses.info;
                  return (
                    <div key={alert.id}
                      className={`flex items-start gap-3 px-4 py-3 border-b border-terminal-border/60 border-l-2 ${cls.border} ${cls.bg}`}>
                      <span className={`text-2xs font-bold px-1.5 py-0.5 rounded border flex-shrink-0 mt-0.5 ${cls.badge}`}>
                        {alert.severity}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-slate-100 text-sm font-semibold">{alert.title}</div>
                        <div className="text-slate-400 text-xs mt-0.5">{alert.message}</div>
                      </div>
                      <span className="text-slate-600 text-2xs flex-shrink-0 mt-0.5 hidden sm:block">
                        {fmtDate(alert.created_at)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Recent Audit Events */}
            <div className="bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden mb-6">
              <div className="flex items-center justify-between px-4 py-3 border-b border-terminal-border">
                <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">🔍 Recent Audit Events</span>
                <button onClick={() => navigate('/audit')}
                  className="text-blue-400 text-xs font-semibold bg-transparent border-0 cursor-pointer hover:text-blue-300 transition-colors">
                  View all →
                </button>
              </div>
              {auditEvents.length === 0 ? (
                <div className="px-4 py-6 text-slate-500 text-sm">No recent audit events.</div>
              ) : (
                <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' } as React.CSSProperties}>
                  <table className="w-full border-collapse text-xs" style={{ minWidth: 560 }}>
                    <tbody>
                      {auditEvents.map(ev => (
                        <tr key={ev.event_id} className="border-b border-terminal-border/60 hover:bg-terminal-raised/40 transition-colors">
                          <td className="px-4 py-2.5 w-2">
                            <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${eventDot(ev.event_type)}`} />
                          </td>
                          <td className={`px-3 py-2.5 font-semibold whitespace-nowrap ${eventColor(ev.event_type)}`}>
                            {ev.event_type || '—'}
                          </td>
                          <td className="px-3 py-2.5 text-slate-400 max-w-xs truncate">{ev.detail || '—'}</td>
                          <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap hidden sm:table-cell">{ev.ip_address || '—'}</td>
                          <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap">{fmtDate(ev.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Platform Controls */}
            <div className="bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden mb-6">
              <div className="flex items-center justify-between px-4 py-3 border-b border-terminal-border">
                <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">⚙️ Platform Controls</span>
                <span className="text-slate-600 text-xs hidden sm:block">Maintenance mode &amp; user broadcasts</span>
              </div>
              <div className="p-4 sm:p-5">
                <MaintenanceBroadcastPanel />
              </div>
            </div>

            {/* Quick Actions — 2-col xs, 3-col sm, 6-col lg */}
            <div className="bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden mb-6">
              <div className="px-4 py-3 border-b border-terminal-border">
                <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">Quick Actions</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-4">
                <QuickAction icon="🔍" label="Audit Log"     desc="Browse all platform events"      path="/audit" />
                <QuickAction icon="🛡️" label="Security Ops"  desc="Threats, IPs, sessions"          path="/security" />
                <QuickAction icon="🩺" label="Auto-Heal"     desc="Self-healing & circuit breakers" path="/auto-heal" />
                <QuickAction icon="🏷️" label="Whitelabel"    desc="Branding & tenant config"        path="/whitelabel" />
                <QuickAction icon="🟢" label="System Status" desc="Health & uptime"                 path="/status" />
                <QuickAction icon="⚡" label="Super Admin"   desc="Master control panel"            path="/superadmin" />
              </div>
            </div>

            <CrossLinkBar title="Platform Sections" links={[
              { label: 'Audit Log',          href: '/audit',              icon: '🔍', color: '#60a5fa' },
              { label: 'Security Dashboard', href: '/security',           icon: '🛡️', color: '#f87171' },
              { label: 'Auto-Heal',          href: '/auto-heal',          icon: '🩺', color: '#4ade80' },
              { label: 'Whitelabel Admin',   href: '/whitelabel',         icon: '🏷️', color: '#a78bfa' },
              { label: 'System Status',      href: '/status',             icon: '🟢', color: '#22c55e' },
              { label: 'Super Admin',        href: '/superadmin',         icon: '⚡', color: '#f59e0b' },
              { label: 'System Reliability', href: '/system-reliability', icon: '🔬', color: '#06b6d4' },
              { label: 'Docs',               href: '/docs',               icon: '📖', color: '#94a3b8' },
            ]} />
          </>
        )}
      </div>
    </div>
  );
};

export default AdminPanel;
