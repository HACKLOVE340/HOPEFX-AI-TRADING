/**
 * PnLDashboard — live P&L dashboard.
 *
 * Auditable trade log, equity curve, Sharpe, drawdown.
 * All data sourced from real engine fills via /api/pnl/* endpoints.
 *
 * Routes consumed:
 *   GET /api/pnl/summary         — headline stats
 *   GET /api/pnl/equity-curve    — equity time series
 *   GET /api/pnl/drawdown-curve  — drawdown % time series
 *   GET /api/pnl/trade-log       — auditable fill-level log
 *   GET /api/pnl/open-positions  — current open positions
 */

import React, { useCallback, useEffect, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader, CrossLinkBar } from '../components';
import { useFlashHighlight } from '../hooks/useFlashHighlight';
import { useQuery } from '@tanstack/react-query';
import {
  TrendingUp, TrendingDown, Activity, Shield,
  Clock, RefreshCw, AlertTriangle, ChevronLeft, ChevronRight,
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { pnlApi } from '../hooks/useApi';
import { useStore, useHasHydrated, selectIsAuth } from '../store';
import { fmtPrice, fmtPctRaw, fmtDateTime } from '../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface PnLSummary {
  equity:               number;
  starting_equity:      number;
  total_return_pct:     number;
  total_fills:          number;
  open_positions:       number;
  win_rate:             number | null;
  sharpe_ratio:         number | null;
  max_drawdown_pct:     number;
  current_drawdown_pct: number;
  avg_slippage_bps:     number;
  avg_latency_ms:       number;
  last_fill_at:         string | null;
  note?:                string;
}

interface FillEntry {
  fill_id:        string;
  order_id:       string;
  signal_id:      string;
  symbol:         string;
  direction:      string;
  quantity:       number;
  fill_price:     number;
  expected_price: number;
  slippage_bps:   number;
  broker:         string;
  latency_ms:     number;
  filled_at:      string;
  lineage_id:     string;
}

interface OpenPosition {
  symbol:         string;
  direction:      string;
  quantity:       number;
  entry_price:    number;
  current_price:  number | null;
  unrealised_pnl: number | null;
  stop_loss:      number | null;
  take_profit:    number | null;
  opened_at:      string;
}

interface EquityPoint {
  timestamp: string;
  equity:    number;
}

interface DrawdownPoint {
  timestamp:    string;
  drawdown_pct: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 25;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtUSD(n: number): string {
  return n.toLocaleString('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2,
  });
}

