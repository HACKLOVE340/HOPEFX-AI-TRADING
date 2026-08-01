// superadmin/OverviewSection.tsx — platform-wide KPI overview
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  KpiTile, SectionCard, StatusBadge, ActionBtn,
  Spinner, ErrorState, LoadingRows,
} from './ui';
import type { PlatformOverview } from './types';
import { useSuperAdminNav } from './types';
import { extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';

// ── Infra detail types ────────────────────────────────────────────────────────
interface InfraHealth {
  cpu_pct: number;
  mem_pct: number;
  disk_pct: number;
  network_in_mbps: number;
  network_out_mbps: number;
  load_avg_1m: number;
  load_avg_5m: number;
  load_avg_15m: number;
}

interface CacheStats {
  hit_rate_pct: number;
  total_keys: number;
  memory_used_mb: number;
  evictions: number;
  connected_clients: number;
  ops_per_sec: number;
}

interface DbStats {
  active_connections: number;
  max_connections: number;
  query_time_avg_ms: number;
  size_mb: number;
  slow_queries: number;
  deadlocks: number;
}

interface QueueEntry {
  name: string;
  pending: number;
  processing: number;
  failed: number;
  workers: number;
}

interface InfraData {
  health: InfraHealth | null;
  cache: CacheStats | null;
  db: DbStats | null;
  queues: QueueEntry[];
}

const fmt = (n: number) =>
  !Number.isFinite(n) ? '—'
  : n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M`
  : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n);

const fmtMoney = (n: number, cur = 'USD') => {
  if (!Number.isFinite(n)) return '—';
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: cur || 'USD', maximumFractionDigits: 0 }).format(n);
  } catch {
    return `$${n.toFixed(0)}`;
  }
};

const fmtPct = (n: number) => (Number.isFinite(n) ? `${n.toFixed(1)}%` : '—');

interface GaugeBarProps { label: string; value: number; max?: number; color?: string; unit?: string }
const GaugeBar: React.FC<GaugeBarProps> = ({ label, value, max = 100, color = '#3b82f6', unit = '%' }) => {
  const pct = Math.min((value / max) * 100, 100);
  const barColor = pct > 85 ? '#ef4444' : pct > 65 ? '#f59e0b' : color;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>{label}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: barColor }}>{value}{unit}</span>
      </div>
      <div style={{ height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: barColor,
          borderRadius: 3, transition: 'width 0.6s ease',
        }} />
      </div>
    </div>
  );
};

interface AlertRowProps { level: 'info' | 'warn' | 'critical'; message: string }
const AlertRow: React.FC<AlertRowProps> = ({ level, message }) => {
  const colors = {
    info:     { bg: '#0c1a2e', border: '#1d4ed8', icon: 'ℹ️', color: '#60a5fa' },
    warn:     { bg: '#1c1200', border: '#d97706', icon: '⚠️', color: '#fbbf24' },
    critical: { bg: '#1a0000', border: '#dc2626', icon: '🚨', color: '#f87171' },
  }[level];
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      background: colors.bg, border: `1px solid ${colors.border}`,
      borderRadius: 8, padding: '10px 14px', marginBottom: 8,
    }}>
      <span style={{ fontSize: 14 }}>{colors.icon}</span>
      <span style={{ fontSize: 12, color: colors.color }}>{message}</span>
    </div>
  );
};

const OverviewSection: React.FC = () => {
  const { navigateTo } = useSuperAdminNav();
  const [data, setData]         = useState<PlatformOverview | null>(null);
  const [infra, setInfra]       = useState<InfraData>({ health: null, cache: null, db: null, queues: [] });
  const [infraLoading, setInfraLoading] = useState(true);
  const [flushing, setFlushing] = useState(false);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [infraMsg, setInfraMsg] = useState('');
  const [infraMsgOk, setInfraMsgOk] = useState(true);
  const [actionBusy, setActionBusy] = useState<'kill-switch' | 'maintenance' | null>(null);
  const [actionMsg, setActionMsg]   = useState('');
  const [actionMsgOk, setActionMsgOk] = useState(true);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    setError('');
    try {
      const res = await superadminApi.overview();
      if (!mountedRef.current) return;
      setData(res.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load overview'));
    } finally {
      if (mountedRef.current) setLoading(false);
      if (mountedRef.current) setRefreshing(false);
    }
  }, []);

  const loadInfra = useCallback(async () => {
    setInfraLoading(true);
    try {
      const [hRes, cRes, dRes, qRes] = await Promise.allSettled([
        superadminApi.infraHealth(),
        superadminApi.cacheStats(),
        superadminApi.dbStats(),
        superadminApi.queueStats(),
      ]);
      if (!mountedRef.current) return;
      setInfra({
        health: hRes.status === 'fulfilled' ? hRes.value.data : null,
        cache:  cRes.status === 'fulfilled' ? cRes.value.data : null,
        db:     dRes.status === 'fulfilled' ? dRes.value.data : null,
        queues: qRes.status === 'fulfilled' ? (qRes.value.data.queues ?? qRes.value.data ?? []) : [],
      });
    } finally {
      if (mountedRef.current) setInfraLoading(false);
    }
  }, []);

  const flushCache = async () => {
    setFlushing(true); setInfraMsg('');
    try {
      await superadminApi.flushCache();
      setInfraMsgOk(true);
      setInfraMsg('Cache flushed successfully');
      setTimeout(loadInfra, 800);
    } catch (e: unknown) {
      setInfraMsgOk(false);
      setInfraMsg(extractApiError(e, 'Cache flush failed'));
    } finally { setFlushing(false); }
  };

  // Toggle kill-switch — calls POST /superadmin/engine/kill-switch
  const toggleKillSwitch = async () => {
    if (!data) return;
    const enabling = !data.kill_switch_active;
    setActionBusy('kill-switch'); setActionMsg('');
    try {
      await superadminApi.killSwitch(enabling);
      setActionMsgOk(true);
      setActionMsg(enabling ? '🛑 Kill switch activated — trading halted' : '▶️ Kill switch deactivated — trading resumed');
      load(true);
    } catch (e: unknown) {
      setActionMsgOk(false);
      setActionMsg(extractApiError(e, 'Kill-switch toggle failed'));
    } finally { if (mountedRef.current) setActionBusy(null); }
  };

  // Toggle maintenance mode — calls POST /superadmin/platform/maintenance
  const toggleMaintenance = async () => {
    if (!data) return;
    const enabling = !data.maintenance_mode;
    setActionBusy('maintenance'); setActionMsg('');
    try {
      await superadminApi.maintenanceMode(enabling, enabling ? 'Maintenance started from Overview' : undefined);
      setActionMsgOk(true);
      setActionMsg(enabling ? '🔧 Maintenance mode enabled' : '✅ Maintenance mode disabled');
      load(true);
    } catch (e: unknown) {
      setActionMsgOk(false);
      setActionMsg(extractApiError(e, 'Maintenance toggle failed'));
    } finally { if (mountedRef.current) setActionBusy(null); }
  };

  useEffect(() => { load(); loadInfra(); }, [load, loadInfra]);

  // Auto-refresh every 30s — pauses when tab is hidden
  usePolling(() => { load(true); loadInfra(); }, 30_000);

  if (loading) return (
    <div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14, marginBottom: 20 }}>
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} style={{ height: 100, borderRadius: 12, background: '#1e293b', animation: 'sa-pulse 1.5s ease-in-out infinite' }} />
        ))}
      </div>
      <LoadingRows rows={4} />
    </div>
  );

  if (error) return <ErrorState message={error} onRetry={() => load()} />;
  if (!data) return null;

  const alerts: { level: 'info' | 'warn' | 'critical'; message: string }[] = [];
  if (data.kill_switch_active) alerts.push({ level: 'warn', message: 'Kill switch is ACTIVE — all trading halted (operator control)' });
  if (data.maintenance_mode)   alerts.push({ level: 'warn',     message: 'Platform is in maintenance mode — users see downtime page' });
  if ((data.error_rate_pct ?? 0) > 5) alerts.push({ level: 'critical', message: `Error rate elevated: ${fmtPct(data.error_rate_pct ?? 0)} (threshold: 5%)` });
  if ((data.cpu_pct ?? 0) > 85)       alerts.push({ level: 'warn',     message: `CPU usage high: ${fmtPct(data.cpu_pct ?? 0)}` });
  if ((data.memory_pct ?? 0) > 85)    alerts.push({ level: 'warn',     message: `Memory usage high: ${fmtPct(data.memory_pct ?? 0)}` });
  if (data.system_health === 'degraded')  alerts.push({ level: 'warn',     message: 'System health is degraded — check service logs' });
  if (data.system_health === 'critical')  alerts.push({ level: 'critical', message: 'System health is CRITICAL — immediate action required' });

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>


      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <StatusBadge status={data.system_health} />
          <span style={{ fontSize: 12, color: '#475569' }}>
            Uptime {fmtPct(data.uptime_pct ?? 0)} · Engine: <span style={{ color: data.engine_status === 'running' ? '#4ade80' : '#f87171' }}>{data.engine_status}</span>
          </span>
        </div>
        <ActionBtn
          label={refreshing ? 'Refreshing…' : 'Refresh'}
          onClick={() => load(true)}
          loading={refreshing}
          icon="🔄"
          size="sm"
        />
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          {alerts.map((a, i) => <AlertRow key={i} level={a.level} message={a.message} />)}
        </div>
      )}

      {/* KPI grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 14, marginBottom: 24 }}>
        <KpiTile label="Total Users"        value={fmt(data.total_users)}          icon="👥" accent="#3b82f6" sub="all time" />
        {/* trend was hardcoded "up", so a week with no signups still rendered an
            upward arrow next to "+0 this week". */}
        <KpiTile label="Active (24h)"       value={fmt(data.active_users_24h)}     icon="🟢" accent="#22c55e" trend={data.new_users_7d > 0 ? "up" : data.new_users_7d < 0 ? "down" : undefined} trendValue={`${data.new_users_7d >= 0 ? "+" : ""}${data.new_users_7d} this week`} />
        <KpiTile label="Revenue MTD"        value={fmtMoney(data.revenue_mtd, data.revenue_currency)} icon="💰" accent="#f59e0b" />
        <KpiTile label="Trades Today"       value={fmt(data.total_trades_today)}   icon="📊" accent="#8b5cf6" />
        <KpiTile label="Open Positions"     value={data.open_positions}            icon="📈" accent="#06b6d4" />
        <KpiTile label="Active Sessions"    value={data.active_sessions}           icon="🔗" accent="#ec4899" />
        <KpiTile label="ML Accuracy"        value={fmtPct((data.ml_model_accuracy ?? 0) * 100)} icon="🧠" accent="#a78bfa" />
        <KpiTile label="Signals Today"      value={fmt(data.signals_generated_today)} icon="📡" accent="#34d399" />
      </div>

      {/* Infrastructure + Response */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        <SectionCard title="Infrastructure" icon="🖥️" accent="#3b82f6">
          <GaugeBar label="CPU Usage"    value={data.cpu_pct}    color="#3b82f6" />
          <GaugeBar label="Memory"       value={data.memory_pct} color="#8b5cf6" />
          <GaugeBar label="DB Connections" value={data.db_connections} max={200} color="#06b6d4" unit="" />
          <GaugeBar label="Redis Memory" value={data.redis_memory_mb} max={2048} color="#f59e0b" unit=" MB" />
        </SectionCard>

        <SectionCard title="API Performance" icon="⚡" accent="#f59e0b">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {[
              { label: 'Avg Response', value: `${data.avg_response_ms ?? 0}ms`, ok: (data.avg_response_ms ?? 0) < 200 },
              { label: 'Error Rate',   value: fmtPct(data.error_rate_pct ?? 0), ok: (data.error_rate_pct ?? 0) < 1 },
              { label: 'Uptime',       value: fmtPct(data.uptime_pct ?? 0),     ok: (data.uptime_pct ?? 0) > 99 },
              { label: 'Engine',       value: data.engine_status,          ok: data.engine_status === 'running' },
            ].map(m => (
              <div key={m.label} style={{
                background: '#1e293b', borderRadius: 8, padding: '12px 14px',
                border: `1px solid ${m.ok ? '#16a34a33' : '#dc262633'}`,
              }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: m.ok ? '#4ade80' : '#f87171' }}>{m.value}</div>
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      {/* Quick actions */}
      <SectionCard title="Quick Actions" icon="⚡" accent="#ef4444"
        subtitle="Immediate platform controls — use with caution">
        <ActionBanner message={actionMsg} ok={actionMsgOk} />
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <ActionBtn label="View All Users"     onClick={() => navigateTo('users')}           icon="👥" variant="primary" />
          <ActionBtn label="Feature Flags"      onClick={() => navigateTo('feature-flags')}   icon="🚩" variant="primary" />
          <ActionBtn label="System Logs"        onClick={() => navigateTo('logs')}             icon="📋" variant="ghost" />
          <ActionBtn label="ML Models"          onClick={() => navigateTo('ml-ai')}            icon="🧠" variant="ghost" />
          <ActionBtn label="Security Events"    onClick={() => navigateTo('security')}         icon="🛡️" variant="ghost" />
          {data.kill_switch_active
            ? <ActionBtn label="Resume Trading" onClick={toggleKillSwitch} loading={actionBusy === 'kill-switch'} icon="▶️" variant="success" />
            : <ActionBtn label="Kill Switch"    onClick={toggleKillSwitch} loading={actionBusy === 'kill-switch'} icon="🛑" variant="danger" />
          }
          {data.maintenance_mode
            ? <ActionBtn label="Disable Maintenance" onClick={toggleMaintenance} loading={actionBusy === 'maintenance'} icon="✅" variant="success" />
            : <ActionBtn label="Maintenance Mode"    onClick={toggleMaintenance} loading={actionBusy === 'maintenance'} icon="🔧" variant="warning" />
          }
        </div>
      </SectionCard>

      {/* ── Infrastructure Details ── */}
      <SectionCard title="Infrastructure Details" icon="🖥️" accent="#06b6d4"
        subtitle="Live metrics from infraHealth, Redis cache, database, and task queues"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <ActionBtn label="Flush Cache" onClick={flushCache} loading={flushing} icon="🗑️" size="sm" variant="warning" />
            <ActionBtn label="Refresh"     onClick={loadInfra}  loading={infraLoading} icon="🔄" size="sm" />
          </div>
        }>
        {infraLoading ? <LoadingRows rows={3} /> : (
          <>
            <ActionBanner message={infraMsg} ok={infraMsgOk} />

            {/* Server Resources */}
            {infra.health && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Server Resources</div>
                  <GaugeBar label="CPU"          value={infra.health.cpu_pct}         color="#3b82f6" />
                  <GaugeBar label="Memory"       value={infra.health.mem_pct}         color="#8b5cf6" />
                  <GaugeBar label="Disk"         value={infra.health.disk_pct}        color="#f59e0b" />
                  <GaugeBar label="Network In"   value={infra.health.network_in_mbps}  max={1000} color="#22c55e" unit=" Mbps" />
                  <GaugeBar label="Network Out"  value={infra.health.network_out_mbps} max={1000} color="#06b6d4" unit=" Mbps" />
                  <div style={{ marginTop: 8, display: 'flex', gap: 16 }}>
                    {[
                      { label: 'Load 1m',  v: (infra.health.load_avg_1m  ?? 0).toFixed(2) },
                      { label: 'Load 5m',  v: (infra.health.load_avg_5m  ?? 0).toFixed(2) },
                      { label: 'Load 15m', v: (infra.health.load_avg_15m ?? 0).toFixed(2) },
                    ].map(l => (
                      <div key={l.label} style={{ background: '#1e293b', borderRadius: 6, padding: '6px 10px', flex: 1 }}>
                        <div style={{ fontSize: 10, color: '#475569' }}>{l.label}</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8' }}>{l.v}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Cache + DB */}
                <div>
                  {infra.cache && (
                    <>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Redis Cache</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 16 }}>
                        {[
                          { label: 'Hit Rate',     value: `${(infra.cache.hit_rate_pct ?? 0).toFixed(1)}%`, color: (infra.cache.hit_rate_pct ?? 0) > 80 ? '#4ade80' : '#fbbf24' },
                          { label: 'Total Keys',   value: (infra.cache.total_keys   ?? 0).toLocaleString(), color: '#94a3b8' },
                          { label: 'Memory',       value: `${infra.cache.memory_used_mb ?? 0} MB`,          color: '#60a5fa' },
                          { label: 'Evictions',    value: (infra.cache.evictions    ?? 0).toLocaleString(), color: (infra.cache.evictions ?? 0) > 100 ? '#f87171' : '#4ade80' },
                          { label: 'Clients',      value: infra.cache.connected_clients ?? 0,               color: '#94a3b8' },
                          { label: 'Ops/sec',      value: (infra.cache.ops_per_sec  ?? 0).toLocaleString(), color: '#a78bfa' },
                        ].map(m => (
                          <div key={m.label} style={{ background: '#0f172a', borderRadius: 6, padding: '8px 10px' }}>
                            <div style={{ fontSize: 10, color: '#475569' }}>{m.label}</div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: m.color }}>{m.value}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                  {infra.db && (
                    <>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Database</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                        {[
                          { label: 'Connections',  value: `${infra.db.active_connections ?? 0}/${infra.db.max_connections ?? 0}`, color: ((infra.db.active_connections ?? 0) / (infra.db.max_connections || 1)) > 0.8 ? '#f87171' : '#4ade80' },
                          { label: 'Avg Query',    value: `${(infra.db.query_time_avg_ms ?? 0).toFixed(1)}ms`,               color: (infra.db.query_time_avg_ms ?? 0) > 100 ? '#fbbf24' : '#4ade80' },
                          { label: 'DB Size',      value: `${(infra.db.size_mb ?? 0).toFixed(0)} MB`,                        color: '#60a5fa' },
                          { label: 'Slow Queries', value: infra.db.slow_queries ?? 0,                                        color: (infra.db.slow_queries ?? 0) > 0 ? '#f87171' : '#4ade80' },
                          { label: 'Deadlocks',    value: infra.db.deadlocks ?? 0,                                           color: (infra.db.deadlocks ?? 0) > 0 ? '#f87171' : '#4ade80' },
                        ].map(m => (
                          <div key={m.label} style={{ background: '#0f172a', borderRadius: 6, padding: '8px 10px' }}>
                            <div style={{ fontSize: 10, color: '#475569' }}>{m.label}</div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: m.color }}>{m.value}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Task Queues */}
            {infra.queues.length > 0 && (
              <>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Task Queues</div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #1e293b' }}>
                        {['Queue', 'Pending', 'Processing', 'Failed', 'Workers'].map(h => (
                          <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {infra.queues.map((q) => (
                        <tr key={q.name} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                          <td style={{ padding: '8px 12px', fontWeight: 600, color: '#f1f5f9' }}>{q.name}</td>
                          <td style={{ padding: '8px 12px', color: (q.pending ?? 0) > 100 ? '#fbbf24' : '#94a3b8', fontWeight: (q.pending ?? 0) > 100 ? 700 : 400 }}>{(q.pending ?? 0).toLocaleString()}</td>
                          <td style={{ padding: '8px 12px', color: '#60a5fa' }}>{(q.processing ?? 0).toLocaleString()}</td>
                          <td style={{ padding: '8px 12px', color: (q.failed ?? 0) > 0 ? '#f87171' : '#4ade80', fontWeight: (q.failed ?? 0) > 0 ? 700 : 400 }}>{(q.failed ?? 0).toLocaleString()}</td>
                          <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{q.workers}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </SectionCard>
    </div>
  );
};

export default OverviewSection;
