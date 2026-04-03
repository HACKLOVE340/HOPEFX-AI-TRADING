// superadmin/OverviewSection.tsx — platform-wide KPI overview
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  KpiTile, SectionCard, StatusBadge, ActionBtn,
  Spinner, ErrorState, LoadingRows, SAStyles,
} from './ui';
import type { PlatformOverview } from './types';

const fmt = (n: number) => n >= 1_000_000
  ? `${(n / 1_000_000).toFixed(2)}M`
  : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n);

const fmtMoney = (n: number, cur = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(n);

const fmtPct = (n: number) => `${n.toFixed(1)}%`;

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
  const [data, setData] = useState<PlatformOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    setError('');
    try {
      const res = await superadminApi.overview();
      setData(res.data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as { message?: string })?.message ?? 'Failed to load overview';
      setError(msg);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 30s
  useEffect(() => {
    const id = setInterval(() => load(true), 30_000);
    return () => clearInterval(id);
  }, [load]);

  if (loading) return (
    <div>
      <SAStyles />
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
  if (data.kill_switch_active) alerts.push({ level: 'critical', message: 'Kill switch is ACTIVE — all trading halted' });
  if (data.maintenance_mode)   alerts.push({ level: 'warn',     message: 'Platform is in maintenance mode — users see downtime page' });
  if (data.error_rate_pct > 5) alerts.push({ level: 'critical', message: `Error rate elevated: ${fmtPct(data.error_rate_pct)} (threshold: 5%)` });
  if (data.cpu_pct > 85)       alerts.push({ level: 'warn',     message: `CPU usage high: ${fmtPct(data.cpu_pct)}` });
  if (data.memory_pct > 85)    alerts.push({ level: 'warn',     message: `Memory usage high: ${fmtPct(data.memory_pct)}` });
  if (data.system_health === 'degraded')  alerts.push({ level: 'warn',     message: 'System health is degraded — check service logs' });
  if (data.system_health === 'critical')  alerts.push({ level: 'critical', message: 'System health is CRITICAL — immediate action required' });

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />

      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <StatusBadge status={data.system_health} />
          <span style={{ fontSize: 12, color: '#475569' }}>
            Uptime {fmtPct(data.uptime_pct)} · Engine: <span style={{ color: data.engine_status === 'running' ? '#4ade80' : '#f87171' }}>{data.engine_status}</span>
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
        <KpiTile label="Active (24h)"       value={fmt(data.active_users_24h)}     icon="🟢" accent="#22c55e" trend="up" trendValue={`+${data.new_users_7d} this week`} />
        <KpiTile label="Revenue MTD"        value={fmtMoney(data.revenue_mtd, data.revenue_currency)} icon="💰" accent="#f59e0b" />
        <KpiTile label="Trades Today"       value={fmt(data.total_trades_today)}   icon="📊" accent="#8b5cf6" />
        <KpiTile label="Open Positions"     value={data.open_positions}            icon="📈" accent="#06b6d4" />
        <KpiTile label="Active Sessions"    value={data.active_sessions}           icon="🔗" accent="#ec4899" />
        <KpiTile label="ML Accuracy"        value={`${data.ml_model_accuracy.toFixed(1)}%`} icon="🧠" accent="#a78bfa" />
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
              { label: 'Avg Response', value: `${data.avg_response_ms}ms`, ok: data.avg_response_ms < 200 },
              { label: 'Error Rate',   value: fmtPct(data.error_rate_pct), ok: data.error_rate_pct < 1 },
              { label: 'Uptime',       value: fmtPct(data.uptime_pct),     ok: data.uptime_pct > 99 },
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
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <ActionBtn label="View All Users"     onClick={() => {}} icon="👥" variant="primary" />
          <ActionBtn label="Feature Flags"      onClick={() => {}} icon="🚩" variant="primary" />
          <ActionBtn label="System Logs"        onClick={() => {}} icon="📋" variant="ghost" />
          <ActionBtn label="ML Models"          onClick={() => {}} icon="🧠" variant="ghost" />
          <ActionBtn label="Security Events"    onClick={() => {}} icon="🛡️" variant="ghost" />
          {data.kill_switch_active
            ? <ActionBtn label="Resume Trading" onClick={() => {}} icon="▶️" variant="success" />
            : <ActionBtn label="Kill Switch"    onClick={() => {}} icon="🛑" variant="danger" />
          }
          {data.maintenance_mode
            ? <ActionBtn label="Disable Maintenance" onClick={() => {}} icon="✅" variant="success" />
            : <ActionBtn label="Maintenance Mode"    onClick={() => {}} icon="🔧" variant="warning" />
          }
        </div>
      </SectionCard>
    </div>
  );
};

export default OverviewSection;
