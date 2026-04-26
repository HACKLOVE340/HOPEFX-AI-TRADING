/**
 * Trade page — real-time multi-symbol price board with integrated order entry.
 *
 * Layout:
 *   - Account metrics bar
 *   - Symbol selector strip (live bid/ask/mid/change% + sparkline per symbol)
 *   - Order entry (left) + Symbol positions (right)
 *   - Bottom tabbed section: All Positions | Trade History
 *
 * Data sources:
 *   1. Live WebSocket feed → Zustand store (prices, priceHistory, positions)
 *   2. REST polling fallback via usePositions / useAccount
 *   3. TanStack Query for trade history
 *
 * Wires to:
 *   POST   /api/trading/orders
 *   GET    /api/trading/trades
 *   DELETE /api/trading/positions/{id}
 *   DELETE /api/trading/positions
 */

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useStore, selectWsStatus, selectPriceHistory, useHasHydrated, selectIsAuth } from '../store';
import { usePositions, useAccount } from '../hooks/useOrchestratorData';
import { tradingApi } from '../hooks/useApi';
import { OrderEntryForm } from '../components/panels/OrderEntryForm';
import { PositionsTable } from '../components/panels/PositionsTable';
import { Sparkline } from '../components/ui/Sparkline';
import { PanelSkeleton } from '../components/ui/Skeleton';
import { cn, fmtPrice, fmtPnl, fmtDateTime } from '../lib/utils';
import type { PriceTick } from '../types';

// ── Constants ─────────────────────────────────────────────────────────────────

const SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD', 'ETH/USD'];

// ── Types ─────────────────────────────────────────────────────────────────────

interface ClosedTrade {
  id: string;
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  exit_price: number;
  realized_pnl: number;
  opened_at: string;
  closed_at: string;
  duration_minutes?: number;
}

// ── Symbol card ───────────────────────────────────────────────────────────────

interface SymbolCardProps {
  symbol:   string;
  tick:     PriceTick | undefined;
  history:  PriceTick[];
  selected: boolean;
  onClick:  () => void;
}

const SymbolCard: React.FC<SymbolCardProps> = ({ symbol, tick, history, selected, onClick }) => {
  const change    = tick?.change_pct ?? 0;
  const isUp      = change >= 0;
  const sparkData = history.slice(-40).map((t) => t.mid);

  return (
    <button
      onClick={onClick}
      className={cn(
        'flex flex-col gap-1.5 px-3 py-2.5 rounded-lg border text-left transition-all',
        'min-w-[148px] flex-shrink-0',
        selected
          ? 'bg-[#1e3a5f] border-[#3b82f6] shadow-[0_0_0_1px_#3b82f6]'
          : 'bg-[#0d1421] border-[#1e2d3d] hover:border-[#334155]',
      )}
    >
      {/* Symbol + change badge */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-bold text-slate-200 tracking-wide">{symbol}</span>
        {tick && (
          <span
            className={cn(
              'text-[10px] font-semibold px-1.5 py-0.5 rounded',
              isUp ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]',
            )}
          >
            {isUp ? '+' : ''}{change.toFixed(2)}%
          </span>
        )}
      </div>

      {/* Mid price — prominent */}
      {tick ? (
        <span className="text-[15px] font-bold tabular-nums text-slate-100 leading-none">
          {fmtPrice(tick.mid)}
        </span>
      ) : (
        <span className="text-[12px] text-slate-600">No feed</span>
      )}

      {/* Bid / Ask / Spread row */}
      {tick && (
        <div className="flex gap-3 text-[10px] tabular-nums">
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] text-slate-600 uppercase">Bid</span>
            <span className="text-[#ff3b5c] font-semibold">{fmtPrice(tick.bid)}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] text-slate-600 uppercase">Ask</span>
            <span className="text-[#00e676] font-semibold">{fmtPrice(tick.ask)}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] text-slate-600 uppercase">Sprd</span>
            <span className="text-slate-500">{fmtPrice(tick.ask - tick.bid, 3)}</span>
          </div>
        </div>
      )}

      {/* Sparkline */}
      {sparkData.length >= 2 && (
        <Sparkline data={sparkData} width={132} height={22} />
      )}
    </button>
  );
};

// ── Account bar ───────────────────────────────────────────────────────────────

