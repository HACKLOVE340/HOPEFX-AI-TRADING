/**
 * Performance page — live equity curve, trade breakdown, public stats.
 *
 * Wires to:
 *   GET /api/performance/public        — PublicPerformance (no auth)
 *   GET /api/performance/equity-curve  — EquityPoint[] (no auth)
 *   GET /api/trading/trades            — trade history (auth)
 *   GET /api/performance/weekly-report/latest — WeeklyReport (auth)
 */

import React, { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { performanceApi, tradingApi } from '../hooks/useApi';
import { PanelSkeleton } from '../components/ui/Skeleton';
import { PageHeader, EmptyState } from '../components';
import { cn, fmtPrice, fmtPnl, fmtDateTime, computeDrawdown } from '../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface PublicPerformance {
  total_trades:    number;
  win_rate:        number | null;
  avg_return_pct:  number | null;
  sharpe:          number | null;
  max_drawdown_pct: number;
  start_date:      string;
  note:            string;
}

// Canonical shape returned by both /api/performance/equity-curve and
// /api/pnl/equity-curve. Both endpoints use the same Pydantic EquityPoint
// model: { time: float (unix seconds), value: float (equity in currency) }.
interface EquityPoint {
  time:  number;
  value: number;
}

interface Trade {
  trade_id:    string;
  symbol:      string;
  side:        string;
  quantity:    number;
  entry_price: number;
  exit_price:  number | null;
  realized_pnl: number;
  commission:  number;
  status:      string;
  strategy:    string;
  entry_time:  string;
  exit_time:   string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// ── SVG equity curve ──────────────────────────────────────────────────────────

function EquityCurveChart({ points }: { points: { t: number; v: number }[] }) {
  if (points.length < 2) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 160, color: '#475569', fontSize: 13 }}>
      Not enough data to render curve
    </div>
  );

  const W = 800; const H = 200;
  const values = points.map((p) => p.v);
  const times  = points.map((p) => p.t);
  const minV = Math.min(...values); const maxV = Math.max(...values);
  const minT = Math.min(...times);  const maxT = Math.max(...times);
  const rangeV = maxV - minV || 1;  const rangeT = maxT - minT || 1;

  const coords = points.map((p) => ({
    x: ((p.t - minT) / rangeT) * W,
    y: H - ((p.v - minV) / rangeV) * H,
  }));

  const linePath = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');
  const fillPath = `${linePath} L${W},${H} L0,${H} Z`;
  const up = values[values.length - 1] >= values[0];
  const color = up ? '#00e676' : '#ff1744';

  const dd = computeDrawdown(values);
  const ddCoords = dd.map((d, i) => ({ x: coords[i].x, y: H - Math.abs(d) * H * 0.4 }));
  const ddPath = ddCoords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 200 }} preserveAspectRatio="none">
        <defs>
          <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.25" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={0} y1={H - f * H} x2={W} y2={H - f * H} stroke="#1e2d3d" strokeWidth={1} />
        ))}
        <path d={fillPath} fill="url(#eq-fill)" />
        <path d={linePath} fill="none" stroke={color} strokeWidth={2} />
        <path d={ddPath} fill="none" stroke="#ff1744" strokeWidth={1} strokeDasharray="3 3" opacity={0.4} />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, padding: '0 4px' }}>
        <span style={{ fontSize: 10, color: '#475569' }}>
          {points[0] ? new Date(points[0].t * 1000).toLocaleDateString() : ''}
        </span>
        <span style={{ fontSize: 10, color: '#475569', fontStyle: 'italic' }}>— — drawdown</span>
        <span style={{ fontSize: 10, color: '#475569' }}>
          {points[points.length - 1] ? new Date(points[points.length - 1].t * 1000).toLocaleDateString() : ''}
        </span>
      </div>
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={s.statCard}>
      <div style={s.statLabel}>{label}</div>
      <div style={{ ...s.statValue, color: color ?? '#f1f5f9' }}>{value}</div>
      {sub && <div style={s.statSub}>{sub}</div>}
    </div>
  );
}

