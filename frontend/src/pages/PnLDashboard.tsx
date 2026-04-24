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

import React, { useCallback, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  TrendingUp, TrendingDown, Activity, Shield,
  Clock, RefreshCw, AlertTriangle, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { api } from '../hooks/useApi';
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

// ── Mini sparkline chart (SVG) ────────────────────────────────────────────────

function MiniChart({
  data,
  color,
  label,
}: {
  data: number[];
  color: string;
  label: string;
}) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-600 text-sm">
        Not enough data
      </div>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 400;
  const h = 120;
  const pad = 8;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x},${y}`;
  });

  const polyline = points.join(' ');
  const area = `${pad},${h - pad} ${polyline} ${w - pad},${h - pad}`;

  return (
    <div>
      <div className="text-xs text-slate-500 mb-2">{label}</div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-32" preserveAspectRatio="none">
        <defs>
          <linearGradient id={`grad-${label}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <polygon points={area} fill={`url(#grad-${label})`} />
        <polyline points={polyline} fill="none" stroke={color} strokeWidth="1.5" />
      </svg>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const PnLDashboard: React.FC = () => {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  const enabled  = hydrated && isAuth;

  const [page, setPage]         = useState(0);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  // ── Summary ────────────────────────────────────────────────────────────────
  const summaryQ = useQuery<PnLSummary>({
    queryKey:        ['pnl', 'summary'],
    queryFn:         async () => (await api.get<PnLSummary>('/pnl/summary')).data,
    enabled,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  // ── Equity curve ───────────────────────────────────────────────────────────
  const equityQ = useQuery<EquityPoint[]>({
    queryKey:        ['pnl', 'equity-curve'],
    queryFn:         async () => (await api.get<EquityPoint[]>('/pnl/equity-curve')).data,
    enabled,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });

  // ── Drawdown curve ─────────────────────────────────────────────────────────
  const drawdownQ = useQuery<DrawdownPoint[]>({
    queryKey:        ['pnl', 'drawdown-curve'],
    queryFn:         async () => (await api.get<DrawdownPoint[]>('/pnl/drawdown-curve')).data,
    enabled,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });

  // ── Trade log (paginated) ──────────────────────────────────────────────────
  const fillsQ = useQuery<FillEntry[]>({
    queryKey:        ['pnl', 'trade-log', page],
    queryFn:         async () =>
      (await api.get<FillEntry[]>(`/pnl/trade-log?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`)).data,
    enabled,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  // ── Open positions ─────────────────────────────────────────────────────────
  const positionsQ = useQuery<OpenPosition[]>({
    queryKey:        ['pnl', 'open-positions'],
    queryFn:         async () => (await api.get<OpenPosition[]>('/pnl/open-positions')).data,
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

  const summary    = summaryQ.data ?? null;
  const fills      = fillsQ.data ?? [];
  const positions  = positionsQ.data ?? [];
  const equityData = (equityQ.data ?? []).map((p) => p.equity);
  const ddData     = (drawdownQ.data ?? []).map((p) => p.drawdown_pct);
  const totalFills = summary?.total_fills ?? 0;
  const totalPages = Math.ceil(totalFills / PAGE_SIZE);
  const isLoading  = summaryQ.isLoading || fillsQ.isLoading;
  const error      = summaryQ.error ?? fillsQ.error ?? positionsQ.error;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Live P&amp;L Dashboard</h1>
          <p className="text-sm text-slate-400 mt-1">
            Real fills from the live engine — no synthetic data
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isLoading}
          className="flex items-center gap-2 px-4 py-2 bg-[#1e2d3d] hover:bg-[#243447] text-slate-300 rounded-lg text-sm transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          {lastUpdated ? `Updated ${lastUpdated}` : 'Refresh'}
        </button>
      </div>

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
          <MiniChart data={equityData} color="#00e676" label="Equity ($)" />
        </div>
        <div className="bg-[#0d1421] rounded-lg border border-[#1e2d3d] p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-slate-200">Drawdown</h3>
            <span className="text-xs text-slate-500">% from peak</span>
          </div>
          <MiniChart data={ddData} color="#ff1744" label="Drawdown (%)" />
        </div>
      </div>

      {/* Open positions */}
      {positions.length > 0 && (
        <div className="bg-[#0d1421] rounded-lg border border-[#1e2d3d] overflow-hidden">
          <div className="px-5 py-4 border-b border-[#1e2d3d]">
            <h3 className="font-semibold text-slate-200">Open Positions ({positions.length})</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 uppercase border-b border-[#1e2d3d]">
                  {['Symbol', 'Direction', 'Qty', 'Entry', 'Current', 'Unrealised P&L', 'SL', 'TP', 'Opened'].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
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
          <div className="px-5 py-12 text-center text-slate-500 text-sm">
            {isLoading
              ? 'Loading trade log…'
              : 'No fills yet. The trade log will populate after the first executed order.'}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 uppercase border-b border-[#1e2d3d]">
                    {['Time', 'Symbol', 'Dir', 'Qty', 'Fill Price', 'Expected', 'Slippage', 'Latency', 'Broker', 'Fill ID'].map((h) => (
                      <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
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
      </div>
    </div>
  );
};

export default PnLDashboard;
