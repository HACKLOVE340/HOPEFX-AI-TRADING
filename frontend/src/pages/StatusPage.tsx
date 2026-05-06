import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { useStore, selectWsStatus } from '../store';
import { Breadcrumb } from '../components/Breadcrumb';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ComponentStatus {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  message: string;
  response_time_ms?: number | null;
}

interface StatusData {
  status: 'healthy' | 'degraded' | 'unhealthy';
  uptime_seconds: number;
  uptime_human: string;
  checked_at: string;
  components: Record<string, ComponentStatus>;
}

interface HistoryDay {
  date: string;
  uptime_pct: number;
}

interface Incident {
  date: string;
  uptime_pct: number;
  severity: 'major' | 'minor';
  title: string;
  resolved: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  healthy:   '#22c55e',
  degraded:  '#f59e0b',
  unhealthy: '#ef4444',
  unknown:   '#64748b',
};

const STATUS_BG: Record<string, string> = {
  healthy:   '#14532d',
  degraded:  '#451a03',
  unhealthy: '#450a0a',
  unknown:   '#1e293b',
};

const STATUS_BORDER: Record<string, string> = {
  healthy:   '#16a34a',
  degraded:  '#d97706',
  unhealthy: '#dc2626',
  unknown:   '#334155',
};

const STATUS_ICON: Record<string, string> = {
  healthy:   '✅',
  degraded:  '⚠️',
  unhealthy: '❌',
  unknown:   '❓',
};

const STATUS_TEXT: Record<string, string> = {
  healthy:   'All systems operational',
  degraded:  'Partial degradation — some services affected',
  unhealthy: 'Service disruption — investigating',
  unknown:   'Status unknown',
};

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });

// ── Sub-components ────────────────────────────────────────────────────────────

const Dot: React.FC<{ status: string }> = ({ status }) => (
  <span style={{
    display: 'inline-block',
    width: 9, height: 9,
    borderRadius: '50%',
    background: STATUS_COLOR[status] ?? '#64748b',
    flexShrink: 0,
  }} />
);

