import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Circle, ShieldAlert, RefreshCw, LayoutDashboard } from 'lucide-react';
import { api } from '../hooks/useApi';
import { useStore, selectWsStatus } from '../store';

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

/** GET /status/live-trading/gate — may the engine trade live right now. */
interface LiveGate {
  allowed: boolean;
  reason?: string;
  checked_at?: string;
  checks?: Record<string, { passed: boolean; message?: string }>;
}

/** GET /status/paper-trading/gate — progress through the validation phases. */
interface PaperGate {
  elapsed_days?: number;
  fill_count?: number;
  phase2_ready?: boolean;
  phase2_reason?: string;
  phase3_ready?: boolean;
  phase3_reason?: string;
}

/** GET /status/sharpe-progress — trades collected toward a stable Sharpe. */
interface SharpeProgress {
  trade_count?: number;
  n_needed?: number;
  pct_complete?: number;
  sharpe?: number;
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
  // `/status/live-trading/gate`, `/status/paper-trading/gate` and
  // `/status/sharpe-progress` are served by the backend and had no caller
  // anywhere in the SPA (audit F185/F230). They answer the question a
  // subscriber actually has on a status page: is the system allowed to trade
  // live right now, and if not, how far off is it.
  const [liveGate, setLiveGate]   = useState<LiveGate | null>(null);
  const [paperGate, setPaperGate] = useState<PaperGate | null>(null);
  const [sharpe, setSharpe]       = useState<SharpeProgress | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [statusRes, histRes, incidentRes, liveRes, paperRes, sharpeRes] =
        await Promise.allSettled([
          api.get<StatusData>('/status/json'),
          api.get<{ history?: HistoryDay[] }>('/status/history'),
          api.get<{ incidents: Incident[] }>('/status/incidents'),
          api.get<LiveGate>('/status/live-trading/gate'),
          api.get<PaperGate>('/status/paper-trading/gate'),
          api.get<SharpeProgress>('/status/sharpe-progress'),
        ]);
      if (!mountedRef.current) return;
      // Each is independent: a readiness endpoint being down must not blank
      // the whole status page.
      setLiveGate(liveRes.status === 'fulfilled' ? liveRes.value.data : null);
      setPaperGate(paperRes.status === 'fulfilled' ? paperRes.value.data : null);
      setSharpe(sharpeRes.status === 'fulfilled' ? sharpeRes.value.data : null);
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
    return <div className="page-content"><p style={{ color: '#64748b' }}>Checking system status…</p></div>;
  }

  if (error || !data) {
    return (
      <div className="page-content">
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
    <div className="page-content">
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
          <button
            onClick={() => navigate('/dashboard')}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-3.5 text-xs font-bold
                       text-[#60a5fa] cursor-pointer transition-colors duration-150
                       hover:bg-[rgba(59,130,246,0.25)] focus-visible:outline-none
                       focus-visible:ring-2 focus-visible:ring-sky-500"
            style={{ background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.4)' }}
          >
            <LayoutDashboard size={14} strokeWidth={1.75} aria-hidden /> Dashboard
          </button>
          <button
            onClick={load}
            title="Refresh now"
            aria-label="Refresh status now"
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg
                       text-slate-400 cursor-pointer transition-colors duration-150
                       hover:bg-[#1e2d3d] focus-visible:outline-none focus-visible:ring-2
                       focus-visible:ring-sky-500"
          >
            <RefreshCw size={15} strokeWidth={2} aria-hidden />
          </button>
        </div>
      </div>

      {/* ── Trading readiness — surfaces /status/live-trading/gate,
             /status/paper-trading/gate and /status/sharpe-progress, none of
             which had a caller anywhere in the SPA (F185/F230). ── */}
      {(liveGate || paperGate || sharpe) && (
        <section aria-labelledby="readiness-h" style={{ marginBottom: 16 }}>
          <h2 id="readiness-h" style={{
            fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.08em', color: '#475569', margin: '0 0 8px 2px',
          }}>
            Trading readiness
          </h2>

          {liveGate && (
            <div style={{
              display: 'flex', alignItems: 'flex-start', gap: 12,
              background: liveGate.allowed ? 'rgba(34,197,94,0.08)' : 'rgba(251,191,36,0.08)',
              border: `1px solid ${liveGate.allowed ? 'rgba(34,197,94,0.3)' : 'rgba(251,191,36,0.3)'}`,
              borderRadius: 10, padding: '12px 16px', marginBottom: 10,
            }}>
              {liveGate.allowed
                ? <CheckCircle2 size={18} strokeWidth={2} aria-hidden style={{ color: '#22c55e', flexShrink: 0, marginTop: 1 }} />
                : <ShieldAlert size={18} strokeWidth={2} aria-hidden style={{ color: '#fbbf24', flexShrink: 0, marginTop: 1 }} />}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: liveGate.allowed ? '#22c55e' : '#fbbf24' }}>
                  {liveGate.allowed
                    ? 'Live trading is permitted'
                    : 'Live trading is blocked'}
                </div>
                {liveGate.reason && (
                  <p style={{ margin: '4px 0 0', fontSize: 12.5, lineHeight: 1.55, color: '#94a3b8' }}>
                    {liveGate.reason}
                  </p>
                )}
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
            {sharpe && (
              <div style={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 10, padding: '12px 14px' }}>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#475569' }}>
                  Statistical confidence
                </div>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0', fontFamily: 'ui-monospace, monospace', marginTop: 4 }}>
                  {sharpe.trade_count ?? 0} / {sharpe.n_needed ?? '—'} trades
                </div>
                {/* Progress toward a Sharpe the platform will trust. */}
                <div
                  role="progressbar"
                  aria-valuenow={Math.round(sharpe.pct_complete ?? 0)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Progress toward a statistically stable Sharpe ratio"
                  style={{ height: 6, borderRadius: 3, background: '#1e2d3d', marginTop: 8, overflow: 'hidden' }}
                >
                  <div style={{
                    width: `${Math.min(100, Math.max(0, sharpe.pct_complete ?? 0))}%`,
                    height: '100%', background: '#00d4ff', transition: 'width 0.3s',
                  }} />
                </div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 6 }}>
                  {(sharpe.pct_complete ?? 0).toFixed(1)}% of the sample needed for a stable Sharpe
                </div>
              </div>
            )}

            {paperGate && (
              <div style={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 10, padding: '12px 14px' }}>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#475569' }}>
                  Validation phases
                </div>
                <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {[
                    { n: 'Phase 2 — anomaly weighting', ok: paperGate.phase2_ready, why: paperGate.phase2_reason },
                    { n: 'Phase 3 — online learning',   ok: paperGate.phase3_ready, why: paperGate.phase3_reason },
                  ].map((ph) => (
                    <li key={ph.n} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                      {ph.ok
                        ? <CheckCircle2 size={13} strokeWidth={2.5} aria-hidden style={{ color: '#22c55e', flexShrink: 0, marginTop: 2 }} />
                        : <Circle size={13} strokeWidth={2} aria-hidden style={{ color: '#475569', flexShrink: 0, marginTop: 2 }} />}
                      <span style={{ minWidth: 0 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: ph.ok ? '#22c55e' : '#94a3b8' }}>{ph.n}</span>
                        {ph.why && <span style={{ display: 'block', fontSize: 11, color: '#64748b', lineHeight: 1.5 }}>{ph.why}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 8 }}>
                  {paperGate.fill_count ?? 0} fills over {paperGate.elapsed_days ?? 0} days
                </div>
              </div>
            )}
          </div>
        </section>
      )}

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
