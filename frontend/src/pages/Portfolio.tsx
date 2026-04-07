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

import React from 'react';
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

  if (!perf) {
    return (
      <Panel title="Performance">
        <PanelSkeleton rows={3} />
      </Panel>
    );
  }

  const metrics: { label: string; value: string; positive?: boolean | null }[] = [
    { label: 'Total Return',   value: fmtPct(perf.total_return_pct),  positive: perf.total_return_pct >= 0 ? true : false },
    { label: 'Sharpe Ratio',   value: fmtRatio(perf.sharpe_ratio),    positive: perf.sharpe_ratio >= 1 ? true : perf.sharpe_ratio < 0 ? false : null },
    { label: 'Sortino Ratio',  value: fmtRatio(perf.sortino_ratio),   positive: perf.sortino_ratio >= 1 ? true : perf.sortino_ratio < 0 ? false : null },
    { label: 'Max Drawdown',   value: fmtPct(-Math.abs(perf.max_drawdown_pct)), positive: false },
    { label: 'Win Rate',       value: fmtPct(perf.win_rate * 100),    positive: perf.win_rate >= 0.5 ? true : false },
    { label: 'Profit Factor',  value: fmtRatio(perf.profit_factor),   positive: perf.profit_factor >= 1 ? true : false },
    { label: 'Total Trades',   value: String(perf.total_trades) },
    { label: 'Avg Trade P&L',  value: `$${perf.avg_trade_pnl.toFixed(2)}`, positive: perf.avg_trade_pnl >= 0 ? true : false },
    { label: 'Best Trade',     value: `+$${perf.best_trade.toFixed(2)}`,   positive: true },
    { label: 'Worst Trade',    value: `-$${Math.abs(perf.worst_trade).toFixed(2)}`, positive: false },
    { label: 'CVaR 95%',       value: `$${perf.cvar_95.toFixed(2)}`,  positive: false },
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

const TradeHistory: React.FC = () => {
  const { data: trades, isLoading, isError } = useQuery<TradeRecord[]>({
    queryKey: ['trades', 'history'],
    queryFn:  async () => {
      const res = await tradingApi.trades(100);
      return res.data as TradeRecord[];
    },
    staleTime:       60_000,
    refetchInterval: 60_000,
  });

  return (
    <Panel title="Trade History" noPad>
      {isLoading && <PanelSkeleton rows={5} />}

      {isError && (
        <div className="px-4 py-6 text-center text-[12px] text-slate-500">
          Could not load trade history.
        </div>
      )}

      {!isLoading && !isError && (!trades || trades.length === 0) && (
        <div className="flex flex-col items-center justify-center py-10 gap-2">
          <span className="text-2xl opacity-30">📋</span>
          <span className="text-[12px] text-slate-500">No closed trades yet</span>
        </div>
      )}

      {trades && trades.length > 0 && (
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
              {trades.map((t) => {
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

// ── Page ──────────────────────────────────────────────────────────────────────

const Portfolio: React.FC = () => {
  // Prefetch all data on mount
  useEquityCurve();
  usePositions();

  return (
    <div className="flex flex-col gap-4 p-4 min-h-screen bg-[#0a0f1a]">

      {/* Page header */}
      <div>
        <h1 className="text-[18px] font-bold text-slate-100">Portfolio</h1>
        <p className="text-[12px] text-slate-500 mt-0.5">
          Balances, equity curve, and trade history
        </p>
      </div>

      {/* Account balances */}
      <AccountSummary />

      {/* Equity curve */}
      <EquityCurveChart />

      {/* Performance metrics */}
      <PerformanceMetrics />

      {/* Open positions */}
      <PositionsTable />

      {/* Closed trade history */}
      <TradeHistory />
    </div>
  );
};

export default Portfolio;