function fmtNum(n: number, decimals = 2): string {
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// ── Stat card ─────────────────────────────────────────────────────────────────

type CardColor = 'amber' | 'green' | 'red' | 'blue' | 'purple';

const COLOR_CLASSES: Record<CardColor, string> = {
  amber:  'bg-amber-500/10 text-amber-400',
  green:  'bg-emerald-500/10 text-emerald-400',
  red:    'bg-red-500/10 text-red-400',
  blue:   'bg-blue-500/10 text-blue-400',
  purple: 'bg-purple-500/10 text-purple-400',
};

function StatCard({
  label, value, sub, icon: Icon, color = 'amber', warn = false,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ElementType;
  color?: CardColor;
  warn?: boolean;
}) {
  return (
    <div className={`bg-[#0d1421] rounded-lg border p-5 ${warn ? 'border-amber-500/40' : 'border-[#1e2d3d]'}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-slate-400">{label}</span>
        <div className={`p-2 rounded-lg ${COLOR_CLASSES[color]}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <div className="text-2xl font-bold text-slate-100">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

// ── Recharts equity sparkline ─────────────────────────────────────────────────

function EquitySparkline({ data }: { data: { ts: string; v: number }[] }) {
  if (data.length < 2) return (
    <div className="flex items-center justify-center h-32 text-slate-600 text-sm">Not enough data</div>
  );
  const up = data[data.length - 1].v >= data[0].v;
  const color = up ? '#00e676' : '#ff1744';
  return (
    <ResponsiveContainer width="100%" height={128}>
      <AreaChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="eq-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2d3d" />
        <XAxis dataKey="ts" hide />
        <YAxis domain={['auto', 'auto']} hide />
        <Tooltip
          contentStyle={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 6, fontSize: 11 }}
          formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, 'Equity']}
          labelFormatter={() => ''}
        />
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill="url(#eq-grad)" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── Recharts drawdown chart ───────────────────────────────────────────────────

function DrawdownChart({ data }: { data: { ts: string; dd: number }[] }) {
  if (data.length < 2) return (
    <div className="flex items-center justify-center h-32 text-slate-600 text-sm">Not enough data</div>
  );
  return (
    <ResponsiveContainer width="100%" height={128}>
      <AreaChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="dd-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#ff1744" stopOpacity={0.35} />
            <stop offset="95%" stopColor="#ff1744" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2d3d" />
        <XAxis dataKey="ts" hide />
        <YAxis domain={['auto', 0]} hide />
        <ReferenceLine y={0} stroke="#334155" strokeDasharray="3 3" />
        <Tooltip
          contentStyle={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 6, fontSize: 11 }}
          formatter={(v: unknown) => [`${Number(v).toFixed(2)}%`, 'Drawdown']}
          labelFormatter={() => ''}
        />
        <Area type="monotone" dataKey="dd" stroke="#ff1744" strokeWidth={1.5} fill="url(#dd-grad)" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

// ── Live equity flash indicator ───────────────────────────────────────────────

const LiveEquityBadge: React.FC<{ equity: number | undefined }> = ({ equity }) => {
  const flash = useFlashHighlight(equity);
  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        padding: '2px 8px', borderRadius: 6, fontSize: 11, fontWeight: 700,
        background: flash !== 'transparent' ? flash : 'rgba(0,230,118,0.08)',
        color: '#00e676', border: '1px solid rgba(0,230,118,0.2)',
        transition: 'background 0.4s ease',
      }}
    >
      ● LIVE {equity != null ? `$${equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
    </span>
  );
};

// ── Trade distribution histogram (SVG) ────────────────────────────────────────

const TradeHistogram: React.FC<{ fills: FillEntry[] }> = ({ fills }) => {
  if (fills.length < 5) return (
    <div className="flex items-center justify-center h-24 text-slate-600 text-xs">Need 5+ fills for histogram</div>
  );

  // Bin slippage_bps into buckets
  const values = fills.map((f) => f.slippage_bps);
  const min = Math.min(...values); const max = Math.max(...values);
  const range = max - min || 1;
  const BINS = 12;
  const binSize = range / BINS;
  const bins = Array.from({ length: BINS }, (_, i) => ({
    label: (min + i * binSize).toFixed(1),
    count: 0,
  }));
  for (const v of values) {
    const idx = Math.min(Math.floor((v - min) / binSize), BINS - 1);
    bins[idx]!.count++;
  }
  const maxCount = Math.max(...bins.map((b) => b.count), 1);
  const W = 400; const H = 60;

  return (
    <div>
      <div className="text-[10px] text-slate-500 mb-1">Slippage Distribution (bps)</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 60 }}>
        {bins.map((b, i) => {
          const barH = (b.count / maxCount) * (H - 8);
          const x = (i / BINS) * W;
          const w = (W / BINS) - 1;
          const isNeg = parseFloat(b.label) < 0;
          return (
            <g key={i}>
              <rect x={x} y={H - barH - 4} width={w} height={barH} fill={isNeg ? '#00e676' : '#ff1744'} opacity={0.7} rx={1}>
                <title>{b.label} bps: {b.count} fills</title>
              </rect>
            </g>
          );
        })}
        <line x1={0} y1={H - 4} x2={W} y2={H - 4} stroke="#1e2d3d" strokeWidth={1} />
      </svg>
      <div className="flex justify-between text-[9px] text-slate-600 mt-0.5">
        <span>{min.toFixed(1)} bps</span>
        <span>0</span>
        <span>{max.toFixed(1)} bps</span>
      </div>
    </div>
  );
};

// ── MAE/MFE analysis ──────────────────────────────────────────────────────────

const MAEMFEPanel: React.FC<{ fills: FillEntry[] }> = ({ fills }) => {
  if (fills.length === 0) return null;

  const slippages = fills.map((f) => f.slippage_bps);
  const latencies = fills.map((f) => f.latency_ms);

  const mae = Math.min(...slippages);  // worst adverse slippage
  const mfe = Math.max(...slippages);  // best favorable slippage
  const avgSlip = slippages.reduce((a, b) => a + b, 0) / slippages.length;
  const avgLat  = latencies.reduce((a, b) => a + b, 0) / latencies.length;
  const p95Lat  = [...latencies].sort((a, b) => a - b)[Math.floor(latencies.length * 0.95)] ?? 0;

  const metrics = [
    { label: 'MAE (worst slippage)', value: `${mae.toFixed(2)} bps`, warn: mae < -5 },
    { label: 'MFE (best slippage)',  value: `${mfe.toFixed(2)} bps`, warn: false },
    { label: 'Avg Slippage',         value: `${avgSlip.toFixed(2)} bps`, warn: avgSlip > 3 },
    { label: 'Avg Latency',          value: `${avgLat.toFixed(1)} ms`, warn: avgLat > 100 },
    { label: 'P95 Latency',          value: `${p95Lat.toFixed(1)} ms`, warn: p95Lat > 200 },
    { label: 'Total Fills',          value: String(fills.length), warn: false },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      {metrics.map(({ label, value, warn }) => (
        <div key={label} className="flex flex-col gap-1 px-3 py-2.5 rounded-lg bg-[#0a0f1a] border border-[#1e2d3d]">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
          <span className={`text-[14px] font-bold tabular-nums ${warn ? 'text-[#ff1744]' : 'text-slate-200'}`}>{value}</span>
        </div>
      ))}
    </div>
  );
};

const PnLDashboard: React.FC = () => {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  const enabled  = hydrated && isAuth;

  const [page, setPage]         = useState(0);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  // ── Summary ────────────────────────────────────────────────────────────────
  const summaryQ = useQuery<PnLSummary>({
    queryKey:        ['pnl', 'summary'],
    queryFn:         async () => (await pnlApi.summary()).data as PnLSummary,
    enabled,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  // ── Equity curve ───────────────────────────────────────────────────────────
  const equityQ = useQuery<EquityPoint[]>({
    queryKey:        ['pnl', 'equity-curve'],
    queryFn:         async () => (await pnlApi.equityCurve()).data as EquityPoint[],
    enabled,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });

  // ── Drawdown curve ─────────────────────────────────────────────────────────
  const drawdownQ = useQuery<DrawdownPoint[]>({
    queryKey:        ['pnl', 'drawdown-curve'],
    queryFn:         async () => (await pnlApi.drawdownCurve()).data as DrawdownPoint[],
    enabled,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });

  // ── Trade log (paginated) ──────────────────────────────────────────────────
  const fillsQ = useQuery<FillEntry[]>({
    queryKey:        ['pnl', 'trade-log', page],
    queryFn:         async () =>
      (await pnlApi.tradeLog({ limit: PAGE_SIZE, offset: page * PAGE_SIZE })).data as FillEntry[],
    enabled,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  // ── Open positions ─────────────────────────────────────────────────────────
  const positionsQ = useQuery<OpenPosition[]>({
    queryKey:        ['pnl', 'open-positions'],
    queryFn:         async () => (await pnlApi.openPositions()).data as OpenPosition[],
    enabled,
    refetchInterval: 10_000,
    staleTime:       5_000,
  });

  // Track last successful refresh time
  useEffect(() => {
    if (summaryQ.dataUpdatedAt) {
      setLastUpdated(new Date(summaryQ.dataUpdatedAt).toLocaleTimeString());
    }
  }, [summaryQ.dataUpdatedAt]);

  const handleRefresh = useCallback(() => {
    summaryQ.refetch();
    equityQ.refetch();
    drawdownQ.refetch();
    fillsQ.refetch();
    positionsQ.refetch();
  }, [summaryQ, equityQ, drawdownQ, fillsQ, positionsQ]);

  const summary   = summaryQ.data ?? null;
  const fills     = fillsQ.data ?? [];
  const positions = positionsQ.data ?? [];
  const equityData = (equityQ.data ?? []).map((p) => ({
    ts: p.timestamp ? new Date(p.timestamp).toLocaleDateString() : '',
    v:  p.equity,
  }));
  const ddData = (drawdownQ.data ?? []).map((p) => ({
    ts: p.timestamp ? new Date(p.timestamp).toLocaleDateString() : '',
    dd: p.drawdown_pct,
  }));
  const totalFills = summary?.total_fills ?? 0;
  const totalPages = Math.ceil(totalFills / PAGE_SIZE);
  const isLoading  = summaryQ.isLoading || fillsQ.isLoading;
  const error      = summaryQ.error ?? fillsQ.error ?? positionsQ.error;

  return (
    <div className="px-3 py-3 sm:px-4 sm:py-4 md:px-6 md:py-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">

      <PageHeader
        title="P&L Dashboard"
        icon="💹"
        subtitle="Real fills from the live engine — no synthetic data"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Analytics', href: '/performance' },
          { label: 'P&L Dashboard' },
        ]}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <LiveEquityBadge equity={summary?.equity} />
            <Link to="/performance" className="flex items-center gap-1 px-3 py-1.5 text-[#4ade80] rounded-lg text-xs font-semibold" style={{ background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)', textDecoration: 'none' }}>📈 Performance</Link>
            <Link to="/tca"         className="flex items-center gap-1 px-3 py-1.5 text-[#a78bfa] rounded-lg text-xs font-semibold" style={{ background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.3)', textDecoration: 'none' }}>📊 TCA</Link>
            <Link to="/journal"     className="flex items-center gap-1 px-3 py-1.5 text-[#60a5fa] rounded-lg text-xs font-semibold" style={{ background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)', textDecoration: 'none' }}>📓 Journal</Link>
            <button onClick={handleRefresh} disabled={isLoading} className="flex items-center gap-2 px-3 py-1.5 bg-[#1e2d3d] hover:bg-[#243447] text-slate-300 rounded-lg text-xs transition-colors disabled:opacity-50">
              <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
              {lastUpdated ? `Updated ${lastUpdated}` : 'Refresh'}
            </button>
          </div>
        }
      />

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {(error as Error).message ?? 'Failed to load P&L data'}
        </div>
      )}

      {/* Backend note (e.g. "insufficient fills for Sharpe") */}
      {summary?.note && (
        <div className="flex items-center gap-3 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-400 text-xs">
          <AlertTriangle className="w-3 h-3 flex-shrink-0" />
          {summary.note}
        </div>
      )}

      {/* Headline stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Equity"
          value={summary ? fmtUSD(summary.equity) : '—'}
          sub={summary ? `Started ${fmtUSD(summary.starting_equity)}` : undefined}
          icon={TrendingUp}
          color={summary && summary.total_return_pct >= 0 ? 'green' : 'red'}
        />
        <StatCard
          label="Total Return"
          value={summary ? fmtPctRaw(summary.total_return_pct) : '—'}
          sub={summary ? `${summary.total_fills} fills` : undefined}
          icon={Activity}
          color={summary && summary.total_return_pct >= 0 ? 'green' : 'red'}
        />
        <StatCard
          label="Sharpe Ratio"
          value={summary?.sharpe_ratio != null ? fmtNum(summary.sharpe_ratio, 3) : '—'}
          sub={
            summary?.sharpe_ratio == null
              ? `Need ${Math.max(0, 30 - (summary?.total_fills ?? 0))} more fills`
              : 'Annualised'
          }
          icon={TrendingUp}
          color={
            summary?.sharpe_ratio == null ? 'amber'
            : summary.sharpe_ratio >= 1.5  ? 'green'
            : summary.sharpe_ratio >= 0.5  ? 'amber'
            : 'red'
          }
        />
        <StatCard
          label="Max Drawdown"
          value={summary ? `${fmtNum(summary.max_drawdown_pct, 2)}%` : '—'}
          sub={summary ? `Current: ${fmtNum(summary.current_drawdown_pct, 2)}%` : undefined}
          icon={TrendingDown}
          color={summary && summary.max_drawdown_pct > 10 ? 'red' : 'amber'}
          warn={summary != null && summary.max_drawdown_pct > 10}
        />
        <StatCard
          label="Win Rate"
          value={summary?.win_rate != null ? `${fmtNum(summary.win_rate, 1)}%` : '—'}
          sub={summary?.win_rate == null ? 'Need 30+ fills' : `${summary.total_fills} fills`}
          icon={Shield}
          color={summary?.win_rate != null && summary.win_rate >= 55 ? 'green' : 'amber'}
        />
        <StatCard
          label="Open Positions"
          value={summary ? String(summary.open_positions) : '—'}
          sub="Live"
          icon={Activity}
          color="blue"
        />
        <StatCard
          label="Avg Slippage"
          value={summary ? `${fmtNum(summary.avg_slippage_bps, 2)} bps` : '—'}
          sub="Per fill"
          icon={TrendingDown}
          color={summary && summary.avg_slippage_bps > 5 ? 'red' : 'green'}
        />
        <StatCard
          label="Avg Latency"
          value={summary ? `${fmtNum(summary.avg_latency_ms, 1)} ms` : '—'}
          sub="Order → fill"
          icon={Clock}
          color="purple"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-[#0d1421] rounded-lg border border-[#1e2d3d] p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-slate-200">Equity Curve</h3>
            <span className="text-xs text-slate-500">Account currency</span>
          </div>
          <EquitySparkline data={equityData} />
        </div>
        <div className="bg-[#0d1421] rounded-lg border border-[#1e2d3d] p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-slate-200">Drawdown Curve</h3>
            <span className="text-xs text-slate-500">% from peak equity</span>
          </div>
          <DrawdownChart data={ddData} />
        </div>
      </div>

      {/* Open positions */}
      {positions.length > 0 && (
        <div className="bg-[#0d1421] rounded-lg border border-[#1e2d3d] overflow-hidden">
          <div className="px-5 py-4 border-b border-[#1e2d3d]">
            <h3 className="font-semibold text-slate-200">Open Positions ({positions.length})</h3>
          </div>
          <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="text-xs text-slate-500 uppercase border-b border-[#1e2d3d]">
                  {['Symbol', 'Direction', 'Qty', 'Entry', 'Current', 'Unrealised P&L', 'SL', 'TP', 'Opened'].map((h) => (
                    <th key={h} className="px-3 py-2.5 text-left font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((pos, i) => {
                  const isLong = pos.direction.toLowerCase().includes('long') || pos.direction.toLowerCase() === 'buy';
                  return (
                    <tr key={i} className="border-b border-[#1e2d3d]/50 hover:bg-[#1e2d3d]/30">
                      <td className="px-4 py-3 font-mono text-amber-400">{pos.symbol}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                        }`}>
                          {pos.direction.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono">{fmtNum(pos.quantity, 4)}</td>
                      <td className="px-4 py-3 font-mono">{fmtPrice(pos.entry_price, 4)}</td>
                      <td className="px-4 py-3 font-mono">{pos.current_price != null ? fmtPrice(pos.current_price, 4) : '—'}</td>
                      <td className={`px-4 py-3 font-mono font-semibold ${
                        pos.unrealised_pnl == null ? 'text-slate-500'
                        : pos.unrealised_pnl >= 0  ? 'text-emerald-400'
                        : 'text-red-400'
                      }`}>
                        {pos.unrealised_pnl != null ? fmtUSD(pos.unrealised_pnl) : '—'}
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-400">{pos.stop_loss != null ? fmtPrice(pos.stop_loss, 4) : '—'}</td>
                      <td className="px-4 py-3 font-mono text-slate-400">{pos.take_profit != null ? fmtPrice(pos.take_profit, 4) : '—'}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs">{fmtDateTime(pos.opened_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Auditable trade log */}
      <div className="bg-[#0d1421] rounded-lg border border-[#1e2d3d] overflow-hidden">
        <div className="px-5 py-4 border-b border-[#1e2d3d] flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-slate-200">Auditable Trade Log</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Every fill linked to lineage store — fill_id → signal → model version
            </p>
          </div>
          <span className="text-xs text-slate-500">{totalFills} total fills</span>
        </div>

        {fills.length === 0 ? (
          <div className="px-5 py-12 text-center">
            {isLoading ? (
              <span className="text-slate-500 text-sm">Loading trade log…</span>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <span className="text-3xl opacity-30">📋</span>
                <p className="text-slate-400 text-sm font-medium">No fills yet</p>
                <p className="text-slate-600 text-xs max-w-xs">The trade log populates after your first executed order.</p>
                <Link to="/trade" className="mt-1 px-4 py-2 bg-blue-600/20 border border-blue-500/30 text-blue-400 rounded-lg text-xs font-semibold hover:bg-blue-600/30 transition-colors" style={{ textDecoration: 'none' }}>
                  ⚡ Place First Trade
                </Link>
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
              <table className="w-full text-sm min-w-[700px]">
                <thead>
                  <tr className="text-xs text-slate-500 uppercase border-b border-[#1e2d3d]">
                    {['Time', 'Symbol', 'Dir', 'Qty', 'Fill Price', 'Expected', 'Slippage', 'Latency', 'Broker', 'Fill ID'].map((h) => (
                      <th key={h} className="px-3 py-2.5 text-left font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {fills.map((f) => (
                    <tr key={f.fill_id} className="border-b border-[#1e2d3d]/50 hover:bg-[#1e2d3d]/30">
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                        {fmtDateTime(f.filled_at)}
                      </td>
                      <td className="px-4 py-3 font-mono text-amber-400">{f.symbol}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          f.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                        }`}>
                          {f.direction.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono">{fmtNum(f.quantity, 4)}</td>
                      <td className="px-4 py-3 font-mono">{fmtPrice(f.fill_price, 4)}</td>
                      <td className="px-4 py-3 font-mono text-slate-400">{fmtPrice(f.expected_price, 4)}</td>
                      <td className={`px-4 py-3 font-mono text-xs ${
                        Math.abs(f.slippage_bps) > 5 ? 'text-amber-400' : 'text-slate-400'
                      }`}>
                        {fmtNum(f.slippage_bps, 2)} bps
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">
                        {fmtNum(f.latency_ms, 1)} ms
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{f.broker}</td>
                      <td
                        className="px-4 py-3 font-mono text-xs text-slate-600 truncate max-w-[120px]"
                        title={f.fill_id}
                      >
                        {f.fill_id.slice(0, 12)}…
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-5 py-3 border-t border-[#1e2d3d] flex items-center justify-between text-sm text-slate-400">
                <span>Page {page + 1} of {totalPages}</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="p-1.5 rounded hover:bg-[#1e2d3d] disabled:opacity-30"
                    aria-label="Previous page"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    className="p-1.5 rounded hover:bg-[#1e2d3d] disabled:opacity-30"
                    aria-label="Next page"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {/* MAE/MFE analysis */}
        {fills.length > 0 && (
          <div className="rounded-xl border border-[#1e2d3d] bg-[#0d1421] p-4">
            <h3 className="text-[13px] font-semibold text-slate-200 mb-3">MAE / MFE Analysis</h3>
            <MAEMFEPanel fills={fills} />
          </div>
        )}

        {/* Trade distribution histogram */}
        {fills.length >= 5 && (
          <div className="rounded-xl border border-[#1e2d3d] bg-[#0d1421] p-4">
            <h3 className="text-[13px] font-semibold text-slate-200 mb-3">Trade Distribution</h3>
            <TradeHistogram fills={fills} />
          </div>
        )}

        <CrossLinkBar title="Related" style={{ marginTop: 8 }} links={[
          { label: '📊 Performance',    href: '/performance',     color: '#4ade80' },
          { label: '💼 Portfolio',       href: '/portfolio',       color: '#60a5fa' },
          { label: '📊 TCA',            href: '/tca',             color: '#a78bfa' },
          { label: '📓 Trade Journal',  href: '/journal',         color: '#fbbf24' },
          { label: '⚡ Trade',          href: '/trade',           color: '#34d399' },
          { label: '🛡️ Prop Tracker',  href: '/prop-firm',       color: '#f97316' },
        ]}/>
      </div>
    </div>
  );
};

export default PnLDashboard;