// ── Trade row ─────────────────────────────────────────────────────────────────

function TradeRow({ trade }: { trade: Trade }) {
  const won = trade.realized_pnl > 0;
  const isLong = trade.side === 'buy' || trade.side === 'long';
  return (
    <tr style={{ borderBottom: '1px solid #1e293b' }}>
      <td style={s.td}><strong style={{ color: '#f1f5f9' }}>{trade.symbol}</strong></td>
      <td style={s.td}>
        <span style={{ color: isLong ? '#00e676' : '#ff1744', fontWeight: 700, fontSize: 11 }}>
          {isLong ? '▲' : '▼'} {trade.side.toUpperCase()}
        </span>
      </td>
      <td style={{ ...s.td, fontFamily: 'monospace' }}>{trade.quantity}</td>
      <td style={{ ...s.td, fontFamily: 'monospace' }}>{fmtPrice(trade.entry_price)}</td>
      <td style={{ ...s.td, fontFamily: 'monospace' }}>{trade.exit_price ? fmtPrice(trade.exit_price) : '—'}</td>
      <td style={s.td}>
        <span style={{ color: won ? '#00e676' : '#ff1744', fontWeight: 600, fontFamily: 'monospace' }}>
          {fmtPnl(trade.realized_pnl)}
        </span>
      </td>
      <td style={{ ...s.td, color: '#64748b' }}>{trade.strategy || '—'}</td>
      <td style={{ ...s.td, color: '#64748b', whiteSpace: 'nowrap' }}>{fmtDateTime(trade.entry_time)}</td>
    </tr>
  );
}

// ── Trade breakdown ───────────────────────────────────────────────────────────

