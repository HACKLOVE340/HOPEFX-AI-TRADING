// settings/PerformanceSection.tsx
// Real-time system performance dashboard wired to /api/admin/settings/performance.
// Polls every 5 s. No mocks — all data comes from live psutil + Redis + DB pool.

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../hooks/useApi';
import { Card, SectionHeader, Button, StatusBadge } from './ui';
import { extractApiError } from '../../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface CpuMetrics {
  percent: number;
  count_logical: number;
  count_physical: number;
  freq_mhz: number | null;
  freq_max_mhz: number | null;
  load_avg_1m: number | null;
  load_avg_5m: number | null;
}

interface MemoryMetrics {
  total_mb: number;
  used_mb: number;
  available_mb: number;
  percent: number;
}

interface DiskMetrics {
  total_gb: number;
  used_gb: number;
  free_gb: number;
  percent: number;
  read_mb?: number;
  write_mb?: number;
}

interface NetworkMetrics {
  bytes_sent_mb: number;
  bytes_recv_mb: number;
  packets_sent: number;
  packets_recv: number;
  errin: number;
  errout: number;
  dropin: number;
  dropout: number;
}

interface ProcessMetrics {
  pid: number;
  rss_mb: number;
  vms_mb: number;
  cpu_percent: number;
  threads: number;
  open_files: number;
  uptime_seconds: number;
}

interface RedisMetrics {
  connected: boolean;
  latency_ms?: number;
  version?: string;
  used_memory_mb?: number;
  connected_clients?: number;
  uptime_seconds?: number;
  ops_per_sec?: number;
  error?: string;
}

interface DatabaseMetrics {
  pool_size?: number;
  checked_out?: number;
  overflow?: number;
  checked_in?: number;
}

interface ComponentMetric {
  name: string;
  status: string;
  latency_ms: number | null;
  critical: boolean;
}

interface PerformanceData {
  cpu: CpuMetrics;
  memory: MemoryMetrics;
  disk: DiskMetrics;
  network: NetworkMetrics;
  process: ProcessMetrics;
  redis: RedisMetrics;
  database: DatabaseMetrics;
  components: ComponentMetric[];
  collected_at: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function pctColor(pct: number, warn = 70, danger = 90): string {
  if (pct >= danger) return '#f87171';
  if (pct >= warn)   return '#fbbf24';
  return '#4ade80';
}

// ── Sub-components ────────────────────────────────────────────────────────────

const GaugeBar: React.FC<{ pct: number; warn?: number; danger?: number }> = ({
  pct, warn = 70, danger = 90,
}) => (
  <div style={{ height: 6, background: '#0f172a', borderRadius: 3, overflow: 'hidden', marginTop: 6 }}>
    <div style={{
      height: '100%',
      width: `${Math.min(pct, 100)}%`,
      background: pctColor(pct, warn, danger),
      borderRadius: 3,
      transition: 'width 0.5s ease, background 0.5s ease',
    }} />
  </div>
);

const MetricRow: React.FC<{ label: string; value: string; sub?: string; color?: string }> = ({
  label, value, sub, color,
}) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '6px 0', borderBottom: '1px solid #1e293b' }}>
    <span style={{ fontSize: 12, color: '#64748b' }}>{label}</span>
    <span style={{ fontSize: 13, fontWeight: 600, color: color ?? '#e2e8f0', fontFamily: 'JetBrains Mono, monospace' }}>
      {value}
      {sub && <span style={{ fontSize: 11, color: '#64748b', marginLeft: 6 }}>{sub}</span>}
    </span>
  </div>
);

const StatTile: React.FC<{ label: string; value: string; color?: string }> = ({ label, value, color }) => (
  <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
    <div style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 16, fontWeight: 700, color: color ?? '#e2e8f0', fontFamily: 'JetBrains Mono, monospace' }}>{value}</div>
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 5000;