const AccountBar: React.FC = () => {
  const { data: account } = useAccount();
  const wsStatus = useStore(selectWsStatus);

  if (!account) return null;

  const equity     = account.equity      ?? account.balance ?? 0;
  const balance    = account.balance     ?? 0;
  const margin     = account.margin_used ?? 0;
  const freeMargin = account.margin_free ?? (equity - margin);
  const pnl        = account.total_pnl   ?? 0;

  return (
    <div className="flex flex-wrap gap-4 px-4 py-2.5 rounded-lg bg-[#0d1421] border border-[#1e2d3d] text-[11px]">
      {[
        { label: 'Balance',      value: `$${balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,    color: 'text-slate-200' },
        { label: 'Equity',       value: `$${equity.toLocaleString('en-US',  { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,    color: 'text-slate-200' },
        { label: 'Free Margin',  value: `$${freeMargin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: 'text-slate-300' },
        {
          label: 'Unrealized P&L',
          value: `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`,
          color: pnl >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]',
        },
        {
          label: 'Margin Level',
          value: account.margin_level != null ? `${account.margin_level.toFixed(0)}%` : '—',
          color:
            (account.margin_level ?? 300) > 200 ? 'text-[#00e676]' :
            (account.margin_level ?? 300) > 100 ? 'text-[#ffb800]' : 'text-[#ff1744]',
        },
      ].map(({ label, value, color }) => (
        <div key={label} className="flex flex-col gap-0.5">
          <span className="text-[9px] uppercase tracking-wider text-slate-500">{label}</span>
          <span className={cn('font-semibold tabular-nums', color)}>{value}</span>
        </div>
      ))}

      <div className="ml-auto flex items-center gap-1.5">
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full',
            wsStatus === 'connected'  ? 'bg-[#00e676] animate-pulse' :
            wsStatus === 'connecting' ? 'bg-[#ffb800]' : 'bg-[#ff1744]',
          )}
        />
        <span className="text-[10px] text-slate-500 capitalize">{wsStatus}</span>
      </div>
    </div>
  );
};

// ── Trade history table ────────────────────────────────────────────────────────

function TradeHistoryTab() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  const { data, isLoading, isError } = useQuery<ClosedTrade[]>({
    queryKey: ['recent-trades-tab'],
    queryFn: async () => {
      const r   = await tradingApi.trades({ limit: 30 });
      const raw = r.data as ClosedTrade[] | { trades?: ClosedTrade[] };
      return Array.isArray(raw) ? raw : (raw.trades ?? []);
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  if (isLoading) return <div className="p-4"><PanelSkeleton rows={5} /></div>;
  if (isError)   return <div className="p-4 text-[11px] text-[#ff1744]">Failed to load trade history</div>;
  if (!data?.length) return (
    <div className="flex items-center justify-center h-20 text-slate-600 text-[12px]">
      No closed trades yet
    </div>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-[#1e2d3d]">
            {['Symbol','Side','Size','Entry','Exit','P&L','Opened','Closed','Duration'].map((h) => (
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
          {data.map((t) => {
            const isLong = t.side === 'long' || t.side === 'buy';
            const pnlPos = t.realized_pnl >= 0;
            return (
              <tr key={t.id} className="border-b border-[#0d1421] hover:bg-[#1e2d3d]/30 transition-colors">
                <td className="px-3 py-2 font-semibold text-slate-200 whitespace-nowrap">{t.symbol}</td>
                <td className="px-3 py-2">
                  <span className={cn(
                    'px-1.5 py-0.5 rounded text-[10px] font-bold uppercase',
                    isLong ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]',
                  )}>
                    {isLong ? '▲ Long' : '▼ Short'}
                  </span>
                </td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{t.size}</td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{fmtPrice(t.entry_price)}</td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{fmtPrice(t.exit_price)}</td>
                <td className="px-3 py-2">
                  <span className={cn('font-semibold tabular-nums', pnlPos ? 'text-[#00e676]' : 'text-[#ff1744]')}>
                    {fmtPnl(t.realized_pnl)}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDateTime(t.opened_at)}</td>
                <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDateTime(t.closed_at)}</td>
                <td className="px-3 py-2 text-slate-500 tabular-nums">
                  {t.duration_minutes != null ? `${t.duration_minutes}m` : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Bottom section (tabbed) ───────────────────────────────────────────────────

type BottomTab = 'all-positions' | 'history';

function BottomSection() {
  const [tab, setTab] = useState<BottomTab>('all-positions');

  const tabs: { id: BottomTab; label: string }[] = [
    { id: 'all-positions', label: 'All Positions' },
    { id: 'history',       label: 'Trade History' },
  ];

  return (
    <div className="bg-[#0d1421] border border-[#1e2d3d] rounded-lg overflow-hidden">
      <div className="flex items-center gap-1 px-3 py-2 border-b border-[#1e2d3d]">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              'px-3 py-1 rounded text-[11px] font-semibold border transition-colors',
              tab === id
                ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
                : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div>
        {tab === 'all-positions' && <PositionsTable />}
        {tab === 'history'       && <TradeHistoryTab />}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const Trade: React.FC = () => {
  const [selectedSymbol, setSelectedSymbol] = useState('XAU/USD');
  const prices      = useStore((s) => s.prices);
  const allHistory  = useStore((s) => s.priceHistory);

  usePositions();

  return (
    <div className="flex flex-col gap-4 p-4 min-h-screen bg-[#0a0f1a]">

      {/* Page header */}
      <div>
        <h1 className="text-[18px] font-bold text-slate-100">Trade</h1>
        <p className="text-[12px] text-slate-500 mt-0.5">
          Real-time execution — market, limit and stop orders
        </p>
      </div>

      {/* Account metrics */}
      <AccountBar />

      {/* Symbol selector strip */}
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin scrollbar-thumb-[#1e2d3d]">
        {SYMBOLS.map((sym) => (
          <SymbolCard
            key={sym}
            symbol={sym}
            tick={prices[sym]}
            history={allHistory[sym] ?? []}
            selected={selectedSymbol === sym}
            onClick={() => setSelectedSymbol(sym)}
          />
        ))}
      </div>

      {/* Order entry + symbol positions */}
      <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-4 items-start">
        <OrderEntryForm
          symbol={selectedSymbol}
          onOrderPlaced={() => {/* positions invalidated inside OrderEntryForm */}}
        />
        <PositionsTable symbol={selectedSymbol} />
      </div>

      {/* Bottom: all positions + trade history tabs */}
      <BottomSection />
    </div>
  );
};

export default Trade;
