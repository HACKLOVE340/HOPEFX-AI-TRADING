/**
 * Portfolio page — account balances, equity curve, performance summary,
 * open positions, and closed trade history.
 *
 * Data sources:
 *   1. Zustand store (equity curve, performance summary, positions, account)
 *      populated by useBootstrapData / WebSocket feed
 *   2. REST polling via useEquityCurve, usePerformanceSummary, useAccount,
 *      usePositions, and a direct trades query
 *
 * Wires to:
 *   GET /performance/equity-curve
 *   GET /performance/summary
 *   GET /trading/account
 *   GET /trading/positions
 *   GET /trading/trades
 */

import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components';
import { useToast } from '../components/Toast';
import { useQuery } from '@tanstack/react-query';
import {
  useStore,
  selectAccount,
  selectPositions,
  selectEquityCurve,
  selectPerformanceSummary,
} from '../store';
import {
  useEquityCurve,
  usePerformanceSummary,
  useAccount,
  usePositions,
} from '../hooks/useOrchestratorData';
import { EquityCurveChart } from '../components/charts/EquityCurveChart';
import { PositionsTable } from '../components/panels/PositionsTable';
import { Panel } from '../components/ui/Panel';
import { PanelSkeleton } from '../components/ui/Skeleton';
import { tradingApi } from '../hooks/useApi';
import { cn, fmtPrice, fmtPnl, fmtDateTime } from '../lib/utils';
import type { PerformanceSummary } from '../types';

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtPct = (n: number) =>
  `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;

const fmtRatio = (n: number) => n.toFixed(2);

// ── Stat tile ─────────────────────────────────────────────────────────────────

interface StatTileProps {
  label:     string;
  value:     string;
  positive?: boolean | null;
  sub?:      string;
}

const StatTile: React.FC<StatTileProps> = ({ label, value, positive, sub }) => (
  <div className="flex flex-col gap-1 px-4 py-3 rounded-lg bg-[#0d1421] border border-[#1e2d3d]">
    <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
    <span
      className={cn(
        'text-[18px] font-bold tabular-nums',
        positive === true  ? 'text-[#00e676]' :
        positive === false ? 'text-[#ff1744]' :
                             'text-slate-100',
      )}
    >
      {value}
    </span>
    {sub && <span className="text-[10px] text-slate-600">{sub}</span>}
  </div>
);

// ── Account summary ───────────────────────────────────────────────────────────

const AccountSummary: React.FC = () => {
  useAccount();
  const account = useStore(selectAccount);

  if (!account) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-20 rounded-lg bg-[#0d1421] border border-[#1e2d3d] animate-pulse" />
        ))}
      </div>
    );
  }

  const balance    = account.balance    ?? 0;
  const equity     = account.equity      ?? balance;
  const margin     = account.margin_used ?? 0;
  const freeMargin = account.margin_free ?? (equity - margin);
  const pnl        = account.total_pnl   ?? 0;
  const dailyPnl   = account.daily_pnl ?? 0;
  const dailyPct   = balance > 0 ? (dailyPnl / balance) * 100 : 0;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <StatTile label="Balance"      value={`$${balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
      <StatTile label="Equity"       value={`$${equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
      <StatTile label="Free Margin"  value={`$${freeMargin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
      <StatTile label="Margin Used"  value={`$${margin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
      <StatTile
        label="Unrealized P&L"
        value={`${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`}
        positive={pnl >= 0 ? true : false}
      />
      <StatTile
        label="Daily P&L"
        value={fmtPct(dailyPct)}
        positive={dailyPct >= 0 ? true : false}
        sub={`${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`}
      />
    </div>
  );
};

// ── Performance metrics ───────────────────────────────────────────────────────

const PerformanceMetrics: React.FC = () => {
  usePerformanceSummary();
  const perf = useStore(selectPerformanceSummary);

  const totalReturn   = perf?.total_return_pct  ?? 0;
  const sharpe        = perf?.sharpe_ratio       ?? 0;
  const sortino       = perf?.sortino_ratio      ?? 0;
  const maxDD         = perf?.max_drawdown_pct   ?? 0;
  const winRate       = perf?.win_rate           ?? 0;
  const profitFactor  = perf?.profit_factor      ?? 0;
  const totalTrades   = perf?.total_trades       ?? 0;
  const avgPnl        = perf?.avg_trade_pnl      ?? 0;
  const bestTrade     = perf?.best_trade         ?? 0;
  const worstTrade    = perf?.worst_trade        ?? 0;
  const cvar          = perf?.cvar_95            ?? 0;

  const metrics: { label: string; value: string; positive?: boolean | null }[] = [
    { label: 'Total Return',   value: fmtPct(totalReturn),            positive: totalReturn >= 0 },
    { label: 'Sharpe Ratio',   value: fmtRatio(sharpe),               positive: sharpe >= 1 ? true : sharpe < 0 ? false : null },
    { label: 'Sortino Ratio',  value: fmtRatio(sortino),              positive: sortino >= 1 ? true : sortino < 0 ? false : null },
    { label: 'Max Drawdown',   value: fmtPct(-Math.abs(maxDD)),       positive: false },
    { label: 'Win Rate',       value: fmtPct(winRate),                positive: winRate >= 50 },
    { label: 'Profit Factor',  value: fmtRatio(profitFactor),         positive: profitFactor >= 1 },
    { label: 'Total Trades',   value: String(totalTrades) },
    { label: 'Avg Trade P&L',  value: `$${avgPnl.toFixed(2)}`,        positive: avgPnl >= 0 },
    { label: 'Best Trade',     value: `+$${bestTrade.toFixed(2)}`,    positive: true },
    { label: 'Worst Trade',    value: `-$${Math.abs(worstTrade).toFixed(2)}`, positive: false },
    { label: 'CVaR 95%',       value: `$${cvar.toFixed(2)}`,          positive: false },
  ];

  return (
    <Panel title="Performance">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {metrics.map(({ label, value, positive }) => (
          <StatTile key={label} label={label} value={value} positive={positive} />
        ))}
      </div>
    </Panel>
  );
};

// ── Trade history ─────────────────────────────────────────────────────────────

interface TradeRecord {
  id:          string;
  symbol:      string;
  side:        string;
  quantity:    number;
  entry_price: number;
  exit_price:  number;
  pnl:         number;
  opened_at:   string;
  closed_at:   string;
}

type TradeFilter = 'all' | 'long' | 'short' | 'win' | 'loss';

const TradeHistory: React.FC = () => {
  const { data: trades, isLoading, isError } = useQuery<TradeRecord[]>({
    queryKey: ['trades', 'history'],
    queryFn:  async () => {
      const res = await tradingApi.trades(100);
      const raw = res.data as TradeRecord[] | { trades: TradeRecord[] };
      return Array.isArray(raw) ? raw : (raw?.trades ?? []);
    },
    staleTime:       60_000,
    refetchInterval: 60_000,
  });

  const [filter, setFilter]   = useState<TradeFilter>('all');
  const [search, setSearch]   = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo]     = useState('');

  const filtered = useMemo(() => {
    if (!trades) return [];
    const fromMs = dateFrom ? new Date(dateFrom).getTime() : 0;
    const toMs   = dateTo   ? new Date(dateTo + 'T23:59:59').getTime() : Infinity;
    return trades.filter((t) => {
      const matchDir = filter === 'all' ? true
        : filter === 'long'  ? (t.side === 'long' || t.side === 'buy')
        : filter === 'short' ? (t.side === 'short' || t.side === 'sell')
        : filter === 'win'   ? t.pnl >= 0
        : t.pnl < 0;
      const matchSearch = !search || t.symbol.toLowerCase().includes(search.toLowerCase());
      const closedMs = t.closed_at ? new Date(t.closed_at).getTime() : 0;
      const matchDate = closedMs >= fromMs && closedMs <= toMs;
      return matchDir && matchSearch && matchDate;
    });
  }, [trades, filter, search, dateFrom, dateTo]);

  const totalPnl = filtered.reduce((s, t) => s + t.pnl, 0);
  const wins     = filtered.filter((t) => t.pnl >= 0).length;

  const FILTERS: { id: TradeFilter; label: string; color: string }[] = [
    { id: 'all',   label: 'ALL',     color: '#64748b' },
    { id: 'long',  label: '▲ LONG',  color: '#00e676' },
    { id: 'short', label: '▼ SHORT', color: '#ff1744' },
    { id: 'win',   label: '✓ WINS',  color: '#00e676' },
    { id: 'loss',  label: '✗ LOSSES',color: '#ff1744' },
  ];

  const dateInputStyle: React.CSSProperties = {
    background: '#111827', border: '1px solid #1e2d3d', borderRadius: 4,
    padding: '2px 6px', fontSize: 10, color: '#94a3b8', outline: 'none',
    colorScheme: 'dark' as React.CSSProperties['colorScheme'],
  };

  const headerRight = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      {/* Date range */}
      <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={dateInputStyle} title="From date" />
      <span style={{ fontSize: 10, color: '#334155' }}>→</span>
      <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} style={dateInputStyle} title="To date" />
      {(dateFrom || dateTo) && (
        <button onClick={() => { setDateFrom(''); setDateTo(''); }} style={{
          background: 'transparent', border: 'none', color: '#475569', fontSize: 10, cursor: 'pointer', padding: '0 2px',
        }} title="Clear date filter">✕</button>
      )}
      <div style={{ width: 1, height: 14, background: '#1e2d3d' }} />
      {/* Search */}
      <input
        type="text"
        placeholder="Symbol…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="bg-[#111827] border border-[#1e2d3d] rounded px-2 py-1 text-[11px] text-slate-300 outline-none w-20"
      />
      {/* Filter pills */}
      {FILTERS.map(({ id, label, color }) => (
        <button
          key={id}
          onClick={() => setFilter(id)}
          style={{
            padding: '2px 8px', borderRadius: 4,
            background: filter === id ? `${color}18` : 'transparent',
            border: `1px solid ${filter === id ? `${color}50` : '#1e2d3d'}`,
            color: filter === id ? color : '#475569',
            fontSize: 9, fontWeight: 700, letterSpacing: 0.8, cursor: 'pointer',
          }}
        >
          {label}
        </button>
      ))}
      {filtered.length > 0 && (
        <span style={{ fontSize: 10, color: totalPnl >= 0 ? '#00e676' : '#ff1744', fontFamily: 'monospace', fontWeight: 700 }}>
          {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)} ({wins}/{filtered.length})
        </span>
      )}
    </div>
  );

  return (
    <Panel title="Trade History" headerRight={headerRight} noPad>
      {isLoading && <PanelSkeleton rows={5} />}

      {isError && (
        <div className="px-4 py-6 text-center text-[12px] text-slate-500">
          Could not load trade history.
        </div>
      )}

      {!isLoading && !isError && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-10 gap-2">
          <span className="text-2xl opacity-30">📋</span>
          <span className="text-[12px] text-slate-500">
            {!trades || trades.length === 0 ? 'No closed trades yet' : `No ${filter} trades`}
          </span>
        </div>
      )}

      {filtered.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-[#1e2d3d]">
                {['Symbol', 'Side', 'Size', 'Entry', 'Exit', 'P&L', 'Opened', 'Closed'].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => {
                const isLong = t.side === 'long' || t.side === 'buy';
                const pnlPos = t.pnl >= 0;
                return (
                  <tr
                    key={t.id}
                    className="border-b border-[#0d1421] hover:bg-[#1e2d3d]/40 transition-colors"
                  >
                    <td className="px-3 py-2.5 font-semibold text-slate-200 whitespace-nowrap">
                      {t.symbol}
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={cn(
                          'inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider',
                          isLong
                            ? 'bg-[#00e676]/10 text-[#00e676]'
                            : 'bg-[#ff1744]/10 text-[#ff1744]',
                        )}
                      >
                        {isLong ? '▲ Long' : '▼ Short'}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-slate-300">{t.quantity}</td>
                    <td className="px-3 py-2.5 tabular-nums text-slate-300">{fmtPrice(t.entry_price)}</td>
                    <td className="px-3 py-2.5 tabular-nums text-slate-200 font-medium">{fmtPrice(t.exit_price)}</td>
                    <td className="px-3 py-2.5">
                      <span
                        className={cn(
                          'inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold tabular-nums',
                          pnlPos
                            ? 'bg-[#00e676]/10 text-[#00e676]'
                            : 'bg-[#ff1744]/10 text-[#ff1744]',
                        )}
                      >
                        {fmtPnl(t.pnl)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                      {fmtDateTime(t.opened_at)}
                    </td>
                    <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                      {fmtDateTime(t.closed_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
};

// ── Allocation pie chart (SVG) ────────────────────────────────────────────────

const PIE_COLORS = ['#3b82f6','#00e676','#f59e0b','#a78bfa','#f87171','#38bdf8','#fb923c'];

const AllocationPie: React.FC<{ slices: { label: string; value: number; pct: number }[] }> = ({ slices }) => {
  const R = 60; const CX = 80; const CY = 80;
  let cumAngle = -Math.PI / 2;
  const paths = slices.map((s, i) => {
    const angle = (s.pct / 100) * 2 * Math.PI;
    const x1 = CX + R * Math.cos(cumAngle);
    const y1 = CY + R * Math.sin(cumAngle);
    cumAngle += angle;
    const x2 = CX + R * Math.cos(cumAngle);
    const y2 = CY + R * Math.sin(cumAngle);
    const large = angle > Math.PI ? 1 : 0;
    return { d: `M${CX},${CY} L${x1.toFixed(1)},${y1.toFixed(1)} A${R},${R} 0 ${large},1 ${x2.toFixed(1)},${y2.toFixed(1)} Z`, color: PIE_COLORS[i % PIE_COLORS.length]!, label: s.label, pct: s.pct };
  });

  return (
    <div className="flex items-center gap-6 flex-wrap">
      <svg width={160} height={160} viewBox="0 0 160 160">
        {paths.map((p, i) => (
          <path key={i} d={p.d} fill={p.color} opacity={0.85} stroke="#0a0f1a" strokeWidth={1.5}>
            <title>{p.label}: {p.pct.toFixed(1)}%</title>
          </path>
        ))}
        <circle cx={CX} cy={CY} r={28} fill="#0a0f1a" />
        <text x={CX} y={CY + 4} textAnchor="middle" fill="#94a3b8" fontSize={10} fontWeight={600}>
          {slices.length} pos
        </text>
      </svg>
      <div className="flex flex-col gap-1.5">
        {paths.map((p, i) => (
          <div key={i} className="flex items-center gap-2 text-[11px]">
            <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: p.color }} />
            <span className="text-slate-300 font-medium w-16">{p.label}</span>
            <span className="text-slate-500 tabular-nums">{p.pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
};

// ── Drawdown chart (SVG) ──────────────────────────────────────────────────────

const DrawdownChart: React.FC<{ equityPoints: { t: number; v: number }[] }> = ({ equityPoints }) => {
  if (equityPoints.length < 2) return (
    <div className="flex items-center justify-center h-24 text-slate-600 text-[12px]">Not enough data</div>
  );
  const W = 600; const H = 80;
  // Compute running max and drawdown %
  let peak = equityPoints[0]!.v;
  const dd = equityPoints.map((p) => {
    if (p.v > peak) peak = p.v;
    return { t: p.t, dd: peak > 0 ? ((p.v - peak) / peak) * 100 : 0 };
  });
  const minDd = Math.min(...dd.map((d) => d.dd));
  const minT  = dd[0]!.t; const maxT = dd[dd.length - 1]!.t; const rangeT = maxT - minT || 1;
  const coords = dd.map((d) => ({
    x: ((d.t - minT) / rangeT) * W,
    y: minDd < 0 ? (d.dd / minDd) * H : 0,
  }));
  const linePath = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');
  const fillPath = `${linePath} L${W},${H} L0,${H} Z`;
  const maxDdPct = Math.abs(minDd).toFixed(2);

  return (
    <div>
      <div className="flex justify-between text-[10px] text-slate-500 mb-1">
        <span>Drawdown</span>
        <span className="text-[#ff1744] font-semibold">Max: -{maxDdPct}%</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 80 }} preserveAspectRatio="none">
        <defs>
          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ff1744" stopOpacity={0.4} />
            <stop offset="100%" stopColor="#ff1744" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <path d={fillPath} fill="url(#ddGrad)" />
        <path d={linePath} fill="none" stroke="#ff1744" strokeWidth={1.5} />
      </svg>
    </div>
  );
};

// ── Per-symbol P&L sparklines ─────────────────────────────────────────────────

const SymbolPnLSparklines: React.FC = () => {
  const positions = useStore(selectPositions);
  if (positions.length === 0) return null;

  const bySymbol: Record<string, { pnl: number; side: string }[]> = {};
  for (const p of positions) {
    if (!bySymbol[p.symbol]) bySymbol[p.symbol] = [];
    bySymbol[p.symbol]!.push({ pnl: p.unrealized_pnl, side: p.side });
  }

  return (
    <Panel title="Open Positions — P&L by Symbol">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {Object.entries(bySymbol).map(([sym, entries]) => {
          const totalPnl = entries.reduce((s, e) => s + e.pnl, 0);
          const isPos    = totalPnl >= 0;
          return (
            <div key={sym} className="flex flex-col gap-1 px-3 py-2.5 rounded-lg bg-[#0d1421] border border-[#1e2d3d]">
              <div className="flex justify-between items-center">
                <span className="text-[11px] font-bold text-slate-200">{sym}</span>
                <span className={cn('text-[11px] font-semibold tabular-nums', isPos ? 'text-[#00e676]' : 'text-[#ff1744]')}>
                  {isPos ? '+' : ''}${totalPnl.toFixed(2)}
                </span>
              </div>
              <div className="flex gap-1 flex-wrap">
                {entries.map((e, i) => (
                  <span key={i} className={cn('text-[9px] px-1 py-0.5 rounded', e.side === 'long' ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]')}>
                    {e.side === 'long' ? '▲' : '▼'} ${e.pnl.toFixed(2)}
                  </span>
                ))}
              </div>
              {/* Mini P&L bar */}
              <div className="h-1 rounded bg-[#1e2d3d] overflow-hidden mt-1">
                <div
                  className="h-1 rounded transition-all"
                  style={{
                    width: `${Math.min(Math.abs(totalPnl) / 100 * 100, 100)}%`,
                    background: isPos ? '#00e676' : '#ff1744',
                    marginLeft: isPos ? 0 : 'auto',
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
};

// ── Allocation breakdown ──────────────────────────────────────────────────────

const AllocationBreakdown: React.FC = () => {
  const positions = useStore(selectPositions);

  if (positions.length === 0) return null;

  const bySymbol: Record<string, { long: number; short: number }> = {};
  for (const p of positions) {
    if (!bySymbol[p.symbol]) bySymbol[p.symbol] = { long: 0, short: 0 };
    const notional = p.size * p.current_price;
    if (p.side === 'long') bySymbol[p.symbol]!.long  += notional;
    else                   bySymbol[p.symbol]!.short += notional;
  }

  const totalNotional = Object.values(bySymbol).reduce((acc, v) => acc + v.long + v.short, 0);
  const slices = Object.entries(bySymbol).map(([label, { long, short }]) => ({
    label,
    value: long + short,
    pct: totalNotional > 0 ? ((long + short) / totalNotional) * 100 : 0,
  }));

  return (
    <Panel title="Allocation by Symbol">
      <div className="flex flex-col gap-4">
        <AllocationPie slices={slices} />
        <div className="flex flex-col gap-2">
          {slices.map(({ label, value, pct }, i) => (
            <div key={label} className="flex items-center gap-3">
              <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
              <span className="text-[12px] font-semibold text-slate-200 w-20 flex-shrink-0">{label}</span>
              <div className="flex-1 h-1.5 rounded bg-[#0d1421] overflow-hidden">
                <div className="h-1.5 rounded transition-all" style={{ width: `${pct}%`, background: PIE_COLORS[i % PIE_COLORS.length] }} />
              </div>
              <span className="text-[11px] text-slate-400 tabular-nums w-12 text-right">{pct.toFixed(1)}%</span>
              <span className="text-[11px] text-slate-500 tabular-nums w-24 text-right">
                ${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
};

// ── Page ──────────────────────────────────────────────────────────────────────

const Portfolio: React.FC = () => {
  useEquityCurve();
  usePositions();
  const equityHistory = useStore(selectEquityCurve);
  const toast = useToast();

  const equityPoints = useMemo(() =>
    equityHistory.map((p) => ({ t: new Date(p.timestamp).getTime() / 1000, v: p.equity })),
    [equityHistory],
  );

  const handleExport = async () => {
    try {
      const res = await tradingApi.trades(1000);
      const raw = res.data as TradeRecord[] | { trades: TradeRecord[] };
      const trades = Array.isArray(raw) ? raw : (raw?.trades ?? []);
      if (trades.length === 0) { toast.warning('No trades to export.'); return; }
      const headers = ['id','symbol','side','quantity','entry_price','exit_price','pnl','opened_at','closed_at'];
      const csv = [
        headers.join(','),
        ...trades.map(t =>
          headers.map(h => JSON.stringify((t as unknown as Record<string, unknown>)[h] ?? '')).join(',')
        ),
      ].join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `hopefx-trades-${new Date().toISOString().slice(0,10)}.csv`;
      a.click(); URL.revokeObjectURL(url);
      toast.success('Trade history exported.');
    } catch {
      toast.error('Export failed. Please try again.');
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4 min-h-screen bg-[#0a0f1a]">

      <PageHeader
        title="Portfolio"
        icon="💼"
        subtitle="Balances, equity curve, allocation, and trade history"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Portfolio' },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <Link to="/performance" className="px-3 py-1.5 rounded text-[11px] font-semibold bg-[#1e1b4b] border border-[#4338ca] text-[#a78bfa] hover:bg-[#4338ca]/20 transition-colors" style={{ textDecoration: 'none' }}>
              📊 Analytics
            </Link>
            <Link to="/trade" className="px-3 py-1.5 rounded text-[11px] font-semibold bg-[#052e16] border border-[#166534] text-[#4ade80] hover:bg-[#14532d]/50 transition-colors" style={{ textDecoration: 'none' }}>
              ⚡ Trade
            </Link>
            <Link to="/journal" className="px-3 py-1.5 rounded text-[11px] font-semibold bg-[#1e293b] border border-[#334155] text-[#94a3b8] hover:bg-[#334155]/50 transition-colors" style={{ textDecoration: 'none' }}>
              📓 Journal
            </Link>
            <button onClick={handleExport} className="px-3 py-1.5 rounded text-[11px] font-semibold bg-[#1e3a5f] border border-[#1d4ed8] text-[#60a5fa] hover:bg-[#1d4ed8]/30 transition-colors">
              ↓ Export CSV
            </button>
          </div>
        }
      />

      <AccountSummary />
      <EquityCurveChart />

      {/* Drawdown chart */}
      {equityPoints.length >= 2 && (
        <Panel title="Drawdown">
          <DrawdownChart equityPoints={equityPoints} />
        </Panel>
      )}

      <PerformanceMetrics />
      <SymbolPnLSparklines />
      <AllocationBreakdown />
      <PositionsTable />
      <TradeHistory />

      {/* Cross-links */}
      <div className="flex flex-wrap gap-2 pt-2 border-t border-[#1e2d3d]">
        {[
          { label: '📈 AI Charts',       path: '/ai-chart' },
          { label: '📊 Performance',     path: '/performance' },
          { label: '💰 P&L Dashboard',   path: '/pnl' },
          { label: '🛡 Risk Calculator', path: '/risk-calculator' },
          { label: '📓 Trade Journal',   path: '/journal' },
          { label: '👁 Watchlist',       path: '/watchlist' },
        ].map(({ label, path }) => (
          <Link
            key={path}
            to={path}
            className="px-3 py-1.5 rounded text-[11px] bg-transparent border border-[#1e2d3d] text-slate-500 hover:text-slate-300 hover:border-[#334155] transition-colors"
            style={{ textDecoration: 'none' }}
          >
            {label}
          </Link>
        ))}
      </div>
    </div>
  );
};

export default Portfolio;