function TradeBreakdown({ trades }: { trades: Trade[] }) {
  const closed = trades.filter((t) => t.status === 'closed' || t.exit_price != null);
  if (closed.length === 0) return null;

  const wins   = closed.filter((t) => t.realized_pnl > 0);
  const losses = closed.filter((t) => t.realized_pnl <= 0);
  const totalPnl = closed.reduce((sum, t) => sum + t.realized_pnl, 0);
  const avgWin  = wins.length   ? wins.reduce((s, t) => s + t.realized_pnl, 0) / wins.length   : 0;
  const avgLoss = losses.length ? losses.reduce((s, t) => s + t.realized_pnl, 0) / losses.length : 0;
  const profitFactor = avgLoss !== 0 ? Math.abs(avgWin / avgLoss) : null;

  const bySymbol: Record<string, { count: number; pnl: number }> = {};
  for (const t of closed) {
    if (!bySymbol[t.symbol]) bySymbol[t.symbol] = { count: 0, pnl: 0 };
    bySymbol[t.symbol].count++;
    bySymbol[t.symbol].pnl += t.realized_pnl;
  }
  const symbolRows = Object.entries(bySymbol).sort((a, b) => b[1].pnl - a[1].pnl);
  const maxAbsPnl = Math.max(...symbolRows.map(([, d]) => Math.abs(d.pnl)), 1);

  const rows = [
    { label: 'Closed trades',  value: closed.length.toString(),                                    color: '#f1f5f9' },
    { label: 'Wins',           value: wins.length.toString(),                                       color: '#00e676' },
    { label: 'Losses',         value: losses.length.toString(),                                     color: '#ff1744' },
    { label: 'Total P&L',      value: fmtPnl(totalPnl),                                            color: totalPnl >= 0 ? '#00e676' : '#ff1744' },
    { label: 'Avg win',        value: fmtPnl(avgWin),                                              color: '#00e676' },
    { label: 'Avg loss',       value: fmtPnl(avgLoss),                                             color: '#ff1744' },
    { label: 'Profit factor',  value: profitFactor ? profitFactor.toFixed(2) : '—',               color: profitFactor && profitFactor >= 1.5 ? '#00e676' : '#ffb800' },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
      <div style={s.card}>
        <h3 style={s.cardTitle}>Trade Breakdown</h3>
        {rows.map(({ label, value, color }) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>{label}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color, fontFamily: 'monospace' }}>{value}</span>
          </div>
        ))}
      </div>
      <div style={s.card}>
        <h3 style={s.cardTitle}>By Symbol</h3>
        {symbolRows.map(([sym, { count, pnl }]) => (
          <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#f1f5f9', width: 72 }}>{sym}</span>
            <div style={{ flex: 1, height: 6, background: '#0f172a', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ height: '100%', borderRadius: 3, background: pnl >= 0 ? '#00e676' : '#ff1744', width: `${Math.min(100, Math.abs(pnl) / maxAbsPnl * 100)}%` }} />
            </div>
            <span style={{ fontSize: 11, fontFamily: 'monospace', color: pnl >= 0 ? '#00e676' : '#ff1744', width: 72, textAlign: 'right' }}>{fmtPnl(pnl)}</span>
            <span style={{ fontSize: 10, color: '#475569', width: 24, textAlign: 'right' }}>{count}x</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type Tab = 'overview' | 'trades' | 'weekly';
type Period = 'weekly' | 'monthly' | 'yearly' | 'all';

// Benchmark returns (annualised %) for comparison
const BENCHMARKS: Record<string, number> = {
  'S&P 500': 10.5,
  'Gold':     8.2,
  'BTC':     42.0,
};

const Performance: React.FC = () => {
  const [tab, setTab]       = useState<Tab>('overview');
  const [period, setPeriod] = useState<Period>('all');
  const [tradeSymbol, setTradeSymbol] = useState('');

  const publicQ = useQuery<PublicPerformance>({
    queryKey: ['performance', 'public'],
    queryFn:  async () => { const r = await performanceApi.summary(); return r.data; },
    refetchInterval: 5 * 60_000,
    staleTime:       2 * 60_000,
  });

  const equityQ = useQuery<EquityPoint[]>({
    queryKey: ['performance', 'equity-curve'],
    queryFn:  async () => { const r = await performanceApi.equityCurve(); return r.data; },
    refetchInterval: 5 * 60_000,
    staleTime:       2 * 60_000,
  });

  const tradesQ = useQuery<{ trades: Trade[]; count: number }>({
    queryKey: ['performance', 'trades'],
    queryFn:  async () => {
      const r = await tradingApi.trades(200);
      const raw = r.data as Trade[] | { trades: Trade[]; count: number };
      return Array.isArray(raw) ? { trades: raw, count: raw.length } : raw;
    },
    refetchInterval: 60_000,
    staleTime:       30_000,
    enabled: tab === 'trades' || tab === 'overview',
  });

  const weeklyQ = useQuery({
    queryKey: ['performance', 'weekly'],
    queryFn:  async () => { const r = await performanceApi.weekly(); return r.data; },
    staleTime: 10 * 60_000,
    enabled: tab === 'weekly',
  });

  const [tradeSide, setTradeSide]   = useState('');
  const [tradeFrom, setTradeFrom]   = useState('');
  const [tradeTo,   setTradeTo]     = useState('');
  const [exporting, setExporting]   = useState(false);

  const handleExport = useCallback(async (format: 'csv' | 'pdf') => {
    setExporting(true);
    try {
      const { performanceExtApi } = await import('../hooks/useApi');
      const res = await performanceExtApi.export(format);
      const url = URL.createObjectURL(new Blob([res.data as BlobPart]));
      const a = document.createElement('a');
      a.href = url; a.download = `performance.${format}`; a.click();
      URL.revokeObjectURL(url);
    } catch { /* non-fatal */ } finally { setExporting(false); }
  }, []);

  const pub    = publicQ.data;
  // Both equity-curve endpoints return { time: number, value: number }.
  // Filter out any points with zero time or value (e.g. missing data).
  const equity = (equityQ.data ?? [])
    .filter((p) => p.time > 0 && p.value > 0)
    .map((p) => ({ t: p.time, v: p.value }));
  const trades = tradesQ.data?.trades ?? [];
  const filteredTrades = trades.filter((t) => {
    if (tradeSymbol && !t.symbol.includes(tradeSymbol.toUpperCase())) return false;
    if (tradeSide && t.side !== tradeSide) return false;
    if (tradeFrom && new Date(t.entry_time) < new Date(tradeFrom)) return false;
    if (tradeTo   && new Date(t.entry_time) > new Date(tradeTo))   return false;
    return true;
  });

  const refresh = useCallback(() => {
    publicQ.refetch();
    equityQ.refetch();
  }, [publicQ, equityQ]);

  return (
    <div style={s.page}>
      <PageHeader
        title="Performance"
        icon="🏆"
        subtitle="Live trading results — updated continuously"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Performance' },
        ]}
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {/* Tab selector */}
            <div style={{ display: 'flex', gap: 4 }}>
              {(['overview', 'trades', 'weekly'] as Tab[]).map((t) => (
                <button key={t} onClick={() => setTab(t)} style={{ ...s.tabBtn, ...(tab === t ? s.tabBtnActive : {}) }}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
            {/* Period toggle */}
            <div style={{ display: 'flex', gap: 2, background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: 2 }}>
              {(['weekly', 'monthly', 'yearly', 'all'] as Period[]).map((p) => (
                <button key={p} onClick={() => setPeriod(p)} style={{
                  ...s.tabBtn, padding: '4px 10px', fontSize: 11, border: 'none',
                  background: period === p ? '#1e3a5f' : 'transparent',
                  color: period === p ? '#60a5fa' : '#475569',
                }}>
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </button>
              ))}
            </div>
            <Link to="/pnl"       style={{ ...s.refreshBtn, background: 'rgba(251,191,36,0.1)', borderColor: 'rgba(251,191,36,0.3)', color: '#fbbf24', textDecoration: 'none' }}>💰 P&L</Link>
            <Link to="/portfolio" style={{ ...s.refreshBtn, background: 'rgba(34,197,94,0.1)',  borderColor: 'rgba(34,197,94,0.3)',  color: '#22c55e', textDecoration: 'none' }}>💼 Portfolio</Link>
            <Link to="/tca"       style={{ ...s.refreshBtn, background: 'rgba(139,92,246,0.1)', borderColor: 'rgba(139,92,246,0.3)', color: '#a78bfa', textDecoration: 'none' }}>📊 TCA</Link>
            <Link to="/journal"   style={{ ...s.refreshBtn, background: 'rgba(59,130,246,0.1)', borderColor: 'rgba(59,130,246,0.3)', color: '#60a5fa', textDecoration: 'none' }}>📓 Journal</Link>
            <button onClick={refresh} disabled={publicQ.isFetching} style={s.refreshBtn}>
              {publicQ.isFetching ? '⟳' : '↻'} Refresh
            </button>
          </div>
        }
      />

      {/* ── Overview ──────────────────────────────────────────────────────── */}
      {tab === 'overview' && (
        <>
          {publicQ.isLoading && <div style={{ padding: 24 }}><PanelSkeleton rows={4} /></div>}
          {publicQ.isError && <div style={s.errorBox}>Failed to load performance data</div>}
          {!publicQ.isLoading && !publicQ.isError && !pub && (
            <EmptyState
              icon="📊"
              title="No performance data yet"
              description="Make your first trade to start tracking equity curve, Sharpe ratio, win rate, and drawdown metrics."
              action={
                <div style={{ display: 'flex', gap: 8 }}>
                  <Link to="/trade" style={{ padding: '8px 18px', background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600, textDecoration: 'none', display: 'inline-block' }}>
                    ⚡ Start Trading
                  </Link>
                  <Link to="/ai-strategy" style={{ padding: '8px 18px', background: 'transparent', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', fontSize: 13, textDecoration: 'none', display: 'inline-block' }}>
                    🧠 AI Strategy
                  </Link>
                </div>
              }
            />
          )}
          {pub && (
            <>
              <div style={s.statsGrid}>
                <StatCard label="Total Trades"  value={pub.total_trades.toString()} sub="Paper trading" color="#60a5fa" />
                <StatCard label="Win Rate"      value={pub.win_rate != null ? `${pub.win_rate}%` : '—'} sub={pub.win_rate == null ? 'Need 50+ trades' : 'Winning trades'} color={pub.win_rate != null && pub.win_rate >= 50 ? '#00e676' : '#ff1744'} />
                <StatCard label="Avg Return"    value={pub.avg_return_pct != null ? `${pub.avg_return_pct > 0 ? '+' : ''}${pub.avg_return_pct}%` : '—'} sub="Per trade" color={pub.avg_return_pct != null && pub.avg_return_pct >= 0 ? '#00e676' : '#ff1744'} />
                <StatCard label="Sharpe"        value={pub.sharpe != null ? pub.sharpe.toString() : '—'} sub={pub.sharpe == null ? 'Need 50+ trades' : 'Annualised'} color="#a78bfa" />
                <StatCard label="Max Drawdown"  value={`${pub.max_drawdown_pct}%`} sub="Peak-to-trough" color="#ff1744" />
              </div>
              <div style={s.noteBox}>
                <span style={{ color: '#fbbf24', marginRight: 8 }}>⏱</span>
                <strong style={{ color: '#f1f5f9' }}>Transparency: </strong>
                {pub.note}
                {pub.start_date !== '—' && ` Paper trading started: ${pub.start_date}.`}
              </div>
            </>
          )}

          {/* Equity curve */}
          <div style={s.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 style={s.cardTitle}>Equity Curve</h3>
              {equity.length > 1 && (
                <span style={{ fontSize: 12, fontWeight: 600, color: equity[equity.length-1].v >= equity[0].v ? '#00e676' : '#ff1744' }}>
                  {equity[equity.length-1].v >= equity[0].v ? '+' : ''}{(((equity[equity.length-1].v - equity[0].v) / equity[0].v) * 100).toFixed(2)}%
                </span>
              )}
            </div>
            {equityQ.isLoading && <PanelSkeleton rows={3} />}
            {equity.length > 1
              ? <EquityCurveChart points={equity} />
              : !equityQ.isLoading && <div style={{ textAlign: 'center', color: '#475569', padding: 40, fontSize: 13 }}>No equity data yet</div>
            }
          </div>

          {/* Benchmark comparison */}
          {pub && pub.avg_return_pct != null && (
            <div style={s.card}>
              <h3 style={{ ...s.cardTitle, marginBottom: 16 }}>Benchmark Comparison — Annualised Return</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {/* Strategy row */}
                {(() => {
                  const stratReturn = pub.avg_return_pct ?? 0;
                  const allReturns  = [stratReturn, ...Object.values(BENCHMARKS)];
                  const maxReturn   = Math.max(...allReturns.map(Math.abs), 1);
                  return (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: '#60a5fa', width: 80, flexShrink: 0 }}>HOPEFX</span>
                        <div style={{ flex: 1, height: 8, background: '#0f172a', borderRadius: 4, overflow: 'hidden' }}>
                          <div style={{ height: '100%', borderRadius: 4, background: stratReturn >= 0 ? '#00e676' : '#ff1744', width: `${Math.abs(stratReturn) / maxReturn * 100}%`, transition: 'width 0.6s ease' }} />
                        </div>
                        <span style={{ fontSize: 12, fontWeight: 700, color: stratReturn >= 0 ? '#00e676' : '#ff1744', width: 60, textAlign: 'right', fontFamily: 'monospace' }}>
                          {stratReturn >= 0 ? '+' : ''}{stratReturn.toFixed(2)}%
                        </span>
                      </div>
                      {Object.entries(BENCHMARKS).map(([name, ret]) => (
                        <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontSize: 12, color: '#64748b', width: 80, flexShrink: 0 }}>{name}</span>
                          <div style={{ flex: 1, height: 6, background: '#0f172a', borderRadius: 4, overflow: 'hidden' }}>
                            <div style={{ height: '100%', borderRadius: 4, background: '#475569', width: `${Math.abs(ret) / maxReturn * 100}%` }} />
                          </div>
                          <span style={{ fontSize: 12, color: '#475569', width: 60, textAlign: 'right', fontFamily: 'monospace' }}>+{ret.toFixed(1)}%</span>
                        </div>
                      ))}
                    </>
                  );
                })()}
              </div>
            </div>
          )}

          {/* Trade breakdown */}
          {tradesQ.data && <TradeBreakdown trades={tradesQ.data.trades} />}
        </>
      )}

      {/* ── Trades ────────────────────────────────────────────────────────── */}
      {tab === 'trades' && (
        <div style={s.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
            <h3 style={s.cardTitle}>Trade History {tradesQ.data ? `(${filteredTrades.length})` : ''}</h3>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <input type="text" placeholder="Filter by symbol…" value={tradeSymbol} onChange={(e) => setTradeSymbol(e.target.value)} style={s.filterInput} />
              <select value={tradeSide} onChange={(e) => setTradeSide(e.target.value)} style={s.filterInput}>
                <option value="">All sides</option>
                <option value="buy">Buy / Long</option>
                <option value="sell">Sell / Short</option>
              </select>
              <input type="date" value={tradeFrom} onChange={(e) => setTradeFrom(e.target.value)} style={s.filterInput} title="From date" />
              <input type="date" value={tradeTo}   onChange={(e) => setTradeTo(e.target.value)}   style={s.filterInput} title="To date" />
              <button onClick={() => handleExport('csv')} disabled={exporting} style={{ ...s.refreshBtn, fontSize: 12 }}>⬇ CSV</button>
              <button onClick={() => handleExport('pdf')} disabled={exporting} style={{ ...s.refreshBtn, fontSize: 12 }}>⬇ PDF</button>
            </div>
          </div>
          {tradesQ.isLoading && <PanelSkeleton rows={6} />}
          {tradesQ.isError && <div style={{ color: '#f87171', fontSize: 13 }}>Failed to load trades — authentication required</div>}
          {filteredTrades.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={s.table}>
                <thead>
                  <tr>
                    {['Symbol', 'Side', 'Qty', 'Entry', 'Exit', 'P&L', 'Strategy', 'Time'].map((h) => (
                      <th key={h} style={s.th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredTrades.map((t) => <TradeRow key={t.trade_id} trade={t} />)}
                </tbody>
              </table>
            </div>
          )}
          {!tradesQ.isLoading && filteredTrades.length === 0 && (
            <div style={{ textAlign: 'center', color: '#475569', padding: 40, fontSize: 13 }}>No trades found</div>
          )}
        </div>
      )}

      {/* ── Weekly ────────────────────────────────────────────────────────── */}
      {tab === 'weekly' && (
        <div style={s.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={s.cardTitle}>Weekly Performance Report</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => handleExport('csv')} disabled={exporting} style={s.refreshBtn}>⬇ Export CSV</button>
              <button onClick={() => handleExport('pdf')} disabled={exporting} style={s.refreshBtn}>⬇ Export PDF</button>
            </div>
          </div>
          {weeklyQ.isLoading && <PanelSkeleton rows={4} />}
          {weeklyQ.isError && (
            <div style={{ color: '#f87171', fontSize: 13, padding: '12px 0' }}>
              No weekly report available yet. Reports are generated automatically each Sunday.
            </div>
          )}
          {weeklyQ.data && (() => {
            const wr = weeklyQ.data as Record<string, unknown>;
            const rows: { label: string; value: string; positive?: boolean }[] = [
              { label: 'Period',         value: String(wr.period ?? wr.week ?? '—') },
              { label: 'Net P&L',        value: `$${Number(wr.net_pnl ?? 0).toFixed(2)}`,         positive: Number(wr.net_pnl ?? 0) >= 0 },
              { label: 'Total Trades',   value: String(wr.total_trades ?? '—') },
              { label: 'Win Rate',       value: `${Number(wr.win_rate ?? 0).toFixed(1)}%`,         positive: Number(wr.win_rate ?? 0) >= 50 },
              { label: 'Sharpe',         value: String(wr.sharpe_ratio ?? wr.sharpe ?? '—') },
              { label: 'Max Drawdown',   value: `${Number(wr.max_drawdown_pct ?? 0).toFixed(2)}%`, positive: false },
              { label: 'Best Trade',     value: `$${Number(wr.best_trade_pnl ?? 0).toFixed(2)}`,   positive: true },
              { label: 'Worst Trade',    value: `$${Number(wr.worst_trade_pnl ?? 0).toFixed(2)}`,  positive: false },
            ];
            return (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(160px,1fr))', gap: 12, marginBottom: 20 }}>
                  {rows.map(({ label, value, positive }) => (
                    <div key={label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{label}</div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: positive === undefined ? '#f1f5f9' : positive ? '#4ade80' : '#f87171' }}>{value}</div>
                    </div>
                  ))}
                </div>
                {wr.ai_commentary && (
                  <div style={{ background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 8, padding: '12px 16px' }}>
                    <div style={{ fontSize: 12, color: '#60a5fa', marginBottom: 6, fontWeight: 600 }}>🤖 AI Commentary</div>
                    <p style={{ fontSize: 13, color: '#94a3b8', margin: 0, lineHeight: 1.6 }}>{String(wr.ai_commentary)}</p>
                  </div>
                )}
              </>
            );
          })()}
        </div>
      )}

      <div style={s.apiNote}>
        Raw data: <a href="/api/performance/public" target="_blank" rel="noopener noreferrer" style={{ color: '#fbbf24', fontFamily: 'monospace' }}>/api/performance/public</a> — no authentication required.
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:        { padding: 24, maxWidth: 1100, margin: '0 auto' },
  header:      { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 },
  title:       { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' },
  subtitle:    { fontSize: 14, color: '#64748b', margin: 0 },
  tabBtn:      { background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#64748b', cursor: 'pointer', fontSize: 12, padding: '6px 12px' },
  tabBtnActive:{ background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  refreshBtn:  { background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 13, padding: '6px 12px' },
  errorBox:    { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, color: '#f87171', fontSize: 13, padding: '12px 16px', marginBottom: 16 },
  statsGrid:   { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 },
  statCard:    { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' },
  statLabel:   { fontSize: 11, color: '#64748b', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' },
  statValue:   { fontSize: 22, fontWeight: 700 },
  statSub:     { fontSize: 11, color: '#475569', marginTop: 4 },
  noteBox:     { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#94a3b8', marginBottom: 20 },
  card:        { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 16, marginBottom: 16 },
  cardTitle:   { fontSize: 13, fontWeight: 700, color: '#f1f5f9', margin: '0 0 12px' },
  table:       { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
  th:          { textAlign: 'left', color: '#475569', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', padding: '6px 10px', borderBottom: '1px solid #334155' },
  td:          { padding: '8px 10px', color: '#94a3b8', fontSize: 12 },
  filterInput: { background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', padding: '6px 10px', fontSize: 12, outline: 'none', width: 140 },
  apiNote:     { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#64748b', marginTop: 16 },
};

export default Performance;
