/**
 * pages/TCADashboard.tsx
 * Route: /tca
 *
 * Transaction Cost Analysis dashboard.
 *
 * Panels:
 *   - KPI strip: mean slippage, p95 slippage, adverse fill rate, mean latency
 *   - Per-broker slippage table with alert badges
 *   - Per-session breakdown (London / New York / Asia)
 *   - Recent fills table (last 100 records)
 *   - Active slippage alerts
 */

import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';

// ── Types ─────────────────────────────────────────────────────────────────────

interface TCAReport {
  broker: string;
  symbol: string | null;
  session: string | null;
  n_trades: number;
  mean_slippage_bps: number;
  median_slippage_bps: number;
  p95_slippage_bps: number;
  p99_slippage_bps: number;
  std_slippage_bps: number;
  total_slippage_usd: number;
  mean_latency_ms: number;
  p95_latency_ms: number;
  mean_signal_to_fill_ms: number;
  adverse_fill_rate: number;
  price_improvement_rate: number;
  alert_triggered: boolean;
  generated_at: string;
}

interface TCARecord {
  request_id: string;
  symbol: string;
  side: string;
  signal_price: number;
  fill_price: number;
  filled_quantity: number;
  slippage_bps: number;
  slippage_usd: number;
  broker: string;
  latency_ms: number;
  signal_to_fill_ms: number;
  model_version: string;
  session: string;
  signal_time: string;
  fill_time: string;
}

interface TCAAlert {
  broker: string;
  symbol: string | null;
  mean_slippage_bps: number;
  p95_slippage_bps: number;
  threshold_bps: number;
  n_trades: number;
  generated_at: string;
}

interface TCAStats {
  n_trades: number;
  mean_slippage_bps: number;
  median_slippage_bps: number;
  p95_slippage_bps: number;
  p99_slippage_bps: number;
  adverse_fill_rate: number;
  price_improvement_rate: number;
  mean_latency_ms: number;
  p95_latency_ms: number;
  mean_signal_to_fill_ms: number;
  by_session: Record<string, { n_trades: number; mean_slippage_bps: number; adverse_rate: number }>;
  by_broker: Record<string, { n_trades: number; mean_slippage_bps: number; p95_slippage_bps: number }>;
  message?: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────

const API_BASE = import.meta.env.VITE_API_URL ?? '';

function authHeader(): Record<string, string> {
  const token = localStorage.getItem('token') ?? sessionStorage.getItem('token') ?? '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchReports(): Promise<TCAReport[]> {
  const { data } = await axios.get<TCAReport[]>(`${API_BASE}/tca/report`, {
    headers: authHeader(),
  });
  return data ?? [];
}

async function fetchRecords(n = 100): Promise<TCARecord[]> {
  const { data } = await axios.get<TCARecord[]>(`${API_BASE}/tca/records`, {
    headers: authHeader(),
    params: { n },
  });
  return data ?? [];
}

async function fetchAlerts(): Promise<TCAAlert[]> {
  const { data } = await axios.get<TCAAlert[]>(`${API_BASE}/tca/alerts`, {
    headers: authHeader(),
  });
  return data ?? [];
}

async function fetchStats(n = 500): Promise<TCAStats | null> {
  const { data } = await axios.get<TCAStats>(`${API_BASE}/tca/stats`, {
    headers: authHeader(),
    params: { n },
  });
  return data ?? null;
}

// ── Component ─────────────────────────────────────────────────────────────────

const TCADashboard: React.FC = () => {
  const [reports, setReports] = useState<TCAReport[]>([]);
  const [records, setRecords] = useState<TCARecord[]>([]);
  const [alerts, setAlerts] = useState<TCAAlert[]>([]);
  const [stats, setStats] = useState<TCAStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recordsPage, setRecordsPage] = useState(0);
  const RECORDS_PER_PAGE = 20;

  const loadAll = useCallback(async () => {
    try {
      const [r, rec, al, st] = await Promise.all([
        fetchReports(),
        fetchRecords(100),
        fetchAlerts(),
        fetchStats(500),
      ]);
      setReports(r);
      setRecords(rec);
      setAlerts(al);
      setStats(st);
      setError(null);
    } catch (err) {
      setError('Failed to load TCA data — backend may be offline');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, 30_000);
    return () => clearInterval(id);
  }, [loadAll]);

  // Derived KPIs from stats
  const meanSlippage = stats?.mean_slippage_bps ?? 0;
  const p95Slippage = stats?.p95_slippage_bps ?? 0;
  const adverseRate = stats?.adverse_fill_rate ?? 0;
  const meanLatency = stats?.mean_latency_ms ?? 0;
  const totalTrades = stats?.n_trades ?? 0;