const PerformanceSection: React.FC = () => {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const r = await api.get<PerformanceData>('/admin/settings/performance');
      setData(r.data);
      setLastRefresh(new Date());
      setError('');
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to load performance metrics.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchMetrics, POLL_INTERVAL_MS);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [autoRefresh, fetchMetrics]);

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading performance metrics…
    </div>
  );

  if (error && !data) return (
    <div style={{ padding: 20, color: '#f87171', background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8 }}>
      {error}
    </div>
  );

  const cpu  = data?.cpu;
  const mem  = data?.memory;
  const disk = data?.disk;
  const net  = data?.network;
  const proc = data?.process;
  const redis = data?.redis;
  const db   = data?.database;
  const components = data?.components ?? [];

  return (
    <div>
      <SectionHeader
        icon="📊"
        title="Performance"
        description="Live system resource usage. Auto-refreshes every 5 seconds."
      />

      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Button
          variant={autoRefresh ? 'primary' : 'secondary'}
          size="sm"
          onClick={() => setAutoRefresh((v) => !v)}
        >
          {autoRefresh ? '⏸ Pause' : '▶ Resume'} auto-refresh
        </Button>
        <Button variant="secondary" size="sm" onClick={fetchMetrics}>
          ↻ Refresh now
        </Button>
        {lastRefresh && (
          <span style={{ fontSize: 11, color: '#475569' }}>
            Last updated: {lastRefresh.toLocaleTimeString()}
          </span>
        )}
        {error && (
          <span style={{ fontSize: 12, color: '#fbbf24' }}>⚠ {error}</span>
        )}
      </div>

      {/* Top stat tiles */}
      {cpu && mem && proc && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
          <StatTile label="CPU" value={`${cpu.percent}%`} color={pctColor(cpu.percent)} />
          <StatTile label="Memory" value={`${mem.percent}%`} color={pctColor(mem.percent)} />
          <StatTile label="Process RSS" value={`${proc.rss_mb} MB`} />
          <StatTile label="Uptime" value={fmtUptime(proc.uptime_seconds)} color="#60a5fa" />
        </div>
      )}

      {/* CPU */}
      {cpu && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>CPU</h3>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Utilisation</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: pctColor(cpu.percent), fontFamily: 'monospace' }}>
              {cpu.percent}%
            </span>
          </div>
          <GaugeBar pct={cpu.percent} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, marginTop: 12 }}>
            <MetricRow label="Logical cores" value={String(cpu.count_logical)} />
            <MetricRow label="Physical cores" value={String(cpu.count_physical)} />
            {cpu.freq_mhz != null && (
              <MetricRow label="Frequency" value={`${cpu.freq_mhz} MHz`} sub={cpu.freq_max_mhz ? `/ ${cpu.freq_max_mhz} max` : undefined} />
            )}
            {cpu.load_avg_1m != null && (
              <MetricRow label="Load avg (1m / 5m)" value={`${cpu.load_avg_1m} / ${cpu.load_avg_5m}`} />
            )}
          </div>
        </Card>
      )}

      {/* Memory */}
      {mem && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>Memory</h3>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>System RAM</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: pctColor(mem.percent), fontFamily: 'monospace' }}>
              {mem.used_mb.toLocaleString()} / {mem.total_mb.toLocaleString()} MB ({mem.percent}%)
            </span>
          </div>
          <GaugeBar pct={mem.percent} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, marginTop: 12 }}>
            <MetricRow label="Available" value={`${mem.available_mb.toLocaleString()} MB`} color="#4ade80" />
            <MetricRow label="Used" value={`${mem.used_mb.toLocaleString()} MB`} />
          </div>
        </Card>
      )}

      {/* Process */}
      {proc && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>
            Process (PID {proc.pid})
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
            <MetricRow label="RSS memory" value={`${proc.rss_mb} MB`} />
            <MetricRow label="Virtual memory" value={`${proc.vms_mb} MB`} />
            <MetricRow label="CPU %" value={`${proc.cpu_percent}%`} color={pctColor(proc.cpu_percent, 50, 80)} />
            <MetricRow label="Threads" value={String(proc.threads)} />
            <MetricRow label="Open files" value={String(proc.open_files)} />
            <MetricRow label="Uptime" value={fmtUptime(proc.uptime_seconds)} color="#60a5fa" />
          </div>
        </Card>
      )}

      {/* Disk */}
      {disk && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>Disk</h3>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Usage</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: pctColor(disk.percent, 75, 90), fontFamily: 'monospace' }}>
              {disk.used_gb} / {disk.total_gb} GB ({disk.percent}%)
            </span>
          </div>
          <GaugeBar pct={disk.percent} warn={75} danger={90} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, marginTop: 12 }}>
            <MetricRow label="Free" value={`${disk.free_gb} GB`} color="#4ade80" />
            {disk.read_mb != null && <MetricRow label="Total reads" value={`${disk.read_mb.toLocaleString()} MB`} />}
            {disk.write_mb != null && <MetricRow label="Total writes" value={`${disk.write_mb.toLocaleString()} MB`} />}
          </div>
        </Card>
      )}

      {/* Network */}
      {net && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>Network I/O</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
            <MetricRow label="Sent" value={`${net.bytes_sent_mb.toLocaleString()} MB`} />
            <MetricRow label="Received" value={`${net.bytes_recv_mb.toLocaleString()} MB`} />
            <MetricRow label="Packets sent" value={net.packets_sent.toLocaleString()} />
            <MetricRow label="Packets received" value={net.packets_recv.toLocaleString()} />
            <MetricRow
              label="Errors in / out"
              value={`${net.errin} / ${net.errout}`}
              color={net.errin + net.errout > 0 ? '#f87171' : '#4ade80'}
            />
            <MetricRow
              label="Drops in / out"
              value={`${net.dropin} / ${net.dropout}`}
              color={net.dropin + net.dropout > 0 ? '#fbbf24' : '#4ade80'}
            />
          </div>
        </Card>
      )}

      {/* Redis */}
      {redis && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>Redis</h3>
          {redis.connected ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
              <MetricRow
                label="Latency"
                value={`${redis.latency_ms} ms`}
                color={redis.latency_ms! < 5 ? '#4ade80' : redis.latency_ms! < 20 ? '#fbbf24' : '#f87171'}
              />
              <MetricRow label="Version" value={redis.version ?? '—'} />
              <MetricRow label="Memory used" value={`${redis.used_memory_mb} MB`} />
              <MetricRow label="Connected clients" value={String(redis.connected_clients)} />
              <MetricRow label="Ops/sec" value={String(redis.ops_per_sec)} />
              <MetricRow label="Uptime" value={fmtUptime(redis.uptime_seconds ?? 0)} color="#60a5fa" />
            </div>
          ) : (
            <div style={{ color: '#f87171', fontSize: 13 }}>
              ❌ Not connected{redis.error ? ` — ${redis.error}` : ''}
            </div>
          )}
        </Card>
      )}

      {/* DB pool */}
      {db && Object.keys(db).length > 0 && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>Database Pool</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
            {db.pool_size != null && <MetricRow label="Pool size" value={String(db.pool_size)} />}
            {db.checked_out != null && <MetricRow label="Checked out" value={String(db.checked_out)} />}
            {db.checked_in != null && <MetricRow label="Checked in" value={String(db.checked_in)} />}
            {db.overflow != null && (
              <MetricRow
                label="Overflow"
                value={String(db.overflow)}
                color={db.overflow > 0 ? '#fbbf24' : '#4ade80'}
              />
            )}
          </div>
        </Card>
      )}

      {/* Component latencies */}
      {components.length > 0 && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 12 }}>
            Component Latencies
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {components.map((c) => (
              <div
                key={c.name}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '7px 0',
                  borderBottom: '1px solid #1e293b',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <StatusBadge
                    status={c.status === 'healthy' ? 'ok' : c.status === 'degraded' ? 'warning' : 'error'}
                    label={c.status}
                  />
                  <span style={{ fontSize: 13, color: '#e2e8f0' }}>{c.name}</span>
                  {c.critical && (
                    <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: '#1e3a5f', color: '#60a5fa', border: '1px solid #1e3a5f' }}>
                      CRITICAL
                    </span>
                  )}
                </div>
                <span style={{
                  fontSize: 12,
                  fontFamily: 'JetBrains Mono, monospace',
                  color: c.latency_ms == null ? '#475569'
                    : c.latency_ms < 10 ? '#4ade80'
                    : c.latency_ms < 100 ? '#fbbf24'
                    : '#f87171',
                }}>
                  {c.latency_ms != null ? `${c.latency_ms.toFixed(2)} ms` : '—'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
};

export default PerformanceSection;
