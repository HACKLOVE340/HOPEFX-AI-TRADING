/**
 * pages/TCADashboard.tsx
 * Route: /tca
 *
 * Production Transaction Cost Analysis dashboard.
 * Connects to /api/tca/* endpoints — no mocks, no stubs.
 *
 * Panels:
 *   - KPI strip (7 metrics)
 *   - Slippage trend chart (Recharts AreaChart, last 50 fills)
 *   - Latency trend chart (Recharts LineChart, last 50 fills)
 *   - Per-broker table with alert badges
 *   - Session breakdown
 *   - Recent fills table (paginated, filterable)
 *   - Active alerts panel
 *   - Admin: flush records
 */

import React, { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api as sharedApi } from '../hooks/useApi';
import {
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import {
  AreaChart, Area,
  LineChart, Line,
  XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { useStore, selectUser } from '../store';

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

// ── API ───────────────────────────────────────────────────────────────────────
// Uses the shared axios instance — JWT injected automatically via interceptor.

const tcaApi = {
  reports: (lastN = 500) =>
    sharedApi.get<TCAReport[]>('/tca/report', { params: { last_n: lastN } })
      .then(r => r.data ?? []),

  records: (n = 100) =>
    sharedApi.get<TCARecord[]>('/tca/records', { params: { n } })
      .then(r => r.data ?? []),

  alerts: () =>
    sharedApi.get<TCAAlert[]>('/tca/alerts')
      .then(r => r.data ?? []),

  stats: (n = 500) =>
    sharedApi.get<TCAStats>('/tca/stats', { params: { n } })
      .then(r => r.data),

  flush: () =>
    sharedApi.delete('/tca/records')
      .then(r => r.data),
};

// ── Query keys ────────────────────────────────────────────────────────────────

const QK = {
  reports: ['tca', 'reports'] as const,
  records: ['tca', 'records'] as const,
  alerts:  ['tca', 'alerts']  as const,
  stats:   ['tca', 'stats']   as const,
};

// ── Colour helpers ────────────────────────────────────────────────────────────

function slippageColor(bps: number): string {
  if (bps > 10) return '#ef4444';
  if (bps > 5)  return '#f97316';
  if (bps > 2)  return '#facc15';
  if (bps < 0)  return '#4ade80';
  return '#94a3b8';
}

const SESSION_COLOURS: Record<string, string> = {
  london:    '#3b82f6',
  new_york:  '#8b5cf6',
  asia:      '#f59e0b',
  off_hours: '#64748b',
};

function sessionDot(session: string): React.CSSProperties {
  return {
    width: 8, height: 8, borderRadius: '50%',
    background: SESSION_COLOURS[session] ?? '#64748b',
    flexShrink: 0, display: 'inline-block',
  };
}

function sessionChip(session: string): React.CSSProperties {
  const c = SESSION_COLOURS[session] ?? '#64748b';
  return {
    background: c + '22', border: `1px solid ${c}`, borderRadius: 10,
    color: c, fontSize: 10, fontWeight: 700, padding: '2px 7px',
    textTransform: 'capitalize', whiteSpace: 'nowrap',
  };
}

// ── CSV export ────────────────────────────────────────────────────────────────

function exportCSV(records: TCARecord[]): void {
  const headers = [
    'fill_time','symbol','side','signal_price','fill_price',
    'slippage_bps','slippage_usd','latency_ms','signal_to_fill_ms',
    'broker','session','model_version','request_id',
  ];
  const rows = records.map(r =>
    headers.map(h => {
      const v = (r as unknown as Record<string, unknown>)[h];
      return typeof v === 'string' && v.includes(',') ? `"${v}"` : String(v ?? '');
    }).join(',')
  );
  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `tca_fills_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Slippage trend chart ──────────────────────────────────────────────────────

interface TrendPoint { t: string; slippage: number; latency: number }

function buildTrendPoints(records: TCARecord[]): TrendPoint[] {
  return [...records]
    .sort((a, b) => new Date(a.fill_time).getTime() - new Date(b.fill_time).getTime())
    .slice(-50)
    .map(r => ({
      t:        new Date(r.fill_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      slippage: parseFloat(r.slippage_bps.toFixed(2)),
      latency:  parseFloat(r.latency_ms.toFixed(1)),
    }));
}

const SlippageTrendChart: React.FC<{ points: TrendPoint[] }> = ({ points }) => (
  <ResponsiveContainer width="100%" height={140}>
    <AreaChart data={points} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
      <defs>
        <linearGradient id="slipGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%"  stopColor="#f97316" stopOpacity={0.35} />
          <stop offset="95%" stopColor="#f97316" stopOpacity={0}    />
        </linearGradient>
      </defs>
      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
      <XAxis dataKey="t" tick={{ fill: '#64748b', fontSize: 10 }} interval="preserveStartEnd" />
      <YAxis tick={{ fill: '#64748b', fontSize: 10 }} />
      <Tooltip
        contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
        labelStyle={{ color: '#94a3b8' }}
        formatter={(v) => [`${v} bps`, 'Slippage']}
      />
      <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="4 2" label={{ value: '5 bps', fill: '#ef4444', fontSize: 10 }} />
      <Area type="monotone" dataKey="slippage" stroke="#f97316" fill="url(#slipGrad)" strokeWidth={1.5} dot={false} />
    </AreaChart>
  </ResponsiveContainer>
);

const LatencyTrendChart: React.FC<{ points: TrendPoint[] }> = ({ points }) => (
  <ResponsiveContainer width="100%" height={140}>
    <LineChart data={points} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
      <XAxis dataKey="t" tick={{ fill: '#64748b', fontSize: 10 }} interval="preserveStartEnd" />
      <YAxis tick={{ fill: '#64748b', fontSize: 10 }} />
      <Tooltip
        contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
        labelStyle={{ color: '#94a3b8' }}
        formatter={(v) => [`${v} ms`, 'Latency']}
      />
      <ReferenceLine y={100} stroke="#facc15" strokeDasharray="4 2" label={{ value: '100ms', fill: '#facc15', fontSize: 10 }} />
      <Line type="monotone" dataKey="latency" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
    </LineChart>
  </ResponsiveContainer>
);

// ── Main component ────────────────────────────────────────────────────────────

const RECORDS_PER_PAGE = 20;

const TCADashboard: React.FC = () => {
  const navigate = useNavigate();
  const user = useStore(selectUser);
  const isAdmin = user?.role === 'admin' || user?.role === 'superadmin';
  const qc = useQueryClient();

  // ── Filters ──────────────────────────────────────────────────────────────
  const [brokerFilter,  setBrokerFilter]  = useState('');
  const [symbolFilter,  setSymbolFilter]  = useState('');
  const [sessionFilter, setSessionFilter] = useState('');
  const [recordsPage,   setRecordsPage]   = useState(0);
  const [flushConfirm,  setFlushConfirm]  = useState(false);

  // ── Queries ───────────────────────────────────────────────────────────────
  const { data: reports = [], isLoading: loadingReports } = useQuery({
    queryKey: QK.reports,
    queryFn:  () => tcaApi.reports(500),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const { data: records = [], isLoading: loadingRecords } = useQuery({
    queryKey: QK.records,
    queryFn:  () => tcaApi.records(200),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const { data: alerts = [], isLoading: loadingAlerts } = useQuery({
    queryKey: QK.alerts,
    queryFn:  tcaApi.alerts,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const { data: stats, isLoading: loadingStats } = useQuery({
    queryKey: QK.stats,
    queryFn:  () => tcaApi.stats(500),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const loading = loadingReports || loadingRecords || loadingAlerts || loadingStats;

  // ── Flush mutation (admin only) ───────────────────────────────────────────
  const flushMutation = useMutation({
    mutationFn: tcaApi.flush,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tca'] });
      setFlushConfirm(false);
    },
  });

  // ── Manual refresh ────────────────────────────────────────────────────────
  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['tca'] });
  }, [qc]);

  // ── Derived: filter options ───────────────────────────────────────────────
  const brokerOptions  = useMemo(() => [...new Set(records.map(r => r.broker))].sort(),  [records]);
  const symbolOptions  = useMemo(() => [...new Set(records.map(r => r.symbol))].sort(),  [records]);
  const sessionOptions = useMemo(() => [...new Set(records.map(r => r.session))].sort(), [records]);

  // ── Derived: filtered records ─────────────────────────────────────────────
  const filteredRecords = useMemo(() => {
    let rs = records;
    if (brokerFilter)  rs = rs.filter(r => r.broker  === brokerFilter);
    if (symbolFilter)  rs = rs.filter(r => r.symbol  === symbolFilter);
    if (sessionFilter) rs = rs.filter(r => r.session === sessionFilter);
    return rs;
  }, [records, brokerFilter, symbolFilter, sessionFilter]);

  const totalPages   = Math.max(1, Math.ceil(filteredRecords.length / RECORDS_PER_PAGE));
  const pagedRecords = filteredRecords.slice(
    recordsPage * RECORDS_PER_PAGE,
    (recordsPage + 1) * RECORDS_PER_PAGE,
  );

  // Reset page when filters change
  const handleBrokerFilter = (v: string)  => { setBrokerFilter(v);  setRecordsPage(0); };
  const handleSymbolFilter = (v: string)  => { setSymbolFilter(v);  setRecordsPage(0); };
  const handleSessionFilter = (v: string) => { setSessionFilter(v); setRecordsPage(0); };

  // ── Derived: trend points ─────────────────────────────────────────────────
  const trendPoints = useMemo(() => buildTrendPoints(filteredRecords), [filteredRecords]);

  // ── KPIs ──────────────────────────────────────────────────────────────────
  const meanSlippage  = stats?.mean_slippage_bps       ?? 0;
  const p95Slippage   = stats?.p95_slippage_bps        ?? 0;
  const adverseRate   = stats?.adverse_fill_rate        ?? 0;
  const improvRate    = stats?.price_improvement_rate   ?? 0;
  const meanLatency   = stats?.mean_latency_ms          ?? 0;
  const meanS2F       = stats?.mean_signal_to_fill_ms   ?? 0;
  const totalTrades   = stats?.n_trades                 ?? 0;

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={pg.page}>
      <PageHeader
        title="Transaction Cost Analysis"
        subtitle="Signal-price vs fill-price slippage across all brokers and sessions"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Analytics', href: '/performance' },
          { label: 'TCA' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {loading && <span style={{ color: '#64748b', fontSize: 11 }}>Updating…</span>}
            <Link to="/performance" style={{ ...pg.btn, background: 'rgba(74,222,128,0.1)', borderColor: 'rgba(74,222,128,0.3)', color: '#4ade80', textDecoration: 'none' }}>📈 Performance</Link>
            <Link to="/pnl"         style={{ ...pg.btn, background: 'rgba(139,92,246,0.1)', borderColor: 'rgba(139,92,246,0.3)', color: '#a78bfa', textDecoration: 'none' }}>💹 P&amp;L</Link>
            <Link to="/correlation" style={{ ...pg.btn, background: 'rgba(96,165,250,0.1)',  borderColor: 'rgba(96,165,250,0.3)',  color: '#60a5fa', textDecoration: 'none' }}>📊 Correlation</Link>
            <button style={pg.btn} onClick={refresh} disabled={loading}>Refresh</button>
            <button style={pg.btnCsv} onClick={() => exportCSV(filteredRecords)} disabled={filteredRecords.length === 0}>
              ↓ CSV
            </button>
            {isAdmin && !flushConfirm && (
              <button style={pg.btnDanger} onClick={() => setFlushConfirm(true)}>Flush Records</button>
            )}
            {isAdmin && flushConfirm && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ color: '#f87171', fontSize: 11 }}>Confirm flush?</span>
                <button
                  style={{ ...pg.btnDanger, opacity: flushMutation.isPending ? 0.6 : 1 }}
                  onClick={() => flushMutation.mutate()}
                  disabled={flushMutation.isPending}
                >
                  {flushMutation.isPending ? 'Flushing…' : 'Yes, flush'}
                </button>
                <button style={pg.btn} onClick={() => setFlushConfirm(false)}>Cancel</button>
              </div>
            )}
          </div>
        }
      />

      {/* Alert banner */}
      {alerts.length > 0 && (
        <div style={pg.alertBanner}>
          <span style={{ fontWeight: 700 }}>
            ⚠ {alerts.length} broker{alerts.length > 1 ? 's' : ''} above slippage threshold
          </span>
          <span style={{ fontSize: 12, color: '#fca5a5' }}>
            {alerts.map(a => a.broker).join(', ')}
          </span>
        </div>
      )}

      {flushMutation.isError && (
        <div style={pg.errorBanner}>
          Flush failed — {(flushMutation.error as Error)?.message ?? 'unknown error'}
        </div>
      )}

      {/* KPI strip */}
      <div style={pg.kpiGrid}>
        <MetricCard label="Mean Slippage"    value={`${meanSlippage.toFixed(2)} bps`}
          delta={meanSlippage > 5 ? 'Above 5 bps' : 'Within threshold'}
          deltaPositive={meanSlippage <= 5} icon="📉" loading={loading} />
        <MetricCard label="P95 Slippage"     value={`${p95Slippage.toFixed(2)} bps`}
          icon="📊" loading={loading} />
        <MetricCard label="Adverse Fill Rate" value={`${(adverseRate * 100).toFixed(1)}%`}
          delta={adverseRate > 0.6 ? 'High' : 'Normal'}
          deltaPositive={adverseRate <= 0.6} icon="🎯" loading={loading} />
        <MetricCard label="Price Improvement" value={`${(improvRate * 100).toFixed(1)}%`}
          delta={improvRate > 0.2 ? 'Good' : undefined}
          deltaPositive={improvRate > 0.2} icon="✅" loading={loading} />
        <MetricCard label="Mean Latency"     value={`${meanLatency.toFixed(1)} ms`}
          delta={meanLatency > 100 ? '>100ms' : '<100ms'}
          deltaPositive={meanLatency <= 100} icon="⚡" loading={loading} />
        <MetricCard label="Signal→Fill"      value={`${meanS2F.toFixed(1)} ms`}
          icon="🔁" loading={loading} />
        <MetricCard label="Total Trades"     value={totalTrades.toLocaleString()}
          icon="📋" loading={loading} />
      </div>

      {/* Trend charts */}
      {trendPoints.length > 1 && (
        <div style={pg.twoCol}>
          <div style={pg.panel}>
            <div style={pg.panelHdr}>
              <span style={pg.panelTitle}>Slippage Trend (last {trendPoints.length} fills)</span>
              <span style={{ ...pg.badge, color: slippageColor(meanSlippage) }}>
                avg {meanSlippage.toFixed(2)} bps
              </span>
            </div>
            <div style={{ padding: '8px 8px 4px' }}>
              <SlippageTrendChart points={trendPoints} />
            </div>
          </div>
          <div style={pg.panel}>
            <div style={pg.panelHdr}>
              <span style={pg.panelTitle}>Latency Trend (last {trendPoints.length} fills)</span>
              <span style={{ ...pg.badge, color: meanLatency > 100 ? '#f97316' : '#4ade80' }}>
                avg {meanLatency.toFixed(1)} ms
              </span>
            </div>
            <div style={{ padding: '8px 8px 4px' }}>
              <LatencyTrendChart points={trendPoints} />
            </div>
          </div>
        </div>
      )}

      {/* Broker table + Session breakdown */}
      <div style={pg.twoCol}>
        {/* Per-broker table */}
        <div style={pg.panel}>
          <div style={pg.panelHdr}>
            <span style={pg.panelTitle}>Broker Performance</span>
            <span style={pg.badge}>{reports.length} brokers</span>
          </div>
          {reports.length === 0 ? (
            <div style={pg.empty}>No broker data yet — fills will appear here.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={pg.table}>
                <thead>
                  <tr>
                    {['Broker','Trades','Mean bps','P95 bps','P99 bps','Adverse%','Latency ms','Slip $','Status'].map(h => (
                      <th key={h} style={pg.th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r, i) => (
                    <tr key={`${r.broker}-${i}`} style={i % 2 === 0 ? pg.rowEven : pg.rowOdd}>
                      <td style={pg.td}><span style={pg.brokerBadge}>{r.broker}</span></td>
                      <td style={pg.tdNum}>{r.n_trades.toLocaleString()}</td>
                      <td style={{ ...pg.tdNum, color: slippageColor(r.mean_slippage_bps) }}>
                        {r.mean_slippage_bps.toFixed(2)}
                      </td>
                      <td style={{ ...pg.tdNum, color: slippageColor(r.p95_slippage_bps) }}>
                        {r.p95_slippage_bps.toFixed(2)}
                      </td>
                      <td style={pg.tdNum}>{r.p99_slippage_bps.toFixed(2)}</td>
                      <td style={pg.tdNum}>{(r.adverse_fill_rate * 100).toFixed(1)}%</td>
                      <td style={{ ...pg.tdNum, color: r.mean_latency_ms > 100 ? '#f97316' : '#94a3b8' }}>
                        {r.mean_latency_ms.toFixed(1)}
                      </td>
                      <td style={pg.tdNum}>${r.total_slippage_usd.toFixed(2)}</td>
                      <td style={pg.td}>
                        {r.alert_triggered
                          ? <span style={pg.alertPill}>ALERT</span>
                          : <span style={pg.okPill}>OK</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Session breakdown + active alerts */}
        <div style={pg.panel}>
          <div style={pg.panelHdr}>
            <span style={pg.panelTitle}>Session Breakdown</span>
          </div>
          {!stats?.by_session || Object.keys(stats.by_session).length === 0 ? (
            <div style={pg.empty}>No session data yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {Object.entries(stats.by_session).map(([session, s]) => (
                <div key={session} style={pg.sessionRow}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={sessionDot(session)} />
                    <span style={{ color: '#f1f5f9', fontSize: 13, fontWeight: 600, textTransform: 'capitalize' }}>
                      {session.replace('_', ' ')}
                    </span>
                    <span style={{ color: '#64748b', fontSize: 11 }}>{s.n_trades} trades</span>
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

          {alerts.length > 0 && (
            <>
              <div style={{ ...pg.panelHdr, borderTop: '1px solid var(--border, #334155)', marginTop: 8 }}>
                <span style={pg.panelTitle}>Active Alerts</span>
                <span style={{ ...pg.badge, background: '#ef444422', color: '#f87171' }}>
                  {alerts.length}
                </span>
              </div>
              {alerts.map((a, i) => (
                <div key={i} style={pg.alertRow}>
                  <div>
                    <span style={pg.brokerBadge}>{a.broker}</span>
                    {a.symbol && <span style={{ color: '#94a3b8', fontSize: 11, marginLeft: 6 }}>{a.symbol}</span>}
                    <div style={{ color: '#64748b', fontSize: 10, marginTop: 2 }}>
                      {new Date(a.generated_at).toLocaleTimeString()} · {a.n_trades} trades
                    </div>
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

      {/* Recent fills — filters + paginated table */}
      <div style={pg.panel}>
        <div style={pg.panelHdr}>
          <span style={pg.panelTitle}>Recent Fills</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {/* Filters */}
            <select style={pg.select} value={brokerFilter}  onChange={e => handleBrokerFilter(e.target.value)}>
              <option value="">All Brokers</option>
              {brokerOptions.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
            <select style={pg.select} value={symbolFilter}  onChange={e => handleSymbolFilter(e.target.value)}>
              <option value="">All Symbols</option>
              {symbolOptions.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <select style={pg.select} value={sessionFilter} onChange={e => handleSessionFilter(e.target.value)}>
              <option value="">All Sessions</option>
              {sessionOptions.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <span style={pg.badge}>{filteredRecords.length} records</span>
            {/* Pagination */}
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <button style={pg.pageBtn} onClick={() => setRecordsPage(p => Math.max(0, p - 1))} disabled={recordsPage === 0}>‹</button>
              <span style={{ color: '#94a3b8', fontSize: 12, padding: '0 4px' }}>
                {recordsPage + 1}/{totalPages}
              </span>
              <button style={pg.pageBtn} onClick={() => setRecordsPage(p => Math.min(totalPages - 1, p + 1))} disabled={recordsPage >= totalPages - 1}>›</button>
            </div>
          </div>
        </div>

        {filteredRecords.length === 0 ? (
          <div style={pg.empty}>
            {records.length === 0
              ? 'No fill records yet — trades will appear here once the execution engine records fills.'
              : 'No records match the current filters.'}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={pg.table}>
              <thead>
                <tr>
                  {['Time','Symbol','Side','Signal','Fill','Slip bps','Slip $','Latency ms','S→F ms','Broker','Session','Model'].map(h => (
                    <th key={h} style={pg.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pagedRecords.map((r, i) => (
                  <tr key={r.request_id} style={i % 2 === 0 ? pg.rowEven : pg.rowOdd}>
                    <td style={pg.td}>
                      <span style={{ color: '#94a3b8', fontSize: 11 }}>
                        {new Date(r.fill_time).toLocaleTimeString()}
                      </span>
                    </td>
                    <td style={pg.td}>
                      <span style={{ color: '#f1f5f9', fontFamily: 'monospace', fontSize: 12 }}>{r.symbol}</span>
                    </td>
                    <td style={pg.td}>
                      <span style={{ color: r.side === 'BUY' ? '#4ade80' : '#f87171', fontSize: 12, fontWeight: 700 }}>
                        {r.side}
                      </span>
                    </td>
                    <td style={pg.tdNum}>{r.signal_price.toFixed(4)}</td>
                    <td style={pg.tdNum}>{r.fill_price.toFixed(4)}</td>
                    <td style={{ ...pg.tdNum, color: slippageColor(r.slippage_bps) }}>
                      {r.slippage_bps.toFixed(2)}
                    </td>
                    <td style={pg.tdNum}>${r.slippage_usd.toFixed(2)}</td>
                    <td style={{ ...pg.tdNum, color: r.latency_ms > 100 ? '#f97316' : '#94a3b8' }}>
                      {r.latency_ms.toFixed(1)}
                    </td>
                    <td style={pg.tdNum}>{r.signal_to_fill_ms.toFixed(1)}</td>
                    <td style={pg.td}><span style={pg.brokerBadge}>{r.broker}</span></td>
                    <td style={pg.td}><span style={sessionChip(r.session)}>{r.session}</span></td>
                    <td style={pg.td}>
                      <span style={{ color: '#64748b', fontSize: 10, fontFamily: 'monospace' }}>
                        {r.model_version}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Cross-links */}
      <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '16px 20px' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>Related Analytics</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {[
            { to: '/performance',  color: '#4ade80', icon: '📈', label: 'Performance' },
            { to: '/pnl',          color: '#a78bfa', icon: '💹', label: 'P&L Dashboard' },
            { to: '/correlation',  color: '#60a5fa', icon: '📊', label: 'Correlation' },
            { to: '/ab-testing',   color: '#34d399', icon: '⚡', label: 'A/B Testing' },
            { to: '/walk-forward', color: '#fbbf24', icon: '🔁', label: 'Walk-Forward' },
            { to: '/trade',        color: '#f87171', icon: '⚡', label: 'Trade' },
          ].map(({ to, color, icon, label }) => (
            <Link key={to} to={to} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', background: '#0f172a', borderRadius: 7, border: '1px solid #1e293b', textDecoration: 'none', fontSize: 12, fontWeight: 600, color }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = color)}
              onMouseLeave={e => (e.currentTarget.style.borderColor = '#1e293b')}
            >
              {icon} {label}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const pg: Record<string, React.CSSProperties> = {
  page: {
    display: 'flex', flexDirection: 'column', gap: 16,
    padding: '20px 24px', maxWidth: 1600, margin: '0 auto',
  },
  btn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '6px 14px',
  },
  btnCsv: {
    background: '#0f2a1a', border: '1px solid #166534', borderRadius: 6,
    color: '#4ade80', cursor: 'pointer', fontSize: 12, padding: '6px 14px',
  },
  btnDanger: {
    background: '#2d0a0a', border: '1px solid #7f1d1d', borderRadius: 6,
    color: '#f87171', cursor: 'pointer', fontSize: 12, padding: '6px 14px',
  },
  alertBanner: {
    alignItems: 'center', background: '#ef444422', border: '1px solid #ef4444',
    borderRadius: 8, color: '#fca5a5', display: 'flex', gap: 12,
    justifyContent: 'space-between', padding: '10px 16px',
  },
  errorBanner: {
    background: '#f9731622', border: '1px solid #f97316', borderRadius: 8,
    color: '#fdba74', fontSize: 12, padding: '10px 16px',
  },
  kpiGrid: {
    display: 'grid', gap: 12,
    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
  },
  twoCol: {
    display: 'grid', gap: 16,
    gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
  },
  panel: {
    background: 'var(--surface, #1e293b)',
    border: '1px solid var(--border, #334155)',
    borderRadius: 10, display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  panelHdr: {
    alignItems: 'center', borderBottom: '1px solid var(--border, #334155)',
    display: 'flex', justifyContent: 'space-between',
    flexWrap: 'wrap', gap: 8, padding: '12px 16px',
  },
  panelTitle: { color: 'var(--text, #f1f5f9)', fontSize: 13, fontWeight: 700 },
  badge: {
    background: '#334155', borderRadius: 10, color: '#94a3b8',
    fontSize: 11, fontWeight: 700, padding: '2px 8px',
  },
  empty: { color: '#64748b', fontSize: 12, padding: '24px 16px', textAlign: 'center' },
  sessionRow: {
    alignItems: 'center', borderBottom: '1px solid #0f172a',
    display: 'flex', justifyContent: 'space-between', padding: '10px 16px',
  },
  alertRow: {
    borderBottom: '1px solid #1e293b', display: 'flex',
    justifyContent: 'space-between', padding: '10px 16px',
  },
  table: { borderCollapse: 'collapse', fontSize: 12, width: '100%' },
  th: {
    background: '#0f172a', color: '#64748b', fontSize: 10, fontWeight: 700,
    letterSpacing: 0.5, padding: '8px 12px', textAlign: 'left',
    textTransform: 'uppercase', whiteSpace: 'nowrap',
  },
  td: { color: 'var(--text, #f1f5f9)', padding: '8px 12px', whiteSpace: 'nowrap' },
  tdNum: {
    color: 'var(--text, #f1f5f9)', fontFamily: 'monospace',
    padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap',
  },
  rowEven: { background: 'transparent' },
  rowOdd:  { background: '#0f172a55' },
  brokerBadge: {
    background: '#1e3a5f', border: '1px solid #1d4ed8', borderRadius: 4,
    color: '#93c5fd', fontSize: 11, fontWeight: 700, padding: '2px 7px',
  },
  alertPill: {
    background: '#ef444422', border: '1px solid #ef4444', borderRadius: 10,
    color: '#f87171', fontSize: 10, fontWeight: 700, padding: '2px 8px',
  },
  okPill: {
    background: '#16a34a22', border: '1px solid #16a34a', borderRadius: 10,
    color: '#4ade80', fontSize: 10, fontWeight: 700, padding: '2px 8px',
  },
  select: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '4px 8px',
  },
  pageBtn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 4,
    color: '#94a3b8', cursor: 'pointer', fontSize: 14, lineHeight: 1,
    padding: '2px 8px',
  },
};

export default TCADashboard;