  const pagedRecords = records.slice(
    recordsPage * RECORDS_PER_PAGE,
    (recordsPage + 1) * RECORDS_PER_PAGE,
  );
  const totalPages = Math.ceil(records.length / RECORDS_PER_PAGE);

  return (
    <div style={pageStyle}>
      <PageHeader
        title="Transaction Cost Analysis"
        subtitle="Signal-price vs fill-price slippage across all brokers and sessions"
        actions={
          <button style={refreshBtnStyle} onClick={loadAll} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        }
      />

      {/* Alert banner */}
      {alerts.length > 0 && (
        <div style={alertBannerStyle}>
          <span style={{ fontWeight: 700 }}>
            ⚠ {alerts.length} broker{alerts.length > 1 ? 's' : ''} above slippage threshold
          </span>
          <span style={{ fontSize: 12, color: '#fca5a5' }}>
            {alerts.map(a => a.broker).join(', ')}
          </span>
        </div>
      )}

      {error && <div style={errorBannerStyle}>{error}</div>}

      {/* KPI strip */}
      <div style={kpiGridStyle}>
        <MetricCard
          label="Mean Slippage"
          value={`${meanSlippage.toFixed(2)} bps`}
          delta={meanSlippage > 5 ? 'Above 5 bps threshold' : 'Within threshold'}
          deltaPositive={meanSlippage <= 5}
          icon="📉"
          loading={loading}
        />
        <MetricCard
          label="P95 Slippage"
          value={`${p95Slippage.toFixed(2)} bps`}
          icon="📊"
          loading={loading}
        />
        <MetricCard
          label="Adverse Fill Rate"
          value={`${(adverseRate * 100).toFixed(1)}%`}
          delta={adverseRate > 0.6 ? 'High adverse rate' : undefined}
          deltaPositive={adverseRate <= 0.6}
          icon="🎯"
          loading={loading}
        />
        <MetricCard
          label="Mean Latency"
          value={`${meanLatency.toFixed(1)} ms`}
          delta={meanLatency > 100 ? '>100ms target' : '<100ms target'}
          deltaPositive={meanLatency <= 100}
          icon="⚡"
          loading={loading}
        />
        <MetricCard
          label="Total Trades"
          value={totalTrades.toLocaleString()}
          icon="📋"
          loading={loading}
        />
      </div>

      {/* Main grid: broker table + session breakdown */}
      <div style={mainGridStyle}>
        {/* Per-broker table */}
        <div style={panelStyle}>
          <div style={panelHeaderStyle}>
            <span style={panelTitleStyle}>Broker Performance</span>
            <span style={panelCountStyle}>{reports.length} brokers</span>
          </div>
          {reports.length === 0 ? (
            <div style={emptyStyle}>No broker data yet — fills will appear here.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    {['Broker', 'Trades', 'Mean bps', 'P95 bps', 'P99 bps', 'Adverse%', 'Latency ms', 'Slippage $', 'Status'].map(h => (
                      <th key={h} style={thStyle}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r, i) => (
                    <tr key={`${r.broker}-${i}`} style={i % 2 === 0 ? rowEvenStyle : rowOddStyle}>
                      <td style={tdStyle}><span style={brokerBadgeStyle}>{r.broker}</span></td>
                      <td style={tdNumStyle}>{r.n_trades.toLocaleString()}</td>
                      <td style={{ ...tdNumStyle, color: slippageColor(r.mean_slippage_bps) }}>
                        {r.mean_slippage_bps.toFixed(2)}
                      </td>
                      <td style={{ ...tdNumStyle, color: slippageColor(r.p95_slippage_bps) }}>
                        {r.p95_slippage_bps.toFixed(2)}
                      </td>
                      <td style={tdNumStyle}>{r.p99_slippage_bps.toFixed(2)}</td>
                      <td style={tdNumStyle}>{(r.adverse_fill_rate * 100).toFixed(1)}%</td>
                      <td style={tdNumStyle}>{r.mean_latency_ms.toFixed(1)}</td>
                      <td style={tdNumStyle}>${r.total_slippage_usd.toFixed(2)}</td>
                      <td style={tdStyle}>
                        {r.alert_triggered ? (
                          <span style={alertPillStyle}>ALERT</span>
                        ) : (
                          <span style={okPillStyle}>OK</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Session breakdown */}
        <div style={panelStyle}>
          <div style={panelHeaderStyle}>
            <span style={panelTitleStyle}>Session Breakdown</span>
          </div>
          {!stats?.by_session || Object.keys(stats.by_session).length === 0 ? (
            <div style={emptyStyle}>No session data yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {Object.entries(stats.by_session).map(([session, s]) => (
                <div key={session} style={sessionRowStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={sessionDotStyle(session)} />
                    <span style={sessionNameStyle}>{session.replace('_', ' ')}</span>
                    <span style={sessionCountStyle}>{s.n_trades} trades</span>
                  </div>
                  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                    <span style={{ color: slippageColor(s.mean_slippage_bps), fontSize: 13, fontWeight: 600 }}>
                      {s.mean_slippage_bps.toFixed(2)} bps
                    </span>
                    <span style={{ color: '#94a3b8', fontSize: 12 }}>
                      {(s.adverse_rate * 100).toFixed(0)}% adverse
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Active alerts */}
          {alerts.length > 0 && (
            <>
              <div style={{ ...panelHeaderStyle, borderTop: '1px solid var(--border, #334155)', marginTop: 8 }}>
                <span style={panelTitleStyle}>Active Alerts</span>
                <span style={{ ...panelCountStyle, background: '#ef444422', color: '#f87171' }}>
                  {alerts.length}
                </span>
              </div>
              {alerts.map((a, i) => (
                <div key={i} style={alertRowStyle}>
                  <div>
                    <span style={brokerBadgeStyle}>{a.broker}</span>
                    {a.symbol && <span style={{ color: '#94a3b8', fontSize: 11, marginLeft: 6 }}>{a.symbol}</span>}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ color: '#f87171', fontSize: 13, fontWeight: 700 }}>
                      {a.mean_slippage_bps.toFixed(2)} bps
                    </div>
                    <div style={{ color: '#64748b', fontSize: 11 }}>
                      threshold: {a.threshold_bps} bps
                    </div>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* Recent fills table */}
      <div style={panelStyle}>
        <div style={panelHeaderStyle}>
          <span style={panelTitleStyle}>Recent Fills</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={panelCountStyle}>{records.length} records</span>
            <div style={{ display: 'flex', gap: 4 }}>
              <button
                style={pageBtnStyle}
                onClick={() => setRecordsPage(p => Math.max(0, p - 1))}
                disabled={recordsPage === 0}
              >
                ‹
              </button>
              <span style={{ color: '#94a3b8', fontSize: 12, padding: '0 4px' }}>
                {recordsPage + 1}/{Math.max(1, totalPages)}
              </span>
              <button
                style={pageBtnStyle}
                onClick={() => setRecordsPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={recordsPage >= totalPages - 1}
              >
                ›
              </button>
            </div>
          </div>
        </div>
        {records.length === 0 ? (
          <div style={emptyStyle}>No fill records yet — trades will appear here.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  {['Time', 'Symbol', 'Side', 'Signal', 'Fill', 'Slippage bps', 'Slippage $', 'Latency ms', 'Broker', 'Session'].map(h => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pagedRecords.map((r, i) => (
                  <tr key={r.request_id} style={i % 2 === 0 ? rowEvenStyle : rowOddStyle}>
                    <td style={tdStyle}>
                      <span style={{ color: '#94a3b8', fontSize: 11 }}>
                        {new Date(r.fill_time).toLocaleTimeString()}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      <span style={{ color: '#f1f5f9', fontFamily: 'monospace', fontSize: 12 }}>
                        {r.symbol}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      <span style={{ color: r.side === 'BUY' ? '#4ade80' : '#f87171', fontSize: 12, fontWeight: 700 }}>
                        {r.side}
                      </span>
                    </td>
                    <td style={tdNumStyle}>{r.signal_price.toFixed(4)}</td>
                    <td style={tdNumStyle}>{r.fill_price.toFixed(4)}</td>
                    <td style={{ ...tdNumStyle, color: slippageColor(r.slippage_bps) }}>
                      {r.slippage_bps.toFixed(2)}
                    </td>
                    <td style={tdNumStyle}>${r.slippage_usd.toFixed(2)}</td>
                    <td style={tdNumStyle}>{r.latency_ms.toFixed(1)}</td>
                    <td style={tdStyle}><span style={brokerBadgeStyle}>{r.broker}</span></td>
                    <td style={tdStyle}>
                      <span style={sessionChipStyle(r.session)}>{r.session}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

// ── Colour helpers ────────────────────────────────────────────────────────────

function slippageColor(bps: number): string {
  if (bps > 10) return '#ef4444';
  if (bps > 5) return '#f97316';
  if (bps > 2) return '#facc15';
  if (bps < 0) return '#4ade80';
  return '#94a3b8';
}

const SESSION_COLOURS: Record<string, string> = {
  london: '#3b82f6',
  new_york: '#8b5cf6',
  asia: '#f59e0b',
  off_hours: '#64748b',
};

function sessionDotStyle(session: string): React.CSSProperties {
  return {
    width: 8, height: 8, borderRadius: '50%',
    background: SESSION_COLOURS[session] ?? '#64748b',
    flexShrink: 0,
  };
}

function sessionChipStyle(session: string): React.CSSProperties {
  const colour = SESSION_COLOURS[session] ?? '#64748b';
  return {
    background: colour + '22',
    border: `1px solid ${colour}`,
    borderRadius: 10,
    color: colour,
    fontSize: 10,
    fontWeight: 700,
    padding: '2px 7px',
    textTransform: 'capitalize',
    whiteSpace: 'nowrap',
  };
}

// ── Styles ────────────────────────────────────────────────────────────────────

const pageStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 16,
  padding: '20px 24px', maxWidth: 1600, margin: '0 auto',
};

const refreshBtnStyle: React.CSSProperties = {
  background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
  color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '6px 14px',
};

const alertBannerStyle: React.CSSProperties = {
  alignItems: 'center', background: '#ef444422', border: '1px solid #ef4444',
  borderRadius: 8, color: '#fca5a5', display: 'flex', gap: 12,
  justifyContent: 'space-between', padding: '10px 16px',
};

const errorBannerStyle: React.CSSProperties = {
  background: '#f9731622', border: '1px solid #f97316', borderRadius: 8,
  color: '#fdba74', fontSize: 12, padding: '10px 16px',
};

const kpiGridStyle: React.CSSProperties = {
  display: 'grid', gap: 12,
  gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
};

const mainGridStyle: React.CSSProperties = {
  display: 'grid', gap: 16,
  gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
};

const panelStyle: React.CSSProperties = {
  background: 'var(--surface, #1e293b)',
  border: '1px solid var(--border, #334155)',
  borderRadius: 10, display: 'flex', flexDirection: 'column', overflow: 'hidden',
};

const panelHeaderStyle: React.CSSProperties = {
  alignItems: 'center', borderBottom: '1px solid var(--border, #334155)',
  display: 'flex', justifyContent: 'space-between', padding: '12px 16px',
};

const panelTitleStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)', fontSize: 13, fontWeight: 700,
};

const panelCountStyle: React.CSSProperties = {
  background: '#334155', borderRadius: 10, color: '#94a3b8',
  fontSize: 11, fontWeight: 700, padding: '2px 8px',
};

const emptyStyle: React.CSSProperties = {
  color: '#64748b', fontSize: 12, padding: '24px 16px', textAlign: 'center',
};

const tableStyle: React.CSSProperties = {
  borderCollapse: 'collapse', fontSize: 12, width: '100%',
};

const thStyle: React.CSSProperties = {
  background: '#0f172a', color: '#64748b', fontSize: 10, fontWeight: 700,
  letterSpacing: 0.5, padding: '8px 12px', textAlign: 'left',
  textTransform: 'uppercase', whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)', padding: '8px 12px', whiteSpace: 'nowrap',
};

const tdNumStyle: React.CSSProperties = {
  ...tdStyle, fontFamily: 'monospace', textAlign: 'right',
};

const rowEvenStyle: React.CSSProperties = { background: 'transparent' };
const rowOddStyle: React.CSSProperties = { background: '#0f172a55' };

const brokerBadgeStyle: React.CSSProperties = {
  background: '#334155', borderRadius: 6, color: '#cbd5e1',
  fontSize: 11, fontWeight: 600, padding: '2px 7px',
};

const alertPillStyle: React.CSSProperties = {
  background: '#ef444422', border: '1px solid #ef4444', borderRadius: 10,
  color: '#f87171', fontSize: 10, fontWeight: 700, padding: '2px 7px',
};

const okPillStyle: React.CSSProperties = {
  background: '#4ade8022', border: '1px solid #4ade80', borderRadius: 10,
  color: '#4ade80', fontSize: 10, fontWeight: 700, padding: '2px 7px',
};

const sessionRowStyle: React.CSSProperties = {
  alignItems: 'center', borderBottom: '1px solid #1e293b',
  display: 'flex', justifyContent: 'space-between', padding: '10px 16px',
};

const sessionNameStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)', fontSize: 13, fontWeight: 600,
  textTransform: 'capitalize',
};

const sessionCountStyle: React.CSSProperties = {
  color: '#64748b', fontSize: 11,
};

const alertRowStyle: React.CSSProperties = {
  borderBottom: '1px solid #1e293b', display: 'flex',
  justifyContent: 'space-between', padding: '10px 16px',
};

const pageBtnStyle: React.CSSProperties = {
  background: '#1e293b', border: '1px solid #334155', borderRadius: 4,
  color: '#94a3b8', cursor: 'pointer', fontSize: 14, lineHeight: 1,
  padding: '2px 8px',
};

export default TCADashboard;