const UptimeBar: React.FC<{ history: HistoryDay[] }> = ({ history }) => (
  <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 32, marginTop: 12 }}>
    {history.map((day) => {
      const pct = day.uptime_pct;
      const h = Math.max(4, Math.round(32 * pct / 100));
      const bg = pct >= 99 ? '#22c55e' : pct >= 90 ? '#f59e0b' : '#ef4444';
      return (
        <div
          key={day.date}
          title={`${day.date}: ${pct.toFixed(1)}%`}
          style={{ flex: 1, height: h, background: bg, borderRadius: 2, minWidth: 2 }}
        />
      );
    })}
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const StatusPage: React.FC = () => {
  const navigate = useNavigate();
  const wsStatus = useStore(selectWsStatus);
  const [data, setData] = useState<StatusData | null>(null);
  const [history, setHistory] = useState<HistoryDay[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [statusRes, histRes, incidentRes] = await Promise.allSettled([
        api.get<StatusData>('/status/json'),
        api.get<{ history?: HistoryDay[] }>('/status/history'),
        api.get<{ incidents: Incident[] }>('/status/incidents'),
      ]);
      if (!mountedRef.current) return;
      if (statusRes.status === 'fulfilled') {
        setData(statusRes.value.data);
      } else {
        setError('Unable to reach the status API. Check your connection.');
        setData(null);
      }
      setHistory(
        histRes.status === 'fulfilled'
          ? (histRes.value.data.history ?? [])
          : []
      );
      setIncidents(
        incidentRes.status === 'fulfilled'
          ? (incidentRes.value.data.incidents ?? [])
          : []
      );
    } catch (err) {
      if (!mountedRef.current) return;
      setError('Status API unavailable.');
    }
    if (mountedRef.current) { setLoading(false); setLastRefresh(new Date()); }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 60_000);
    return () => clearInterval(interval);
  }, [load]);

  if (loading) {
    return <div style={styles.page}><p style={{ color: '#64748b' }}>Checking system status…</p></div>;
  }

  if (error || !data) {
    return (
      <div style={styles.page}>
        <div style={{ ...styles.banner, background: '#450a0a', border: '1px solid #dc2626' }}>
          <span style={{ fontSize: 32 }}>❌</span>
          <div>
            <div style={styles.bannerTitle}>Status unavailable</div>
            <div style={styles.bannerSub}>{error ?? 'No data received from the API.'}</div>
          </div>
          <button onClick={load} style={styles.refreshBtn} title="Retry">↻</button>
        </div>
      </div>
    );
  }

  const status = data?.status ?? 'unknown';
  const components = data?.components ?? {};

  // Compute 30-day uptime from history
  const last30 = history.slice(-30);
  const avg30 = last30.length
    ? last30.reduce((s, d) => s + d.uptime_pct, 0) / last30.length
    : 100;

  return (
    <div style={styles.page}>
      {/* Breadcrumbs */}
      <Breadcrumb items={[
        { label: 'Home', href: '/home' },
        { label: 'System Status' },
      ]} style={{ marginBottom: 16 }} />

      {/* Banner */}
      <div style={{
        ...styles.banner,
        background: STATUS_BG[status],
        border: `1px solid ${STATUS_BORDER[status]}`,
      }}>
        <span style={{ fontSize: 32 }}>{STATUS_ICON[status]}</span>
        <div>
          <div style={styles.bannerTitle}>{STATUS_TEXT[status]}</div>
          <div style={styles.bannerSub}>
            Uptime: {data?.uptime_human ?? '—'} &nbsp;·&nbsp; Checked: {data ? fmtTime(data.checked_at) : '—'}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <Link to="/home"
            style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.4)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
            📊 Dashboard
          </Link>
          <Link to="/docs"
            style={{ padding: '6px 14px', background: 'rgba(100,116,139,0.15)', border: '1px solid rgba(100,116,139,0.4)', borderRadius: 7, color: '#94a3b8', fontSize: 12, fontWeight: 700, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
            📖 Docs
          </Link>
          <button onClick={load} style={styles.refreshBtn} title="Refresh now">↻</button>
        </div>
      </div>

      {/* WebSocket live status */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
        padding: '10px 16px', marginBottom: 16,
      }}>
        <span style={{
          width: 9, height: 9, borderRadius: '50%', flexShrink: 0,
          background: wsStatus === 'connected' ? '#22c55e' : wsStatus === 'connecting' ? '#f59e0b' : '#ef4444',
          boxShadow: wsStatus === 'connected' ? '0 0 6px #22c55e' : 'none',
        }} />
        <span style={{ fontSize: 13, color: '#94a3b8' }}>
          WebSocket feed: <strong style={{ color: wsStatus === 'connected' ? '#22c55e' : wsStatus === 'connecting' ? '#f59e0b' : '#ef4444' }}>
            {wsStatus.charAt(0).toUpperCase() + wsStatus.slice(1)}
          </strong>
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#475569' }}>
          Live market data stream
        </span>
      </div>

      {/* Components */}
      <div style={styles.sectionTitle}>Components</div>
      <div style={styles.componentsCard}>
        {Object.entries(components).map(([name, info], i, arr) => (
          <div
            key={name}
            style={{
              ...styles.componentRow,
              borderBottom: i < arr.length - 1 ? '1px solid #1e293b' : 'none',
            }}
          >
            <div style={styles.componentName}>{name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</div>
            <div style={styles.componentStatus}>
              <Dot status={info.status} />
              <span style={{ color: STATUS_COLOR[info.status], fontWeight: 600, textTransform: 'capitalize', fontSize: 13 }}>
                {info.status}
              </span>
            </div>
            <div style={styles.componentMsg}>
              {info.message}
              {info.response_time_ms != null && (
                <span style={{ color: '#475569', marginLeft: 6 }}>{info.response_time_ms}ms</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Uptime */}
      <div style={styles.sectionTitle}>Uptime</div>
      <div style={styles.uptimeCard}>
        <div style={{ display: 'flex', gap: 32, marginBottom: 16 }}>
          <div>
            <div style={styles.uptimeValue}>{avg30.toFixed(2)}%</div>
            <div style={styles.uptimeLabel}>30-day uptime</div>
          </div>
          <div>
            <div style={{ ...styles.uptimeValue, fontSize: 24 }}>{data?.uptime_human ?? '—'}</div>
            <div style={styles.uptimeLabel}>Current uptime</div>
          </div>
        </div>
        <UptimeBar history={history} />
        <div style={styles.historyLabels}>
          <span>90 days ago</span>
          <span>Today</span>
        </div>
      </div>

      {/* Incident history */}
      <div style={styles.sectionTitle}>Recent incidents</div>
      <div style={styles.incidentCard}>
        {incidents.length === 0 ? (
          <p style={{ color: '#64748b', fontSize: 14 }}>No incidents in the last 90 days.</p>
        ) : (
          incidents.slice(0, 10).map(inc => (
            <div key={inc.date} style={styles.incidentRow}>
              <span style={{ color: inc.severity === 'major' ? '#ef4444' : '#fbbf24' }}>
                {inc.severity === 'major' ? '❌' : '⚠️'}
              </span>
              <span style={{ color: '#e2e8f0', fontWeight: 500 }}>{inc.date}</span>
              <span style={{ color: '#94a3b8', fontSize: 13, flex: 1 }}>{inc.title}</span>
              <span style={{ fontSize: 11, color: inc.resolved ? '#4ade80' : '#fbbf24' }}>
                {inc.resolved ? 'Resolved' : 'Ongoing'}
              </span>
            </div>
          ))
        )}
      </div>

      {/* Cross-links */}
      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 20, marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Related
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
          {[
            { icon: '🔬', label: 'System Reliability', desc: 'OTel tracing & self-tests',       to: '/system-reliability' },
            { icon: '🩺', label: 'Auto-Heal',          desc: 'Self-healing & fix approvals',    to: '/auto-heal' },
            { icon: '🛡️', label: 'Security Ops',       desc: 'Threats & lockdown controls',     to: '/security' },
            { icon: '🔧', label: 'Admin Panel',        desc: 'Platform overview & KPIs',        to: '/admin' },
            { icon: '📖', label: 'Docs',               desc: 'Platform documentation',          to: '/docs' },
          ].map(({ icon, label, desc, to }) => (
            <Link
              key={to}
              to={to}
              style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '12px 16px', textDecoration: 'none' }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#475569'; (e.currentTarget as HTMLAnchorElement).style.background = '#243044'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155'; (e.currentTarget as HTMLAnchorElement).style.background = '#1e293b'; }}
            >
              <span style={{ fontSize: 18, flexShrink: 0 }}>{icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{label}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{desc}</div>
              </div>
              <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 16 }}>›</span>
            </Link>
          ))}
        </div>
      </div>

      <div style={styles.footer}>
        Last refreshed: {lastRefresh.toLocaleTimeString()} &nbsp;·&nbsp;
        Auto-refreshes every 60s &nbsp;·&nbsp;
        <a href="/api/status/json" style={{ color: '#3b82f6' }}>JSON API</a>
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 760,
    margin: '0 auto',
    padding: '32px 16px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    color: '#f1f5f9',
    background: '#0f172a',
    minHeight: '100vh',
  },
  banner: {
    border: '1px solid #334155',
    borderRadius: 12,
    padding: '20px 24px',
    marginBottom: 32,
    display: 'flex',
    alignItems: 'center',
    gap: 16,
  },
  bannerTitle: { fontSize: 18, fontWeight: 700, color: '#f8fafc' },
  bannerSub: { fontSize: 13, color: '#94a3b8', marginTop: 4 },
  refreshBtn: {
    marginLeft: 'auto',
    background: 'transparent',
    border: '1px solid #334155',
    color: '#94a3b8',
    borderRadius: 6,
    padding: '6px 12px',
    fontSize: 18,
    cursor: 'pointer',
    flexShrink: 0,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 10,
  },
  componentsCard: {
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: 12,
    overflow: 'hidden',
    marginBottom: 28,
  },
  componentRow: {
    display: 'grid',
    gridTemplateColumns: '1fr auto 1fr',
    alignItems: 'center',
    padding: '13px 20px',
    gap: 12,
  },
  componentName: { fontSize: 14, fontWeight: 500, color: '#e2e8f0' },
  componentStatus: { display: 'flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap' },
  componentMsg: { fontSize: 12, color: '#64748b', textAlign: 'right' },
  uptimeCard: {
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: 12,
    padding: '20px 24px',
    marginBottom: 28,
  },
  uptimeValue: { fontSize: 36, fontWeight: 800, color: '#4ade80' },
  uptimeLabel: { fontSize: 12, color: '#64748b', marginTop: 2 },
  historyLabels: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 11,
    color: '#475569',
    marginTop: 6,
  },
  incidentCard: {
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: 12,
    padding: '16px 20px',
    marginBottom: 28,
  },
  incidentRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '8px 0',
    borderBottom: '1px solid #1e293b',
    fontSize: 14,
  },
  footer: {
    textAlign: 'center',
    fontSize: 12,
    color: '#475569',
    paddingTop: 8,
  },
};

export default StatusPage;
