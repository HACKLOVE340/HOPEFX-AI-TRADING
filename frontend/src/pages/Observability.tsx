/**
 * Observability — live platform telemetry (services, metrics, alerts).
 *
 * Wires to the roadmap observability router:
 *   GET /api/observability/metrics
 *   GET /api/observability/services
 *   GET /api/observability/alerts
 * Admin/ops surface — gated at the route level.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { observabilityApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

interface Metrics {
  cpu_percent?: number; memory_percent?: number; request_rate?: number;
  error_rate?: number; active_connections?: number; timestamp?: string;
}
interface Service {
  name: string; status: string; uptime_seconds?: number; version?: string; last_heartbeat?: string;
}
interface Alert {
  id?: string; severity?: string; message?: string; service?: string; timestamp?: string;
}

const SEV_COLOR: Record<string, string> = {
  critical: '#f87171', warning: '#fbbf24', info: '#60a5fa',
};

function fmtUptime(s?: number): string {
  if (!s || s <= 0) return '—';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

const Observability: React.FC = () => {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [services, setServices] = useState<Service[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const mountedRef = useRef(true);

  const load = useCallback(async () => {
    setErr('');
    const [m, s, a] = await Promise.allSettled([
      observabilityApi.metrics(),
      observabilityApi.services(),
      observabilityApi.alerts(),
    ]);
    if (!mountedRef.current) return;
    if (m.status === 'fulfilled') setMetrics(m.value.data ?? null);
    if (s.status === 'fulfilled') setServices(s.value.data?.services ?? []);
    if (a.status === 'fulfilled') setAlerts(a.value.data?.alerts ?? []);
    if (m.status === 'rejected' && s.status === 'rejected' && a.status === 'rejected') {
      setErr(extractApiError(m.reason, 'Failed to load observability data.'));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load();
    const id = window.setInterval(load, 15000);
    return () => { mountedRef.current = false; window.clearInterval(id); };
  }, [load]);

  const tiles: { label: string; value: string }[] = [
    { label: 'CPU', value: metrics?.cpu_percent != null ? `${metrics.cpu_percent.toFixed(1)}%` : '—' },
    { label: 'Memory', value: metrics?.memory_percent != null ? `${metrics.memory_percent.toFixed(1)}%` : '—' },
    { label: 'Req/s', value: metrics?.request_rate != null ? metrics.request_rate.toFixed(1) : '—' },
    { label: 'Error rate', value: metrics?.error_rate != null ? `${(metrics.error_rate * 100).toFixed(2)}%` : '—' },
    { label: 'Connections', value: metrics?.active_connections != null ? String(metrics.active_connections) : '—' },
  ];

  return (
    <div style={{ padding: 20, maxWidth: 1200, margin: '0 auto', color: '#e2e8f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>📡 Observability</h1>
        <button onClick={load} style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
          ↻ Refresh
        </button>
      </div>

      {loading && <div style={{ color: '#64748b', padding: 20 }}>Loading telemetry…</div>}
      {!loading && err && (
        <div style={{ padding: '12px 16px', background: '#2a1215', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', marginBottom: 16 }}>{err}</div>
      )}

      {!loading && (
        <>
          {/* Metrics strip */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
            {tiles.map((t) => (
              <div key={t.label} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{t.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{t.value}</div>
              </div>
            ))}
          </div>

          {/* Services */}
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#94a3b8', margin: '0 0 10px' }}>Services</h2>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 12, marginBottom: 20 }}>
            {services.length === 0 ? (
              <div style={{ color: '#64748b', padding: 8 }}>No service data.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {services.map((s) => (
                  <div key={s.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, padding: '8px 10px', background: '#0f172a', borderRadius: 8 }}>
                    <span style={{ fontWeight: 600 }}>{s.name}</span>
                    <span style={{ display: 'flex', gap: 14, alignItems: 'center', fontSize: 12, color: '#94a3b8' }}>
                      <span>up {fmtUptime(s.uptime_seconds)}</span>
                      <span>v{s.version ?? '—'}</span>
                      <span style={{ color: (s.status === 'active' || s.status === 'healthy' || s.status === 'ok') ? '#4ade80' : '#fbbf24', fontWeight: 700, textTransform: 'uppercase', fontSize: 11 }}>{s.status}</span>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Alerts */}
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#94a3b8', margin: '0 0 10px' }}>Recent Alerts</h2>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 12 }}>
            {alerts.length === 0 ? (
              <div style={{ color: '#64748b', padding: 8 }}>No active alerts. 🎉</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {alerts.map((a, i) => (
                  <div key={a.id ?? i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '8px 10px', background: '#0f172a', borderRadius: 8 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', marginTop: 6, flexShrink: 0, background: SEV_COLOR[(a.severity ?? 'info').toLowerCase()] ?? '#60a5fa' }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13 }}>{a.message ?? '(no message)'}</div>
                      <div style={{ fontSize: 11, color: '#64748b' }}>{a.service ?? ''}{a.timestamp ? ` · ${a.timestamp}` : ''}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default Observability;
